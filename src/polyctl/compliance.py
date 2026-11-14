"""Enterprise compliance & audit evidence bundle export and verification (SOC 2, ISO/IEC 42001, KVKK — P1-1)."""
import hashlib, hmac, json, os, re, stat, subprocess, sys, time, uuid
from datetime import datetime, timezone
from . import billing as BIL, lib as A, security as SEC, storage

UTF8, FRAMEWORKS = "utf-8", ("soc2", "iso42001", "kvkk", "all")
COMPLIANCE_BUNDLES_REL, COMPLIANCE_STATE_REL = ".polyctl/compliance/bundles", ".polyctl/compliance/state.json"
_BUNDLE_ID_RE = re.compile(r"^CMP-(\d{8})-([0-9a-f]{8,16})$")
_EXTRA_LEDGERS = (
    ("slices", ".polyctl/ledger/slices.jsonl", "polyctl-slice-row-v1", True),
    ("billing_usage", ".polyctl/billing/usage.jsonl", "polyctl-billing-usage-v1", False),
)

def _utc_iso(ts=None):
    return datetime.fromtimestamp(time.time() if ts is None else float(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _signing_key():
    return (os.environ.get("POLYCTL_COMPLIANCE_SIGNING_KEY") or "").strip()

def _state_path(root):
    return os.path.join(root, ".polyctl", "compliance", "state.json")

def _bundles_dir(root):
    return os.path.join(root, ".polyctl", "compliance", "bundles")

def _lock_path(root):
    return os.path.join(root, ".polyctl", "compliance", "compliance.lock")

def _ckpt_get(root):
    return storage._checkpoint_entry(_state_path(root))

def _ckpt_record_bundle(root, bundle_id, bundle_digest, integrity_sha256, ledger_heads):
    store_real, root_real = os.path.realpath(storage.checkpoint_path()), os.path.realpath(root)
    if os.path.commonpath([root_real, store_real]) == root_real:
        raise storage.LedgerCorruption(f"checkpoint store {storage.checkpoint_path()} lies inside the project tree")
    def _upd(prev):
        bundles = dict(prev.get("bundles") if isinstance(prev.get("bundles"), dict) else {})
        bundles[str(bundle_id)] = {"bundle_digest": bundle_digest, "integrity_sha256": integrity_sha256, "ledger_heads": dict(ledger_heads or {}), "recorded_at": _utc_iso()}
        return {**prev, "compliance_active": True, "latest_bundle_id": str(bundle_id), "latest_bundle_digest": bundle_digest, "bundles": bundles}
    storage._update_checkpoint(_state_path(root), _upd)

def _canonical_digests(payload, key=None):
    body = {k: v for k, v in payload.items() if k not in ("bundle_digest", "integrity_sha256", "checksum_matches", "integrity_verified", "exported_to")}
    domain_raw = b"polyctl-compliance-bundle-v1\0" + json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(UTF8)
    sha = "sha256:" + hashlib.sha256(domain_raw).hexdigest()
    k = _signing_key() if key is None else str(key).strip()
    sig = ("hmac-sha256:" + hmac.new(k.encode(UTF8), domain_raw, hashlib.sha256).hexdigest()) if k else sha
    return sha, sig, bool(k)

def _inspect_ledger(root, name, rel, chain, legacy_prefix, is_gate):
    path = os.path.join(root, *rel.split("/"))
    try:
        if name == "opt-ins":
            rows, (unattested, _) = storage.read_chained_in_tree(root, rel, chain), storage.unattested_in_tree(root, rel, chain)
        else:
            rows = storage.read_chained_history(path, chain, legacy_prefix=legacy_prefix)
            unattested, _ = storage.unattested_ledger(path, chain, legacy_prefix=legacy_prefix) if is_gate else (0, len(rows))
        head = storage.chained_row_digest(rows[-1], chain) if rows else None
        return {"name": name, "path": rel, "chain": chain, "chain_valid": True, "row_count": len(rows), "attested_rows": len(rows), "unattested_rows": int(unattested), "head_digest": head, "error": None}, rows
    except (storage.LedgerCorruption, storage.InTheWay, OSError, ValueError) as exc:
        return {"name": name, "path": rel, "chain": chain, "chain_valid": False, "row_count": 0, "attested_rows": 0, "unattested_rows": 0, "head_digest": None, "error": str(exc)}, []

def _inspect_git_trailers(root, rows_by_name):
    auth_rows, ver_rows = (rows_by_name.get("authority") or ([], ""))[0], (rows_by_name.get("verifications") or ([], ""))[0]
    rev_rows, waiver_rows = (rows_by_name.get("reviews") or ([], ""))[0], (rows_by_name.get("waivers") or ([], ""))[0]
    grants = {str(r.get("token")).strip(): r for r in auth_rows if isinstance(r, dict) and r.get("granted") is True and str(r.get("token") or "").strip()}
    valid_vers = {str(r.get("id")).strip() for r in ver_rows if isinstance(r, dict) and r.get("passed") is True and str(r.get("id") or "").strip()}
    valid_revs = {str(r.get("artefact") or r.get("id") or "").strip() for r in rev_rows if isinstance(r, dict) and r.get("verdict") == "APPROVED"} - {""}
    valid_waivers = {str(r.get("id")).strip() for r in waiver_rows if isinstance(r, dict) and str(r.get("id") or "").strip()}
    try:
        audit = A.trailer_audit(root, "HEAD", since_first=True)
    except Exception as exc:
        return {"ok": False, "commits_checked": 0, "trailer_commits": 0, "governed_commits": 0, "ungoverned_commits": 0, "all_governed": False, "head_commit": None, "error": str(exc)}
    if audit.get("unreadable"):
        return {"ok": False, "commits_checked": 0, "trailer_commits": 0, "governed_commits": 0, "ungoverned_commits": 0, "all_governed": False, "head_commit": None, "error": str(audit["unreadable"])}
    commits = audit.get("commits") or []
    held_commits = [c for c in commits if not c.get("exempt")]
    trailer_commits, governed, ungoverned = 0, 0, 0
    for c in held_commits:
        carried = A._polyctl_trailers(c["trailers"])
        if carried:
            trailer_commits += 1
        if c.get("merge") or c.get("problems") or not c.get("on_record"):
            ungoverned += 1; continue
        said = {k: v[0] for k, v in carried.items() if v}
        if said.get("Polyctl-Grant", "") not in grants:
            ungoverned += 1; continue
        if said.get("Polyctl-Verification") == A.COORDINATION_TRAILER:
            governed += 1; continue
        v_ok = said.get("Polyctl-Verification", "") in valid_vers
        w_ids = [w.strip() for w in (said.get("Polyctl-Waiver") or "").split(",") if w.strip()]
        r_ok = (said.get("Polyctl-Review", "") in valid_revs) or (bool(w_ids) and all(w in valid_waivers for w in w_ids))
        if v_ok and r_ok:
            governed += 1
        else:
            ungoverned += 1
    return {"ok": True, "commits_checked": len(held_commits), "trailer_commits": trailer_commits, "governed_commits": governed,
            "ungoverned_commits": ungoverned, "all_governed": bool(held_commits and governed > 0 and ungoverned == 0), "head_commit": commits[-1]["sha"] if commits else None, "error": None}

def _scan_compliance_security(root):
    staged = SEC.scan_staged(root)
    if not staged.get("ok"):
        c = staged.get("counts") or {}
        return {"ok": False, "scanned_source": "staged", "scanned_files": max(1, int(staged.get("scanned_files", 1))),
                "total_findings": int(staged.get("total_findings", c.get("BLOCKER", 0) + c.get("HIGH", 0))), "blocker_count": int(c.get("BLOCKER", 0)),
                "high_count": int(c.get("HIGH", 0)), "pii_clean": not any(f.get("rule_id") == "SEC-008" for f in (staged.get("findings") or [])), "error": staged.get("error")}
    try:
        proc = subprocess.run([A.git_binary(), "-C", root, "ls-files", "-z"], capture_output=True, check=False, timeout=10)
        tracked = [p.decode(UTF8, "surrogateescape") for p in (proc.stdout or b"").split(b"\0") if p] if proc.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        tracked = []
    if not tracked:
        return {"ok": False, "scanned_source": "none", "scanned_files": 0, "total_findings": 0, "blocker_count": 0, "high_count": 0, "pii_clean": False, "error": "no tracked files to scan"}
    res = SEC.scan_paths(root, tracked)
    if res.get("error"):
        return {"ok": False, "scanned_source": "staged+tracked", "scanned_files": int(res.get("scanned_files", 0)), "total_findings": 0, "blocker_count": 0, "high_count": 0, "pii_clean": False, "error": res.get("error")}
    try:
        head_diff = subprocess.run([A.git_binary(), "-C", root, "diff", "HEAD", "--no-ext-diff", "--no-textconv", "--unified=0", "--no-color"],
                                   capture_output=True, text=True, encoding=UTF8, errors="replace", check=False, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "scanned_source": "staged+tracked", "scanned_files": int(res.get("scanned_files", 0)), "total_findings": 0, "blocker_count": 0, "high_count": 0, "pii_clean": False, "error": str(exc)}
    if head_diff.returncode != 0:
        return {"ok": False, "scanned_source": "staged+tracked", "scanned_files": int(res.get("scanned_files", 0)), "total_findings": 0, "blocker_count": 0, "high_count": 0, "pii_clean": False, "error": (head_diff.stderr or "git diff HEAD failed").strip()}
    removed_in_wt = "\n".join(line[1:] for line in (head_diff.stdout or "").splitlines() if line.startswith("-") and not line.startswith("--- "))
    all_findings = list(res.get("findings") or []) + (SEC.scan_text(removed_in_wt, path="<HEAD>") if removed_in_wt else [])
    merged = SEC.summarize_findings(all_findings, target="staged+tracked+head")
    counts = merged.get("counts") or {}
    return {"ok": bool(merged.get("ok")) and int(res.get("scanned_files", 0)) > 0, "scanned_source": "staged+tracked+head",
            "scanned_files": int(res.get("scanned_files", 0)), "total_findings": int(merged.get("total_findings", 0)),
            "blocker_count": int(counts.get("BLOCKER", 0)), "high_count": int(counts.get("HIGH", 0)),
            "pii_clean": bool(merged.get("ok")) and not any(f.get("rule_id") == "SEC-008" for f in all_findings), "error": merged.get("error")}

def _evaluate_controls(framework, ledgers_by_name, sec_info, finops_info, git_info):
    req = ("soc2", "iso42001", "kvkk") if framework == "all" else (framework,)
    all_valid = bool(ledgers_by_name) and all(l.get("chain_valid") and l.get("unattested_rows", 0) == 0 for l in ledgers_by_name.values())
    auth, ver, rev = ledgers_by_name.get("authority") or {}, ledgers_by_name.get("verifications") or {}, ledgers_by_name.get("reviews") or {}
    slc, usg = ledgers_by_name.get("slices") or {}, ledgers_by_name.get("billing_usage") or {}
    git_ok = bool(git_info.get("ok") and int(git_info.get("governed_commits", 0)) > 0 and int(git_info.get("ungoverned_commits", 0)) == 0 and git_info.get("all_governed") is True)
    auth_ok = bool(auth.get("chain_valid") and auth.get("unattested_rows", 0) == 0 and int(auth.get("row_count", 0)) > 0 and git_ok)
    ver_ok = bool(ver.get("chain_valid") and ver.get("unattested_rows", 0) == 0 and int(ver.get("row_count", 0)) > 0 and git_ok)
    rev_ok = bool(rev.get("chain_valid") and rev.get("unattested_rows", 0) == 0 and int(rev.get("row_count", 0)) > 0 and git_ok)
    sec_ok = bool(sec_info.get("ok") and int(sec_info.get("scanned_files", 0)) > 0)
    controls = []
    if "soc2" in req:
        controls.extend([
            {"framework": "soc2", "control_id": "CC6.1", "title": "Logical Access & Cryptographic Authority Chain", "status": "MET" if auth_ok and all_valid else "NOT_MET", "evidence_ref": ".polyctl/ledger/authority.jsonl"},
            {"framework": "soc2", "control_id": "CC7.2", "title": "Pre-Commit & Repository Secret Detection", "status": "MET" if sec_ok else "NOT_MET", "evidence_ref": "polyctl security-scan"},
            {"framework": "soc2", "control_id": "CC8.1", "title": "Change Management, Verification & Independent Review", "status": "MET" if (ver_ok and rev_ok) else ("PARTIAL" if (ver_ok or rev_ok) else "NOT_MET"), "evidence_ref": ".polyctl/ledger/verifications.jsonl,.polyctl/ledger/reviews.jsonl"},
        ])
    if "iso42001" in req:
        usg_valid = bool(usg.get("chain_valid") and finops_info.get("budget_ok"))
        controls.extend([
            {"framework": "iso42001", "control_id": "A.6.2", "title": "AI System Lifecycle & Deterministic Verification Gates", "status": "MET" if ver_ok and bool(slc.get("chain_valid")) else "NOT_MET", "evidence_ref": ".polyctl/ledger/verifications.jsonl,.polyctl/ledger/slices.jsonl"},
            {"framework": "iso42001", "control_id": "A.8.4", "title": "Independent AI Output Review & Cross-Family Oversight", "status": "MET" if rev_ok else "NOT_MET", "evidence_ref": ".polyctl/ledger/reviews.jsonl"},
            {"framework": "iso42001", "control_id": "A.9.3", "title": "AI Token, Call & Cost Metering and Spend-Cap Governance", "status": "MET" if (usg_valid and int(usg.get("row_count", 0)) > 0) else ("PARTIAL" if usg_valid else "NOT_MET"), "evidence_ref": ".polyctl/billing/usage.jsonl"},
        ])
    if "kvkk" in req:
        controls.extend([
            {"framework": "kvkk", "control_id": "KVKK-M12.1", "title": "Personal Data (TCKN/PII) & Credential Leak Prevention", "status": "MET" if sec_ok and bool(sec_info.get("pii_clean")) else "NOT_MET", "evidence_ref": "polyctl security-scan"},
            {"framework": "kvkk", "control_id": "KVKK-M12.2", "title": "Tamper-Evident Audit Trail & Hash-Chained Log Integrity", "status": "MET" if (all_valid and auth_ok and ver_ok and rev_ok) else "NOT_MET", "evidence_ref": ".polyctl/ledger/authority.jsonl"},
        ])
    return controls

def _collect_with_rows(root, framework="all"):
    fw = str(framework or "all").strip().lower()
    if fw not in FRAMEWORKS:
        raise ValueError(f"unsupported compliance framework {framework!r}; choose from {', '.join(FRAMEWORKS)}")
    ckpt = _ckpt_get(root)
    if ckpt.get("compliance_active"):
        raw_state = storage.read_in_tree(root, COMPLIANCE_STATE_REL)
        if raw_state is None:
            raise storage.LedgerCorruption(f"{COMPLIANCE_STATE_REL} is missing but checkpoint records exported compliance bundles")
        try:
            st_obj = json.loads(raw_state.decode(UTF8))
        except (ValueError, UnicodeDecodeError) as exc:
            raise storage.LedgerCorruption(f"malformed {COMPLIANCE_STATE_REL}: {exc}") from exc
        if not isinstance(st_obj, dict) or st_obj.get("latest_bundle_id") != ckpt.get("latest_bundle_id") or st_obj.get("latest_bundle_digest") != ckpt.get("latest_bundle_digest"):
            raise storage.LedgerCorruption(f"{COMPLIANCE_STATE_REL} diverges from machine checkpoint store")
    ledgers, rows_by_name = [], {}
    for name, rel, chain, legacy, _ in storage.GATE_LEDGERS:
        info, rows = _inspect_ledger(root, name, rel, chain, legacy, True)
        ledgers.append(info); rows_by_name[name] = (rows, chain)
    for name, rel, chain, legacy in _EXTRA_LEDGERS:
        info, rows = _inspect_ledger(root, name, rel, chain, legacy, False)
        ledgers.append(info); rows_by_name[name] = (rows, chain)
    by_name, sec_info = {item["name"]: item for item in ledgers}, _scan_compliance_security(root)
    try:
        sub, usage = BIL.load_subscription(root), BIL.usage_summary(root)
        finops_info = {"ok": True, "plan_id": sub.get("plan_id", "community"), "status": sub.get("status", "ACTIVE"), "period": usage.get("period"),
                       "used_units": usage.get("used_units", 0), "budget_ok": not bool((usage.get("budget") or {}).get("hard_cap") and (usage.get("budget_exceeded") or usage.get("quota_exceeded")))}
    except (storage.LedgerCorruption, storage.InTheWay, OSError, ValueError) as exc:
        finops_info = {"ok": False, "plan_id": "unknown", "status": "ERROR", "period": None, "used_units": 0, "budget_ok": False, "error": str(exc)}
    git_info = _inspect_git_trailers(root, rows_by_name)
    controls = _evaluate_controls(fw, by_name, sec_info, finops_info, git_info)
    ledgers_valid = all(item["chain_valid"] and item["unattested_rows"] == 0 for item in ledgers) and finops_info["ok"]
    overall_ok = bool(ledgers_valid and controls and all(c["status"] == "MET" for c in controls) and sec_info["ok"])
    report = {
        "schema_version": 1, "framework": fw, "generated_at": _utc_iso(), "status": "COMPLIANT" if overall_ok else "NON_COMPLIANT", "ok": overall_ok, "ledgers_valid": ledgers_valid,
        "controls_summary": {"total": len(controls), "met": sum(1 for c in controls if c["status"] == "MET"), "partial": sum(1 for c in controls if c["status"] == "PARTIAL"), "not_met": sum(1 for c in controls if c["status"] == "NOT_MET")},
        "controls": controls, "evidence": {"ledgers": ledgers, "security_scan": sec_info, "finops": finops_info, "git_trailers": git_info},
    }
    return report, rows_by_name

def collect_compliance_evidence(root, framework="all"):
    return _collect_with_rows(root, framework=framework)[0]

def export_compliance_bundle(root, *, framework="all", out_path=None):
    with storage._exclusive_lock(_lock_path(root)):
        report, _ = _collect_with_rows(root, framework=framework)
        if not report["ledgers_valid"]:
            corrupt = [l["name"] for l in report["evidence"]["ledgers"] if not l["chain_valid"] or l["unattested_rows"] > 0]
            raise storage.LedgerCorruption(f"cannot export compliance bundle from corrupt or unattested ledger(s): {', '.join(corrupt) or 'billing'}")
        if not report["ok"]:
            failing = [f"{c['control_id']}={c['status']}" for c in report["controls"] if c["status"] != "MET"]
            raise ValueError(f"cannot export compliance bundle while project is NON_COMPLIANT ({', '.join(failing)})")
        if out_path:
            target, root_abs = os.path.abspath(os.path.expanduser(str(out_path))), os.path.abspath(root)
            if os.path.commonpath([root_abs, target]) == root_abs and (target == root_abs or os.path.relpath(target, root_abs).split(os.sep)[0] in (".polyctl", ".git")):
                raise ValueError(f"refusing to overwrite protected path {out_path!r}")
        bundle_id = f"CMP-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:10]}"
        bundle = {"bundle_id": bundle_id, **report}
        b_digest, sig, keyed = _canonical_digests(bundle)
        bundle.update(bundle_digest=b_digest, integrity_sha256=sig, checksum_matches=True, integrity_verified=keyed)
        raw = (json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(UTF8)
        rel = f"{COMPLIANCE_BUNDLES_REL}/{bundle_id}.json"
        storage.replace_in_tree(root, rel, raw)
        heads = {l["name"]: {"row_count": l["row_count"], "head_digest": l["head_digest"]} for l in report["evidence"]["ledgers"]}
        state = {"schema_version": 1, "latest_bundle_id": bundle_id, "latest_bundle_digest": b_digest, "latest_integrity_sha256": sig, "updated_at": bundle["generated_at"]}
        state_raw = (json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(UTF8)
        prev_ckpt = _ckpt_get(root)
        _ckpt_record_bundle(root, bundle_id, b_digest, sig, heads)
        try:
            storage.replace_in_tree(root, COMPLIANCE_STATE_REL, state_raw)
        except BaseException:
            storage._update_checkpoint(_state_path(root), lambda _: dict(prev_ckpt))
            raise
        if out_path:
            if os.path.commonpath([root_abs, target]) == root_abs:
                storage.replace_in_tree(root, os.path.relpath(target, root_abs), raw)
            else:
                if os.path.lexists(target) and stat.S_ISLNK(os.lstat(target).st_mode):
                    raise storage.InTheWay(target, "is a symlink; refusing to write compliance bundle through a link")
                storage.replace_file_durably(target, raw)
            bundle["exported_to"] = target
        else:
            bundle["exported_to"] = rel
        return bundle

def _invalid_res(bid, msg):
    return {"ok": False, "bundle_id": bid, "checksum_matches": False, "integrity_verified": False, "checkpoint_matches": False, "ledgers_valid": False, "errors": [msg]}

def verify_compliance_bundle(root, target):
    ref = str(target or "").strip()
    if not ref:
        raise ValueError("bundle id or file path is required for verification")
    raw = None
    if _BUNDLE_ID_RE.match(ref):
        raw = storage.read_in_tree(root, f"{COMPLIANCE_BUNDLES_REL}/{ref}.json")
    else:
        cand, root_abs = os.path.abspath(os.path.expanduser(ref)), os.path.abspath(root)
        if os.path.commonpath([root_abs, cand]) == root_abs and cand != root_abs:
            raw = storage.read_in_tree(root, os.path.relpath(cand, root_abs))
        elif os.path.lexists(cand):
            st = os.lstat(cand)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                raise storage.InTheWay(ref, "is not a regular non-symlink file")
            with open(cand, "rb") as fh:
                raw = fh.read()
    if raw is None:
        return _invalid_res(ref, f"compliance bundle not found: {ref}")
    try:
        bundle = json.loads(raw.decode(UTF8))
    except (ValueError, UnicodeDecodeError) as exc:
        return _invalid_res(ref, f"malformed bundle JSON: {exc}")
    if not isinstance(bundle, dict):
        return _invalid_res(ref, "bundle payload must be a JSON object")
    bid, rec_digest, rec_sig = str(bundle.get("bundle_id") or ref), str(bundle.get("bundle_digest") or ""), str(bundle.get("integrity_sha256") or "")
    try:
        exp_digest, exp_sig, keyed = _canonical_digests(bundle)
    except (TypeError, ValueError) as exc:
        return _invalid_res(bid, f"invalid bundle structure: {exc}")
    digest_ok = bool(rec_digest and hmac.compare_digest(rec_digest, exp_digest))
    sig_ok = bool(rec_sig and hmac.compare_digest(rec_sig, exp_sig))
    checksum_matches = bool(digest_ok and (sig_ok or (not keyed and rec_sig == exp_digest)))
    integrity_verified = bool(keyed and digest_ok and sig_ok and rec_sig.startswith("hmac-sha256:"))
    errors = []
    if not digest_ok:
        errors.append("bundle_digest mismatch: bundle content was modified after export")
    if keyed and not integrity_verified:
        errors.append("HMAC-SHA256 signature verification failed under active signing key")
    elif not keyed and not sig_ok:
        errors.append("integrity_sha256 checksum mismatch")
    ckpt_entry = (_ckpt_get(root).get("bundles") or {}).get(bid)
    if not isinstance(ckpt_entry, dict):
        checkpoint_matches = False; errors.append(f"bundle {bid!r} is not attested in machine checkpoint store")
    elif ckpt_entry.get("bundle_digest") != rec_digest or ckpt_entry.get("integrity_sha256") != rec_sig:
        checkpoint_matches = False; errors.append("bundle digest or signature diverges from machine checkpoint store")
    else:
        checkpoint_matches = True
    fw = str(bundle.get("framework") or "all").strip().lower()
    if fw not in FRAMEWORKS:
        errors.append(f"invalid framework {fw!r} in bundle"); fw = "all"
    live, rows_by_name = _collect_with_rows(root, framework=fw)
    live_by_name, ledgers_valid = {l["name"]: l for l in live["evidence"]["ledgers"]}, bool(live["ledgers_valid"])
    ev = bundle.get("evidence") if isinstance(bundle.get("evidence"), dict) else {}
    raw_b_ledgers = ev.get("ledgers") if isinstance(ev.get("ledgers"), list) else []
    b_by_name = {item.get("name"): item for item in raw_b_ledgers if isinstance(item, dict) and isinstance(item.get("name"), str)}
    for lname, cur in live_by_name.items():
        b_ledger = b_by_name.get(lname)
        if not isinstance(b_ledger, dict):
            ledgers_valid = False; errors.append(f"bundle is missing required ledger {lname!r}"); continue
        raw_cnt = b_ledger.get("row_count")
        if not isinstance(raw_cnt, int) or isinstance(raw_cnt, bool) or raw_cnt < 0:
            ledgers_valid = False; errors.append(f"bundle ledger {lname!r} has invalid row_count"); continue
        if not cur["chain_valid"]:
            ledgers_valid = False; errors.append(f"live ledger {lname!r} failed chain validation")
        elif int(cur["row_count"]) < raw_cnt:
            ledgers_valid = False; errors.append(f"live ledger {lname!r} has fewer rows ({cur['row_count']}) than bundle ({raw_cnt})")
        elif raw_cnt > 0:
            rows, chain = rows_by_name.get(lname, ([], ""))
            if len(rows) < raw_cnt or storage.chained_row_digest(rows[raw_cnt - 1], chain) != b_ledger.get("head_digest"):
                ledgers_valid = False; errors.append(f"live ledger {lname!r} row {raw_cnt} digest diverges from bundle head_digest")
    try:
        re_controls = _evaluate_controls(fw, b_by_name, ev.get("security_scan") if isinstance(ev.get("security_scan"), dict) else {},
                                         ev.get("finops") if isinstance(ev.get("finops"), dict) else {}, ev.get("git_trailers") if isinstance(ev.get("git_trailers"), dict) else {})
        if bundle.get("controls") != re_controls or not re_controls or not all(c["status"] == "MET" for c in re_controls):
            errors.append("bundle controls do not match or satisfy recorded compliance evidence")
    except (TypeError, ValueError, KeyError) as exc:
        errors.append(f"cannot evaluate bundle controls: {exc}")
    if bundle.get("status") != "COMPLIANT" or bundle.get("ok") is not True:
        errors.append("bundle status is not COMPLIANT")
    ok = bool(checksum_matches and (not keyed or integrity_verified) and checkpoint_matches and ledgers_valid and not errors)
    return {"ok": ok, "bundle_id": bid, "framework": bundle.get("framework"), "status": bundle.get("status"),
            "checksum_matches": checksum_matches, "integrity_verified": integrity_verified, "checkpoint_matches": checkpoint_matches, "ledgers_valid": ledgers_valid, "errors": errors}

def cmd_compliance(cfg, args):
    root, action, as_json = cfg["root"], getattr(args, "action", "status") or "status", bool(getattr(args, "json", False))
    fw = getattr(args, "framework", "all") or "all"
    try:
        if action == "status":
            rep = collect_compliance_evidence(root, framework=fw)
            if as_json:
                print(json.dumps(rep, ensure_ascii=False, indent=2))
            else:
                cs = rep["controls_summary"]
                print(f"COMPLIANCE {rep['status']} · framework={rep['framework']} · controls={cs['met']} MET / {cs['partial']} PARTIAL / {cs['not_met']} NOT_MET · ledgers={'VALID' if rep['ledgers_valid'] else 'INVALID'}")
                for c in rep["controls"]:
                    print(f"  [{c['status']}] {c['framework'].upper()} {c['control_id']}: {c['title']} ({c['evidence_ref']})")
            return 0 if rep["ok"] else 1
        if action == "export":
            bundle = export_compliance_bundle(root, framework=fw, out_path=getattr(args, "out", None))
            if as_json:
                print(json.dumps(bundle, ensure_ascii=False, indent=2))
            else:
                print(f"COMPLIANCE BUNDLE EXPORTED · id={bundle['bundle_id']} · status={bundle['status']} · path={bundle['exported_to']} · digest={bundle['bundle_digest'][:24]}...")
            return 0 if bundle["ok"] else 1
        if action == "verify":
            res = verify_compliance_bundle(root, getattr(args, "target", None))
            if as_json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            elif res["ok"]:
                print(f"COMPLIANCE BUNDLE VERIFIED · id={res['bundle_id']} · checksum=OK · hmac={'VERIFIED' if res['integrity_verified'] else 'UNKEYED'}")
            else:
                print(f"COMPLIANCE BUNDLE INVALID · id={res['bundle_id']} · {'; '.join(res['errors'])}", file=sys.stderr)
            return 0 if res["ok"] else 1
    except (ValueError, TypeError, KeyError, OSError, storage.LedgerCorruption) as exc:
        if as_json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"polyctl compliance {action}: {exc}", file=sys.stderr)
        return 1
    return 0
