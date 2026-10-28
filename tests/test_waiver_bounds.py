import json
import os
import stat
import subprocess
import time
from types import SimpleNamespace

import pytest

from polyctl import cli, lib as A, storage
from tests.test_switches_and_bypass import _allow_candidate_verification

WAIVE = dict(gate="review", slice="B7", why="reviewer at quota", by="alice (owner)", hours=24.0)
# A catch-up that reaches a review names the family that wrote the range (#65).
NAMED = SimpleNamespace(boundary=None, author_family="author-family", by="A. Person")


def _running(root, *slices):
    board = os.path.join(root, ".polyctl", "board.md")
    text = open(board, encoding="utf-8").read()
    items = "".join(f"- [{s}] slice {s} · since: 2026-09-05 10:00\n" for s in slices)
    open(board, "w", encoding="utf-8").write(text.replace("## running\n", "## running\n" + items))


def _stage(root, name, text):
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    open(os.path.join(root, "src", name), "w", encoding="utf-8").write(text)
    subprocess.run(["git", "add", f"src/{name}"], cwd=root, check=True, capture_output=True)
    return A.index_candidate(root)


def _commit(root, message):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", message],
                   cwd=root, check=True, capture_output=True)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                          capture_output=True, text=True).stdout.strip()


def _commit_ok(project, capsys):
    capsys.readouterr()
    code = cli.cmd_commit_ok(project, SimpleNamespace(verify=False, profile=None))
    return code, capsys.readouterr().out


@pytest.mark.parametrize("change,message", [
    ({"slice": None}, "--slice is required"),
    ({"slice": "*"}, "--slice is required"),
    ({"by": None}, "--by is required"),
    ({"by": "kiro"}, "names an agent or a role"),
    ({"by": "human"}, "names an agent or a role"),
    ({"hours": 0.0}, "--hours must be above 0"),
    ({"hours": 169.0}, "--hours must be above 0"),
])
def test_polyctl_waive_refuses_a_waiver_without_bounds(project, capsys, change, message):
    assert cli.cmd_waive(project, SimpleNamespace(**{**WAIVE, **change})) == 2
    assert message in capsys.readouterr().out
    assert not os.path.exists(A.waivers_path(project["root"]))


def test_a_waiver_is_a_chained_row_with_an_expiry_and_who_ran_it(project):
    root = project["root"]
    assert cli.cmd_waive(project, SimpleNamespace(**WAIVE)) == 0

    (row,) = storage.read_chained_jsonl(A.waivers_path(root), A.WAIVER_CHAIN)
    assert row["slice"] == "B7" and row["by"] == "alice (owner)"
    assert 0 < row["expires"] - row["at"] <= 24 * 3600
    assert "user" in row and isinstance(row["interactive"], bool)
    assert A.open_waiver_report(root)[0].startswith(f"{row['id']} review for B7")


def test_an_expired_waiver_authorises_nothing(project, monkeypatch, capsys):
    root = project["root"]
    _running(root, "B7")
    _allow_candidate_verification(monkeypatch, _stage(root, "a.py", "value = 1\n"))
    A.waive(root, "review", "B7", "quota", by="alice (owner)", hours=0.0002)
    time.sleep(1)

    code, out = _commit_ok(project, capsys)
    assert code == 1 and "expired" in out


def test_a_waiver_cannot_be_replayed_for_other_bytes(project, monkeypatch, capsys):
    root = project["root"]
    _running(root, "B7")
    first = _stage(root, "a.py", "value = 1\n")
    _allow_candidate_verification(monkeypatch, first)
    waiver = A.waive(root, "review", "B7", "quota", by="alice (owner)")

    code, out = _commit_ok(project, capsys)
    assert code == 0 and "review waived" in out
    assert A.latest_authority_decision(root)["waiver"] == waiver["id"]
    assert cli.cmd_commit_check(project, SimpleNamespace()) == 0

    second = _stage(root, "b.py", "other = 2\n")
    _allow_candidate_verification(monkeypatch, second)
    code, out = _commit_ok(project, capsys)
    assert code == 1 and f"waiver {waiver['id']} already authorised other bytes" in out


def test_a_waiver_for_every_slice_or_without_an_expiry_covers_nothing(project, monkeypatch, capsys):
    root = project["root"]
    _running(root, "B7")
    _allow_candidate_verification(monkeypatch, _stage(root, "a.py", "value = 1\n"))
    with open(A.waivers_path(root), "w", encoding="utf-8") as fh:
        for wid, slice_id in (("W-every", "*"), ("W-legacy", "B7")):
            row = {"event": "waived", "id": wid, "gate": "review", "slice": slice_id,
                   "why": "old", "by": "human", "at": 1, "head": "x", "tree": "t"}
            fh.write(json.dumps(row) + "\n")
    storage._record_committed_length(A.waivers_path(root), 2, storage.chained_row_digest(row, A.WAIVER_CHAIN))

    code, out = _commit_ok(project, capsys)
    assert code == 1
    assert "W-every names every slice" in out and "W-legacy for B7 predates waiver expiry" in out


def test_a_row_appended_without_a_link_makes_waivers_unreadable(project, monkeypatch, capsys):
    root = project["root"]
    _running(root, "B7")
    _allow_candidate_verification(monkeypatch, _stage(root, "a.py", "value = 1\n"))
    A.waive(root, "review", "B7", "quota", by="alice (owner)")
    with open(A.waivers_path(root), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event": "closed", "id": "W-other", "at": 1, "outcome": "forged"}) + "\n")
    storage._record_committed_length(A.waivers_path(root), 2, None)

    with pytest.raises(storage.LedgerCorruption):
        A.open_waivers(root)
    code, out = _commit_ok(project, capsys)
    assert code == 1 and "waiver ledger is unreadable" in out


def _landed_under_a_waiver(project, monkeypatch, capsys):
    root = project["root"]
    _stage(root, "a.py", "value = 1\n")
    _commit(root, "base")
    _running(root, "B7")
    _allow_candidate_verification(monkeypatch, _stage(root, "a.py", "value = 2\n"))
    waiver = A.waive(root, "review", "B7", "quota", by="alice (owner)")
    assert _commit_ok(project, capsys)[0] == 0
    landed = _commit(root, "b7")
    parent = subprocess.run(["git", "rev-parse", f"{landed}^"], cwd=root, check=True,
                            capture_output=True, text=True).stdout.strip()
    _stage(root, "c.py", "unrelated = 3\n")
    _commit(root, "later work, not under the waiver")
    return waiver, parent, landed


def test_catchup_reviews_exactly_the_commit_granted_under_a_bounded_waiver(project, monkeypatch, capsys):
    waiver, parent, landed = _landed_under_a_waiver(project, monkeypatch, capsys)
    seen = []
    monkeypatch.setattr(cli, "cmd_review", lambda cfg, ns: seen.append(ns.commits) or 3)
    from polyctl import watchdog as W
    monkeypatch.setattr(W, "run", lambda ns: 0)

    assert cli.cmd_catchup(project, NAMED) == 3
    assert seen == [f"{parent}..{landed}"]
    assert [w["id"] for w in A.open_waivers(project["root"])] == [waiver["id"]]


def test_catchup_does_not_close_a_waiver_when_no_review_was_recorded(project, monkeypatch, capsys):
    waiver, _, _ = _landed_under_a_waiver(project, monkeypatch, capsys)
    from polyctl import watchdog as W
    monkeypatch.setattr(W, "run", lambda ns: 0)
    mailed = []
    monkeypatch.setattr(A, "write_mail", lambda *args, **kwargs: mailed.append(args))

    for code in (1, 2):
        monkeypatch.setattr(cli, "cmd_review", lambda cfg, ns, code=code: code)
        assert cli.cmd_catchup(project, NAMED) == 3
        assert [w["id"] for w in A.open_waivers(project["root"])] == [waiver["id"]]
    assert mailed == []


def test_catchup_closes_a_waiver_on_its_own_review_not_on_another_of_the_same_range(project, monkeypatch, capsys):
    """CATCHUP-READY-2: a `polyctl review --commits` of the same range that ran meanwhile, judged against the implementer
    configured now and recording no author, was the review the waiver closed on."""
    waiver, _, _ = _landed_under_a_waiver(project, monkeypatch, capsys)
    from polyctl import watchdog as W
    monkeypatch.setattr(W, "run", lambda ns: 0)

    def concurrent(cfg, ns):
        A.record_review(cfg["root"], "other.md", b"VERDICT: APPROVED\n",
                        {"kind": "commit-range", "commits": ns.commits}, "APPROVED")
        return 2
    monkeypatch.setattr(cli, "cmd_review", concurrent)

    assert cli.cmd_catchup(project, NAMED) == 3
    assert [w["id"] for w in A.open_waivers(project["root"])] == [waiver["id"]]


def test_a_close_that_cannot_be_written_fails_catchup(project, monkeypatch, capsys):
    root = project["root"]
    _stage(root, "a.py", "value = 1\n")
    _commit(root, "base")
    empty = A.waive(root, "review", "B7", "quota", by="alice (owner)", hours=0.0002)
    time.sleep(1)
    from polyctl import watchdog as W
    monkeypatch.setattr(W, "run", lambda ns: 0)
    path = os.path.abspath(A.waivers_path(root))
    append = storage.append_chained_jsonl

    def refused(target, *args, **kwargs):
        # A file mode does not stop root, so the refusal is the write's own (the Linux lane runs as root).
        if os.path.abspath(target) == path:
            raise PermissionError(13, "Permission denied", target)
        return append(target, *args, **kwargs)

    monkeypatch.setattr(storage, "append_chained_jsonl", refused)
    assert cli.cmd_catchup(project, SimpleNamespace(boundary=None)) == 1
    assert "could not close" in capsys.readouterr().out
    assert [w["id"] for w in A.open_waivers(root)] == [empty["id"]]


def _write_gates_spec(root):
    spec = {
        "default_profile": "quick",
        "profiles": {"quick": ["syntax", "focused"]},
        "gates": {
            "syntax": {"run": "python3 -c 'print(1)'", "timeout": 30},
            "focused": {"run": "python3 -c 'import sys; sys.exit(0)'", "timeout": 30},
        },
    }
    with open(os.path.join(root, ".polyctl", "gates.json"), "w", encoding="utf-8") as fh:
        json.dump(spec, fh)
    return spec


def _record_failed_verification(root, candidate, failed_gates=("focused",), ran_gates=("syntax", "focused"),
                                vid="V-1"):
    _write_gates_spec(root)
    gates = [
        {"name": name, "passed": name not in failed_gates,
         "detail": "timed out after 600s" if name in failed_gates else "exit 0",
         "exit": 124 if name in failed_gates else 0, "seconds": 1}
        for name in ran_gates
    ]
    rec = {
        "id": vid,
        "at": "2026-10-26T12:00:00",
        "schema": 2,
        "profile": "quick",
        "gates_digest": A.gate_definitions_digest(root, "quick"),
        "by": "polyctl verify",
        "passed": False,
        "gates": gates,
        "plan_drift": [],
        "candidate": candidate,
        "candidate_after": candidate,
        "candidate_ready": True,
        "candidate_issues": [],
        "isolation_inputs": A.gate_inputs(root),
        "tree": A.tree_digest(root),
        "head": A._git_text(root, "rev-parse", "--short", "HEAD"),
    }
    return A.record_verification(root, rec)


def test_waive_refuses_inventory_and_describes_each_gate_truthfully(project, capsys):
    root = project["root"]
    assert cli.cmd_waive(project, SimpleNamespace(**{**WAIVE, "gate": "inventory"})) == 2
    out = capsys.readouterr().out
    assert "nothing reads an inventory waiver" in out
    assert not os.path.exists(A.waivers_path(root))
    with pytest.raises(ValueError, match="nothing reads an inventory waiver"):
        A.waive(root, "inventory", "B7", "no rule", by="alice (owner)")
    assert not os.path.exists(A.waivers_path(root))

    assert cli.cmd_waive(project, SimpleNamespace(**{**WAIVE, "gate": "review", "gates": "focused"})) == 2
    assert "--gates applies only to `polyctl waive gates`" in capsys.readouterr().out

    assert cli.cmd_waive(project, SimpleNamespace(**WAIVE)) == 0
    rev_out = capsys.readouterr().out
    assert "in place of an APPROVED review for one staged candidate" in rev_out
    assert "runs the missed review against the landed range" in rev_out

    assert cli.cmd_waive(project, SimpleNamespace(
        gate="gates", gates="focused", slice="B7", why="focused timed out under load",
        by="alice (owner)", hours=24.0,
    )) == 0
    gates_out = capsys.readouterr().out
    assert "waived" in gates_out and "gates (focused) for B7" in gates_out
    assert "verification ran every gate of the profile, failed only failed gate(s) focused" in gates_out
    assert "re-runs the waived gates on the landed range and closes it" in gates_out


def test_gates_waiver_grants_on_failed_focused_gate_names_waiver_and_refuses_other_bytes(
    project, monkeypatch, capsys
):
    from tests.conftest import review_off
    cfg = review_off(project)
    root = cfg["root"]
    _running(root, "MIGRATION-1")
    monkeypatch.setattr(A, "plan_drift", lambda r: [])
    monkeypatch.setattr(A, "hold_state", lambda r: None)
    monkeypatch.setattr(A, "urgent_messages", lambda *a, **kw: [])

    first = _stage(root, "doc.md", "notes\n")
    _record_failed_verification(root, first, failed_gates=("focused",))

    code, out = _commit_ok(cfg, capsys)
    assert code == 1 and "last verification failed: focused" in out

    waiver = A.waive(root, "gates", "MIGRATION-1", "focused timed out under machine load",
                     by="alice (owner)", gates="focused")
    status_out = cli.render(cfg, shown=False)
    assert waiver["id"] in status_out and "gates (focused) for MIGRATION-1" in status_out
    facts = cli.status_facts(cfg, shown=False)
    assert any(waiver["id"] in line for line in facts.get("waivers", []))

    code, out = _commit_ok(cfg, capsys)
    assert code == 0, out
    assert f"gates waived (focused) by alice (owner) ({waiver['id']})" in out
    assert f"waived focused: {waiver['id']}" in out

    grant = A.latest_authority_decision(root)
    assert grant["waiver"] == waiver["id"]
    assert grant["waived_gates"] == ["focused"]
    trailers = dict(A.grant_trailers(grant))
    assert trailers["Polyctl-Waiver"] == waiver["id"]

    assert cli.cmd_commit_check(cfg, SimpleNamespace(range=None)) == 0
    assert "AUTHORIZED" in capsys.readouterr().out

    assert cli.cmd_commit(cfg, SimpleNamespace(message="docs: note migration", file=None)) == 0
    capsys.readouterr()
    commit_msg = subprocess.run(["git", "log", "-1", "--format=%B"], cwd=root, check=True,
                                capture_output=True, text=True).stdout
    assert f"Polyctl-Waiver: {waiver['id']}" in commit_msg

    # A waiver spent on one candidate stands in for no other bytes.
    second = _stage(root, "other.md", "more\n")
    _record_failed_verification(root, second, failed_gates=("focused",), vid="V-2")
    code, out = _commit_ok(cfg, capsys)
    assert code == 1
    assert f"waiver {waiver['id']} already authorised other bytes; it covers one candidate" in out


def test_gates_waiver_refuses_unwaived_failing_gate_and_incomplete_profile_run(project, monkeypatch, capsys):
    from tests.conftest import review_off
    cfg = review_off(project)
    root = cfg["root"]
    _running(root, "MIGRATION-1")
    monkeypatch.setattr(A, "plan_drift", lambda r: [])
    monkeypatch.setattr(A, "hold_state", lambda r: None)
    monkeypatch.setattr(A, "urgent_messages", lambda *a, **kw: [])

    candidate = _stage(root, "doc.md", "notes\n")
    _record_failed_verification(root, candidate, failed_gates=("syntax", "focused"))
    waiver = A.waive(root, "gates", "MIGRATION-1", "focused timed out",
                     by="alice (owner)", gates=["focused"])

    code, out = _commit_ok(cfg, capsys)
    assert code == 1
    assert f"waiver {waiver['id']} covers focused, not syntax" in out

    # Even an all-gates waiver refuses a verification that did not run every gate of the profile.
    A.close_waiver(root, waiver["id"], "superseded")
    A.waive(root, "gates", "MIGRATION-1", "all gates", by="alice (owner)")
    _record_failed_verification(root, candidate, failed_gates=("focused",), ran_gates=("focused",), vid="V-2")
    code, out = _commit_ok(cfg, capsys)
    assert code == 1
    assert "did not run every gate of profile quick: missing syntax" in out


def test_catchup_reruns_waived_gates_on_landed_range_and_closes_when_passing(project, monkeypatch, capsys):
    from polyctl import watchdog as W
    from tests.conftest import review_off
    cfg = review_off(project)
    root = cfg["root"]
    monkeypatch.setattr(W, "run", lambda ns: 0)
    monkeypatch.setattr(A, "plan_drift", lambda r: [])
    monkeypatch.setattr(A, "hold_state", lambda r: None)
    monkeypatch.setattr(A, "urgent_messages", lambda *a, **kw: [])

    _stage(root, "base.py", "x = 1\n")
    _commit(root, "base")
    _running(root, "MIGRATION-1")
    candidate = _stage(root, "doc.md", "notes\n")
    _record_failed_verification(root, candidate, failed_gates=("focused",))
    waiver = A.waive(root, "gates", "MIGRATION-1", "focused timed out under load",
                     by="alice (owner)", gates="focused")
    assert _commit_ok(cfg, capsys)[0] == 0
    assert cli.cmd_commit(cfg, SimpleNamespace(message="docs: note", file=None)) == 0
    landed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                            capture_output=True, text=True).stdout.strip()
    capsys.readouterr()

    # If the waived gate still fails on the landed commit, catchup keeps the waiver open and exits 1.
    ran_trees = []

    def failing_run_gate(c, g, work_dir):
        ran_trees.append(subprocess.run(["git", "rev-parse", "HEAD"], cwd=work_dir, check=True,
                                        capture_output=True, text=True).stdout.strip())
        return "FAILED\n", 1

    monkeypatch.setattr(cli, "_run_gate", failing_run_gate)
    assert cli.cmd_catchup(cfg, SimpleNamespace(boundary=None)) == 1
    out = capsys.readouterr().out
    assert "waived gates failed" in out and f"{waiver['id']} stays open" in out
    assert [w["id"] for w in A.open_waivers(root)] == [waiver["id"]]
    assert ran_trees == [landed]

    # Once the waived gate passes on the landed commit, catchup closes the waiver.
    monkeypatch.setattr(cli, "_run_gate", lambda c, g, work_dir: ("ok\n", 0))
    assert cli.cmd_catchup(cfg, SimpleNamespace(boundary=None)) == 0
    out = capsys.readouterr().out
    assert "waived gates passed (focused); closed" in out
    assert A.open_waivers(root) == []


def test_catchup_refuses_to_close_gates_waiver_when_gate_definitions_differ(project, monkeypatch, capsys):
    from polyctl import watchdog as W
    from tests.conftest import review_off
    cfg = review_off(project)
    root = cfg["root"]
    monkeypatch.setattr(W, "run", lambda ns: 0)
    monkeypatch.setattr(A, "plan_drift", lambda r: [])
    monkeypatch.setattr(A, "hold_state", lambda r: None)
    monkeypatch.setattr(A, "urgent_messages", lambda *a, **kw: [])

    # Without .polyctl/gates.json on disk, verification_waivable_gates fails closed even if gates_digest is omitted.
    waivable, why = A.verification_waivable_gates(
        root, {"id": "V-0", "profile": "quick", "gates": [{"name": "focused", "passed": False}]}
    )
    assert waivable is None and "cannot read .polyctl/gates.json" in why

    _stage(root, "base.py", "x = 1\n")
    _commit(root, "base")
    _running(root, "MIGRATION-1")
    candidate = _stage(root, "doc.md", "notes\n")
    _record_failed_verification(root, candidate, failed_gates=("focused",))
    waiver = A.waive(root, "gates", "MIGRATION-1", "focused timed out under load",
                     by="alice (owner)", gates="focused")
    assert _commit_ok(cfg, capsys)[0] == 0
    assert cli.cmd_commit(cfg, SimpleNamespace(message="docs: note", file=None)) == 0
    capsys.readouterr()

    # Rewriting the untracked .polyctl/gates.json to weaken `focused` after landing cannot close the waiver.
    spec = _write_gates_spec(root)
    spec["gates"]["focused"]["run"] = "true"
    with open(os.path.join(root, ".polyctl", "gates.json"), "w", encoding="utf-8") as fh:
        json.dump(spec, fh)
    ran = []
    monkeypatch.setattr(cli, "_run_gate", lambda c, g, work_dir: ran.append(g["run"]) or ("ok\n", 0))
    assert cli.cmd_catchup(cfg, SimpleNamespace(boundary=None)) == 1
    out = capsys.readouterr().out
    assert "gate definitions for profile quick changed since V-1" in out
    assert f"{waiver['id']} stays open" in out
    assert ran == []
    assert [w["id"] for w in A.open_waivers(root)] == [waiver["id"]]

    # Restoring the gate definitions that V-1 bound lets catchup run the gate and close the waiver.
    _write_gates_spec(root)
    assert cli.cmd_catchup(cfg, SimpleNamespace(boundary=None)) == 0
    out = capsys.readouterr().out
    assert "waived gates passed (focused); closed" in out
    assert len(ran) == 1
    assert A.open_waivers(root) == []


def test_gates_waiver_with_review_enabled_checks_review_and_combines_waiver_trailers(project, monkeypatch, capsys):
    from tests.conftest import review_off
    root = project["root"]
    _running(root, "MIGRATION-1")
    monkeypatch.setattr(A, "plan_drift", lambda r: [])
    monkeypatch.setattr(A, "hold_state", lambda r: None)
    monkeypatch.setattr(A, "urgent_messages", lambda *a, **kw: [])

    candidate = _stage(root, "doc.md", "notes\n")
    _record_failed_verification(root, candidate, failed_gates=("focused",))
    gwaiver = A.waive(root, "gates", "MIGRATION-1", "focused timed out",
                      by="alice (owner)", gates="focused")

    # With review on and no review or review waiver, a gates waiver alone does not grant commit-ok.
    code, out = _commit_ok(project, capsys)
    assert code == 1
    assert f"gates waived (focused) by alice (owner) ({gwaiver['id']})" in out
    assert "no APPROVED prospective review is bound to this staged candidate" in out

    # A grant whose `waiver` holds a gates-waiver ID (granted while review was off) is refused by
    # _bound_commit_check once review is on, because a gates waiver cannot stand in for review.
    off_cfg = review_off(project)
    assert _commit_ok(off_cfg, capsys)[0] == 0
    A.record_opt_in(root, "features.review", True, "alice (owner)")
    from polyctl import features as F
    F.set_switch(root, "review", True)
    on_cfg = A.load_config(root)
    assert cli.cmd_commit_check(on_cfg, SimpleNamespace(range=None)) == 1
    check_out = capsys.readouterr().out
    assert f"review is enabled and no matching running-slice waiver is open (the grant stood on {gwaiver['id']})" in check_out

    # With both review and gates waived while review is on, commit-ok records both and joins Polyctl-Waiver.
    rwaiver = A.waive(root, "review", "MIGRATION-1", "reviewer at quota", by="alice (owner)")
    assert cli.cmd_commit_check(on_cfg, SimpleNamespace(range=None)) == 1
    capsys.readouterr()

    code, out = _commit_ok(on_cfg, capsys)
    assert code == 0, out
    assert f"gates waived (focused) by alice (owner) ({gwaiver['id']})" in out
    assert f"review waived by alice (owner) ({rwaiver['id']})" in out

    grant = A.latest_authority_decision(root)
    assert grant["waiver"] == rwaiver["id"]
    assert grant["gates_waiver"] == gwaiver["id"]
    assert grant["waived_gates"] == ["focused"]
    trailers = dict(A.grant_trailers(grant))
    assert trailers["Polyctl-Waiver"] == f"{rwaiver['id']}, {gwaiver['id']}"

    assert cli.cmd_commit_check(on_cfg, SimpleNamespace(range=None)) == 0
    assert "AUTHORIZED" in capsys.readouterr().out

    assert cli.cmd_commit(on_cfg, SimpleNamespace(message="docs: note migration", file=None)) == 0
    capsys.readouterr()
    commit_msg = subprocess.run(["git", "log", "-1", "--format=%B"], cwd=root, check=True,
                                capture_output=True, text=True).stdout
    assert f"Polyctl-Waiver: {rwaiver['id']}, {gwaiver['id']}" in commit_msg
    assert cli.cmd_commit_check(on_cfg, SimpleNamespace(range="HEAD~1..HEAD", since_first_trailer=False)) == 0
    capsys.readouterr()
    assert [item["waiver"]["id"] for item in A.review_waiver_ranges(root) if item["landed"]] == [rwaiver["id"]]
    assert [item["waiver"]["id"] for item in A.gates_waiver_ranges(root) if item["landed"]] == [gwaiver["id"]]
