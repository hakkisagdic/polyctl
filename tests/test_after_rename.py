"""What the mechanical rename (ao -> polyctl) could not carry (POLYCTL-AFTER-RENAME).

1. `pctl` runs `polyctl` as the short command in pyproject.toml (`[project.scripts]`), the wheel's
   entry points, an editable install, the Homebrew formula and `bin/polyctl.ps1`, with the same
   parser, exit codes and `--version` line, while help and error messages name the command the
   person typed; `poly` is not offered because a BlackArch tool already uses that name.
2. `CHANGELOG.md` opens `[Unreleased]` with the old name (`ao`, `ao-orchestrator` on PyPI,
   `github.com/hakkisagdic/agent-orchestrator`), and `README.md` and `README.tr.md` state the same
   in one sentence under the install section.
3. `README.md`, `README.tr.md` and `docs/windows.md` state the 0.7.0 platform support plainly near
   the top.
"""
import configparser
import glob
from importlib import metadata
import os
import pathlib
import re
import subprocess
import sys
import zipfile

import pytest

import polyctl
from polyctl import cli, lib as A

ROOT = pathlib.Path(__file__).resolve().parent.parent

OLD_NAME_SENTENCE = (
    "Until 0.7.0 polyctl was called ao, on PyPI ao-orchestrator, at "
    "github.com/hakkisagdic/agent-orchestrator (which GitHub now redirects); nothing of the old "
    "name is read any more - no command, variable, folder or format - and a project an older ao "
    "set up starts over with `polyctl init`."
)
PLATFORM_SENTENCE = (
    "polyctl 0.7.0 is built and supported on macOS; Linux runs the test suite in CI but is not a "
    "supported platform yet; on Windows 29 tests fail (WINDOWS-LANE-0.7, docs/backlog.md) and "
    "Windows waits for a later release."
)


def _project_scripts():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    body = text.split("\n[project.scripts]\n", 1)[1].split("\n[", 1)[0]
    scripts = {}
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, _, target = line.partition("=")
        scripts[name.strip()] = target.strip().strip('"')
    return scripts


def _build_backend():
    """Import hatchling.build or flit_core.buildapi from the environment or local wheel caches."""
    from tests import conftest
    extras = []
    for home in {conftest.REAL_HOME, os.path.expanduser("~")}:
        for pkg in ("hatchling", "pathspec", "pluggy", "packaging", "trove-classifiers", "editables"):
            extras.extend(sorted(glob.glob(os.path.join(home, ".cache", "uv", "wheels-v*", "pypi", pkg, "*-any"))))
    extras.extend(sorted(glob.glob("/opt/homebrew/Cellar/*/*/libexec/lib/python*/site-packages")))
    for path in extras:
        if path not in sys.path:
            sys.path.append(path)
    try:
        import hatchling.build as backend
        return backend
    except ImportError:
        try:
            import flit_core.buildapi as backend
            return backend
        except ImportError:
            return None


def _entry_points_from_wheel(wheel_path):
    with zipfile.ZipFile(wheel_path) as archive:
        [name] = [member for member in archive.namelist() if member.endswith(".dist-info/entry_points.txt")]
        parser = configparser.ConfigParser()
        parser.read_string(archive.read(name).decode("utf-8"))
        return {key: value.strip() for key, value in parser.items("console_scripts")}


def _write_console_script(path):
    path.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "from polyctl.cli import main\n"
        "sys.exit(main())\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def test_pyproject_wheel_and_editable_install_offer_pctl_beside_polyctl_and_never_poly(tmp_path, monkeypatch):
    scripts = _project_scripts()
    assert scripts["polyctl"] == "polyctl.cli:main"
    assert scripts["pctl"] == "polyctl.cli:main"
    assert "poly" not in scripts

    backend = _build_backend()
    if backend is not None:
        monkeypatch.chdir(ROOT)
        wheel_dir = tmp_path / "wheel"
        editable_dir = tmp_path / "editable_wheel"
        wheel_dir.mkdir()
        editable_dir.mkdir()

        wheel_name = backend.build_wheel(str(wheel_dir))
        editable_name = backend.build_editable(str(editable_dir))

        for built in (wheel_dir / wheel_name, editable_dir / editable_name):
            console = _entry_points_from_wheel(built)
            assert console["polyctl"] == "polyctl.cli:main"
            assert console["pctl"] == "polyctl.cli:main"
            assert "poly" not in console

        site_dir = tmp_path / "site-packages"
        with zipfile.ZipFile(editable_dir / editable_name) as archive:
            archive.extractall(site_dir)
        [dist] = list(metadata.distributions(path=[str(site_dir)]))
    else:
        dist = metadata.distribution("polyctl")

    ep_map = {ep.name: ep.value for ep in dist.entry_points if ep.group == "console_scripts"}
    assert ep_map["polyctl"] == "polyctl.cli:main"
    assert ep_map["pctl"] == "polyctl.cli:main"
    assert "poly" not in ep_map

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("polyctl", "pctl"):
        _write_console_script(bin_dir / name)

    env = A.self_child_env(os.environ)
    polyctl_ver = subprocess.run([sys.executable, str(bin_dir / "polyctl"), "--version"],
                                 capture_output=True, text=True, env=env, check=True)
    pctl_ver = subprocess.run([sys.executable, str(bin_dir / "pctl"), "--version"],
                              capture_output=True, text=True, env=env, check=True)
    assert polyctl_ver.stdout == pctl_ver.stdout == f"polyctl {polyctl.__version__}\n"

    pctl_help = subprocess.run([sys.executable, str(bin_dir / "pctl"), "--help"],
                               capture_output=True, text=True, env=env, check=True)
    polyctl_help = subprocess.run([sys.executable, str(bin_dir / "polyctl"), "--help"],
                                  capture_output=True, text=True, env=env, check=True)
    assert pctl_help.stdout.startswith("usage: pctl ")
    assert polyctl_help.stdout.startswith("usage: polyctl ")


def test_pctl_and_polyctl_share_the_version_line_and_name_the_typed_command_in_help_and_errors(project, tmp_path,
                                                                                               monkeypatch, capsys):
    outputs = {}
    for typed in ("polyctl", "pctl", "/usr/local/bin/pctl", "C:\\Scripts\\pctl.exe"):
        monkeypatch.setattr(sys, "argv", [typed])
        with pytest.raises(SystemExit) as stopped:
            cli.main(["--version"])
        assert stopped.value.code == 0
        outputs[typed] = capsys.readouterr().out.strip()
    assert set(outputs.values()) == {f"polyctl {polyctl.__version__}"}

    for typed in ("polyctl", "pctl"):
        monkeypatch.setattr(sys, "argv", [typed])
        assert cli.main([]) == 0
        assert capsys.readouterr().out.startswith(f"usage: {typed} ")

        with pytest.raises(SystemExit) as stopped:
            cli.main(["--help"])
        assert stopped.value.code == 0
        assert capsys.readouterr().out.startswith(f"usage: {typed} ")

        with pytest.raises(SystemExit) as stopped:
            cli.main(["status", "--help"])
        assert stopped.value.code == 0
        assert capsys.readouterr().out.startswith(f"usage: {typed} status")

        with pytest.raises(SystemExit) as stopped:
            cli.main(["--no-such-option"])
        assert stopped.value.code == 2
        err = capsys.readouterr().err
        assert f"usage: {typed} " in err and f"{typed}: error:" in err

        missing = tmp_path / "missing-root"
        with pytest.raises(SystemExit) as stopped:
            cli.main(["-C", str(missing), "status"])
        assert stopped.value.code == 2
        assert capsys.readouterr().err == f"{typed}: error: -C {missing}: no such directory\n"

    def broken(cfg, args):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "cmd_board", broken)
    monkeypatch.delenv("POLYCTL_DEBUG", raising=False)
    for typed in ("polyctl", "pctl"):
        monkeypatch.setattr(sys, "argv", [typed])
        assert cli.main(["-C", project["root"], "board"]) == 1
        assert capsys.readouterr().err.startswith(f"{typed} board: RuntimeError: boom")


def test_homebrew_formula_windows_wrapper_and_command_docs_offer_pctl():
    formula = (ROOT / "packaging" / "homebrew" / "polyctl.rb").read_text(encoding="utf-8")
    assert "pctl" in formula
    assert '#{bin}/pctl' in formula

    ps1 = (ROOT / "bin" / "polyctl.ps1").read_text(encoding="ascii")
    assert "Set-Alias -Name pctl" in ps1

    commands_en = (ROOT / "docs" / "commands.md").read_text(encoding="utf-8")
    commands_tr = (ROOT / "docs" / "commands.tr.md").read_text(encoding="utf-8")
    assert "`pctl`" in commands_en.splitlines()[2]
    assert "`pctl`" in commands_tr.splitlines()[2]


def test_changelog_and_readmes_state_the_old_name_once_and_the_platform_support_plainly():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = changelog.split("## [Unreleased]\n", 1)[1].split("\n## ", 1)[0].strip()
    assert unreleased.startswith(OLD_NAME_SENTENCE)
    assert unreleased.count("ao-orchestrator") == 1
    assert unreleased.count("github.com/hakkisagdic/agent-orchestrator") == 1

    readme_en = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_tr = (ROOT / "README.tr.md").read_text(encoding="utf-8")
    windows_doc = (ROOT / "docs" / "windows.md").read_text(encoding="utf-8")

    # Requirement 2: the old name, once, in one sentence under the install section.
    install_en = readme_en.split("## Install\n", 1)[1].split("\n## ", 1)[0]
    install_tr = readme_tr.split("## Kurulum\n", 1)[1].split("\n## ", 1)[0]
    assert OLD_NAME_SENTENCE in install_en
    assert readme_en.count("ao-orchestrator") == 1
    assert readme_en.count("github.com/hakkisagdic/agent-orchestrator") == 1
    for token in ("0.7.0", "ao", "ao-orchestrator", "github.com/hakkisagdic/agent-orchestrator", "`polyctl init`"):
        assert token in install_tr
    assert readme_tr.count("ao-orchestrator") == 1
    assert readme_tr.count("github.com/hakkisagdic/agent-orchestrator") == 1

    # Requirement 3: the platforms, said plainly near the top of README.md, README.tr.md and docs/windows.md.
    top_en = readme_en.split("\n## Why\n", 1)[0]
    top_tr = readme_tr.split("\n## Neden\n", 1)[0]
    assert PLATFORM_SENTENCE in top_en
    for token in ("polyctl 0.7.0", "macOS", "Linux", "29", "WINDOWS-LANE-0.7", "docs/backlog.md"):
        assert token in top_tr
    windows_first_paragraph = re.sub(r"^#\s+[^\n]+\n+", "", windows_doc).splitlines()[0].strip()
    assert windows_first_paragraph == PLATFORM_SENTENCE
