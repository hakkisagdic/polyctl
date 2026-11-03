"""A release is made from a version tag on main, by actions pinned to commits (RELEASE-PINNED).

The bug hunter's first run read .github/workflows/release.yml and named two leads. The workflow can be dispatched
on any ref, and its one check compared the ref's name with the packaged version: a branch named like a version
passed it, that branch's code was published to PyPI, and `gh release create` then tagged main's head with the
name - a release no tag reproduces. And the publishing job ran pypa/gh-action-pypi-publish by its branch
release/v1, beside the OIDC token PyPI trusts: whoever moves that branch chooses the code that holds the token.
Every workflow named its actions by tags, which can be moved as a branch can.

So the build refuses a ref that is not a tag and a tag on a commit main does not hold, the publishing jobs run
for a tag alone, and every action every workflow uses is named by a commit, its release written beside it.

The v0.7.0 release run (41642398467) failed before it built anything because release.yml's tests job ran Python 3.9
on ubuntu-latest (now Ubuntu 26.04, where actions/setup-python has no 3.9 build) after tests.yml had already moved
its 3.9 Ubuntu legs to ubuntu-24.04 (CI-UBUNTU-39); the 3.12 leg was cancelled by fail-fast and nothing was
published. release.yml now runs its 3.9 leg on ubuntu-24.04 and its 3.12 leg on ubuntu-latest, and no job in
.github/workflows/*.yml may set up Python 3.9 on ubuntu-latest (RELEASE-PY39-IMAGE).
"""
import itertools
import os
import re
import subprocess

import pytest

from tests.test_github_action import _bash, _scripts
from tests.test_windows_lane_parity import _gh_render

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS = os.path.join(ROOT, ".github", "workflows")
RELEASE = os.path.join(WORKFLOWS, "release.yml")


def _text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _job(text, name):
    """The lines of one job of a workflow, read by its indentation."""
    lines = text.split("\n  " + name + ":\n", 1)[1].splitlines()
    return [line for line in lines[:next((at for at, line in enumerate(lines) if re.match(r"  \S", line)),
                                         len(lines))]]


def test_every_action_every_workflow_uses_is_named_by_a_commit_with_its_release_beside_it():
    names = sorted(name for name in os.listdir(WORKFLOWS) if name.endswith((".yml", ".yaml")))
    uses = [(name, line.strip()) for name in names for line in _text(os.path.join(WORKFLOWS, name)).splitlines()
            if re.match(r"\s*(- )?uses:", line)]

    assert names and len(uses) >= 20
    unpinned = [(name, line) for name, line in uses
                if not re.fullmatch(r"(- )?uses: [\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d+(\.\d+)*", line)]
    assert unpinned == []


def test_the_jobs_that_publish_run_for_a_tag_alone():
    text = _text(RELEASE)

    for job in ("pypi", "github-release"):
        assert "    if: github.ref_type == 'tag'" in _job(text, job), job
    assert "id-token: write" in "\n".join(_job(text, "pypi"))


def _input_contexts(text):
    """Every combination of workflow_dispatch choice inputs a workflow defines, or [{}] when it defines none."""
    options = {match.group(1): [item.strip().strip("'\"") for item in match.group(2).split(",") if item.strip()]
               for match in re.finditer(r"^      ([\w-]+):\n(?:        .+\n)*?        options:\s*\[([^\]]+)\]",
                                        text, re.M)}
    if not options:
        return [{}]
    keys = list(options)
    return [dict(zip(keys, values)) for values in itertools.product(*(options[key] for key in keys))]


def _job_matrices(uncommented, inputs):
    """Every matrix dictionary a job's `matrix:` block expands to under `inputs`, or [{}] without a matrix."""
    if "\n      matrix:\n" not in uncommented:
        return [{}]
    after = uncommented.split("\n      matrix:\n", 1)[1].splitlines()
    block = "\n".join(after[:next((at for at, line in enumerate(after) if re.match(r" {0,6}\S", line)), len(after))])
    included = []
    if re.search(r"^        include:\s*$", block, re.M):
        inc_part = re.split(r"^        include:\s*$", block, maxsplit=1, flags=re.M)[1]
        for chunk in re.split(r"(?m)^          - ", inc_part)[1:]:
            included.append({key: val.strip().strip("'\"")
                             for key, val in re.findall(r"^\s*([\w-]+):\s*(.+)$", chunk, re.M)})
        block = re.split(r"^        include:\s*$", block, maxsplit=1, flags=re.M)[0]
    axes = {}
    for key, raw in re.findall(r"^        ([\w-]+):\s*(.+)$", block, re.M):
        raw = raw.strip()
        if raw.startswith("[") and raw.endswith("]"):
            axes[key] = [item.strip().strip("'\"") for item in raw[1:-1].split(",") if item.strip()]
        else:
            rendered = _gh_render(raw, inputs=inputs)
            axes[key] = rendered if isinstance(rendered, list) else [str(rendered)]
    crossed = ([dict(zip(axes, values)) for values in itertools.product(*(axes[key] for key in axes))]
               if axes else [])
    return crossed + included or [{}]


def _workflow_python_legs(text):
    """(job, runs_on, python_version) for every leg of every job in `text` that sets up Python."""
    inputs_all = _input_contexts(text)
    names = [match.group(1) for match in re.finditer(r"^  ([\w-]+):\s*$", text.split("\njobs:\n", 1)[1], re.M)]
    legs = []
    for job in names:
        lines = _job(text, job)
        uncommented = "\n".join(line.split("#", 1)[0].rstrip() for line in lines
                                if not line.lstrip().startswith("#"))
        py_versions = [next(group for group in match.groups() if group is not None).strip()
                       for match in re.finditer(
                           r"python-version:\s*(?:'([^']+)'|\"([^\"]+)\"|(\$\{\{.*?\}\})|([^\s}#]+))", uncommented)]
        if not py_versions and "actions/setup-python" not in uncommented:
            continue
        assert py_versions, f"{job} uses setup-python without python-version"
        runs_on_tpl = re.search(r"^\s+runs-on:\s*(.+)$", uncommented, re.M).group(1).strip().strip("'\"")
        for inputs in (inputs_all if "inputs." in uncommented else [{}]):
            for matrix in _job_matrices(uncommented, inputs):
                runs_on = str(_gh_render(runs_on_tpl, inputs=inputs, matrix=matrix))
                for py_tpl in py_versions:
                    py = str(_gh_render(py_tpl, inputs=inputs, matrix=matrix))
                    if (job, runs_on, py) not in legs:
                        legs.append((job, runs_on, py))
    return legs


def test_no_workflow_job_sets_up_python_39_on_ubuntu_latest():
    """ubuntu-latest is Ubuntu 26.04, which has no Python 3.9 build at actions/setup-python (RELEASE-PY39-IMAGE)."""
    names = sorted(name for name in os.listdir(WORKFLOWS) if name.endswith((".yml", ".yaml")))
    legs = [(name, job, runs_on, py)
            for name in names
            for job, runs_on, py in _workflow_python_legs(_text(os.path.join(WORKFLOWS, name)))]

    assert [leg for leg in legs if leg[3] == "3.9"]
    assert [leg for leg in legs if leg[2] == "ubuntu-latest" and (leg[3] == "3.9" or leg[3].startswith("3.9."))] == []

    release = _text(RELEASE)
    tests_job = "\n".join(_job(release, "tests"))
    assert "Ubuntu 26.04" in tests_job and "ubuntu-24.04" in tests_job
    assert "      fail-fast: true" in tests_job
    assert "    runs-on: ${{ matrix.os }}" in tests_job
    assert "    timeout-minutes: 40" in tests_job
    assert _workflow_python_legs(release) == [
        ("tests", "ubuntu-24.04", "3.9"),
        ("tests", "ubuntu-latest", "3.12"),
        ("build", "ubuntu-latest", "3.12"),
    ]
    for job in ("build", "pypi", "github-release"):
        assert "    runs-on: ubuntu-latest" in _job(release, job), job

    drifted = release.replace(
        "        include:\n          - os: ubuntu-24.04\n            python: '3.9'\n"
        "          - os: ubuntu-latest\n            python: '3.12'\n    runs-on: ${{ matrix.os }}",
        "        python: ['3.9', '3.12']\n    runs-on: ubuntu-latest",
    )
    assert drifted != release and ("tests", "ubuntu-latest", "3.9") in _workflow_python_legs(drifted)


@pytest.fixture
def repository(tmp_path):
    """(path, main's commit, a commit main does not hold): a clone as the build checks it out, main fetched."""
    path = str(tmp_path / "clone")
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", path], check=True)
    commits = []
    for name in ("on-main", "elsewhere"):
        with open(os.path.join(path, name), "w", encoding="utf-8") as fh:
            fh.write(name + "\n")
        subprocess.run(git + ["add", name], cwd=path, check=True)
        subprocess.run(git + ["commit", "-q", "-m", name], cwd=path, check=True)
        commits.append(subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True,
                                      check=True).stdout.strip())
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", commits[0]], cwd=path, check=True)
    return path, commits[0], commits[1]


@pytest.mark.skipif(not _bash(), reason="the workflow's steps are bash scripts, and there is no bash here to run one")
def test_the_build_refuses_a_branch_and_a_tag_on_a_commit_main_does_not_hold(repository):
    path, on_main, elsewhere = repository
    (guard,) = [script for script in _scripts(_text(RELEASE)) if "merge-base --is-ancestor" in script]
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}

    def build(kind, sha):
        ref = ("refs/tags/" if kind == "tag" else "refs/heads/") + "v0.5.3"
        return subprocess.run([_bash(), "--noprofile", "--norc", "-e", "-c", guard], cwd=path, capture_output=True,
                              text=True, encoding="utf-8", env=dict(env, GITHUB_REF_TYPE=kind, GITHUB_REF=ref,
                                                                    GITHUB_REF_NAME="v0.5.3", GITHUB_SHA=sha))

    branch, outside, tagged = build("branch", on_main), build("tag", elsewhere), build("tag", on_main)

    assert branch.returncode == 1 and "refs/heads/v0.5.3 is a branch" in branch.stderr
    assert outside.returncode == 1 and f"tags {elsewhere}, which main does not hold" in outside.stderr
    assert tagged.returncode == 0, tagged.stderr
