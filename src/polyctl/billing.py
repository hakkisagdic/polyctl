"""Commercial billing, usage metering, FinOps spend caps and invoice storage (P0-1, P0-2)."""
import base64, hashlib, hmac, json, math, os, re, time, urllib.error, urllib.request, uuid
from datetime import datetime, timezone
from . import security as SEC, storage

UTF8, VAT_RATE_TRY, USD_TO_TRY_DEFAULT = "utf-8", 0.20, 36.0
PLANS = {"community": {"id": "community", "name": "Community (Open-Source Core)", "monthly_try": 0.0, "monthly_usd": 0.0, "yearly_try": 0.0, "yearly_usd": 0.0, "per_seat": False, "min_seats": 1, "included_units": 50, "overage_try": 0.0, "overage_usd": 0.0, "features": ["worktree orchestration", "cross-family review gate", "SHA-256 ledger", "50 units/mo"]},
         "pro": {"id": "pro", "name": "Pro (Individual Professional)", "monthly_try": 690.0, "monthly_usd": 19.0, "yearly_try": 6900.0, "yearly_usd": 190.0, "per_seat": False, "min_seats": 1, "included_units": 500, "overage_try": 0.75, "overage_usd": 0.02, "features": ["web FinOps dashboard", "secret & PII scanner", "personal spend cap", "500 units/mo"]},
         "team": {"id": "team", "name": "Team (Engineering Governance)", "monthly_try": 1490.0, "monthly_usd": 39.0, "yearly_try": 14900.0, "yearly_usd": 390.0, "per_seat": True, "min_seats": 3, "included_units": 2000, "overage_try": 0.50, "overage_usd": 0.015, "features": ["team policy & RBAC", "fleet spend caps", "CI/CD SARIF & webhooks", "2,000 units/seat/mo"]},
         "enterprise": {"id": "enterprise", "name": "Enterprise (Regulated & On-Premise)", "monthly_try": 3490.0, "monthly_usd": 89.0, "yearly_try": 34900.0, "yearly_usd": 890.0, "per_seat": True, "min_seats": 10, "included_units": 10000, "overage_try": 0.35, "overage_usd": 0.01, "features": ["SOC 2 / ISO 42001 / KVKK export", "air-gapped / private UHP", "SAML/SSO & 99.9% SLA", "10,000 units/seat/mo"]}}
CURRENCIES, CYCLES, PROVIDERS = ("TRY", "USD"), ("monthly", "yearly"), ("iyzico", "local")
USAGE_KINDS, USAGE_CHAIN = ("review", "verify", "security_scan", "agent_run"), "polyctl-billing-usage-v1"
SUBSCRIPTION_REL = ".polyctl/billing/subscription.json"; BUDGET_REL = ".polyctl/billing/budget.json"; USAGE_REL = ".polyctl/billing/usage.jsonl"
_DOC_NAME_RE = re.compile(r"^(INV|SIM|SBX)-(\d{8})-(\d+)\.json$")
def _utc_iso(ts=None): return datetime.fromtimestamp(time.time() if ts is None else float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def _utc_month(ts=None): return datetime.fromtimestamp(time.time() if ts is None else float(ts), tz=timezone.utc).strftime("%Y-%m")
def _billing_lock_path(root): return os.path.join(root, ".polyctl", "billing", "billing.lock")
def invoice_path(root, invoice_id): return os.path.join(root, ".polyctl", "billing", "invoices", f"{invoice_id}.json")
def usage_log_path(root): return os.path.join(root, ".polyctl", "billing", "usage.jsonl")
def _ckpt_get(root): return storage._checkpoint_entry(usage_log_path(root))
def _ckpt_set(root, *, min_ord=0, refs=(), budget=None):
    def _upd(prev):
        out = {**prev, "billing_active": True, "min_usage_ordinal": max(int(prev.get("min_usage_ordinal", 0) or 0), int(min_ord or 0))}
        if refs: out["used_refs"] = sorted(set(prev.get("used_refs") or ()) | {str(r).strip() for r in refs if r})
        if budget is not None: out["budget"] = budget
        return out
    storage._update_checkpoint(usage_log_path(root), _upd)
def _finite_nonneg(val, name="value"):
    if not math.isfinite(f := float(val)) or f < 0.0: raise ValueError(f"{name} must be a finite non-negative number")
    return f
def _expires_period(period_str, cycle):
    if cycle != "yearly" or not (isinstance(period_str, str) and len(period_str) == 7 and period_str[4] == "-"): return str(period_str)
    tot = int(period_str[:4]) * 12 + (int(period_str[5:7]) - 1) + 11
    return f"{tot // 12:04d}-{(tot % 12) + 1:02d}"
def _canonical_sha256(payload):
    body = {k: v for k, v in payload.items() if k not in ("integrity_sha256", "integrity_verified", "checksum_matches")}
    raw, key = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(UTF8), (os.environ.get("POLYCTL_BILLING_SIGNING_KEY") or "").strip()
    return ("hmac-sha256:" + hmac.new(key.encode(UTF8), raw, hashlib.sha256).hexdigest()) if key else ("sha256:" + hashlib.sha256(raw).hexdigest())
def _is_sub_paid(sub, active_period=None):
    key_set, p_start, p_end = bool((os.environ.get("POLYCTL_BILLING_SIGNING_KEY") or "").strip()), str(sub.get("period") or ""), str(sub.get("expires_period") or "")
    p_ok = True if not active_period else bool(p_start and p_end and p_start <= str(active_period) <= p_end)
    return bool(p_ok and sub.get("plan_id") != "community" and sub.get("status") == "ACTIVE" and sub.get("provider") == "iyzico" and sub.get("provider_mode") == "live" and sub.get("checksum_matches") and (not key_set or sub.get("integrity_verified")))
class PaymentProvider:
    name = "abstract"
    def create_checkout(self, *, plan_id, seats, currency, cycle, subtotal, tax, total, customer, tax_id, line_items=None, payment_token=None): raise NotImplementedError
    def verify_payment(self, reference, *, expected_total=None, expected_currency=None, expected_plan_id=None): raise NotImplementedError
class LocalMockPaymentProvider(PaymentProvider):
    name = "local"
    def create_checkout(self, *, plan_id, seats, currency, cycle, subtotal, tax, total, customer, tax_id, line_items=None, payment_token=None):
        token = hashlib.sha256(f"{plan_id}:{seats}:{currency}:{cycle}:{total:.2f}:{customer}:{time.time_ns()}".encode(UTF8)).hexdigest()[:16]
        return {"ok": True, "provider": self.name, "mode": "local-simulated", "status": "SIMULATED", "payment_reference": f"loc_sim_{token}", "checkout_url": None, "currency": currency, "amount": round(float(total), 2), "verified": True}
    def verify_payment(self, reference, *, expected_total=None, expected_currency=None, expected_plan_id=None):
        ref = str(reference or "").strip()
        ok = bool(ref and ref.startswith("loc_sim_") and len(ref) == 24)
        return {"ok": ok, "verified": ok, "provider": self.name, "payment_reference": ref, "status": "SIMULATED" if ok else "UNKNOWN"}
class IyzicoPaymentProvider(PaymentProvider):
    name, DEFAULT_BASE_URL = "iyzico", "https://api.iyzipay.com"
    INITIALIZE_URI, RETRIEVE_URI = "/payment/iyzipos/checkoutform/initialize/auth/ecom", "/payment/iyzipos/checkoutform/auth/ecom/detail"
    def __init__(self, api_key=None, secret_key=None, base_url=None, callback_url=None):
        self.api_key = (api_key if api_key is not None else os.environ.get("IYZICO_API_KEY", "")).strip()
        self.secret_key = (secret_key if secret_key is not None else os.environ.get("IYZICO_SECRET_KEY", "")).strip()
        self.base_url = (base_url if base_url is not None else os.environ.get("IYZICO_BASE_URL", "")).strip() or self.DEFAULT_BASE_URL
        self.callback_url = (callback_url if callback_url is not None else os.environ.get("IYZICO_CALLBACK_URL", "")).strip() or "https://localhost/polyctl/billing/callback"
    @property
    def is_sandbox(self): return "sandbox" in self.base_url.lower()
    @staticmethod
    def build_iyzws_v2_header(api_key, secret_key, random_key, uri_path, body_json=""):
        sig = hmac.new(secret_key.encode(UTF8), f"{random_key}{uri_path}{body_json}".encode(UTF8), hashlib.sha256).hexdigest()
        return f"IYZWSv2 {base64.b64encode(f'apiKey:{api_key}&randomKey:{random_key}&signature:{sig}'.encode(UTF8)).decode('ascii')}", sig
    def _post_signed(self, uri, payload):
        rnd, body_json = str(int(time.time() * 1000)), json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        auth_header, sig = self.build_iyzws_v2_header(self.api_key, self.secret_key, rnd, uri, body_json)
        req = urllib.request.Request(self.base_url.rstrip("/") + uri, data=body_json.encode(UTF8), headers={"Authorization": auth_header, "x-iyzi-rnd": rnd, "Content-Type": "application/json", "Accept": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as resp: return json.loads(resp.read().decode(UTF8)), sig
    def _fail(self, mode, currency, total, error, ref=None, cid=None, sig=None, status="FAILED", checkout_url=None, checkout_token=None):
        out = {"ok": False, "provider": self.name, "mode": mode, "status": status, "payment_reference": ref, "checkout_url": checkout_url, "checkout_token": checkout_token, "currency": currency, "amount": round(float(total), 2), "verified": False, "error": error}
        return {**out, **({"conversation_id": cid} if cid else {}), **({"signature_prefix": sig[:16]} if sig else {})}
    def create_checkout(self, *, plan_id, seats, currency, cycle, subtotal, tax, total, customer, tax_id, line_items=None, payment_token=None):
        mode = "sandbox" if self.is_sandbox else "live"
        if not (self.api_key and self.secret_key): return self._fail("unconfigured", currency, total, "IYZICO_API_KEY and IYZICO_SECRET_KEY are required for --provider iyzico")
        customer_name, tax_number = str(customer or "").strip(), str(tax_id or "").strip()
        if not customer_name or not tax_number: return self._fail(mode, currency, total, "customer name (--customer) and tax/identity number (--tax-id) are required")
        if payment_token: return self.verify_payment(payment_token, expected_total=total, expected_currency=currency, expected_plan_id=plan_id)
        cid, parts = f"polyctl-{plan_id}-{uuid.uuid4().hex[:10]}", customer_name.split(None, 1)
        first_name, last_name = parts[0], (parts[1] if len(parts) > 1 else "Customer")
        addr = {"contactName": customer_name, "city": os.environ.get("IYZICO_BUYER_CITY", "Istanbul"), "country": os.environ.get("IYZICO_BUYER_COUNTRY", "Turkey"), "address": os.environ.get("IYZICO_BUYER_ADDRESS", "Istanbul, Turkey"), "zipCode": "34000"}
        items = [{"id": f"ITEM-{i + 1}", "name": it["description"], "category1": "SaaS", "itemType": "VIRTUAL", "price": f"{float(it['amount']):.2f}"} for i, it in enumerate(line_items or []) if float(it.get("amount", 0)) > 0] or [{"id": f"PLAN-{plan_id}", "name": f"polyctl {plan_id}", "category1": "SaaS", "itemType": "VIRTUAL", "price": f"{float(subtotal):.2f}"}]
        payload = {"locale": "tr" if currency == "TRY" else "en", "conversationId": cid, "price": f"{float(subtotal):.2f}", "paidPrice": f"{float(total):.2f}", "currency": currency, "basketId": f"B-{cid}", "paymentGroup": "SUBSCRIPTION", "callbackUrl": self.callback_url, "buyer": {"id": f"BY-{tax_number[-4:]}", "name": first_name, "surname": last_name, "identityNumber": tax_number, "email": os.environ.get("IYZICO_BUYER_EMAIL", "billing@example.com"), "gsmNumber": os.environ.get("IYZICO_BUYER_GSM", "+905000000000"), "registrationAddress": addr["address"], "city": addr["city"], "country": addr["country"], "ip": os.environ.get("IYZICO_BUYER_IP", "127.0.0.1")}, "billingAddress": addr, "shippingAddress": addr, "basketItems": items}
        try:
            data, sig = self._post_signed(self.INITIALIZE_URI, payload)
            tok, url = data.get("token"), (data.get("paymentPageUrl") or data.get("checkoutFormContent"))
            if data.get("status") != "success" or not tok: return self._fail(mode, currency, total, data.get("errorMessage") or "iyzico checkout initialize failed", cid=cid, sig=sig)
            return self._fail(mode, currency, total, "checkout initialized; complete payment in browser and re-run with --payment-token", cid=cid, sig=sig, status="PENDING_CHECKOUT", checkout_url=url, checkout_token=str(tok))
        except (urllib.error.URLError, ValueError, OSError) as exc: return self._fail(mode, currency, total, f"{type(exc).__name__}: {exc}", cid=cid)
    def verify_payment(self, reference, *, expected_total=None, expected_currency=None, expected_plan_id=None):
        mode, ref, curr, tot = ("sandbox" if self.is_sandbox else "live"), str(reference or "").strip(), str(expected_currency or "TRY").upper(), round(float(expected_total or 0.0), 2)
        if not ref or not (self.api_key and self.secret_key): return self._fail(mode, curr, tot, "payment token and iyzico credentials are required", ref=ref, status="UNVERIFIED")
        cid = f"polyctl-verify-{uuid.uuid4().hex[:10]}"
        try:
            data, sig = self._post_signed(self.RETRIEVE_URI, {"locale": "tr" if curr == "TRY" else "en", "conversationId": cid, "token": ref})
            p_status, p_id, basket_id = str(data.get("paymentStatus") or "").upper(), (data.get("paymentId") or data.get("hostReference")), str(data.get("basketId") or "")
            paid_price, paid_curr = round(float(data.get("paidPrice") or 0.0), 2), str(data.get("currency") or curr).upper()
            if not (data.get("status") == "success" and p_status == "SUCCESS" and p_id): return self._fail(mode, curr, tot, data.get("errorMessage") or f"iyzico payment not settled ({p_status or 'UNKNOWN'})", ref=ref, cid=cid, sig=sig)
            if expected_plan_id and not basket_id.startswith(f"B-polyctl-{expected_plan_id}-"): return self._fail(mode, curr, tot, f"iyzico basketId ({basket_id or 'missing'}) does not match plan ({expected_plan_id})", ref=str(p_id), cid=cid, sig=sig)
            if expected_total is not None and abs(paid_price - tot) >= 0.01: return self._fail(mode, curr, tot, f"iyzico paidPrice ({paid_price:.2f}) does not match invoice total ({tot:.2f})", ref=str(p_id), cid=cid, sig=sig)
            if expected_currency is not None and paid_curr != curr: return self._fail(mode, curr, tot, f"iyzico currency ({paid_curr}) does not match expected ({curr})", ref=str(p_id), cid=cid, sig=sig)
            return {"ok": True, "verified": True, "provider": self.name, "mode": mode, "status": "SANDBOX_PAID" if self.is_sandbox else "PAID", "payment_reference": str(p_id), "checkout_token": ref, "basket_id": basket_id or None, "conversation_id": cid, "signature_prefix": sig[:16], "currency": paid_curr, "amount": paid_price, "error": None}
        except (urllib.error.URLError, ValueError, OSError) as exc: return self._fail(mode, curr, tot, f"{type(exc).__name__}: {exc}", ref=ref, cid=cid)
def get_payment_provider(provider_name="iyzico"):
    if (name := str(provider_name or "iyzico").strip().lower()) in ("iyzico", "local"):
        return IyzicoPaymentProvider() if name == "iyzico" else LocalMockPaymentProvider()
    raise ValueError(f"unsupported payment provider {provider_name!r}; expected one of {', '.join(PROVIDERS)}")
def list_plans(currency="TRY"):
    if (curr := str(currency or "TRY").upper()) not in CURRENCIES: raise ValueError(f"currency must be one of {', '.join(CURRENCIES)}")
    return [{**PLANS[pid], "selected_currency": curr, "display_monthly": PLANS[pid]["monthly_try" if curr == "TRY" else "monthly_usd"], "display_yearly": PLANS[pid]["yearly_try" if curr == "TRY" else "yearly_usd"], "display_overage": PLANS[pid]["overage_try" if curr == "TRY" else "overage_usd"]} for pid in ("community", "pro", "team", "enterprise")]
def calculate_quote(plan_id, seats=1, currency="TRY", cycle="monthly", overage_units=0, overage_rate_override=None):
    plan_key, curr, cyc = str(plan_id or "").strip().lower(), str(currency or "TRY").upper(), str(cycle or "monthly").lower()
    if plan_key not in PLANS or curr not in CURRENCIES or cyc not in CYCLES: raise ValueError("invalid plan, currency or cycle")
    plan = PLANS[plan_key]
    eff_seats = 1 if not plan["per_seat"] else max(int(plan["min_seats"]), max(1, int(seats or 1)))
    unit_price, overage_count = plan[f"{cyc}_{curr.lower()}"], max(0, int(overage_units or 0))
    overage_rate = _finite_nonneg(overage_rate_override, "overage_rate") if overage_rate_override is not None else plan[f"overage_{curr.lower()}"]
    base_amount, overage_amount = round(unit_price * eff_seats, 2), round(overage_count * overage_rate, 2)
    subtotal = round(base_amount + overage_amount, 2)
    vat_rate = VAT_RATE_TRY if curr == "TRY" and subtotal > 0 else 0.0
    tax, inc = round(subtotal * vat_rate, 2), int(plan["included_units"]) * (eff_seats if plan["per_seat"] else 1)
    return {"plan_id": plan_key, "plan_name": plan["name"], "seats": eff_seats, "currency": curr, "cycle": cyc, "unit_price": unit_price, "base_amount": base_amount, "overage_units": overage_count, "overage_rate": overage_rate, "overage_amount": overage_amount, "subtotal": subtotal, "vat_rate": vat_rate, "tax": tax, "total": round(subtotal + tax, 2), "included_units": inc}
def load_subscription(root):
    try:
        raw = storage.read_in_tree(root, SUBSCRIPTION_REL)
        if isinstance(data := (json.loads(raw.decode(UTF8)) if raw else None), dict) and data.get("plan_id") in PLANS:
            stored = str(data.get("integrity_sha256") or "")
            matches = bool(stored and stored == _canonical_sha256(data))
            data["checksum_matches"], data["integrity_verified"] = matches, bool(matches and stored.startswith("hmac-sha256:"))
            return data
    except (OSError, ValueError): pass
    p = PLANS["community"]
    return {"plan_id": "community", "plan_name": p["name"], "status": "ACTIVE", "seats": 1, "currency": "TRY", "cycle": "monthly", "provider": "local", "provider_mode": "local", "period": None, "expires_period": None, "included_units": p["included_units"], "overage_try": 0.0, "overage_usd": 0.0, "customer": "Community User", "tax_id_masked": None, "started_at": None, "latest_invoice_id": None, "min_usage_ordinal": 0, "checksum_matches": True, "integrity_verified": False}
def list_invoices(root):
    inv_dir = os.path.join(root, ".polyctl", "billing", "invoices")
    if not os.path.isdir(inv_dir): return []
    out = []
    for name in sorted(os.listdir(inv_dir), reverse=True):
        if not (_DOC_NAME_RE.match(name)): continue
        try:
            raw = storage.read_in_tree(root, f".polyctl/billing/invoices/{name}")
            doc = json.loads(raw.decode(UTF8)) if raw else None
        except (OSError, ValueError): continue
        if isinstance(doc, dict):
            stored = str(doc.get("integrity_sha256") or "")
            matches = (stored == _canonical_sha256(doc))
            doc["checksum_matches"], doc["integrity_verified"] = matches, bool(matches and stored.startswith("hmac-sha256:"))
            out.append(doc)
    return out
def _next_invoice_id(root, now_ts=None, *, prefix="INV"):
    day, inv_dir, max_seq = datetime.fromtimestamp(time.time() if now_ts is None else float(now_ts), tz=timezone.utc).strftime("%Y%m%d"), os.path.join(root, ".polyctl", "billing", "invoices"), 0
    if os.path.isdir(inv_dir):
        for fname in os.listdir(inv_dir):
            if (m := _DOC_NAME_RE.match(fname)) and m.group(1) == prefix and m.group(2) == day: max_seq = max(max_seq, int(m.group(3)))
    seq = max_seq + 1
    while os.path.exists(invoice_path(root, f"{prefix}-{day}-{seq:04d}")): seq += 1
    return f"{prefix}-{day}-{seq:04d}"
def subscribe_plan(root, plan_id, *, seats=1, currency="TRY", cycle="monthly", provider_name="iyzico", customer="Polyctl Team", tax_id=None, payment_token=None, include_overage=True):
    with storage._exclusive_lock(_billing_lock_path(root)):
        prior_sub, prior_sum, curr = load_subscription(root), usage_summary(root), str(currency or "TRY").upper()
        prior_paid = _is_sub_paid(prior_sub, prior_sum["period"])
        prior_rate = float(prior_sub.get("overage_try" if curr == "TRY" else "overage_usd", 0.0) or 0.0) if prior_paid else 0.0
        unbilled = prior_sum["unbilled_overage_units"] if (include_overage and prior_paid) else 0
        quote = calculate_quote(plan_id, seats=seats, currency=curr, cycle=cycle, overage_units=unbilled, overage_rate_override=prior_rate if unbilled > 0 else None)
        used_refs = set(_ckpt_get(root).get("used_refs") or ()) | {str(inv.get(k)).strip() for inv in list_invoices(root) for k in ("checkout_token", "payment_reference") if inv.get(k)}
        if payment_token and str(payment_token).strip() in used_refs:
            return {"ok": False, "quote": quote, "checkout": {"ok": False, "provider": provider_name, "status": "REPLAYED", "error": f"payment token {payment_token!r} was already redeemed"}, "subscription": None, "invoice": None}
        plan = PLANS[quote["plan_id"]]
        items = [{"description": f"{plan['name']} ({quote['cycle']}, {quote['seats']} seat(s))", "quantity": quote["seats"], "unit_price": quote["unit_price"], "amount": quote["base_amount"], "currency": quote["currency"]}]
        if quote["overage_units"] > 0: items.append({"description": f"Metered overage from {prior_sub.get('plan_id', 'prior')} ({quote['overage_units']} units)", "quantity": quote["overage_units"], "unit_price": quote["overage_rate"], "amount": quote["overage_amount"], "currency": quote["currency"]})
        checkout = get_payment_provider(provider_name).create_checkout(plan_id=quote["plan_id"], seats=quote["seats"], currency=quote["currency"], cycle=quote["cycle"], subtotal=quote["subtotal"], tax=quote["tax"], total=quote["total"], customer=customer, tax_id=tax_id, line_items=items, payment_token=payment_token)
        if not checkout.get("ok"): return {"ok": False, "quote": quote, "checkout": checkout, "subscription": None, "invoice": None}
        if str(checkout.get("payment_reference") or "").strip() in used_refs:
            return {"ok": False, "quote": quote, "checkout": {**checkout, "ok": False, "status": "REPLAYED", "error": "payment reference was already redeemed"}, "subscription": None, "invoice": None}
        now, c_status, cur_ord = int(time.time()), str(checkout.get("status") or ""), prior_sum["total_events_all_time"]
        prefix = "SIM" if c_status == "SIMULATED" else ("SBX" if c_status == "SANDBOX_PAID" else "INV")
        kind, raw_tax = ("simulation" if prefix == "SIM" else ("sandbox_invoice" if prefix == "SBX" else "invoice")), (str(tax_id).strip() if tax_id else "")
        masked_tax = None if not raw_tax else ("****" if len(raw_tax) <= 4 else ("*" * (len(raw_tax) - 4)) + raw_tax[-4:])
        inv_id, settled_units = _next_invoice_id(root, now, prefix=prefix), (prior_sum["used_units"] if (kind == "invoice" and quote["overage_units"] > 0) else 0)
        invoice = {"invoice_id": inv_id, "kind": kind, "period": prior_sum["period"], "issued_at": _utc_iso(now), "timestamp": now, "status": c_status, "provider": checkout["provider"], "provider_mode": checkout.get("mode"), "payment_reference": checkout.get("payment_reference"), "checkout_token": checkout.get("checkout_token"), "customer": {"name": customer or "Polyctl Customer", "tax_id_masked": masked_tax}, "plan_id": quote["plan_id"], "plan_name": quote["plan_name"], "cycle": quote["cycle"], "seats": quote["seats"], "currency": quote["currency"], "overage_units": quote["overage_units"], "overage_amount": quote["overage_amount"], "settled_used_units": settled_units, "min_usage_ordinal": cur_ord, "line_items": items, "subtotal": quote["subtotal"], "vat_rate": quote["vat_rate"], "tax": quote["tax"], "total": quote["total"]}
        invoice["integrity_sha256"] = _canonical_sha256(invoice)
        storage.replace_in_tree(root, f".polyctl/billing/invoices/{inv_id}.json", (json.dumps(invoice, ensure_ascii=False, indent=2) + "\n").encode(UTF8))
        sub_status = "SIMULATED" if prefix == "SIM" else ("SANDBOX_ACTIVE" if prefix == "SBX" else "ACTIVE")
        sub = {"plan_id": quote["plan_id"], "plan_name": quote["plan_name"], "status": sub_status, "seats": quote["seats"], "currency": quote["currency"], "cycle": quote["cycle"], "period": prior_sum["period"], "expires_period": _expires_period(prior_sum["period"], quote["cycle"]), "provider": checkout["provider"], "provider_mode": checkout.get("mode"), "payment_reference": checkout.get("payment_reference"), "included_units": quote["included_units"], "overage_try": plan["overage_try"], "overage_usd": plan["overage_usd"], "customer": customer or "Polyctl Customer", "tax_id_masked": masked_tax, "started_at": _utc_iso(now), "latest_invoice_id": inv_id, "min_usage_ordinal": cur_ord}
        sub["integrity_sha256"] = _canonical_sha256(sub)
        if not (prefix != "INV" and prior_paid): storage.replace_in_tree(root, SUBSCRIPTION_REL, (json.dumps(sub, ensure_ascii=False, indent=2) + "\n").encode(UTF8))
        _ckpt_set(root, min_ord=cur_ord, refs=(checkout.get("checkout_token"), checkout.get("payment_reference")))
        return {"ok": True, "quote": quote, "checkout": checkout, "subscription": sub, "invoice": invoice}
def load_budget(root):
    ckpt_b = _ckpt_get(root).get("budget")
    try:
        raw = storage.read_in_tree(root, BUDGET_REL)
        disk_b = json.loads(raw.decode(UTF8)) if raw else None
        if isinstance(disk_b, dict):
            sig = str(disk_b.get("integrity_sha256") or "")
            if not sig or sig != _canonical_sha256(disk_b): disk_b = None
    except (OSError, ValueError, TypeError): disk_b = None
    data = ckpt_b if isinstance(ckpt_b, dict) and (disk_b is None or (ckpt_b.get("hard_cap") and not disk_b.get("hard_cap"))) else (disk_b or ckpt_b)
    if isinstance(data, dict):
        try: return {"cap_try": _finite_nonneg(data["cap_try"], "cap_try") if data.get("cap_try") is not None else None, "cap_usd": _finite_nonneg(data["cap_usd"], "cap_usd") if data.get("cap_usd") is not None else None, "hard_cap": bool(data.get("hard_cap", False)), "alert_percent": _finite_nonneg(data.get("alert_percent", 80.0), "alert_percent"), "min_usage_ordinal": int(data.get("min_usage_ordinal", 0) or 0), "updated_at": data.get("updated_at"), "integrity_sha256": data.get("integrity_sha256")}
        except (ValueError, TypeError): pass
    return {"cap_try": None, "cap_usd": None, "hard_cap": False, "alert_percent": 80.0, "min_usage_ordinal": 0, "updated_at": None, "integrity_sha256": None}
def set_budget(root, *, cap_try=None, cap_usd=None, hard_cap=None, alert_percent=None):
    with storage._exclusive_lock(_billing_lock_path(root)):
        cur = load_budget(root)
        if cap_try is not None: cur["cap_try"] = round(_finite_nonneg(cap_try, "cap_try"), 2)
        if cap_usd is not None: cur["cap_usd"] = round(_finite_nonneg(cap_usd, "cap_usd"), 2)
        if hard_cap is not None: cur["hard_cap"] = bool(hard_cap)
        if alert_percent is not None: cur["alert_percent"] = max(1.0, min(100.0, _finite_nonneg(alert_percent, "alert_percent")))
        cur["min_usage_ordinal"], cur["updated_at"] = len(read_usage_events(root)), _utc_iso()
        cur["integrity_sha256"] = _canonical_sha256(cur)
        storage.replace_in_tree(root, BUDGET_REL, (json.dumps(cur, ensure_ascii=False, indent=2) + "\n").encode(UTF8))
        _ckpt_set(root, min_ord=cur["min_usage_ordinal"], budget=cur)
        return cur
def read_usage_events(root):
    try: raw = storage.read_in_tree(root, USAGE_REL)
    except OSError as exc: raise storage.LedgerCorruption(f"cannot read {USAGE_REL}: {exc}") from exc
    if not raw: return []
    out, expected_prev, ordinal, key_set = [], None, 0, bool((os.environ.get("POLYCTL_BILLING_SIGNING_KEY") or "").strip())
    for line_no, line in enumerate(raw.decode(UTF8, errors="replace").splitlines(), 1):
        if not (line := line.strip()): continue
        ordinal += 1
        try:
            row = json.loads(line)
            if not isinstance(row, dict) or row.get("ordinal") != ordinal or row.get("previous") != expected_prev: raise storage.LedgerCorruption(f"corrupt usage chain in {USAGE_REL}:{line_no}")
            stored_sig = str(row.get("integrity_sha256") or "")
            if not stored_sig or stored_sig != _canonical_sha256(row) or (key_set and not stored_sig.startswith("hmac-sha256:")): raise storage.LedgerCorruption(f"corrupt row signature in {USAGE_REL}:{line_no}")
            expected_prev = storage.chained_row_digest(row, USAGE_CHAIN)
        except ValueError as exc: raise storage.LedgerCorruption(f"malformed JSON in {USAGE_REL}:{line_no}") from exc
        out.append(row)
    return out
def record_usage(root, kind, *, model=None, actor=None, prompt_tokens=0, completion_tokens=0, cost_usd=None, cost_try=None, units=1, now_ts=None):
    if (kind_str := str(kind or "review").strip().lower()) not in USAGE_KINDS: raise ValueError(f"unsupported usage kind {kind!r}")
    p_tok, c_tok = max(0, int(prompt_tokens or 0)), max(0, int(completion_tokens or 0))
    if cost_usd is None and cost_try is None:
        est_usd = round(max((p_tok * 0.000003) + (c_tok * 0.000015), 0.015 if kind_str == "review" else 0.002), 6)
        est_try = round(est_usd * USD_TO_TRY_DEFAULT, 4)
    elif cost_usd is not None and cost_try is None:
        est_usd = round(_finite_nonneg(cost_usd, "cost_usd"), 6); est_try = round(est_usd * USD_TO_TRY_DEFAULT, 4)
    elif cost_try is not None and cost_usd is None:
        est_try = round(_finite_nonneg(cost_try, "cost_try"), 4); est_usd = round(est_try / USD_TO_TRY_DEFAULT, 6)
    else:
        est_usd, est_try = round(_finite_nonneg(cost_usd, "cost_usd"), 6), round(_finite_nonneg(cost_try, "cost_try"), 4)
    with storage._exclusive_lock(_billing_lock_path(root)):
        existing = read_usage_events(root)
        prev, now = (storage.chained_row_digest(existing[-1], USAGE_CHAIN) if existing else None), int(time.time() if now_ts is None else float(now_ts))
        row = {"previous": prev, "ordinal": len(existing) + 1, "event_id": f"U-{now}-{uuid.uuid4().hex[:8]}", "at": now, "ts": _utc_iso(now), "period": _utc_month(now), "kind": kind_str, "model": str(model or "unknown"), "actor": str(actor or "polyctl"), "prompt_tokens": p_tok, "completion_tokens": c_tok, "total_tokens": p_tok + c_tok, "cost_usd": est_usd, "cost_try": est_try, "units": max(1, int(units or 1))}
        row["integrity_sha256"] = _canonical_sha256(row)
        raw_prev = storage.read_in_tree(root, USAGE_REL) or b""
        if raw_prev and not raw_prev.endswith(b"\n"): raw_prev += b"\n"
        storage.replace_in_tree(root, USAGE_REL, raw_prev + (json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode(UTF8))
        _ckpt_set(root, min_ord=row["ordinal"])
        return row
def usage_summary(root, period=None):
    active_period, sub, budget, all_events, all_invs, ckpt = str(period or _utc_month()), load_subscription(root), load_budget(root), read_usage_events(root), list_invoices(root), _ckpt_get(root)
    min_ord = max([int(ckpt.get("min_usage_ordinal", 0) or 0), int(sub.get("min_usage_ordinal", 0) or 0), int(budget.get("min_usage_ordinal", 0) or 0)] + [int(inv.get("min_usage_ordinal", 0) or 0) for inv in all_invs])
    if len(all_events) < min_ord: raise storage.LedgerCorruption(f"{USAGE_REL} was truncated or deleted (found {len(all_events)} events, expected >= {min_ord})")
    events = [e for e in all_events if (e.get("period") if isinstance(e.get("period"), str) and len(e["period"]) == 7 else (str(e.get("ts") or "")[:7] if len(str(e.get("ts") or "")) >= 7 else _utc_month(e.get("at")))) == active_period]
    used_units, is_paid = sum(int(e.get("units", 1) or 1) for e in events), _is_sub_paid(sub, active_period)
    plan_units = int(sub.get("included_units", PLANS["community"]["included_units"]) or 0)
    included = plan_units if is_paid else int(PLANS["community"]["included_units"])
    paid_invs = [inv for inv in all_invs if inv.get("kind") == "invoice" and inv.get("status") == "PAID" and (inv.get("period") or str(inv.get("issued_at") or "")[:7]) == active_period]
    billed_overage, settled_units = sum(int(inv.get("overage_units", 0) or 0) for inv in paid_invs), max([0] + [int(inv.get("settled_used_units", 0) or 0) for inv in paid_invs])
    overage_units, unbilled_overage = max(0, used_units - included), max(0, used_units - max(included, settled_units))
    overage_try = round(unbilled_overage * float(sub.get("overage_try", 0.0) or 0.0), 2) if is_paid else 0.0
    overage_usd = round(unbilled_overage * float(sub.get("overage_usd", 0.0) or 0.0), 4) if is_paid else 0.0
    api_try, api_usd = round(sum(float(e.get("cost_try", 0.0) or 0.0) for e in events), 2), round(sum(float(e.get("cost_usd", 0.0) or 0.0) for e in events), 4)
    tot_try, tot_usd = round(api_try + overage_try, 2), round(api_usd + overage_usd, 4)
    by_kind = {k: {"events": len(m), "units": sum(int(e.get("units", 1) or 1) for e in m), "tokens": sum(int(e.get("total_tokens", 0) or 0) for e in m), "cost_try": round(sum(float(e.get("cost_try", 0.0) or 0.0) for e in m), 2), "cost_usd": round(sum(float(e.get("cost_usd", 0.0) or 0.0) for e in m), 4)} for k in USAGE_KINDS if (m := [e for e in events if e.get("kind") == k])}
    cap_try, cap_usd = budget.get("cap_try"), budget.get("cap_usd")
    try_exc, usd_exc, quota_exc = bool(cap_try is not None and tot_try > cap_try), bool(cap_usd is not None and tot_usd > cap_usd), bool(not is_paid and used_units > included)
    exceeded, blocked = (try_exc or usd_exc or quota_exc), bool((try_exc or usd_exc or quota_exc) and budget.get("hard_cap"))
    reasons = ([f"TRY spend ({tot_try:.2f} TL) exceeded cap ({cap_try:.2f} TL)"] if try_exc else []) + ([f"USD spend (${tot_usd:.2f}) exceeded cap (${cap_usd:.2f})"] if usd_exc else []) + ([f"Quota exceeded ({used_units}/{included} units); complete paid checkout"] if quota_exc else [])
    return {"period": active_period, "events_count": len(events), "total_events_all_time": len(all_events), "used_units": used_units, "included_units": included, "plan_units": plan_units, "enforced_quota_units": included, "remaining_units": max(0, included - used_units), "quota_percent": round(100.0 * used_units / included, 1) if included > 0 else 0.0, "overage_units": overage_units, "billed_overage_units": billed_overage, "unbilled_overage_units": unbilled_overage, "overage_try": overage_try, "overage_usd": overage_usd, "api_cost_try": api_try, "api_cost_usd": api_usd, "total_spend_try": tot_try, "total_spend_usd": tot_usd, "total_tokens": sum(int(e.get("total_tokens", 0) or 0) for e in events), "by_kind": by_kind, "budget": budget, "exceeded": exceeded, "blocked": blocked, "quota_exceeded": quota_exc, "reasons": reasons}
def check_budget_gate(root, period=None):
    summary = usage_summary(root, period=period)
    return (not summary["blocked"]), summary
def maybe_meter_cmd(root, args, run_fn):
    cmd = getattr(args, "cmd", None)
    if cmd not in ("review", "verify", "security-scan") or getattr(args, "run", None) or getattr(args, "action", None) in ("collect", "cancel"): return run_fn()
    if not (os.path.isdir(os.path.join(root, ".polyctl", "billing")) or _ckpt_get(root).get("billing_active")): return run_fn()
    try: allowed, summary = check_budget_gate(root)
    except (storage.LedgerCorruption, ValueError) as exc: print(f"BILLING GATE BLOCKED ({cmd}): {exc}"); return 1
    if not allowed: print(f"BILLING GATE BLOCKED ({cmd}): {'; '.join(summary['reasons'])}"); return 1
    if summary.get("exceeded"): print(f"BILLING WARNING ({cmd}): {'; '.join(summary['reasons'])}")
    rc = run_fn()
    try:
        c_usd = os.environ.get("POLYCTL_METER_COST_USD")
        record_usage(root, "security_scan" if cmd == "security-scan" else cmd, model=getattr(args, "model", None) or getattr(args, "reviewer", None) or os.environ.get("POLYCTL_METER_MODEL"), actor=cmd, prompt_tokens=int(os.environ.get("POLYCTL_METER_PROMPT_TOKENS", 0) or 0), completion_tokens=int(os.environ.get("POLYCTL_METER_COMPLETION_TOKENS", 0) or 0), cost_usd=float(c_usd) if c_usd else None)
    except (ValueError, storage.LedgerCorruption): pass
    return rc
def billing_facts(root): return {"at": int(time.time()), "subscription": load_subscription(root), "usage": usage_summary(root), "security": SEC.scan_staged(root), "invoices": list_invoices(root), "plans": list_plans("TRY")}
def cmd_billing(cfg, args):
    root, action, currency, as_json = cfg["root"], getattr(args, "action", None) or "status", (getattr(args, "currency", None) or "TRY").upper(), getattr(args, "json", False)
    try:
        if action == "plans":
            plans = list_plans(currency)
            print(json.dumps({"currency": currency, "plans": plans}, ensure_ascii=False, indent=2) if as_json else "\n".join(f"  {p['id']:<12} {p['name']:<36} {p['display_monthly']:.2f} {currency}/mo ({p['included_units']} units)" for p in plans))
            return 0
        if action == "subscribe":
            res = subscribe_plan(root, getattr(args, "plan", None) or "pro", seats=getattr(args, "seats", 1) or 1, currency=currency, cycle=getattr(args, "cycle", None) or "monthly", provider_name=getattr(args, "provider", None) or "iyzico", customer=getattr(args, "customer", None) or cfg.get("project", "Polyctl Team"), tax_id=getattr(args, "tax_id", None), payment_token=getattr(args, "payment_token", None))
            print(json.dumps(res, ensure_ascii=False, indent=2) if as_json else (f"SUBSCRIBED  plan={res['subscription']['plan_id']}  invoice={res['invoice']['invoice_id']}  total={res['invoice']['total']:.2f} {currency}" if res.get("ok") else f"BILLING ERROR: {(res.get('checkout') or {}).get('error') or 'payment failed'}"))
            return 0 if res.get("ok") else 1
        if action == "meter":
            ev = record_usage(root, getattr(args, "kind", None) or "review", model=getattr(args, "model", None) or "unknown", actor=getattr(args, "actor", None) or "polyctl", prompt_tokens=getattr(args, "prompt_tokens", 0) or 0, completion_tokens=getattr(args, "completion_tokens", 0) or 0, cost_usd=getattr(args, "cost_usd", None), cost_try=getattr(args, "cost_try", None), units=getattr(args, "units", 1) or 1)
            summary = usage_summary(root)
            print(json.dumps({"event": ev, "usage": summary}, ensure_ascii=False, indent=2) if as_json else f"METERED  {ev['event_id']}  used={summary['used_units']}/{summary['included_units']}")
            return 0
        if action == "budget":
            if any(getattr(args, k, None) is not None for k in ("cap_try", "cap_usd", "hard_cap")):
                set_budget(root, cap_try=getattr(args, "cap_try", None), cap_usd=getattr(args, "cap_usd", None), hard_cap=getattr(args, "hard_cap", None))
            allowed, summary = check_budget_gate(root)
            print(json.dumps({"allowed": allowed, "usage": summary}, ensure_ascii=False, indent=2) if as_json else f"BUDGET {'OK' if allowed else 'BLOCKED'}  spend=₺{summary['total_spend_try']:.2f}")
            return 1 if (getattr(args, "check", False) and not allowed) else 0
        if action == "invoices":
            invs = [i for i in list_invoices(root) if not getattr(args, "invoice_id", None) or i.get("invoice_id") == getattr(args, "invoice_id", None)]
            print(json.dumps({"invoices": invs}, ensure_ascii=False, indent=2) if as_json else ("\n".join(f"  {i['invoice_id']}  {i['total']:.2f} {i['currency']}" for i in invs) or "No invoices."))
            return 0
        facts = billing_facts(root)
        print(json.dumps(facts, ensure_ascii=False, indent=2) if as_json else f"Subscription: {facts['subscription']['plan_name']} ({facts['subscription']['status']}) · used={facts['usage']['used_units']}/{facts['usage']['included_units']}")
        return 0
    except (storage.LedgerCorruption, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2) if as_json else f"BILLING ERROR: {exc}")
        return 1
