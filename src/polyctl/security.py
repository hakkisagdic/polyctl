"""Pre-commit and repository secret, PII and dangerous policy scanner (P0-3).

Scans git staged diffs (`git diff --cached --no-ext-diff --no-textconv`) using `lib.git_binary()` or
specified repository paths for leaked credentials, API keys, private keys, PII (such as Turkish
National ID / TCKN in assignment context) and high-risk policy patterns before an agent commits.
Secrets and PII are always masked (`REDACTED`) in terminal and JSON output without trailing characters,
and low-entropy PII fingerprints never hash raw identity digits without an HMAC salt.
"""
import hashlib
import hmac
import json
import os
import re
import subprocess

from . import lib as A

UTF8 = "utf-8"

RULES = (
    {"id": "SEC-001", "severity": "BLOCKER", "title": "Anthropic API Key",
     "pattern": re.compile(r"\bsk-ant-(?:api03-)?[A-Za-z0-9_-]{20,}\b"),
     "remediation": "Remove the key, rotate it in Anthropic Console, and read ANTHROPIC_API_KEY from the environment."},
    {"id": "SEC-002", "severity": "BLOCKER", "title": "OpenAI API Key",
     "pattern": re.compile(r"\bsk-(?!ant-)(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}\b"),
     "remediation": "Remove the key, revoke it in OpenAI Dashboard, and read OPENAI_API_KEY from the environment."},
    {"id": "SEC-003", "severity": "BLOCKER", "title": "AWS Access Key ID",
     "pattern": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
     "remediation": "Remove the AWS key, deactivate it in IAM, and use short-lived IAM roles or environment variables."},
    {"id": "SEC-004", "severity": "BLOCKER", "title": "GitHub Personal Access Token",
     "pattern": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
     "remediation": "Revoke the GitHub token immediately and inject GITHUB_TOKEN via environment or gh auth."},
    {"id": "SEC-005", "severity": "BLOCKER", "title": "PEM Private Key Block",
     "pattern": re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PRIVATE )?PRIVATE KEY-----"),
     "remediation": "Never commit private key material; store keys outside the repository and add *.pem/*.key to .gitignore."},
    {"id": "SEC-006", "severity": "HIGH", "title": "Slack / Payment Live Secret Token",
     "pattern": re.compile(r"\b(?:xox[baprs]-[0-9A-Za-z-]{20,}|sk_live_[0-9A-Za-z]{20,}|iyz_live_[0-9A-Za-z_]{16,})\b"),
     "remediation": "Rotate the Slack/payment secret and load it from environment variables."},
    {"id": "SEC-007", "severity": "HIGH", "title": "Credentials Embedded in URL",
     "pattern": re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]+:[^/\s@]{4,}@[^/\s]+\b"),
     "remediation": "Strip inline username:password from the URL and pass credentials via environment or header."},
    {"id": "SEC-008", "severity": "HIGH", "title": "Hardcoded PII / National Identity Number (TCKN)",
     "pattern": re.compile(r"(?i)(?:^|[^A-Za-z0-9])(?:tckn|tc_kimlik|kimlik_no|identity_?number)\b\s*[:=]\s*['\"]?([1-9][0-9]{10})['\"]?"),
     "remediation": "Remove hardcoded national identity numbers (KVKK PII) from source files and use synthetic fixtures."},
)


def mask_secret(raw_value, *, rule_id=None):
    """Mask a sensitive match without exposing trailing characters or PII digits."""
    val = str(raw_value or "").strip()
    if not val or len(val) <= 4 or rule_id == "SEC-008":
        return "***REDACTED***"
    return f"{val[:2]}***REDACTED***" if len(val) < 16 else f"{val[:4]}***REDACTED***"


def fingerprint_secret(path, line_number, rule_id, raw_value):
    """Return a 16-hex finding fingerprint; never unsalted-hash low-entropy PII (SEC-008)."""
    salt = (os.environ.get("POLYCTL_SECURITY_SALT") or "").strip()
    if salt:
        msg = f"{path}:{line_number}:{rule_id}:{raw_value}".encode(UTF8)
        return "hmac-sha256:" + hmac.new(salt.encode(UTF8), msg, hashlib.sha256).hexdigest()[:16]
    payload = f"{path}:{line_number}:{rule_id}" if rule_id == "SEC-008" else f"{path}:{line_number}:{rule_id}:{raw_value}"
    return "sha256:" + hashlib.sha256(payload.encode(UTF8)).hexdigest()[:16]


def _make_finding(rule, path, line_no, raw):
    return {
        "rule_id": rule["id"], "severity": rule["severity"], "title": rule["title"],
        "path": path, "line": line_no, "masked_match": mask_secret(raw, rule_id=rule["id"]),
        "fingerprint": fingerprint_secret(path, line_no, rule["id"], raw),
        "remediation": rule["remediation"],
    }


def scan_text(text, path="<memory>"):
    """Scan `text` line by line and return masked finding dicts."""
    findings = []
    for line_no, line in enumerate((text or "").splitlines(), 1):
        for rule in RULES:
            for match in rule["pattern"].finditer(line):
                raw = match.group(1) if match.lastindex else match.group(0)
                findings.append(_make_finding(rule, path, line_no, raw))
    return findings


def scan_diff(diff_text):
    """Scan only added lines (`+...`, excluding `+++ b/...`) in a unified git diff."""
    findings, current_path, current_line = [], "<staged>", 0
    hunk_re = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
    for raw_line in (diff_text or "").splitlines():
        if raw_line.startswith("+++ b/"):
            current_path = raw_line[6:].strip()
        elif raw_line.startswith("+++ "):
            continue
        elif m := hunk_re.match(raw_line):
            current_line = int(m.group(1)) - 1
        elif raw_line.startswith("+"):
            current_line += 1
            added = raw_line[1:]
            for rule in RULES:
                for match in rule["pattern"].finditer(added):
                    raw = match.group(1) if match.lastindex else match.group(0)
                    findings.append(_make_finding(rule, current_path, max(1, current_line), raw))
        elif not raw_line.startswith("-"):
            current_line += 1
    return findings


def _error_report(target, error_msg, scanned_files=None):
    out = {
        "ok": False, "verdict": "ERROR", "target": target, "error": error_msg,
        "total_findings": 0, "counts": {"BLOCKER": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}, "findings": [],
    }
    if scanned_files is not None:
        out["scanned_files"] = scanned_files
    return out


def scan_staged(root):
    """Run `git diff --cached --no-ext-diff --no-textconv --unified=0` via `A.git_binary()`; fail closed if git fails."""
    try:
        proc = subprocess.run(
            [A.git_binary(), "-C", str(root), "diff", "--cached", "--no-ext-diff", "--no-textconv", "--unified=0", "--no-color"],
            capture_output=True, text=True, encoding=UTF8, errors="replace", check=False,
        )
    except OSError as exc:
        return _error_report("staged", f"git execution failed: {exc}")
    if proc.returncode != 0:
        return _error_report("staged", (proc.stderr or "").strip() or f"git diff --cached exited {proc.returncode}")
    return summarize_findings(scan_diff(proc.stdout or ""), target="staged")


def _within_root(root_real, candidate_real):
    try:
        return os.path.commonpath([root_real, candidate_real]) == root_real
    except ValueError:
        return False


def scan_paths(root, paths):
    """Scan specified files or directories under `root`; fail closed on paths outside `root` or missing paths."""
    findings, scanned_files, root_real = [], 0, os.path.realpath(root)
    for item in paths or []:
        candidate = item if os.path.isabs(item) else os.path.join(root, item)
        candidate_real = os.path.realpath(candidate)
        if not _within_root(root_real, candidate_real):
            return _error_report("paths", f"refused path outside repository root: {item}", scanned_files)
        if not os.path.exists(candidate_real):
            return _error_report("paths", f"path does not exist: {item}", scanned_files)
        if os.path.isdir(candidate_real):
            for dirpath, dirnames, filenames in os.walk(candidate_real):
                dirnames[:] = [d for d in dirnames if d not in (".git", ".venv", "__pycache__", "node_modules")]
                for fname in sorted(filenames):
                    f_real = os.path.realpath(os.path.join(dirpath, fname))
                    if not _within_root(root_real, f_real):
                        continue
                    try:
                        with open(f_real, "rb") as fh:
                            data = fh.read(2_000_000)
                        if b"\x00" not in data:
                            scanned_files += 1
                            findings.extend(scan_text(data.decode(UTF8, "replace"), path=os.path.relpath(f_real, root_real)))
                    except OSError:
                        continue
        elif os.path.isfile(candidate_real):
            try:
                with open(candidate_real, "rb") as fh:
                    data = fh.read(2_000_000)
                if b"\x00" not in data:
                    scanned_files += 1
                    findings.extend(scan_text(data.decode(UTF8, "replace"), path=os.path.relpath(candidate_real, root_real)))
            except OSError as exc:
                return _error_report("paths", f"cannot read {item}: {exc}", scanned_files)
    return summarize_findings(findings, target="paths", scanned_files=scanned_files)


def summarize_findings(findings, target="staged", scanned_files=None):
    counts = {"BLOCKER": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for f in findings:
        sev = f.get("severity", "HIGH")
        counts[sev] = counts.get(sev, 0) + 1
    passed = (counts["BLOCKER"] == 0 and counts["HIGH"] == 0)
    out = {"ok": passed, "verdict": "PASS" if passed else "BLOCKED", "target": target,
           "total_findings": len(findings), "counts": counts, "findings": findings}
    if scanned_files is not None:
        out["scanned_files"] = scanned_files
    return out


def cmd_security_scan(cfg, args):
    """Run the deterministic pre-commit secret, PII and policy scanner (`polyctl security-scan`)."""
    root = cfg["root"]
    paths = getattr(args, "paths", None)
    report = scan_paths(root, paths) if paths else scan_staged(root)
    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    if report["verdict"] == "ERROR":
        print(f"SECURITY SCAN ERROR  target={report['target']}  {report.get('error', 'scan failed')}")
        return 1
    if report["ok"]:
        print(f"SECURITY SCAN PASS  target={report['target']}  findings=0")
        return 0
    print(f"SECURITY SCAN BLOCKED  target={report['target']}  BLOCKER={report['counts']['BLOCKER']}  HIGH={report['counts']['HIGH']}")
    for f in report["findings"]:
        print(f"  [{f['severity']}] {f['rule_id']} {f['path']}:{f['line']} — {f['title']} ({f['masked_match']}, {f['fingerprint']})")
        print(f"    remediation: {f['remediation']}")
    return 1
