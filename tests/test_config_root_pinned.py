"""A project's own config cannot point polyctl at another project.

``root`` is the directory ``load_config`` was given — where `.polyctl/config.json` was found,
or the directory `-C` named. A `root` key in that file is ignored. `secondary[].root` is a
different key and still names the other project.
"""
import json
import os
from types import SimpleNamespace

from polyctl import cli, lib as A, mcp


def _stored(root):
    with open(os.path.join(root, ".polyctl", "config.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _write(root, document):
    with open(os.path.join(root, ".polyctl", "config.json"), "w", encoding="utf-8") as fh:
        json.dump(document, fh)


def test_a_config_without_root_keeps_the_project_directory(project):
    root = project["root"]
    document = _stored(root)
    assert "root" not in document

    cfg = A.load_config(root)

    assert cfg["root"] == root
    assert "_config_notes" not in cfg
    assert cfg["mailbox"] == document["mailbox"]
    assert cfg["reviews"] == document["reviews"]


def test_a_root_key_naming_this_project_is_kept_quiet(project):
    root = project["root"]
    document = _stored(root)
    document["root"] = root
    _write(root, document)

    cfg = A.load_config(root)

    assert cfg["root"] == root
    assert "_config_notes" not in cfg


def test_a_foreign_root_is_ignored_and_doctor_says_so(project, tmp_path, capsys):
    root = project["root"]
    other = tmp_path / "not-this-project"
    (other / ".polyctl").mkdir(parents=True)
    (other / ".polyctl" / "config.json").write_text(
        json.dumps({"project": "not-this-project", "mailbox": "agent-mail", "reviews": "semantic-review"}),
        encoding="utf-8")
    document = _stored(root)
    document["root"] = str(other)
    _write(root, document)

    cfg = A.load_config(root)

    assert cfg["root"] == root
    assert cfg["project"] == "proj"
    assert cfg["_config_notes"] == ["config.json names root; ignored"]
    assert str(other) not in cfg["_config_notes"][0]
    facts = cli.status_facts(cfg, shown=False)
    assert facts["root"] == root and facts["project"] == "proj"
    assert str(other) not in facts["root"]
    # tests/test_mcp_adoption.py is not in this tree. polyctl_status returns status_payload.
    payload = mcp.status_payload(cfg)
    assert payload["root"] == root and payload["project"] == "proj"
    assert str(other) not in payload["root"]

    capsys.readouterr()
    cli.cmd_doctor(cfg, SimpleNamespace())
    out = capsys.readouterr().out
    assert any("config.json names root" in line and "ignored" in line for line in out.splitlines())
    assert str(other) not in out


def test_a_root_inside_the_project_is_named_relatively(project):
    root = project["root"]
    os.makedirs(os.path.join(root, "nested"))
    document = _stored(root)
    document["root"] = os.path.join(root, "nested")
    _write(root, document)

    cfg = A.load_config(root)

    assert cfg["root"] == root
    assert cfg["_config_notes"] == ["config.json names root nested; ignored"]
    assert os.path.join(root, "nested") not in cfg["_config_notes"][0]


def test_mailbox_and_reviews_still_default_when_the_file_omits_them(project):
    root = project["root"]
    document = _stored(root)
    document.pop("mailbox", None)
    document.pop("reviews", None)
    _write(root, document)

    cfg = A.load_config(root)

    assert cfg["root"] == root
    assert cfg["mailbox"] == "agent-mail"
    assert cfg["reviews"] == "semantic-review"
    assert "_config_notes" not in cfg


def test_a_secondary_entry_still_lists_its_project(project, tmp_path):
    root = project["root"]
    other = tmp_path / "polyctl-secondary"
    (other / ".polyctl").mkdir(parents=True)
    (other / ".polyctl" / "config.json").write_text(
        json.dumps({"project": "polyctl-secondary", "mailbox": "agent-mail", "reviews": "semantic-review",
                    "implementer": {"adapter": "kiro", "session": "s2", "name": "kiro"}}),
        encoding="utf-8")
    elsewhere = tmp_path / "not-this-project"
    elsewhere.mkdir()
    document = _stored(root)
    document["root"] = str(elsewhere)
    document["secondary"] = [{"root": str(other), "name": "polyctl"}]
    _write(root, document)

    cfg = A.load_config(root)
    found = A.secondary_projects(cfg)

    assert cfg["root"] == root
    assert [row["name"] for row in found] == ["polyctl"]
    assert os.path.realpath(found[0]["root"]) == os.path.realpath(other)
    assert os.path.realpath(found[0]["cfg"]["root"]) == os.path.realpath(other)
    assert str(elsewhere) not in " ".join(cfg.get("_config_notes") or [])
