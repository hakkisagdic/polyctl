"""Tests for enterprise compliance & audit evidence bundle export and verification (P1-1)."""
import json
import subprocess
import pytest

from polyctl import billing, cli, compliance, storage


def _init_bare_repo(tmp_path, monkeypatch):
    ckpt = tmp_path / "checkpoints.json"
    monkeypatch.setenv("POLYCTL_LEDGER_CHECKPOINTS", str(ckpt))
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test User"], check=True)
    (repo / ".polyctl" / "ledger").mkdir(parents=True)
    (repo / "README.md").write_text("# test\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    tree_sha = subprocess.check_output(["git", "-C", str(repo), "write-tree"], text=True).strip()
    subprocess.run(
        [
            "git", "-C", str(repo), "commit", "-m",
            f"initial\n\nPolyctl-Grant: C-100\nPolyctl-Tree: {tree_sha}\nPolyctl-Verification: V-100\nPolyctl-Review: 2026-11-13-000000-init.md",
        ],
        check=True,
        capture_output=True,
    )
    return repo, tree_sha


def _init_governed_repo(tmp_path, monkeypatch):
    repo, tree_sha = _init_bare_repo(tmp_path, monkeypatch)
    storage.append_chained_jsonl(
        str(repo / ".polyctl" / "ledger" / "authority.jsonl"),
        {"token": "C-100", "granted": True, "candidate": {"index_tree": tree_sha}, "verification": "V-100", "review": "2026-11-13-000000-init.md"},
        "polyctl-authority-row-v1",
    )
    storage.append_chained_jsonl(
        str(repo / ".polyctl" / "ledger" / "verifications.jsonl"),
        {"id": "V-100", "passed": True, "profile": "quick"},
        "polyctl-verification-row-v1",
        legacy_prefix=True,
    )
    storage.append_chained_jsonl(
        str(repo / ".polyctl" / "ledger" / "reviews.jsonl"),
        {"artefact": "2026-11-13-000000-init.md", "verdict": "APPROVED", "tier": "independent"},
        "polyctl-review-row-v1",
    )
    storage.append_chained_jsonl(
        str(repo / ".polyctl" / "ledger" / "slices.jsonl"),
        {"id": "P1-1", "state": "running"},
        "polyctl-slice-row-v1",
        legacy_prefix=True,
    )
    billing.record_usage(str(repo), kind="review", model="claude-sonnet-4-5", prompt_tokens=500, completion_tokens=100)
    return repo


def test_ungoverned_and_mixed_commits_are_non_compliant(tmp_path, monkeypatch):
    repo, _ = _init_bare_repo(tmp_path, monkeypatch)
    rep = compliance.collect_compliance_evidence(str(repo), framework="all")
    assert rep["ok"] is False
    assert rep["status"] == "NON_COMPLIANT"
    assert rep["evidence"]["git_trailers"]["trailer_commits"] == 1
    assert rep["evidence"]["git_trailers"]["governed_commits"] == 0
    assert rep["evidence"]["git_trailers"]["ungoverned_commits"] == 1
    assert rep["evidence"]["git_trailers"]["all_governed"] is False
    with pytest.raises(ValueError, match="NON_COMPLIANT"):
        compliance.export_compliance_bundle(str(repo), framework="all")

    gov_repo = _init_governed_repo(tmp_path / "gov", monkeypatch)
    assert compliance.collect_compliance_evidence(str(gov_repo))["ok"] is True
    (gov_repo / "README.md").write_text("# bypassed commit\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(gov_repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(gov_repo), "commit", "--no-verify", "-m", "unreviewed change"], check=True, capture_output=True)

    mixed = compliance.collect_compliance_evidence(str(gov_repo), framework="all")
    assert mixed["ok"] is False
    assert mixed["status"] == "NON_COMPLIANT"
    assert mixed["evidence"]["git_trailers"]["governed_commits"] == 1
    assert mixed["evidence"]["git_trailers"]["ungoverned_commits"] == 1
    assert mixed["evidence"]["git_trailers"]["all_governed"] is False
    by_id = {c["control_id"]: c["status"] for c in mixed["controls"]}
    assert by_id["CC6.1"] == "NOT_MET"
    assert by_id["CC8.1"] == "NOT_MET"
    assert by_id["A.6.2"] == "NOT_MET"
    assert by_id["A.8.4"] == "NOT_MET"
    assert by_id["KVKK-M12.2"] == "NOT_MET"


def test_pre_enrollment_history_and_status_filtering(tmp_path, monkeypatch):
    # Pre-enrollment commit without Polyctl trailers followed by governed enrollment commit (no candidate.head)
    ckpt = tmp_path / "checkpoints.json"
    monkeypatch.setenv("POLYCTL_LEDGER_CHECKPOINTS", str(ckpt))
    repo = tmp_path / "enrolled"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test User"], check=True)
    (repo / ".polyctl" / "ledger").mkdir(parents=True)
    (repo / "LEGACY.md").write_text("legacy before polyctl\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "LEGACY.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "pre-polyctl history"], check=True, capture_output=True)

    (repo / "README.md").write_text("# enrolled\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    tree_sha = subprocess.check_output(["git", "-C", str(repo), "write-tree"], text=True).strip()
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", f"enroll\n\nPolyctl-Grant: C-200\nPolyctl-Tree: {tree_sha}\nPolyctl-Verification: V-200\nPolyctl-Review: 2026-11-13-000000-init.md"],
        check=True, capture_output=True,
    )
    storage.append_chained_jsonl(str(repo / ".polyctl" / "ledger" / "authority.jsonl"), {"token": "C-200", "granted": True, "candidate": {"index_tree": tree_sha}, "verification": "V-200", "review": "2026-11-13-000000-init.md"}, "polyctl-authority-row-v1")
    storage.append_chained_jsonl(str(repo / ".polyctl" / "ledger" / "verifications.jsonl"), {"id": "V-200", "passed": True, "profile": "quick"}, "polyctl-verification-row-v1", legacy_prefix=True)
    storage.append_chained_jsonl(str(repo / ".polyctl" / "ledger" / "reviews.jsonl"), {"artefact": "2026-11-13-000000-init.md", "verdict": "APPROVED", "tier": "independent"}, "polyctl-review-row-v1")
    storage.append_chained_jsonl(str(repo / ".polyctl" / "ledger" / "slices.jsonl"), {"id": "P1-1", "state": "running"}, "polyctl-slice-row-v1", legacy_prefix=True)
    billing.record_usage(str(repo), kind="review", model="claude-sonnet-4-5", prompt_tokens=500, completion_tokens=100)

    rep_all = compliance.collect_compliance_evidence(str(repo), framework="all")
    assert rep_all["ok"] is True
    assert rep_all["status"] == "COMPLIANT"
    assert rep_all["evidence"]["git_trailers"]["commits_checked"] == 1
    assert rep_all["evidence"]["git_trailers"]["governed_commits"] == 1
    assert rep_all["evidence"]["git_trailers"]["ungoverned_commits"] == 0

    rep_kvkk = compliance.collect_compliance_evidence(str(repo), framework="kvkk")
    assert {c["framework"] for c in rep_kvkk["controls"]} == {"kvkk"}
    assert all(c["status"] == "MET" for c in rep_kvkk["controls"])


def test_compliance_export_verify_and_checkpoint_rollback(tmp_path, monkeypatch):
    repo = _init_governed_repo(tmp_path, monkeypatch)
    monkeypatch.delenv("POLYCTL_COMPLIANCE_SIGNING_KEY", raising=False)

    # Simulate failure writing state.json after checkpoint update: checkpoint must roll back cleanly
    orig_replace = storage.replace_in_tree
    def _fail_state(root_arg, rel_arg, data_arg):
        if rel_arg == compliance.COMPLIANCE_STATE_REL:
            raise OSError("simulated state.json write failure")
        return orig_replace(root_arg, rel_arg, data_arg)
    monkeypatch.setattr(storage, "replace_in_tree", _fail_state)
    with pytest.raises(OSError, match="simulated state.json write failure"):
        compliance.export_compliance_bundle(str(repo), framework="all")
    assert not compliance._ckpt_get(str(repo)).get("compliance_active")
    monkeypatch.setattr(storage, "replace_in_tree", orig_replace)

    bundle = compliance.export_compliance_bundle(str(repo), framework="all")
    assert bundle["ok"] is True
    assert bundle["checksum_matches"] is True
    assert bundle["integrity_verified"] is False

    v_unkeyed = compliance.verify_compliance_bundle(str(repo), bundle["bundle_id"])
    assert v_unkeyed["ok"] is True

    monkeypatch.setenv("POLYCTL_COMPLIANCE_SIGNING_KEY", "enterprise-secret-key-2026")
    v_under_key = compliance.verify_compliance_bundle(str(repo), bundle["bundle_id"])
    assert v_under_key["ok"] is False
    assert any("HMAC-SHA256" in err for err in v_under_key["errors"])

    signed = compliance.export_compliance_bundle(str(repo), framework="soc2")
    assert signed["integrity_verified"] is True
    v_signed = compliance.verify_compliance_bundle(str(repo), signed["bundle_id"])
    assert v_signed["ok"] is True
    assert v_signed["integrity_verified"] is True


def test_compliance_tamper_digest_mismatch_forged_and_missing_ledger(tmp_path, monkeypatch):
    repo = _init_governed_repo(tmp_path, monkeypatch)
    monkeypatch.delenv("POLYCTL_COMPLIANCE_SIGNING_KEY", raising=False)
    bundle = compliance.export_compliance_bundle(str(repo), framework="all")
    b_path = repo / ".polyctl" / "compliance" / "bundles" / f"{bundle['bundle_id']}.json"
    orig_data = json.loads(b_path.read_text(encoding="utf-8"))

    # 1. Direct content edit without recomputing bundle_digest triggers bundle_digest mismatch
    tampered_direct = dict(orig_data, generated_at="2099-01-01T00:00:00Z")
    b_path.write_text(json.dumps(tampered_direct, indent=2), encoding="utf-8")
    v_direct = compliance.verify_compliance_bundle(str(repo), bundle["bundle_id"])
    assert v_direct["ok"] is False
    assert v_direct["checksum_matches"] is False
    assert any("bundle_digest mismatch" in e for e in v_direct["errors"])

    # 2. Forged bundle with a brand-new bundle_id never exported by polyctl is rejected
    forged = dict(orig_data, bundle_id="CMP-20261113-deadbeef00")
    f_digest, f_sig, _ = compliance._canonical_digests(forged)
    forged["bundle_digest"], forged["integrity_sha256"] = f_digest, f_sig
    forged_path = tmp_path / "forged.json"
    forged_path.write_text(json.dumps(forged, indent=2), encoding="utf-8")
    v_forged = compliance.verify_compliance_bundle(str(repo), str(forged_path))
    assert v_forged["ok"] is False
    assert v_forged["checkpoint_matches"] is False
    assert any("not attested in machine checkpoint store" in e for e in v_forged["errors"])

    # 3. Bundle dropping a ledger or having row_count=None fails cleanly without TypeError
    dropped = json.loads(json.dumps(orig_data))
    dropped["evidence"]["ledgers"] = [l for l in dropped["evidence"]["ledgers"] if l["name"] != "authority"]
    dropped["evidence"]["ledgers"][0]["row_count"] = None
    d_digest, d_sig, _ = compliance._canonical_digests(dropped)
    dropped["bundle_digest"], dropped["integrity_sha256"] = d_digest, d_sig
    b_path.write_text(json.dumps(dropped, indent=2), encoding="utf-8")
    v_dropped = compliance.verify_compliance_bundle(str(repo), bundle["bundle_id"])
    assert v_dropped["ok"] is False
    assert v_dropped["ledgers_valid"] is False
    assert any("missing required ledger 'authority'" in e for e in v_dropped["errors"])
    assert any("invalid row_count" in e for e in v_dropped["errors"])

    # 4. Deleting .polyctl/compliance/state.json raises LedgerCorruption
    (repo / ".polyctl" / "compliance" / "state.json").unlink()
    with pytest.raises(storage.LedgerCorruption):
        compliance.collect_compliance_evidence(str(repo))


def test_compliance_detects_non_ascii_path_and_working_tree_hidden_secret(tmp_path, monkeypatch):
    repo = _init_governed_repo(tmp_path, monkeypatch)
    # Tracked PII inside non-ASCII Turkish filename tests/kullanıcı.py must be scanned via git ls-files -z
    fixtures_dir = repo / "tests"
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    tr_file = fixtures_dir / "kullanıcı.py"
    tr_file.write_text('tckn = "12345678901"\n', encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "tests/kullanıcı.py"], check=True)
    tree_sha = subprocess.check_output(["git", "-C", str(repo), "write-tree"], text=True).strip()
    head_sha = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", f"add tr file\n\nPolyctl-Grant: C-101\nPolyctl-Tree: {tree_sha}\nPolyctl-Verification: V-100\nPolyctl-Review: 2026-11-13-000000-init.md"],
        check=True, capture_output=True,
    )
    storage.append_chained_jsonl(
        str(repo / ".polyctl" / "ledger" / "authority.jsonl"),
        {"token": "C-101", "granted": True, "candidate": {"index_tree": tree_sha, "head": head_sha}, "verification": "V-100", "review": "2026-11-13-000000-init.md"},
        "polyctl-authority-row-v1",
    )

    rep_tr = compliance.collect_compliance_evidence(str(repo), framework="all")
    assert rep_tr["ok"] is False
    assert rep_tr["evidence"]["security_scan"]["pii_clean"] is False

    # Even if the working-tree copy is wiped clean without committing, the secret in HEAD is still detected
    tr_file.write_text("# cleaned only in working tree\n", encoding="utf-8")
    rep_head = compliance.collect_compliance_evidence(str(repo), framework="all")
    assert rep_head["ok"] is False
    assert rep_head["evidence"]["security_scan"]["pii_clean"] is False

    # And if a tracked file is deleted from the working tree, scan_paths fails closed
    tr_file.unlink()
    rep_del = compliance.collect_compliance_evidence(str(repo), framework="all")
    assert rep_del["ok"] is False
    assert rep_del["evidence"]["security_scan"]["ok"] is False


def test_compliance_cli_commands(tmp_path, monkeypatch, capsys):
    repo = _init_governed_repo(tmp_path, monkeypatch)
    monkeypatch.setenv("POLYCTL_COMPLIANCE_SIGNING_KEY", "cli-test-signing-key")
    out_file = tmp_path / "external-bundle.json"

    rc = cli.main(["-C", str(repo), "compliance", "status", "--framework", "all", "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["status"] == "COMPLIANT"

    rc = cli.main(["-C", str(repo), "compliance", "export", "--framework", "all", "--out", str(out_file), "--json"])
    assert rc == 0
    exp_out = json.loads(capsys.readouterr().out)
    assert out_file.is_file() and exp_out["integrity_verified"] is True

    rc = cli.main(["-C", str(repo), "compliance", "verify", str(out_file), "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
