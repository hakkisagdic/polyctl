"""Tests for the `polyctl archon` command group (polyctl-archon-7)."""
import ast
import json
import os
import shutil
import subprocess
import sys

import pytest

from polyctl import cli, email, lib as A, ntfy, storage, telegram, watchdog as W
from tests.conftest import GIT, review_off


def _parse_one_json_line(text):
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) == 1, f"expected 1 JSON line, got {len(lines)}: {text!r}"
    return json.loads(lines[0])


def _write_fake_archon(bin_dir, body):
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "archon"
    script.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    script.chmod(0o755)
    return script


def _path_without_archon(tmp_path):
    safe_bin = tmp_path / "safe-bin"
    safe_bin.mkdir(parents=True, exist_ok=True)
    git_src = shutil.which("git")
    if git_src:
        link = safe_bin / os.path.basename(git_src)
        if not link.exists():
            os.symlink(git_src, link)
    return str(safe_bin)


def _isolate_home(tmp_path, monkeypatch, suffix="home"):
    home = tmp_path / suffix
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(A, "HOME", str(home))
    monkeypatch.setattr(W, "STATE_DIR", str(home / ".polyctl"))
    return home


def _make_adopted_repo(tmp_path, name, *, gate_cmd, review_enabled=False, install_hooks=False):
    repo = tmp_path / name
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run([GIT, "init", "-q"], cwd=repo, check=True)
    (repo / ".polyctl-project").write_bytes(b"polyctl-project-v1\n")
    (repo / "README.md").write_text("# sample\n", encoding="utf-8")
    subprocess.run([GIT, "add", ".polyctl-project", "README.md"], cwd=repo, check=True)
    subprocess.run(
        [GIT, "-c", "user.name=tester", "-c", "user.email=tester.invalid", "commit", "-q", "-m", "init"],
        cwd=repo,
        check=True,
    )
    (repo / ".polyctl").mkdir()
    (repo / ".polyctl" / "ledger").mkdir()
    cfg = {
        "project": name,
        "mailbox": "agent-mail",
        "reviews": "semantic-review",
        "actors": {
            "impl-one": {"id": "impl-one", "adapter": "kiro", "family": "anthropic"},
            "rev-one": {"id": "rev-one", "adapter": "codex", "family": "openai"},
        },
        "roles": {"implementer": "impl-one", "reviewer": "rev-one"},
    }
    if not review_enabled:
        cfg["features"] = {"review": False}
    (repo / ".polyctl" / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    gates = {
        "gates": {
            "check": {
                "run": gate_cmd,
                "expect": "exit_zero",
                "timeout": 30,
            }
        },
        "profiles": {"quick": ["check"], "full": ["check"]},
        "default_profile": "quick",
    }
    (repo / ".polyctl" / "gates.json").write_text(json.dumps(gates, indent=2), encoding="utf-8")
    (repo / ".polyctl" / "board.md").write_text(
        "# Board\n\n## running\n\n## blocked\n\n## queued\n\n## inbox\n\n## verified\n\n## done\n",
        encoding="utf-8",
    )
    (repo / "agent-mail").mkdir()
    (repo / "semantic-review").mkdir()
    full_cfg = dict(cfg, root=str(repo))
    if not review_enabled:
        full_cfg = review_off(full_cfg)
    if install_hooks:
        rc, problems = cli._hooks_install(full_cfg)
        assert rc == 0, problems
    return repo, full_cfg


def test_help_lists_archon_and_six_subcommands(capsys):
    top_help = cli.build_parser().format_help()
    assert "archon" in top_help

    with pytest.raises(SystemExit) as stopped:
        cli.main(["archon", "--help"])
    assert stopped.value.code == 0
    sub_help = capsys.readouterr().out
    expected = ["doctor", "runs", "gate", "record", "notify", "leftovers"]
    for name in expected:
        assert any(name in line and line.strip().startswith(name) for line in sub_help.splitlines()), (
            f"missing one-line help for {name}: {sub_help}"
        )

    code = cli.main(["archon"])
    out = capsys.readouterr()
    assert code == 2
    data = _parse_one_json_line(out.out)
    assert data["ok"] is False


def test_missing_archon_binary_runs_and_doctor(project, tmp_path, monkeypatch, capsys):
    root = project["root"]
    monkeypatch.setenv("PATH", _path_without_archon(tmp_path))

    code = cli.main(["-C", root, "archon", "runs"])
    out = capsys.readouterr()
    assert code == 2
    data = _parse_one_json_line(out.out)
    assert data["ok"] is False
    assert "archon" in data["error"].lower()

    code = cli.main(["-C", root, "archon", "doctor"])
    out = capsys.readouterr()
    assert code == 0
    doc = _parse_one_json_line(out.out)
    assert doc["ok"] is True
    assert doc["archon_found"] is False
    assert doc["archon_version"] is None
    assert doc["adopted"] is True
    assert doc["hooks_installed"] is False

    plain_dir = tmp_path / "plain"
    plain_dir.mkdir()
    code = cli.main(["-C", str(plain_dir), "archon", "doctor"])
    plain_doc = _parse_one_json_line(capsys.readouterr().out)
    assert code == 0
    assert plain_doc["ok"] is True
    assert plain_doc["adopted"] is False
    assert plain_doc["hooks_installed"] is False

    bin_dir = tmp_path / "bin"
    _write_fake_archon(
        bin_dir,
        "import sys\n"
        "if sys.argv[1:] == ['--version']:\n"
        "    print('archon 0.14.0')\n"
        "    sys.exit(0)\n"
        "sys.exit(1)\n",
    )
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + _path_without_archon(tmp_path))
    repo, _ = _make_adopted_repo(
        tmp_path,
        "hooked",
        gate_cmd=f'"{sys.executable}" -c "pass"',
        install_hooks=True,
    )
    capsys.readouterr()
    code = cli.main(["-C", str(repo), "archon", "doctor"])
    hooked_doc = _parse_one_json_line(capsys.readouterr().out)
    assert code == 0
    assert hooked_doc["archon_found"] is True
    assert hooked_doc["archon_version"] == "archon 0.14.0"
    assert hooked_doc["adopted"] is True
    assert hooked_doc["hooks_installed"] is True


def test_gate_green_profile_commits_with_trailers(tmp_path, monkeypatch, capsys):
    _isolate_home(tmp_path, monkeypatch)
    repo, _ = _make_adopted_repo(
        tmp_path,
        "target",
        gate_cmd=f'"{sys.executable}" -c "pass"',
        review_enabled=False,
    )
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run([GIT, "add", "app.py"], cwd=repo, check=True)
    capsys.readouterr()

    code = cli.main(["archon", "gate", "--worktree", str(repo), "-m", "feat: archon gate commit"])
    out = capsys.readouterr()
    assert code == 0, out.out + out.err
    payload = _parse_one_json_line(out.out)
    head_sha = subprocess.check_output([GIT, "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    assert payload["ok"] is True
    assert payload["sha"] == head_sha

    commit_msg = subprocess.check_output([GIT, "-C", str(repo), "log", "-1", "--format=%B"], text=True)
    assert "feat: archon gate commit" in commit_msg
    assert "Polyctl-Grant:" in commit_msg
    assert "Polyctl-Tree:" in commit_msg
    assert "Polyctl-Verification:" in commit_msg


def test_gate_failing_profile_refuses_and_bystander_untouched(tmp_path, monkeypatch, capsys):
    _isolate_home(tmp_path, monkeypatch)
    repo, _ = _make_adopted_repo(
        tmp_path,
        "failing-repo",
        gate_cmd=f'"{sys.executable}" -c "import sys; sys.exit(1)"',
        review_enabled=False,
    )
    bystander, _ = _make_adopted_repo(
        tmp_path,
        "bystander",
        gate_cmd=f'"{sys.executable}" -c "pass"',
        review_enabled=False,
    )
    (repo / "broken.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run([GIT, "add", "broken.py"], cwd=repo, check=True)
    (bystander / "other.py").write_text("y = 2\n", encoding="utf-8")
    subprocess.run([GIT, "add", "other.py"], cwd=bystander, check=True)

    target_count_before = subprocess.check_output([GIT, "-C", str(repo), "rev-list", "--count", "HEAD"], text=True).strip()
    bystander_head_before = subprocess.check_output([GIT, "-C", str(bystander), "rev-parse", "HEAD"], text=True).strip()
    bystander_count_before = subprocess.check_output(
        [GIT, "-C", str(bystander), "rev-list", "--count", "HEAD"], text=True
    ).strip()
    capsys.readouterr()

    code = cli.main(["-C", str(bystander), "archon", "gate", "--worktree", str(repo), "-m", "should refuse"])
    out = capsys.readouterr()
    assert code == 3
    payload = _parse_one_json_line(out.out)
    assert payload["ok"] is False
    assert payload["refused"] == "verify"

    assert subprocess.check_output([GIT, "-C", str(repo), "rev-list", "--count", "HEAD"], text=True).strip() == target_count_before
    assert subprocess.check_output([GIT, "-C", str(bystander), "rev-parse", "HEAD"], text=True).strip() == bystander_head_before
    assert subprocess.check_output(
        [GIT, "-C", str(bystander), "rev-list", "--count", "HEAD"], text=True
    ).strip() == bystander_count_before


def test_gate_review_requirement_and_pin(tmp_path, monkeypatch, capsys):
    _isolate_home(tmp_path, monkeypatch)
    repo, _ = _make_adopted_repo(
        tmp_path,
        "reviewed-repo",
        gate_cmd=f'"{sys.executable}" -c "pass"',
        review_enabled=True,
    )
    (repo / "mod.py").write_text("z = 3\n", encoding="utf-8")
    subprocess.run([GIT, "add", "mod.py"], cwd=repo, check=True)
    count_before = subprocess.check_output([GIT, "-C", str(repo), "rev-list", "--count", "HEAD"], text=True).strip()
    capsys.readouterr()

    code = cli.main(["archon", "gate", "--worktree", str(repo), "-m", "needs review"])
    payload = _parse_one_json_line(capsys.readouterr().out)
    assert code == 3
    assert payload["ok"] is False
    assert payload["refused"] == "review"

    code = cli.main(["archon", "gate", "--worktree", str(repo), "-m", "missing review id", "--review", "R-99999"])
    payload = _parse_one_json_line(capsys.readouterr().out)
    assert code == 3
    assert payload["ok"] is False
    assert payload["refused"] == "review"

    reviews_dir = repo / ".polyctl" / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    (reviews_dir / "R-1002.json").write_text(
        json.dumps({"id": "R-1002", "state": "running", "tree": "0" * 40}),
        encoding="utf-8",
    )
    code = cli.main(["archon", "gate", "--worktree", str(repo), "-m", "unfinished review", "--review", "R-1002"])
    payload = _parse_one_json_line(capsys.readouterr().out)
    assert code == 3
    assert payload["ok"] is False
    assert payload["refused"] == "review"

    (reviews_dir / "R-1001.json").write_text(
        json.dumps({"id": "R-1001", "state": "finished", "tree": "0" * 40}),
        encoding="utf-8",
    )
    code = cli.main(["archon", "gate", "--worktree", str(repo), "-m", "wrong tree", "--review", "R-1001"])
    payload = _parse_one_json_line(capsys.readouterr().out)
    assert code == 3
    assert payload["ok"] is False
    assert payload["refused"] == "review"
    assert subprocess.check_output([GIT, "-C", str(repo), "rev-list", "--count", "HEAD"], text=True).strip() == count_before


def test_gate_nothing_staged_and_invalid_worktree(tmp_path, monkeypatch, capsys):
    _isolate_home(tmp_path, monkeypatch)
    repo, _ = _make_adopted_repo(
        tmp_path,
        "clean-repo",
        gate_cmd=f'"{sys.executable}" -c "pass"',
        review_enabled=False,
    )
    sub = repo / "nested"
    sub.mkdir()
    not_repo = tmp_path / "plain-dir"
    not_repo.mkdir()
    capsys.readouterr()

    code = cli.main(["archon", "gate", "--worktree", str(repo), "-m", "empty stage"])
    payload = _parse_one_json_line(capsys.readouterr().out)
    assert code == 3
    assert payload["ok"] is False
    assert payload["refused"] == "staged"

    code = cli.main(["archon", "gate", "--worktree", str(not_repo), "-m", "not git"])
    payload = _parse_one_json_line(capsys.readouterr().out)
    assert code == 2
    assert payload["ok"] is False

    code = cli.main(["archon", "gate", "--worktree", str(sub), "-m", "subdir"])
    payload = _parse_one_json_line(capsys.readouterr().out)
    assert code == 2
    assert payload["ok"] is False

    code = cli.main(["archon", "gate", "--worktree", str(repo), "-m", "   "])
    payload = _parse_one_json_line(capsys.readouterr().out)
    assert code == 2
    assert payload["ok"] is False


def test_record_chained_ledger_and_tamper_detection(project, tmp_path, capsys):
    from polyctl import archon

    root = project["root"]
    sha1 = "a" * 40
    sha2 = "b" * 40

    code1 = cli.main([
        "-C", root, "archon", "record",
        "--run", "r1", "--event", "landed", "--sha", sha1, "--undo", f"git revert {sha1}",
        "--item", "IT-1", "--result", "ok",
    ])
    res1 = _parse_one_json_line(capsys.readouterr().out)
    assert code1 == 0
    assert res1["ok"] is True
    assert res1["ordinal"] == 1
    assert res1["previous"] is None

    code2 = cli.main([
        "-C", root, "archon", "record",
        "--run", "r2", "--event", "landed", "--sha", sha2, "--undo", f"git revert {sha2}",
    ])
    res2 = _parse_one_json_line(capsys.readouterr().out)
    assert code2 == 0
    assert res2["ok"] is True
    assert res2["ordinal"] == 2
    assert res2["previous"].startswith("sha256:")

    ledger_path = archon.archon_ledger_path(root)
    rows = storage.read_chained_jsonl(ledger_path, archon.ARCHON_CHAIN)
    assert len(rows) == 2
    assert rows[0]["run"] == "r1"
    assert rows[0]["item"] == "IT-1"
    assert rows[1]["run"] == "r2"
    assert rows[1]["sha"] == sha2

    assert cli.main(["-C", root, "doctor", "--consistency"]) == 0
    capsys.readouterr()
    assert "archon-unreadable" not in dict(cli.doctor_problems(project))

    bad_code = cli.main(["-C", root, "archon", "record", "--run", "r3", "--event", "landed", "--sha", "xyz", "--undo", "u"])
    bad_res = _parse_one_json_line(capsys.readouterr().out)
    assert bad_code == 2
    assert bad_res["ok"] is False

    backup_dir = tmp_path / "backups"
    assert cli.main(["-C", root, "backup", "--to", str(backup_dir)]) == 0
    capsys.readouterr()

    with open(ledger_path, "r+b") as fh:
        raw = fh.read()
        tampered = raw.replace(b'"r1"', b'"r9"', 1)
        assert tampered != raw
        fh.seek(0)
        fh.write(tampered)
        fh.truncate()

    with pytest.raises(storage.LedgerCorruption):
        storage.read_chained_jsonl(ledger_path, archon.ARCHON_CHAIN)

    assert cli.main(["-C", root, "doctor", "--consistency"]) == 1
    consistency_out = capsys.readouterr().out
    assert "archon" in consistency_out.lower()
    assert "archon-unreadable" in dict(cli.doctor_problems(project))

    append_corrupt = cli.main(["-C", root, "archon", "record", "--run", "r3", "--event", "landed", "--sha", sha1, "--undo", "u"])
    corrupt_res = _parse_one_json_line(capsys.readouterr().out)
    assert append_corrupt == 3
    assert corrupt_res["ok"] is False

    snapshots = list((backup_dir / A.project_key(root)).iterdir())
    assert len(snapshots) == 1
    restored, unverified = A.restore_backup(root, str(snapshots[0]))
    assert ".polyctl/ledger/archon.jsonl" in restored
    assert unverified == []
    assert cli.main(["-C", root, "doctor", "--consistency"]) == 0
    capsys.readouterr()


def test_runs_and_leftovers_with_fake_archon(tmp_path, monkeypatch, capsys):
    _isolate_home(tmp_path, monkeypatch)
    repo, _ = _make_adopted_repo(
        tmp_path,
        "main-repo",
        gate_cmd=f'"{sys.executable}" -c "pass"',
        review_enabled=False,
    )
    wt_done = tmp_path / "wt-done"
    wt_active = tmp_path / "wt-active"
    subprocess.run([GIT, "-C", str(repo), "worktree", "add", "-q", str(wt_done), "-b", "is/done-1"], check=True)
    subprocess.run([GIT, "-C", str(repo), "worktree", "add", "-q", str(wt_active), "-b", "is/active-2"], check=True)

    runs_payload = {
        "runs": [
            {"id": "run-1", "workflow": "fab-fix", "status": "completed", "branch": "is/done-1", "worktree": str(wt_done)},
            {"id": "run-2", "workflow": "fab-fix", "status": "running", "branch": "is/active-2", "worktree": str(wt_active)},
        ]
    }
    runs_json_file = tmp_path / "fake-runs.json"
    runs_json_file.write_text(json.dumps(runs_payload), encoding="utf-8")

    bin_dir = tmp_path / "fake-bin"
    _write_fake_archon(
        bin_dir,
        "import os, pathlib, sys\n"
        "args = sys.argv[1:]\n"
        "if args == ['--version']:\n"
        "    print('archon 0.14.0')\n"
        "    sys.exit(0)\n"
        "if args == ['workflow', 'status', '--json']:\n"
        f"    print(pathlib.Path({str(runs_json_file)!r}).read_text(encoding='utf-8'))\n"
        "    sys.exit(0)\n"
        "sys.exit(2)\n",
    )
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + _path_without_archon(tmp_path))
    capsys.readouterr()

    code = cli.main(["-C", str(repo), "archon", "runs"])
    runs_out = _parse_one_json_line(capsys.readouterr().out)
    assert code == 0
    assert runs_out["ok"] is True
    assert runs_out["runs"] == [
        {"run": "run-1", "workflow": "fab-fix", "state": "completed", "branch": "is/done-1"},
        {"run": "run-2", "workflow": "fab-fix", "state": "running", "branch": "is/active-2"},
    ]

    code = cli.main(["archon", "leftovers", "--repo", str(repo)])
    left_out = _parse_one_json_line(capsys.readouterr().out)
    assert code == 3
    assert left_out["ok"] is False
    assert left_out["refused"] == "leftovers"
    assert len(left_out["worktrees"]) == 1
    assert os.path.realpath(left_out["worktrees"][0]["path"]) == os.path.realpath(str(wt_done))
    assert left_out["branches"] == ["is/done-1"]
    assert wt_done.is_dir() and wt_active.is_dir()

    subprocess.run([GIT, "-C", str(repo), "worktree", "remove", str(wt_done)], check=True)
    subprocess.run([GIT, "-C", str(repo), "branch", "-D", "is/done-1"], check=True)

    code = cli.main(["archon", "leftovers", "--repo", str(repo)])
    clean_out = _parse_one_json_line(capsys.readouterr().out)
    assert code == 0
    assert clean_out["ok"] is True
    assert clean_out["worktrees"] == []
    assert clean_out["branches"] == []

    _write_fake_archon(
        bin_dir,
        "import sys\n"
        "print('not valid json output')\n"
        "sys.exit(0)\n",
    )
    for subcmd in (["runs"], ["leftovers", "--repo", str(repo)]):
        code = cli.main(["-C", str(repo), "archon"] + subcmd)
        captured = capsys.readouterr()
        err_out = _parse_one_json_line(captured.out)
        assert code == 2
        assert err_out["ok"] is False
        assert "Traceback" not in captured.err

    not_repo = tmp_path / "not-a-repo"
    not_repo.mkdir()
    code = cli.main(["archon", "leftovers", "--repo", str(not_repo)])
    bad_repo = _parse_one_json_line(capsys.readouterr().out)
    assert code == 2
    assert bad_repo["ok"] is False


def test_notify_calls_existing_channels_and_never_answers(project, monkeypatch, capsys):
    root = project["root"]
    dec = A.ask(root, "Deploy release?", ["yes", "no"], cfg=project)

    sent = {"telegram": [], "ntfy": [], "email": [], "answered": False}
    monkeypatch.setattr(telegram, "send", lambda text, r=None, keyboard=None: (sent["telegram"].append((text, r)), 1)[1])
    monkeypatch.setattr(ntfy, "send", lambda text, r=None, level=None: (sent["ntfy"].append((text, r, level)), True)[1])
    monkeypatch.setattr(email, "send", lambda subj, body, r=None, opener=None: (sent["email"].append((subj, body, r)), False)[1])

    def _forbid_answer(*args, **kwargs):
        sent["answered"] = True
        raise AssertionError("notify must never answer a decision")

    monkeypatch.setattr(A, "answer", _forbid_answer)
    capsys.readouterr()

    code = cli.main(["-C", root, "archon", "notify", "--run", "r42", "--text", "Owner gate waiting"])
    res = _parse_one_json_line(capsys.readouterr().out)
    assert code == 0
    assert res["ok"] is True
    assert res["run"] == "r42"
    assert res["delivered"] is True
    assert sent["answered"] is False
    assert len(sent["telegram"]) == 1 and "r42" in sent["telegram"][0][0] and "Owner gate waiting" in sent["telegram"][0][0]
    assert len(sent["ntfy"]) == 1 and "Owner gate waiting" in sent["ntfy"][0][0]
    assert len(sent["email"]) == 1

    decisions = [d for d in A.decisions(root) if d["id"] == dec["id"]]
    assert len(decisions) == 1 and decisions[0]["state"] == "open" and decisions[0]["answer"] is None

    bad = cli.main(["-C", root, "archon", "notify", "--run", " ", "--text", "hi"])
    bad_res = _parse_one_json_line(capsys.readouterr().out)
    assert bad == 2
    assert bad_res["ok"] is False


def test_python39_syntax_no_archon_import_and_exit_code_contract():
    src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "polyctl", "archon.py")
    source = open(src_path, encoding="utf-8").read()
    tree = ast.parse(source, src_path)

    for node in ast.walk(tree):
        if hasattr(ast, "Match"):
            assert not isinstance(node, ast.Match), "Python 3.9 does not support match/case"
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "archon" and not alias.name.startswith("archon.")
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                assert node.module != "archon" and not node.module.startswith("archon.")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ann_nodes = [node.returns] + [a.annotation for a in node.args.args + node.args.kwonlyargs]
            for ann in ann_nodes:
                if ann is not None:
                    for inner in ast.walk(ann):
                        if isinstance(inner, ast.BinOp) and isinstance(inner.op, ast.BitOr):
                            raise AssertionError("Python 3.9 does not support X | Y type annotations at runtime")

    # Exit code contract sanity check: 0 ok, 2 usage/missing, 3 refused/leftovers
    from polyctl import archon
    assert archon.EXIT_OK == 0
    assert archon.EXIT_USAGE == 2
    assert archon.EXIT_REFUSED == 3
