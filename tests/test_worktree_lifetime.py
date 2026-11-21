import glob
import json
import os
import subprocess
import time
from types import SimpleNamespace

from polyctl import cli, lib as A


def _git(cwd, *args):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def _worktree(root, tmp_path, name):
    path = tmp_path / name
    _git(root, "worktree", "add", "-q", "-b", name, str(path))
    (path / f"{name}.txt").write_text(name, encoding="utf-8")
    _git(path, "add", f"{name}.txt")
    _git(path, "commit", "-q", "-m", name)
    return path


def test_merged_and_rejected_worktrees_go_while_dirty_and_reviewed_ones_stay(project, tmp_path, capsys):
    root = project["root"]
    merged, dirty, reviewed, rejected = (_worktree(root, tmp_path, name)
                                         for name in ("merged", "dirty", "reviewed", "rejected"))
    for name in ("merged", "dirty", "reviewed"):
        _git(root, "merge", "-q", "--no-ff", "--no-edit", name)
    (dirty / "dirty.txt").write_text("changed, never committed", encoding="utf-8")
    (reviewed / ".polyctl" / "reviews").mkdir(parents=True)
    with open(reviewed / ".polyctl" / "reviews" / "R-1.json", "w", encoding="utf-8") as fh:
        json.dump({"id": "R-1", "state": "running", "pid": os.getpid(), "submitted_at": int(time.time())}, fh)
    (merged / ".polyctl").mkdir()
    (merged / ".polyctl" / "notes.jsonl").write_text('{"kept": true}\n', encoding="utf-8")
    rejected_head = _git(rejected, "rev-parse", "HEAD")
    with open(os.path.join(root, ".polyctl", "board.md"), "a", encoding="utf-8") as fh:
        fh.write(f"\n## rejected\n- [ABN] an abandoned slice · worktree: {rejected}\n")

    assert cli.cmd_worktrees(project, SimpleNamespace(action="prune", yes=False)) == 0
    assert merged.exists() and rejected.exists()

    assert cli.cmd_worktrees(project, SimpleNamespace(action="prune", yes=True)) == 0

    assert not merged.exists() and not rejected.exists()
    assert dirty.exists() and reviewed.exists()
    left = {os.path.realpath(fact["path"]) for fact in A.worktree_list(root)}
    assert left == {os.path.realpath(p) for p in (root, dirty, reviewed)}
    branches = _git(root, "branch", "--format=%(refname:short)").split()
    assert "merged" not in branches and "rejected" not in branches and "dirty" in branches
    archived = _git(root, "for-each-ref", "--format=%(objectname)", "refs/polyctl/archive/")
    assert rejected_head in archived.split()
    kept = glob.glob(os.path.join(A.HOME, ".polyctl", "archive", A.project_key(root), "worktree-merged-*", ".polyctl",
                                  "notes.jsonl"))
    assert len(kept) == 1
    out = capsys.readouterr().out
    assert "1 uncommitted product change(s)" in out and "review in flight: R-1" in out


def test_a_worktree_whose_directory_was_deleted_by_hand_goes_with_its_branch(project, tmp_path, capsys):
    import shutil
    root = project["root"]
    gone = _worktree(root, tmp_path, "gone")
    head = _git(gone, "rev-parse", "HEAD")
    shutil.rmtree(gone)                 # git still lists it, and would not delete a branch it lists as checked out

    assert cli.cmd_worktrees(project, SimpleNamespace(action="prune", yes=True)) == 0

    assert "its directory is gone" in capsys.readouterr().out
    assert "gone" not in _git(root, "branch", "--format=%(refname:short)").split()
    assert len(A.worktree_list(root)) == 1
    assert head in _git(root, "for-each-ref", "--format=%(objectname)", "refs/polyctl/archive/").split()


def _merged(root, tmp_path, name="merged"):
    path = _worktree(root, tmp_path, name)
    _git(root, "merge", "-q", "--no-ff", "--no-edit", name)
    return path


def _archive_hits(root, pattern):
    return glob.glob(os.path.join(A.HOME, ".polyctl", "archive", A.project_key(root), pattern))


def test_prune_archives_an_untracked_mailbox_file_before_the_worktree_goes(project, tmp_path, capsys):
    root = project["root"]
    merged = _merged(root, tmp_path)
    mail = merged / "agent-mail"
    mail.mkdir()
    body = b"keep this mailbox note byte for byte\n"
    note = mail / "note.md"
    note.write_bytes(body)
    expected = tmp_path / "expected-note.md"
    expected.write_bytes(body)

    assert cli.cmd_worktrees(project, SimpleNamespace(action="prune", yes=True)) == 0

    assert not merged.exists()
    assert os.path.isdir(os.path.join(root, "agent-mail"))
    kept = _archive_hits(root, "worktree-merged-*/agent-mail/note.md")
    assert len(kept) == 1 and kept[0].startswith(str(tmp_path))
    with open(kept[0], "rb") as fh:
        assert fh.read() == body
    diff = subprocess.run(["diff", str(expected), kept[0]], capture_output=True)
    assert diff.returncode == 0 and diff.stdout == b""


def test_prune_dry_run_lists_the_mailbox_archive_and_copies_nothing(project, tmp_path, capsys):
    root = project["root"]
    merged = _merged(root, tmp_path)
    mail = merged / "agent-mail"
    mail.mkdir()
    body = b"still in the worktree\n"
    note = mail / "note.md"
    note.write_bytes(body)

    assert cli.cmd_worktrees(project, SimpleNamespace(action="prune", yes=False)) == 0

    out = capsys.readouterr().out
    assert "archive agent-mail/ to " in out
    assert "would: archive agent-mail/ to " in out
    assert merged.exists() and note.read_bytes() == body
    assert "merged" in _git(root, "branch", "--format=%(refname:short)").split()
    assert not os.path.isdir(os.path.join(A.HOME, ".polyctl", "archive"))


def test_prune_archives_nothing_outside_when_the_mailbox_name_leaves_the_worktree(project, tmp_path, capsys):
    root = project["root"]
    merged = _merged(root, tmp_path)
    cfg_path = os.path.join(root, ".polyctl", "config.json")
    with open(cfg_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg["mailbox"] = "../x"
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    project["mailbox"] = "../x"
    outside = tmp_path / "x"
    outside.mkdir()
    marker = outside / "secret.md"
    body = b"outside the worktree\n"
    marker.write_bytes(body)

    assert cli.cmd_worktrees(project, SimpleNamespace(action="prune", yes=True)) == 0

    out = capsys.readouterr().out
    assert "archive nothing for mailbox ../x: the mailbox name leaves the worktree" in out
    assert not merged.exists()
    assert marker.read_bytes() == body
    found = []
    for dirpath, dirnames, files in os.walk(tmp_path):
        dirnames[:] = [name for name in dirnames if not os.path.islink(os.path.join(dirpath, name))]
        for name in files:
            path = os.path.join(dirpath, name)
            if os.path.islink(path):
                continue
            with open(path, "rb") as fh:
                if fh.read() == body:
                    found.append(os.path.realpath(path))
    assert found == [os.path.realpath(marker)]


def test_prune_without_a_mailbox_folder_still_archives_polyctl_and_removes_the_worktree(project, tmp_path, capsys):
    root = project["root"]
    merged = _merged(root, tmp_path)
    (merged / ".polyctl").mkdir()
    (merged / ".polyctl" / "notes.jsonl").write_text('{"kept": true}\n', encoding="utf-8")
    assert not (merged / "agent-mail").exists()

    assert cli.cmd_worktrees(project, SimpleNamespace(action="prune", yes=True)) == 0

    assert not merged.exists()
    out = capsys.readouterr().out
    assert "archive .polyctl/ to " in out
    assert "archive agent-mail/" not in out and "archive nothing for mailbox" not in out
    kept = _archive_hits(root, "worktree-merged-*/.polyctl/notes.jsonl")
    assert len(kept) == 1 and open(kept[0], encoding="utf-8").read() == '{"kept": true}\n'
    assert _archive_hits(root, "worktree-merged-*/agent-mail") == []
    assert "merged" not in _git(root, "branch", "--format=%(refname:short)").split()


def test_the_doctor_names_worktrees_that_may_go_with_their_size(project, tmp_path):
    root = project["root"]
    _worktree(root, tmp_path, "landed")
    _git(root, "merge", "-q", "--no-ff", "--no-edit", "landed")

    text = "\n".join(cli._worktree_lines(project))

    # Git names a worktree with forward slashes on every platform.
    assert "1 may go" in text and "merged into" in text and str(tmp_path / "landed").replace(os.sep, "/") in text
