"""MCP inbox, ack, report, and status keep the mailbox inside the project.

`polyctl_inbox`, `polyctl_ack`, `polyctl_report`, and `polyctl_status` joined the project root, the
config's `mailbox`, and a file name with no containment or regular-file check. A `mailbox` of
`../elsewhere`, an absolute path, a symlink pointing outside the project, or a mail entry that is a
symlink, FIFO, or directory could be read, listed, opened, or removed. The handler is `mcp.call`,
as the role and leads tests drive it.
"""
import json
import os
import stat
from pathlib import Path

import pytest

from polyctl import lib as A, mcp

OUTSIDE = "the mailbox must be a folder inside the project"


@pytest.fixture(autouse=True)
def _no_host_process_scan(monkeypatch):
    monkeypatch.setattr(A, "agent_pids", lambda *a, **k: [])


def _config(project, mailbox, store=None):
    """The fixture's project with `mailbox` (and optional `mail.store`) written into its config."""
    root = project["root"]
    stored = {key: value for key, value in project.items() if key != "root"}
    stored["mailbox"] = mailbox
    if store is not None:
        stored["mail"] = {"store": store}
    Path(root, ".polyctl", "config.json").write_text(json.dumps(stored), encoding="utf-8")
    cfg = A.load_config(root)
    assert cfg["mailbox"] == mailbox
    return cfg


def _addressed(project, stamp, slug, text):
    """(name, body) of one message addressed to the implementer."""
    implementer, architect = A.mail_names(project)
    name = f"{stamp}-{architect}-to-{implementer}-DECISION-{slug}.md"
    return name, f"# {slug}\n\n{text}\n"


def _report_name(project, stamp, slug, kind="STATUS"):
    """Filename of one report written by the implementer to the architect."""
    implementer, architect = A.mail_names(project)
    return f"{stamp}-{implementer}-to-{architect}-{kind}-{slug}.md"


def test_inbox_lists_a_message_addressed_to_the_implementer(project):
    root = Path(project["root"])
    name, body = _addressed(project, "20261120-0900", "go", "Apply it, then acknowledge it.")
    (root / "agent-mail" / name).write_text(body, encoding="utf-8")

    reply = mcp.call("polyctl_inbox", {}, project, False, "implementer")

    assert reply["messages"] == [{"id": name, "body": body}]
    assert reply["count"] == 1
    assert "polyctl_ack" in reply["note"]
    assert set(reply) == {"messages", "count", "note"}


def test_inbox_refuses_a_mailbox_that_resolves_outside_the_project(project):
    root = Path(project["root"])
    elsewhere = root.parent / "elsewhere"
    elsewhere.mkdir()
    name, body = _addressed(project, "20261120-0901", "outside", "This file stands outside the project.")
    (elsewhere / name).write_text(body, encoding="utf-8")
    cfg = _config(project, "../elsewhere")

    reply = mcp.call("polyctl_inbox", {}, cfg, False, "implementer")

    assert reply == {"error": OUTSIDE}
    assert body not in json.dumps(reply)
    assert (elsewhere / name).read_text(encoding="utf-8") == body


def test_inbox_refuses_an_absolute_mailbox_and_project_root(project):
    root = Path(project["root"])
    elsewhere = root.parent / "elsewhere"
    elsewhere.mkdir()
    name, body = _addressed(project, "20261120-0902", "absolute", "This file stands outside the project.")
    (elsewhere / name).write_text(body, encoding="utf-8")
    cfg = _config(project, str(elsewhere.resolve()))

    reply = mcp.call("polyctl_inbox", {}, cfg, False, "implementer")

    assert reply == {"error": OUTSIDE}
    assert body not in json.dumps(reply)
    assert (elsewhere / name).read_text(encoding="utf-8") == body

    # Absolute is refused even when the path is the project's own mailbox.
    own, own_body = _addressed(project, "20261120-0903", "own", "Apply it, then acknowledge it.")
    (root / "agent-mail" / own).write_text(own_body, encoding="utf-8")
    inside = _config(project, str((root / "agent-mail").resolve()))

    owned = mcp.call("polyctl_inbox", {}, inside, False, "implementer")

    assert owned == {"error": OUTSIDE}
    assert own_body not in json.dumps(owned)
    assert (root / "agent-mail" / own).read_text(encoding="utf-8") == own_body

    # Project root itself ('.') or empty string is not a mailbox folder.
    for bad in (".", ""):
        bad_cfg = dict(project, mailbox=bad)
        assert mcp.call("polyctl_inbox", {}, bad_cfg, False, "implementer") == {"error": OUTSIDE}


def test_inbox_skips_a_mail_entry_that_is_a_symlink(project, tmp_path):
    root = Path(project["root"])
    real_name, real_body = _addressed(project, "20261120-0904", "go", "Apply it, then acknowledge it.")
    linked, _ = _addressed(project, "20261120-0905", "linked", "This file stands outside the project.")
    outside = tmp_path / "outside.md"
    outside_body = "# linked\n\nThis file stands outside the project.\n"
    (root / "agent-mail" / real_name).write_text(real_body, encoding="utf-8")
    outside.write_text(outside_body, encoding="utf-8")
    (root / "agent-mail" / linked).symlink_to(outside)

    reply = mcp.call("polyctl_inbox", {}, project, False, "implementer")

    assert [message["id"] for message in reply["messages"]] == [real_name]
    assert reply["messages"][0]["body"] == real_body
    assert outside_body not in json.dumps(reply)

    refused = mcp.call("polyctl_ack", {"id": linked, "outcome": "applied"}, project, False, "implementer")

    assert refused == {"error": f"{linked} is a link, so polyctl_ack does not take it"}
    assert (root / "agent-mail" / linked).is_symlink()
    assert outside.read_text(encoding="utf-8") == outside_body


def test_ack_refuses_a_mailbox_outside_the_project_and_leaves_the_file(project):
    root = Path(project["root"])
    elsewhere = root.parent / "elsewhere"
    elsewhere.mkdir()
    name, body = _addressed(project, "20261120-0906", "keep", "This file stands outside the project.")
    target = elsewhere / name
    target.write_text(body, encoding="utf-8")
    cfg = _config(project, "../elsewhere")

    reply = mcp.call("polyctl_ack", {"id": name, "outcome": "applied"}, cfg, False, "implementer")

    assert reply == {"error": OUTSIDE}
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == body


@pytest.mark.parametrize("store", ["deletion", "append-only"])
def test_ack_refuses_fifo_directory_and_symlink_entries_and_leaves_them(project, tmp_path, store):
    root = Path(project["root"])
    cfg = _config(project, "agent-mail", store=store)
    box = root / "agent-mail"

    dir_name, _ = _addressed(project, "20261125-0901", "dir", "Directory entry.")
    dir_entry = box / dir_name
    dir_entry.mkdir()
    (dir_entry / "sentinel.txt").write_text("keep", encoding="utf-8")

    out_target = tmp_path / "outside-target.md"
    out_target.write_text("# out\n\nKeep me.\n", encoding="utf-8")
    out_link_name, _ = _addressed(project, "20261125-0902", "outlink", "Symlink outside.")
    (box / out_link_name).symlink_to(out_target)

    in_target = root / "inside-target.md"
    in_target.write_text("# in\n\nKeep me inside.\n", encoding="utf-8")
    in_link_name, _ = _addressed(project, "20261125-0903", "inlink", "Symlink inside.")
    (box / in_link_name).symlink_to(in_target)

    entries = [
        (dir_name, "not a regular file"),
        (out_link_name, "is a link"),
        (in_link_name, "is a link"),
    ]
    if hasattr(os, "mkfifo"):
        fifo_name, _ = _addressed(project, "20261125-0900", "fifo", "FIFO entry.")
        os.mkfifo(box / fifo_name)
        entries.insert(0, (fifo_name, "not a regular file"))

    for entry_id, expected_fragment in entries:
        reply = mcp.call("polyctl_ack", {"id": entry_id, "outcome": "applied"}, cfg, False, "implementer")
        assert list(reply) == ["error"]
        assert expected_fragment in reply["error"]

    if hasattr(os, "mkfifo"):
        assert stat.S_ISFIFO(os.lstat(box / entries[0][0]).st_mode)
    assert dir_entry.is_dir()
    assert (dir_entry / "sentinel.txt").read_text(encoding="utf-8") == "keep"
    assert (box / out_link_name).is_symlink()
    assert out_target.read_text(encoding="utf-8") == "# out\n\nKeep me.\n"
    assert (box / in_link_name).is_symlink()
    assert in_target.read_text(encoding="utf-8") == "# in\n\nKeep me inside.\n"
    assert [r for r in A.mail_log(str(root)) if r.get("event") == "consumed"] == []
    if store == "append-only":
        assert [r for r in A.mail_store_rows(str(root)) if r.get("event") == "handled"] == []


def test_symlinked_mailbox_inside_project_works_for_inbox_ack_report_and_status(project):
    root = Path(project["root"])
    real_mail = root / "nested" / "real-mail"
    real_mail.mkdir(parents=True)
    (root / "mail-link").symlink_to(real_mail)
    cfg = _config(project, "mail-link")

    msg_name, msg_body = _addressed(project, "20261125-0910", "inside", "Handle this message.")
    (real_mail / msg_name).write_text(msg_body, encoding="utf-8")

    status = mcp.call("polyctl_status", {}, cfg, False, "implementer")
    assert status["mailbox"] == [msg_name]

    inbox = mcp.call("polyctl_inbox", {}, cfg, False, "implementer")
    assert inbox["messages"] == [{"id": msg_name, "body": msg_body}]

    ack = mcp.call("polyctl_ack", {"id": msg_name, "outcome": "applied"}, cfg, False, "implementer")
    assert ack == {"acknowledged": msg_name, "outcome": "applied"}
    assert not (real_mail / msg_name).exists()

    first = mcp.call("polyctl_report", {"kind": "status", "summary": "Inside symlink report"}, cfg, False, "implementer")
    assert "error" not in first
    written = first["written"]
    assert (real_mail / written).is_file()

    second = mcp.call("polyctl_report", {"kind": "status", "summary": "Inside symlink report"}, cfg, False, "implementer")
    assert second["written"] == written
    assert second["repeated"] == 2


def test_symlinked_mailbox_outside_project_is_refused_by_inbox_ack_report_and_status(project, tmp_path):
    root = Path(project["root"])
    outside_mail = tmp_path / "outside-mail"
    outside_mail.mkdir()
    msg_name, msg_body = _addressed(project, "20261125-0915", "escape", "Outside secret.")
    target = outside_mail / msg_name
    target.write_text(msg_body, encoding="utf-8")
    (root / "mail-link").symlink_to(outside_mail)
    cfg = _config(project, "mail-link")

    assert mcp.call("polyctl_inbox", {}, cfg, False, "implementer") == {"error": OUTSIDE}
    assert mcp.call("polyctl_ack", {"id": msg_name, "outcome": "applied"}, cfg, False, "implementer") == {"error": OUTSIDE}
    assert mcp.call("polyctl_report", {"kind": "status", "summary": "Should not write"}, cfg, False, "implementer") == {
        "error": OUTSIDE
    }
    status = mcp.call("polyctl_status", {}, cfg, False, "implementer")
    assert status["mailbox"] == []
    assert [p.name for p in outside_mail.iterdir()] == [msg_name]
    assert target.read_text(encoding="utf-8") == msg_body


def test_report_refuses_outside_and_absolute_mailbox(project):
    root = Path(project["root"])
    elsewhere = root.parent / "elsewhere-report"
    elsewhere.mkdir()

    for mailbox in ("../elsewhere-report", str(elsewhere.resolve()), str((root / "agent-mail").resolve())):
        cfg = _config(project, mailbox)
        reply = mcp.call("polyctl_report", {"kind": "status", "summary": "Blocked write"}, cfg, False, "implementer")
        assert reply == {"error": OUTSIDE}
    assert list(elsewhere.iterdir()) == []
    assert list((root / "agent-mail").iterdir()) == []


def test_report_duplicate_scan_skips_symlink_fifo_and_directory(project, tmp_path):
    root = Path(project["root"])
    box = root / "agent-mail"
    summary = "Same summary"

    outside = tmp_path / "outside-report.md"
    outside_body = f"# {summary}\n\n## STATUS\n\nOutside content.\n"
    outside.write_text(outside_body, encoding="utf-8")

    link_rep = _report_name(project, "20261125-0920", "link")
    (box / link_rep).symlink_to(outside)

    dir_rep = _report_name(project, "20261125-0921", "dir")
    (box / dir_rep).mkdir()

    if hasattr(os, "mkfifo"):
        fifo_rep = _report_name(project, "20261125-0922", "fifo")
        os.mkfifo(box / fifo_rep)

    first = mcp.call("polyctl_report", {"kind": "status", "summary": summary}, project, False, "implementer")
    assert "error" not in first
    assert "repeated" not in first
    written = first["written"]
    assert (box / written).is_file()
    assert outside.read_text(encoding="utf-8") == outside_body

    second = mcp.call("polyctl_report", {"kind": "status", "summary": summary}, project, False, "implementer")
    assert second["written"] == written
    assert second["repeated"] == 2


def test_mixed_fixture_status_inbox_and_report_see_only_regular_entries(project, tmp_path):
    root = Path(project["root"])
    box = root / "agent-mail"

    reg_in, reg_in_body = _addressed(project, "20261125-0930", "reg-in", "Regular inbound.")
    (box / reg_in).write_text(reg_in_body, encoding="utf-8")

    reg_rep = _report_name(project, "20261125-0931", "standing")
    (box / reg_rep).write_text("# Standing blocker\n\n## STATUS\n\nInitial.\n", encoding="utf-8")

    outside_in = tmp_path / "outside-in.md"
    outside_in.write_text("# Link\n\nDo not read.\n", encoding="utf-8")
    link_in, _ = _addressed(project, "20261125-0932", "link-in", "Link inbound.")
    (box / link_in).symlink_to(outside_in)

    outside_rep = tmp_path / "outside-rep.md"
    outside_rep.write_text("# Standing blocker\n\n## STATUS\n\nDo not touch.\n", encoding="utf-8")
    link_rep = _report_name(project, "20261125-0933", "link-rep")
    (box / link_rep).symlink_to(outside_rep)

    dir_in, _ = _addressed(project, "20261125-0934", "dir-in", "Dir inbound.")
    (box / dir_in).mkdir()

    dir_rep = _report_name(project, "20261125-0935", "dir-rep")
    (box / dir_rep).mkdir()

    if hasattr(os, "mkfifo"):
        fifo_in, _ = _addressed(project, "20261125-0936", "fifo-in", "FIFO inbound.")
        os.mkfifo(box / fifo_in)
        fifo_rep = _report_name(project, "20261125-0937", "fifo-rep")
        os.mkfifo(box / fifo_rep)

    status = mcp.call("polyctl_status", {}, project, False, "implementer")
    assert status["mailbox"] == sorted([reg_in, reg_rep])

    inbox = mcp.call("polyctl_inbox", {}, project, False, "implementer")
    assert [m["id"] for m in inbox["messages"]] == [reg_in]

    rep = mcp.call("polyctl_report", {"kind": "status", "summary": "Standing blocker"}, project, False, "implementer")
    assert rep["written"] == reg_rep
    assert rep["repeated"] == 2
    assert outside_rep.read_text(encoding="utf-8") == "# Standing blocker\n\n## STATUS\n\nDo not touch.\n"
    assert (box / link_in).is_symlink()
    assert (box / dir_in).is_dir()
    if hasattr(os, "mkfifo"):
        assert stat.S_ISFIFO(os.lstat(box / fifo_in).st_mode)


def test_status_append_only_keeps_removed_view_store_row_while_skipping_non_regular_entries(project, tmp_path):
    root = Path(project["root"])
    cfg = _config(project, "agent-mail", store="append-only")
    box = root / "agent-mail"

    stored_name, stored_body = _addressed(project, "20261125-0940", "stored", "Stored in append-only.")
    written = A.write_mail(str(root), cfg, stored_name, stored_body, {"kind": "decision", "from": "fable", "to": "kiro"})
    assert written == stored_name
    # Remove the view file; append-only store still holds the unhandled message.
    os.unlink(box / stored_name)

    outside = tmp_path / "outside-ao.md"
    outside.write_text("# Link\n\nOutside.\n", encoding="utf-8")
    link_name, _ = _addressed(project, "20261125-0941", "link-ao", "Link.")
    (box / link_name).symlink_to(outside)

    dir_name, _ = _addressed(project, "20261125-0942", "dir-ao", "Dir.")
    (box / dir_name).mkdir()

    if hasattr(os, "mkfifo"):
        fifo_name, _ = _addressed(project, "20261125-0943", "fifo-ao", "FIFO.")
        os.mkfifo(box / fifo_name)

    status = mcp.call("polyctl_status", {}, cfg, False, "implementer")
    assert status["mailbox"] == [stored_name]


def test_ack_regular_message_in_append_only_skips_sibling_fifo_dir_and_symlink(project, tmp_path):
    root = Path(project["root"])
    cfg = _config(project, "agent-mail", store="append-only")
    box = root / "agent-mail"

    reg_name, reg_body = _addressed(project, "20261125-0950", "regular", "Apply this one.")
    (box / reg_name).write_text(reg_body, encoding="utf-8")

    outside = tmp_path / "outside-sibling.md"
    outside_body = "# Sibling\n\nDo not ingest.\n"
    outside.write_text(outside_body, encoding="utf-8")
    link_name, _ = _addressed(project, "20261125-0951", "sib-link", "Symlink sibling.")
    (box / link_name).symlink_to(outside)

    dir_name, _ = _addressed(project, "20261125-0952", "sib-dir", "Dir sibling.")
    (box / dir_name).mkdir()

    fifo_name = None
    if hasattr(os, "mkfifo"):
        fifo_name, _ = _addressed(project, "20261125-0953", "sib-fifo", "FIFO sibling.")
        os.mkfifo(box / fifo_name)

    ack = mcp.call("polyctl_ack", {"id": reg_name, "outcome": "applied"}, cfg, False, "implementer")
    assert ack == {"acknowledged": reg_name, "outcome": "applied"}
    assert not (box / reg_name).exists()

    rows = A.mail_store_rows(str(root))
    assert [r["id"] for r in rows if r.get("event") == "message"] == [reg_name]
    assert [r["id"] for r in rows if r.get("event") == "handled"] == [reg_name]
    assert (box / link_name).is_symlink()
    assert outside.read_text(encoding="utf-8") == outside_body
    assert (box / dir_name).is_dir()
    if fifo_name is not None:
        assert stat.S_ISFIFO(os.lstat(box / fifo_name).st_mode)
