"""ingest_mail must not store a message whose file is still empty.

write_mail creates the view under `.polyctl/mail/write.lock` and writes the body before it lets
the lock go. ingest_mail takes that same lock for the read and the store, and leaves an empty
view for the next pass, so an empty body is never recorded under a digest the id then keeps.
"""
import hashlib
import json
import os
import threading

from polyctl import lib as A
from polyctl import mcp, storage


NAME = "20260916-0900-fable-to-kiro-NOTE-a.md"
BODY = b"# a\n\nthe full body\n"


def _append_only(project):
    root = project["root"]
    stored = {key: value for key, value in project.items() if key != "root"}
    stored["mail"] = {"store": "append-only"}
    with open(os.path.join(root, ".polyctl", "config.json"), "w", encoding="utf-8") as fh:
        json.dump(stored, fh)
    return root, A.load_config(root)


def _view(root, name, body):
    path = os.path.join(root, "agent-mail", name)
    with open(path, "wb") as fh:
        fh.write(body)
    return path


def _digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _messages(root):
    return [row for row in A.mail_store_rows(root) if row.get("event") == "message"]


def test_a_fully_written_message_is_stored_with_its_digest(project):
    root, cfg = _append_only(project)
    _view(root, NAME, BODY)

    assert A.ingest_mail(root, cfg) == [NAME]

    rows = _messages(root)
    assert [row["id"] for row in rows] == [NAME]
    assert rows[0]["digest"] == _digest(BODY)
    assert open(A._store_path(root, NAME), "rb").read() == BODY


def test_an_empty_view_is_left_until_the_body_is_written(project):
    """A writer has created the file and not the body. Storing that empty read would keep the id forever."""
    root, cfg = _append_only(project)
    path = _view(root, NAME, b"")

    assert A.ingest_mail(root, cfg) == []
    assert _messages(root) == []
    assert not os.path.exists(A._store_path(root, NAME))

    with open(path, "wb") as fh:
        fh.write(BODY)
    assert A.ingest_mail(root, cfg) == [NAME]

    rows = _messages(root)
    assert [row["id"] for row in rows] == [NAME]
    assert rows[0]["digest"] == _digest(BODY)
    assert open(A._store_path(root, NAME), "rb").read() == BODY


def test_ingest_mail_waits_until_the_write_lock_is_released(project, monkeypatch):
    """The write lock is held, as another process holds it while write_mail fills the file. ingest_mail
    runs on a thread and stores the message only after that hold ends."""
    root, cfg = _append_only(project)
    _view(root, NAME, BODY)
    lock = os.path.join(root, ".polyctl", "mail", "write.lock")
    holding, release = threading.Event(), threading.Event()
    waiting, finished = threading.Event(), threading.Event()
    result, errors = [], []

    def hold():
        try:
            with storage._exclusive_lock(lock):
                holding.set()
                release.wait(timeout=30)
        except BaseException as exc:
            errors.append(exc)

    def run():
        try:
            result.append(A.ingest_mail(root, cfg))
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()

    worker = threading.Thread(target=run, daemon=True)
    real_sleep = storage.time.sleep

    def notice(seconds):
        # Raised from the lock's own wait, while this thread is blocked on write.lock.
        if threading.current_thread() is worker:
            waiting.set()
        real_sleep(seconds)

    monkeypatch.setattr(storage.time, "sleep", notice)
    holder = threading.Thread(target=hold, daemon=True)
    holder.start()
    try:
        assert holding.wait(timeout=30), errors
        worker.start()
        assert waiting.wait(timeout=30), errors
        assert not finished.is_set()
        assert _messages(root) == []
        release.set()
        assert finished.wait(timeout=30), errors
    finally:
        release.set()
        holder.join(timeout=30)
        if worker.ident is not None:
            worker.join(timeout=30)

    assert errors == [] and result == [[NAME]]
    rows = _messages(root)
    assert [row["id"] for row in rows] == [NAME]
    assert rows[0]["digest"] == _digest(BODY)


def test_polyctl_ack_in_append_only_mode_records_the_handled_row(project):
    root, cfg = _append_only(project)
    implementer, architect = A.mail_names(cfg)
    name = f"20260916-0902-{architect}-to-{implementer}-DECISION-go.md"
    assert A.write_mail(root, cfg, name, "# go\n\nApply it.\n",
                        {"kind": "decision", "from": architect, "to": implementer}) == name

    assert mcp.call("polyctl_ack", {"id": name, "outcome": "applied"}, cfg, False, "implementer") == {
        "acknowledged": name, "outcome": "applied"}

    handled = [row for row in A.mail_store_rows(root) if row.get("event") == "handled"]
    assert [(row["id"], row["by"], row["outcome"]) for row in handled] == [(name, "implementer", "applied")]
    assert name not in A.unhandled_messages(root)
