"""Check a slice's written evidence before spending a review round (AIDLC-2)."""
import os
import re
import stat
from urllib.parse import urlsplit

UTF8 = "utf-8"
REQUIRED_SECTIONS = ("problem", "acceptance criteria", "out of scope", "tests", "risks")
WORK_TYPES = ("feature", "enterprise", "bugfix", "poc")
MAX_SPEC_BYTES = 1048576
HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
ITEM = re.compile(r"^\s*(?:[-*+]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+)(.*)")
TEST_NAME = re.compile(r"(?<![\w/.-])(?:[\w./-]+::)+(?:[\w.-]+)(?:\[[^\]\n]+\])?(?![\w/.-])")
TEST_ID = re.compile(r"(?<![\w-])(?:T\d+|TEST-[A-Za-z0-9_-]+|test_[A-Za-z0-9_]+)(?![\w-])")
URL = re.compile(r"https?://[^\s<>\[\]`]+", re.I)
REFERENCE = re.compile(r"\[([^\]]+)\](?![(:])")


def _name(text):
    return " ".join(text.strip().lower().replace("_", " ").replace("-", " ").split())


def _sections(text):
    """Ignore examples and comments; nested headings keep their parent's evidence (AIDLC-2)."""
    sections, stack, fence = {"": []}, [(0, "")], None
    text = re.sub(r"<!--.*?(?:-->|\Z)", lambda match: "\n" * match.group().count("\n"), text, flags=re.S)
    for number, line in enumerate(text.splitlines(), 1):
        mark = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if mark and mark.group(1)[0] == fence[0] and len(mark.group(1)) >= len(fence) \
                    and not mark.group(2).strip():
                fence = None
            continue
        if mark:
            fence = mark.group(1)
            continue
        heading = HEADING.match(line)
        if heading:
            sections[""].append((number, ""))
            level, name = len(heading.group(1)), _name(heading.group(2))
            stack = [(depth, key) for depth, key in stack if depth < level]
            stack.append((level, name))
            sections.setdefault(name, [])
        else:
            for _, name in stack:
                sections[name].append((number, line))
    return sections


def _entries(lines):
    """A list item or paragraph is one criterion; wrapped lines belong to it (AIDLC-2)."""
    entries, current = [], None
    for number, line in lines:
        item = ITEM.match(line)
        if not line.strip():
            current = None
        elif item or current is None or re.match(r"^\s*external\s*:", line, re.I):
            current = [number, item.group(1) if item else line.strip()]
            entries.append(current)
        else:
            current[1] += " " + line.strip()
    return entries


def _has_url(text):
    for value in URL.findall(text):
        try:
            if urlsplit(value.rstrip(".,;)>")).hostname:
                return True
        except ValueError:
            continue
    return False


def findings(text, required=REQUIRED_SECTIONS):
    """Structural findings only: a test reference or citation does not prove a claim (AIDLC-2)."""
    sections = _sections(text)
    out = []
    for section in required:
        if not any(line.strip() for _, line in sections.get(_name(section), [])):
            out.append(f"missing or empty section '{section}'; add its evidence")
    tests = "\n".join(line for _, line in sections.get("tests", []))
    named = set(TEST_ID.findall(tests))
    criteria = _entries(sections.get("acceptance criteria", []))
    if not criteria:
        out.append("no acceptance criteria; list each criterion with a named test")
    for number, criterion in criteria:
        if not TEST_NAME.search(criterion) and not named.intersection(TEST_ID.findall(criterion)):
            out.append(f"line {number}: acceptance criterion has no named test; add path::name or a test id "
                       "declared in Tests")
    # Sources are resolved from visible prose only, never from a fenced example (AIDLC-2).
    visible = dict(sections[""])
    sources = {match.group(1).casefold() for line in visible.values()
               for match in [re.match(r"^\s*\[([^\]]+)\]:\s*(https?://\S+)", line, re.I)]
               if match and _has_url(match.group(2))}
    claims = dict(_entries(sections.get("external claims", [])))
    for number, line in _entries(list(visible.items())):
        if re.match(r"^external\s*:", line, re.I):
            claims[number] = line
    for number, claim in claims.items():
        if not _has_url(claim) and not sources.intersection(ref.casefold() for ref in REFERENCE.findall(claim)):
            out.append(f"line {number}: external claim has no source; add an HTTP(S) citation or a defined reference")
    return out


def _read(root, path):
    real_root = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root, path))
    if os.path.isabs(path) or not target.startswith(real_root + os.sep):
        raise ValueError("spec must be a relative path inside the project")
    fd = os.open(target, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("spec must be a regular file")
        data = stream.read(MAX_SPEC_BYTES + 1)
    if len(data) > MAX_SPEC_BYTES:
        raise ValueError("spec exceeds 1,048,576 bytes; split it into bounded slices")
    return data.decode(UTF8)


def check(cfg, item):
    """Read the declared spec and work-type requirements without writes or network (AIDLC-2)."""
    notes = item.get("notes") or {}
    kind = notes.get("work-type", "feature")
    result = {"slice": item["id"], "work_type": kind, "findings": [], "blocked": False}
    try:
        if kind not in WORK_TYPES:
            raise ValueError("unknown work-type; choose feature, enterprise, bugfix or poc")
        if cfg.get("_config_problem"):
            raise ValueError("project configuration cannot be read: " + str(cfg["_config_problem"]))
        types = cfg.get("work_types", {})
        if not isinstance(types, dict):
            raise ValueError("work_types must be an object keyed by work type")
        policy = types.get(kind, {})
        if not isinstance(policy, dict):
            raise ValueError(f"work_types.{kind} must be an object")
        required = policy.get("required_sections", REQUIRED_SECTIONS)
        if not isinstance(required, (list, tuple)) or any(not isinstance(name, str) or not name.strip()
                                                        for name in required):
            raise ValueError(f"work_types.{kind}.required_sections must be a list of section names")
        path = notes.get("spec")
        if not path:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", item["id"]):
                raise ValueError("slice id needs an explicit project-relative spec path")
            path = f"docs/specs/{item['id']}.md"
        result["file"] = path
        result["findings"] = findings(_read(cfg["root"], path), required)
    except (OSError, UnicodeError, ValueError) as exc:
        result["findings"] = [f"cannot check spec: {exc}; fix the spec path, encoding or work-type configuration"]
    result["blocked"] = bool(result["findings"]) and kind not in ("bugfix", "poc")
    return result
