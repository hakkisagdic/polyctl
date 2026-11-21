#!/usr/bin/env python3
"""polyctl — polyctl's command line.

Every command is in build_parser(), with its code in a part under src/polyctl/parts/ that runs in
this module's namespace; the playbook, src/polyctl/skill/SKILL.md, lists each one.

Standard library only. Observation of an agent's session is strictly read-only.
"""
import argparse
import json
import os
import shutil
import subprocess
import signal
import sys
import textwrap
import time
from datetime import datetime

from . import __version__
from . import language
from . import lib as A
from . import matrix as M
from . import settings as S
from . import specs
from .procs import TableUnreadable
from .storage import LedgerLockTimeout
from .verdicts import REVIEWER_VERDICTS
UTF8 = "utf-8"    # every text file polyctl writes or reads; Windows would otherwise use cp1252

C = A.C


A._part("cli_status", globals())


A._part("cli_authority", globals())


A._part("cli_channels", globals())
A._part("cli_gain", globals())
A._part("cli_evidence", globals())
A._part("cli_next", globals())


A._part("cli_review", globals())


A._part("cli_project", globals())


A._part("cli_checks", globals())


A._part("cli_hooks", globals())


A._part("cli_maintenance", globals())


A._part("cli_lanes", globals())
A._part("cli_pr", globals())
A._part("cli_harness", globals())
A._part("cli_install", globals())
A._part("cli_completion", globals())
from .billing import cmd_billing, maybe_meter_cmd
from .security import cmd_security_scan
from .compliance import cmd_compliance
from .policy import cmd_policy
from .archon import (
    cmd_archon_doctor,
    cmd_archon_gate,
    cmd_archon_help,
    cmd_archon_leftovers,
    cmd_archon_notify,
    cmd_archon_record,
    cmd_archon_runs,
)


def _prog_name(prog=None):
    """The command the person typed (`pctl` or `polyctl`), or `polyctl` when run from Python or pytest."""
    raw = os.path.basename(str(prog if prog is not None else (sys.argv[0] if sys.argv else "polyctl"))).lower()
    for suffix in ("-script.py", ".exe", ".ps1", ".cmd", ".bat", ".py"):
        if raw.endswith(suffix):
            raw = raw[:-len(suffix)]
            break
    return "pctl" if raw == "pctl" else "polyctl"


def build_parser(root=None, prog=None):
    """The whole `polyctl` command line, built without running a command.

    main parses with it, and tests/test_docs_commands.py walks it, so a document that shows
    an invocation this parser refuses fails there rather than in a reader's terminal. Building
    it reads the adapter catalog once, for the --agent names init and skill share, the project's
    own adapters among them where `root` names the project (HARNESS-SETUP-3). `prog` names the
    command the person typed (`pctl` or `polyctl`) in help and error messages, while `--version`
    prints `polyctl <version>` for both (POLYCTL-AFTER-RENAME).
    """
    p = argparse.ArgumentParser(prog=_prog_name(prog), description="polyctl (observation layer)")
    p.add_argument("-C", "--root", help="project directory (default: nearest .polyctl/ or git root)")
    p.add_argument("--version", action="version", version=f"polyctl {__version__}")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("status", help="one-shot summary")
    s.add_argument("-m", "--messages", type=int, default=6)
    s.add_argument("--window", type=A.time_arg("h"), default=24.0,
                   help="throughput window: hours (24), or 30m, 1d, today, a date (default 24)")
    s.add_argument("--json", action="store_true", help="print what the panel shows as one JSON document")
    s.set_defaults(fn=cmd_status)

    w = sub.add_parser("watch", help="live panel; leave it in a background terminal")
    w.add_argument("-i", "--interval", type=int, default=15, help="seconds between refreshes (default 15)")
    w.add_argument("-m", "--messages", type=int, default=8)
    w.add_argument("--all", action="store_true", help="one row per project instead of one panel")
    w.add_argument("--web", action="store_true",
                   help="serve the panel, the board, the pipeline and the fleet as read-only pages and /api/* JSON "
                        "on 127.0.0.1 instead")
    w.add_argument("--port", type=int,
                   help=f"with --web: the port on 127.0.0.1 (default {WEB_PORT}; 0 takes a free one)")
    w.set_defaults(fn=cmd_watch)

    fl = sub.add_parser("fleet", help="one-shot view of every project")
    fl.add_argument("--json", action="store_true", help="print the rows as one JSON document")
    fl.set_defaults(fn=cmd_fleet)

    t = sub.add_parser("tail", help="recent messages from the implementer's transcript")
    t.add_argument("-n", type=int, default=5)
    t.set_defaults(fn=cmd_tail)

    ev = sub.add_parser("events", help="what polyctl did on this machine, one line an event; --follow as it happens")
    ev.add_argument("-f", "--follow", action="store_true", help="then print each event as it is written, until Ctrl+C")
    ev.add_argument("--project", help="one project's events: its key, the name its files in ~/.polyctl carry")
    ev.add_argument("--since", type=A.time_arg(), help="written at or after: 30m, 2h, today, a date (2026-09-26)")
    ev.add_argument("-n", type=int, default=20, help="the newest N before following (default 20; 0: every one)")
    ev.add_argument("--json", action="store_true", help="each event as a line of JSON, in the shape the log holds")
    ev.set_defaults(fn=cmd_events)

    m = sub.add_parser("mail", help="list, read or send coordination messages")
    m.add_argument("action", choices=["list", "read", "send", "log", "search", "ack", "compact", "sync"])
    m.add_argument("type", nargs="?", default="INFO")
    m.add_argument("topic", nargs="?")
    m.add_argument("--body")
    m.add_argument("--allow-empty", action="store_true",
                   help="send: allow an empty message body")
    m.add_argument("--from", dest="mail_from",
                   help="who sends the message: a role from the role table, admin or person (default: architect)")
    m.add_argument("--to", dest="mail_to",
                   help="who receives the message: a role from the role table, admin, person or anyone (default: implementer)")
    m.add_argument("--class", dest="mail_class", choices=A.MAIL_CLASSES,
                   help="what the message asks of its reader; needs-decision escalates while unseen")
    m.set_defaults(fn=cmd_mail)

    v = sub.add_parser("verify", help="run the declared gates and record the result")
    v.add_argument("-p", "--profile")
    v.add_argument("--wait", type=int, default=900,
                   help="seconds to wait if another run, of any project, holds the machine gate lock, and as long "
                        "again while the machine is short of memory, paging or disk")
    v.set_defaults(fn=cmd_verify)

    mc = sub.add_parser("merge-check", help="run the gates on a merge's result before merging, and record it")
    mc.add_argument("branch", help="the branch or commit to be merged")
    mc.add_argument("--into", default="HEAD", help="what it is merged into (default HEAD)")
    mc.add_argument("-p", "--profile", help="gate profile (default full, when declared)")
    mc.add_argument("--wait", type=int, default=900,
                    help="seconds to wait if another run, of any project, holds the machine gate lock, and as long "
                         "again while the machine is short of memory, paging or disk")
    mc.set_defaults(fn=cmd_merge_check)

    wd = sub.add_parser("watchdog", help="the scheduled job that restarts a stalled agent: launchd, "
                        "a user systemd on Linux, Task Scheduler on Windows")
    wd.add_argument("action", choices=["install", "uninstall", "status", "explain", "trace"])
    wd.add_argument("--interval", type=int, default=120)
    wd.add_argument("--idle-minutes", type=float, default=None,
                    help="default: the watchdog.idle_minutes setting, read when installed")
    wd.add_argument("--last", type=int, default=20)
    wd.set_defaults(fn=cmd_watchdog)

    bd = sub.add_parser("board", help="where each pre-authorised item is")
    bd.add_argument("view", nargs="?", choices=["ready", "add"],
                    help="ready: exactly the items that may start now, exit 1 on a broken edge; "
                         "add: admit one item, with the boundary it is judged against")
    bd.add_argument("id", nargs="?", help="add: the item's id, one word")
    bd.add_argument("title", nargs="?", help="add: what the item is, on one line")
    bd.add_argument("--acceptance", help="add: what the work must meet, written before it starts")
    bd.add_argument("--needs", help="add: the ids this item waits for, comma-separated")
    bd.add_argument("--role", help="add: the role that takes it, when that is not the implementer")
    bd.set_defaults(fn=cmd_board)
    sp = sub.add_parser("spec", help="check a slice's sections, test traceability and external sources")
    sp.add_argument("action", choices=["check"])
    sp.add_argument("slice", help="the board item's id")
    sp.set_defaults(fn=cmd_spec)
    sl = sub.add_parser("slice", help="add or re-type, start, block or abandon a slice; moves enter the slice ledger; "
                                      "status: where one stands and how it got there")
    sl.add_argument("action", nargs="?", choices=["add", "edit", "start", "block", "abandon", "status"], default="status")
    sl.add_argument("text", nargs="?", help="add, edit, start, status, abandon: the item's id; block: what it waits on")
    sl.add_argument("title", nargs="?", help="add: the item's title")
    sl.add_argument("--type", choices=sorted(A.WORK_TYPE_PROFILES), help="add/edit: work type (default feature)")
    sl.add_argument("--acceptance", help="add: the acceptance boundary")
    sl.add_argument("--needs", help="add: dependency ids, comma-separated")
    sl.add_argument("--role", help="add: the role that takes the slice")
    sl.add_argument("--slice", help="block, abandon, status: the item (default: the running slice)")
    sl.add_argument("--why", help="abandon: why it is dropped, required; start: why, kept with the move")
    sl.add_argument("--waiting", help="block: who it waits on - human, architect, decision or external")
    sl.add_argument("--boundary-file", dest="boundary_file",
                    help="start: a file committed in the repository that the slice is judged against, in place of "
                         "its acceptance sentence; the architect's or a person's")
    sl.set_defaults(fn=cmd_slice)
    sls = sub.add_parser("slices", help="every slice on the board, its state and since when; --open leaves out "
                                        "the done and the rejected")
    sls.add_argument("--open", action="store_true", help="only the open ones: running, blocked, queued, inbox, "
                                                         "verified")
    sls.set_defaults(fn=cmd_slices)
    ak = sub.add_parser("ask", help="pose a decision, answerable in one tap")
    ak.add_argument("question", nargs="?")
    ak.add_argument("options", nargs="*")
    ak.add_argument("--context")
    ak.add_argument("--slice")
    ak.add_argument("--from", dest="asked_by", help="who asks the decision (default: the invoking role or implementer)")
    ak.add_argument("--to", dest="addressee", help="who the decision is addressed to (default: person)")
    ak.add_argument("--codebase", action="store_true",
                    help="ask the code, through codebase.provider run in a copy of the working tree; the answer must "
                         "cite files and lines")
    ak.set_defaults(fn=cmd_ask)
    an = sub.add_parser("answer", help="answer a pending decision")
    an.add_argument("id")
    an.add_argument("value", nargs="*", help="an option's key; after the free-text key, your own words")
    an.add_argument("--change", action="store_true",
                    help="replace an answer already given; both stay in the decision's record")
    an.add_argument("--close", action="store_true",
                    help="close or withdraw an unanswered decision")
    an.add_argument("--why", help="with --close: why the decision is closed or withdrawn")
    an.set_defaults(fn=cmd_answer)
    dc = sub.add_parser("decisions", help="open and answered questions")
    dc.add_argument("-n", type=int, default=10)
    dc.add_argument("--close", metavar="ID", help="close or withdraw an unanswered decision")
    dc.add_argument("--why", help="with --close: why the decision is closed or withdrawn")
    dc.set_defaults(fn=cmd_decisions)
    po = sub.add_parser("propose", help="propose a change to a rule you work under, for a person to accept or "
                                        "reject, instead of editing it")
    po.add_argument("text", nargs="+", help="the change: what the rule would say, or what would change")
    po.add_argument("--why", help="what went wrong under the rule as it stands; required")
    po.add_argument("--rule-file", dest="rule_file",
                    help="the file that holds the rule, as a path in the project (relative to its root)")
    po.set_defaults(fn=cmd_propose)
    pp = sub.add_parser("proposals", help="rule proposals waiting for a person; --all adds the decided ones")
    pp.add_argument("--all", action="store_true", help="also the accepted, rejected and otherwise answered ones")
    pp.add_argument("-n", type=int, default=20, help="at most this many, newest first (default 20)")
    pp.set_defaults(fn=cmd_proposals)
    st_ = sub.add_parser("stats", help="slice outcomes: rounds, first-pass rate, time, size, defects found later")
    st_.add_argument("--all", action="store_true", help="every project registered on this machine")
    st_.add_argument("--since", type=A.time_arg(), help="landed at or after: a date (2026-09-10), 7d, yesterday")
    st_.add_argument("--until", type=A.time_arg(), help="landed before: a date (2026-09-17), 2h, today")
    st_.add_argument("--slices", action="store_true", help="one line per slice")
    st_.set_defaults(fn=cmd_stats)
    gn = sub.add_parser("gain", help="what polyctl measured: slices, spend, reviews, activity, lane evidence and "
                                     "their daily trend, read from the ledgers and never estimated")
    gn.add_argument("--all", action="store_true", help="every project registered on this machine")
    gn.add_argument("--since", type=A.time_arg(),
                    help="window: 30m, 2h, 7d, yesterday or a date (default: everything recorded)")
    gn.add_argument("--days", type=int, default=14, help="days the daily trend shows (default 14)")
    gn.add_argument("--slices", action="store_true", help="one line per landed slice")
    gn.add_argument("--json", action="store_true", help="print one JSON document")
    gn.add_argument("--sources", action="store_true", help="name the files the numbers were read from")
    gn.add_argument("--quota", action="store_true",
                    help="also read the implementer's account (one request; nothing is guessed for an adapter "
                         "that declares no lookup)")
    gn.set_defaults(fn=cmd_gain)
    ex = sub.add_parser("export", help="the project's ledger as OpenTelemetry traces in the OTLP/JSON encoding")
    ex.add_argument("format", choices=["otlp"], help="the export encoding: otlp (one ExportTraceServiceRequest)")
    ex.add_argument("--attested", action="store_true",
                    help="export only the rows this machine's checkpoint store attests and mark the output accordingly")
    ex.add_argument("--out", metavar="FILE", help="write to FILE instead of standard output")
    ex.set_defaults(fn=cmd_export)
    ev = sub.add_parser("evidence", help="platform lane runs recorded from CI as evidence, and what each "
                                         "platform's newest run still vouches for")
    ev.add_argument("action", nargs="?", default="show", choices=["record", "show"])
    ev.add_argument("--platform", help="record: the lane that ran, such as windows, macos or linux")
    ev.add_argument("--run", help="record: the CI run's id, read through gh")
    ev.add_argument("--all", action="store_true", help="show: every recorded row, not only each platform's newest")
    ev.add_argument("--json", action="store_true", help="show: the same readings as one JSON document")
    ev.set_defaults(fn=cmd_evidence)
    nx = sub.add_parser("next", help="what needs doing now, and whose hand does it: a person's items first, then the "
                                     "staged candidate's landing chain, each with the command that closes it")
    nx.add_argument("--json", action="store_true", help="print one JSON document, for the panel and a script")
    nx.add_argument("--short", action="store_true",
                    help="menu-bar output for SwiftBar or xbar: one summary line, then --- and the dropdown lines")
    nx.set_defaults(fn=cmd_next)
    sf = sub.add_parser("surfaces",
                        help="install or remove a desktop surface plugin in the folder you name; never guessed")
    sf.add_argument("action", choices=["install", "uninstall"])
    sf.add_argument("surface", choices=["swiftbar"])
    sf.add_argument("--dir", required=True, metavar="DIR",
                    help="the plugin folder to write into or remove from; required")
    sf.set_defaults(fn=cmd_surfaces)
    rc = sub.add_parser("recall", help="what was decided, found or learned before, across projects")
    rc.add_argument("text", nargs="+")
    rc.add_argument("-n", "--limit", type=int, default=10)
    rc.set_defaults(fn=cmd_recall)
    wt = sub.add_parser("worktrees", help="every worktree and whether it may go; prune retires those that may")
    wt.add_argument("action", nargs="?", choices=["list", "prune"], default="list")
    wt.add_argument("--yes", action="store_true", help="apply the prune (default is a dry run)")
    wt.set_defaults(fn=cmd_worktrees)
    ln = sub.add_parser("lane", help="one worktree per READY board item, prepared from the lane settings")
    ln.add_argument("action", nargs="?", choices=["start", "list", "remove"], default="list")
    ln.add_argument("item", nargs="?", help="start, remove: the board item's id")
    ln.set_defaults(fn=cmd_lane)
    ro = sub.add_parser("role", help="the role table: show, or reassign a role to an actor")
    ro.add_argument("action", nargs="?", choices=["show", "set", "swap"], default="show")
    ro.add_argument("role", nargs="?", choices=list(A.ROLE_BLOCKS))
    ro.add_argument("actor", nargs="?", help="set: an actor; swap: the other role")
    ro.add_argument("--model", help="with set reviewer <adapter>: the model the composed reviewer runs")
    ro.add_argument("--effort", help="with set reviewer <adapter>: its effort, where the adapter takes one")
    ro.add_argument("--family", help="with set reviewer <adapter>: the model's family; a tool reviewer needs one")
    ro.add_argument("--hotfix", action="store_true",
                    help="on a product repository: let the architect implement, named as a hotfix")
    ro.set_defaults(fn=cmd_role)
    spl = sub.add_parser("split-check", help="is the staged candidate a pure move between files?")
    spl.set_defaults(fn=cmd_split_check)
    ht = sub.add_parser("hunt", help="a bounded read-only bug hunt; leads go to the architect")
    ht.add_argument("action", nargs="?", choices=["run", "discard", "status"], default="run")
    ht.add_argument("fingerprint", nargs="?", help="discard: the lead's id")
    ht.set_defaults(fn=cmd_hunt)
    pw = sub.add_parser("pr", help="read this checkout's pull requests through gh and mail the implementer what "
                                   "needs it; never writes to GitHub")
    pw.add_argument("action", choices=["watch"])
    pw.add_argument("--once", action="store_true", help="one pass, then exit; the watchdog does not run it yet")
    pw.set_defaults(fn=cmd_pr)
    hs = sub.add_parser("harness", help="probe: ask each harness that speaks ACP what it supports, sending no prompt; "
                                        "seen: a person reads the harness configuration an agent changed here, and "
                                        "records it as seen")
    hs.add_argument("action", choices=["probe", "seen"])
    hs.add_argument("ids", nargs="*", help="probe: the adapters to ask; every one that declares acp.argv when none is "
                                           "named")
    hs.add_argument("--sessions", action="store_true", help="probe: also ask how many sessions it lists for this "
                                                            "directory")
    hs.add_argument("--timeout", type=float, default=20.0, help="probe: seconds each harness has to answer")
    hs.add_argument("--by", help="seen: the person who reads the changes; never an agent or a role")
    hs.add_argument("--digest", help="seen: record the changes as seen, while they are the bytes shown with this "
                                     "digest; without it they are shown and nothing is recorded")
    hs.add_argument("--ask", action="store_true", help="seen: at a terminal, show the changes and record exactly "
                                                       "them on a yes; one step for a person's own tool approvals")
    hs.set_defaults(fn=cmd_harness)
    ah = sub.add_parser("agent-hook", help="what a harness's lifecycle hook runs: record one event of its session")
    ah.add_argument("event", help="the event in polyctl's words: " + ", ".join(A.AGENT_EVENTS))
    ah.add_argument("--harness", help="the adapter the hook belongs to")
    ah.set_defaults(fn=cmd_agent_hook)
    ag = sub.add_parser("agents", help="the sessions this project's harness hooks spoke of, and what each is doing")
    ag.set_defaults(fn=cmd_agents)
    bk = sub.add_parser("backup", help="write the governance to a directory, a ref or a private remote")
    bk.add_argument("--to", help="a directory, `ref`, or `remote:<name>`; default backup.to in the config")
    bk.set_defaults(fn=cmd_backup)
    rsr = sub.add_parser("restore", help="reconstruct the governance from a backup directory")
    rsr.add_argument("source", help="a backup directory with its manifest.json")
    rsr.add_argument("--by", help="the person who attests the restored ledgers on this machine; never an agent or a role")
    rsr.add_argument("--ask", action="store_true",
                     help="at a terminal, show what would be attested and attest it on a yes")
    rsr.set_defaults(fn=cmd_restore)
    ct = sub.add_parser("content", help="borrow third-party skills, steering and agent definitions pinned to a "
                                        "commit, text only; verify them")
    ct.add_argument("action", choices=["add", "verify"])
    ct.add_argument("spec", nargs="?", help="add: <source>@<40-character commit>")
    ct.add_argument("--skills", help="add: the skills to borrow, comma-separated")
    ct.add_argument("--steering", help="add: the steering files to borrow, comma-separated")
    ct.add_argument("--agents", help="add: the agent definitions to borrow, comma-separated")
    ct.add_argument("--from", dest="base", help="add: the directory in the source that holds skills/, steering/, "
                                                "agents/ and hooks/ (default: its root)")
    ct.add_argument("--harness", help="add: harness adapters to install into (default: those detected)")
    ct.add_argument("--dry-run", action="store_true", help="add: say what would be written where; write nothing")
    ct.set_defaults(fn=cmd_content)
    rm_ = sub.add_parser("room", help="messages across every registered project")
    rm_.add_argument("action", choices=["search"])
    rm_.add_argument("text", nargs="+")
    rm_.set_defaults(fn=cmd_room)
    dg = sub.add_parser("digest", help="what happened, read from the ledgers")
    dg.add_argument("--days", type=A.time_arg("d"), default=1.0,
                    help="how far back: days (7), or 12h, today, a date (default 1)")
    dg.add_argument("-n", type=int, default=6)
    dg.set_defaults(fn=cmd_digest)
    ini = sub.add_parser("init", help="put polyctl on this project (idempotent)")
    ini.add_argument("--name")
    from . import skillkit as _skillkit
    agents = _skillkit.agent_choices(root)  # init and skill offer the same names: one read of the adapter catalog
    ini.add_argument("--agent", choices=agents, default="auto")
    ini.add_argument("--mcp", action="store_true", help="(default) register the MCP server for detected agents")
    ini.add_argument("--no-mcp", action="store_true", help="skip the MCP registration")
    ini.add_argument("--rules", action="store_true", help="also write the pointer into the owner's rule files")
    ini.add_argument("--profile", choices=sorted(A.profiles(root)),
                     help="write the role blocks: who implements, reviews, judges")
    ini.add_argument("--implementer", help="implementer adapter id (`polyctl adapters` lists them); overrides the profile")
    ini.add_argument("--model", help="implementer model, passed through the adapter's --model option")
    ini.add_argument("--effort", help="implementer effort, where its adapter takes one (options.effort_values)")
    ini.add_argument("--reviewer-model", dest="reviewer_model", help="reviewer model (default: its adapter's models.review)")
    ini.add_argument("--watchdog", action="store_true", help="also install the watchdog")
    ini.add_argument("--allow-uncovered-gates", action="store_true",
                     help="write quick gates that exercise none of the detected toolchains")
    ini.add_argument("--prove", action="store_true", help="finish by running polyctl prove")
    ini.add_argument("--no-review", action="store_true", help="with --prove: skip the throwaway review")
    from . import tiers as _tiers
    ini.add_argument("--review-tier", dest="review_tier", choices=list(_tiers.TIERS),
                     help="independent (default): a reviewer of another model family; same-family: another model of "
                          "the implementer's family, labeled weaker independence, which needs --by; person: no model "
                          "reviewer, a person reviews each candidate with polyctl person-review")
    ini.add_argument("--by", help="with --review-tier same-family: the person who opts in, recorded with the login")
    ini.add_argument("--language", choices=list(S.CHOICES["language"]),
                     help="the project's language, set in its config before init writes a file: en (the default) "
                          "or tr; what polyctl writes into the project and for its people follows it")
    ini.add_argument("--adopt", action="store_true",
                     help="adopt polyctl state no tracked .polyctl-project covers, such as a project an older polyctl set up: keep "
                          "all of it, write and stage the marker, install the current hooks, and name the commit left")
    ini.add_argument("--allow-shared-hooks", action="store_true",
                     help="with --adopt: authorize the hook install where Git routes hooks through shared, external, "
                          "or global/system configuration")
    ini.set_defaults(fn=_init_then_prove)
    pv = sub.add_parser("prove", help="run the guarantees: the hook refuses, the reviewer answers, a slice lands")
    pv.add_argument("--no-review", action="store_true",
                    help="skip the throwaway slice, which spends one short review")
    pv.set_defaults(fn=cmd_prove)
    dm = sub.add_parser("demo", help="see the guarantee in about a minute: a change with a bug refused, its fix landed, "
                                     "on a scratch project with a stand-in reviewer")
    dm.add_argument("--keep", action="store_true", help="keep the scratch folder and say where it is")
    dm.set_defaults(fn=cmd_demo)
    st = sub.add_parser("start", help="first-run wizard from nothing to a working, governed project")
    st.add_argument("--yes", action="store_true",
                    help="run only the steps that need no person without asking before each")
    st.set_defaults(fn=cmd_start)
    de = sub.add_parser("decide", help="record an architect decision durably")
    de.add_argument("decision", nargs="?")
    de.add_argument("--why")
    de.add_argument("--answers", help="open decision id this settles, e.g. D-123")
    de.add_argument("--scope")
    de.add_argument("--to", default=None, help="a name; default: whoever holds the implementer role")
    de.add_argument("--urgent", action="store_true")
    de.add_argument("--list", action="store_true")
    de.add_argument("-n", type=int, default=10)
    de.set_defaults(fn=cmd_decide)
    si = sub.add_parser("since", help="what changed since you last looked")
    si.add_argument("ref", nargs="?",
                    help="last | 30m | 2h | 1d | today | yesterday | a date | <git ref>: a ref is given to git "
                         "as a single argument, never an option")
    si.add_argument("--no-mark", action="store_true")
    si.set_defaults(fn=cmd_since)
    nt = sub.add_parser("note", help="write an architect message into the mailbox")
    nt.add_argument("title")
    nt.add_argument("--body")
    nt.add_argument("--to", default=None, help="a name; default: whoever holds the implementer role")
    nt.add_argument("--urgent", action="store_true")
    nt.add_argument("--stdin", action="store_true", help="read the body from stdin")
    nt.set_defaults(fn=cmd_note)
    hf = sub.add_parser("handoff", help="write and send everything a successor needs")
    hf.add_argument("--reason")
    hf.add_argument("--no-send", action="store_true")
    hf.set_defaults(fn=cmd_handoff)
    rw = sub.add_parser("review", help="review an exact staged candidate with an independent actor")
    rw.add_argument("action", nargs="?", choices=["submit", "collect", "cancel"],
                    help="submit: pin the staged candidate and review it in the background; "
                         "collect: take a finished review; cancel: stop a submitted review and its reviewer")
    rw.add_argument("rid", nargs="?", help="collect, cancel: the review id")
    rw.add_argument("--any", action="store_true", help="collect: the oldest finished review")
    rw.add_argument("--run", help=argparse.SUPPRESS)
    rw.add_argument("--boundary", help="acceptance boundary; defaults to the running slice")
    rw.add_argument("--paths", nargs="*", help="narrow a prospective review to these staged paths")
    rw.add_argument("--commits", help="review landed work retrospectively; never authorizes a commit")
    rw.add_argument("--reviewer", metavar="ACTOR",
                    help="with --commits: a reviewer actor of the project's table reviews the range in place of the "
                         "reviewer role, as `polyctl catchup --reviewer` does; the table is not changed")
    rw.add_argument("--slice", dest="range_slice", metavar="ID",
                    help="with --commits: the slice that landed the range; the review is recorded as that slice's and, "
                         "without --boundary, judged against the range's commit messages, as a catch-up review is")
    # Accepted so existing callers keep working, and ignored: the timeout is
    # `review_timeout` in .polyctl/config.json (#63).
    rw.add_argument("--timeout", type=int, help=argparse.SUPPRESS)
    rw.set_defaults(fn=cmd_review)
    rs = sub.add_parser("reviews", help="submitted reviews: state, slice, elapsed and verdict")
    rs.set_defaults(fn=cmd_reviews)
    cr = sub.add_parser("collect-review",
                        help="a person records a stand-in session's answer to polyctl's review request")
    cr.add_argument("nonce")
    cr.add_argument("--response", required=True, help="file holding the session's whole answer")
    cr.add_argument("--model", required=True, help="the model the session ran, as you know it")
    cr.add_argument("--by", required=True, help="the person who carried the answer")
    cr.set_defaults(fn=cmd_collect_review)
    pr = sub.add_parser("person-review",
                        help="a person reads the staged candidate's diff and records APPROVED or NEEDS_CHANGES")
    pr.add_argument("--by", required=True, help="the person who reads the diff; never an agent or a role")
    pr.add_argument("--verdict", choices=list(REVIEWER_VERDICTS),
                    help="record this verdict; without it the diff and its digest are shown and nothing is recorded")
    pr.add_argument("--digest", help="with --verdict: the whole digest shown beside the diff you read")
    pr.add_argument("--findings", help="a file of findings, one a line: - [BLOCKER|HIGH|MEDIUM|LOW] file:line - what "
                                       "breaks; NEEDS_CHANGES needs a BLOCKER or HIGH one. A boundary's criteria are "
                                       "answered there too: CRITERION <n>: MET|NOT MET - the evidence")
    pr.add_argument("--boundary", help="acceptance boundary; defaults to the running slice")
    pr.add_argument("--paths", nargs="*", help="narrow the review to these staged paths")
    pr.add_argument("--commits", help="a landed range instead of the staged candidate: what catch-up closes a waiver on")
    pr.set_defaults(fn=cmd_person_review)
    ci = sub.add_parser("ci", help="a pull request's change reviewed in CI by a model of another family, with no "
                                   "setup; it grants nothing")
    ci.add_argument("action", choices=["review"])
    ci.add_argument("--base", required=True,
                    help="the revision the change is measured from, such as the pull request's base; the review "
                         "starts at its merge base with --head")
    ci.add_argument("--head", default="HEAD", help="the change's last commit (default HEAD)")
    ci.add_argument("--reviewer", required=True, metavar="ADAPTER",
                    help="the reviewer's adapter, composed for this run alone as polyctl role set reviewer composes one")
    ci.add_argument("--model", help="the model the reviewer runs; a tool reviewer needs one")
    ci.add_argument("--family", help="the reviewer model's family, as you know it; a tool reviewer needs one")
    ci.add_argument("--author-family", dest="author_family", required=True,
                    help="the family of the model that wrote the change, or unknown: a statement, not a measurement; "
                         "a reviewer of that family is refused")
    ci.add_argument("--boundary", help="what the change says it does, such as the pull request's title; judged as its "
                                       "author's claim")
    ci.add_argument("--summary", help="a Markdown file to append the verdict and the findings to, such as "
                                      "$GITHUB_STEP_SUMMARY")
    ci.add_argument("--outputs", help="a file to append name=value lines to, such as $GITHUB_OUTPUT: verdict, "
                                      "artefact, tier, base, head and the four counts")
    ci.set_defaults(fn=cmd_ci)
    tg = sub.add_parser("telegram", help="phone channel: alerts out, decisions in")
    tg.add_argument("action", nargs="?", default="status",
                    choices=["status", "setup", "test", "poll", "install", "uninstall"])
    tg.add_argument("--once", action="store_true", help="poll: one pass then exit")
    tg.add_argument("--chat", action="append", metavar="ID",
                    help="setup: a chat the bot takes messages from, by its id; again for each. Without one, polyctl lists "
                         "the chats that wrote to the bot and asks")
    tg.add_argument("--token-env", metavar="NAME",
                    help="setup: the environment variable holding the bot token, where no terminal is attached to "
                         "ask for it at")
    tg.set_defaults(fn=cmd_telegram)
    nt = sub.add_parser("ntfy", help="phone channel: alerts out via ntfy.sh or a self-hosted ntfy server")
    nt.add_argument("action", nargs="?", default="status", choices=["status", "setup", "test"])
    nt.add_argument("--topic-url", metavar="URL", help="setup: the topic's https URL (ntfy.sh or your own server)")
    nt.add_argument("--token-env", metavar="NAME",
                    help="setup: the environment variable holding the access token, when the server needs one")
    # Kept so `--token VALUE` is refused in polyctl's words without argparse quoting the token back.
    nt.add_argument("--token", help=argparse.SUPPRESS)
    nt.set_defaults(fn=cmd_ntfy)
    cr = sub.add_parser("credits", help="credit spend measured from local transcripts")
    cr.add_argument("--offline", action="store_true", help="skip the account lookup")
    cr.add_argument("--local", action="store_true", help="also show this machine's share")
    cr.add_argument("--all", action="store_true",
                    help="every shipped adapter's account and local estimate, one block each")
    cr.add_argument("--reset-day", type=int, help="fallback: override the renewal day")
    cr.set_defaults(fn=cmd_credits)
    cm = sub.add_parser("commit", help="commit the staged candidate after polyctl commit-ok, naming its grant in Polyctl- "
                                       "trailers; never skips hooks")
    source = cm.add_mutually_exclusive_group(required=True)
    source.add_argument("-m", "--message")
    source.add_argument("-F", "--file")
    cm.set_defaults(fn=cmd_commit)
    ck = sub.add_parser("commit-ok", help="grant authority for the exact staged index candidate")
    ck.add_argument("--verify", action="store_true", help="run the quick gates first when the verification is stale")
    ck.add_argument("-p", "--profile", help="gate profile for --verify (default quick)")
    ck.add_argument("--review", help="grant only if the staged tree is the tree this submitted review pinned")
    ck.add_argument("--by", help="person authorising a coordination-only commit (never an agent)")
    ck.add_argument("--ask", action="store_true",
                    help="with --by: show the coordination candidate and ask at this terminal before granting")
    ck.add_argument("--digest", metavar="SHA256",
                    help="with --by: the staged candidate digest polyctl printed to confirm")
    ck.set_defaults(fn=cmd_commit_ok)
    cc = sub.add_parser(
        "commit-check",
        help="pre-commit check: revalidate the recorded grant against the active index; "
             "--range checks landed commits instead",
    )
    cc.add_argument("--range", metavar="A..B",
                    help="check each commit of a revision range instead, or of one commit's whole history: it "
                         "carries the Polyctl- trailers polyctl commit writes and has the tree they name; read-only, and "
                         "it needs no .polyctl/, as in CI")
    cc.add_argument("--since-first-trailer", action="store_true",
                    help="with --range: leave out the commits older than the first one carrying Polyctl- trailers")
    cc.set_defaults(fn=cmd_commit_check)
    lk = sub.add_parser("lock", help="run a heavy command under the machine-wide lock")
    lk.add_argument("--wait", type=int, default=1800,
                    help="seconds to wait if another run holds the machine gate lock, and as long again while the "
                         "machine is short of memory, paging or disk")
    lk.add_argument("command", nargs=argparse.REMAINDER)
    lk.set_defaults(fn=cmd_lock)
    mc = sub.add_parser("mcp", help="serve project state to MCP clients (stdio)")
    mc.add_argument("action", choices=["serve", "config"], nargs="?", default="config")
    mc.add_argument("--allow-verify", action="store_true", help="expose the gate runner too")
    # A role the server does not know is refused here, naming the roles, and by the server itself: it was served every
    # tool, so a mistyped reviewer could report and acknowledge mail as the architect (HUNT-LEADS-SEC). Read without
    # case or surrounding space, as the server reads it (MCP-ROLES).
    mc.add_argument("--role", type=lambda given: given.strip().lower(), choices=sorted(A.ROLE_BLOCKS),
                    help="the role this server serves: architect, implementer or reviewer, each only its own tools "
                         "(default: every tool)")
    mc.add_argument("--project", type=lambda given: given.strip().lower(), choices=["all"],
                    help="all: serve every project in polyctl's project registry on one server, refusing any outside it")
    mc.set_defaults(fn=cmd_mcp)
    am = sub.add_parser("a2a-mcp", help="reach A2A agents from an MCP client (stdio)")
    am.add_argument("action", choices=["serve", "config"], nargs="?", default="config")
    am.set_defaults(fn=cmd_a2a_mcp)

    a2 = sub.add_parser("a2a", help="serve the board as A2A tasks (loopback HTTP)")
    a2.add_argument("action", choices=["serve", "info"], nargs="?", default="info")
    a2.add_argument("--port", type=int, default=8731)
    a2.set_defaults(fn=cmd_a2a)
    n = sub.add_parser("notices", help="alerts this project raised; with an id, what it was raised on")
    n.add_argument("ident", nargs="?", help="a notice id: print its evidence")
    n.add_argument("-n", type=int, default=12)
    n.add_argument("--all", action="store_true", help="include rate-limited ones")
    n.add_argument("--json", action="store_true", help="print the notices as one JSON document")
    n.set_defaults(fn=cmd_notices)
    pr = sub.add_parser("prune", help="trim accumulated records and logs")
    pr.add_argument("--days", type=A.time_arg("d"), default=7,
                    help="records older than this: days (7), or 12h, yesterday, a date (default 7)")
    pr.add_argument("--keep-kb", type=int, default=64, help="log tail to keep")
    pr.add_argument("--evidence", action="store_true", help="also prune verifications and plans")
    pr.add_argument("--review-days", type=A.time_arg("d"), default=None,
                    help="age at which review artefacts nothing rests on move to the archive "
                         "(default: review.prune_after_days)")
    pr.add_argument("--yes", action="store_true", help="apply (default is a dry run)")
    pr.set_defaults(fn=cmd_prune)
    h = sub.add_parser("hold", help="stop this project's agents and keep them stopped")
    h.add_argument("action", choices=["hold", "release", "status"], nargs="?", default="hold")
    h.add_argument("reason", nargs="?")
    h.add_argument("--by", default="architect")
    h.add_argument("--note", help="on release: what changed while the agent was stopped")
    h.add_argument("--grace", type=float, default=10, help="seconds before SIGKILL")
    h.set_defaults(fn=cmd_hold)
    em = sub.add_parser("email", help="the red alarm channel: e-mail via formsubmit.co or an SMTP server")
    em.add_argument("action", choices=["setup", "test", "status"], nargs="?", default="status")
    em.add_argument("--provider", choices=["formsubmit", "smtp"])
    em.add_argument("--token", help="formsubmit: the alias it hands back after verification")
    em.add_argument("--to")
    em.add_argument("--host", help="smtp: the server")
    em.add_argument("--port", type=int, help="smtp: 587 for starttls, 465 for implicit")
    em.add_argument("--user", help="smtp: the account")
    em.add_argument("--password-env", help="smtp: the environment variable holding the password")
    em.add_argument("--from", dest="sender", help="smtp: the sender, if not --to")
    em.add_argument("--tls", choices=["starttls", "implicit", "none"])
    em.set_defaults(fn=cmd_email)
    al = sub.add_parser("alarms", help="live alarm episodes (yellow/orange/red); test rings the channels")
    al.add_argument("action", choices=["list", "test", "snooze", "unsnooze"], nargs="?", default="list")
    al.add_argument("key", nargs="?", help="snooze/unsnooze: the alarm key as polyctl alarms lists it")
    al.add_argument("--level", choices=["yellow", "orange", "red"])
    al.add_argument("--until", type=A.time_arg(),
                    help="snooze: a date (2026-10-01) or a span from now (3d); the alarm rings again from then")
    al.add_argument("--why", help="snooze: why nobody can act on it before then")
    al.add_argument("--by", default="human", help="snooze: who decided it")
    al.set_defaults(fn=cmd_alarms)
    co = sub.add_parser("cost", help="what the coordination spends: implementer turns by class (product/analysis/ceremony/coordination)")
    co.add_argument("--since", type=A.time_arg(),
                    help="window: 24h, 7d, today, a date (default: whole transcript)")
    view = co.add_mutually_exclusive_group()
    view.add_argument("--features", action="store_true", help="what each feature switch spent, measured")
    view.add_argument("--usd", action="store_true",
                      help="the spend in US dollars: an estimate from the price table polyctl ships, unknown for a "
                           "model it does not price")
    co.set_defaults(fn=cmd_cost)
    cf = sub.add_parser("config", help="what a person can set: list, get, set, unset")
    cf.add_argument("action", choices=["list", "get", "set", "unset"], nargs="?", default="list")
    cf.add_argument("key", nargs="?")
    cf.add_argument("value", nargs="?")
    cf.add_argument("--machine", action="store_true", help="the machine's settings, not the project's")
    cf.add_argument("--by", help="the person who changes a setting that weakens a guarantee (review.same_family), "
                                 "recorded with the login")
    cf.set_defaults(fn=cmd_config)
    ft = sub.add_parser("features", help="the switches and what each costs; all off = deterministic polyctl")
    ft.add_argument("action", choices=["list", "on", "off"], nargs="?", default="list")
    ft.add_argument("key", nargs="?")
    ft.add_argument("--by", help="off, for a switch that weakens a guarantee (review, inventory_review): the person "
                                 "who turns it off, on the record; required")
    ft.set_defaults(fn=cmd_features)
    wv = sub.add_parser("waive", help="a person bypasses a gate for a slice, on the record")
    wv.add_argument("gate", choices=["review", "inventory", "gates"])
    wv.add_argument("--slice")
    wv.add_argument("--why")
    wv.add_argument("--by", help="the person who authorises it; required")
    wv.add_argument("--gates", "--gate", dest="gates", default=None,
                    help="for `gates`: comma-separated gate names this waiver covers (every gate of the profile "
                         "when omitted)")
    wv.add_argument("--hours", type=float, default=None,
                    help="how long it may stand in for the gate (settings waivers.default_hours "
                         "and waivers.max_hours; 24 and 168 unless changed)")
    wv.set_defaults(fn=cmd_waive)
    cu = sub.add_parser("catchup", help="replay what could not run: waived reviews and gates, deferred wakes and nudges",
                        description="Replay what could not run: waived reviews and gates, deferred wakes and nudges. "
                                    "A run exits 3 when the reviews it started decided nothing, 1 when a waived gate "
                                    "failed or something could not be written or read, 2 when it is refused, and "
                                    "otherwise 0, whether it made progress or had nothing to do.")
    cu.add_argument("--boundary", help="replace the range's commit claims with a person's boundary; needs --by")
    cu.add_argument("--plan", action="store_true",
                    help="list each open review or gates waiver, its range, commits and changed lines or waived gates, "
                         "whether it closes by proof, and the totals; run nothing and write nothing")
    cu.add_argument("--limit", type=int, help="start at most this many gate re-runs and reviews in this run; what needs "
                                              "neither is still done")
    cu.add_argument("--slice", help="only the waivers for this slice")
    cu.add_argument("--author-family", dest="author_family",
                    help="a person names the model family that wrote the waived ranges, for those whose grant "
                         "recorded none; a reviewer of a family named either way is refused. Needs --by")
    cu.add_argument("--move-only", dest="move_only",
                    help="a person states that these waived slices, separated by commas, only moved code; each "
                         "closes only if the move proof holds on what it landed, never on the statement. Needs --by")
    cu.add_argument("--by", help="with --author-family, --move-only or --boundary: the person who states it, recorded with "
                                 "what it decides")
    cu.add_argument("--reviewer", metavar="ACTOR",
                    help="a reviewer actor of the project's table reviews this run in place of the reviewer role, "
                         "so runs over different slices can each have their own; the table is not changed")
    cu.set_defaults(fn=cmd_catchup)
    pg = sub.add_parser("pings", help="dead man's switch: external pings that alarm when they stop")
    pg.add_argument("action", choices=["status", "setup", "test"], nargs="?", default="status")
    # Kept so a script's `--url VALUE` is refused in polyctl's words: argparse's would quote the URL back (SECRETS-2).
    pg.add_argument("--url", help=argparse.SUPPRESS)
    pg.add_argument("--url-env", metavar="NAME",
                    help="setup: the environment variable holding the ping URL, where no terminal is attached to ask "
                         "for it at")
    pg.add_argument("--all", action="store_true", help="setup: the URL of every project that has none of its own")
    pg.set_defaults(fn=cmd_pings)
    hk = sub.add_parser(
        "hooks",
        help="inspect/install static polyctl hook intent at Git's effective path; shared/external/global mutation needs explicit authorization",
    )
    hk.add_argument("action", choices=["install", "uninstall", "status"], nargs="?", default="status")
    hk.add_argument(
        "--allow-shared-hooks", action="store_true",
        help="authorize the whole mutation set when Git routes hooks through shared, external, or global/system configuration",
    )
    hk.set_defaults(fn=cmd_hooks)
    ps_ = sub.add_parser("push", help="allow a human push for N minutes; check is what the hook runs")
    ps_.add_argument("action", choices=["status", "allow", "check"], nargs="?", default="status")
    ps_.add_argument("--minutes", type=int, default=30)
    ps_.set_defaults(fn=cmd_push)
    rm = sub.add_parser(
        "remove",
        help="take polyctl off this repository after a full hook-topology preflight; protected hooks stay untouched",
    )
    rm.add_argument("--yes", action="store_true")
    rm.add_argument(
        "--allow-shared-hooks", action="store_true",
        help="authorize the whole hook-removal set when Git routes hooks through shared, external, or global/system configuration",
    )
    rm.set_defaults(fn=cmd_remove)
    up = sub.add_parser("update", help="update polyctl the way it was installed (git clone, Homebrew, pipx, uv or pip), "
                                       "saying what it runs first")
    up_when = up.add_mutually_exclusive_group()
    up_when.add_argument("--yes", action="store_true", help="run the update without asking")
    up_when.add_argument("--dry-run", action="store_true", help="say what would run, and run nothing")
    up.set_defaults(fn=cmd_update)
    un = sub.add_parser("uninstall", help="take polyctl's scheduled jobs, hooks and MCP entries off this machine; "
                                          "a dry run unless --yes")
    un.add_argument("--yes", action="store_true", help="take them (default is a dry run)")
    un.add_argument("--purge", action="store_true",
                    help="also delete ~/.polyctl: settings, channel credentials, logs, archived reviews, the registry")
    un.add_argument(
        "--allow-shared-hooks", action="store_true",
        help="authorize removing hooks where Git routes them through shared, external, or global/system configuration",
    )
    un.set_defaults(fn=cmd_uninstall)
    fo = sub.add_parser("fanout", help="may a fan-out of N sub-agents start now; record what one cost")
    fo.add_argument("action", choices=["ok", "record", "history"], nargs="?", default="ok")
    fo.add_argument("--agents", type=int)
    fo.add_argument("--roots", type=int, help="pipeline: number of first-stage agents")
    fo.add_argument("--per-root", type=int, dest="per_root", help="pipeline: at most this many second-stage agents per root")
    fo.add_argument("--per-agent-tokens", type=int, dest="per_agent_tokens")
    fo.add_argument("--provider", help="keyflip provider; default: the architect's")
    fo.add_argument("--done", type=int)
    fo.add_argument("--errors", type=int)
    fo.add_argument("--tokens", type=int)
    fo.add_argument("--note")
    fo.add_argument("--limit", type=int, default=20)
    fo.add_argument("--json", action="store_true")
    fo.set_defaults(fn=cmd_fanout)
    w = sub.add_parser("writers", help="live turns in this tree (not processes); orphans set aside")
    w.add_argument("--clean", action="store_true", help="stop orphaned processes left by ended turns")
    w.add_argument("--json", action="store_true")
    w.set_defaults(fn=cmd_writers)
    sr = sub.add_parser("source", help="external work queues feeding the board")
    sr.add_argument("action", choices=["list", "status", "import"], nargs="?", default="status")
    sr.set_defaults(fn=cmd_source)
    sub.add_parser("projects", help="workspaces with a local agent session").set_defaults(fn=cmd_projects)
    adp = sub.add_parser("adapters", help="adapter registry: list, validate a candidate, run conformance")
    adp.add_argument("action", nargs="?", choices=["list", "validate", "conform"], default="list")
    adp.add_argument("target", nargs="?", help="an adapter id or a JSON file")
    adp.set_defaults(fn=cmd_adapters)
    md = sub.add_parser("mode", help="the project's mode: full (enforced) or lite (basic setup without enforcement)")
    md.add_argument("action", choices=["show", "lite", "full"], nargs="?", default="show")
    md.add_argument("--by", help="the person who switches between lite and full mode, on the record")
    md.add_argument(
        "--allow-shared-hooks", action="store_true",
        help="authorize hook install or uninstall where Git routes hooks through shared, external, "
             "or global/system configuration",
    )
    md.add_argument(
        "--review-lite", action="append", default=None, metavar="CHOICE",
        help="full: which lite-window commits to review (all, none, or <sha>[,<sha>...])",
    )
    md.add_argument(
        "--plan", action="store_true",
        help="full: print the lite window and what each --review-lite choice would do, writing nothing",
    )
    md.set_defaults(fn=cmd_mode)
    dr = sub.add_parser("doctor", help="check this workspace's wiring")
    dr.add_argument("--check", action="store_true",
                    help="quiet: one line per problem, exit 1 if any; pages nobody without --notify")
    dr.add_argument("--notify", action="store_true",
                    help="with --check, for the scheduled job only: page red findings, record advisories")
    dr.add_argument("--consistency", action="store_true",
                    help="check the board, the ledgers, the review artefacts and git against each other")
    dr.add_argument("--repair", action="store_true",
                    help="with --consistency: fix only mechanical disagreements, on the record")
    dr.set_defaults(fn=cmd_doctor)
    sk = sub.add_parser("skill", help="the playbook, rendered for the agents this repository uses")
    sk.add_argument("action", choices=["install", "show"], nargs="?", default="install")
    sk.add_argument("--agent", choices=agents, default="auto")
    sk.set_defaults(fn=cmd_skill)
    cp = sub.add_parser("completion", help="print a script that completes polyctl's commands, options and choices "
                                           "in bash, zsh, fish or PowerShell")
    cp.add_argument("shell", choices=list(COMPLETION_SHELLS), help="the shell the script is for")
    cp.set_defaults(fn=cmd_completion)
    bl = sub.add_parser("billing", help="open-core subscription tiers, iyzico/local payments, usage metering, FinOps spend caps and invoices")
    bl.add_argument("action", nargs="?", default="status", choices=["status", "plans", "subscribe", "meter", "budget", "invoices"])
    bl.add_argument("kind", nargs="?", choices=["review", "verify", "security_scan", "agent_run"], help="meter: operation kind (default review)")
    bl.add_argument("--plan", choices=["community", "pro", "team", "enterprise"], help="subscribe: tier to activate")
    bl.add_argument("--seats", type=int, default=1, help="subscribe: seat count")
    bl.add_argument("--currency", choices=["TRY", "USD"], default="TRY", help="billing currency (default TRY)")
    bl.add_argument("--cycle", choices=["monthly", "yearly"], default="monthly", help="billing cycle")
    bl.add_argument("--provider", choices=["iyzico", "local"], default="iyzico", help="payment provider")
    bl.add_argument("--customer", help="subscribe: customer or organization name")
    bl.add_argument("--tax-id", dest="tax_id", help="subscribe: tax or national identity number")
    bl.add_argument("--payment-token", dest="payment_token", help="subscribe: iyzico checkout token to verify")
    bl.add_argument("--model", help="meter: model identifier")
    bl.add_argument("--actor", help="meter: actor or role identifier")
    bl.add_argument("--prompt-tokens", dest="prompt_tokens", type=int, default=0)
    bl.add_argument("--completion-tokens", dest="completion_tokens", type=int, default=0)
    bl.add_argument("--cost-usd", dest="cost_usd", type=float, default=None)
    bl.add_argument("--cost-try", dest="cost_try", type=float, default=None)
    bl.add_argument("--units", type=int, default=1)
    bl.add_argument("--cap-try", dest="cap_try", type=float, default=None, help="budget: monthly TRY cap")
    bl.add_argument("--cap-usd", dest="cap_usd", type=float, default=None, help="budget: monthly USD cap")
    bl.add_argument("--hard-cap", dest="hard_cap", action="store_true", default=None, help="budget: block when cap exceeded")
    bl.add_argument("--soft-cap", dest="hard_cap", action="store_false", help="budget: warn without blocking")
    bl.add_argument("--check", action="store_true", help="budget: exit 1 when a hard spend cap or quota is exceeded")
    bl.add_argument("--invoice-id", dest="invoice_id", help="invoices: filter by invoice id")
    bl.add_argument("--json", action="store_true", help="print output as JSON")
    bl.set_defaults(fn=cmd_billing)
    sc = sub.add_parser("security-scan", help="deterministic pre-commit secret, credential and policy scanner")
    sc.add_argument("--paths", nargs="*", help="scan specific relative paths instead of the staged git index")
    sc.add_argument("--json", action="store_true", help="print output as JSON")
    sc.set_defaults(fn=cmd_security_scan)
    cmp = sub.add_parser("compliance", help="enterprise compliance and audit evidence bundle export and verification (SOC 2, ISO/IEC 42001, KVKK)")
    cmp.add_argument("action", nargs="?", default="status", choices=["status", "export", "verify"])
    cmp.add_argument("target", nargs="?", help="verify: compliance bundle id (CMP-YYYYMMDD-...) or path to bundle JSON file")
    cmp.add_argument("--framework", choices=["soc2", "iso42001", "kvkk", "all"], default="all", help="compliance framework to evaluate or export (default all)")
    cmp.add_argument("--out", metavar="FILE", help="export: also write the signed evidence bundle JSON to FILE")
    cmp.add_argument("--json", action="store_true", help="print output as JSON")
    cmp.set_defaults(fn=cmd_compliance)
    pol = sub.add_parser("policy", help="team RBAC and policy-as-code enforcement engine")
    pol.add_argument("action", nargs="?", default="status", choices=["status", "init", "bind", "set-rules", "check"])
    pol.add_argument("--actor", help="bind/check: actor or role identifier")
    pol.add_argument("--role", choices=["owner", "admin", "architect", "reviewer", "implementer", "auditor"], help="bind: RBAC role to assign")
    pol.add_argument("--permission", help="check: specific RBAC permission to verify (e.g. code:write, commit:grant, compliance:export)")
    pol.add_argument("--max-product-lines", dest="max_product_lines", type=int, default=None, help="set-rules: maximum staged product lines")
    pol.add_argument("--forbidden-paths", dest="forbidden_paths", nargs="*", default=None, help="set-rules: glob patterns forbidden for implementer")
    pol.add_argument("--require-security-scan", dest="require_security_scan", action="store_true", default=None, help="set-rules: require clean security scan")
    pol.add_argument("--no-require-security-scan", dest="require_security_scan", action="store_false", help="set-rules: disable security scan requirement")
    pol.add_argument("--require-cross-family-review", dest="require_cross_family_review", action="store_true", default=None, help="set-rules: require cross-family reviewer")
    pol.add_argument("--no-require-cross-family-review", dest="require_cross_family_review", action="store_false", help="set-rules: allow same-family reviewer in policy")
    pol.add_argument("--require-budget-ok", dest="require_budget_ok", action="store_true", default=None, help="set-rules: require FinOps budget gate pass")
    pol.add_argument("--no-require-budget-ok", dest="require_budget_ok", action="store_false", help="set-rules: disable FinOps budget gate check in policy")
    pol.add_argument("--json", action="store_true", help="print output as JSON")
    pol.set_defaults(fn=cmd_policy)
    ar = sub.add_parser("archon", help="bridge to the archon CLI: doctor, runs, gate, record, notify, leftovers")
    ar.set_defaults(fn=cmd_archon_help)
    ar_sub = ar.add_subparsers(dest="archon_cmd", metavar="{doctor,runs,gate,record,notify,leftovers}")
    ar_dr = ar_sub.add_parser("doctor", help="check archon CLI, adoption and hooks")
    ar_dr.set_defaults(fn=cmd_archon_doctor)
    ar_rn = ar_sub.add_parser("runs", help="list Archon workflow runs as JSON")
    ar_rn.set_defaults(fn=cmd_archon_runs)
    ar_gt = ar_sub.add_parser("gate", help="verify, grant and commit a staged worktree")
    ar_gt.add_argument("--worktree", required=True, metavar="DIR", help="git worktree directory to gate and commit")
    ar_gt.add_argument("-m", "--message", required=True, metavar="MSG", help="commit message")
    ar_gt.add_argument("--review", metavar="ID", help="submitted review id pinned to the staged tree")
    ar_gt.add_argument("-p", "--profile", metavar="PROFILE", help="verification profile for verify and commit-ok")
    ar_gt.set_defaults(fn=cmd_archon_gate)
    ar_rc = ar_sub.add_parser("record", help="append a chained Archon run event")
    ar_rc.add_argument("--run", required=True, metavar="ID", help="Archon run identifier")
    ar_rc.add_argument("--event", required=True, metavar="E", help="event name (for example landed or backup)")
    ar_rc.add_argument("--sha", required=True, metavar="S", help="commit SHA (7-64 hexadecimal characters)")
    ar_rc.add_argument("--undo", required=True, metavar="TEXT", help="undo command or rollback pointer")
    ar_rc.add_argument("--item", metavar="ITEM", help="work item identifier")
    ar_rc.add_argument("--result", metavar="R", help="outcome or summary string")
    ar_rc.set_defaults(fn=cmd_archon_record)
    ar_nt = ar_sub.add_parser("notify", help="send an open question through polyctl channels")
    ar_nt.add_argument("--run", required=True, metavar="ID", help="Archon run identifier")
    ar_nt.add_argument("--text", required=True, metavar="T", help="open question or notification text")
    ar_nt.set_defaults(fn=cmd_archon_notify)
    ar_lo = ar_sub.add_parser("leftovers", help="list worktrees and branches of finished runs")
    ar_lo.add_argument("--repo", required=True, metavar="DIR", help="git repository directory to inspect")
    ar_lo.set_defaults(fn=cmd_archon_leftovers)
    return p


def _coordination_cfg(cfg, args, record=True):
    """Use the governed main checkout for project-wide coordination when `-C` was not given (ADMIN-FINDINGS-1, MSG-FIX-1).

    Gate and commit commands run against the linked worktree's own tree and ledgers so a lane can
    verify, grant and commit its own files; status, mail, notes, decisions and MCP serve the shared
    main checkout unless `-C` explicitly names a checkout.
    """
    if not getattr(args, "root", None):
        main_root = A.linked_worktree_main(cfg["root"])
        if main_root and os.path.realpath(main_root) != os.path.realpath(cfg["root"]):
            return A.load_config(main_root, record=record)
    return cfg


def main(argv=None, prog=None):
    """Run one `polyctl` command and return its exit status.

    Ordinary trouble ends in a line, not a traceback (CLI-ROBUST): an argument polyctl cannot read
    exits 2 naming what it takes, and so does a project directory that does not exist; a
    ledger lock another process holds names the lock and what to do; Ctrl+C exits 130, as a
    shell's own commands do; anything unexpected prints its type and message, and POLYCTL_DEBUG=1
    keeps its traceback for whoever has to find where it came from. The standard streams are
    UTF-8 before anything is read or printed, whatever the platform's code page (#71). A
    process table the platform could not read stops the command where it was asked, and says
    so: what the command decides from it is not decided (WINDOWS-TABLE-CLOSED). A board that
    changed while a command read it is named with what to do, and nothing was moved
    (SLICE-LIFECYCLE-2). Help and error messages name the command the person typed (`pctl` or
    `polyctl`), while `--version` prints `polyctl <version>` for both (POLYCTL-AFTER-RENAME).
    """
    A.utf8_streams()
    prog = _prog_name(prog)
    command, root = prog, None
    try:
        # The project the command is for, read before the rest, so --agent knows its own adapters (HARNESS-SETUP-3).
        early = argparse.ArgumentParser(add_help=False, exit_on_error=False)
        early.add_argument("-C", "--root")
        try:
            given = early.parse_known_args(argv)[0].root
        except argparse.ArgumentError:
            given = None                        # the parser proper names what is wrong, as `prog`
        p = build_parser(A.find_root(given if given and os.path.isdir(os.path.expanduser(given)) else None), prog=prog)
        args = p.parse_args(argv)
        if args.root and not os.path.isdir(os.path.expanduser(args.root)):
            # Taken at face value, a missing directory showed an empty panel and exited 0.
            what = "not a directory" if os.path.exists(os.path.expanduser(args.root)) else "no such directory"
            p.exit(2, f"{prog}: error: -C {args.root}: {what}\n")
        if not getattr(args, "fn", None):
            p.print_help()
            return 0
        command = f"{prog} {args.cmd}"
        root = A.find_root(args.root)
        record = args.cmd not in ("export", "spec", "archon") and not (args.cmd == "watch" and getattr(args, "web", False))
        cfg = A.load_config(root, record=record)
        return maybe_meter_cmd(cfg["root"], args, lambda: args.fn(cfg, args) or 0)
    except KeyboardInterrupt:
        return 130
    except LedgerLockTimeout as exc:
        lock = exc.path or str(exc)
        if root and lock.startswith(os.path.join(root, "")):
            lock = os.path.relpath(lock, root)
        waited = f" for {exc.timeout:g}s" if exc.timeout is not None else ""
        print(f"{command}: another process held the ledger lock {lock}{waited}; "
              "let it finish, then run this again", file=sys.stderr)
        return 1
    except TableUnreadable as exc:
        print(f"{command} stopped: {exc}. It decides nothing from processes it cannot see; "
              "run it again once the table can be read", file=sys.stderr)
        return 1
    except A.BoardChanged as exc:
        print(f"{command}: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        if os.environ.get("POLYCTL_DEBUG", "") not in ("", "0"):
            raise
        print(f"{command}: {type(exc).__name__}: {' '.join(str(exc).split())} "
              "(run it again with POLYCTL_DEBUG=1 for the traceback)", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
