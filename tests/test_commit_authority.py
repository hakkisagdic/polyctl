import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from types import SimpleNamespace

import pytest

from polyctl import cli, lib as A, storage


def _git(root, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _repo_with_change(root):
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    path = os.path.join(root, "src", "a.py")
    open(path, "w", encoding="utf-8").write("value = 1\n")
    _git(root, "add", "src/a.py")
    _git(root, "commit", "-q", "-m", "product base")
    open(path, "w", encoding="utf-8").write("value = 2\n")
    _git(root, "add", "src/a.py")
    return path


def _approved_reviewer():
    script = "; ".join(
        f"print({line!r})"
        for line in (
            "VERDICT: APPROVED",
            "BLOCKER: 0",
            "HIGH: 0",
            "MEDIUM: 0",
            "LOW: 0",
            "",
            "## Bulgular",
            "Bulgu yok.",
        )
    )
    return [sys.executable, "-c", script, "{prompt}"]


def _review_args():
    return SimpleNamespace(boundary="product change", timeout=30, paths=None, commits=None)


def _write_approved_review(project, tree=None, candidate=None):
    root = project["root"]
    lines = ["# Review approved.md", ""]
    evidence = None
    if candidate is not None:
        scope = A.candidate_scope(candidate)
        lines.append(A.review_evidence_line(evidence := {
            "schema": 2,
            "kind": "index-candidate",
            "authorizable": True,
            "candidate": candidate,
            "scope": scope,
            "diff_digest": "sha256:" + hashlib.sha256(
                A.candidate_diff(root, candidate, scope)
            ).hexdigest(),
            "reviewer": {"id": "independent-reviewer", "family": "independent", "fallback": False},
        }))
    lines.extend([
        "- reviewer: `independent-reviewer`",
        "- implementer: `kiro/s1`",
    ])
    if tree is not None:
        lines.append(f"- tree: `{tree}`")
    lines.extend(
        [
            "- boundary: product change",
            "",
            "VERDICT: APPROVED",
            "BLOCKER: 0",
            "HIGH: 0",
            "MEDIUM: 0",
            "LOW: 0",
            "",
        ]
    )
    path = os.path.join(root, project["reviews"], "approved.md")
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    A.record_review(root, "approved.md", open(path, "rb").read(), evidence, "APPROVED")
    return path


def _tamper_review(path, field):
    body = open(path, encoding="utf-8").read()
    evidence = A.review_evidence(body)
    original = A.review_evidence_line(evidence)
    if field == "candidate":
        evidence["candidate"]["changed_count"] += 1
    elif field == "scope":
        evidence["scope"]["digest"] = "sha256:tampered"
    elif field == "diff_digest":
        evidence["diff_digest"] = "sha256:tampered"
    else:
        raise AssertionError(f"unknown review tamper field: {field}")
    open(path, "w", encoding="utf-8").write(
        body.replace(original, A.review_evidence_line(evidence), 1)
    )
    # A forger who can edit the file can append its record too; the evidence
    # checks are what refuse it then.
    A.record_review(os.path.dirname(os.path.dirname(path)), os.path.basename(path),
                    open(path, "rb").read(), evidence, A._review_verdict(body))


def _allow_commit_prerequisites(monkeypatch, tree, candidate):
    monkeypatch.setattr(
        A,
        "latest_verification",
        lambda root: {
            "id": "V-1",
            "passed": True,
            "tree": tree,
            "gates": [],
            "candidate": candidate,
            "candidate_ready": True,
            "isolation_inputs": A.gate_inputs(root),
        },
    )
    monkeypatch.setattr(A, "plan_drift", lambda root: [])
    monkeypatch.setattr(A, "hold_state", lambda root: None)
    monkeypatch.setattr(A, "urgent_messages", lambda *args, **kwargs: [])


def test_tree_digest_hashes_untracked_content_and_ignores_staging(project):
    root = project["root"]
    path = os.path.join(root, "new-product.txt")
    open(path, "w", encoding="utf-8").write("alpha")
    alpha = A.tree_digest(root, project)

    open(path, "w", encoding="utf-8").write("bravo")
    bravo = A.tree_digest(root, project)
    assert bravo != alpha

    _git(root, "add", "new-product.txt")
    assert A.tree_digest(root, project) == bravo


def test_tree_digest_changes_for_tracked_product_content(project):
    root = project["root"]
    path = _repo_with_change(root)
    changed = A.tree_digest(root, project)
    open(path, "w", encoding="utf-8").write("value = 3\n")
    assert A.tree_digest(root, project) != changed


def test_verify_record_does_not_invalidate_its_own_tree(project, tmp_path, monkeypatch):
    root = project["root"]
    verification_ledger = os.path.join(root, ".polyctl", "ledger", "verifications.jsonl")
    open(verification_ledger, "w", encoding="utf-8").write("")
    _git(root, "add", ".polyctl/ledger/verifications.jsonl")
    _git(root, "commit", "-q", "-m", "track verification ledger")

    argv = [sys.executable, "-c", 'print("gate ok")']
    command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    gates = {
        "gates": {"smoke": {"run": command, "expect": "exit_zero", "timeout": 30}},
        "profiles": {"quick": ["smoke"]},
        "default_profile": "quick",
    }
    open(os.path.join(root, ".polyctl", "gates.json"), "w", encoding="utf-8").write(
        json.dumps(gates)
    )
    monkeypatch.setattr(A, "GATE_LOCK", str(tmp_path / "gate.lock"))

    before = A.tree_digest(root, project)
    assert cli.cmd_verify(project, SimpleNamespace(profile="quick", wait=0)) == 0
    after = A.tree_digest(root, project)
    record = A.latest_verification(root)

    assert after == before
    assert record is not None and record["passed"] is True and record["tree"] == after


def test_gate_lock_liveness_probe_does_not_signal_windows_process(tmp_path, monkeypatch):
    from polyctl import procs

    lock = tmp_path / "gate.lock"
    lock.write_text(json.dumps({"root": "project", "pid": 4242, "at": 1}), encoding="utf-8")
    monkeypatch.setattr(A, "GATE_LOCK", str(lock))
    monkeypatch.setattr(A.os, "name", "nt")
    # Where Windows does not answer for the process itself, the snapshot is read (WINDOWS-PID-ALIVE); on
    # Windows it would answer, for a pid 4242 that is not this test's.
    monkeypatch.setattr(procs, "alive", lambda pid: None)
    monkeypatch.setattr(procs, "all_pids", lambda: [4242])

    def unexpected_signal(*args):
        raise AssertionError(f"Windows liveness probe sent signal: {args}")

    monkeypatch.setattr(A.os, "kill", unexpected_signal)
    assert A.gate_lock_holder()["pid"] == 4242

    monkeypatch.setattr(procs, "all_pids", lambda: [])
    assert A.gate_lock_holder() is None
    assert not lock.exists()


def test_review_artifact_does_not_invalidate_reviewed_tree(project):
    root = project["root"]
    _repo_with_change(root)
    cfg = dict(
        project,
        reviewer={"id": "independent-reviewer", "family": "test", "argv": _approved_reviewer()},
    )
    before = A.tree_digest(root, cfg)
    candidate = A.index_candidate(root)

    assert cli.cmd_review(cfg, _review_args()) == 0

    names = [name for name in os.listdir(os.path.join(root, cfg["reviews"])) if name.endswith(".md")]
    assert len(names) == 1
    body = open(os.path.join(root, cfg["reviews"], names[0]), encoding="utf-8").read()
    recorded = re.search(r"tree:\s*`([^`]+)`", body).group(1)
    evidence = A.review_evidence(body)
    assert recorded == before == A.tree_digest(root, cfg)
    assert evidence["authorizable"] is True
    assert evidence["candidate"]["digest"] == candidate["digest"]


def test_commit_ok_refuses_legacy_review_without_candidate_evidence(project, monkeypatch, capsys):
    root = project["root"]
    _repo_with_change(root)
    tree = A.tree_digest(root, project)
    candidate = A.index_candidate(root)
    _write_approved_review(project, tree)
    _allow_commit_prerequisites(monkeypatch, tree, candidate)

    code = cli.cmd_commit_ok(project, SimpleNamespace(verify=False, profile=None))
    output = capsys.readouterr().out

    assert code == 1
    assert "no APPROVED prospective review is bound" in output
    assert "GRANTED" not in output


def test_commit_ok_refuses_when_grant_cannot_be_persisted(project, monkeypatch, capsys):
    root = project["root"]
    _repo_with_change(root)
    tree = A.tree_digest(root, project)
    candidate = A.index_candidate(root)
    _write_approved_review(project, tree, candidate)
    _allow_commit_prerequisites(monkeypatch, tree, candidate)

    def fail_record(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(A, "record_authority", fail_record)
    code = cli.cmd_commit_ok(project, SimpleNamespace(verify=False, profile=None))
    output = capsys.readouterr().out

    assert code == 1
    assert "could not persist authority grant" in output
    assert "GRANTED" not in output


def test_record_authority_persists_the_complete_grant(project):
    root = project["root"]
    A.record_authority(
        root,
        True,
        [],
        "sha256:tree",
        "V-1",
        "C-1",
        review="review.md",
        reviewer="independent-reviewer",
    )
    path = os.path.join(root, ".polyctl", "ledger", "authority.jsonl")
    row = json.loads(open(path, encoding="utf-8").read().splitlines()[-1])
    assert row == {
        "previous": None,
        "ordinal": 1,
        "at": row["at"],
        "granted": True,
        "token": "C-1",
        "reasons": [],
        "tree": "sha256:tree",
        "verification": "V-1",
        "review": "review.md",
        "reviewer": "independent-reviewer",
    }


def test_commit_ok_records_the_exact_index_candidate(project, monkeypatch, capsys):
    root = project["root"]
    _repo_with_change(root)
    tree = A.tree_digest(root, project)
    candidate = A.index_candidate(root)
    _write_approved_review(project, tree, candidate)
    _allow_commit_prerequisites(monkeypatch, tree, candidate)

    code = cli.cmd_commit_ok(project, SimpleNamespace(verify=False, profile=None))
    output = capsys.readouterr().out

    assert code == 0 and "GRANTED" in output
    ledger = os.path.join(root, ".polyctl", "ledger", "authority.jsonl")
    row = json.loads(open(ledger, encoding="utf-8").read().splitlines()[-1])
    assert row["schema"] == 2
    assert row["candidate"]["digest"] == candidate["digest"]
    assert row["candidate"]["index_tree"] == candidate["index_tree"]
    assert row["scope"]["kind"] == "full-index"


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        (
            "candidate",
            "review evidence candidate does not exactly match the current index candidate",
        ),
        (
            "scope",
            "review evidence scope does not exactly match the current candidate",
        ),
        (
            "diff_digest",
            "review evidence diff digest does not match the exact candidate diff",
        ),
    ],
)
def test_commit_ok_refuses_tampered_review_integrity(
    project, monkeypatch, capsys, field, reason
):
    root = project["root"]
    _repo_with_change(root)
    tree = A.tree_digest(root, project)
    candidate = A.index_candidate(root)
    review_path = _write_approved_review(project, tree, candidate)
    _tamper_review(review_path, field)
    _allow_commit_prerequisites(monkeypatch, tree, candidate)

    code = cli.cmd_commit_ok(project, SimpleNamespace(verify=False, profile=None))
    output = capsys.readouterr().out

    assert code == 1
    assert reason in output
    assert "GRANTED" not in output


def test_commit_ok_refuses_index_mutation_after_review_and_verification(
    project, monkeypatch, capsys
):
    root = project["root"]
    path = _repo_with_change(root)
    tree = A.tree_digest(root, project)
    reviewed = A.index_candidate(root)
    _write_approved_review(project, tree, reviewed)
    _allow_commit_prerequisites(monkeypatch, tree, reviewed)

    open(path, "w", encoding="utf-8").write("value = 3\n")
    _git(root, "add", "src/a.py")
    current = A.index_candidate(root)
    assert current["digest"] != reviewed["digest"]

    code = cli.cmd_commit_ok(project, SimpleNamespace(verify=False, profile=None))
    output = capsys.readouterr().out

    assert code == 1
    assert "index changed since V-1" in output
    assert "no APPROVED prospective review is bound" in output
    assert "GRANTED" not in output


def _install_passing_gate(project, tmp_path, monkeypatch):
    root = project["root"]
    argv = [sys.executable, "-c", 'print("gate ok")']
    command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    gates = {
        "gates": {"smoke": {"run": command, "expect": "exit_zero", "timeout": 30}},
        "profiles": {"quick": ["smoke"]},
        "default_profile": "quick",
    }
    open(os.path.join(root, ".polyctl", "gates.json"), "w", encoding="utf-8").write(
        json.dumps(gates)
    )
    monkeypatch.setattr(A, "GATE_LOCK", str(tmp_path / "gate.lock"))


def test_verify_records_exact_staged_candidate_before_and_after(
    project, tmp_path, monkeypatch
):
    root = project["root"]
    _repo_with_change(root)
    _install_passing_gate(project, tmp_path, monkeypatch)
    expected = A.index_candidate(root)

    assert cli.cmd_verify(project, SimpleNamespace(profile="quick", wait=0)) == 0
    record = A.latest_verification(root)

    assert record["passed"] is True
    assert record["candidate"] == expected
    assert record["candidate_after"] == expected
    assert record["candidate_ready"] is True
    assert record["candidate_issues"] == []
    assert record["candidate"]["changed_paths"] == ["src/a.py"]


def test_verify_refuses_partially_staged_product_candidate(
    project, tmp_path, monkeypatch
):
    root = project["root"]
    path = _repo_with_change(root)
    expected = A.index_candidate(root)
    open(path, "w", encoding="utf-8").write("value = 3\n")
    _install_passing_gate(project, tmp_path, monkeypatch)

    assert cli.cmd_verify(project, SimpleNamespace(profile="quick", wait=0)) == 1
    record = A.latest_verification(root)
    issue = "unstaged product changes differ from the index: src/a.py"

    assert record["passed"] is False
    assert record["candidate_ready"] is False
    assert record["candidate"] == expected
    assert record["candidate_after"] == expected
    assert record["candidate_issues"] == [issue]
    isolation = next(gate for gate in record["gates"] if gate["name"] == "candidate-isolation")
    assert isolation == {
        "name": "candidate-isolation",
        "passed": False,
        "detail": issue,
        "exit": 1,
        "seconds": 0,
    }


def test_commit_ok_refuses_approved_retrospective_review_for_new_candidate(
    project, monkeypatch, capsys
):
    root = project["root"]
    path = _repo_with_change(root)
    _git(root, "commit", "-q", "-m", "reviewed change")
    cfg = dict(
        project,
        reviewer={"id": "independent-reviewer", "family": "test", "argv": _approved_reviewer()},
    )
    args = _review_args()
    args.commits = "HEAD~1..HEAD"

    assert cli.cmd_review(cfg, args) == 0
    names = [name for name in os.listdir(os.path.join(root, cfg["reviews"])) if name.endswith(".md")]
    assert len(names) == 1
    body = open(os.path.join(root, cfg["reviews"], names[0]), encoding="utf-8").read()
    evidence = A.review_evidence(body)
    assert "VERDICT: APPROVED" in body
    assert evidence["kind"] == "commit-range"
    assert evidence["authorizable"] is False
    assert evidence["commits"] == "HEAD~1..HEAD"

    open(path, "w", encoding="utf-8").write("value = 3\n")
    _git(root, "add", "src/a.py")
    tree = A.tree_digest(root, cfg)
    candidate = A.index_candidate(root)
    _allow_commit_prerequisites(monkeypatch, tree, candidate)
    assert A.latest_candidate_review(root, cfg["reviews"], candidate["digest"]) is None
    capsys.readouterr()

    code = cli.cmd_commit_ok(cfg, SimpleNamespace(verify=False, profile=None))
    output = capsys.readouterr().out

    assert code == 1
    assert "no APPROVED prospective review is bound to this staged candidate" in output
    assert "GRANTED" not in output


def _persist_exact_candidate_grant(project):
    root = project["root"]
    candidate = A.index_candidate(root)
    review_path = _write_approved_review(project, A.tree_digest(root, project), candidate)
    review_name = os.path.basename(review_path)
    verification = {
        "id": "V-persisted",
        "schema": 2,
        "passed": True,
        "candidate_ready": True,
        "isolation_inputs": A.gate_inputs(root),
        "candidate": candidate,
        "candidate_after": candidate,
        "gates": [],
    }
    A.record_verification(root, verification)
    A.record_authority(
        root,
        True,
        [],
        A.tree_digest(root, project),
        verification["id"],
        "C-persisted",
        review=review_name,
        reviewer="independent-reviewer",
        candidate=candidate,
        scope=A.candidate_scope(candidate),
    )
    return candidate


def test_commit_check_accepts_exact_persisted_grant_without_mutating_ledger(
    project, capsys
):
    root = project["root"]
    _repo_with_change(root)
    candidate = _persist_exact_candidate_grant(project)
    ledger = os.path.join(root, ".polyctl", "ledger", "authority.jsonl")
    before = open(ledger, "rb").read()

    code = cli.cmd_commit_check(project, SimpleNamespace())
    output = capsys.readouterr().out

    assert code == 0
    assert "AUTHORIZED" in output
    assert candidate["index_tree"] in output
    assert A.latest_authority_decision(root)["token"] == "C-persisted"
    assert open(ledger, "rb").read() == before


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        (
            "scope",
            "granted review scope does not exactly match the persisted authority grant",
        ),
        (
            "diff_digest",
            "review evidence diff digest does not match the exact candidate diff",
        ),
    ],
)
def test_commit_check_refuses_tampered_review_integrity_without_mutating_ledger(
    project, capsys, field, reason
):
    root = project["root"]
    _repo_with_change(root)
    _persist_exact_candidate_grant(project)
    review_path = os.path.join(root, project["reviews"], "approved.md")
    _tamper_review(review_path, field)
    ledger = os.path.join(root, ".polyctl", "ledger", "authority.jsonl")
    before = open(ledger, "rb").read()

    code = cli.cmd_commit_check(project, SimpleNamespace())
    output = capsys.readouterr().out

    assert code == 1
    assert "COMMIT REFUSED" in output
    assert reason in output
    assert open(ledger, "rb").read() == before


def test_commit_check_refuses_changed_index_without_mutating_ledger(project, capsys):
    root = project["root"]
    path = _repo_with_change(root)
    _persist_exact_candidate_grant(project)
    ledger = os.path.join(root, ".polyctl", "ledger", "authority.jsonl")
    before = open(ledger, "rb").read()

    open(path, "w", encoding="utf-8").write("value = 3\n")
    _git(root, "add", "src/a.py")
    code = cli.cmd_commit_check(project, SimpleNamespace())
    output = capsys.readouterr().out

    assert code == 1
    assert "COMMIT REFUSED" in output
    assert "latest grant does not match the current index candidate" in output
    assert open(ledger, "rb").read() == before



def _persist_three_authority_decisions(project):
    root = project["root"]
    A.record_authority(
        root, False, ["older refusal"], "sha256:older-1", "V-old-1", "R-1"
    )
    A.record_authority(
        root, False, ["newer refusal"], "sha256:older-2", "V-old-2", "R-2"
    )
    return _persist_exact_candidate_grant(project)


@pytest.mark.parametrize(
    "mutation",
    ["middle-edit", "middle-delete", "reorder", "wrong-predecessor-append"],
)
def test_commit_check_refuses_a_broken_authority_chain_without_mutating_it(
    project, capsys, mutation
):
    root = project["root"]
    _repo_with_change(root)
    _persist_three_authority_decisions(project)
    ledger = os.path.join(root, ".polyctl", "ledger", "authority.jsonl")
    rows = [json.loads(line) for line in open(ledger, encoding="utf-8")]

    if mutation == "middle-edit":
        rows[1]["tree"] = "sha256:tampered"
    elif mutation == "middle-delete":
        del rows[1]
    elif mutation == "reorder":
        rows[0], rows[1] = rows[1], rows[0]
    else:
        forged = dict(rows[-1])
        forged["previous"] = "sha256:forged-predecessor"
        forged["token"] = "C-forged"
        rows.append(forged)

    with open(ledger, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    if mutation == "wrong-predecessor-append":
        storage._record_committed_length(ledger, len(rows), None)
    before = open(ledger, "rb").read()

    code = cli.cmd_commit_check(project, SimpleNamespace())
    output = capsys.readouterr().out

    assert code == 1
    assert "COMMIT REFUSED" in output
    assert "authority ledger is unreadable: broken hash chain" in output
    assert "AUTHORIZED" not in output
    assert open(ledger, "rb").read() == before


def test_commit_ok_refuses_to_append_to_an_unchained_legacy_ledger(
    project, monkeypatch, capsys
):
    root = project["root"]
    _repo_with_change(root)
    tree = A.tree_digest(root, project)
    candidate = A.index_candidate(root)
    _write_approved_review(project, tree, candidate)
    _allow_commit_prerequisites(monkeypatch, tree, candidate)
    ledger = os.path.join(root, ".polyctl", "ledger", "authority.jsonl")
    open(ledger, "w", encoding="utf-8").write(
        '{"granted":false,"token":"legacy"}\n'
    )
    storage._record_committed_length(ledger, 1, None)
    before = open(ledger, "rb").read()

    code = cli.cmd_commit_ok(project, SimpleNamespace(verify=False, profile=None))
    output = capsys.readouterr().out

    assert code == 1
    assert "REFUSED" in output
    assert "could not persist authority grant" in output
    assert "has no 'previous' field" in output
    assert (
        "legacy ledger — archive .polyctl/ledger/authority.jsonl and re-run "
        "polyctl commit-ok (docs/ledger.md)"
    ) in output
    assert "GRANTED" not in output
    assert open(ledger, "rb").read() == before


def test_digest_surfaces_broken_authority_chain_without_trusting_counts(
    project, monkeypatch, capsys
):
    root = project["root"]
    A.record_authority(
        root, False, ["expected refusal"], "sha256:first", "V-1", "R-1"
    )
    A.record_authority(
        root, True, [], "sha256:second", "V-2", "C-2"
    )
    ledger = os.path.join(root, ".polyctl", "ledger", "authority.jsonl")
    rows = [json.loads(line) for line in open(ledger, encoding="utf-8")]
    rows[0]["tree"] = "sha256:tampered"
    with open(ledger, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")

    monkeypatch.setattr(A, "sh", lambda *args, **kwargs: "")
    monkeypatch.setattr(A, "decisions", lambda root, state=None: [])
    monkeypatch.setattr(
        A,
        "board",
        lambda root: {state: [] for state in A.BOARD_STATES},
    )
    monkeypatch.setattr(A, "reviews", lambda *args, **kwargs: [])
    monkeypatch.setattr(A, "account_usage", lambda timeout=20, adapter_id=None: None)
    monkeypatch.setattr(A, "credit_usage", lambda adapter_id, monthly_budget=None: {"days": {}})

    result = A.digest(root, project)
    assert result["authority"]["integrity"] == "broken"
    assert result["authority"]["granted"] == 0
    assert result["authority"]["refused"] == 0
    assert "broken hash chain" in result["authority"]["error"]

    monkeypatch.setattr(A, "digest", lambda *args, **kwargs: result)
    monkeypatch.setattr(A, "busy", lambda *args, **kwargs: ("idle", 0, ""))
    monkeypatch.setattr(A, "spinning", lambda root: None)
    code = cli.cmd_digest(project, SimpleNamespace(days=1, n=5))
    output = capsys.readouterr().out

    assert code == 0
    assert "AUTHORITY LEDGER INTEGRITY BROKEN" in output
    # Captured output is no terminal, so it carries no colour (CLI-ROBUST): the line is looked for as printed.
    assert "commit-ok  0 granted" not in output


def _install_current_hook_for_git(root, project, tmp_path, monkeypatch):
    bin_dir = tmp_path / "hook-bin"
    bin_dir.mkdir(exist_ok=True)
    src_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
    if os.name == "nt":
        shim = bin_dir / "polyctl.cmd"
        shim.write_text(
            f'@echo off\r\nset "PYTHONPATH={src_root};%PYTHONPATH%"\r\n"{sys.executable}" -m polyctl %*\r\n',
            encoding="utf-8",
        )
    else:
        shim = bin_dir / "polyctl"
        shim.write_text(
            f'#!/bin/sh\nPYTHONPATH={shlex.quote(src_root)} exec {shlex.quote(sys.executable)} -m polyctl "$@"\n',
            encoding="utf-8",
        )
        shim.chmod(0o755)
    monkeypatch.setenv("HOME", A.HOME)
    monkeypatch.setenv("USERPROFILE", A.HOME)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    assert cli.cmd_hooks(project, SimpleNamespace(action="install", allow_shared_hooks=False)) == 0


def test_coordination_commit_granted_with_by_lands_through_hook_and_trailers_say_so(
    project, tmp_path, monkeypatch, capsys
):
    root = project["root"]
    steering_dir = os.path.join(root, ".kiro", "steering")
    reviews_dir = os.path.join(root, "semantic-review")
    os.makedirs(steering_dir, exist_ok=True)
    os.makedirs(reviews_dir, exist_ok=True)
    open(os.path.join(steering_dir, "product.md"), "w", encoding="utf-8").write("old steering\n")
    open(os.path.join(steering_dir, "tech.md"), "w", encoding="utf-8").write("old tech\n")
    open(os.path.join(reviews_dir, "20261027-MIGRATION-1.md"), "w", encoding="utf-8").write("old review\n")
    _git(
        root, "add", "-f",
        ".kiro/steering/product.md",
        ".kiro/steering/tech.md",
        "semantic-review/20261027-MIGRATION-1.md",
    )
    _git(root, "commit", "-q", "-m", "track steering and review records")

    _install_current_hook_for_git(root, project, tmp_path, monkeypatch)
    capsys.readouterr()

    _git(root, "mv", ".kiro/steering/product.md", ".kiro/steering/polyctl-product.md")
    _git(root, "rm", "--cached", "-q", "--", ".kiro/steering/tech.md")
    open(os.path.join(reviews_dir, "20261027-MIGRATION-1.md"), "w", encoding="utf-8").write("updated review\n")
    _git(root, "add", "-f", "semantic-review/20261027-MIGRATION-1.md")

    candidate = A.index_candidate(root)
    assert A.coordination_candidate(candidate, project) is True
    assert A.candidate_worktree_issues(root, project, candidate)["staged_coordination"] == []

    monkeypatch.setattr(cli, "_confirm", lambda question: True)
    assert cli.cmd_harness(
        project,
        cli.build_parser().parse_args(["harness", "seen", "--by", "alice (owner)", "--ask"]),
    ) == 0
    capsys.readouterr()

    args = cli.build_parser().parse_args(["commit-ok", "--by", "alice (owner)", "--ask"])
    assert cli.cmd_commit_ok(project, args) == 0
    out = capsys.readouterr().out
    assert "GRANTED" in out
    assert "coordination by alice (owner)" in out

    grant = A.latest_authority_decision(root)
    assert grant["granted"] is True
    assert grant["verification"] is None
    assert grant["review"] is None
    assert grant["coordination"]["by"] == "alice (owner)"
    assert grant["coordination"]["paths"] == [
        ".kiro/steering/polyctl-product.md",
        ".kiro/steering/product.md",
        ".kiro/steering/tech.md",
        "semantic-review/20261027-MIGRATION-1.md",
    ]
    trailers = dict(A.grant_trailers(grant))
    assert trailers["Polyctl-Grant"] == grant["token"]
    assert trailers["Polyctl-Tree"] == candidate["index_tree"]
    assert trailers["Polyctl-Verification"] == "coordination"
    assert trailers["Polyctl-Review"] == "coordination (alice (owner))"

    commit_args = cli.build_parser().parse_args(["commit", "-m", "rename steering and review records for MIGRATION-1"])
    assert cli.cmd_commit(project, commit_args) == 0
    capsys.readouterr()

    range_args = cli.build_parser().parse_args(["commit-check", "--range", "HEAD~1..HEAD"])
    assert cli.cmd_commit_check(project, range_args) == 0
    range_out = capsys.readouterr().out
    assert "Polyctl-Verification: coordination" in A._git_text(root, "log", "-1", "--format=%B")
    assert "Polyctl-Review: coordination (alice (owner))" in A._git_text(root, "log", "-1", "--format=%B")
    assert "1 commit(s) checked" in range_out and grant["token"] in range_out

    # Untracking the remaining coordination file also lands directly through Git's pre-commit hook.
    _git(root, "rm", "--cached", "-q", "--", "semantic-review/20261027-MIGRATION-1.md")
    assert cli.cmd_commit_ok(
        project, cli.build_parser().parse_args(["commit-ok", "--by", "alice (owner)", "--ask"])
    ) == 0
    capsys.readouterr()
    _git(root, "commit", "-q", "-m", "untrack review record")


def test_coordination_commit_refused_without_by_or_by_an_agent_or_role(
    project, monkeypatch, capsys
):
    root = project["root"]
    reviews_dir = os.path.join(root, "semantic-review")
    os.makedirs(reviews_dir, exist_ok=True)
    review_file = os.path.join(reviews_dir, "20261027-MIGRATION-1.md")
    open(review_file, "w", encoding="utf-8").write("v1\n")
    _git(root, "add", "-f", "semantic-review/20261027-MIGRATION-1.md")
    _git(root, "commit", "-q", "-m", "track review")

    open(review_file, "w", encoding="utf-8").write("v2\n")
    _git(root, "add", "-f", "semantic-review/20261027-MIGRATION-1.md")
    candidate = A.index_candidate(root)

    assert cli.cmd_commit_ok(project, cli.build_parser().parse_args(["commit-ok"])) == 1
    out = capsys.readouterr().out
    assert "REFUSED" in out
    assert "--by is required: staged candidate holds only coordination paths" in out
    assert A.latest_authority_decision(root)["granted"] is False

    for bad_name in ("implementer", "architect", "reviewer", "claude-code", "kiro", "codex"):
        assert cli.cmd_commit_ok(
            project, cli.build_parser().parse_args(["commit-ok", "--by", bad_name])
        ) == 1
        out = capsys.readouterr().out
        assert f"--by names an agent or a role ({bad_name}); a coordination commit is a person's act" in out
        assert A.latest_authority_decision(root)["granted"] is False

    # --by without --ask or --digest, non-interactive, is refused and prints the --digest command.
    monkeypatch.delenv("POLYCTL_ROLE", raising=False)
    monkeypatch.setattr(cli, "_confirm", lambda question: None)
    assert cli.cmd_commit_ok(
        project, cli.build_parser().parse_args(["commit-ok", "--by", "alice (owner)"])
    ) == 1
    out = capsys.readouterr().out
    assert "REFUSED" in out
    assert f"polyctl commit-ok --by {A.copyable_word('alice (owner)')} --digest {candidate['digest']}" in out
    assert A.latest_authority_decision(root)["granted"] is False

    # An agent (POLYCTL_ROLE unset, non-interactive) is refused even when --ask is given.
    assert cli.cmd_commit_ok(
        project, cli.build_parser().parse_args(["commit-ok", "--by", "alice (owner)", "--ask"])
    ) == 1
    out = capsys.readouterr().out
    assert "REFUSED" in out
    assert f"polyctl commit-ok --by {A.copyable_word('alice (owner)')} --digest {candidate['digest']}" in out
    assert A.latest_authority_decision(root)["granted"] is False

    # A wrong --digest is refused and prints the candidate's --digest command.
    assert cli.cmd_commit_ok(
        project,
        cli.build_parser().parse_args(["commit-ok", "--by", "alice (owner)", "--digest", "sha256:" + "0" * 64]),
    ) == 1
    out = capsys.readouterr().out
    assert "REFUSED" in out
    assert f"polyctl commit-ok --by {A.copyable_word('alice (owner)')} --digest {candidate['digest']}" in out
    assert A.latest_authority_decision(root)["granted"] is False

    monkeypatch.setenv("POLYCTL_ROLE", "implementer")
    assert cli.cmd_commit_ok(
        project,
        cli.build_parser().parse_args(["commit-ok", "--by", "alice (owner)", "--digest", candidate["digest"]]),
    ) == 1
    out = capsys.readouterr().out
    assert "a coordination commit is a person's act, not the implementer's" in out
    assert A.latest_authority_decision(root)["granted"] is False

    # With POLYCTL_ROLE unset and the exact candidate's --digest, the person's grant succeeds.
    monkeypatch.delenv("POLYCTL_ROLE", raising=False)
    assert cli.cmd_commit_ok(
        project,
        cli.build_parser().parse_args(["commit-ok", "--by", "alice (owner)", "--digest", candidate["digest"]]),
    ) == 0
    assert A.latest_authority_decision(root)["granted"] is True


def test_coordination_commit_refuses_unseen_claude_settings_and_grants_once_seen(
    project, tmp_path, monkeypatch, capsys
):
    root = project["root"]
    _install_current_hook_for_git(root, project, tmp_path, monkeypatch)
    capsys.readouterr()

    assert A.unseen_harness_config(root) == []
    base_head = A._git_text(root, "rev-parse", "HEAD")

    claude_dir = os.path.join(root, ".claude")
    os.makedirs(claude_dir, exist_ok=True)
    settings_path = os.path.join(claude_dir, "settings.json")
    open(settings_path, "w", encoding="utf-8").write(
        '{"hooks": {"SessionStart": [{"command": "echo hi"}]}}\n'
    )
    _git(root, "add", "-f", ".claude/settings.json")

    candidate = A.index_candidate(root)
    assert A.coordination_candidate(candidate, project) is True
    assert [path for path, _, _ in A.unseen_harness_config(root)] == [".claude/settings.json"]

    monkeypatch.delenv("POLYCTL_ROLE", raising=False)
    monkeypatch.setattr(cli, "_confirm", lambda question: True)

    # Refused while .claude/settings.json is unseen, naming `polyctl harness seen --ask`.
    assert cli.cmd_commit_ok(
        project, cli.build_parser().parse_args(["commit-ok", "--by", "alice (owner)", "--ask"])
    ) == 1
    out = capsys.readouterr().out
    assert "REFUSED" in out
    assert "polyctl harness seen --ask" in out
    assert A.latest_authority_decision(root)["granted"] is False

    # Even if a coordination grant row is persisted before the hook runs, the pre-commit check
    # refuses while .claude/settings.json is unseen and names `polyctl harness seen --ask`, and
    # harness_config_base does not treat the coordination grant's tree as product-granted.
    A.record_authority(
        root, True, [], A.tree_digest(root, project), None, "C-unseen",
        candidate=candidate, scope=A.candidate_scope(candidate),
        coordination={"by": "alice (owner)", "user": "alice", "interactive": True, "paths": [".claude/settings.json"]},
    )
    assert cli.cmd_commit_check(project, SimpleNamespace(range=None)) == 1
    check_out = capsys.readouterr().out
    assert "COMMIT REFUSED" in check_out
    assert "polyctl harness seen --ask" in check_out

    _git(root, "commit", "--no-verify", "-q", "-m", "unseen coordination commit")
    assert A.harness_config_base(root) == base_head
    assert [path for path, _, _ in A.unseen_harness_config(root)] == [".claude/settings.json"]
    _git(root, "reset", "--soft", "HEAD~1")

    # Once a person sees .claude/settings.json, commit-ok --by --ask grants and the commit lands.
    assert cli.cmd_harness(
        project,
        cli.build_parser().parse_args(["harness", "seen", "--by", "alice (owner)", "--ask"]),
    ) == 0
    capsys.readouterr()
    assert A.unseen_harness_config(root) == []

    assert cli.cmd_commit_ok(
        project, cli.build_parser().parse_args(["commit-ok", "--by", "alice (owner)", "--ask"])
    ) == 0
    assert "GRANTED" in capsys.readouterr().out

    commit_args = cli.build_parser().parse_args(["commit", "-m", "record seen claude settings for MIGRATION-1"])
    assert cli.cmd_commit(project, commit_args) == 0
    capsys.readouterr()
    assert A.unseen_harness_config(root) == []


def test_allowlist_forbids_commit_ok_by_and_bound_commit_check_is_not_reindented():
    import ast
    from polyctl import allowlist as AL

    assert ("grants a coordination commit", "polyctl commit-ok --by p") in AL.FORBIDDEN
    for rule in (
        "Bash(polyctl commit-ok --by alice)",
        "Bash(polyctl commit-ok --by alice --ask)",
        "Bash(polyctl commit-ok --by alice --digest sha256:0)",
        "Bash(polyctl commit-ok:*)",
    ):
        found = AL.problems(["claude", "-p", "{prompt}", "--allowedTools", f"Read,{rule}"], {})
        assert [(reason, granted) for reason, _, granted in found] == [
            ("grants a coordination commit", rule)
        ]

    for ident in ("claude-code", "qoder", "qwen"):
        argv = A.role_commands(A.load_adapter(ident))["implementer"]
        assert AL.problems(argv, A.load_adapter(ident).get("options") or {}) == []
        assert not any(AL.admits(rule, "polyctl commit-ok --by alice") for rule in AL.rules(argv))

    assert callable(getattr(cli, "_coordination_commit_check", None))
    auth_path = os.path.join(
        os.path.dirname(__file__), "..", "src", "polyctl", "parts", "cli_authority.py"
    )
    tree = ast.parse(open(auth_path, encoding="utf-8").read())
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_bound_commit_check")
    top_targets = [
        node.targets[0].id
        for node in fn.body
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
    ]
    assert "strict" in top_targets


def test_mixed_candidate_and_product_candidate_with_by_are_refused(project, capsys):
    root = project["root"]
    _repo_with_change(root)
    steering_dir = os.path.join(root, ".kiro", "steering")
    os.makedirs(steering_dir, exist_ok=True)
    open(os.path.join(steering_dir, "product.md"), "w", encoding="utf-8").write("steering\n")
    _git(root, "add", "-f", ".kiro/steering/product.md")

    assert A.coordination_candidate(A.index_candidate(root), project) is False
    for argv in (["commit-ok"], ["commit-ok", "--by", "alice (owner)"]):
        assert cli.cmd_commit_ok(project, cli.build_parser().parse_args(argv)) == 1
        out = capsys.readouterr().out
        assert "coordination paths must not share a product commit: .kiro/steering/product.md" in out

    _git(root, "rm", "--cached", "-q", "--", ".kiro/steering/product.md")
    assert cli.cmd_commit_ok(
        project, cli.build_parser().parse_args(["commit-ok", "--by", "alice (owner)"])
    ) == 1
    out = capsys.readouterr().out
    assert "--by is only for a coordination commit: staged candidate holds product paths" in out
