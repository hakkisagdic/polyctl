"""Unit tests for open-core billing, iyzico/local payment providers, usage metering, spend-cap gate, and security scanner."""
import base64
import hashlib
import hmac
import json
import shutil
import urllib.request
from pathlib import Path

import pytest

import http.client
import threading
from types import SimpleNamespace
from polyctl import billing as B, cli, security as SEC, storage, web


def test_plans_and_quote_calculations_try_and_usd():
    plans_try = B.list_plans("TRY")
    assert [p["id"] for p in plans_try] == ["community", "pro", "team", "enterprise"]
    assert plans_try[1]["display_monthly"] == 690.0

    plans_usd = B.list_plans("USD")
    assert plans_usd[1]["display_monthly"] == 19.0

    with pytest.raises(ValueError):
        B.list_plans("EUR")

    # Team plan enforces minimum 3 seats and 20% KDV for TRY
    q_team_try = B.calculate_quote("team", seats=1, currency="TRY", cycle="monthly")
    assert q_team_try["seats"] == 3
    assert q_team_try["base_amount"] == 4470.0
    assert q_team_try["tax"] == 894.0
    assert q_team_try["total"] == 5364.0
    assert q_team_try["included_units"] == 6000

    # Yearly plan charges yearly price (2 months free) while keeping monthly quota allowance (500 units/mo)
    q_pro_usd = B.calculate_quote("pro", seats=5, currency="USD", cycle="yearly", overage_units=50)
    assert q_pro_usd["seats"] == 1
    assert q_pro_usd["base_amount"] == 190.0
    assert q_pro_usd["overage_amount"] == 1.0
    assert q_pro_usd["tax"] == 0.0
    assert q_pro_usd["total"] == 191.0
    assert q_pro_usd["included_units"] == 500


def test_payment_provider_abstraction_iyzico_checkout_and_invoice_integrity(project, monkeypatch):
    root = project["root"]
    monkeypatch.setenv("POLYCTL_BILLING_SIGNING_KEY", "test-billing-hmac-secret-key")
    monkeypatch.delenv("IYZICO_API_KEY", raising=False)
    monkeypatch.delenv("IYZICO_SECRET_KEY", raising=False)
    monkeypatch.delenv("IYZICO_BASE_URL", raising=False)

    # Default base URL is live api.iyzipay.com, and unconfigured provider fails closed
    assert B.IyzicoPaymentProvider().base_url == "https://api.iyzipay.com"
    unconf = B.subscribe_plan(root, "pro", currency="TRY", provider_name="iyzico")
    assert unconf["ok"] is False
    assert unconf["checkout"]["status"] == "FAILED"
    assert B.list_invoices(root) == []

    monkeypatch.setenv("IYZICO_API_KEY", "live-api-key")
    monkeypatch.setenv("IYZICO_SECRET_KEY", "live-secret-key")

    captured = []

    def _fake_urlopen(req, timeout=15):
        body = req.data.decode("utf-8") if req.data else ""
        captured.append((req.full_url, dict(req.header_items()), body))
        payload = json.loads(body) if body else {}
        if req.full_url.endswith(B.IyzicoPaymentProvider.INITIALIZE_URI):
            resp = {"status": "success", "token": "iyz_tok_123", "paymentPageUrl": "https://api.iyzipay.com/checkout/iyz_tok_123"}
        else:
            resp = {"status": "success", "paymentStatus": "SUCCESS", "paymentId": "iyz_pay_9001", "basketId": "B-polyctl-pro-abc123", "paidPrice": float(payload.get("expected_paid", 828.0)), "currency": "TRY"}
        class _Resp:
            def read(self):
                return json.dumps(resp).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    # Step 1: Without --payment-token, create_checkout initializes checkout form and returns PENDING_CHECKOUT (not PAID)
    init_res = B.subscribe_plan(root, "pro", seats=1, currency="TRY", cycle="monthly", provider_name="iyzico", customer="Acme Yazilim A.S.", tax_id="1234567890")
    assert init_res["ok"] is False
    assert init_res["checkout"]["status"] == "PENDING_CHECKOUT"
    assert init_res["checkout"]["checkout_token"] == "iyz_tok_123"
    assert B.list_invoices(root) == []

    url, headers, body = captured[0]
    assert url == "https://api.iyzipay.com/payment/iyzipos/checkoutform/initialize/auth/ecom"
    rnd = headers.get("X-iyzi-rnd") or headers.get("x-iyzi-rnd")
    expected_auth, _ = B.IyzicoPaymentProvider.build_iyzws_v2_header("live-api-key", "live-secret-key", rnd, B.IyzicoPaymentProvider.INITIALIZE_URI, body)
    assert (headers.get("Authorization") or headers.get("authorization")) == expected_auth
    sent = json.loads(body)
    assert sent["paidPrice"] == "828.00"
    assert sent["buyer"]["identityNumber"] == "1234567890"
    assert sent["billingAddress"]["city"] == "Istanbul"
    assert len(sent["basketItems"]) == 1

    # Step 2: With --payment-token, create_checkout calls /payment/iyzipos/checkoutform/auth/ecom/detail and verifies paidPrice + basketId
    paid_res = B.subscribe_plan(root, "pro", seats=1, currency="TRY", cycle="monthly", provider_name="iyzico", customer="Acme Yazilim A.S.", tax_id="1234567890", payment_token="iyz_tok_123")
    assert paid_res["ok"] is True
    assert paid_res["checkout"]["status"] == "PAID"
    assert paid_res["checkout"]["payment_reference"] == "iyz_pay_9001"

    # Replaying the same payment_token is rejected with REPLAYED
    replay_res = B.subscribe_plan(root, "pro", seats=1, currency="TRY", cycle="monthly", provider_name="iyzico", customer="Acme Yazilim A.S.", tax_id="1234567890", payment_token="iyz_tok_123")
    assert replay_res["ok"] is False
    assert replay_res["checkout"]["status"] == "REPLAYED"

    # Attempting to use a Pro basket token for an Enterprise plan is rejected on basketId mismatch
    mismatch_res = B.subscribe_plan(root, "enterprise", seats=10, currency="TRY", cycle="monthly", provider_name="iyzico", customer="Acme Yazilim A.S.", tax_id="1234567890", payment_token="iyz_tok_other")
    assert mismatch_res["ok"] is False
    assert "basketId" in mismatch_res["checkout"]["error"]

    sub = B.load_subscription(root)
    assert sub["plan_id"] == "pro" and sub["status"] == "ACTIVE"
    assert sub["checksum_matches"] is True and sub["integrity_verified"] is True
    assert sub["period"] == sub["expires_period"]

    # Subscription expires in the next billing period and falls back to 50-unit Community quota
    assert B.usage_summary(root, period="2099-12")["included_units"] == 50

    inv = B.list_invoices(root)[0]
    assert inv["invoice_id"].startswith("INV-")
    assert inv["checksum_matches"] is True and inv["integrity_verified"] is True

    # Tampering with invoice total invalidates checksum_matches and integrity_verified
    inv_file = Path(B.invoice_path(root, inv["invoice_id"]))
    tampered = json.loads(inv_file.read_text(encoding="utf-8"))
    tampered["total"] = 1.0
    inv_file.write_text(json.dumps(tampered), encoding="utf-8")
    after = B.list_invoices(root)[0]
    assert after["checksum_matches"] is False and after["integrity_verified"] is False

    # Even if all invoice files in the working tree are deleted, checkpoint replay protection rejects the old token
    inv_file.unlink()
    replay_after_delete = B.subscribe_plan(root, "pro", seats=1, currency="TRY", cycle="monthly", provider_name="iyzico", customer="Acme Yazilim A.S.", tax_id="1234567890", payment_token="iyz_tok_123")
    assert replay_after_delete["ok"] is False and replay_after_delete["checkout"]["status"] == "REPLAYED"


def test_usage_metering_overage_settlement_across_upgrades_and_tamper_checks(project, monkeypatch):
    root = project["root"]
    monkeypatch.setenv("POLYCTL_BILLING_SIGNING_KEY", "test-billing-hmac-secret-key")
    monkeypatch.setenv("IYZICO_API_KEY", "live-key")
    monkeypatch.setenv("IYZICO_SECRET_KEY", "live-secret")

    # Local simulation writes SIM- invoice, reports 50 enforced included_units, and never lifts quota block
    sim_res = B.subscribe_plan(root, "pro", currency="TRY", provider_name="local")
    assert sim_res["invoice"]["invoice_id"].startswith("SIM-")
    assert B.usage_summary(root)["included_units"] == 50
    assert B.usage_summary(root)["plan_units"] == 500

    seq = {"n": 0}
    def _mock_iyzico(req, timeout=15):
        seq["n"] += 1
        return_price = getattr(_mock_iyzico, "next_paid_price", 828.0)
        plan_slug = getattr(_mock_iyzico, "next_plan", "pro")
        class _R:
            def read(self):
                return json.dumps({"status": "success", "paymentStatus": "SUCCESS", "paymentId": f"iyz_p{seq['n']}", "basketId": f"B-polyctl-{plan_slug}-{seq['n']}", "paidPrice": return_price, "currency": "TRY"}).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        return _R()

    monkeypatch.setattr(urllib.request, "urlopen", _mock_iyzico)
    _mock_iyzico.next_paid_price = 828.0
    _mock_iyzico.next_plan = "pro"
    B.subscribe_plan(root, "pro", currency="TRY", provider_name="iyzico", customer="Acme", tax_id="1234567890", payment_token="tok_pro")

    B.record_usage(root, "review", model="claude-sonnet-4-5", prompt_tokens=10000, completion_tokens=2000, units=300)
    B.record_usage(root, "security_scan", model="deterministic", units=250)
    summary = B.usage_summary(root)
    assert summary["used_units"] == 550 and summary["included_units"] == 500
    assert summary["unbilled_overage_units"] == 50

    # Local simulation at 550 units does NOT consume unbilled_overage_units or overwrite paid subscription
    B.subscribe_plan(root, "pro", currency="TRY", provider_name="local")
    _mock_iyzico.next_paid_price = round((690.0 + 37.50) * 1.20, 2)
    res_pro_1 = B.subscribe_plan(root, "pro", currency="TRY", provider_name="iyzico", customer="Acme", tax_id="1234567890", payment_token="tok_pro_over1")
    assert res_pro_1["ok"] is True
    assert res_pro_1["invoice"]["overage_units"] == 50
    assert res_pro_1["invoice"]["settled_used_units"] == 550

    # Re-subscribing to THE SAME Pro plan at 550 units does not double-bill the 50 units
    assert B.usage_summary(root)["unbilled_overage_units"] == 0
    _mock_iyzico.next_paid_price = 828.0
    res_pro_2 = B.subscribe_plan(root, "pro", currency="TRY", provider_name="iyzico", customer="Acme", tax_id="1234567890", payment_token="tok_pro_over2")
    assert res_pro_2["ok"] is True
    assert res_pro_2["invoice"]["overage_units"] == 0

    # Adding 30 more units on Pro (total 580) bills only the 30 new units on upgrade to Team (quota 6,000)
    B.record_usage(root, "verify", units=30)
    assert B.usage_summary(root)["unbilled_overage_units"] == 30
    _mock_iyzico.next_paid_price = round((4470.0 + 30 * 0.75) * 1.20, 2)
    _mock_iyzico.next_plan = "team"
    upgrade = B.subscribe_plan(root, "team", seats=3, currency="TRY", provider_name="iyzico", customer="Acme", tax_id="1234567890", payment_token="tok_team")
    assert upgrade["ok"] is True
    assert upgrade["invoice"]["overage_units"] == 30
    assert upgrade["invoice"]["overage_amount"] == 22.50

    # Reaching 6,050 units on Team (quota 6,000) has 50 unbilled Team overage units
    B.record_usage(root, "agent_run", units=5470)
    team_sum = B.usage_summary(root)
    assert team_sum["used_units"] == 6050 and team_sum["included_units"] == 6000
    assert team_sum["unbilled_overage_units"] == 50

    # Forging subscription.json without valid HMAC signing key fails closed back to 50-unit Community quota
    sub_path = Path(root) / ".polyctl" / "billing" / "subscription.json"
    forged = json.loads(sub_path.read_text(encoding="utf-8"))
    forged["included_units"] = 999999
    sub_path.write_text(json.dumps(forged), encoding="utf-8")
    forged_sum = B.usage_summary(root)
    assert forged_sum["included_units"] == 50 and forged_sum["quota_exceeded"] is True

    # Stripping integrity_sha256 from a row in usage.jsonl raises LedgerCorruption
    usage_file = Path(B.usage_log_path(root))
    lines = usage_file.read_text(encoding="utf-8").splitlines()
    first_row = json.loads(lines[0])
    first_row.pop("integrity_sha256", None)
    usage_file.write_text(json.dumps(first_row) + "\n", encoding="utf-8")
    with pytest.raises(storage.LedgerCorruption):
        B.read_usage_events(root)

    # Deleting `.polyctl/billing/usage.jsonl` raises `storage.LedgerCorruption` via checkpoint min_usage_ordinal
    usage_file.unlink()
    with pytest.raises(storage.LedgerCorruption):
        B.usage_summary(root)


def test_pre_commit_security_scanner_detects_secrets_pii_and_fails_closed(project, capsys):
    root = Path(project["root"])
    leaked_file = root / "config_leak.py"
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
    assert report["counts"]["BLOCKER"] == 3 and report["counts"]["HIGH"] == 1
    assert [f["rule_id"] for f in report["findings"]] == ["SEC-001", "SEC-003", "SEC-004", "SEC-008"]

    serialized = json.dumps(report)
    assert fake_anth not in serialized and fake_tckn not in serialized
    assert [f for f in report["findings"] if f["rule_id"] == "SEC-008"][0]["masked_match"] == "***REDACTED***"

    assert cli.main(["-C", str(root), "security-scan", "--paths", "config_leak.py"]) == 1
    assert "SECURITY SCAN BLOCKED" in capsys.readouterr().out
    assert cli.main(["-C", str(root), "security-scan", "--paths", "does_not_exist.py"]) == 1
    capsys.readouterr()

    (root / "clean.py").write_text("x = 42\n", encoding="utf-8")
    assert cli.main(["-C", str(root), "security-scan", "--paths", "clean.py"]) == 0
    assert "SECURITY SCAN PASS" in capsys.readouterr().out


def test_cli_billing_subcommands_end_to_end(project, capsys, monkeypatch):
    root = str(project["root"])
    (Path(root) / "clean.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.delenv("IYZICO_API_KEY", raising=False)
    monkeypatch.delenv("IYZICO_SECRET_KEY", raising=False)

    assert cli.main(["-C", root, "billing", "plans", "--currency", "TRY", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)["plans"]) == 4

    assert cli.main(["-C", root, "billing", "subscribe", "--plan", "pro", "--provider", "iyzico"]) == 1
    assert "BILLING ERROR" in capsys.readouterr().out

    # Non-finite cost-usd (inf / nan) is rejected cleanly with exit code 1
    assert cli.main(["-C", root, "billing", "meter", "review", "--cost-usd", "inf"]) == 1
    assert "BILLING ERROR" in capsys.readouterr().out

    assert cli.main(["-C", root, "billing", "subscribe", "--plan", "team", "--seats", "4", "--currency", "TRY", "--provider", "local", "--customer", "Polyctl Labs", "--tax-id", "9876543210", "--json"]) == 0
    sub_out = json.loads(capsys.readouterr().out)
    assert sub_out["ok"] is True and sub_out["invoice"]["invoice_id"].startswith("SIM-")

    # Automatic metering on security-scan when .polyctl/billing/ is active (default soft-cap does NOT block)
    assert cli.main(["-C", root, "security-scan", "--paths", "clean.py"]) == 0
    capsys.readouterr()
    assert B.usage_summary(root)["used_units"] == 1

    assert cli.main(["-C", root, "billing", "meter", "review", "--model", "claude-opus-4-7", "--units", "60", "--json"]) == 0
    meter_out = json.loads(capsys.readouterr().out)
    assert meter_out["usage"]["quota_exceeded"] is True and meter_out["usage"]["exceeded"] is True and meter_out["usage"]["blocked"] is False

    # Under default soft-cap, security-scan still runs past 50 units and prints BILLING WARNING
    assert cli.main(["-C", root, "security-scan", "--paths", "clean.py"]) == 0
    assert "BILLING WARNING" in capsys.readouterr().out

    # Enabling --hard-cap blocks budget --check and gates security-scan
    assert cli.main(["-C", root, "billing", "budget", "--hard-cap", "--check"]) == 1
    assert "BUDGET BLOCKED" in capsys.readouterr().out
    assert cli.main(["-C", root, "security-scan", "--paths", "clean.py"]) == 1
    assert "BILLING GATE BLOCKED" in capsys.readouterr().out

    # Tampering with budget.json on disk to set hard_cap=False does not bypass the checkpointed hard_cap
    (Path(root) / ".polyctl" / "billing" / "budget.json").write_text('{"hard_cap": false}\n', encoding="utf-8")
    assert cli.main(["-C", root, "security-scan", "--paths", "clean.py"]) == 1
    assert "BILLING GATE BLOCKED" in capsys.readouterr().out

    # Even if .polyctl/billing is deleted from the working tree, checkpoint store keeps the gate fail-closed
    shutil.rmtree(Path(root) / ".polyctl" / "billing")
    assert cli.main(["-C", root, "security-scan", "--paths", "clean.py"]) == 1
    assert "BILLING GATE BLOCKED" in capsys.readouterr().out


def test_web_billing_page_and_api_endpoint(project):
    root = project["root"]
    B.subscribe_plan(root, "pro", currency="TRY", provider_name="local")
    B.record_usage(root, "review", units=10)
    B.set_budget(root, cap_try=5000.0, hard_cap=True)

    args = SimpleNamespace(messages=8, interval=15, port=0, all=False, web=True)
    server = web.listen(cli._web_pages(root, args), "proj", 15, 0, api=cli._web_api(root, args))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        conn.request("GET", "/billing")
        resp = conn.getresponse()
        html_body = resp.read().decode("utf-8")
        assert resp.status == 200
        assert "data-view=\"billing\"" in html_body
        assert "data-section=\"security\"" in html_body
        assert "Pro (Individual Professional)" in html_body
        assert "SIMULATED" in html_body
        assert "HEALTHY" in html_body
        assert "<script" not in html_body.lower()

        conn.request("GET", "/api/billing")
        api_resp = conn.getresponse()
        api_data = json.loads(api_resp.read().decode("utf-8"))
        assert api_resp.status == 200
        assert api_data["schema_version"] == 1
        assert api_data["subscription"]["plan_id"] == "pro"
        assert api_data["usage"]["used_units"] == 10
        assert api_data["security"]["verdict"] == "PASS"
        assert len(api_data["invoices"]) == 1
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
