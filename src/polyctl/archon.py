"""`polyctl archon` — stdlib-only CLI wrapper bridging bash workflow nodes to the `archon` CLI.

This module never imports Archon code, never reads private paths, never starts a review actor,
never waives a gate, never pushes, and never deletes worktrees or branches. Every subcommand
emits exactly one JSON line on stdout and uses exit codes:
  0  success
  2  usage error, invalid arguments, missing `archon` binary, or non-JSON `archon` output
  3  gate refusal, corrupt ledger on append, or leftover worktrees/branches found
"""
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

from . import lib as A
from . import storage

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 3

ARCHON_CHAIN = "polyctl-archon-row-v1"
ARCHON_RUNS_ARGV = ("workflow", "status", "--json")
ARCHON_VERSION_ARGV = ("--version",)
ARCHON_TIMEOUT = 30
FINISHED_STATES = frozenset({
    "completed",
    "complete",
    "done",
    "finished",
    "landed",
    "succeeded",
    "success",
    "failed",
    "cancelled",
    "canceled",
    "abandoned",
})
SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_GIT_ENV_STRIP = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_PREFIX",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
)


class ArchonMissingError(RuntimeError):
    """Raised when the `archon` executable is not found on PATH."""


class ArchonCallError(RuntimeError):
    """Raised when invoking `archon` fails or produces invalid output."""


def archon_ledger_path(root):
    """Return the path to the chained Archon run-event ledger in `root`."""
    return os.path.join(root, ".polyctl", "ledger", "archon.jsonl")


def _emit(payload, code=EXIT_OK):
    """Write one JSON line to stdout and return `code`."""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return code


def _clean_git_env():
    """Return a copy of os.environ without inherited repository-binding GIT_* variables."""
    env = dict(os.environ)
    for var in _GIT_ENV_STRIP:
        env.pop(var, None)
    return env


def _git_run(cwd, *args, timeout=30):
    """Run git in `cwd` with clean git env; returns CompletedProcess."""
    return subprocess.run(
        [A.git_binary(), "-C", cwd] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=_clean_git_env(),
        shell=False,
    )


def _compact_detail(text):
    """Strip ANSI codes and collapse whitespace for concise JSON refusal messages."""
    clean = _ANSI_RE.sub("", str(text or ""))
    lines = [" ".join(line.split()) for line in clean.splitlines() if line.strip()]
    joined = "; ".join(lines)
    return joined[:400] if len(joined) > 400 else joined


def _capture_call(fn, *args, **kwargs):
    """Call `fn(*args, **kwargs)` with stdout and stderr captured; return (rc, combined_output)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = fn(*args, **kwargs)
    return (0 if rc is None else int(rc)), buf.getvalue()


def find_archon():
    """Return the path to `archon` on PATH, or None if absent."""
    return shutil.which("archon")


def run_archon(args, timeout=ARCHON_TIMEOUT, cwd=None, expect_json=True):
    """Invoke `archon` with argument list `args` (no shell) and parse JSON stdout when requested."""
    binary = find_archon()
    if not binary:
        raise ArchonMissingError("archon CLI not found on PATH")
    argv = [binary] + list(args)
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ArchonCallError(f"archon timed out after {timeout}s") from exc
    except OSError as exc:
        raise ArchonCallError(f"failed to execute archon: {exc}") from exc

    if proc.returncode != 0:
        raw_err = proc.stderr.strip() or proc.stdout.strip()
        first_line = raw_err.splitlines()[0] if raw_err else f"exit {proc.returncode}"
        raise ArchonCallError(f"archon exited {proc.returncode}: {first_line[:200]}")

    stdout = proc.stdout.strip()
    if not expect_json:
        return stdout
    if not stdout:
        raise ArchonCallError("archon returned empty output instead of JSON")
    try:
        return json.loads(stdout)
    except ValueError as exc:
        raise ArchonCallError(f"archon returned non-JSON output: {exc}") from exc


def _extract_runs(raw):
    """Extract a list of run dicts from `archon workflow status --json` output."""
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = None
        for key in ("runs", "workflows", "items"):
            if isinstance(raw.get(key), list):
                items = raw[key]
                break
        if items is None:
            raise ArchonCallError("unexpected JSON structure from archon: expected runs list")
    else:
        raise ArchonCallError("unexpected JSON structure from archon: expected list or object")

    for item in items:
        if not isinstance(item, dict):
            raise ArchonCallError("unexpected JSON item in archon runs list: expected object")
    return items


def _normalize_run(item):
    """Map an Archon run entry to `{run, workflow, state, branch}`."""
    return {
        "run": item.get("run") or item.get("id") or item.get("run_id"),
        "workflow": item.get("workflow") or item.get("workflow_name") or item.get("workflowName") or item.get("name"),
        "state": item.get("state") or item.get("status"),
        "branch": item.get("branch") or item.get("branch_name") or item.get("branchName"),
    }


def _run_worktree(item):
    """Extract an optional worktree path from a raw Archon run object."""
    return item.get("worktree") or item.get("worktree_path") or item.get("worktreePath") or item.get("path") or None


def cmd_archon_help(cfg, args):
    """Handle bare `polyctl archon` with no subcommand."""
    return _emit(
        {
            "ok": False,
            "error": "missing archon subcommand: choose one of doctor, runs, gate, record, notify, leftovers",
        },
        EXIT_USAGE,
    )


def cmd_archon_doctor(cfg, args):
    """Report Archon binary presence, version, polyctl adoption, and hook status as JSON."""
    root = cfg["root"]
    binary = find_archon()
    archon_found = bool(binary)
    archon_version = None
    if archon_found:
        try:
            ver_text = run_archon(ARCHON_VERSION_ARGV, timeout=10, expect_json=False)
            lines = [line.strip() for line in ver_text.splitlines() if line.strip()]
            archon_version = lines[0] if lines else None
        except (ArchonMissingError, ArchonCallError):
            archon_version = None

    adopted = bool(A.project_config_document(root).get("config"))
    hooks_installed = False
    try:
        from . import cli
        inv = cli._polyctl_hook_inventory(root)
        if not inv.get("error"):
            active = cli._active_hook_targets(inv)
            pre = active.get("pre-commit") or {}
            hooks_installed = cli._state_base(pre.get("static_state", "")) in ("current-local", "current-scoped")
    except Exception:
        hooks_installed = False

    return _emit(
        {
            "ok": True,
            "archon_found": archon_found,
            "archon_version": archon_version,
            "adopted": adopted,
            "hooks_installed": hooks_installed,
        },
        EXIT_OK,
    )


def cmd_archon_runs(cfg, args):
    """Query `archon workflow status --json` and emit normalized run rows."""
    try:
        raw = run_archon(ARCHON_RUNS_ARGV)
        items = _extract_runs(raw)
    except (ArchonMissingError, ArchonCallError) as exc:
        return _emit({"ok": False, "error": str(exc)}, EXIT_USAGE)
    rows = [_normalize_run(item) for item in items]
    return _emit({"ok": True, "runs": rows}, EXIT_OK)


def _is_git_worktree_root(path):
    """Return True only when `path` is an existing directory that is the top-level of a git worktree."""
    if not path or not os.path.isdir(path):
        return False
    try:
        inside = _git_run(path, "rev-parse", "--is-inside-work-tree")
        if inside.returncode != 0 or inside.stdout.strip().lower() != "true":
            return False
        top = _git_run(path, "rev-parse", "--show-toplevel")
        if top.returncode != 0 or not top.stdout.strip():
            return False
    except (OSError, subprocess.SubprocessError):
        return False
    return os.path.realpath(top.stdout.strip()) == os.path.realpath(path)


def cmd_archon_gate(cfg, args):
    """Run verify, review pin check, commit-ok, and commit inside `--worktree DIR`."""
    message = getattr(args, "message", None)
    if not str(message or "").strip():
        return _emit({"ok": False, "error": "commit message must not be empty"}, EXIT_USAGE)

    raw_dir = getattr(args, "worktree", None)
    worktree = A.find_root(raw_dir) if raw_dir else ""
    if not _is_git_worktree_root(worktree):
        return _emit({"ok": False, "error": f"not a git worktree: {raw_dir or worktree}"}, EXIT_USAGE)

    wt_cfg = A.load_config(worktree, record=False)
    from . import cli
    from . import features as F

    # 1. Require a staged candidate in the target worktree.
    try:
        candidate = A.index_candidate(worktree)
    except RuntimeError as exc:
        return _emit({"ok": False, "refused": "staged", "detail": str(exc)}, EXIT_REFUSED)
    if not candidate.get("changed_paths"):
        return _emit({"ok": False, "refused": "staged", "detail": "nothing staged in worktree"}, EXIT_REFUSED)

    # 2. Run verification gates against the target worktree.
    profile = getattr(args, "profile", None)
    rc_verify, out_verify = _capture_call(
        cli.cmd_verify, wt_cfg, SimpleNamespace(profile=profile, wait=900)
    )
    if rc_verify != 0:
        return _emit(
            {"ok": False, "refused": "verify", "detail": _compact_detail(out_verify) or "verification failed"},
            EXIT_REFUSED,
        )

    try:
        candidate = A.index_candidate(worktree)
    except RuntimeError as exc:
        return _emit({"ok": False, "refused": "staged", "detail": str(exc)}, EXIT_REFUSED)

    # 3. Check review pin without starting any reviewer actor.
    try:
        work_profile = A.active_work_profile(wt_cfg)
    except ValueError as exc:
        return _emit({"ok": False, "refused": "commit-ok", "detail": str(exc)}, EXIT_REFUSED)

    review_required = F.enabled(wt_cfg, "review") or work_profile["reviewer_families"] == 2
    review_id = getattr(args, "review", None)
    if review_required and not review_id:
        return _emit(
            {
                "ok": False,
                "refused": "review",
                "detail": "profile requires a review; pass --review ID",
            },
            EXIT_REFUSED,
        )
    if review_id:
        state = cli._review_state(worktree, review_id)
        if not state:
            return _emit(
                {"ok": False, "refused": "review", "detail": f"no submitted review {review_id}"},
                EXIT_REFUSED,
            )
        if state.get("state") != "finished":
            return _emit(
                {
                    "ok": False,
                    "refused": "review",
                    "detail": f"{review_id} is {state.get('state')}, not finished",
                },
                EXIT_REFUSED,
            )
        if state.get("tree") != candidate.get("index_tree"):
            return _emit(
                {
                    "ok": False,
                    "refused": "review",
                    "detail": f"staged tree does not match review {review_id}",
                },
                EXIT_REFUSED,
            )

    # 4. Grant commit authority via `commit-ok --verify`.
    rc_ok, out_ok = _capture_call(
        cli.cmd_commit_ok,
        wt_cfg,
        SimpleNamespace(verify=True, profile=profile, review=review_id, by=None, ask=False, digest=None),
    )
    if rc_ok != 0:
        detail = _compact_detail(out_ok) or "commit-ok refused"
        lowered = detail.lower()
        if review_required and ("review" in lowered or "capability matrix" in lowered):
            step = "review"
        elif "verification" in lowered:
            step = "verify"
        else:
            step = "commit-ok"
        return _emit({"ok": False, "refused": step, "detail": detail}, EXIT_REFUSED)

    # 5. Commit the granted tree via `polyctl commit`.
    rc_commit, out_commit = _capture_call(
        cli.cmd_commit, wt_cfg, SimpleNamespace(message=message, file=None)
    )
    if rc_commit != 0:
        return _emit(
            {"ok": False, "refused": "commit", "detail": _compact_detail(out_commit) or "commit refused"},
            EXIT_REFUSED,
        )

    head_proc = _git_run(worktree, "rev-parse", "HEAD")
    sha = head_proc.stdout.strip() if head_proc.returncode == 0 else None
    payload = {"ok": True, "sha": sha, "worktree": worktree}
    if review_id:
        payload["review"] = review_id
    if profile:
        payload["profile"] = profile
    return _emit(payload, EXIT_OK)


def cmd_archon_record(cfg, args):
    """Append one hash-chained Archon run event to `.polyctl/ledger/archon.jsonl`."""
    run_id = str(getattr(args, "run", "") or "").strip()
    event = str(getattr(args, "event", "") or "").strip()
    sha_raw = str(getattr(args, "sha", "") or "").strip()
    undo = str(getattr(args, "undo", "") or "").strip()

    if not run_id or not event or not undo:
        return _emit({"ok": False, "error": "run, event and undo must not be empty"}, EXIT_USAGE)
    if not SHA_RE.fullmatch(sha_raw):
        return _emit({"ok": False, "error": "sha must be 7-64 hexadecimal characters"}, EXIT_USAGE)

    raw_row = {
        "at": int(time.time()),
        "run": run_id,
        "event": event,
        "sha": sha_raw.lower(),
        "undo": undo,
    }
    item = getattr(args, "item", None)
    result = getattr(args, "result", None)
    if item is not None:
        raw_row["item"] = str(item)
    if result is not None:
        raw_row["result"] = str(result)

    record = A.scan_record(raw_row)
    path = archon_ledger_path(cfg["root"])
    try:
        row = storage.append_chained_jsonl(path, record, ARCHON_CHAIN)
    except (storage.LedgerCorruption, OSError, ValueError) as exc:
        return _emit({"ok": False, "refused": "record", "error": str(exc)}, EXIT_REFUSED)

    return _emit(
        {
            "ok": True,
            "ledger": ".polyctl/ledger/archon.jsonl",
            "ordinal": row["ordinal"],
            "previous": row["previous"],
            "run": row["run"],
            "event": row["event"],
            "sha": row["sha"],
            "at": row["at"],
        },
        EXIT_OK,
    )


def cmd_archon_notify(cfg, args):
    """Forward an open question through polyctl's existing channels; never answers decisions."""
    run_id = str(getattr(args, "run", "") or "").strip()
    text = str(getattr(args, "text", "") or "").strip()
    if not run_id or not text:
        return _emit({"ok": False, "error": "run and text must not be empty"}, EXIT_USAGE)

    root = cfg["root"]
    title = f"Archon run {run_id}"
    message = f"{title}\n{text}"

    from . import email, ntfy, telegram

    tg_count = 0
    ntfy_ok = False
    email_ok = False
    try:
        _, _ = _capture_call(lambda: None)
        tg_res, _ = _capture_call(telegram.send, message, root)
        tg_count = int(tg_res or 0)
    except Exception:
        tg_count = 0
    try:
        ntfy_res, _ = _capture_call(ntfy.send, message, root, level="orange")
        ntfy_ok = bool(ntfy_res)
    except Exception:
        ntfy_ok = False
    try:
        email_res, _ = _capture_call(email.send, title, message, root)
        email_ok = bool(email_res)
    except Exception:
        email_ok = False

    delivered = bool(tg_count or ntfy_ok or email_ok)
    if os.path.isdir(os.path.join(root, ".polyctl")):
        try:
            A.record_notice(root, title, text[:200], sent=delivered, key=f"archon:{run_id}")
        except Exception:
            pass

    return _emit(
        {
            "ok": True,
            "run": run_id,
            "delivered": delivered,
            "channels": {
                "telegram": tg_count,
                "ntfy": ntfy_ok,
                "email": email_ok,
            },
        },
        EXIT_OK,
    )


def cmd_archon_leftovers(cfg, args):
    """List git worktrees and branches belonging to finished Archon runs that still exist."""
    raw_repo = getattr(args, "repo", None)
    repo = A.find_root(raw_repo) if raw_repo else ""
    if not repo or not os.path.isdir(repo):
        return _emit({"ok": False, "error": f"not a git repository: {raw_repo or repo}"}, EXIT_USAGE)
    try:
        inside = _git_run(repo, "rev-parse", "--is-inside-work-tree")
    except (OSError, subprocess.SubprocessError) as exc:
        return _emit({"ok": False, "error": f"not a git repository: {exc}"}, EXIT_USAGE)
    if inside.returncode != 0 or inside.stdout.strip().lower() != "true":
        return _emit({"ok": False, "error": f"not a git repository: {raw_repo or repo}"}, EXIT_USAGE)

    try:
        raw = run_archon(ARCHON_RUNS_ARGV)
        items = _extract_runs(raw)
    except (ArchonMissingError, ArchonCallError) as exc:
        return _emit({"ok": False, "error": str(exc)}, EXIT_USAGE)

    trees = A.worktree_list(repo)
    linked_trees = trees[1:] if len(trees) > 1 else []
    branch_proc = _git_run(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    local_branches = set(
        line.strip() for line in (branch_proc.stdout.splitlines() if branch_proc.returncode == 0 else []) if line.strip()
    )
    protected = set()
    default_br = A.default_branch(repo)
    if default_br:
        protected.add(default_br)
    if trees and trees[0].get("branch"):
        protected.add(trees[0]["branch"])

    seen_wt = set()
    leftover_worktrees = []
    seen_br = set()
    leftover_branches = []

    for raw_item in items:
        norm = _normalize_run(raw_item)
        state = str(norm.get("state") or "").strip().lower()
        if state not in FINISHED_STATES:
            continue
        run_wt = _run_worktree(raw_item)
        run_wt_real = os.path.realpath(run_wt) if run_wt else None
        run_branch = norm.get("branch")

        for tree in linked_trees:
            t_path = tree.get("path")
            if not t_path or not os.path.isdir(t_path):
                continue
            t_real = os.path.realpath(t_path)
            matched = (run_wt_real and t_real == run_wt_real) or (run_branch and tree.get("branch") == run_branch)
            if matched and t_real not in seen_wt:
                seen_wt.add(t_real)
                leftover_worktrees.append({
                    "run": norm.get("run"),
                    "path": t_path,
                    "branch": tree.get("branch"),
                    "state": norm.get("state"),
                })

        if run_branch and run_branch in local_branches and run_branch not in protected and run_branch not in seen_br:
            seen_br.add(run_branch)
            leftover_branches.append(run_branch)

    if leftover_worktrees or leftover_branches:
        return _emit(
            {
                "ok": False,
                "refused": "leftovers",
                "repo": repo,
                "worktrees": leftover_worktrees,
                "branches": leftover_branches,
            },
            EXIT_REFUSED,
        )

    return _emit(
        {
            "ok": True,
            "repo": repo,
            "worktrees": [],
            "branches": [],
        },
        EXIT_OK,
    )
