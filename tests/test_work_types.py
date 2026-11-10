"""Work type chooses gate weight without changing enforcement or reusing lighter evidence (AIDLC-1)."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from polyctl import cli, language, lib as A
from tests.test_commit_authority import (
    _git, _install_passing_gate, _repo_with_change, _review_args,
)
from tests import standin


def _reviewer(project, tmp_path):
    capture = tmp_path / "prompt.txt"
    answer = "VERDICT: APPROVED\nBLOCKER: 0\nHIGH: 0\nMEDIUM: 0\nLOW: 0\n"
    source = ("import pathlib, sys\n"
              f"pathlib.Path({str(capture)!r}).write_text(sys.argv[1], encoding='utf-8')\n"
              f"print({answer!r})\n")
    program = standin.program(tmp_path / "bin", "work-type-reviewer", source)
    return dict(project, reviewer={"id": "r", "family": "x", "argv": [program, "{prompt}"]}), capture


def _typed(project, kind):
    path = Path(project["root"]) / ".polyctl" / "board.md"
    path.write_text(
        "# Board\n\n## running\n- [S1] change · acceptance: product change · type: " + kind
        + "\n\n## queued\n\n## blocked\n\n## done\n", encoding="utf-8")
    return A.active_work_profile(project)


def _verify(project, tmp_path, monkeypatch, spec=True):
    _install_passing_gate(project, tmp_path, monkeypatch)
    path = Path(project["root"]) / ".polyctl" / "gates.json"
    gates = json.loads(path.read_text(encoding="utf-8"))
    gates["gates"]["spec"] = dict(gates["gates"]["smoke"])
    gates["profiles"]["full"] = ["smoke", "spec"] if spec else ["smoke"]
    path.write_text(json.dumps(gates) + "\n", encoding="utf-8")
    return cli.cmd_verify(project, SimpleNamespace(profile=None, wait=0))


def _command(project, *words):
    args = cli.build_parser().parse_args(list(words))
    return args.fn(project, args)


@pytest.mark.parametrize("kind,verify,review,size,spec,families", [
    ("bugfix", "quick", "diff", False, False, 1),
    ("poc", "quick", "full", False, False, 1),
    ("feature", "default", "full", True, False, 1),
    ("enterprise", "full", "full", True, True, 2),
])
def test_each_type_selects_its_gates_in_both_modes(project, kind, verify, review, size, spec, families):
    expected = dict(type=kind, verify=verify, review=review, size=size, spec=spec, reviewer_families=families)
    for mode in ("lite", "full"):
        cfg = dict(project, mode=mode)
        assert _typed(cfg, kind) == expected


def test_add_default_edit_and_board(project, capsys):
    _typed(project, "feature")
    assert _command(project, "slice", "add", "S2", "new change", "--acceptance", "works") == 0
    assert A.board(project["root"])["queued"][0]["notes"]["type"] == "feature"
    assert _command(project, "slice", "edit", "S2", "--type", "bugfix") == 0
    assert A.board(project["root"])["queued"][0]["notes"]["type"] == "bugfix"
    assert _command(project, "slice", "edit", "S2", "--type", "poc") == 0
    assert A.board(project["root"])["queued"][0]["notes"]["type"] == "poc"
    assert _command(project, "board") == 0
    assert "type:" in capsys.readouterr().out
    assert _command(project, "slice", "edit", "S2", "--type", "feature", "--acceptance", "other") == 2
    assert _command(project, "slice", "edit", "missing", "--type", "poc") == 2
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["slice", "edit", "S2", "--type", "poc", "--by", "Alice"])


def test_slice_add_and_edit_catch_invalid_work_types_and_print_repair_message(project, capsys):
    _typed(project, "feature")
    before = (Path(project["root"]) / ".polyctl" / "board.md").read_text(encoding="utf-8")
    weakened = dict(project, work_types={"feature": {"review": "diff"}})
    assert _command(weakened, "slice", "add", "S2", "new change", "--acceptance", "works", "--type", "feature") == 2
    out = capsys.readouterr().out
    assert "REFUSED" in out and "weakens its minimum gates; restore the documented defaults" in out
    assert _command(weakened, "slice", "edit", "S1", "--type", "feature") == 2
    out = capsys.readouterr().out
    assert "REFUSED" in out and "weakens its minimum gates; restore the documented defaults" in out
    no_review = dict(project, work_types={"poc": {"review": "none", "reviewer_families": 0}})
    assert _command(no_review, "slice", "edit", "S1", "--type", "poc") == 2
    out = capsys.readouterr().out
    assert "REFUSED" in out and "invalid work_types.poc" in out
    unknown = dict(project, work_types={"fast": {}})
    assert _command(unknown, "slice", "add", "S2", "new change", "--acceptance", "works") == 2
    out = capsys.readouterr().out
    assert "REFUSED" in out and "unknown work_types entry; use bugfix, poc, feature or enterprise" in out
    assert (Path(project["root"]) / ".polyctl" / "board.md").read_text(encoding="utf-8") == before


def test_legacy_board_defaults_to_feature(project):
    assert A.work_type_profile(project, {"notes": {}})["type"] == "feature"
    assert A.work_profile_matches({}, A.work_type_profile(project))


@pytest.mark.parametrize("kind,override", [
    ("feature", {"review": "none", "reviewer_families": 0}),
    ("feature", {"review": "diff"}),
    ("feature", {"size": False}),
    ("feature", {"spec": "yes"}),
    ("feature", {"reviewer_families": 0}),
    ("feature", {"reviewer_families": True}),
    ("feature", {"unknown": 3}),
    ("poc", {"review": "none", "reviewer_families": 0}),
    ("poc", {"review": "diff"}),
    ("enterprise", {"verify": "quick"}),
    ("enterprise", {"verify": "default"}),
    ("enterprise", {"spec": False}),
    ("enterprise", {"reviewer_families": 1}),
])
def test_invalid_or_weakened_table_is_refused(project, kind, override):
    with pytest.raises(ValueError):
        A.work_type_profile(dict(project, work_types={kind: override}), {"notes": {"type": kind}})


def test_configuration_can_increase_weight(project):
    cfg = dict(project, work_types={"bugfix": {"verify": "full", "review": "full", "size": True}})
    assert _typed(cfg, "bugfix")["verify"] == "full"
    assert A.active_work_profile(cfg)["size"] is True


def test_mixed_running_types_refuse_instead_of_selecting_first(project):
    _typed(project, "poc")
    path = Path(project["root"]) / ".polyctl" / "board.md"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "## running\n", "## running\n- [S2] another · type: enterprise\n"), encoding="utf-8")
    with pytest.raises(ValueError, match="different work types"):
        A.active_work_profile(project)


@pytest.mark.parametrize("kind", ["bugfix", "poc", "feature", "enterprise"])
def test_verification_records_selected_profile_and_size(project, tmp_path, monkeypatch, kind):
    _repo_with_change(project["root"])
    weight = _typed(project, kind)
    assert _verify(project, tmp_path, monkeypatch) == 0
    row = A.latest_verification(project["root"])
    assert row["work_profile"] == weight
    assert row["profile"] == ("full" if kind == "enterprise" else "quick")
    assert (row["candidate_size"] is not None) == weight["size"]
    assert [gate["name"] for gate in row["gates"]] == (["smoke", "spec"] if weight["spec"] else ["smoke"])
    if kind in ("bugfix", "poc"):
        assert cli.cmd_verify(project, SimpleNamespace(profile="full", wait=0)) == 2


def test_enterprise_requires_spec_gate_before_running(project, tmp_path, monkeypatch, capsys):
    _repo_with_change(project["root"])
    _typed(project, "enterprise")
    assert _verify(project, tmp_path, monkeypatch, spec=False) == 2
    assert "spec gate" in capsys.readouterr().out
    assert A.latest_verification(project["root"]) is None


def test_poc_requires_cross_family_review_and_commit_ok_like_any_other_slice(
        project, tmp_path, monkeypatch, capsys):
    root = project["root"]
    _repo_with_change(root)
    _typed(project, "feature")
    assert _command(project, "slice", "edit", "S1", "--type", "poc") == 0
    cfg, _ = _reviewer(project, tmp_path)
    cfg["implementer"] = {"id": "impl", "family": "impl-family"}
    assert _verify(cfg, tmp_path, monkeypatch) == 0
    capsys.readouterr()

    assert cli.cmd_commit_ok(cfg, SimpleNamespace(verify=False)) == 1
    assert "no APPROVED prospective review" in capsys.readouterr().out

    same_family = dict(cfg, reviewer=dict(cfg["reviewer"], family="impl-family"))
    assert cli.cmd_review(same_family, _review_args()) != 0
    capsys.readouterr()

    assert cli.cmd_review(cfg, _review_args()) == 0
    assert cli.cmd_commit_ok(cfg, SimpleNamespace(verify=False)) == 0
    assert cli.cmd_commit_check(cfg, SimpleNamespace()) == 0
    grant = A.latest_authority_decision(root)
    assert grant["granted"] is True and grant["review"]
    assert grant["work_profile"]["type"] == "poc"

    assert _command(cfg, "slice", "edit", "S1", "--type", "feature") == 0
    capsys.readouterr()
    assert cli.cmd_commit_check(cfg, SimpleNamespace()) == 1
    assert "work type changed" in capsys.readouterr().out


def test_implementer_cannot_type_slices_and_recorded_type_blocks_hand_edit_downgrades(
        project, tmp_path, monkeypatch, capsys):
    root = project["root"]
    _repo_with_change(root)
    _typed(project, "feature")
    board_path = Path(root) / ".polyctl" / "board.md"
    before = board_path.read_text(encoding="utf-8")

    with monkeypatch.context() as mp:
        mp.setenv("POLYCTL_ROLE", "implementer")
        for kind in ("poc", "bugfix", "feature", "enterprise"):
            assert _command(project, "slice", "edit", "S1", "--type", kind) == 2
        assert _command(project, "slice", "add", "S2", "change", "--acceptance", "ok", "--type", "poc") == 2
        capsys.readouterr()
    assert board_path.read_text(encoding="utf-8") == before
    assert A.recorded_opt_in(root, "slice.type:S1") is None

    with monkeypatch.context() as mp:
        mp.setenv("POLYCTL_ROLE", "architect")
        assert _command(project, "slice", "edit", "S1", "--type", "enterprise") == 0
    for downgraded in ("poc", "feature"):
        _typed(project, downgraded)
        cfg, _ = _reviewer(project, tmp_path)
        assert _verify(cfg, tmp_path, monkeypatch) == 0
        assert cli.cmd_review(cfg, _review_args()) == 0
        capsys.readouterr()
        assert cli.cmd_commit_ok(cfg, SimpleNamespace(verify=False)) == 1
        assert "recorded as type enterprise" in capsys.readouterr().out
        assert cli.cmd_commit_check(cfg, SimpleNamespace()) == 1
        assert "recorded as type enterprise" in capsys.readouterr().out

    opt_ins = Path(root) / ".polyctl" / "ledger" / "opt-ins.jsonl"
    opt_ins.write_text("not json\n", encoding="utf-8")
    capsys.readouterr()
    assert cli.cmd_commit_ok(cfg, SimpleNamespace(verify=False)) == 1
    assert "opt-in ledger cannot be read" in capsys.readouterr().out


@pytest.mark.parametrize("kind", ["bugfix", "poc", "feature"])
def test_review_weight_controls_context_tree_sections_and_size(project, tmp_path, monkeypatch, kind):
    root = project["root"]
    _repo_with_change(root)
    _typed(project, kind)
    cfg, capture = _reviewer(project, tmp_path)
    calls, context_calls = [], []
    original = cli._invoke_reviewer_chain
    original_context = A.review_context

    def context(*args, **kwargs):
        context_calls.append(True)
        return original_context(*args, **kwargs)

    def invoke(*args, **kwargs):
        calls.append(kwargs.get("tree"))
        return original(*args, **kwargs)

    monkeypatch.setattr(cli, "_invoke_reviewer_chain", invoke)
    monkeypatch.setattr(A, "review_context", context)
    assert cli.cmd_review(cfg, _review_args()) == 0
    decision = A.candidate_review_decision(root, cfg["reviews"], A.index_candidate(root)["digest"])
    evidence = decision["match"][3]
    assert evidence["work_profile"]["type"] == kind
    assert ("size" in evidence) == (kind == "feature")
    full_review = kind in ("poc", "feature")
    assert bool(calls[0]) == full_review
    marker = language.text(project, "prompt.review-context")
    assert bool(context_calls) == full_review
    if kind == "bugfix":
        assert marker not in capture.read_text(encoding="utf-8")


@pytest.mark.parametrize("second_family,second_high,expected", [("y", 0, 0), ("y", 1, 1), ("x", 0, 3)])
def test_enterprise_asks_two_families_and_neither_rejection_is_lost(
        project, tmp_path, monkeypatch, second_family, second_high, expected):
    root = project["root"]
    _repo_with_change(root)
    _typed(project, "enterprise")
    cfg, _ = _reviewer(project, tmp_path)
    second = dict(cfg["reviewer"], id="second", family=second_family)
    cfg["reviewer"]["fallbacks"] = [second]
    seen = []

    def invoke(root, chain, prompt, timeout, strict, **kwargs):
        route = chain[0]
        seen.append(route["id"])
        high = second_high if route["id"] == "second" else 0
        out = f"VERDICT: APPROVED\nBLOCKER: 0\nHIGH: {high}\nMEDIUM: 0\nLOW: 0\n"
        return {"used": route, "used_position": 0, "attempt": {"ok": True, "out": out, "binary": "stand-in"},
                "failures": {}, "labels": {}, "chain": chain}

    monkeypatch.setattr(cli, "_invoke_reviewer_chain", invoke)
    assert cli.cmd_review(cfg, _review_args()) == expected
    assert seen == (["r", "second"] if second_family == "y" else ["r"])
    if expected == 0:
        ev = A.candidate_review_decision(root, cfg["reviews"], A.index_candidate(root)["digest"])["match"][3]
        assert ev["additional_review"]["reviewer"]["family"] == "y"
        assert cli._work_review_refusals(cfg, A.active_work_profile(cfg), ev) == []
        assert _verify(cfg, tmp_path, monkeypatch) == 0
        assert cli.cmd_commit_ok(cfg, SimpleNamespace(verify=False)) == 0
        assert cli.cmd_commit_check(cfg, SimpleNamespace()) == 0
        cfg["reviewer"]["fallbacks"][0]["family"] = "x"
        assert cli._work_review_refusals(cfg, A.active_work_profile(cfg), ev)
        assert cli.cmd_commit_check(cfg, SimpleNamespace()) == 1


def test_enterprise_cannot_use_feature_approval(project):
    _typed(project, "enterprise")
    reasons = cli._work_review_refusals(project, A.active_work_profile(project), {})
    assert any("another work type" in reason for reason in reasons)
    assert any("second reviewer family" in reason for reason in reasons)


@pytest.mark.parametrize("lighter", ["bugfix", "poc"])
def test_lighter_approval_cannot_be_reused_after_retyping_feature(project, tmp_path, monkeypatch, capsys, lighter):
    root = project["root"]
    _repo_with_change(root)
    _typed(project, lighter)
    cfg, _ = _reviewer(project, tmp_path)
    assert _verify(cfg, tmp_path, monkeypatch) == 0
    assert cli.cmd_review(cfg, _review_args()) == 0
    assert cli.cmd_commit_ok(cfg, SimpleNamespace(verify=False)) == 0
    _typed(project, "feature")
    assert _verify(cfg, tmp_path, monkeypatch) == 0
    capsys.readouterr()
    assert cli.cmd_commit_ok(cfg, SimpleNamespace(verify=False)) == 1
    assert "review used another work type" in capsys.readouterr().out


def test_enterprise_matrix_uses_bound_families_and_revalidates_both(project, tmp_path, monkeypatch):
    from tests.test_capability_matrix import _strict_config
    from polyctl import matrix as M

    root = project["root"]
    _repo_with_change(root)
    _typed(project, "enterprise")
    cfg = _strict_config(project)
    seen = []

    def invoke(root, chain, prompt, timeout, strict, **kwargs):
        route = chain[0]
        seen.append(route["identity"]["binding"])
        return {"used": route, "used_position": 0,
                "attempt": {"ok": True, "out": "VERDICT: APPROVED\nBLOCKER: 0\nHIGH: 0\nMEDIUM: 0\nLOW: 0\n"},
                "failures": {}, "labels": {}, "chain": chain}

    monkeypatch.setattr(cli, "_invoke_reviewer_chain", invoke)
    assert cli.cmd_review(cfg, _review_args()) == 0
    assert seen == ["binding.primary", "binding.fallback"]
    ev = A.candidate_review_decision(root, cfg["reviews"], A.index_candidate(root)["digest"])["match"][3]
    assert not cli._work_review_refusals(cfg, A.active_work_profile(cfg), ev, M.resolve(cfg))
    assert _verify(cfg, tmp_path, monkeypatch) == 0
    assert cli.cmd_commit_ok(cfg, SimpleNamespace(verify=False)) == 0
    assert cli.cmd_commit_check(cfg, SimpleNamespace()) == 0


@pytest.mark.parametrize("reply", [None, "unstructured answer"])
def test_unavailable_or_invalid_second_review_grants_nothing(project, tmp_path, monkeypatch, reply):
    root = project["root"]
    _repo_with_change(root)
    _typed(project, "enterprise")
    cfg, _ = _reviewer(project, tmp_path)
    cfg["reviewer"]["fallbacks"] = [dict(cfg["reviewer"], id="second", family="y")]

    def invoke(root, chain, prompt, timeout, strict, **kwargs):
        route = chain[0]
        out = "VERDICT: APPROVED\nBLOCKER: 0\nHIGH: 0\nMEDIUM: 0\nLOW: 0\n" if route["id"] == "r" else reply
        return {"used": route if out is not None else None, "used_position": 0,
                "attempt": {"ok": out is not None, "out": out or ""},
                "failures": {}, "labels": {}, "chain": chain}

    monkeypatch.setattr(cli, "_invoke_reviewer_chain", invoke)
    assert cli.cmd_review(cfg, _review_args()) == 3
    assert A.candidate_review_decision(root, cfg["reviews"], A.index_candidate(root)["digest"])["match"] is None


@pytest.mark.parametrize("matching", [False, True])
def test_second_tool_reviewer_is_bound_to_the_same_diff(project, monkeypatch, matching):
    diff = b"candidate diff"
    primary = {"id": "first", "family": "first-family"}
    second = {"id": "second", "family": "second-family", "kind": "tool",
              "adapter": "pr-agent", "model": "provider/review-model"}
    cfg = dict(project, reviewer=dict(primary, fallbacks=[second]))
    handed = "sha256:" + A.hashlib.sha256(diff if matching else b"other diff").hexdigest()
    out = "VERDICT: APPROVED\nBLOCKER: 0\nHIGH: 0\nMEDIUM: 0\nLOW: 0\n"

    def invoke(*args, **kwargs):
        return {"used": second, "used_position": 0, "attempt": {
            "ok": True, "out": out, "tool": {"handed": handed, "bytes": len(diff)}},
            "failures": {}, "labels": {}, "chain": [second]}

    monkeypatch.setattr(cli, "_invoke_reviewer_chain", invoke)
    extra, answer, problem = cli._second_work_review(
        cfg, [primary, second], {"used": primary}, "review", diff, None, "review", False, [])
    if matching:
        assert problem is None and answer == out
        assert extra["diff_digest"] == extra["tool"]["handed"] == handed
    else:
        assert extra is None and "not the candidate diff" in problem


def test_default_feature_resumes_legacy_journals_but_custom_weights_do_not(project):
    evidence = {"diff_digest": "sha256:" + A.hashlib.sha256(b"same candidate").hexdigest()}
    sections, chain = [{"name": "correctness"}], [{"id": "reviewer"}]
    legacy = cli._section_journal(project["root"], evidence, "boundary", sections, chain)
    profile = A.work_type_profile(project)
    assert cli._section_journal(project["root"], dict(evidence, work_profile=profile),
                                "boundary", sections, chain) == legacy
    for changed in (dict(profile, verify="full"), dict(profile, spec=True),
                    dict(profile, reviewer_families=2)):
        assert cli._section_journal(project["root"], dict(evidence, work_profile=changed),
                                    "boundary", sections, chain) != legacy


@pytest.mark.parametrize("cached_verdict", ["MET", "NOT MET", None])
def test_default_feature_resume_keeps_cached_criteria_and_requires_every_verdict(
        project, tmp_path, monkeypatch, cached_verdict):
    from polyctl import storage
    from tests.test_language_prompts import (
        APPROVED, _choose, _newest_review, _reviewer as language_reviewer, _staged_diff,
    )
    from tests.test_review_sections import SCENARIOS, _args

    cfg, _ = _choose(project, "tr")
    root = cfg["root"]
    _repo_with_change(root)
    route, handed = language_reviewer(
        tmp_path, monkeypatch, answer=APPROVED + "CRITERION 3: MET - replay test passes\n")
    sections = [{"name": f"scenario:{number}"} for number in range(1, 4)]
    evidence = {"diff_digest": "sha256:" + A.hashlib.sha256(_staged_diff(root)).hexdigest()}
    journal = cli._section_journal(root, evidence, SCENARIOS, sections, [route])
    for number, verdict in ((1, cached_verdict), (2, "MET")):
        answer = APPROVED + (f"CRITERION {number}: {verdict} - saved section evidence\n" if verdict else "")
        storage.append_jsonl(journal, {"section": f"scenario:{number}", "position": 0, "route": "r1",
                                       "counts": {"BLOCKER": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0},
                                       "out": answer, "verdict": "APPROVED"})

    assert cli.cmd_review(dict(cfg, reviewer=route), _args(SCENARIOS)) == 0

    evidence = A.review_evidence(_newest_review(root))
    assert [criterion["verdict"] for criterion in evidence["criteria"]] == [
        cached_verdict.lower() if cached_verdict else None, "met", "met"]
    assert bool(A.criteria_refusals(evidence)) == (cached_verdict != "MET")
    (prompt,) = handed()
    assert "CRITERION" in prompt and "Scenario 3:" in prompt
    assert [row["section"] for row in storage.read_jsonl(journal)] == [s["name"] for s in sections]


def test_retyping_separates_section_journals_and_person_digests(project):
    evidence = {"diff_digest": "sha256:" + A.hashlib.sha256(b"same candidate").hexdigest(), "slice": "S1"}
    sections = [{"name": "correctness", "question": "Does it work?"}]
    journals, digests = set(), set()
    for kind in A.WORK_TYPE_PROFILES:
        weighted = dict(evidence, work_profile=A.work_type_profile(project, {"notes": {"type": kind}}))
        journals.add(cli._section_journal(project["root"], weighted, "boundary", sections, [{"id": "reviewer"}]))
        digests.add(cli._person_read(weighted, "boundary", []))
    assert len(journals) == len(digests) == 4


def test_person_must_read_again_after_slice_is_retyped(project, capsys):
    from tests.test_review_tiers import _person, _digest

    _repo_with_change(project["root"])
    _typed(project, "bugfix")
    code, shown = _person(project, capsys)
    assert code == 0 and "work profile:" in shown
    digest = _digest(shown)
    _typed(project, "feature")
    code, output = _person(project, capsys, verdict="APPROVED", digest=digest)
    assert code == 1 and "read it again" in output


@pytest.mark.parametrize("kind", ["bugfix", "poc", "enterprise"])
def test_nondefault_profile_cannot_leave_a_standin_request_to_collect_after_retyping(
        project, tmp_path, monkeypatch, kind):
    _repo_with_change(project["root"])
    _typed(project, kind)
    cfg, _ = _reviewer(project, tmp_path)

    def unavailable(root, chain, *args, **kwargs):
        return {"used": None, "used_position": None, "attempt": None, "chain": chain,
                "failures": {0: {"kind": "quota", "reason": "quota exhausted"}}, "labels": {0: "reviewer"}}

    def unexpected(*args, **kwargs):
        pytest.fail("a request without a type binding could be collected under another type")

    monkeypatch.setattr(cli, "_invoke_reviewer_chain", unavailable)
    monkeypatch.setattr(A, "write_review_request", unexpected)
    assert cli.cmd_review(cfg, _review_args()) == 3
