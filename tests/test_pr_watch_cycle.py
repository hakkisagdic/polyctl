"""A watchdog cycle runs the pull-request pass when `pr.watch` is on (PR-WATCH-CYCLE).

One live cycle is `watchdog.run`, the way the other cycle tests run `polyctl watchdog` once.
The gh it would ask is the fake from tests/test_pr_watch.py, so nothing here reaches GitHub.
Off, and on a dry run, that fake is not asked and `.polyctl/pr-watch.last` is not written.
On, a failed check is mailed once; a second cycle inside `pr.watch_minutes` asks nothing more;
an unauthenticated gh still lets the cycle end, and rings one alarm for six hours.
"""
import json
import os
import re
import time
from types import SimpleNamespace

import pytest

from polyctl import cli, email, lib as A, ntfy, settings as S, telegram, watchdog as W
from tests.test_pr_watch import FAILED, HEAD, FakeGh, _mails, _pull, _watching

on_posix = pytest.mark.skipif(os.name == "nt", reason="the fake gh runs through its shebang, which Windows ignores")


def _last(root):
    return os.path.join(root, ".polyctl", "pr-watch.last")


def _cycle(root, capsys, dry_run=False):
    """One cycle. Its text is what it printed, with the colour codes taken out."""
    code = W.run(SimpleNamespace(root=root, idle_minutes=6.0, dry_run=dry_run))
    captured = capsys.readouterr()
    return code, re.sub(r"\x1b\[[0-9;]*m", "", captured.out + captured.err)


def _saved(root):
    with open(os.path.join(root, ".polyctl", "config.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _attempt(root):
    """The sidecar's text and mtime: a skipped cycle leaves both where they were."""
    path = _last(root)
    with open(path, encoding="utf-8") as fh:
        return fh.read(), os.path.getmtime(path)


def _age_attempt(root, seconds):
    """Move the last attempt `seconds` into the past, as an integer and as the file's mtime."""
    path = _last(root)
    when = time.time() - seconds
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"{int(when)}\n")
    os.utime(path, (when, when))


def _past_interval(root):
    _age_attempt(root, S.get(A.load_config(root), "pr.watch_minutes") * 60 + 5)


def _mail_rows(root):
    path = os.path.join(root, ".polyctl", "ledger", "mail.jsonl")
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _alarms(root, sent=None):
    path = os.path.join(root, ".polyctl", "ledger", "notices.jsonl")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("key") != "pr-watch-unreadable":
                continue
            if sent is None or row.get("sent") is sent:
                rows.append(row)
    return rows


def _rings(desktop):
    return [msg for title, msg in desktop if "pull requests could not be read" in title]


# ---- the cycle, with the setting off, on, throttled, failing, or dry -----------------------------------

@on_posix
def test_with_pr_watch_off_a_cycle_asks_gh_nothing_and_writes_no_sidecar(project, tmp_path, monkeypatch, capsys):
    gh = FakeGh(tmp_path, monkeypatch)
    gh.answer(_pull(statusCheckRollup=[FAILED]))
    root = _watching(project, watch="off")

    code, out = _cycle(root, capsys)

    assert code == 0 and "nothing to watch" in out, out
    assert gh.calls() == [] and not os.path.exists(_last(root)) and _mails(root) == []


@on_posix
def test_a_cycle_mails_a_failed_check_and_records_the_mail(project, tmp_path, monkeypatch, capsys):
    gh = FakeGh(tmp_path, monkeypatch)
    gh.answer(_pull(statusCheckRollup=[FAILED]))
    root = _watching(project)

    code, out = _cycle(root, capsys)

    [mail] = _mails(root)
    assert code == 0 and "nothing to watch" in out, out
    assert re.fullmatch(r"\d{8}-\d{4}-pr-watch-to-kiro-PR-12-check-failed-" + HEAD[:12] + r"\.md", mail)
    assert any(row.get("event") == "written" and row.get("id") == mail for row in _mail_rows(root))
    assert [call[:2] for call in gh.calls()] == [["pr", "list"], ["pr", "view"]]
    assert re.fullmatch(r"[0-9]+\n", _attempt(root)[0])


@on_posix
def test_a_second_cycle_inside_the_interval_reads_nothing_and_one_past_it_mails_the_head_once(
        project, tmp_path, monkeypatch, capsys):
    gh = FakeGh(tmp_path, monkeypatch)
    gh.answer(_pull(statusCheckRollup=[FAILED]))
    root = _watching(project)
    assert _cycle(root, capsys)[0] == 0
    [mail] = _mails(root)
    asked, kept = gh.calls(), _attempt(root)

    code, out = _cycle(root, capsys)

    assert code == 0 and gh.calls() == asked and _attempt(root) == kept and _mails(root) == [mail], out

    _past_interval(root)
    code, out = _cycle(root, capsys)

    assert code == 0 and _mails(root) == [mail], out
    assert [call[:2] for call in gh.calls()] == [["pr", "list"], ["pr", "view"], ["pr", "list"], ["pr", "view"]]
    with open(A.pr_watch_path(root), encoding="utf-8") as fh:
        recorded = json.load(fh)
    assert recorded["reported"]["12"]["check-failed"]["head"] == HEAD


@on_posix
def test_an_unauthenticated_gh_leaves_the_cycle_its_exit_and_rings_once_within_six_hours(
        project, tmp_path, monkeypatch, capsys, desktop_notifications):
    # The desktop stand-in is already in place. The phone and the mail must not leave this machine.
    phone = []
    monkeypatch.setattr(telegram, "send", lambda *args, **kwargs: phone.append("telegram") or 0)
    monkeypatch.setattr(ntfy, "send", lambda *args, **kwargs: phone.append("ntfy") or False)
    monkeypatch.setattr(email, "send", lambda *args, **kwargs: phone.append("email") or False)
    gh = FakeGh(tmp_path, monkeypatch)
    gh.answer(_pull(statusCheckRollup=[FAILED]), authenticated=False)
    root = _watching(project)

    code, out = _cycle(root, capsys)

    assert code == 0 and "nothing to watch" in out, out
    assert _mails(root) == [] and not os.path.exists(A.pr_watch_path(root))
    assert re.fullmatch(r"[0-9]+\n", _attempt(root)[0])
    sent = _alarms(root, sent=True)
    assert len(sent) == 1 and sent[0]["key"] == "pr-watch-unreadable" and "gh auth login" in sent[0]["msg"]
    assert len(_rings(desktop_notifications)) == 1 and "gh auth login" in _rings(desktop_notifications)[0]
    assert phone == ["telegram", "ntfy"]
    assert any(episode["key"] == "pr-watch-unreadable" for episode in A.active_alarms(A.project_key(root)))

    # The read is due again, and the alarm's six hours have not passed.
    _past_interval(root)
    code, out = _cycle(root, capsys)

    assert code == 0 and "nothing to watch" in out, out
    assert [call[:2] for call in gh.calls()] == [["pr", "list"], ["pr", "list"]]
    assert len(_alarms(root, sent=True)) == 1 and len(_rings(desktop_notifications)) == 1
    assert phone == ["telegram", "ntfy"] and _mails(root) == []


@on_posix
def test_a_dry_run_with_pr_watch_on_asks_gh_nothing_and_writes_no_sidecar(project, tmp_path, monkeypatch, capsys):
    gh = FakeGh(tmp_path, monkeypatch)
    gh.answer(_pull(statusCheckRollup=[FAILED]))
    root = _watching(project)

    code, out = _cycle(root, capsys, dry_run=True)

    assert code == 0 and "nothing to watch" in out, out
    assert gh.calls() == [] and not os.path.exists(_last(root)) and _mails(root) == []
    assert not os.path.exists(A.pr_watch_path(root))


def test_a_watch_interval_under_five_minutes_is_refused_and_the_list_shows_fifteen(project, capsys):
    root = project["root"]
    before = _saved(root)

    code = cli.main(["-C", root, "config", "set", "pr.watch_minutes", "3"])
    out, err = capsys.readouterr()
    shown = re.sub(r"\x1b\[[0-9;]*m", "", out)

    assert code == 2 and "pr.watch_minutes must be a whole number of at least 5" in shown, shown + err
    assert _saved(root) == before

    assert cli.main(["-C", root, "config", "list"]) == 0
    out, err = capsys.readouterr()
    shown = re.sub(r"\x1b\[[0-9;]*m", "", out)
    assert re.search(r"pr\.watch_minutes\s+15\s+15\s+default", shown), shown + err
