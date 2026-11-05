import json
import os
import time
from types import SimpleNamespace

import pytest

from polyctl import cli, lib as A, watchdog as W


def _project(parent, name="api"):
    root = parent / name
    (root / ".polyctl").mkdir(parents=True)
    return str(root)


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(A, "HOME", str(home))
    monkeypatch.setattr(W, "STATE_DIR", str(home / ".polyctl"))
    return home


def test_an_installed_project_keeps_the_name_its_files_already_have(tmp_path, home):
    root = _project(tmp_path)

    assert A.project_key(root) == "api"
    assert A.project_key(root + "/") == "api"
    assert A.heartbeat_path(root).endswith("heartbeat-api")
    mark = json.load(open(os.path.join(root, ".polyctl", A.PROJECT_KEY_FILE), encoding="utf-8"))
    assert mark == {"key": "api", "root": os.path.realpath(root)}


def test_two_projects_with_one_name_keep_their_files_apart(tmp_path, home):
    first = _project(tmp_path / "work")
    second = _project(tmp_path / "personal")
    one, two = A.project_key(first), A.project_key(second)
    assert one == "api" and two.startswith("api-") and len(two) == len("api-") + 8

    # a push window opened for one is not open for the other
    push = lambda root, action: cli.cmd_push({"root": root}, SimpleNamespace(action=action, minutes=30))
    assert push(first, "allow") == 0
    assert push(first, "check") == 0
    assert push(second, "check") == 1

    # watchdog state, heartbeats, locks, helper and reviewer records, cycle logs
    W.save_state(first, {"attempts": 7})
    assert W.load_state(first)["attempts"] == 7 and W.load_state(second).get("attempts") != 7
    A.heartbeat(first)
    assert A.heartbeat_age(first) is not None and A.heartbeat_age(second) is None
    assert A.acquire_architect(first, os.getpid(), "test")
    assert A.architect_lock_holder(second) is None
    for path in (W.state_path, W.cycles_path, A.architect_lock_path, A.helpers_path,
                 A.reviewer_state_path, A.heartbeat_path):
        assert path(first) != path(second), path.__name__
    then = time.time() - 20 * 60
    os.utime(A.heartbeat_path(first), (then, then))
    assert set(A.stale_siblings(second)) == {one}
    assert A.stale_siblings(first) == {}


def test_names_differing_only_in_case_are_one_name(tmp_path, home):
    assert A.project_key(_project(tmp_path / "a", "Api")) == "Api"
    assert A.project_key(_project(tmp_path / "b", "api")).startswith("api-")


def test_a_lost_registry_gives_each_project_its_own_name_back(tmp_path, home):
    first = _project(tmp_path / "work")
    second = _project(tmp_path / "personal")
    names = A.project_key(first), A.project_key(second)
    os.replace(A.project_registry_path(), str(tmp_path / "set-aside.json"))

    assert (A.project_key(second), A.project_key(first)) == (names[1], names[0])


def test_a_copied_polyctl_directory_does_not_claim_the_original_name(tmp_path, home):
    original = _project(tmp_path / "work")
    assert A.project_key(original) == "api"
    copy = _project(tmp_path / "copy")
    mark = open(os.path.join(original, ".polyctl", A.PROJECT_KEY_FILE), encoding="utf-8").read()
    open(os.path.join(copy, ".polyctl", A.PROJECT_KEY_FILE), "w", encoding="utf-8").write(mark)

    assert A.project_key(copy).startswith("api-")


def test_a_name_whose_project_is_gone_is_taken_by_the_next(tmp_path, home):
    retired = _project(tmp_path / "old")
    assert A.project_key(retired) == "api"
    os.rename(os.path.join(retired, ".polyctl"), os.path.join(retired, "polyctl-was-here"))

    assert A.project_key(_project(tmp_path / "new")) == "api"


def test_a_directory_that_is_not_a_project_is_named_but_not_recorded(tmp_path, home):
    plain = tmp_path / "scratch"
    plain.mkdir()

    assert A.project_key(str(plain)) == "scratch"
    assert A.project_registry() == {}


def test_polyctl_projects_names_the_projects_that_would_have_collided(tmp_path, home, capsys, monkeypatch):
    monkeypatch.setattr(A, "all_workspaces", lambda: [])
    first = _project(tmp_path / "work")
    second = _project(tmp_path / "personal")
    A.project_key(first), A.project_key(second)

    cli.cmd_projects({}, SimpleNamespace())

    out = capsys.readouterr().out
    assert "2 projects are named api" in out
    assert os.path.realpath(first) in out and os.path.realpath(second) in out


def test_a_linked_worktree_resolves_to_the_main_checkouts_project(tmp_path, home, monkeypatch, capsys):
    import json
    import subprocess as sp

    main_dir = tmp_path / "repo"
    (main_dir / ".polyctl" / "ledger").mkdir(parents=True)
    (main_dir / "agent-mail").mkdir()
    (main_dir / ".polyctl" / "config.json").write_text(json.dumps({
        "architect": {"id": "claude-code", "name": "architect", "cmd": "claude"},
        "implementer": {"id": "kiro-cli", "name": "implementer", "cmd": "kiro-cli"},
    }), encoding="utf-8")
    (main_dir / ".polyctl" / "board.md").write_text("# Board\n\n## Running\n- [S1] Slice one\n", encoding="utf-8")
    for argv in (
        ["init", "-q"],
        ["config", "user.email", "t@e"],
        ["config", "user.name", "t"],
        ["add", ".polyctl/config.json", ".polyctl/board.md"],
        ["commit", "-q", "-m", "init"],
    ):
        sp.run(["git", *argv], cwd=str(main_dir), check=True)

    assert A.project_key(str(main_dir)) == "repo"
    A.write_mail(
        str(main_dir),
        {"mailbox": "agent-mail"},
        "20261019-1200-architect-to-implementer-NOTE-hello.md",
        "# Hello from main\n",
        {"kind": "note", "from": "architect", "to": "implementer"},
    )

    wt_dir = tmp_path / "wt-slice-1"
    sp.run(["git", "worktree", "add", "-q", "-b", "wt-1", str(wt_dir)], cwd=str(main_dir), check=True)
    assert (wt_dir / ".polyctl" / "config.json").is_file()

    assert A.linked_worktree_main(str(wt_dir)) == os.path.realpath(str(main_dir))
    sub = wt_dir / "src" / "pkg"
    sub.mkdir(parents=True)
    assert A.linked_worktree_main(str(sub)) == os.path.realpath(str(main_dir))
    assert A.find_root(str(wt_dir)) == os.path.abspath(str(wt_dir))
    monkeypatch.chdir(sub)
    assert A.find_root() == os.path.abspath(str(wt_dir))
    assert A.project_key(str(wt_dir)) == "repo"
    assert set(A.project_registry()) == {"repo"}

    monkeypatch.chdir(wt_dir)
    assert cli.main(["mail", "list"]) == 0
    out = capsys.readouterr().out
    assert "NOTE-hello.md" in out
    assert set(A.project_registry()) == {"repo"}


def test_a_governed_worktree_verifies_grants_and_commits_its_own_tree_under_the_local_hook(
    tmp_path, home, monkeypatch, capsys
):
    import json
    import shlex
    import subprocess as sp
    import sys

    bindir = tmp_path / "bin"
    bindir.mkdir()
    source = os.path.dirname(os.path.dirname(os.path.abspath(cli.__file__))).replace("\\", "/")
    python = sys.executable.replace("\\", "/")
    wrapper = bindir / "polyctl"
    wrapper.write_text(
        "#!/bin/sh\n"
        "export PYTHONDONTWRITEBYTECODE=1\n"
        f"export PYTHONPATH={shlex.quote(source)}\n"
        f"exec {shlex.quote(python)} -m polyctl.cli \"$@\"\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))
    for var in A.AGENT_HARNESS_ENV:
        monkeypatch.delenv(var, raising=False)

    main_dir = tmp_path / "repo"
    (main_dir / ".polyctl" / "ledger").mkdir(parents=True)
    (main_dir / "agent-mail").mkdir()
    (main_dir / ".githooks").mkdir()
    (main_dir / cli.PROJECT_MARKER).write_bytes(cli.PROJECT_MARKER_BYTES)
    (main_dir / ".polyctl" / "config.json").write_text(json.dumps({
        "architect": {"id": "claude-code", "name": "architect", "cmd": "claude"},
        "implementer": {"id": "kiro-cli", "name": "implementer", "cmd": "kiro-cli"},
    }), encoding="utf-8")
    (main_dir / ".polyctl" / "gates.json").write_text(json.dumps({
        "gates": {
            "lane-file": {
                "run": f"{shlex.quote(sys.executable)} -c \"assert open('feature.txt').read() == 'lane work\\\\n'\"",
                "timeout": 10,
            },
        },
        "profiles": {"quick": ["lane-file"]},
    }), encoding="utf-8")
    (main_dir / ".polyctl" / "board.md").write_text("# Board\n\n## running\n- [S1] Slice one\n", encoding="utf-8")
    hook = main_dir / ".githooks" / "pre-commit"
    hook.write_bytes(cli._render_local_hook("pre-commit", "."))
    hook.chmod(0o755)

    for argv in (
        ["init", "-q"],
        ["config", "user.email", "t@e"],
        ["config", "user.name", "t"],
        ["config", "core.hooksPath", ".githooks"],
        ["add", ".polyctl-project", ".polyctl/config.json", ".polyctl/gates.json", ".polyctl/board.md", ".githooks/pre-commit"],
        ["commit", "-q", "--no-verify", "-m", "init"],
    ):
        sp.run(["git", *argv], cwd=str(main_dir), check=True)
    main_head = sp.run(["git", "rev-parse", "HEAD"], cwd=str(main_dir), check=True, capture_output=True, text=True).stdout.strip()

    wt_dir = tmp_path / "wt-lane-1"
    sp.run(["git", "worktree", "add", "-q", "-b", "lane/s1", str(wt_dir)], cwd=str(main_dir), check=True)
    (wt_dir / "feature.txt").write_text("lane work\n", encoding="utf-8")
    sp.run(["git", "add", "feature.txt"], cwd=str(wt_dir), check=True)

    monkeypatch.chdir(wt_dir)
    assert cli.main(["verify", "-p", "quick"]) == 0
    assert A.latest_verification(str(wt_dir)) is not None
    assert A.latest_verification(str(main_dir)) is None

    assert cli.main(["waive", "review", "--slice", "S1", "--why", "test", "--by", "Sam"]) == 0
    assert cli.main(["commit-ok"]) == 0
    capsys.readouterr()

    sp.run(["git", "commit", "-q", "-m", "S1: lane work"], cwd=str(wt_dir), check=True)
    wt_head = sp.run(["git", "rev-parse", "HEAD"], cwd=str(wt_dir), check=True, capture_output=True, text=True).stdout.strip()
    assert wt_head != main_head
    assert sp.run(["git", "rev-parse", "HEAD"], cwd=str(main_dir), check=True, capture_output=True, text=True).stdout.strip() == main_head
    assert set(A.project_registry()) == {"repo"}
