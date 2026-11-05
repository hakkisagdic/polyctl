"""Doctor reports redirects alongside other findings and still pages human alarms (NESTED-GIT)."""
import time
from types import SimpleNamespace

from polyctl import cli, lib as A
from polyctl import watchdog as W
from tests.test_nested_git import _outer_with_subproject, _plant


def test_redirected_doctor_continues_checks_and_human_notifications(tmp_path, monkeypatch, capsys):
    outer, root = _outer_with_subproject(tmp_path)
    inner_git = _plant(tmp_path, root, "gitfile")
    cfg = A.load_config(str(root))
    monkeypatch.delenv(cli.COMMIT_TOP_ENV, raising=False)
    monkeypatch.setattr(cli, "_active_review_tier", lambda cfg: (
        "test", [("transcript-missing", "missing transcript; restore the session")]))
    raised = []
    monkeypatch.setattr(W, "notify", lambda title, msg, root=None, **kw:
                        raised.append((kw["key"], kw["audience"])) or True)

    problems = dict(cli.doctor_problems(cfg))
    assert "repository-redirect" in problems
    assert "transcript-missing" in problems
    assert cli.cmd_doctor(cfg, SimpleNamespace(check=True, notify=True)) == 1
    out = capsys.readouterr().out
    assert "PROBLEM repository-redirect:" in out
    assert "PROBLEM transcript-missing:" in out
    assert ("doctor:transcript-missing", "human") in raised
    assert ("doctor:repository-redirect", "human") in raised
    assert not (inner_git / "polyctl-enrolled.json").exists()
    assert not (outer / ".git" / "polyctl-enrolled.json").exists()


def test_manual_doctor_reports_redirect_and_continues(tmp_path, monkeypatch, capsys):
    outer, root = _outer_with_subproject(tmp_path)
    _plant(tmp_path, root, "gitfile")
    cfg = A.load_config(str(root))
    (root / cfg["mailbox"]).mkdir()
    monkeypatch.delenv(cli.COMMIT_TOP_ENV, raising=False)
    monkeypatch.setattr(cli, "_session_lines", lambda cfg: ["session checks continued"])
    assert cli.cmd_doctor(cfg, SimpleNamespace()) == 1
    out = capsys.readouterr().out
    assert "repository redirect" in out
    assert "session checks continued" in out
    assert "commit hook" in out


def test_redirect_does_not_skip_doctor_consistency(tmp_path, monkeypatch):
    outer, root = _outer_with_subproject(tmp_path)
    _plant(tmp_path, root, "gitfile")
    cfg = A.load_config(str(root))
    checked = []
    monkeypatch.setattr(cli, "_doctor_consistency", lambda cfg, repair=False: checked.append(repair) or 1)
    assert cli.cmd_doctor(cfg, SimpleNamespace(consistency=True)) == 1
    assert checked == [False]


def _capture(monkeypatch, problems):
    raised = []
    monkeypatch.setattr(cli, "doctor_problems", lambda cfg: problems)
    monkeypatch.setattr(W, "notify", lambda title, msg, root=None, key=None, window=1800,
                        audience=None, level=None, **kw: raised.append(key) or True)
    return raised


def test_the_doctor_does_not_ring_a_second_alarm_for_what_the_watchdog_rings(project, monkeypatch, capsys):
    raised = _capture(monkeypatch, [
        ("credits-exhaust", "credits exhausted at the last reading"),
        ("wake-failed", "last architect wake failed (binary): not found"),
        ("no-channel", "no human channel beyond desktop notifications"),
    ])
    A.alarm_touch("proj", "credits-exhaust", "red", title="proj: credits exhausted")

    assert cli._doctor_check(project, page=True) == 1

    out = capsys.readouterr().out
    assert "PROBLEM credits-exhaust" in out and "PROBLEM no-channel" in out
    assert raised == ["credits-exhaust", "architect-wake-failed", "doctor:no-channel"]


def test_the_doctor_rings_once_the_watchdogs_alarm_has_gone_quiet(project, monkeypatch):
    raised = _capture(monkeypatch, [("wake-failed", "last architect wake failed (session): gone")])
    A.alarm_touch("proj", "architect-wake-failed", "orange",
                  now=time.time() - A.ALARM_RESET_AFTER - 60)

    assert cli._doctor_check(project, page=True) == 1

    assert raised == ["architect-wake-failed"]


def test_a_reading_over_the_limit_is_exhausted_not_a_date_ahead():
    projection = {"before_reset": True, "exhausts_at": time.time() + 3600, "per_day": 8547}

    assert cli._credits_problem(projection, {"used": 12503.14, "limit": 10000}) == (
        "credits-exhaust", "credits exhausted at the last reading: 12503/10000 (account not named by the reading)")
    code, text = cli._credits_problem(projection, {"used": 9000, "limit": 10000})
    assert code == "credits-exhaust" and text.startswith("credits run out ")
    assert cli._credits_problem({"before_reset": False}, {"used": 10, "limit": 10000}) is None
    assert cli._credits_problem(None, None) is None


def test_doctor_names_projects_created_by_a_linked_worktree_without_deleting_them(project, tmp_path, capsys):
    import json
    import os
    import subprocess as sp

    root = project["root"]
    sp.run(["git", "add", ".polyctl/config.json"], cwd=root, check=True)
    sp.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=root, check=True)
    A.project_key(root)

    wt_dir = tmp_path / "wt-mistake"
    sp.run(["git", "worktree", "add", "-q", "-b", "wt-mistake", str(wt_dir)], cwd=root, check=True)

    reg_path = A.project_registry_path()
    reg = A.project_registry()
    reg["wt-mistake"] = {"root": str(wt_dir), "at": 1700000000}
    os.makedirs(os.path.dirname(reg_path), exist_ok=True)
    open(reg_path, "w", encoding="utf-8").write(json.dumps(reg))
    mistake_state = os.path.join(A.HOME, ".polyctl", "heartbeat-wt-mistake")
    os.makedirs(os.path.dirname(mistake_state), exist_ok=True)
    open(mistake_state, "w", encoding="utf-8").write("{}\n")

    problems = dict(cli.doctor_problems(project))
    assert "worktree-project:wt-mistake" in problems
    assert "wt-mistake" in problems["worktree-project:wt-mistake"]
    assert os.path.realpath(root) in problems["worktree-project:wt-mistake"]

    cli.cmd_doctor(project, SimpleNamespace(
        check=False, page=False, fix=False, reconcile=False, adopt_orphans=False, json=False))
    out = capsys.readouterr().out
    assert "wt-mistake" in out and os.path.realpath(root) in out
    assert "wt-mistake" in A.project_registry()
    assert os.path.isfile(mistake_state)
