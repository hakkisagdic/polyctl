"""Tests for Team Role-Based Access Control (RBAC) and Policy-as-Code enforcement engine (P1-2)."""
import json
import subprocess
import pytest

from polyctl import billing, cli, policy, storage


def _init_repo(tmp_path, monkeypatch):
    ckpt = tmp_path / "checkpoints.json"
    monkeypatch.setenv("POLYCTL_LEDGER_CHECKPOINTS", str(ckpt))
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test User"], check=True)
    (repo / ".polyctl" / "ledger").mkdir(parents=True)
    cfg = {
        "project": "test-policy",
        "actors": {
            "qoder-implementer": {"id": "qoder-implementer", "adapter": "qoder", "family": "alibaba"},
            "claude-reviewer": {"id": "claude-reviewer", "adapter": "claude-code", "family": "anthropic"},
        },
        "roles": {"implementer": "qoder-implementer", "reviewer": "claude-reviewer"},
    }
    (repo / ".polyctl" / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    (repo / "README.md").write_text("# test\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "initial"], check=True, capture_output=True)
    return repo


def test_rbac_permissions_and_role_binding(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path, monkeypatch)
    pol = policy.load_policy(str(repo))
    assert pol["bindings"]["admin"] == "owner"
    assert pol["bindings"]["implementer"] == "implementer"

    # Implementer cannot export compliance bundles or grant commits, but can write code
    assert policy.check_permission(str(repo), "implementer", "code:write")["ok"] is True
    assert policy.check_permission(str(repo), "implementer", "commit:grant")["ok"] is False
    assert policy.check_permission(str(repo), "implementer", "policy:write")["ok"] is False

    # Bind a custom developer actor to architect role
    policy.bind_actor_role(str(repo), "dev-lead", "architect")
    assert policy.check_permission(str(repo), "dev-lead", "commit:grant")["ok"] is True
    assert policy.check_permission(str(repo), "dev-lead", "compliance:export")["ok"] is True
    assert policy.check_permission(str(repo), "dev-lead", "policy:write")["ok"] is False


def test_policy_forbidden_paths_and_max_lines_enforcement(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path, monkeypatch)
    policy.save_policy(str(repo), policy.load_policy(str(repo)))

    # Implementer staging a workflow file under .github/workflows/* is blocked
    wf_dir = repo / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    wf_file = wf_dir / "deploy.yml"
    wf_file.write_text("name: CI\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", ".github/workflows/deploy.yml"], check=True)

    res_imp = policy.evaluate_policy(str(repo), actor="implementer", permission="code:write")
    assert res_imp["ok"] is False
    assert res_imp["verdict"] == "DENY"
    assert any(v["rule"] == "forbidden_paths_for_implementer" for v in res_imp["violations"])

    # Architect is permitted to modify .github/workflows/deploy.yml
    res_arch = policy.evaluate_policy(str(repo), actor="architect", permission="code:write")
    assert res_arch["ok"] is True
    assert res_arch["verdict"] == "ALLOW"

    # Unstage workflow file and test max_product_lines violation
    subprocess.run(["git", "-C", str(repo), "reset", "HEAD", ".github/workflows/deploy.yml"], check=True)
    wf_file.unlink()
    policy.update_policy_rules(str(repo), max_product_lines=10)
    big_file = repo / "app.py"
    big_file.write_text("\n".join(f"x_{i} = {i}" for i in range(25)) + "\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "app.py"], check=True)

    res_lines = policy.evaluate_policy(str(repo), actor="implementer")
    assert res_lines["ok"] is False
    assert any(v["rule"] == "max_product_lines" for v in res_lines["violations"])


def test_policy_security_scan_budget_and_cross_family_rules(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path, monkeypatch)
    policy.save_policy(str(repo), policy.load_policy(str(repo)))

    # 1. Staged secret triggers require_security_scan violation
    leak = repo / "secret.py"
    leak.write_text('KEY = "sk-ant-api03-' + ("b" * 48) + '"\n', encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "secret.py"], check=True)
    res_sec = policy.evaluate_policy(str(repo), actor="implementer")
    assert res_sec["ok"] is False
    assert any(v["rule"] == "require_security_scan" for v in res_sec["violations"])
    subprocess.run(["git", "-C", str(repo), "reset", "HEAD", "secret.py"], check=True)
    leak.unlink()

    # 2. Same model family for implementer and reviewer triggers require_cross_family_review violation
    cfg_path = repo / ".polyctl" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["actors"]["claude-reviewer"]["family"] = "alibaba"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    res_fam = policy.evaluate_policy(str(repo), actor="implementer")
    assert res_fam["ok"] is False
    assert any(v["rule"] == "require_cross_family_review" for v in res_fam["violations"])


def test_policy_tamper_and_checkpoint_divergence_detection(tmp_path, monkeypatch):
    repo = _init_repo(tmp_path, monkeypatch)
    monkeypatch.setenv("POLYCTL_POLICY_SIGNING_KEY", "policy-hmac-secret-2026")
    saved = policy.save_policy(str(repo), policy.load_policy(str(repo)))
    assert saved["integrity_verified"] is True
    assert saved["integrity_sha256"].startswith("hmac-sha256:")

    # Editing policy.json directly in working tree raises LedgerCorruption
    p_file = repo / ".polyctl" / "policy" / "policy.json"
    data = json.loads(p_file.read_text(encoding="utf-8"))
    data["rules"]["max_product_lines"] = 9999
    p_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    with pytest.raises(storage.LedgerCorruption, match="failed integrity verification"):
        policy.load_policy(str(repo))

    # Deleting policy.json after it was attested in checkpoint raises LedgerCorruption
    p_file.unlink()
    with pytest.raises(storage.LedgerCorruption, match="missing but checkpoint records"):
        policy.load_policy(str(repo))


def test_policy_cli_commands(tmp_path, monkeypatch, capsys):
    repo = _init_repo(tmp_path, monkeypatch)
    assert cli.main(["-C", str(repo), "policy", "init", "--json"]) == 0
    capsys.readouterr()

    assert cli.main(["-C", str(repo), "policy", "bind", "--actor", "ci-bot", "--role", "auditor", "--json"]) == 0
    bind_out = json.loads(capsys.readouterr().out)
    assert bind_out["bindings"]["ci-bot"] == "auditor"

    assert cli.main(["-C", str(repo), "policy", "check", "--actor", "ci-bot", "--permission", "compliance:export", "--json"]) == 0
    chk_out = json.loads(capsys.readouterr().out)
    assert chk_out["ok"] is True

    assert cli.main(["-C", str(repo), "policy", "check", "--actor", "ci-bot", "--permission", "code:write", "--json"]) == 1
    deny_out = json.loads(capsys.readouterr().out)
    assert deny_out["ok"] is False
