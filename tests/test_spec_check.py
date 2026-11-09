"""A review could start with no test trace or source for a slice's claims; check them first (AIDLC-2)."""
from pathlib import Path

import pytest

from polyctl import cli, specs


GOOD = """# Store

## Problem
Rows could be lost on retry.

## Acceptance criteria
- AC-1: retries preserve rows (T1).
- AC-2: empty input returns no rows (`tests/test_store.py::test_empty`).

## Out of scope
Changing the storage engine.

## Tests
- T1: tests/test_store.py::test_retry
- tests/test_store.py::test_empty

## Risks
Clients might retry concurrently.

## External claims
- The service documents retry semantics [service].

[service]: https://example.invalid/service/retries
"""


def _slice(project, kind="feature", text=GOOD, extra=""):
    root = Path(project["root"])
    path = root / "docs" / "specs" / "S1.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if text is not None:
        path.write_text(text, encoding="utf-8")
    (root / ".polyctl" / "board.md").write_text(
        f"# Board\n\n## running\n- [S1] store · work-type: {kind}{extra}\n", encoding="utf-8")
    return {"id": "S1", "notes": {"work-type": kind}}


def _check(project):
    args = cli.build_parser().parse_args(["spec", "check", "S1"])
    return args.fn(project, args)


def test_good_spec_reports_pass_without_writing(project, capsys):
    _slice(project)
    root = Path(project["root"])
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert cli.main(["-C", project["root"], "spec", "check", "S1"]) == 0
    assert "spec S1 (feature): PASS" in capsys.readouterr().out
    assert before == {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_cli_dispatch_reads_configuration_without_recording(project, monkeypatch):
    _slice(project)

    def read_config(root, record=True):
        assert root == project["root"]
        assert record is False
        return project

    monkeypatch.setattr(cli.A, "load_config", read_config)
    assert cli.main(["-C", project["root"], "spec", "check", "S1"]) == 0


def test_unreadable_project_policy_cannot_fall_back_to_weaker_requirements(project):
    _slice(project)
    (Path(project["root"]) / ".polyctl/config.json").write_text("{\n", encoding="utf-8")
    assert cli.main(["-C", project["root"], "spec", "check", "S1"]) == 1


@pytest.mark.parametrize("kind,code,label", [("feature", 1, "FAIL"), ("enterprise", 1, "FAIL"),
                                            ("bugfix", 0, "WARN"), ("poc", 0, "WARN")])
def test_findings_follow_work_type(project, capsys, kind, code, label):
    _slice(project, kind, "# Bad spec\n\n## Acceptance criteria\n- It works.\n\n"
           "## External claims\n- The service always responds.\n")
    assert _check(project) == code
    output = capsys.readouterr().out
    assert label in output
    assert "missing or empty section 'problem'" in output
    assert "acceptance criterion has no named test" in output
    assert "external claim has no source" in output


@pytest.mark.parametrize("section", specs.REQUIRED_SECTIONS)
def test_each_required_section_is_checked(section):
    text = GOOD.replace("## " + section.title(), "## Other")
    # The fixture uses sentence case for its headings (AIDLC-2).
    text = text.replace("## " + section.capitalize(), "## Other")
    assert any(f"section '{section}'" in problem for problem in specs.findings(text))


def test_every_criterion_needs_its_own_trace():
    text = GOOD.replace("(T1)", "(T10)")
    problems = specs.findings(text)
    assert len(problems) == 1
    assert "line 7: acceptance criterion has no named test" in problems[0]


@pytest.mark.parametrize("reference", ["TEST-retry", "test_retry", "tests/test_store.py::Store::test_retry",
                                        "tests/test_store.py::test_retry[empty]"])
def test_named_test_forms(reference):
    assert specs.findings(GOOD.replace("T1", reference)) == []


def test_unknown_test_id_does_not_trace_a_criterion():
    assert any("no named test" in problem for problem in specs.findings(GOOD.replace("(T1)", "(TEST-absent)")))


def test_a_citation_on_one_claim_does_not_cover_another():
    text = GOOD.replace("[service]:", "- The service also guarantees ordering.\n\n[service]:")
    assert sum("has no source" in problem for problem in specs.findings(text)) == 1


def test_inline_external_claim_and_wrapped_source():
    text = GOOD.replace("Rows could be lost on retry.",
                        "External: the service accepts retries\n  (https://example.invalid/retries).")
    assert specs.findings(text) == []
    assert any("has no source" in problem for problem in specs.findings(
        text.replace("  (https://example.invalid/retries).", "  without a citation.")))


def test_undefined_reference_and_empty_url_are_not_sources():
    for text in (GOOD.replace("[service]:", "[another]:"), GOOD.replace("https://example.invalid/service/retries", "https://")):
        assert any("has no source" in problem for problem in specs.findings(text))


def test_adjacent_external_claims_and_sections_do_not_share_sources():
    text = GOOD.replace("Rows could be lost on retry.", "External: first claim has no source.\n"
                        "External: second claim https://example.invalid/retries")
    assert sum("has no source" in problem for problem in specs.findings(text)) == 1
    text = GOOD.replace("Rows could be lost on retry.", "External: missing source.").replace(
        "## Acceptance criteria", "## Sources\nhttps://example.invalid/retries\n\n## Acceptance criteria")
    assert sum("has no source" in problem for problem in specs.findings(text)) == 1


def test_examples_and_comments_supply_no_evidence():
    text = "```markdown\n" + GOOD + "```\n<!--\n" + GOOD + "-->\n"
    assert len(specs.findings(text)) == 6
    text = GOOD.replace("- AC-1: retries preserve rows (T1).", "- AC-1: retries preserve rows. <!-- T1 -->")
    assert any("no named test" in problem for problem in specs.findings(text))


def test_empty_section_and_empty_criteria_are_findings():
    text = GOOD.replace("Clients might retry concurrently.", "")
    assert any("section 'risks'" in problem for problem in specs.findings(text))
    assert "no acceptance criteria; list each criterion with a named test" in specs.findings("## Acceptance criteria\n")


def test_custom_requirements_are_per_work_type(project):
    item = _slice(project, "poc", "## Acceptance criteria\n- Returns no rows (tests/test_store.py::test_empty).\n")
    project["work_types"] = {"poc": {"required_sections": ["acceptance criteria"]},
                             "enterprise": {"required_sections": ["rollout"]}}
    assert specs.check(project, item)["findings"] == []
    item["notes"]["work-type"] = "enterprise"
    assert specs.check(project, item)["blocked"]
    assert "section 'rollout'" in specs.check(project, item)["findings"][0]


@pytest.mark.parametrize("policy", [None, [], {"feature": None}, {"feature": {"required_sections": "problem"}},
                                    {"feature": {"required_sections": [False]}}])
def test_bad_policy_is_reported(project, policy):
    item = _slice(project)
    project["work_types"] = policy
    assert specs.check(project, item)["blocked"]
    assert "configuration" in specs.check(project, item)["findings"][0]


@pytest.mark.parametrize("kind,blocked", [("feature", True), ("bugfix", False), ("unknown", True)])
def test_missing_spec_and_unknown_type(project, kind, blocked):
    result = specs.check(project, _slice(project, kind, None))
    assert result["blocked"] is blocked
    assert result["findings"]


def test_explicit_path_and_path_escape(project, tmp_path):
    item = _slice(project)
    item["notes"]["spec"] = "docs/specs/S1.md"
    assert not specs.check(project, item)["findings"]
    outside = tmp_path / "outside.md"
    outside.write_text(GOOD, encoding="utf-8")
    for path in (str(outside), "../outside.md"):
        item["notes"]["spec"] = path
        assert specs.check(project, item)["blocked"]


def test_symlink_outside_project_is_refused(project, tmp_path):
    item = _slice(project)
    outside = tmp_path / "outside.md"
    outside.write_text(GOOD, encoding="utf-8")
    link = Path(project["root"]) / "link.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("this platform does not allow creating symlinks")
    item["notes"]["spec"] = "link.md"
    assert specs.check(project, item)["blocked"]


def test_spec_size_encoding_and_file_type_are_bounded(project, monkeypatch):
    item = _slice(project)
    monkeypatch.setattr(specs, "MAX_SPEC_BYTES", 16)
    assert "exceeds" in specs.check(project, item)["findings"][0]
    path = Path(project["root"]) / "docs/specs/S1.md"
    path.write_bytes(b"\xff")
    assert "encoding" in specs.check(project, item)["findings"][0]
    item["notes"]["spec"] = "docs/specs"
    assert specs.check(project, item)["blocked"]


def test_unknown_and_duplicate_slice_are_refused(project):
    assert _check(project) == 2
    _slice(project)
    board = Path(project["root"]) / ".polyctl/board.md"
    board.write_text(board.read_text(encoding="utf-8") + "- [S1] duplicate\n", encoding="utf-8")
    assert _check(project) == 2


@pytest.mark.parametrize("action", [[], ["submit"]])
@pytest.mark.parametrize("kind", ["feature", "enterprise"])
def test_bad_spec_stops_review_before_a_reviewer_or_state_write(project, monkeypatch, action, kind):
    _slice(project, kind, "# incomplete\n")
    monkeypatch.setattr(cli.A, "index_candidate", lambda root: {"changed_paths": ["store.py"]})
    monkeypatch.setattr(cli, "_review_states", lambda root: [])
    monkeypatch.setattr(cli.A, "hold_unseen_routes", lambda *args: pytest.fail("reviewer preparation reached"))
    monkeypatch.setattr(cli, "_claim_review_id", lambda *args: pytest.fail("review state written"))
    args = cli.build_parser().parse_args(["review", *action])
    assert args.fn(project, args) == 1


@pytest.mark.parametrize("kind,text", [("bugfix", "# incomplete\n"), ("poc", "# incomplete\n"), ("feature", GOOD)])
def test_advisory_or_good_specs_allow_review_to_continue(project, monkeypatch, capsys, kind, text):
    _slice(project, kind, text)
    class ReachedReview(Exception):
        pass

    def reached(*args):
        raise ReachedReview()

    monkeypatch.setattr(cli.A, "hold_unseen_routes", reached)
    args = cli.build_parser().parse_args(["review"])
    with pytest.raises(ReachedReview):
        args.fn(project, args)
    assert ("WARN" if kind != "feature" else "PASS") in capsys.readouterr().out


def test_pinned_and_retrospective_reviews_do_not_check_the_next_slice(project, monkeypatch):
    _slice(project, "enterprise", "# incomplete\n")
    monkeypatch.setattr(cli, "_review_spec_check", lambda *args: pytest.fail("wrong slice checked"))
    class ReachedReview(Exception):
        pass

    def reached(*args):
        raise ReachedReview()

    monkeypatch.setattr(cli.A, "hold_unseen_routes", reached)
    for words in (["review", "--commits", "HEAD~1..HEAD"], ["review"]):
        args = cli.build_parser().parse_args(words)
        args.pinned = len(words) == 1
        with pytest.raises(ReachedReview):
            args.fn(project, args)


def test_legacy_untyped_slice_keeps_its_boundary_contract(project):
    assert cli._review_spec_check(project, {"id": "old", "notes": {"acceptance": "keep rows"}}) == 0
    assert cli._review_spec_check(project, None) == 0
