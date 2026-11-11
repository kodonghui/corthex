"""Shared helpers for the repository checks. Standard library only."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS = ROOT / "plugins"

SKILL_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

# YAML rejects an unquoted value, or reads it as something else, when it starts
# with an indicator, contains ": " or " #", ends with ":", or looks like a
# number, boolean or null. Such values must be quoted.
INDICATORS = ",[]{}#&*!|>'\"%@`"
PLAIN_BREAK = re.compile(r":(?:\s|$)|\s#")
NOT_A_STRING = re.compile(
    r"~|null|true|false|yes|no|on|off|[-+]?(?:\d[\d_]*(?:\.\d*)?|\.\d+)(?:e[-+]?\d+)?",
    re.IGNORECASE,
)


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def read_text(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def plugin_dirs():
    return sorted(p for p in PLUGINS.iterdir() if p.is_dir())


def skill_files():
    return sorted(PLUGINS.glob("*/skills/*/SKILL.md"))


def staged_skill_files():
    """A skill of a later release, which waits beside its SKILL.md as SKILL-<version>.md, a name that no host loads."""
    return sorted(path for path in PLUGINS.glob("*/skills/*/SKILL-*.md") if re.fullmatch(r"SKILL-\d+\.\d+\.\d+\.md", path.name))


def _plain_ok(value):
    """Whether YAML reads this unquoted value as the same string."""
    if not value:
        return True
    if value[0] in INDICATORS or (value[0] in "-?:" and not value[1:2].strip()):
        return False
    return not PLAIN_BREAK.search(value) and not NOT_A_STRING.fullmatch(value)


def _scalar(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    if not _plain_ok(value):
        raise ValueError("quote this frontmatter value, YAML does not read it as written: %r" % value)
    return value


def split_frontmatter(text):
    """Return (fields, body) for a SKILL.md that starts with a `---` block.

    Supports the subset the skills use: `key: value` lines and one level of
    indented `key: value` lines under a key with no value (such as metadata).
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("frontmatter must start on the first line")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise ValueError("frontmatter is not closed") from None
    fields = {}
    parent = None
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indented = raw.startswith((" ", "\t"))
        key, sep, value = raw.strip().partition(":")
        if not sep:
            raise ValueError("cannot parse frontmatter line: %r" % raw)
        if indented:
            if parent is None:
                raise ValueError("indented line without a parent key: %r" % raw)
            fields[parent][key.strip()] = _scalar(value)
            continue
        key = key.strip()
        if key in fields:
            raise ValueError("duplicate frontmatter key: %s" % key)
        if value.strip():
            fields[key] = _scalar(value)
            parent = None
        else:
            fields[key] = {}
            parent = key
    return fields, "\n".join(lines[end + 1:])


def local_links(text):
    """Relative link targets in Markdown text, without anchors."""
    targets = []
    for target in LINK.findall(text):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
            continue
        targets.append(target.split("#", 1)[0])
    return targets
