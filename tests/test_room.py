import json
import os
from types import SimpleNamespace
import polyctl.cli as cli
import polyctl.lib as A


def _make_governed(tmp_path, name, arch="architect", impl="implementer"):
    root = tmp_path / name
    (root / ".polyctl" / "ledger").mkdir(parents=True)
    (root / "agent-mail").mkdir()
    cfg = {
        "root": str(root),
        "mailbox": "agent-mail",
        "architect": {"id": "claude-code", "name": arch, "cmd": "claude"},
        "implementer": {"id": "kiro-cli", "name": impl, "cmd": "kiro-cli"},
        "reviewer": {"id": "codex", "name": "reviewer"},
    }
    (root / ".polyctl" / "config.json").write_text(
        json.dumps({k: v for k, v in cfg.items() if k != "root"}), encoding="utf-8"
    )
    A.project_key(str(root))
    return str(root), cfg


def test_room_search_covers_pending_and_consumed_mail_across_registered_projects(tmp_path, monkeypatch, capsys):
    alpha_root, alpha_cfg = _make_governed(tmp_path, "alpha")
    beta_root, beta_cfg = _make_governed(tmp_path, "beta")

    cli.cmd_mail(
        alpha_cfg,
        SimpleNamespace(
            action="send",
            type="INFO",
            topic="quota",
            body="Check capacity reservation quota",
            mail_class=None,
            mail_from=None,
            mail_to=None,
            allow_empty=False,
        ),
    )
    capsys.readouterr()

    cli.cmd_mail(alpha_cfg, SimpleNamespace(action="list", mail_from=None, mail_to=None))
    listed = capsys.readouterr().out
    assert "INFO-quota.md" in listed

    consumed_name = A.write_mail(
        beta_root,
        beta_cfg,
        "20261019-1200-architect-to-implementer-DECISION-quota.md",
        "# Capacity reservation quota aligned\n\nCapacity reservation quota is settled.\n",
        {"kind": "decision", "from": "architect", "to": "implementer", "slice": "S1"},
    )
    monkeypatch.setenv("POLYCTL_ROLE", "implementer")
    assert cli.cmd_mail(beta_cfg, SimpleNamespace(action="ack", type=consumed_name, body="done")) in (0, None)
    monkeypatch.delenv("POLYCTL_ROLE", raising=False)
    capsys.readouterr()

    hits = A.room_search("capacity reservation", root=alpha_root)
    by_proj = {row["project"]: row for row in hits}
    assert set(by_proj) == {"alpha", "beta"}
    assert by_proj["alpha"]["state"] == "pending"
    assert by_proj["beta"]["state"] == "consumed"

    cli.cmd_room(alpha_cfg, SimpleNamespace(room_action="search", text="capacity reservation", limit=20))
    out = capsys.readouterr().out
    assert "no stored message mentions that" not in out
    assert "alpha" in out and "pending" in out
    assert "beta" in out and "consumed" in out


def test_room_search_streams_pending_mail_past_64_kib(tmp_path):
    alpha_root, _ = _make_governed(tmp_path, "alpha")
    pending = os.path.join(
        alpha_root, "agent-mail", "20261019-1300-architect-to-implementer-NOTE-huge.md"
    )
    prefix = "---\nfrom: architect\nto: implementer\nkind: note\n---\n\n# Oversized pending note\n\nhead-token\n"
    filler = "x" * 70_000
    with open(pending, "w", encoding="utf-8") as fh:
        fh.write(prefix + filler + "\ntail-beyond-bound\n")

    assert getattr(A, "ROOM_SEARCH_MAX_BYTES", None) == 65_536
    head_hits = A.room_search("head-token", root=alpha_root)
    assert len(head_hits) == 1
    assert head_hits[0]["summary"] == "Oversized pending note"
    tail_hits = A.room_search("tail-beyond-bound", root=alpha_root)
    assert len(tail_hits) == 1
    assert tail_hits[0]["id"] == "20261019-1300-architect-to-implementer-NOTE-huge.md"
