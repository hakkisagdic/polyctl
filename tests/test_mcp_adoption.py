import io
import json
from pathlib import Path

from polyctl import cli, lib as A, mcp, skillkit


def _rpc(monkeypatch, capsys, root, messages, *extra_args):
    stdin = io.StringIO("\n".join(json.dumps(m) for m in messages) + "\n")
    monkeypatch.setattr("sys.stdin", stdin)
    rc = cli.main(["-C", root, "mcp", "serve", *extra_args])
    assert rc == 0
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def test_mcp_serve_handshake_roles_and_real_cli_parity(project, monkeypatch, capsys):
    root = project["root"]
    # Add a READY slice on the board and send a message to implementer so board/mail/next have real state
    assert cli.main([
        "-C", root, "board", "add", "SLICE-MCP-1", "Verify MCP parity",
        "--acceptance", "MCP and CLI outputs match on board, status, next, mail, and decisions.",
    ]) == 0
    assert cli.main([
        "-C", root, "mail", "send", "INFO", "Parity test",
        "--body", "Parity check body", "--from", "architect", "--to", "implementer",
    ]) == 0
    capsys.readouterr()

    # 1. Verify architect role lists all 15 tools and all 3 prompts
    arch_resps = _rpc(
        monkeypatch,
        capsys,
        root,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "prompts/list"},
        ],
        "--role",
        "architect",
    )
    arch_by_id = {r["id"]: r for r in arch_resps}
    assert [t["name"] for t in arch_by_id[1]["result"]["tools"]] == list(mcp.EVERY_TOOL)
    assert [p["name"] for p in arch_by_id[2]["result"]["prompts"]] == ["status", "land-slice", "stuck"]

    # 2. Verify implementer role handshake, discover, tools, and read calls
    responses = _rpc(
        monkeypatch,
        capsys,
        root,
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "claude-code", "version": "2.1"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "server/discover",
                "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}},
            },
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 4, "method": "resources/list"},
            {"jsonrpc": "2.0", "id": 5, "method": "prompts/list"},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "polyctl_status", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "polyctl_board", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "polyctl_next", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "polyctl_inbox", "arguments": {}}},
        ],
        "--role",
        "implementer",
    )
    by_id = {r["id"]: r for r in responses}
    assert by_id[1]["result"]["protocolVersion"] == "2025-06-18"
    assert by_id[2]["result"]["supportedVersions"] == ["2026-07-28", "2025-06-18"]
    assert [t["name"] for t in by_id[3]["result"]["tools"]] == list(mcp.ROLE_TOOLS["implementer"])
    assert len(by_id[4]["result"]["resources"]) == 4
    assert [p["name"] for p in by_id[5]["result"]["prompts"]] == ["status", "stuck"]

    mcp_status = json.loads(by_id[6]["result"]["content"][0]["text"])
    mcp_board = json.loads(by_id[7]["result"]["content"][0]["text"])
    mcp_next = json.loads(by_id[8]["result"]["content"][0]["text"])
    mcp_inbox = json.loads(by_id[9]["result"]["content"][0]["text"])

    # Compare status against `polyctl status --json` across all shared status domains
    assert cli.main(["-C", root, "status", "--json"]) == 0
    cli_status = json.loads(capsys.readouterr().out)
    assert len(mcp_status) >= 27
    assert mcp_status["project"] == cli_status["project"]
    assert mcp_status["root"] == cli_status["root"]
    assert mcp_status["state"] == cli_status["implementer"]["state"]
    assert mcp_status["adapter"] == cli_status["implementer"]["adapter"]
    assert mcp_status["doing"] == cli_status["implementer"]["doing"]
    assert mcp_status["dirty_files"] == cli_status["repository"]["dirty_files"]
    assert mcp_status["behind"] == cli_status["repository"]["behind"]
    assert mcp_status["base"] == cli_status["repository"]["base"]
    assert mcp_status["merged"] == cli_status["repository"]["merged"]
    assert mcp_status["unpushed"] == (cli_status["repository"]["ahead"] if cli_status["repository"]["ahead"] is not None else "?")
    assert mcp_status["context_percent"] == cli_status["telemetry"]["context_percent"]
    assert (mcp_status["cost_unit"] or "credit") == cli_status["telemetry"]["cost_unit"]
    assert (mcp_status["turns"] or 0) == cli_status["telemetry"]["turns"]
    assert (mcp_status["cost_total"] or 0) == (cli_status["telemetry"]["cost_total"] or 0)
    assert (mcp_status["cost_delegated"] or 0) == (cli_status["telemetry"]["cost_delegated"] or 0)
    assert mcp_status["nothing_to_do_since"] == cli_status["problems"]["nothing_to_do_since"]
    assert mcp_status["spinning_minutes"] == cli_status["problems"]["spinning_minutes"]
    assert mcp_status.get("push_guard") == (cli_status.get("push_guard") if mcp_status.get("push_guard") is not None else None)
    assert mcp_status["throughput"] == cli_status["throughput"]
    assert mcp_status["mailbox"] == cli_status["mail"]["waiting"]

    # Compare board against `polyctl board` and `polyctl board ready`
    assert cli.main(["-C", root, "board"]) == 0
    cli_board_text = capsys.readouterr().out
    assert "SLICE-MCP-1" in cli_board_text
    assert cli.main(["-C", root, "board", "ready"]) == 0
    cli_ready_lines = [line.strip() for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert mcp_board["ready"] == [line.split()[0] for line in cli_ready_lines if line.startswith("SLICE-")]
    assert "SLICE-MCP-1" in mcp_board["ready"]

    # Compare next against `polyctl next --json`
    assert cli.main(["-C", root, "next", "--json"]) == 0
    cli_next = json.loads(capsys.readouterr().out)
    assert mcp_next["project"] == cli_next["project"]
    assert mcp_next["items"] == cli_next["person"] + cli_next["implementer"]
    assert mcp_next["counts"] == {
        "person": len(cli_next["person"]),
        "implementer": len(cli_next["implementer"]),
    }

    # Compare mail inbox, ack, report, ask, and decisions against CLI
    assert mcp_inbox["count"] == 1
    msg_id = mcp_inbox["messages"][0]["id"]
    assert "Parity check body" in mcp_inbox["messages"][0]["body"]

    mut_resps = _rpc(
        monkeypatch,
        capsys,
        root,
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "polyctl_ack", "arguments": {"id": msg_id, "outcome": "applied"}},
            },
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "polyctl_inbox", "arguments": {}}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "polyctl_ask",
                    "arguments": {
                        "question": "Which scope?",
                        "options": ["local", "project"],
                        "slice": "SLICE-MCP-1",
                    },
                },
            },
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "polyctl_decisions", "arguments": {}}},
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "polyctl_report",
                    "arguments": {"kind": "status", "summary": "MCP parity verified"},
                },
            },
        ],
        "--role",
        "implementer",
    )
    mut_by_id = {r["id"]: r for r in mut_resps}
    ack_payload = json.loads(mut_by_id[1]["result"]["content"][0]["text"])
    assert ack_payload["acknowledged"] == msg_id
    inbox_after = json.loads(mut_by_id[2]["result"]["content"][0]["text"])
    assert inbox_after["count"] == 0
    mcp_ask = json.loads(mut_by_id[3]["result"]["content"][0]["text"])
    mcp_decisions = json.loads(mut_by_id[4]["result"]["content"][0]["text"])
    mcp_report = json.loads(mut_by_id[5]["result"]["content"][0]["text"])

    assert cli.main(["-C", root, "mail", "list", "--to", "architect"]) == 0
    cli_arch_mail = capsys.readouterr().out
    assert mcp_report["written"] in cli_arch_mail

    assert any(d["id"] == mcp_ask["id"] for d in mcp_decisions["decisions"])
    assert cli.main(["-C", root, "decisions"]) == 0
    cli_decisions_out = capsys.readouterr().out
    assert mcp_ask["id"] in cli_decisions_out and "Which scope?" in cli_decisions_out

    # 3. Verify reviewer role serves only read-only tools and matches staged candidate digest
    rev_resps = _rpc(
        monkeypatch,
        capsys,
        root,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "polyctl_candidate", "arguments": {}}},
        ],
        "--role",
        "reviewer",
    )
    rev_by_id = {r["id"]: r for r in rev_resps}
    assert [t["name"] for t in rev_by_id[1]["result"]["tools"]] == ["polyctl_status", "polyctl_board", "polyctl_candidate"]
    mcp_cand = json.loads(rev_by_id[2]["result"]["content"][0]["text"])
    expected_cand = A.index_candidate(root)
    assert mcp_cand["candidate"]["digest"] == expected_cand["digest"]
    assert mcp_cand["candidate"]["changed_paths"] == expected_cand["changed_paths"]


def test_playbook_rule_pointer_and_dogrulama_document_mcp_adoption(project):
    root = project["root"]
    # Verify register_mcp writes .mcp.json with --role for claude-code and skips antigravity (which has no mcp block)
    reg = skillkit.register_mcp(root, {"claude-code", "antigravity"}, exe="/usr/local/bin/polyctl")
    assert reg == {"claude-code": "registered"}
    mcp_json = json.loads(Path(root, ".mcp.json").read_text(encoding="utf-8"))
    assert mcp_json["mcpServers"]["polyctl"]["args"] == ["-C", root, "mcp", "serve", "--role", "architect"]
    agy_adapter = A.load_adapter("antigravity")
    assert "mcp" not in agy_adapter and agy_adapter["subcommands"]["mcp"] == ["agy", "mcp"]

    assert "polyctl_status" in skillkit.RULE_POINTER
    assert "polyctl_inbox" in skillkit.RULE_POINTER

    lines_claude = skillkit.next_steps({"claude-code"}, {"claude-code": "registered"})
    assert "restart" in lines_claude[0].lower() and "Claude Code" in lines_claude[0]
    assert "Approve the `.mcp.json` project server in Claude Code" in lines_claude[0]

    _, body = skillkit.playbook()
    for token in (
        "polyctl_status",
        "polyctl_board",
        "polyctl_next",
        "polyctl_candidate",
        "polyctl_inbox",
        "claude mcp add -s local",
        "agy mcp add",
        "run `polyctl init --no-mcp`",
    ):
        assert token in body

    dogrulama = Path(__file__).resolve().parents[1] / "docs" / "DOGRULAMA.md"
    assert dogrulama.is_file()
    text = dogrulama.read_text(encoding="utf-8")
    assert "Pending approval" in text
    assert "agy mcp add" in text
    assert "polyctl_status" in text and "polyctl_board" in text and "polyctl_inbox" in text
