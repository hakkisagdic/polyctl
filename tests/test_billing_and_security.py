"""Tests for P0-3 pre-commit secret and KVKK PII scanner."""
import json
from pathlib import Path

from polyctl import cli, security as SEC


def test_pre_commit_security_scanner_detects_secrets_pii_and_fails_closed(project, capsys):
    root = Path(project["root"])
    leaked_file = root / "config_leak.py"
    # Construct synthetic secret tokens at runtime so no static scanner flags this test file
    fake_anth = "sk-ant-api03-" + ("A" * 24)
    fake_aws = "AKIA" + ("B" * 16)
    fake_gh = "ghp_" + ("C" * 36)
    fake_tckn = "10000000146"
    leaked_file.write_text(
        f'ANTHROPIC_KEY = "{fake_anth}"\n'
        f'AWS_ID = "{fake_aws}"\n'
        f'GH_TOKEN = "{fake_gh}"\n'
        f'musteri_tckn = "{fake_tckn}"\n',
        encoding="utf-8",
    )

    report = SEC.scan_paths(str(root), ["config_leak.py"])
    assert report["ok"] is False
    assert report["counts"]["BLOCKER"] == 3
    assert report["counts"]["HIGH"] == 1
    rule_ids = [f["rule_id"] for f in report["findings"]]
    assert rule_ids == ["SEC-001", "SEC-003", "SEC-004", "SEC-008"]

    # Ensure cleartext secrets and TCKN digits are never present in the report or CLI output
    serialized = json.dumps(report)
    assert fake_anth not in serialized
    assert fake_aws not in serialized
    assert fake_gh not in serialized
    assert fake_tckn not in serialized
    tckn_finding = [f for f in report["findings"] if f["rule_id"] == "SEC-008"][0]
    assert tckn_finding["masked_match"] == "***REDACTED***"
    assert all("***REDACTED***" in f["masked_match"] for f in report["findings"])

    code = cli.main(["-C", str(root), "security-scan", "--paths", "config_leak.py"])
    out = capsys.readouterr().out
    assert code == 1
    assert "SECURITY SCAN BLOCKED" in out
    assert fake_anth not in out

    # Nonexistent path or path outside repo fails closed (`verdict == "ERROR"`, exit 1)
    err_report = SEC.scan_paths(str(root), ["does_not_exist.py"])
    assert err_report["ok"] is False
    assert err_report["verdict"] == "ERROR"
    assert cli.main(["-C", str(root), "security-scan", "--paths", "does_not_exist.py"]) == 1
    capsys.readouterr()

    clean_file = root / "clean.py"
    clean_file.write_text("x = 42\n", encoding="utf-8")
    assert cli.main(["-C", str(root), "security-scan", "--paths", "clean.py"]) == 0
    assert "SECURITY SCAN PASS" in capsys.readouterr().out
