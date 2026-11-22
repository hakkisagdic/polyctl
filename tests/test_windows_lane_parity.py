"""The Windows lane runs the reviewer and authority tests the other lanes run (WINDOWS-LANE-PARITY).

Each of those tests started a stand-in harness - a reviewer, a kiro-cli, an agy, an opencode, the conformance
harness - through its shebang line, which Windows does not run, and polyctl knows a harness by the name of the program
it starts: eighteen tests were skipped on the Windows lane, and what they hold was held on Windows by nothing.
Every lane also ran Python in UTF-8 mode, which a Python a person installs on Windows does not run in.

tests/standin.py now writes a stand-in as a program on both: an executable script on POSIX, and on Windows
`<name>.exe`, as pip writes a console script there - distlib's console launcher, a line naming this interpreter,
and the script as `__main__.py` in a zip after them. The launcher runs only on Windows; what it hands the
interpreter - the file itself, which Python runs as a zip application - runs on every platform, and is run here.
The workflow has no schedule and no Windows or macOS lane: such a run is started by hand from a branch that adds
it (the owner's Actions decision of 22 Nov 2026), and every lane's log lists what it skipped and why. The
Python 3.9 Ubuntu legs run on ubuntu-24.04 after ubuntu-latest moved to Ubuntu 26.04, which has no 3.9 build at
actions/setup-python (CI-UBUNTU-39).
"""
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests import standin

ROOT = Path(__file__).resolve().parent.parent
SOURCE = "import sys\nprint('ran', sys.argv[1:])\n"
# The tests still skipped on Windows for a script its shebang runs, and why each is: the fake gh of `polyctl pr watch`
# and of the watchdog cycle that runs it is no reviewer's or authority's harness and is not yet a program, and the
# suite's own test of the python it puts on PATH for such scripts, which it puts there on POSIX alone.
STILL_BY_SHEBANG = {"test_pr_watch.py", "test_pr_watch_cycle.py", "test_suite_isolation.py"}


# ---- a stand-in is a program ---------------------------------------------------------------------------

def test_a_stand_in_is_a_program_started_by_its_own_name(tmp_path):
    path = standin.program(tmp_path, "agy", SOURCE)

    assert os.path.basename(path) == ("agy.exe" if os.name == "nt" else "agy")
    done = subprocess.run([path, "--print=review this", "--output-format=json"], capture_output=True, text=True,
                          timeout=60)
    assert (done.returncode, done.stdout.strip()) == (0, "ran ['--print=review this', '--output-format=json']"), \
        done.stderr


def test_on_windows_it_is_the_launcher_then_this_interpreter_then_the_script_as_a_zip(tmp_path, monkeypatch):
    # pip's own launcher where this Python's pip holds one, as it does on every platform; else bytes in its place.
    launcher = standin._launcher() or b"MZ, a launcher"
    monkeypatch.setattr(standin, "_launcher", lambda: launcher)
    with monkeypatch.context() as patch:
        patch.setattr(os, "name", "nt")
        path = standin.program(tmp_path, "agy", SOURCE)

    assert path == os.path.join(str(tmp_path), "agy.exe")
    interpreter = f'"{sys.executable}"' if " " in sys.executable else sys.executable
    with open(path, "rb") as fh:
        assert fh.read().startswith(launcher + b"#!" + interpreter.encode("utf-8") + b"\n")
    # What the launcher hands the interpreter: its own file, which Python runs as a zip application.
    done = subprocess.run([sys.executable, path, "--print=review this"], capture_output=True, text=True, timeout=60)
    assert (done.returncode, done.stdout.strip()) == (0, "ran ['--print=review this']"), done.stderr


def test_a_windows_without_a_launcher_skips_the_test_and_says_why(tmp_path, monkeypatch):
    monkeypatch.setattr(standin, "_launcher", lambda: None)
    with monkeypatch.context() as patch:
        patch.setattr(os, "name", "nt")
        with pytest.raises(pytest.skip.Exception, match="pip's console launcher"):
            standin.program(tmp_path, "agy", SOURCE)

    assert os.listdir(str(tmp_path)) == []


def test_a_stand_in_written_again_as_it_is_is_left_alone_and_a_changed_one_is_written(tmp_path, monkeypatch):
    # Windows may still hold a program that has just run, so the same program is not written over itself.
    launcher = standin._launcher() or b"MZ, a launcher"
    monkeypatch.setattr(standin, "_launcher", lambda: launcher)
    for platform in ("posix", "nt"):
        with monkeypatch.context() as patch:
            patch.setattr(os, "name", platform)
            path = standin.program(tmp_path, "harness", SOURCE)
            os.utime(path, (1_000_000_000, 1_000_000_000))
            assert standin.program(tmp_path, "harness", SOURCE) == path
            assert int(os.stat(path).st_mtime) == 1_000_000_000
            assert standin.program(tmp_path, "harness", SOURCE + "print('more')\n") == path
            assert int(os.stat(path).st_mtime) != 1_000_000_000


# ---- the lane: what it skips it says, and one leg runs as a default install does ---------------------------

def _skip_reasons(path):
    """The reason of every skip a test module makes, as its source writes it; a name stands for its constant."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    constants = {target.id: node.value.value for node in tree.body if isinstance(node, ast.Assign)
                 and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
                 for target in node.targets if isinstance(target, ast.Name)}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("skipif", "skip"):
            for value in [keyword.value for keyword in node.keywords if keyword.arg == "reason"] + node.args[:1]:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    found.append(value.value)
                elif isinstance(value, ast.Name) and value.id in constants:
                    found.append(constants[value.id])
    return found


def test_no_reviewer_or_authority_test_is_skipped_on_windows_for_a_script_its_shebang_runs():
    by_shebang = {path.name for path in sorted((ROOT / "tests").glob("test_*.py"))
                  if any("shebang" in reason for reason in _skip_reasons(path))}

    assert by_shebang == STILL_BY_SHEBANG, "write the stand-in with tests/standin.py, which makes it a program on " \
                                           "Windows too, or name here why the test cannot run there"


def _job_text(workflow, name):
    """The text of one job in a workflow file, bounded by indentation."""
    after = workflow.split(f"\n  {name}:\n", 1)[1].splitlines()
    end = next((index for index, line in enumerate(after) if re.match(r"  \S", line)), len(after))
    return "\n".join(after[:end])


def _gh_eval(expr, **contexts):
    """Evaluate a GitHub Actions ${{ ... }} expression against named contexts (inputs, matrix)."""
    py_expr = expr.replace("&&", " and ").replace("||", " or ")

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            return contexts[node.value.id][node.attr]
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
            left, right = walk(node.left), walk(node.comparators[0])
            return left == right if isinstance(node.ops[0], ast.Eq) else left != right
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                value = True
                for part in node.values:
                    value = walk(part)
                    if not value:
                        return value
                return value
            value = False
            for part in node.values:
                value = walk(part)
                if value:
                    return value
            return value
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            args = [walk(arg) for arg in node.args]
            if node.func.id == "fromJSON":
                return json.loads(args[0])
            if node.func.id == "format":
                return args[0].format(*args[1:])
        raise AssertionError(f"unsupported workflow expression node: {ast.dump(node)}")

    return walk(ast.parse(py_expr, mode="eval"))


def _gh_render(template, **contexts):
    """Render a workflow field containing one or more ${{ ... }} expressions."""
    whole = re.fullmatch(r"\$\{\{\s*((?:(?!\}\}).)*?)\s*\}\}", template.strip())
    if whole:
        value = _gh_eval(whole.group(1), **contexts)
        if not isinstance(value, str):
            return value
    return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", lambda match: str(_gh_eval(match.group(1), **contexts)), template.strip())


def _job_field(job, field):
    return re.search(rf"^\s+{re.escape(field)}:\s*(.+?)\s*(?:#.*)?$", job, re.M).group(1).strip('"')


def test_every_lane_lists_what_it_skipped():
    """The one test workflow runs every lane with -rs, so a skip names its reason (no weekly or on-demand lanes)."""
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    assert "schedule:" not in workflow and "workflow_dispatch" not in workflow
    runs = re.findall(r"^\s+- run: (python -m pytest.*)$", workflow, re.M)
    assert len(runs) == 1 and runs[0] == "python -m pytest -q -rs", runs


def test_python_39_ubuntu_lanes_run_on_an_image_with_a_39_build_and_never_on_ubuntu_latest():
    """ubuntu-latest moved to Ubuntu 26.04, which has no Python 3.9 build at actions/setup-python (CI-UBUNTU-39)."""
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    header = workflow.split("\non:\n", 1)[0]
    assert "Ubuntu 26.04" in header and "ubuntu-24.04" in header and "retired" in header

    ubuntu = _job_text(workflow, "ubuntu")
    assert not re.search(r"^\s+python:\s*\[", ubuntu, re.M)
    include = [{"os": os_name, "python": py}
               for os_name, py in re.findall(r"^\s+- os:\s*(\S+)\n\s+python:\s*\"([^\"]+)\"", ubuntu, re.M)]
    ubuntu_legs = [(_gh_render(_job_field(ubuntu, "name"), matrix=leg),
                    _gh_render(_job_field(ubuntu, "runs-on"), matrix=leg),
                    _gh_render(_job_field(ubuntu, "python-version"), matrix=leg)) for leg in include]
    assert ubuntu_legs == [
        ("ubuntu-24.04 / Python 3.9", "ubuntu-24.04", "3.9"),
        ("ubuntu-latest / Python 3.12", "ubuntu-latest", "3.12"),
    ]
