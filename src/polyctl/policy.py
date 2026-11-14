"""Team Role-Based Access Control (RBAC) and Policy-as-Code enforcement engine (P1-2)."""
import fnmatch, hashlib, hmac, json, os, sys, time
from datetime import datetime, timezone
from . import billing as BIL, lib as A, security as SEC, storage

UTF8, POLICY_REL = "utf-8", ".polyctl/policy/policy.json"
ROLES = ("owner", "admin", "architect", "reviewer", "implementer", "auditor")
ROLE_PERMISSIONS = {
    "owner": ("policy:write", "billing:write", "compliance:export", "commit:grant", "code:write", "review:submit", "security:scan", "audit:read"),
    "admin": ("policy:write", "billing:write", "compliance:export", "commit:grant", "code:write", "review:submit", "security:scan", "audit:read"),
    "architect": ("compliance:export", "commit:grant", "code:write", "review:submit", "security:scan", "audit:read"),
    "reviewer": ("review:submit", "security:scan", "audit:read"),
    "implementer": ("code:write", "security:scan"),
    "auditor": ("compliance:export", "security:scan", "audit:read"),
}
DEFAULT_RULES = {
    "require_security_scan": True,
    "require_cross_family_review": True,
    "require_budget_ok": True,
    "max_product_lines": 400,
    "forbidden_paths_for_implementer": [".github/workflows/*", ".polyctl/policy/*", ".polyctl/billing/subscription.json"],
}

def _utc_iso(ts=None):
    return datetime.fromtimestamp(time.time() if ts is None else float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _signing_key():
    return (os.environ.get("POLYCTL_POLICY_SIGNING_KEY") or "").strip()

def _policy_path(root):
    return os.path.join(root, ".polyctl", "policy", "policy.json")

def _lock_path(root):
    return os.path.join(root, ".polyctl", "policy", "policy.lock")

def _ckpt_get(root):
    return storage._checkpoint_entry(_policy_path(root))

def _ckpt_set(root, policy_digest, integrity_sha256, rules, bindings):
    store_real, root_real = os.path.realpath(storage.checkpoint_path()), os.path.realpath(root)
    if os.path.commonpath([root_real, store_real]) == root_real:
        raise storage.LedgerCorruption(f"checkpoint store {storage.checkpoint_path()} lies inside the project tree")
    storage._update_checkpoint(
        _policy_path(root),
        lambda prev: {**prev, "policy_active": True, "policy_digest": policy_digest, "integrity_sha256": integrity_sha256,
                      "rules": dict(rules or {}), "bindings": dict(bindings or {}), "updated_at": _utc_iso()},
    )

def _canonical_digests(payload, key=None):
    body = {k: v for k, v in payload.items() if k not in ("policy_digest", "integrity_sha256", "checksum_matches", "integrity_verified")}
    domain_raw = b"polyctl-policy-v1\0" + json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(UTF8)
    sha = "sha256:" + hashlib.sha256(domain_raw).hexdigest()
    k = _signing_key() if key is None else str(key).strip()
    sig = ("hmac-sha256:" + hmac.new(k.encode(UTF8), domain_raw, hashlib.sha256).hexdigest()) if k else sha
    return sha, sig, bool(k)

def _default_policy():
    return {
        "schema_version": 1,
        "updated_at": None,
        "bindings": {"admin": "owner", "architect": "architect", "reviewer": "reviewer", "implementer": "implementer", "auditor": "auditor"},
        "rules": dict(DEFAULT_RULES),
    }

def _validate_policy_shape(data):
    if not isinstance(data, dict):
        raise storage.LedgerCorruption("policy.json must be a JSON object")
    bindings = data.get("bindings")
    if not isinstance(bindings, dict) or not bindings:
        raise storage.LedgerCorruption("policy.json bindings must be a non-empty object")
    for actor, role in bindings.items():
        if not isinstance(actor, str) or not actor.strip() or role not in ROLES:
            raise storage.LedgerCorruption(f"invalid role binding {actor!r} -> {role!r}")
    rules = data.get("rules")
    if not isinstance(rules, dict):
        raise storage.LedgerCorruption("policy.json rules must be a JSON object")
    max_lines = rules.get("max_product_lines", 400)
    if not isinstance(max_lines, int) or isinstance(max_lines, bool) or max_lines < 1 or max_lines > 10000:
        raise storage.LedgerCorruption(f"invalid max_product_lines {max_lines!r} in policy.json")
    for bkey in ("require_security_scan", "require_cross_family_review", "require_budget_ok"):
        if bkey in rules and not isinstance(rules[bkey], bool):
            raise storage.LedgerCorruption(f"policy rule {bkey!r} must be a boolean")
    fpaths = rules.get("forbidden_paths_for_implementer", [])
    if not isinstance(fpaths, list) or not all(isinstance(p, str) and p.strip() for p in fpaths):
        raise storage.LedgerCorruption("forbidden_paths_for_implementer must be a list of non-empty strings")

def load_policy(root):
    raw = storage.read_in_tree(root, POLICY_REL)
    ckpt = _ckpt_get(root)
    if raw is None:
        if ckpt.get("policy_active"):
            raise storage.LedgerCorruption(f"{POLICY_REL} is missing but checkpoint records an active policy")
        pol = _default_policy()
        p_digest, sig, keyed = _canonical_digests(pol)
        pol.update(policy_digest=p_digest, integrity_sha256=sig, checksum_matches=True, integrity_verified=keyed)
        return pol
    try:
        data = json.loads(raw.decode(UTF8))
    except (ValueError, UnicodeDecodeError) as exc:
        raise storage.LedgerCorruption(f"malformed {POLICY_REL}: {exc}") from exc
    _validate_policy_shape(data)
    rec_digest, rec_sig = str(data.get("policy_digest") or ""), str(data.get("integrity_sha256") or "")
    exp_digest, exp_sig, keyed = _canonical_digests(data)
    digest_ok = bool(rec_digest and hmac.compare_digest(rec_digest, exp_digest))
    sig_ok = bool(rec_sig and hmac.compare_digest(rec_sig, exp_sig))
    if not digest_ok or (keyed and not (sig_ok and rec_sig.startswith("hmac-sha256:"))) or (not keyed and not sig_ok):
        raise storage.LedgerCorruption(f"{POLICY_REL} failed integrity verification (tampered policy file)")
    if ckpt.get("policy_active"):
        if ckpt.get("policy_digest") != rec_digest or ckpt.get("integrity_sha256") != rec_sig:
            raise storage.LedgerCorruption(f"{POLICY_REL} diverges from machine checkpoint store")
    data.update(checksum_matches=True, integrity_verified=bool(keyed and sig_ok and rec_sig.startswith("hmac-sha256:")))
    return data

def save_policy(root, policy_obj):
    with storage._exclusive_lock(_lock_path(root)):
        clean = {
            "schema_version": 1,
            "updated_at": _utc_iso(),
            "bindings": dict(policy_obj.get("bindings") or {}),
            "rules": {**DEFAULT_RULES, **dict(policy_obj.get("rules") or {})},
        }
        _validate_policy_shape(clean)
        p_digest, sig, keyed = _canonical_digests(clean)
        clean.update(policy_digest=p_digest, integrity_sha256=sig)
        raw = (json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(UTF8)
        prev_ckpt = _ckpt_get(root)
        _ckpt_set(root, p_digest, sig, clean["rules"], clean["bindings"])
        try:
            storage.replace_in_tree(root, POLICY_REL, raw)
        except BaseException:
            storage._update_checkpoint(_policy_path(root), lambda _: dict(prev_ckpt))
            raise
        clean.update(checksum_matches=True, integrity_verified=keyed)
        return clean

def bind_actor_role(root, actor, role):
    actor_s, role_s = str(actor or "").strip(), str(role or "").strip().lower()
    if not actor_s:
        raise ValueError("actor identifier cannot be empty")
    if role_s not in ROLES:
        raise ValueError(f"unsupported role {role!r}; choose from {', '.join(ROLES)}")
    pol = load_policy(root)
    pol["bindings"][actor_s] = role_s
    return save_policy(root, pol)

def update_policy_rules(root, *, max_product_lines=None, forbidden_paths=None, require_security_scan=None,
                        require_cross_family_review=None, require_budget_ok=None):
    pol = load_policy(root)
    rules = dict(pol.get("rules") or DEFAULT_RULES)
    if max_product_lines is not None:
        if isinstance(max_product_lines, bool) or int(max_product_lines) < 1 or int(max_product_lines) > 10000:
            raise ValueError("max_product_lines must be an integer between 1 and 10000")
        rules["max_product_lines"] = int(max_product_lines)
    if forbidden_paths is not None:
        cleaned = [str(p).strip() for p in forbidden_paths if str(p).strip()]
        rules["forbidden_paths_for_implementer"] = cleaned
    if require_security_scan is not None:
        rules["require_security_scan"] = bool(require_security_scan)
    if require_cross_family_review is not None:
        rules["require_cross_family_review"] = bool(require_cross_family_review)
    if require_budget_ok is not None:
        rules["require_budget_ok"] = bool(require_budget_ok)
    pol["rules"] = rules
    return save_policy(root, pol)

def resolve_actor_role(pol, actor):
    bindings = pol.get("bindings") or {}
    actor_s = str(actor or "").strip()
    if actor_s in bindings:
        return bindings[actor_s]
    low = actor_s.lower()
    for r in ROLES:
        if low == r or f"-{r}" in low or low.startswith(f"{r}-"):
            return r
    return "implementer"

def check_permission(root, actor, permission):
    pol = load_policy(root)
    role = resolve_actor_role(pol, actor)
    perms = ROLE_PERMISSIONS.get(role, ())
    allowed = permission in perms
    return {"ok": allowed, "actor": actor, "role": role, "permission": permission, "permissions": list(perms)}

def evaluate_policy(root, *, actor="implementer", permission=None):
    pol = load_policy(root)
    role = resolve_actor_role(pol, actor)
    perms = ROLE_PERMISSIONS.get(role, ())
    rules = pol.get("rules") or DEFAULT_RULES
    violations = []
    if permission and permission not in perms:
        violations.append({"rule": "rbac_permission", "severity": "BLOCKER",
                           "message": f"actor {actor!r} (role={role}) lacks required permission {permission!r}"})
    cand = A.index_candidate(root)
    changed_paths = cand.get("changed_paths") or []
    if role == "implementer":
        patterns = rules.get("forbidden_paths_for_implementer") or []
        for path in changed_paths:
            for pat in patterns:
                if fnmatch.fnmatch(path, pat) or path == pat:
                    violations.append({"rule": "forbidden_paths_for_implementer", "severity": "BLOCKER",
                                       "message": f"role 'implementer' is forbidden from modifying {path!r} (matches {pat!r})"})
                    break
    max_lines = int(rules.get("max_product_lines", 400))
    try:
        measured = A.candidate_size(root, cand)
        prod = (measured.get("kinds") or {}).get("product") or {}
        prod_lines = int(prod.get("added", 0)) + int(prod.get("deleted", 0))
    except Exception:
        prod_lines = 0
    if prod_lines > max_lines:
        violations.append({"rule": "max_product_lines", "severity": "HIGH",
                           "message": f"staged product diff ({prod_lines} lines) exceeds policy max_product_lines ({max_lines})"})
    if rules.get("require_security_scan", True):
        sec = SEC.scan_staged(root)
        if not sec.get("ok"):
            violations.append({"rule": "require_security_scan", "severity": "BLOCKER",
                               "message": f"staged diff failed security scan ({sec.get('total_findings', 0)} finding(s))"})
    if rules.get("require_budget_ok", True):
        budget_ok, reason = BIL.check_budget_gate(root)
        if not budget_ok:
            violations.append({"rule": "require_budget_ok", "severity": "BLOCKER", "message": reason or "budget gate exceeded"})
    if rules.get("require_cross_family_review", True):
        try:
            cfg = A.load_config(root)
            roles_cfg, actors_cfg = cfg.get("roles") or {}, cfg.get("actors") or {}
            imp_fam = (actors_cfg.get(roles_cfg.get("implementer") or "") or {}).get("family")
            rev_fam = (actors_cfg.get(roles_cfg.get("reviewer") or "") or {}).get("family")
            if imp_fam and rev_fam and imp_fam == rev_fam:
                violations.append({"rule": "require_cross_family_review", "severity": "HIGH",
                                   "message": f"implementer and reviewer share model family {imp_fam!r}"})
        except Exception as exc:
            violations.append({"rule": "require_cross_family_review", "severity": "HIGH", "message": str(exc)})
    ok = len(violations) == 0
    return {
        "ok": ok, "verdict": "ALLOW" if ok else "DENY", "actor": actor, "role": role,
        "permissions": list(perms), "checked_permission": permission, "changed_paths": changed_paths,
        "product_lines": prod_lines, "policy_digest": pol.get("policy_digest"), "violations": violations,
    }

def cmd_policy(cfg, args):
    root, action, as_json = cfg["root"], getattr(args, "action", "status") or "status", bool(getattr(args, "json", False))
    try:
        if action == "status":
            pol = load_policy(root)
            out = {**pol, "roles_matrix": {r: list(p) for r, p in ROLE_PERMISSIONS.items()}}
            if as_json:
                print(json.dumps(out, ensure_ascii=False, indent=2))
            else:
                print(f"POLICY ACTIVE · digest={pol['policy_digest'][:24]}... · hmac={'VERIFIED' if pol['integrity_verified'] else 'UNKEYED'}")
                print("  Bindings:", ", ".join(f"{k}={v}" for k, v in sorted(pol["bindings"].items())))
                r = pol["rules"]
                print(f"  Rules: max_product_lines={r['max_product_lines']} · sec_scan={r['require_security_scan']} · cross_family={r['require_cross_family_review']} · budget_gate={r['require_budget_ok']}")
            return 0
        if action == "init":
            pol = save_policy(root, load_policy(root))
            if as_json:
                print(json.dumps(pol, ensure_ascii=False, indent=2))
            else:
                print(f"POLICY INITIALIZED · path={POLICY_REL} · digest={pol['policy_digest'][:24]}...")
            return 0
        if action == "bind":
            pol = bind_actor_role(root, getattr(args, "actor", None), getattr(args, "role", None))
            if as_json:
                print(json.dumps(pol, ensure_ascii=False, indent=2))
            else:
                print(f"POLICY ROLE BOUND · {args.actor} -> {args.role}")
            return 0
        if action == "set-rules":
            pol = update_policy_rules(
                root, max_product_lines=getattr(args, "max_product_lines", None),
                forbidden_paths=getattr(args, "forbidden_paths", None),
                require_security_scan=getattr(args, "require_security_scan", None),
                require_cross_family_review=getattr(args, "require_cross_family_review", None),
                require_budget_ok=getattr(args, "require_budget_ok", None),
            )
            if as_json:
                print(json.dumps(pol, ensure_ascii=False, indent=2))
            else:
                print(f"POLICY RULES UPDATED · max_product_lines={pol['rules']['max_product_lines']}")
            return 0
        if action == "check":
            res = evaluate_policy(root, actor=getattr(args, "actor", None) or "implementer", permission=getattr(args, "permission", None))
            if as_json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            elif res["ok"]:
                print(f"POLICY ALLOW · actor={res['actor']} (role={res['role']}) · paths={len(res['changed_paths'])} · product_lines={res['product_lines']}")
            else:
                print(f"POLICY DENY · actor={res['actor']} (role={res['role']}) · {len(res['violations'])} violation(s):", file=sys.stderr)
                for v in res["violations"]:
                    print(f"  [{v['severity']}] {v['rule']}: {v['message']}", file=sys.stderr)
            return 0 if res["ok"] else 1
    except (ValueError, TypeError, KeyError, OSError, storage.LedgerCorruption) as exc:
        if as_json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"polyctl policy {action}: {exc}", file=sys.stderr)
        return 1
    return 0
