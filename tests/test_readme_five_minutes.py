"""Both READMEs' five-minute install block leads with `polyctl start` (polyctl-giris-yolu).

The wizard is the first polyctl command in that block. `polyctl init --profile` stays
on the next line, marked by hand in English and elle in Turkish, with the same command
order in both files. Those profile names are the presets in profiles.json and
docs/profiles.md, and each role's adapter ships in the package. The document-wide
parser scan stays in tests/test_docs_commands.py; docs/getting-started.md stays with
tests/test_prove.py.
"""
import contextlib
import io
import json
import shlex
from pathlib import Path

from polyctl import cli

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ("agy-codex", "codex-agy", "claude-codex")
INSTALL = (
    "pip install polyctl",
    "cd {checkout}",
    "polyctl start",
    "polyctl init --profile agy-codex",
    'git add .polyctl-project .gitignore && git commit -m "adopt polyctl"',
    "polyctl hooks install",
)


def _text(name):
    return (ROOT / name).read_text(encoding="utf-8")


def _section(text, heading):
    start = text.index("\n" + heading + "\n")
    rest = text[start + 1:]
    end = rest.find("\n## ")
    return rest if end == -1 else rest[:end]


def _bash_blocks(section):
    lines, blocks, i = section.splitlines(), [], 0
    while i < len(lines):
        if lines[i].strip() == "```bash":
            i += 1
            body = []
            while i < len(lines) and not lines[i].startswith("```"):
                body.append(lines[i])
                i += 1
            blocks.append(body)
        i += 1
    return blocks


def _commands(body):
    found = []
    for line in body:
        code, sep, comment = line.partition("#")
        code = code.strip()
        if code:
            found.append((code, comment.strip() if sep else ""))
    return found


def _install(readme, heading):
    blocks = _bash_blocks(_section(_text(readme), heading))
    assert blocks, readme
    return _commands(blocks[0])


def _profile_order(text):
    return [name for name in sorted(PROFILES, key=text.find) if name in text]


def _accepts(command):
    words = shlex.split(command)
    assert words[0] == "polyctl", command
    buffer = io.StringIO()
    try:
        with contextlib.redirect_stderr(buffer):
            cli.build_parser().parse_args(words[1:])
    except SystemExit as exc:
        raise AssertionError("%s: %s %s" % (command, exc, buffer.getvalue())) from exc


def test_both_readmes_lead_the_five_minute_install_block_with_the_wizard():
    en = _install("README.md", "## Five minutes to the first reviewed commit")
    tr = _install("README.tr.md", "## İlk gözden geçirilmiş commit'e beş dakika")

    assert [code for code, _ in en] == [line.format(checkout="your-repository") for line in INSTALL]
    assert [code for code, _ in tr] == [line.format(checkout="deponun-yolu") for line in INSTALL]
    assert [code for code, _ in en if code.startswith("polyctl")] == \
        [code for code, _ in tr if code.startswith("polyctl")]
    assert en[2][0] == "polyctl start" and tr[2][0] == "polyctl start"
    assert "by hand" in en[3][1]
    assert "elle" in tr[3][1]
    assert _profile_order(en[3][0] + " " + en[3][1]) == list(PROFILES)
    assert _profile_order(tr[3][0] + " " + tr[3][1]) == list(PROFILES)
    for code, _ in en:
        if code.startswith("polyctl"):
            _accepts(code)


def test_the_five_minute_profile_names_match_the_shipped_presets():
    shipped = json.loads((ROOT / "src" / "polyctl" / "adapters" / "profiles.json").read_text(encoding="utf-8"))
    profiles = shipped["profiles"]
    page = _text("docs/profiles.md")

    assert set(PROFILES) <= set(profiles)
    for readme, heading in (("README.md", "## Five minutes to the first reviewed commit"),
                            ("README.tr.md", "## İlk gözden geçirilmiş commit'e beş dakika")):
        block = "\n".join("%s %s" % (code, comment) for code, comment in _install(readme, heading))
        assert _profile_order(block) == list(PROFILES), readme
    for name in PROFILES:
        assert "`%s`" % name in page
        for adapter in profiles[name].values():
            assert (ROOT / "src" / "polyctl" / "adapters" / ("%s.json" % adapter)).is_file(), (name, adapter)
