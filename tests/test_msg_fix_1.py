"""Tests for MSG-FIX-1: messaging defects across mail, inbox, ack, room search, decisions and MCP."""
import io
import json
import os
import subprocess as sp
from pathlib import Path
from types import SimpleNamespace

import pytest

from polyctl import cli, language, lib as A, mcp
from tests import conftest
from tests.test_profiles import _init_args


def _set_store(project, mode):
    root = project["root"]
    stored = {k: v for k, v in project.items() if k != "root"}
    stored["mail"] = {"store": mode}
    Path(root, ".polyctl", "config.json").write_text(json.dumps(stored), encoding="utf-8")
    return A.load_config(root)


# ── H1 & M1: Addressee isolation, admin/person/reviewer inboxes, anyone/handoff per-reader, urgent scope ──

@pytest.mark.parametrize("store", ["deletion", "append-only"])
def test_h1_m1_addressee_isolation_and_handoff_per_reader(project, monkeypatch, capsys, store):
    cfg = _set_store(project, store)
    root = cfg["root"]

    # Unknown recipient is refused at send time.
    assert cli.main(["-C", root, "mail", "send", "INFO", "bad", "--to", "stranger", "--body", "hi"]) == 2
    assert "unknown mail recipient" in capsys.readouterr().out

    # Send to admin, person, reviewer, architect, implementer, and anyone (handoff).
    for recipient in ("admin", "person", "reviewer", "architect", "implementer", "anyone"):
        assert cli.main([
            "-C", root, "mail", "send", "INFO", f"for-{recipient}",
            "--to", recipient, "--body", f"Hello {recipient}",
        ]) == 0
        capsys.readouterr()

    # Implementer inbox contains only implementer + anyone mail, never admin/person/reviewer/architect.
    impl_inbox = [m["id"] for m in mcp.call("polyctl_inbox", {}, cfg, False, role="implementer")["messages"]]
    assert len(impl_inbox) == 2
    assert all("-to-implementer-" in m or "-to-anyone-" in m for m in impl_inbox)

    # Admin, person, reviewer, and architect each see only their own mail + anyone.
    for role in ("admin", "person", "reviewer", "architect"):
        monkeypatch.setenv("POLYCTL_ROLE", role)
        assert cli.main(["-C", root, "mail", "list"]) == 0
        out = capsys.readouterr().out
        assert f"-to-{role}-" in out and "-to-anyone-" in out
        for other in ("admin", "person", "reviewer", "architect", "implementer"):
            if other != role:
                assert f"-to-{other}-" not in out

    # Implementer cannot ack admin's or person's mail.
    admin_msg = next(f for f in A.mailbox(root, cfg["mailbox"]) if "-to-admin-" in f)
    handoff_msg = next(f for f in A.mailbox(root, cfg["mailbox"]) if "-to-anyone-" in f)
    monkeypatch.setenv("POLYCTL_ROLE", "implementer")
    assert cli.main(["-C", root, "mail", "ack", admin_msg]) == 1
    capsys.readouterr()

    # Implementer acking handoff ("anyone") consumes it only for implementer; reviewer and admin still see and ack it.
    assert cli.main(["-C", root, "mail", "ack", handoff_msg]) == 0
    capsys.readouterr()
    assert not A.addressed_to(handoff_msg, cfg, "implementer", root=root)
    assert A.addressed_to(handoff_msg, cfg, "reviewer", root=root)
    assert A.addressed_to(handoff_msg, cfg, "admin", root=root)

    # Reviewer and admin can ack their own mail and the handoff mail.
    rev_msg = next(f for f in A.mailbox(root, cfg["mailbox"]) if "-to-reviewer-" in f)
    monkeypatch.setenv("POLYCTL_ROLE", "reviewer")
    assert cli.main(["-C", root, "mail", "ack", rev_msg]) == 0
    assert cli.main(["-C", root, "mail", "ack", handoff_msg]) == 0
    capsys.readouterr()
    assert not A.addressed_to(handoff_msg, cfg, "reviewer", root=root)

    monkeypatch.setenv("POLYCTL_ROLE", "admin")
    assert cli.main(["-C", root, "mail", "ack", admin_msg]) == 0
    assert cli.main(["-C", root, "mail", "ack", handoff_msg]) == 0
    capsys.readouterr()
    assert not A.addressed_to(handoff_msg, cfg, "admin", root=root)

    # Watchdog anomaly mail is addressed to the architect (not implementer) and can be acked by architect.
    anomaly = A.write_report(root, cfg, "decision-requested", ["the implementer wrote a.md"], key="implementer")
    assert anomaly is not None
    assert A.addressed_to(anomaly, cfg, "architect", root=root)
    assert not A.addressed_to(anomaly, cfg, "implementer", root=root)
    monkeypatch.setenv("POLYCTL_ROLE", "architect")
    assert cli.main(["-C", root, "mail", "ack", anomaly]) == 0
    capsys.readouterr()


def test_h1_urgent_mail_to_admin_does_not_block_implementer(project, capsys):
    root = project["root"]
    assert cli.main([
        "-C", root, "mail", "send", "URGENT", "admin-alert",
        "--to", "admin", "--body", "# Alert\n\n## URGENT\n\nAdmin only.",
    ]) == 0
    capsys.readouterr()

    assert A.urgent_messages(root, project, role="implementer") == []
    assert len(A.urgent_messages(root, project, role="admin")) == 1
    assert A.role_of("admin", project) == "admin"


def test_h1_composed_reviewer_addresses_accepted_by_mail_send_and_note(project, capsys):
    root = project["root"]
    fallback_route = A.compose_reviewer("openai-api", model="local/glm-5.3", family="zhipu")
    primary_route = dict(A.compose_reviewer("claude-code", model="sonnet"), fallbacks=[fallback_route])
    cfg = dict(project, reviewer=primary_route)
    with open(os.path.join(root, ".polyctl", "config.json"), "w", encoding="utf-8") as fh:
        json.dump({k: v for k, v in cfg.items() if k != "root"}, fh)

    for recipient in (
        fallback_route["id"],
        "openai-api/local/glm-5.3",
        A.safe_slug(fallback_route["id"]),
        primary_route["id"],
    ):
        note_name = A.note(root, cfg, recipient, "review context", "Scope note.")
        assert A.addressed_to(note_name, cfg, "reviewer", root=root)
        assert not A.addressed_to(note_name, cfg, "implementer", root=root)
        assert cli.main(["-C", root, "mail", "send", "INFO", "composed-rev", "--to", recipient, "--body", "hi"]) == 0
        sent_name = capsys.readouterr().out.strip()
        assert A.addressed_to(sent_name, cfg, "reviewer", root=root)
        assert not A.addressed_to(sent_name, cfg, "implementer", root=root)

    # Genuinely unknown composed-looking names are still refused.
    assert cli.main([
        "-C", root, "mail", "send", "INFO", "bad-rev", "--to", "openai-api/unknown-model", "--body", "hi",
    ]) == 2
    assert "unknown mail recipient" in capsys.readouterr().out
    with pytest.raises(ValueError, match="unknown mail recipient"):
        A.note(root, cfg, "openai-api/unknown-model", "bad", "body")


# ── H2: Linked worktree resolves to main checkout for every command and MCP ──

def test_h2_linked_worktree_resolves_to_main_checkout_everywhere(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(A, "HOME", str(home))

    main_dir = tmp_path / "alpha-main"
    (main_dir / ".polyctl" / "ledger").mkdir(parents=True)
    (main_dir / "agent-mail").mkdir()
    (main_dir / ".polyctl" / "config.json").write_text(json.dumps({
        "project": "alpha-main",
        "mailbox": "agent-mail",
        "architect": {"id": "claude-code", "name": "fable", "cmd": "claude"},
        "implementer": {"id": "kiro-cli", "name": "kiro", "cmd": "kiro-cli"},
    }), encoding="utf-8")
    (main_dir / ".polyctl" / "board.md").write_text(
        "# Board\n\n## running\n- [S1] Slice one\n\n## blocked\n\n## queued\n\n## done\n",
        encoding="utf-8",
    )
    for argv in (
        ["init", "-q"],
        ["config", "user.email", "t@e"],
        ["config", "user.name", "t"],
        ["add", ".polyctl/config.json", ".polyctl/board.md"],
        ["commit", "-q", "-m", "init"],
    ):
        sp.run([conftest.GIT, *argv], cwd=str(main_dir), check=True)

    wt_dir = tmp_path / "wt-worker"
    sp.run([conftest.GIT, "worktree", "add", "-q", "-b", "wt-branch", str(wt_dir)], cwd=str(main_dir), check=True)
    assert (wt_dir / ".polyctl" / "config.json").is_file()

    monkeypatch.chdir(wt_dir)
    assert A.linked_worktree_main(str(wt_dir)) == os.path.realpath(str(main_dir))
    assert A.find_root(str(wt_dir)) == os.path.abspath(str(wt_dir))

    # status, mail/inbox, report, ask and decisions from worktree all use main_dir.
    assert cli.main(["status", "--json"]) == 0
    status_doc = json.loads(capsys.readouterr().out)
    assert os.path.realpath(status_doc["root"]) == os.path.realpath(str(main_dir))

    assert cli.main(["ask", "Deploy target?", "Staging", "Prod"]) == 0
    did = capsys.readouterr().out.split()[0]
    assert (main_dir / ".polyctl" / "decisions" / f"{did}.json").is_file()
    assert not (wt_dir / ".polyctl" / "decisions").exists()

    assert cli.main(["decisions"]) == 0
    assert did in capsys.readouterr().out

    # MCP server invoked via `polyctl mcp serve` from worktree resolves to main_dir.
    stream = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "polyctl_report",
                               "arguments": {"kind": "status", "summary": "from worktree"}}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "polyctl_inbox", "arguments": {}}}),
    ]) + "\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(stream))
    assert cli.main(["mcp", "serve", "--role", "implementer"]) in (0, None)
    replies = {
        json.loads(line).get("id"): json.loads(line)
        for line in capsys.readouterr().out.splitlines() if line.strip()
    }
    rep = json.loads(replies[1]["result"]["content"][0]["text"])
    assert (main_dir / "agent-mail" / rep["written"]).is_file()
    assert not (wt_dir / "agent-mail").exists()


# ── H3: MCP server uses its own role for inbox and ack ──

def test_h3_mcp_role_architect_reads_and_acks_architect_mail(project):
    root = project["root"]
    to_arch = A.write_mail(
        root, project, "20261020-1000-kiro-to-fable-BLOCKED-need-scope.md",
        "# Need scope\n\n## DECISION REQUIRED\n",
        {"kind": "blocked", "from": "implementer", "to": "architect"},
    )
    to_impl = A.write_mail(
        root, project, "20261020-1001-fable-to-kiro-DECISION-go.md",
        "# Go\n",
        {"kind": "decision", "from": "architect", "to": "implementer"},
    )

    inbox = mcp.call("polyctl_inbox", {}, project, False, role="architect")
    assert [m["id"] for m in inbox["messages"]] == [to_arch]
    seen_rows = [r for r in A.mail_log(root) if r.get("event") == "seen"]
    assert seen_rows[-1]["by"] == "architect" and seen_rows[-1]["id"] == to_arch

    # Architect cannot ack implementer's mail, and can ack its own mail.
    refused = mcp.call("polyctl_ack", {"id": to_impl}, project, False, role="architect")
    assert "not addressed to the architect" in refused.get("error", "")
    acked = mcp.call("polyctl_ack", {"id": to_arch}, project, False, role="architect")
    assert acked["acknowledged"] == to_arch


# ── M2: Seen is recorded per reader so another role listing does not suppress escalation ──

def test_m2_seen_is_recorded_per_reader(project, monkeypatch, capsys):
    root = project["root"]
    msg = A.write_mail(
        root, project, "20261020-1100-kiro-to-fable-BLOCKED-wait.md",
        "# Waiting\n\n## DECISION REQUIRED\n",
        {"kind": "blocked", "from": "implementer", "to": "architect"},
    )
    # Reviewer lists mail: architect's needs-decision mail must remain unseen by architect.
    monkeypatch.setenv("POLYCTL_ROLE", "reviewer")
    assert cli.main(["-C", root, "mail", "list"]) == 0
    capsys.readouterr()

    unseen = [m["id"] for m in A.unseen_messages(root, project)]
    assert msg in unseen

    # Once architect lists mail, it is seen by architect.
    monkeypatch.setenv("POLYCTL_ROLE", "architect")
    assert cli.main(["-C", root, "mail", "list"]) == 0
    capsys.readouterr()
    assert msg not in [m["id"] for m in A.unseen_messages(root, project)]


# ── M3: Sender authentication and agent-harness refusal for person/admin ──

def test_m3_agent_cannot_spoof_person_or_admin_or_ack_as_person(project, monkeypatch, capsys):
    root = project["root"]
    msg = A.write_mail(
        root, project, "20261020-1200-fable-to-person-INFO-hi.md",
        "# Hi person\n",
        {"kind": "info", "from": "architect", "to": "person"},
    )
    monkeypatch.setenv("CLAUDECODE", "1")

    assert cli.main(["-C", root, "mail", "send", "INFO", "spoof", "--from", "person", "--body", "hi"]) == 2
    assert "agent harness" in capsys.readouterr().out

    assert cli.main(["-C", root, "mail", "send", "INFO", "spoof", "--from", "admin", "--body", "hi"]) == 2
    assert "agent harness" in capsys.readouterr().out

    assert cli.main(["-C", root, "mail", "ack", msg]) == 2
    assert "agent harness" in capsys.readouterr().out
    assert msg in A.mailbox(root, project["mailbox"])


# ── M4: Urgent kind, --class urgent, and ## URGENT heading all classify as urgent ──

def test_m4_all_urgent_forms_reach_urgent_messages_and_next(project, capsys):
    root = project["root"]
    assert cli.main([
        "-C", root, "mail", "send", "URGENT", "by-kind",
        "--to", "implementer", "--body", "Urgent by kind alone.",
    ]) == 0
    m_kind = capsys.readouterr().out.strip()

    assert cli.main([
        "-C", root, "mail", "send", "INFO", "by-class",
        "--to", "person", "--class", "urgent", "--body", "Urgent by class.",
    ]) == 0
    m_class = capsys.readouterr().out.strip()

    assert m_kind in [m["id"] for m in A.urgent_messages(root, project, role="implementer")]
    assert m_class in [m["id"] for m in A.urgent_messages(root, project, role="person")]
    assert len(cli._urgent_banner(project)) == 1
    capsys.readouterr()
    person_urgent = [i for i in A.person_items(project) if i["kind"] == "mail-urgent"]
    assert len(person_urgent) == 1 and m_class in person_urgent[0]["command"]


# ── M5: Decisions record asked_by, addressee, interactive/role answerer, and support close ──

def test_m5_decisions_metadata_and_close(project, monkeypatch, capsys):
    root = project["root"]
    monkeypatch.setenv("POLYCTL_ROLE", "implementer")
    assert cli.main([
        "-C", root, "ask", "Which cache?", "Memory", "Disk", "--to", "architect",
    ]) == 0
    did = capsys.readouterr().out.split()[0]

    rec = A.decisions(root)[0]
    assert rec["asked_by"] == "implementer" and rec["addressee"] == "architect"

    # Answered by architect (non-interactively) shows role and non-interactive in decisions output.
    monkeypatch.setenv("POLYCTL_ROLE", "architect")
    assert cli.main(["-C", root, "answer", did, "a"]) == 0
    capsys.readouterr()

    assert cli.main(["-C", root, "decisions"]) == 0
    out = capsys.readouterr().out
    assert "implementer → architect" in out
    assert "architect" in out and "non-interactive" in out

    # Ask another decision and close/withdraw it as a person.
    monkeypatch.setenv("POLYCTL_ROLE", "implementer")
    assert cli.main(["-C", root, "ask", "Obsolete question?", "Yes", "No"]) == 0
    did2 = capsys.readouterr().out.split()[0]

    monkeypatch.delenv("POLYCTL_ROLE", raising=False)
    assert cli.main(["-C", root, "decisions", "--close", did2, "--why", "no longer needed"]) == 0
    assert "closed" in capsys.readouterr().out
    closed_rec = next(d for d in A.decisions(root) if d["id"] == did2)
    assert closed_rec["state"] == "closed" and closed_rec["closed_why"] == "no longer needed"


# ── M6: init .gitignore excludes mail.jsonl, decisions/*.json, decisions.lock and .polyctl/mail/ ──

def test_m6_init_gitignore_excludes_mail_summaries_decisions_and_locks(tmp_path, capsys):
    repo = tmp_path / "clean-repo"
    repo.mkdir()
    sp.run([conftest.GIT, "init", "-q"], cwd=str(repo), check=True)
    assert cli.cmd_init({"root": str(repo)}, _init_args(name="clean-repo", profile=None, agent="kiro")) == 0
    capsys.readouterr()

    gitignore = (repo / ".gitignore").read_text(encoding="utf-8")
    for pattern in (
        ".polyctl/ledger/mail.jsonl",
        ".polyctl/decisions/*.json",
        ".polyctl/decisions.lock",
        ".polyctl/mail/",
    ):
        assert pattern in gitignore


# ── L1, L2, L3: Turkish case-insensitive search, streamed >64KiB body, >20 overflow, empty refused, worktree dedup ──

def test_l1_l2_l3_room_and_mail_search_turkish_streaming_overflow_and_worktree(tmp_path, project, monkeypatch, capsys):
    root = project["root"]
    # L1: Turkish İ/ı and Ş/ş folding.
    A.write_mail(
        root, project, "20261020-1300-fable-to-kiro-INFO-tr.md",
        "# Şimdi İstanbul kapısı\n\nIğdır ve Diyarbakır.\n",
        {"kind": "info", "from": "architect", "to": "implementer"},
    )
    assert len(A.room_search("ŞİMDİ", root)) == 1
    assert len(A.room_search("istanbul", root)) == 1
    assert len(A.room_search("İĞDIR", root)) == 1
    assert len(A.mail_search(root, "ŞİMDİ")) == 1

    # L2: Empty query refused.
    with pytest.raises(ValueError):
        A.room_search("   ", root)
    assert cli.main(["-C", root, "room", "search", "   "]) == 2
    assert "non-empty query" in capsys.readouterr().out

    # L2: Search past 64 KiB of body.
    large_body = "# Header\n\n" + ("padding line\n" * 6000) + "\nneedle-beyond-64k\n"
    assert len(large_body.encode("utf-8")) > 65536
    A.write_mail(
        root, project, "20261020-1301-fable-to-kiro-INFO-large.md",
        large_body,
        {"kind": "info", "from": "architect", "to": "implementer"},
    )
    assert len(A.room_search("needle-beyond-64k", root)) == 1

    # L2: >20 hits prints '... and N more'.
    for idx in range(25):
        A.write_mail(
            root, project, f"20261020-14{idx:02d}-fable-to-kiro-INFO-batch-{idx}.md",
            f"# Batch item {idx}\n\ncommon-overflow-token\n",
            {"kind": "info", "from": "architect", "to": "implementer"},
        )
    assert cli.main(["-C", root, "room", "search", "common-overflow-token"]) == 0
    out = capsys.readouterr().out
    assert "... and 5 more" in out

    # L3: Linked worktree's orphaned mail is not labeled as the main project.
    wt_dir = tmp_path / "wt-search"
    sp.run([conftest.GIT, "worktree", "add", "-q", "-b", "wt-s", str(wt_dir)], cwd=root, check=True)
    (wt_dir / "agent-mail").mkdir(exist_ok=True)
    (wt_dir / "agent-mail" / "20261020-1500-fable-to-kiro-INFO-orphan.md").write_text(
        "# Orphan token-wt-only\n", encoding="utf-8"
    )
    assert A.room_search("token-wt-only", str(wt_dir)) == []


# ── L4: --body "" is distinguished from omitted --body and refused unless --allow-empty ──

def test_l4_empty_body_refused_unless_allow_empty(project, monkeypatch, capsys):
    root = project["root"]
    monkeypatch.setattr("sys.stdin", io.StringIO("stdin fallback that must not be read\n"))
    assert cli.main(["-C", root, "mail", "send", "INFO", "empty", "--body", ""]) == 2
    assert "empty message" in capsys.readouterr().out

    assert cli.main(["-C", root, "mail", "send", "INFO", "empty-ok", "--body", "", "--allow-empty"]) == 0
    written = capsys.readouterr().out.strip()
    assert written.endswith("-INFO-empty-ok.md")


# ── L5: Turkish and accented letters transliterated in slugs ──

def test_l5_safe_slug_transliterates_turkish_and_accented_letters():
    assert A.safe_slug("Türkçe Başlık Çağrısı İğne Öğle".lower()) == "turkce-baslik-cagrisi-igne-ogle"
    assert A.safe_slug("Türkçe Başlık") == "Turkce-Baslik"
    assert language.transliterate_ascii("Şimdi ğüzel") == "Simdi guzel"


# ── L6: note validates --to and derives default kind from context ──

def test_l6_note_validates_recipient_and_defaults_kind_to_note(project, capsys):
    root = project["root"]
    assert cli.main(["-C", root, "note", "Title", "--body", "Body", "--to", "person/../evil"]) == 2
    assert "unknown mail recipient" in capsys.readouterr().out

    name_plain = A.note(root, project, "implementer", "Plain update", "Just an FYI")
    assert "-NOTE-" in name_plain
    name_dec = A.note(root, project, "architect", "Question", "Need answer\n\n## DECISION REQUIRED\n")
    assert "-DECISION-" in name_dec


# ── L7 & L8: polyctl_ask validates question/options and MCP sets isError: true on tool errors ──

def test_l7_l8_mcp_ask_validation_and_is_error_flag(project, monkeypatch, capsys):
    assert "error" in mcp.call("polyctl_ask", {"question": "", "options": ["A", "B"]}, project, False)
    assert "error" in mcp.call("polyctl_ask", {"question": "One?", "options": ["OnlyOne"]}, project, False)
    assert "error" in mcp.call(
        "polyctl_ask", {"question": "Too many?", "options": [f"O{i}" for i in range(9)]}, project, False
    )

    stream = "\n".join([
        json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "polyctl_ask", "arguments": {"question": "", "options": []}}}),
    ]) + "\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(stream))
    monkeypatch.setattr("sys.argv", ["polyctl-mcp", "-C", project["root"]])
    assert mcp.main() in (0, None)
    replies = {
        json.loads(line).get("id"): json.loads(line)
        for line in capsys.readouterr().out.splitlines() if line.strip()
    }
    assert replies[1]["result"]["isError"] is True


# ── L9: Empty role table and configured names normalise recipients to role names ──

def test_l9_recipients_normalise_to_roles(project, capsys):
    root = project["root"]
    empty_cfg = {"root": root, "project": "proj", "mailbox": "agent-mail", "implementer": {}, "architect": {}}
    args1 = SimpleNamespace(
        action="send", type="INFO", topic="default-to", body="hello",
        mail_from=None, mail_to=None, mail_class=None, allow_empty=False, root=root,
    )
    args2 = SimpleNamespace(
        action="send", type="INFO", topic="explicit-to", body="hello",
        mail_from=None, mail_to="implementer", mail_class=None, allow_empty=False, root=root,
    )
    assert cli.cmd_mail(empty_cfg, args1) is None
    n1 = capsys.readouterr().out.strip()
    assert cli.cmd_mail(empty_cfg, args2) is None
    n2 = capsys.readouterr().out.strip()
    assert "-to-implementer-" in n1 and "-to-implementer-" in n2


# ── L10: Repeated ack is idempotent (exit 0, "already handled") and next wording for urgent mail ──

@pytest.mark.parametrize("store", ["deletion", "append-only"])
def test_l10_ack_is_idempotent_and_next_does_not_assign_implementer_urgent_to_person(
    project, monkeypatch, capsys, store
):
    cfg = _set_store(project, store)
    root = cfg["root"]
    msg = A.write_mail(
        root, cfg, "20261020-1600-fable-to-kiro-URGENT-stop.md",
        "# Stop\n\n## URGENT\n\nHold work.\n",
        {"kind": "urgent", "from": "architect", "to": "implementer"},
    )
    # Person items do not tell the person to ack the implementer's urgent mail.
    assert [i for i in A.person_items(cfg) if i["kind"] == "mail-urgent"] == []

    monkeypatch.setenv("POLYCTL_ROLE", "implementer")
    assert cli.main(["-C", root, "mail", "ack", msg]) == 0
    capsys.readouterr()

    # Repeated ack exits 0 and prints "already handled".
    assert cli.main(["-C", root, "mail", "ack", msg]) == 0
    assert "already handled" in capsys.readouterr().out
    res = mcp.call("polyctl_ack", {"id": msg}, cfg, False, role="implementer")
    assert res["acknowledged"] == msg and res["already_handled"] is True


# ── Review round 1 fixes ──

def test_r1_agent_harness_cannot_send_or_ack_as_admin_or_person_via_polyctl_role(project, monkeypatch, capsys):
    root = project["root"]
    admin_msg = A.write_mail(
        root, project, "20261021-1000-fable-to-admin-INFO-directive.md",
        "# Admin directive\n",
        {"kind": "info", "from": "architect", "to": "admin"},
    )
    person_msg = A.write_mail(
        root, project, "20261021-1001-fable-to-person-INFO-notice.md",
        "# Person notice\n",
        {"kind": "info", "from": "architect", "to": "person"},
    )
    monkeypatch.setenv("CLAUDECODE", "1")

    for role, target_msg in (("admin", admin_msg), ("person", person_msg)):
        monkeypatch.setenv("POLYCTL_ROLE", role)
        assert cli.main(["-C", root, "mail", "send", "INFO", "spoof", "--from", role, "--body", "hi"]) == 2
        assert "agent harness" in capsys.readouterr().out

        assert cli.main(["-C", root, "mail", "send", "INFO", "spoof-implicit", "--body", "hi"]) == 2
        assert "agent harness" in capsys.readouterr().out

        assert cli.main(["-C", root, "mail", "ack", target_msg]) == 2
        assert "agent harness" in capsys.readouterr().out
        assert target_msg in A.mailbox(root, project["mailbox"])


def test_r1_close_decision_refuses_agents_and_rule_proposals(project, monkeypatch, capsys):
    root = project["root"]
    monkeypatch.setenv("POLYCTL_ROLE", "implementer")
    proposal, question, created = A.propose(root, project, "allow 500 lines", "oversized diff")
    assert created
    prop_did = question["id"]

    assert cli.main(["-C", root, "ask", "Deploy tonight?", "Yes", "No"]) == 0
    person_did = capsys.readouterr().out.split()[0]

    # Agents cannot close a rule proposal's question or a decision addressed to a person.
    assert cli.main(["-C", root, "decisions", "--close", prop_did]) == 2
    assert "not closed" in capsys.readouterr().out
    assert cli.main(["-C", root, "decisions", "--close", person_did]) == 2
    assert "not closed" in capsys.readouterr().out

    # Agent harness without POLYCTL_ROLE is also refused.
    monkeypatch.delenv("POLYCTL_ROLE", raising=False)
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["-C", root, "answer", person_did, "--close"]) == 2
    assert "not closed" in capsys.readouterr().out
    monkeypatch.delenv("CLAUDECODE", raising=False)

    # Even a person cannot close a rule proposal's question (it is accepted or rejected via answer).
    assert cli.main(["-C", root, "decisions", "--close", prop_did]) == 2
    assert "not closed" in capsys.readouterr().out
    assert A.proposals(root)[0]["state"] == "open"
    assert next(d for d in A.decisions(root) if d["id"] == prop_did)["state"] == A.PROPOSED

    # A person in their own terminal can close an open non-proposal decision.
    assert cli.main(["-C", root, "decisions", "--close", person_did, "--why", "withdrawn"]) == 0
    capsys.readouterr()
    closed = next(d for d in A.decisions(root) if d["id"] == person_did)
    assert closed["state"] == "closed" and closed["closed_by"] == "person"


def test_r1_urgent_decision_mail_escalates_on_unseen_ladder_and_handoff_urgent_holds_commit(
    project, monkeypatch, tmp_path, capsys
):
    from tests.scenarios import World
    import time

    world = World(project, monkeypatch, tmp_path)
    req = "20261021-1100-kiro-to-fable-BLOCKED-urgent-scope.md"
    body = "# Blocked on scope\n\n## URGENT\n\n## DECISION REQUIRED\n\nNeed architect decision.\n"
    world.mail(req, body)
    world.transcript_age(900)
    path = os.path.join(world.root, "agent-mail", req)

    assert A.mail_class(req, A.mail_meta(path), body) == "needs-decision"
    assert req in [m["id"] for m in A.urgent_messages(world.root, world.cfg, role="architect")]

    when = time.time() - 70 * 60
    os.utime(path, (when, when))
    world.notices.clear()
    world.cycle()
    told = [n for n in world.notices if "unread decision request" in n[0]]
    assert told and told[-1][2] == "human" and told[-1][3] == "orange"

    # Handoff ("anyone") urgent mail blocks implementer commit-check until implementer acks, and stays on disk.
    handoff_urgent = A.write_mail(
        world.root, world.cfg, "20261021-1105-admin-to-anyone-URGENT-freeze.md",
        "# Freeze\n\n## URGENT\n\nHold commits.\n",
        {"kind": "urgent", "from": "admin", "to": "anyone"},
    )
    assert handoff_urgent in [m["id"] for m in A.urgent_messages(world.root, world.cfg)]
    monkeypatch.setenv("POLYCTL_ROLE", "implementer")
    assert cli.main(["-C", world.root, "mail", "ack", handoff_urgent]) == 0
    capsys.readouterr()
    assert handoff_urgent not in [m["id"] for m in A.urgent_messages(world.root, world.cfg)]
    assert handoff_urgent in A.mailbox(world.root, world.cfg["mailbox"])
    assert handoff_urgent in [m["id"] for m in A.urgent_messages(world.root, world.cfg, role="reviewer")]


def test_r1_reviewer_and_admin_roles_across_grant_author_propose_answer_board_and_coordination_commit(
    project, monkeypatch, capsys
):
    root = project["root"]
    cfg = dict(
        project,
        reviewer={"id": "codex-reviewer", "name": "codex-rev", "adapter": "codex", "family": "openai"},
    )
    Path(root, ".polyctl", "config.json").write_text(
        json.dumps({k: v for k, v in cfg.items() if k != "root"}), encoding="utf-8"
    )
    Path(root, ".polyctl", "board.md").write_text(
        "# Board\n\n## running\n- [S1] Slice one · acceptance: green\n\n## blocked\n\n## queued\n\n## done\n",
        encoding="utf-8",
    )
    cfg = A.load_config(root)

    # 1. grant_author and propose for admin and reviewer never fall back to architect's name.
    monkeypatch.setenv("POLYCTL_ROLE", "admin")
    assert A.grant_author(cfg) == {"role": "admin", "actor": "admin", "adapter": None, "family": None}
    prop_admin, q_admin, _ = A.propose(root, cfg, "admin rule change", "admin reason")
    assert prop_admin["by"] == {"role": "admin", "actor": "admin", "adapter": None, "family": None}

    monkeypatch.setenv("POLYCTL_ROLE", "reviewer")
    assert A.grant_author(cfg) == {
        "role": "reviewer", "actor": "codex-rev", "adapter": "codex", "family": "openai"
    }
    assert A.grant_author(project)["actor"] == "reviewer"
    prop_rev, _, _ = A.propose(root, cfg, "reviewer rule change", "reviewer reason")
    assert prop_rev["by"]["role"] == "reviewer" and prop_rev["by"]["actor"] == "codex-rev"

    # 2. answer refuses reviewer and admin on proposals, and records answered_role on normal questions.
    for role in ("reviewer", "admin"):
        monkeypatch.setenv("POLYCTL_ROLE", role)
        with pytest.raises(A.AnswerRefused):
            A.answer(root, q_admin["id"], "a")
        q_norm = A.ask(root, f"Question for {role}?", ["Yes", "No"], cfg=cfg, addressee=role)
        answered = A.answer(root, q_norm["id"], "a", interactive=True)
        assert answered["answered_role"] == role and answered["answered_interactive"] is False

    # 3. Board slice block and start record reviewer and admin in the slice ledger.
    monkeypatch.setenv("POLYCTL_ROLE", "reviewer")
    assert cli.main(["-C", root, "slice", "block", "waiting on review", "--slice", "S1"]) == 0
    capsys.readouterr()
    monkeypatch.setenv("POLYCTL_ROLE", "admin")
    assert cli.main(["-C", root, "slice", "start", "S1"]) == 0
    capsys.readouterr()
    slice_rows = A.slice_moves(root)
    assert [r["by"] for r in slice_rows[-2:]] == ["reviewer", "admin"]

    # 4. Coordination-commit refuses reviewer and admin in POLYCTL_ROLE and --by admin.
    reviews_dir = Path(root, "semantic-review")
    reviews_dir.mkdir(exist_ok=True)
    rev_file = reviews_dir / "20261021-COORD.md"
    rev_file.write_text("v1\n", encoding="utf-8")
    sp.run([conftest.GIT, "add", "-f", "semantic-review/20261021-COORD.md"], cwd=root, check=True)
    sp.run([conftest.GIT, "commit", "-q", "--no-verify", "-m", "seed coord"], cwd=root, check=True)
    rev_file.write_text("v2\n", encoding="utf-8")
    sp.run([conftest.GIT, "add", "-f", "semantic-review/20261021-COORD.md"], cwd=root, check=True)
    cand = A.index_candidate(root)

    for role in ("reviewer", "admin"):
        monkeypatch.setenv("POLYCTL_ROLE", role)
        assert cli.cmd_commit_ok(
            cfg, cli.build_parser().parse_args(["commit-ok", "--by", "Sam", "--digest", cand["digest"]])
        ) == 1
        assert f"a coordination commit is a person's act, not the {role}'s" in capsys.readouterr().out

    monkeypatch.delenv("POLYCTL_ROLE", raising=False)
    assert cli.cmd_commit_ok(
        cfg, cli.build_parser().parse_args(["commit-ok", "--by", "admin", "--digest", cand["digest"]])
    ) == 1
    assert "--by names an agent or a role (admin)" in capsys.readouterr().out


@pytest.mark.parametrize("store", ["deletion", "append-only"])
def test_r1_ack_already_handled_checks_literal_id_addressee_and_consumption(project, monkeypatch, capsys, store):
    cfg = _set_store(project, store)
    root = cfg["root"]

    impl_msg = A.write_mail(
        root, cfg, "20261021-1200-fable-to-kiro-INFO-work.md",
        "# Work\n",
        {"kind": "info", "from": "architect", "to": "implementer"},
    )
    admin_acked = A.write_mail(
        root, cfg, "20261021-1202-fable-to-admin-INFO-done.md",
        "# Admin done\n",
        {"kind": "info", "from": "architect", "to": "admin"},
    )

    monkeypatch.setenv("POLYCTL_ROLE", "implementer")
    assert cli.main(["-C", root, "mail", "ack", impl_msg]) == 0
    capsys.readouterr()

    monkeypatch.setenv("POLYCTL_ROLE", "admin")
    assert cli.main(["-C", root, "mail", "ack", admin_acked]) == 0
    capsys.readouterr()

    assert A.mailbox(root, cfg["mailbox"]) == []

    # Wildcard ack on an empty mailbox must fail rather than claiming "already handled".
    monkeypatch.setenv("POLYCTL_ROLE", "implementer")
    assert cli.main(["-C", root, "mail", "ack", "*"]) == 1
    assert "no message matches *" in capsys.readouterr().out

    # Another role cannot get already_handled on admin's consumed mail via CLI or MCP.
    assert cli.main(["-C", root, "mail", "ack", admin_acked]) == 1
    capsys.readouterr()
    mcp_acked = mcp.call("polyctl_ack", {"id": admin_acked}, cfg, False, role="implementer")
    assert "error" in mcp_acked and not mcp_acked.get("already_handled")

    # A message whose view file was deleted without consumption is not "already handled".
    admin_deleted = A.write_mail(
        root, cfg, "20261021-1203-fable-to-admin-INFO-secret.md",
        "# Admin only\n",
        {"kind": "info", "from": "architect", "to": "admin"},
    )
    os.remove(os.path.join(root, cfg["mailbox"], admin_deleted))
    mcp_deleted = mcp.call("polyctl_ack", {"id": admin_deleted}, cfg, False, role="implementer")
    assert "error" in mcp_deleted and not mcp_deleted.get("already_handled")
    if store == "deletion":
        monkeypatch.setenv("POLYCTL_ROLE", "admin")
        assert cli.main(["-C", root, "mail", "ack", admin_deleted]) == 1
        assert "no message matches" in capsys.readouterr().out

    # Legitimate repeat acks by the addressee still exit 0 with already_handled.
    monkeypatch.setenv("POLYCTL_ROLE", "implementer")
    assert cli.main(["-C", root, "mail", "ack", impl_msg]) == 0
    assert "already handled" in capsys.readouterr().out
    monkeypatch.setenv("POLYCTL_ROLE", "admin")
    assert cli.main(["-C", root, "mail", "ack", admin_acked]) == 0
    assert "already handled" in capsys.readouterr().out
