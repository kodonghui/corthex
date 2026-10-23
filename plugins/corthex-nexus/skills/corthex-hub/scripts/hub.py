#!/usr/bin/env python3
"""CORTHEX hub: one page with the stages, checks and trace links of every project.

Commands, each with --help:
  snapshot  read a project's stage sources and save a snapshot of them
  status    record a stage's progress, last checkpoint and next action
  build     refresh the snapshots and write the hub page
  push      send snapshots to your own NEXUS server
  remove    remove projects from your NEXUS server

It reads ~/.corthex/profile.json, ~/.corthex/projects.json, each project's
.corthex/project.json and the stage sources that file names. It writes only
under ~/.corthex/hub/ and never into a repository. Only `push` and `remove`
use the network. Standard library only.
"""

import argparse
import csv
import html
import io
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

VERSION = "0.1.0"
SCHEMA = "corthex-hub/0.1"
PAGE_SCHEMA = "corthex-hub-page/0.1"
TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "hub.html"
PLACEHOLDER = "__CORTHEX_HUB_DATA__"
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")

# The stage contract of the `corthex` skill: key, name, default source, the ID
# kinds the stage creates, and whether the hub reads the stage's files for IDs.
# tests/test_hub.py keeps this table equal to references/stage-contract.md.
STAGES = (
    ("01-domain", "Domain discovery", "docs/01-domain/", ("context", "term"), True),
    ("02-prd", "PRD", "docs/02-prd/requirements.md", ("requirement",), True),
    ("03-user-flow", "User flow", "docs/03-user-flow/", ("flow",), True),
    ("04-functional-spec", "Functional spec", "docs/04-functional-spec/spec.md", ("spec",), True),
    ("05-erd", "ERD", "db/schema.sql", ("table",), True),
    ("06-api", "API", "api/openapi.yaml", ("api",), True),
    ("07-sitemap", "Sitemap", "docs/07-sitemap/sitemap.yaml", ("screen",), True),
    ("08-screen-states", "Screen states", "docs/08-screens/", (), True),
    ("09-mockup", "Mockup", "design/base.tokens.json", (), False),
    ("10-wbs", "WBS", "docs/10-wbs/wbs.md", ("task",), True),
    ("11-development", "Development", None, (), False),
    ("12-qa", "QA", "docs/12-qa/test-plan.md", ("test", "bug"), True),
    ("13-presentation", "Presentation", "docs/13-presentation/script.md", ("scene",), True),
)
STAGE_KEYS = tuple(stage[0] for stage in STAGES)
# Screen state files describe the screens of the sitemap instead of new items.
SCREEN_STAGE = "08-screen-states"

# ID kinds and their default prefixes, in the order of the stage contract.
KINDS = (
    ("context", "CTX"), ("term", "TERM"), ("requirement", "REQ"), ("flow", "FL"),
    ("spec", "SPEC"), ("table", "TBL"), ("api", "API"), ("screen", "SCR"),
    ("task", "TASK"), ("test", "TC"), ("bug", "BUG"), ("decision", "DEC"), ("scene", "SCENE"),
)
KIND_NAMES = tuple(kind for kind, _ in KINDS)
DEFINED_IN = {kind: stage[0] for stage in STAGES for kind in stage[3]}
# Each item of these kinds names at least one item of the kinds it comes from.
UPSTREAM = {
    "flow": ("requirement",),
    "spec": ("requirement",),
    "table": ("spec",),
    "api": ("spec",),
    "task": ("spec",),
    "test": ("requirement", "flow", "spec"),
    "bug": ("test", "screen", "spec"),
}
STATES = ("done", "in_progress", "not_started", "skipped")
LEVELS = ("error", "warn", "info")

MAX_FILE_BYTES = 1024 * 1024
MAX_FILES = 400
MAX_ITEMS = 3000
MAX_CHECKS = 2000
MAX_LINKS = 60
MAX_PLACES = 3
MAX_SNAPSHOT_BYTES = 1000 * 1000
TITLE_CHARS = 120
TEXT_CHARS = 300

MARKDOWN = {".md", ".markdown", ".mdx"}
YAML = {".yaml", ".yml"}
TABLES = {".csv": ",", ".tsv": "\t"}
TEXT = MARKDOWN | YAML | set(TABLES) | {".json", ".sql", ".txt", ".mmd", ".mermaid", ".feature", ".rst", ".adoc"}
SKIP_DIRS = {"node_modules", "__pycache__", "venv"}
SECRET_NAME = re.compile(
    r"(?i)(?:^|[._-])(?:secrets?|credentials?|passwords?|passwd|api[-_]?keys?|private[-_]?keys?"
    r"|access[-_]?tokens?|auth[-_]?tokens?)(?:[._-]|$)|\.(?:pem|key|p12|pfx)$"
)
# A key starts a word, so "Task-board-…" in a title or a page address is not one.
SECRET_TEXT = re.compile(
    r"(?<![A-Za-z0-9])(?:sk-[A-Za-z0-9_-]{20,}|(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
)

csv.field_size_limit(max(csv.field_size_limit(), MAX_FILE_BYTES))

PREFIX = re.compile(r"^[A-Z][A-Z0-9]*$")
ALIAS = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NAME = ALIAS
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[ T][0-9:.+\-Z ]{2,25}[A-Z]{0,5})?$")
STATE = re.compile(r"#([a-z][a-z0-9_-]{0,30})")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(?:`{3,}|~{3,})")
SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
CELL_SPLIT = re.compile(r"(?<!\\)\|")
LEAD = re.compile(r"^[\s*_`~\[(]+")
TRAIL = re.compile(r"^[\s\]):：.\-–—·|*_`~]+")
MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
TAG = re.compile(r"<[^>]{0,300}>")
MARKUP = re.compile(r"\*\*|__|~~|`")
STRUCK = re.compile(r"~~[^~\n]+~~")
URL = re.compile(r"https?://[^\s<>\"'`|\])]+")
YAML_KEY = re.compile(r"^(\s*)(-\s+)?(\"[^\"]*\"|'[^']*'|[^\s#\"'-][^:#]*?|-[^\s:#][^:#]*?)\s*:(?:\s+(.*))?$")
YAML_ITEM = re.compile(r"^(\s*)-\s+(.*)$")
YAML_COMMENT = re.compile(r"(?:^|\s)#.*$")
JSON_ID = re.compile(r'"id"\s*:\s*"([^"\\]{1,80})"')
SQL_COMMENT = re.compile(r"--\s?(.*)$")
GITHUB = re.compile(
    r"^(?:https://(?:[^@/\s]+@)?github\.com/|ssh://git@github\.com/|git@github\.com:)"
    r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)
METHODS = {"get", "put", "post", "delete", "patch", "options", "head", "trace"}

# Column and property names, compared after norm(). The first title column wins.
TITLE_NAMES = (
    "title", "name", "item", "requirement", "behaviour", "behavior", "task", "case", "term",
    "message", "decision", "summary", "screen name", "제목", "이름", "항목", "요구사항", "기능명",
    "화면명", "용어", "작업", "케이스", "장면", "메시지", "결정",
)
TITLE_WEAK = ("flow", "feature", "흐름", "기능", "내용")
FIELD_NAMES = {
    "status": {"status", "state", "상태"},
    "type": {"type", "category", "유형", "구분", "종류"},
    "priority": {"priority", "우선순위", "중요도"},
    "link": {"link", "url", "notion", "notion url", "notion_url", "notion link", "notion 링크", "링크", "원문"},
}
COPY_TIMES = {"exported_at", "refreshed_at", "copied_at", "synced_at", "refreshed", "exported"}
ID_HEADERS = {"id", "key", "아이디", "번호", "키"}

EMPTY = {"", "-", "none", "null", "n a", "na", "tbd", "없음", "비어 있음", "미정"}
MUST = {"must", "must have", "mandatory", "required", "p0", "필수"}
NON_FUNCTIONAL = {"non-functional", "nonfunctional", "non functional", "nfr", "quality", "비기능"}
OUT_OF_SCOPE = {"backlog", "overview", "later", "백로그", "개요"}
REMOVED = {"removed", "deleted", "dropped", "cancelled", "canceled", "deprecated", "obsolete", "삭제", "삭제됨", "폐기", "제외", "취소"}


# ---------------------------------------------------------------- small helpers

def now_text():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def say(text, stream=None):
    """Print a line, replacing what the console encoding cannot show."""
    stream = stream or sys.stdout
    try:
        stream.write(text + "\n")
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        stream.write(text.encode(encoding, "replace").decode(encoding) + "\n")


def load_json(path):
    """The JSON object in a file, or None when it is missing or not an object."""
    try:
        with open(path, encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def dump(data, compact=False):
    if compact:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(data, ensure_ascii=False, indent=1) + "\n"


def write_file(path, text):
    """Write text through a temporary file, so a failed write keeps the old file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with open(temp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(temp, path)


def hub_dir(home):
    return home / ".corthex" / "hub"


def is_dir(path):
    try:
        return path.is_dir()
    except OSError:
        return False


def is_file(path):
    try:
        return path.is_file()
    except OSError:
        return False


def resolve(raw):
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return Path(raw).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def inside(path, root):
    return path == root or root in path.parents


def one_line(value, limit=TEXT_CHARS):
    """A string value on one line with secrets removed, or "" for anything else."""
    if not isinstance(value, str):
        return ""
    text = " ".join(SECRET_TEXT.sub("[redacted]", value).split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def plain(value, limit=TITLE_CHARS):
    """Markdown or HTML text as plain text on one line, with secrets removed."""
    if not isinstance(value, str):
        return ""
    text = MD_LINK.sub(r"\1", value)
    text = TAG.sub(" ", text.replace("<br>", " "))
    text = MARKUP.sub("", html.unescape(text))
    return one_line(text, limit)


def norm(value):
    """A name or value in lowercase words, without emoji or punctuation, for comparing."""
    text = re.sub(r"[^\w\s-]", " ", str(value).lower()).replace("_", " ")
    return " ".join(text.split())


def field_value(field, raw):
    """A field value as stored in a snapshot; empty markers become ""."""
    if field == "link":
        return web_link(raw)
    value = plain(raw, 60)
    return "" if norm(value) in EMPTY else value


def web_link(raw):
    """The first http(s) address in raw text, without any user name or password.

    A link that holds a secret or an email address, even percent-encoded, is
    left out whole: with the secret taken out it would no longer work.
    """
    match = URL.search(raw if isinstance(raw, str) else "")
    if not match:
        return ""
    try:
        parts = urllib.parse.urlsplit(match.group(0))
        port = parts.port
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return ""
    netloc = parts.hostname + (":%d" % port if port else "")
    link = urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    if SECRET_TEXT.search(link) or SECRET_TEXT.search(urllib.parse.unquote(link)):
        return ""
    return link[:500]


def field_of(name):
    """The snapshot field that a column or property name stands for, or None."""
    if name in TITLE_NAMES or name in TITLE_WEAK:
        return "title"
    for field, names in FIELD_NAMES.items():
        if name in names:
            return field
    return None


def id_key(ident):
    """Sort key for IDs: prefix, then number."""
    prefix, _, number = ident.partition("-")
    return (prefix, int(number) if number.isdigit() else 0, ident)


# ---------------------------------------------------------------- trace IDs

def id_format(value, default):
    """(prefixes, digits) from one entry of a project's `ids`; digits is None when unset."""
    if isinstance(value, str) and PREFIX.match(value):
        return [value], None
    if isinstance(value, dict):
        raw = value.get("prefix")
        prefixes = [raw] if isinstance(raw, str) else raw if isinstance(raw, list) else []
        prefixes = [p for p in prefixes if isinstance(p, str) and PREFIX.match(p)]
        digits = value.get("digits")
        if isinstance(digits, bool) or not isinstance(digits, int) or not 1 <= digits <= 6:
            digits = None
        if prefixes:
            return prefixes, digits
    return [default], None


class IdFormat:
    """The trace ID prefixes of one project, and a pattern that finds them in text."""

    def __init__(self, ids):
        ids = ids if isinstance(ids, dict) else {}
        self.kind_of = {}
        self.digits = {}
        self.clashes = []
        for kind, default in KINDS:
            prefixes, digits = id_format(ids.get(kind), default)
            for prefix in prefixes:
                if prefix in self.kind_of:
                    self.clashes.append((prefix, self.kind_of[prefix], kind))
                else:
                    self.kind_of[prefix] = kind
            if digits:
                self.digits[kind] = digits
        names = sorted(self.kind_of, key=lambda p: (-len(p), p))
        self.pattern = re.compile(
            r"(?<![A-Za-z0-9_])(%s)-([0-9]{1,6})(?![0-9A-Za-z_])" % "|".join(map(re.escape, names))
        )

    def kind(self, ident):
        return self.kind_of.get(ident.partition("-")[0])

    def find(self, text):
        """(id, kind, end) for each ID in text."""
        for match in self.pattern.finditer(text):
            yield match.group(0), self.kind_of[match.group(1)], match.end()

    def lead(self, text):
        """(id, kind, state, rest) when text starts with an ID, else None."""
        text = LEAD.sub("", text)
        match = self.pattern.match(text)
        if not match:
            return None
        rest = text[match.end():]
        state = STATE.match(rest)
        if state:
            rest = rest[state.end():]
        return match.group(0), self.kind_of[match.group(1)], state and state.group(1), TRAIL.sub("", rest)

    def whole(self, text):
        """(id, kind, state) when text is one ID, optionally with a #state, else None."""
        text = text.strip()
        match = self.pattern.match(text)
        if not match:
            return None
        rest = text[match.end():]
        state = STATE.fullmatch(rest) if rest else None
        if rest and not state:
            return None
        return match.group(0), self.kind_of[match.group(1)], state and state.group(1)

    def only_ids(self, text):
        """True when text holds IDs and punctuation only."""
        return not re.search(r"\w", self.pattern.sub("", text))


# ---------------------------------------------------------------- reading sources

class Source:
    """One file of a stage source: where it is and which IDs it can define."""

    def __init__(self, stage, kinds, alias, rel):
        self.stage = stage
        self.kinds = kinds
        self.alias = alias
        self.rel = rel
        stem = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        self.stem = stem
        # Listings, such as an exported database index, only fill in what the
        # items' own files leave out, so they never count as a second definition.
        self.listing = stem.startswith("_") or stem.lower() in ("index", "readme", "list", "목록")

    def where(self, line):
        prefix = "" if self.alias == "." else self.alias + ":"
        return "%s%s:%d" % (prefix, self.rel, line)


class Scan:
    """What the stage sources of one project define, link and mention."""

    def __init__(self, ids):
        self.ids = ids
        self.defs = {}
        self.links = {}
        self.mentions = {}
        self.states = {}
        self.screen_docs = {}
        self.copied = {}

    def claim(self, ident, kind, src, line, fields, parent=None):
        """Define ident when the file's stage creates its kind. Returns the entry or None."""
        if kind in src.kinds:
            strong = not src.listing
        elif kind == "screen" and src.stage == SCREEN_STAGE:
            strong = False
            self.screen_docs.setdefault(ident, src.where(line))
        else:
            return None
        entry = {"kind": kind, "stage": src.stage, "where": src.where(line), "strong": strong}
        for name, value in fields.items():
            if value:
                entry[name] = value
        if parent:
            entry["parent"] = parent
        self.defs.setdefault(ident, []).append(entry)
        return entry

    def link(self, source, target):
        if source and source != target:
            self.links.setdefault(source, set()).add(target)

    def mention(self, ident, src, line):
        places = self.mentions.setdefault(ident, [])
        where = src.where(line)
        if len(places) < MAX_PLACES and where not in places:
            places.append(where)

    def refer(self, text, src, line, subject=None):
        """Record each ID in text, as a link from subject when there is one."""
        for ident, kind, end in self.ids.find(text):
            self.mention(ident, src, line)
            self.link(subject, ident)
            if kind == "screen" and src.stage == SCREEN_STAGE:
                state = STATE.match(text, end)
                if state:
                    self.states.setdefault(ident, set()).add(state.group(1))

    def add_state(self, ident, state, src):
        if state and src.stage == SCREEN_STAGE:
            self.states.setdefault(ident, set()).add(state)


def front_matter(lines):
    """(fields, body start) for a Markdown file that starts with a `---` block."""
    if not lines or lines[0].strip() != "---":
        return {}, 0
    fields = {}
    for number in range(1, min(len(lines), 200)):
        line = lines[number]
        if line.strip() in ("---", "..."):
            return fields, number + 1
        if line[:1].isspace():
            continue
        key, sep, value = line.partition(":")
        if sep:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            fields[key.strip().lower()] = value
    return {}, 0


def meta_fields(meta):
    fields = {}
    for key, value in meta.items():
        field = field_of(norm(key)) or ("link" if key in ("notion_url", "source_url") else None)
        if field and not fields.get(field):
            fields[field] = plain(value) if field == "title" else field_value(field, value)
    return fields


def copy_time(meta):
    for key in COPY_TIMES:
        value = one_line(meta.get(key), 40)
        if value:
            return value
    return ""


def cells(line):
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    return [cell.strip() for cell in CELL_SPLIT.split(text)]


def is_table(line):
    return line.lstrip().startswith("|")


def id_column(header):
    """The index of a table's ID column, from its header, or None."""
    for index, name in enumerate(header or ()):
        if name in ID_HEADERS or name.endswith(" id"):
            return index
    return None


def row_fields(ids, row, header, skip):
    """Title, status, type, priority and link of one table row."""
    fields = {}
    strong, weak, rest = [], [], []
    for index, cell in enumerate(row):
        if index == skip:
            continue
        name = header[index] if header and index < len(header) else ""
        field = field_of(name)
        if field == "title":
            (strong if name in TITLE_NAMES else weak).append(index)
        elif field:
            if not fields.get(field):
                fields[field] = field_value(field, cell)
        else:
            rest.append(index)
    for index in strong + weak + rest:
        text = plain(row[index])
        if text and not ids.only_ids(text):
            fields["title"] = text
            break
    return fields


def scan_markdown(scan, src, text):
    # Struck-through text is deleted text, as in exports from Notion.
    lines = [STRUCK.sub(" ", line) for line in text.splitlines()]
    meta, body = front_matter(lines)
    subject = None
    if scan.ids.whole(meta.get("id", "")):
        subject = scan.ids.whole(meta["id"])[:2]
    else:
        match = scan.ids.pattern.match(src.stem)
        if match and (match.end() == len(src.stem) or src.stem[match.end()] in " _-."):
            subject = match.group(0), scan.ids.kind_of[match.group(1)]
    if subject:
        scan_item_file(scan, src, lines, meta, body, subject)
    else:
        scan_sections(scan, src, lines, body)
    copied = copy_time(meta)
    if copied:
        scan.copied.setdefault(src.stage, []).append(copied)


def scan_item_file(scan, src, lines, meta, body, subject):
    """A file about one item, such as REQ-23.md: every ID in it links from that item."""
    ident, kind = subject
    fields = meta_fields(meta)
    meta_title = fields.get("title")
    heading_title = ""
    in_fence = False
    for number, line in enumerate(lines, 1):
        scan.refer(line, src, number, ident)
        if FENCE.match(line):
            in_fence = not in_fence
        if in_fence or number <= body:
            continue
        heading = HEADING.match(line)
        if heading and len(heading.group(1)) == 1 and not heading_title:
            text = plain(heading.group(2), 400)
            lead = scan.ids.lead(text)
            heading_title = plain(lead[3]) if lead and lead[0] == ident else plain(text)
        elif is_table(line) and not SEPARATOR.match(line):
            if number < len(lines) and SEPARATOR.match(lines[number]):
                continue  # a header row names columns; it is not a field
            row = cells(line)
            if len(row) == 2:
                field = field_of(norm(plain(row[0], 60)))
                if field and not fields.get(field):
                    fields[field] = plain(row[1]) if field == "title" else field_value(field, row[1])
    if heading_title and not meta_title:
        fields["title"] = heading_title
    scan.claim(ident, kind, src, 1, fields)


def scan_sections(scan, src, lines, body):
    """Headings and table rows that start with an ID define items; the rest links."""
    sections = []
    header = None
    in_fence = False
    for number, line in enumerate(lines, 1):
        subject = sections[-1][1] if sections else None
        if FENCE.match(line):
            in_fence = not in_fence
        elif not in_fence and number > body:
            heading = HEADING.match(line)
            if heading:
                level = len(heading.group(1))
                while sections and sections[-1][0] >= level:
                    sections.pop()
                header = None
                lead = scan.ids.lead(plain(heading.group(2), 400))
                if lead:
                    ident, kind, state, rest = lead
                    entry = scan.claim(ident, kind, src, number, {"title": plain(rest)})
                    scan.add_state(ident, state, src)
                    sections.append((level, ident, entry))
                    subject = ident
                scan.refer(line, src, number, subject)
                continue
            if is_table(line):
                if SEPARATOR.match(line):
                    continue
                if number < len(lines) and SEPARATOR.match(lines[number]):
                    header = [norm(plain(cell, 60)) for cell in cells(line)]
                    continue
                scan_row(scan, src, number, cells(line), header, sections)
                continue
            header = None
        scan.refer(line, src, number, subject)


def scan_row(scan, src, number, row, header, sections):
    subject = sections[-1][1] if sections else None
    entry = sections[-1][2] if sections else None
    column = id_column(header)
    found = scan.ids.whole(plain(row[column], 200)) if column is not None and column < len(row) else None
    claimable = found is not None
    if found is None and row:
        # A row that starts with an ID, as in a trace table, links from that ID.
        found = scan.ids.whole(plain(row[0], 200))
        column = 0
    if found is None:
        if entry is not None and len(row) == 2:
            field = field_of(norm(plain(row[0], 60)))
            if field and not entry.get(field):
                entry[field] = plain(row[1]) if field == "title" else field_value(field, row[1])
        scan.refer(" | ".join(row), src, number, subject)
        return
    ident, kind, state = found
    scan.mention(ident, src, number)
    scan.add_state(ident, state, src)
    if claimable and ident != subject:
        scan.claim(ident, kind, src, number, row_fields(scan.ids, row, header, column))
    others = " | ".join(cell for index, cell in enumerate(row) if index != column)
    scan.refer(others, src, number, ident)


def scan_yaml(scan, src, text):
    """Mappings with an `id:` key define items; the rest of the mapping links from them."""
    lines = []
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = YAML_KEY.match(line)
        item = YAML_ITEM.match(line)
        indent = len(line) - len(line.lstrip(" "))
        dash = bool(match and match.group(2)) or (item is not None and not match)
        level = indent + (len(match.group(2)) if match and match.group(2) else 2 if dash else 0)
        key = match.group(3).strip().strip("\"'") if match else None
        value = yaml_value(match.group(4) or "") if match else ""
        lines.append((number, line, level, dash, key, value))
    # The keys of a mapping may come in any order, so first find each mapping's
    # ID and fields: [level, enclosing mapping, ID, line of the ID, fields].
    maps = []
    owners = []
    open_maps = []
    for number, line, level, dash, key, value in lines:
        while open_maps and (level < maps[open_maps[-1]][0] or (level == maps[open_maps[-1]][0] and dash)):
            open_maps.pop()
        if key is not None and not (open_maps and maps[open_maps[-1]][0] == level):
            maps.append([level, open_maps[-1] if open_maps else None, None, 0, {}])
            open_maps.append(len(maps) - 1)
        owners.append(open_maps[-1] if open_maps else None)
        if key is None:
            continue
        mapping = maps[open_maps[-1]]
        if key.lower() == "id":
            found = scan.ids.whole(value)
            if found and mapping[2] is None:
                mapping[2], mapping[3] = found, number
            continue
        # Only clear names give a title here; `feature:` may be anything.
        field = field_of(norm(key))
        if field == "title" and norm(key) not in TITLE_NAMES:
            field = None
        if field and not mapping[4].get(field):
            mapping[4][field] = plain(value) if field == "title" else field_value(field, value)
    # Each mapping speaks for its own ID, else for that of the nearest mapping around it.
    subjects = []
    for _, outer, found, _, _ in maps:
        subjects.append(found[0] if found else subjects[outer] if outer is not None else None)
    keys = []
    for (number, line, level, dash, key, value), owner in zip(lines, owners):
        if key is not None:
            while keys and keys[-1][0] >= level:
                keys.pop()
            keys.append((level, key))
            _, outer, found, id_line, fields = maps[owner]
            if id_line == number:
                ident, kind, _ = found
                fields = dict(fields)
                if kind == "api" and api_title(keys):
                    fields["title"] = api_title(keys)
                scan.claim(ident, kind, src, number, fields, subjects[outer] if outer is not None else None)
                scan.mention(ident, src, number)
                continue
            inline = re.search(r"\bid\s*:\s*[\"']?([^\s,\"'}]+)", value) if value.startswith("{") else None
            found = scan.ids.whole(inline.group(1)) if inline else None
            if found:
                scan.claim(found[0], found[1], src, number, {"title": api_title(keys) if found[1] == "api" else ""})
                scan.refer(value, src, number, found[0])
                continue
        scan.refer(line, src, number, subjects[owner] if owner is not None else None)


def yaml_value(value):
    """A YAML scalar without its quotes or its trailing comment."""
    value = value.strip()
    if value[:1] in ("\"", "'"):
        end = value.find(value[0], 1)
        return value[1:end] if end > 0 else value[1:]
    return YAML_COMMENT.sub("", value).strip()


def api_title(keys):
    """"POST /orders" from the keys around an OpenAPI operation, or ""."""
    names = [key for _, key in keys]
    for index in range(len(names) - 1, 0, -1):
        if names[index].lower() in METHODS and names[index - 1].startswith("/"):
            return "%s %s" % (names[index].upper(), names[index - 1])
    return ""


def scan_json(scan, src, text):
    try:
        data = json.loads(text)
    except ValueError:
        scan_yaml(scan, src, text)
        return
    first_line = {}
    id_lines = {}
    for number, line in enumerate(text.splitlines(), 1):
        for ident, _, _ in scan.ids.find(line):
            first_line.setdefault(ident, number)
        for match in JSON_ID.finditer(line):
            found = scan.ids.whole(match.group(1))
            if found:
                id_lines.setdefault(found[0], []).append(number)

    def line_of(ident):
        return first_line.get(ident, 1)

    def definition_line(ident):
        """The line of the next `"id": "<ident>"`, in the order the walk meets them."""
        lines = id_lines.get(ident)
        return lines.pop(0) if lines else line_of(ident)

    def walk(node, subject, path):
        if isinstance(node, dict):
            found = scan.ids.whole(node["id"]) if isinstance(node.get("id"), str) else None
            marker = node.get("x-corthex")
            from_marker = False
            if found is None and isinstance(marker, dict) and isinstance(marker.get("id"), str):
                found = scan.ids.whole(marker["id"])
                from_marker = found is not None
            if found:
                ident, kind, _ = found
                title = node.get("name") or node.get("title") or node.get("summary") or ""
                if kind == "api":
                    title = api_title(list(enumerate(path))) or title
                fields = {"title": plain(title) if isinstance(title, str) else ""}
                for key, value in node.items():
                    field = field_of(norm(key))
                    if field and field != "title" and isinstance(value, str):
                        fields[field] = field_value(field, value)
                number = definition_line(ident)
                scan.claim(ident, kind, src, number, fields, subject)
                scan.mention(ident, src, number)
                subject = ident
            for key, value in node.items():
                if key == "id" and found and not from_marker:
                    continue
                if key == "x-corthex" and from_marker:
                    value = {k: v for k, v in value.items() if k != "id"}
                walk(value, subject, path + [str(key)])
        elif isinstance(node, list):
            for value in node:
                walk(value, subject, path)
        elif isinstance(node, str):
            for ident, _, _ in scan.ids.find(node):
                scan.mention(ident, src, line_of(ident))
                scan.link(subject, ident)

    walk(data, None, [])


def scan_sql(scan, src, text):
    """`-- TBL-001 orders ← SPEC-001` defines a table; later lines link from it."""
    subject = None
    for number, line in enumerate(text.splitlines(), 1):
        comment = SQL_COMMENT.search(line)
        lead = scan.ids.lead(comment.group(1)) if comment else None
        if lead and lead[1] in src.kinds:
            ident, kind, _, rest = lead
            name = re.split(r"[(←<,;]|\s-\s", rest, maxsplit=1)[0]
            scan.claim(ident, kind, src, number, {"title": plain(name)})
            subject = ident
        scan.refer(line, src, number, subject)


def scan_table_file(scan, src, text, delimiter):
    # The stream keeps its line breaks, so a quoted field can span lines; each
    # record is numbered by the line it starts on.
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    rows = []
    start = 1
    try:
        for row in reader:
            rows.append((start, row))
            start = reader.line_num + 1
    except csv.Error:
        scan_text(scan, src, text)
        return
    if not rows:
        return
    header = [norm(plain(cell, 60)) for cell in rows[0][1]]
    column = id_column(header)
    for number, row in rows[1:]:
        found = scan.ids.whole(plain(row[column], 200)) if column is not None and column < len(row) else None
        if found is None:
            scan.refer(" | ".join(row), src, number)
            continue
        ident, kind, _ = found
        scan.mention(ident, src, number)
        scan.claim(ident, kind, src, number, row_fields(scan.ids, row, header, column))
        scan.refer(" | ".join(c for i, c in enumerate(row) if i != column), src, number, ident)


def scan_text(scan, src, text):
    match = scan.ids.pattern.match(src.stem)
    subject = match.group(0) if match and match.end() == len(src.stem) else None
    for number, line in enumerate(text.splitlines(), 1):
        scan.refer(line, src, number, subject)


def scan_file(scan, src, text):
    suffix = os.path.splitext(src.rel)[1].lower()
    if suffix in MARKDOWN:
        scan_markdown(scan, src, text)
    elif suffix in YAML:
        scan_yaml(scan, src, text)
    elif suffix == ".json":
        scan_json(scan, src, text)
    elif suffix == ".sql":
        scan_sql(scan, src, text)
    elif suffix in TABLES:
        scan_table_file(scan, src, text, TABLES[suffix])
    else:
        scan_text(scan, src, text)


def source_files(target, root, skipped):
    """The text files of a stage source, in a stable order, counting what is skipped."""
    if is_file(target):
        candidates = [target]
    else:
        candidates = []
        for folder, dirs, files in os.walk(target):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS)
            candidates.extend(Path(folder) / name for name in sorted(files) if not name.startswith("."))
    chosen = []
    for path in candidates:
        reason = None
        try:
            if path.suffix.lower() not in TEXT:
                reason = "format"
            elif secret_path(path, root):
                reason = "secret"
            elif not inside(path.resolve(), root):
                reason = "outside"
            elif path.stat().st_size > MAX_FILE_BYTES:
                reason = "size"
            elif len(chosen) >= MAX_FILES:
                reason = "limit"
        except OSError:
            reason = "unreadable"
        if reason:
            skipped[reason] = skipped.get(reason, 0) + 1
        else:
            chosen.append(path)
    return chosen


def secret_path(path, root):
    """True when the file's name, or a folder between it and the repository root, looks like a secret."""
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        parts = (path.name,)
    return any(SECRET_NAME.search(part) for part in parts)


def read_text(path):
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


# ---------------------------------------------------------------- projects

def find_project_file(start):
    """The nearest .corthex/project.json from start up to the repository root."""
    for folder in (start,) + tuple(start.parents):
        candidate = folder / ".corthex" / "project.json"
        if is_file(candidate):
            return candidate
        if (folder / ".git").exists():
            return None
    return None


def registered(home):
    """The entries of ~/.corthex/projects.json that have a valid name."""
    data = load_json(home / ".corthex" / "projects.json") or {}
    projects = data.get("projects")
    if not isinstance(projects, list):
        return []
    return [p for p in projects if isinstance(p, dict) and isinstance(p.get("name"), str) and NAME.match(p["name"])]


def checkouts_of(entry):
    repos = entry.get("repos") if entry else None
    if not isinstance(repos, dict):
        return {}
    return {alias: path for alias, path in repos.items() if isinstance(alias, str) and resolve(path)}


class Project:
    """A project to read: its folder, its settings and the local checkouts of its other repositories."""

    def __init__(self, name, root, settings, checkouts):
        self.name = name
        self.root = root
        self.settings = settings
        self.checkouts = checkouts


def open_project(root, entry=None, extra=None):
    """The Project in root, or (None, reason)."""
    path = root / ".corthex" / "project.json"
    settings = load_json(path)
    if settings is None:
        return None, "no readable .corthex/project.json in the project folder"
    name = settings.get("name") if isinstance(settings.get("name"), str) else ""
    if not NAME.match(name or ""):
        name = entry.get("name") if entry else ""
    if not NAME.match(name or ""):
        return None, "the project has no valid name in .corthex/project.json"
    checkouts = checkouts_of(entry)
    checkouts.update(extra or {})
    return Project(name, root, settings, checkouts), None


def select_projects(home, names, path=None, extra=None):
    """[(name, Project or None, reason)] for the named projects, or for the current folder."""
    entries = registered(home)
    by_name = {entry["name"]: entry for entry in entries}
    if path is not None or not names:
        start = Path(path or os.getcwd()).expanduser().resolve()
        found = find_project_file(start)
        if found is None:
            return [(None, None, "no .corthex/project.json from %s up to the repository root" % start)]
        root = found.parent.parent
        entry = next((e for e in entries if resolve(e.get("path")) == root), None)
        project, reason = open_project(root, entry, extra)
        if project and entry is None:
            entry = by_name.get(project.name)
            if entry:
                project.checkouts = dict(checkouts_of(entry), **(extra or {}))
        return [(project.name if project else None, project, reason)]
    result = []
    for name in names:
        entry = by_name.get(name)
        if entry is None:
            result.append((name, None, "not in ~/.corthex/projects.json"))
            continue
        root = resolve(entry.get("path"))
        if root is None or not is_dir(root):
            result.append((name, None, "its folder is not on this machine"))
            continue
        project, reason = open_project(root, entry, extra)
        result.append((name, project, reason))
    return result


# ---------------------------------------------------------------- repositories

def git(root, *args):
    try:
        result = subprocess.run(
            # The fsmonitor hook would run a program from the repository's config,
            # and optional locks let `git status` rewrite the index.
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root)] + list(args),
            capture_output=True, timeout=30,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", "replace").strip()


def github_base(url):
    match = GITHUB.match(url or "")
    return "https://github.com/%s/%s" % match.groups() if match else ""


def repo_info(root, url=""):
    """Commit, branch and whether the working tree has changes; no local paths."""
    info = {}
    link = web_link(url)
    if link:
        info["url"] = link
    commit = git(root, "rev-parse", "--verify", "-q", "HEAD")
    if commit:
        info["commit"] = commit
        branch = git(root, "symbolic-ref", "--short", "-q", "HEAD")
        if branch:
            info["branch"] = one_line(branch, 120)
        status = git(root, "status", "--porcelain")
        if status is not None:
            info["dirty"] = bool(status)
    web = github_base(url) or github_base(git(root, "remote", "get-url", "origin") or "")
    if web:
        info["web"] = web
    return info


# ---------------------------------------------------------------- snapshots

def split_source(source):
    """(alias, path) of a stage source; the alias is "." for the project's own repository."""
    alias, sep, rel = source.partition(":")
    if not sep or not ALIAS.match(alias):
        return ".", source
    return alias, rel


def is_absolute(rel):
    return rel.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", rel) is not None


def shown_source(source):
    """A source as a snapshot may hold it: never a path of this machine."""
    return "[absolute path]" if is_absolute(split_source(source)[1]) else source


def locate(source, project, problems, key):
    """(alias, repository root, target path, state) for a stage source."""
    alias, rel = split_source(source)
    if "\\" in rel or is_absolute(rel):
        shown = shown_source(source)
        problems.append(check("source-invalid", "error", "%s: the source %s is not a relative path with forward slashes" % (key, shown), stage=key, args={"stage": key, "source": shown}))
        return alias, None, None, "invalid"
    if alias == ".":
        root = project.root
    else:
        declared = project.settings.get("repos")
        if not isinstance(declared, dict) or alias not in declared:
            problems.append(check("unknown-alias", "error", "%s: %s is not a repository in the project's repos" % (key, alias), stage=key, args={"stage": key, "alias": alias}))
            return alias, None, None, "invalid"
        root = resolve(project.checkouts.get(alias))
        if root is None or not is_dir(root):
            problems.append(check("no-checkout", "warn", "%s: the %s repository has no local checkout on this machine; add its path to ~/.corthex/projects.json" % (key, alias), stage=key, args={"stage": key, "alias": alias}))
            return alias, None, None, "no-checkout"
    root = root.resolve()
    target = (root / rel).resolve() if rel not in ("", ".") else root
    if not inside(target, root):
        problems.append(check("source-outside", "error", "%s: the source %s points outside its repository" % (key, source), stage=key, args={"stage": key, "source": source}))
        return alias, root, None, "invalid"
    return alias, root, target, "found" if target.exists() else "missing"


def check(rule, level, message, refs=(), stage=None, args=None, by="scan"):
    entry = {"rule": rule, "level": level, "message": one_line(message, 600), "by": by}
    if stage:
        entry["stage"] = stage
    refs = sorted(set(refs), key=id_key)
    if refs:
        entry["refs"] = refs[:50]
    if args:
        entry["args"] = args
    return entry


def read_stages(project, scan, problems):
    stages = {}
    settings = project.settings.get("stages")
    settings = settings if isinstance(settings, dict) else {}
    for key, name, default, kinds, readable in STAGES:
        given = settings.get(key) if isinstance(settings.get(key), dict) else None
        stage = {"name": name, "truth": "source"}
        if given:
            for field in ("human", "truth"):
                value = one_line(given.get(field), 40)
                if value:
                    stage[field] = value
            link = web_link(given.get("link")) if isinstance(given.get("link"), str) else ""
            if link:
                stage["link"] = link
            note = one_line(given.get("note"))
            if note:
                stage["note"] = note
        stages[key] = stage
        if given and given.get("skip") is True:
            stage["skip"] = True
            stage["source_state"] = "skipped"
            continue
        # Only a stage without an entry takes the default path; an entry, even
        # an empty one, is read from its own `source` or not at all.
        source = given.get("source") if given is not None else default
        if not isinstance(source, str) or not source.strip():
            stage["source_state"] = "none"
            continue
        stage["source"] = one_line(shown_source(source.strip()), 200)
        if given is None:
            stage["default_source"] = True
        alias, root, target, state = locate(source.strip(), project, problems, key)
        stage["source_state"] = state
        if alias != ".":
            stage["repo"] = alias
        if state == "missing" and given is not None:
            problems.append(check("source-missing", "warn", "%s: the source %s does not exist" % (key, source), stage=key, args={"stage": key, "source": source}))
        if state != "found" or not readable:
            continue
        skipped = {}
        files = source_files(target, root, skipped)
        stage["read"] = True
        stage["files"] = len(files)
        for path in files:
            text = read_text(path)
            if text is None:
                skipped["unreadable"] = skipped.get("unreadable", 0) + 1
                continue
            rel = path.resolve().relative_to(root).as_posix()
            scan_file(scan, Source(key, kinds, alias, rel), text)
        if skipped:
            stage["skipped"] = skipped
            noted = {reason: count for reason, count in skipped.items() if reason != "format"}
            if noted:
                total = sum(noted.values())
                reasons = ", ".join("%d %s" % (count, reason) for reason, count in sorted(noted.items()))
                problems.append(check("files-skipped", "info", "%s: files not read (%d): %s" % (key, total, reasons), stage=key, args={"stage": key, "count": total, "reasons": noted}))
    for key, times in scan.copied.items():
        stages[key]["copied"] = {"oldest": min(times), "newest": max(times)}
    return stages


def build_items(scan):
    items = {}
    for ident, defs in scan.defs.items():
        strong = [d for d in defs if d["strong"]]
        main = strong[0] if strong else defs[0]
        ordered = [main] + [d for d in strong + defs if d is not main]
        item = {"id": ident, "kind": main["kind"], "stage": main["stage"], "where": main["where"]}
        for field in ("title", "status", "type", "priority", "link", "parent"):
            value = next((d[field] for d in ordered if d.get(field)), "")
            if value:
                item[field] = value
        if ident in scan.screen_docs:
            item["screen_doc"] = scan.screen_docs[ident]
        if ident in scan.states:
            item["states"] = sorted(scan.states[ident])
        links = sorted(scan.links.get(ident, ()), key=id_key)
        if links:
            item["links"] = links[:MAX_LINKS]
        items[ident] = item
    return items


def neighbours(items, scan):
    """IDs linked to each ID in either direction."""
    result = {}
    for source, targets in scan.links.items():
        for target in targets:
            result.setdefault(source, set()).add(target)
            result.setdefault(target, set()).add(source)
    return result


def is_removed(item):
    return any(word in REMOVED for word in norm(item.get("status", "")).split())


def item_checks(scan, items, stages):
    """Checks that need the whole project: duplicates, unknown IDs and missing links."""
    found = []
    scanned = {key for key, stage in stages.items() if stage.get("read") and stage.get("files")}
    kinds_with_items = {item["kind"] for item in items.values()}
    for ident, defs in sorted(scan.defs.items(), key=lambda pair: id_key(pair[0])):
        places = []
        for entry in defs:
            if entry["strong"] and entry["where"] not in places:
                places.append(entry["where"])
        if len(places) > 1:
            found.append(check("duplicate-id", "error", "%s is defined more than once: %s" % (ident, ", ".join(places[:MAX_PLACES])), [ident], defs[0]["stage"], {"id": ident, "places": places[:MAX_PLACES]}))
    for ident in sorted(scan.mentions, key=id_key):
        kind = scan.ids.kind(ident)
        stage = DEFINED_IN.get(kind)
        if ident in items or stage not in scanned:
            continue
        places = scan.mentions[ident]
        found.append(check("unknown-ref", "warn", "%s is mentioned but not defined in %s: %s" % (ident, stage, ", ".join(places)), [ident], stage, {"id": ident, "stage": stage, "places": places}))
    near = neighbours(items, scan)
    for ident in sorted(items, key=id_key):
        item = items[ident]
        kind = item["kind"]
        if is_removed(item):
            continue
        if kind == "screen" and item["stage"] == SCREEN_STAGE and "07-sitemap" in scanned:
            found.append(check("screen-not-in-sitemap", "warn", "%s has a screen definition but is not in the sitemap" % ident, [ident], SCREEN_STAGE, {"id": ident}))
        wanted = [k for k in UPSTREAM.get(kind, ()) if k in kinds_with_items]
        linked = {scan.ids.kind(other) for other in near.get(ident, ())}
        if wanted and not linked.intersection(UPSTREAM[kind]):
            names = "/".join(UPSTREAM[kind])
            found.append(check("missing-upstream", "warn", "%s links no %s" % (ident, names), [ident], item["stage"], {"id": ident, "kinds": list(UPSTREAM[kind])}))
    found.extend(requirement_checks(scan, items, near, scanned))
    found.extend(format_checks(scan, items))
    if SCREEN_STAGE in scanned:
        bare = [i for i, item in items.items() if item["kind"] == "screen" and "screen_doc" not in item and not is_removed(item)]
        if bare:
            bare.sort(key=id_key)
            found.append(check("screen-without-states", "info", "Screens without a screen definition yet (%d): %s" % (len(bare), ", ".join(bare[:20])), bare, SCREEN_STAGE, {"count": len(bare), "ids": bare[:20]}))
    return found


def requirement_checks(scan, items, near, scanned):
    found = []
    requirements = [items[i] for i in sorted(items, key=id_key) if items[i]["kind"] == "requirement"]
    in_scope = [r for r in requirements if not is_removed(r) and norm(r.get("type", "")) not in OUT_OF_SCOPE]
    if "04-functional-spec" in scanned:
        for req in in_scope:
            if norm(req.get("priority", "")) not in MUST or norm(req.get("type", "")) in NON_FUNCTIONAL:
                continue
            if any(scan.ids.kind(other) == "spec" for other in near.get(req["id"], ())):
                continue
            unknown = not req.get("type")
            message = "%s is a %sMust requirement with no spec row" % (req["id"], "" if unknown else "functional ")
            found.append(check("req-without-spec", "warn", message + (" (its type is not set)" if unknown else ""), [req["id"]], "04-functional-spec", {"id": req["id"], "type_unknown": unknown}))
    if any(r.get("priority") for r in requirements):
        bare = [r["id"] for r in in_scope if not r.get("priority")]
        if bare:
            found.append(check("req-without-priority", "info", "Requirements without a priority (%d): %s" % (len(bare), ", ".join(bare[:20])), bare, "02-prd", {"count": len(bare), "ids": bare[:20]}))
    return found


def format_checks(scan, items):
    found = []
    for prefix, first, second in scan.ids.clashes:
        found.append(check("id-config", "warn", "The prefix %s is set for both %s and %s; it counts as %s" % (prefix, first, second, first), args={"prefix": prefix, "kinds": [first, second]}))
    seen = set(items) | set(scan.mentions)
    for kind, digits in sorted(scan.ids.digits.items()):
        odd = sorted((i for i in seen if scan.ids.kind(i) == kind and len(i.rpartition("-")[2]) != digits), key=id_key)
        if odd:
            sample = "%s-%s" % (next(p for p, k in scan.ids.kind_of.items() if k == kind), "0" * digits)
            found.append(check("id-format", "info", "IDs not in the format %s (%d): %s" % (sample, len(odd), ", ".join(odd[:20])), odd, DEFINED_IN.get(kind), {"kind": kind, "format": sample, "count": len(odd), "ids": odd[:20]}))
    return found


def stage_status(status, key):
    entry = (status or {}).get("stages", {}).get(key)
    return entry if isinstance(entry, dict) else {}


def apply_status(stages, status, ids):
    """Copy recorded progress and review checks into the stages; returns the review checks."""
    found = []
    for key, stage in stages.items():
        entry = stage_status(status, key)
        state = entry.get("state")
        stage["state"] = state if state in STATES else "skipped" if stage.get("skip") else "unknown"
        for field in ("checkpoint", "checkpoint_date", "next", "updated"):
            value = one_line(entry.get(field), 300)
            if value:
                stage[field] = value
        reviews = entry.get("checks")
        for review in reviews if isinstance(reviews, list) else ():
            if not isinstance(review, dict) or review.get("level") not in LEVELS:
                continue
            message = one_line(review.get("message"), 600)
            if message:
                refs = [ident for ident, _, _ in ids.find(message)]
                entry_check = check("review", review["level"], message, refs, key, by="review")
                if one_line(review.get("at"), 40):
                    entry_check["at"] = one_line(review.get("at"), 40)
                found.append(entry_check)
    return found


def stage_order(item):
    return (STAGE_KEYS.index(item["stage"]) if item["stage"] in STAGE_KEYS else 99,) + id_key(item["id"])


def make_snapshot(project, status=None, now=None):
    """The snapshot of one project: settings, repositories, stages, items and checks."""
    settings = project.settings
    ids = IdFormat(settings.get("ids"))
    scan = Scan(ids)
    problems = []
    stages = read_stages(project, scan, problems)
    items = build_items(scan)
    for key, stage in stages.items():
        if stage.get("read"):
            stage["items"] = sum(1 for item in items.values() if item["stage"] == key)
    if stages[SCREEN_STAGE].get("read"):
        stages[SCREEN_STAGE]["items"] = len(scan.screen_docs)
    checks = problems + item_checks(scan, items, stages) + apply_status(stages, status, ids)
    checks.sort(key=lambda c: (LEVELS.index(c["level"]), STAGE_KEYS.index(c["stage"]) if c.get("stage") in STAGE_KEYS else 99))
    ordered = sorted(items.values(), key=stage_order)
    records = settings.get("records") if isinstance(settings.get("records"), dict) else {}
    snapshot = {
        "schema": SCHEMA,
        "generator": "corthex-nexus " + VERSION,
        "generated_at": now or now_text(),
        "project": {
            "name": project.name,
            "title": one_line(settings.get("title"), 120) or project.name,
            "team": settings.get("team") is True,
            "language": one_line(settings.get("language"), 20),
            "records": {
                "kind": one_line(records.get("kind"), 20),
                "link": web_link(records.get("location")) if isinstance(records.get("location"), str) else "",
            },
        },
        "ids": dict(sorted(ids.kind_of.items())),
        "repos": repos_of(project),
        "stages": stages,
        "items": ordered,
        "checks": checks,
        "summary": summary(ordered, checks, stages),
        "truncated": False,
    }
    return fit(snapshot)


def repos_of(project):
    """Commit and web address of the project's repository and of each declared other one."""
    repos = {".": repo_info(project.root)}
    declared = project.settings.get("repos")
    for alias, url in sorted(declared.items()) if isinstance(declared, dict) else ():
        if not isinstance(alias, str) or not ALIAS.match(alias):
            continue
        url = url if isinstance(url, str) else ""
        root = resolve(project.checkouts.get(alias))
        if root and is_dir(root):
            repos[alias] = repo_info(root, url)
            continue
        info = {"checkout": False}
        if web_link(url):
            info["url"] = web_link(url)
        if github_base(url):
            info["web"] = github_base(url)
        repos[alias] = info
    return repos


def summary(items, checks, stages):
    kinds = {}
    for item in items:
        kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
    states = {}
    for stage in stages.values():
        states[stage["state"]] = states.get(stage["state"], 0) + 1
    return {
        "items": len(items),
        "kinds": kinds,
        "checks": {level: sum(1 for c in checks if c["level"] == level) for level in LEVELS},
        "states": states,
    }


def fit(snapshot):
    """Keep a snapshot under the size limits by dropping items, then checks, from the end."""
    items, checks = snapshot["items"], snapshot["checks"]
    shown_items, shown_checks = min(len(items), MAX_ITEMS), min(len(checks), MAX_CHECKS)
    while True:
        cut = shown_items < len(items) or shown_checks < len(checks)
        notice = [truncation(shown_items, len(items), shown_checks, len(checks))] if cut else []
        result = dict(snapshot, items=items[:shown_items], checks=notice + checks[:shown_checks], truncated=cut)
        if len(dump(result, compact=True).encode("utf-8")) <= MAX_SNAPSHOT_BYTES:
            return result
        if shown_items:
            shown_items = shown_items * 3 // 4
        elif shown_checks:
            shown_checks = shown_checks * 3 // 4
        else:
            raise ValueError("%s: the project's settings alone are over the snapshot size limit" % snapshot["project"]["name"])


def truncation(shown_items, total_items, shown_checks, total_checks):
    parts = []
    if shown_items < total_items:
        parts.append("%d of %d items" % (shown_items, total_items))
    if shown_checks < total_checks:
        parts.append("%d of %d checks" % (shown_checks, total_checks))
    return check(
        "truncated", "warn", "The snapshot was cut to %s to stay under the size limit" % " and ".join(parts),
        args={"shown": shown_items, "total": total_items, "checks_shown": shown_checks, "checks_total": total_checks},
    )


# ---------------------------------------------------------------- stored files

def status_path(home, name):
    return hub_dir(home) / "status" / (name + ".json")


def snapshot_path(home, name):
    return hub_dir(home) / "snapshots" / (name + ".json")


def load_status(home, name):
    return load_json(status_path(home, name)) or {"project": name, "stages": {}}


def save_snapshot(home, snapshot):
    path = snapshot_path(home, snapshot["project"]["name"])
    write_file(path, dump(snapshot))
    return path


def stored_snapshots(home):
    folder = hub_dir(home) / "snapshots"
    result = {}
    if not is_dir(folder):
        return result
    for path in sorted(folder.glob("*.json")):
        data = load_json(path)
        if data and data.get("schema") == SCHEMA and isinstance(data.get("project"), dict):
            name = data["project"].get("name")
            if isinstance(name, str) and NAME.match(name):
                result[name] = data
    return result


def record_status(home, name, stage, state=None, checkpoint=None, date=None, next_action=None,
                  checks=(), clear_checks=False, reset=False, now=None):
    """Update one stage in ~/.corthex/hub/status/<name>.json and return its entry."""
    if not NAME.match(name or ""):
        raise ValueError("the project name must be lowercase letters, digits and hyphens")
    if stage not in STAGE_KEYS:
        raise ValueError("unknown stage %s; use one of %s" % (stage, ", ".join(STAGE_KEYS)))
    if state is not None and state not in STATES:
        raise ValueError("the state must be one of %s" % ", ".join(STATES))
    if date is not None and not DATE.match(date):
        raise ValueError("the date must start with YYYY-MM-DD")
    for level, message in checks:
        if level not in LEVELS:
            raise ValueError("a check level must be one of %s" % ", ".join(LEVELS))
        if not one_line(message):
            raise ValueError("a check needs a message")
    now = now or now_text()
    data = load_status(home, name)
    stages = data.setdefault("stages", {})
    if not isinstance(stages, dict):
        stages = data["stages"] = {}
    if reset:
        stages.pop(stage, None)
        entry = {}
    else:
        entry = stages.setdefault(stage, {})
        if state is not None:
            entry["state"] = state
        if checkpoint is not None:
            entry["checkpoint"] = one_line(checkpoint)
        if date is not None:
            entry["checkpoint_date"] = date
        if next_action is not None:
            entry["next"] = one_line(next_action)
        if clear_checks:
            entry.pop("checks", None)
        for level, message in checks:
            entry.setdefault("checks", []).append({"level": level, "message": one_line(message, 600), "at": now[:10]})
        if entry.get("state") == "done" and not (entry.get("checkpoint") and DATE.match(entry.get("checkpoint_date") or "")):
            raise ValueError("record done with its checkpoint: --checkpoint (what was approved, by whom, where) and --date")
        entry["updated"] = now
    data["project"] = name
    path = status_path(home, name)
    if is_file(path):
        write_file(path.with_name(path.name + ".bak"), path.read_text(encoding="utf-8"))
    write_file(path, dump(data))
    return entry


# ---------------------------------------------------------------- the page

def profile_of(home):
    return load_json(home / ".corthex" / "profile.json") or {}


def page_data(home, snapshots, missing, now=None):
    language = one_line(profile_of(home).get("language"), 20)
    return {
        "schema": PAGE_SCHEMA,
        "generated_at": now or now_text(),
        "lang": "ko" if language.lower().startswith("ko") else "en",
        "origin": "local",
        "projects": snapshots,
        "missing": missing,
    }


def render_page(data, template=TEMPLATE):
    """The hub page: the template with the data in a JSON script block."""
    with open(template, encoding="utf-8") as handle:
        page = handle.read()
    if page.count(PLACEHOLDER) != 1:
        raise ValueError("the hub template must hold %s exactly once" % PLACEHOLDER)
    payload = dump(data, compact=True)
    # Inside <script>, "<" could end the block; JSON allows these escapes.
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return page.replace(PLACEHOLDER, payload)


def build_hub(home, names=(), out=None, scan=True, now=None):
    """Refresh the snapshots, then write the hub page. Returns (path, snapshots, notes)."""
    notes = []
    entries = registered(home)
    wanted = list(names) or [entry["name"] for entry in entries]
    if scan and wanted:
        for name, project, reason in select_projects(home, wanted):
            if project is None:
                notes.append("%s: %s" % (name, reason))
                continue
            snapshot = make_snapshot(project, load_status(home, project.name), now)
            save_snapshot(home, snapshot)
    stored = stored_snapshots(home)
    snapshots = [stored[n] for n in wanted if n in stored]
    if not names:
        for name in sorted(n for n in stored if n not in wanted):
            notes.append("%s: left off the page because it is not in ~/.corthex/projects.json; its saved snapshot stays in %s" % (name, snapshot_path(home, name).parent))
    missing = [{"name": n, "reason": "no snapshot"} for n in wanted if n not in stored]
    path = Path(out).expanduser().resolve() if out else hub_dir(home) / "index.html"
    write_file(path, render_page(page_data(home, snapshots, missing, now)))
    return path, snapshots, notes


# ---------------------------------------------------------------- push

class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Cloudflare Access answers a refused token with a redirect to its login page."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def nexus_url(raw):
    """The server address, checked: https, or http only for this machine."""
    parts = urllib.parse.urlsplit((raw or "").strip())
    local = parts.hostname in ("localhost", "127.0.0.1", "::1")
    if parts.scheme not in ("https", "http") or not parts.hostname or (parts.scheme == "http" and not local):
        raise ValueError("the NEXUS address must start with https://")
    if parts.username or parts.password:
        raise ValueError("put the service token in environment variables, not in the address")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", "")), local


def nexus_settings(home, url, env):
    """The server address, whether it is on this machine, and the projects that may be sent."""
    settings = profile_of(home).get("nexus")
    settings = settings if isinstance(settings, dict) else {}
    address = url or env.get("CORTHEX_NEXUS_URL") or settings.get("url")
    if not isinstance(address, str) or not address.strip():
        raise ValueError("no NEXUS address: set nexus.url in ~/.corthex/profile.json, CORTHEX_NEXUS_URL or --url")
    base, local = nexus_url(address)
    listed = settings.get("push")
    allowed = [n for n in listed if isinstance(n, str)] if isinstance(listed, list) else []
    return base, local, allowed


def service_token(env, local, dry_run):
    client_id = env.get("CORTHEX_NEXUS_CLIENT_ID", "")
    secret = env.get("CORTHEX_NEXUS_CLIENT_SECRET", "")
    if not (client_id and secret) and not local and not dry_run:
        raise ValueError("set CORTHEX_NEXUS_CLIENT_ID and CORTHEX_NEXUS_CLIENT_SECRET to the service token")
    return (client_id, secret) if client_id and secret else None


def nexus_request(base, path, method, token, body=None):
    request = urllib.request.Request(base + path, data=body, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", "corthex-nexus/" + VERSION)
    if token:
        request.add_header("CF-Access-Client-Id", token[0])
        request.add_header("CF-Access-Client-Secret", token[1])
    return request


def nexus_opener(local):
    handlers = [NoRedirect()] + ([urllib.request.ProxyHandler({})] if local else [])
    return urllib.request.build_opener(*handlers)


def push(home, names=(), url=None, dry_run=False, env=None, timeout=30):
    """Send the stored snapshots of opted-in projects. Returns a list of result lines."""
    env = os.environ if env is None else env
    base, local, allowed = nexus_settings(home, url, env)
    chosen = list(names) or allowed
    refused = [n for n in chosen if n not in allowed]
    if refused:
        raise ValueError("add %s to nexus.push in ~/.corthex/profile.json before sending it" % ", ".join(refused))
    if not chosen:
        raise ValueError("no project is listed in nexus.push in ~/.corthex/profile.json")
    stored = stored_snapshots(home)
    missing = [n for n in chosen if n not in stored]
    if missing:
        raise ValueError("no snapshot for %s yet; run `hub.py snapshot` or `hub.py build` first" % ", ".join(missing))
    token = service_token(env, local, dry_run)
    opener = nexus_opener(local)
    lines = []
    for name in chosen:
        body = dump(stored[name], compact=True).encode("utf-8")
        if dry_run:
            lines.append("%s: would send %d bytes to %s/api/snapshots" % (name, len(body), base))
            continue
        code, reply = send(opener, nexus_request(base, "/api/snapshots", "POST", token, body), timeout)
        try:
            revision = json.loads(reply).get("revision")
        except (ValueError, AttributeError):
            revision = None
        lines.append("%s: sent, HTTP %d%s" % (name, code, ", revision %s" % revision if isinstance(revision, int) else ""))
    return lines


def remove(home, names, url=None, dry_run=False, env=None, timeout=30):
    """Remove projects from the NEXUS server. Returns a list of result lines."""
    env = os.environ if env is None else env
    base, local, _ = nexus_settings(home, url, env)
    names = list(names)
    if not names:
        raise ValueError("name the projects to remove from the server")
    wrong = [n for n in names if not isinstance(n, str) or not NAME.match(n)]
    if wrong:
        raise ValueError("%s is not a project name" % ", ".join(str(n) for n in wrong))
    token = service_token(env, local, dry_run)
    opener = nexus_opener(local)
    lines = []
    for name in names:
        if dry_run:
            lines.append("%s: would remove it from %s" % (name, base))
            continue
        try:
            send(opener, nexus_request(base, "/api/snapshots/" + name, "DELETE", token), timeout)
        except ServerRefused as error:
            if error.code == 404 and error.reason:
                lines.append("%s: not on the server" % name)
                continue
            raise
        lines.append("%s: removed from the server" % name)
    return lines


class ServerRefused(RuntimeError):
    """A request the server or Cloudflare Access did not accept."""

    def __init__(self, message, code, reason=""):
        RuntimeError.__init__(self, message)
        self.code = code
        self.reason = reason


def server_reason(error):
    """The reason a NEXUS server gave, from its JSON reply, on one line and
    without control characters, since it is printed to the terminal."""
    try:
        reply = json.loads(error.read(4096).decode("utf-8", "replace"))
    except (ValueError, OSError, AttributeError):
        return ""
    reason = reply.get("error") if isinstance(reply, dict) else None
    return one_line(CONTROL.sub(" ", reason), 300) if isinstance(reason, str) else ""


def send(opener, request, timeout):
    """Send one request. Returns (status, reply text) or raises ServerRefused."""
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.getcode(), response.read(4096).decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        reason = server_reason(error)
        if reason:
            raise ServerRefused("the server refused it (HTTP %d): %s" % (error.code, reason), error.code, reason)
        if error.code in (301, 302, 303, 307, 308, 401, 403):
            raise ServerRefused("the server refused the service token (HTTP %d); check the token and the Access policy" % error.code, error.code)
        raise ServerRefused("the server answered HTTP %d" % error.code, error.code)
    except (urllib.error.URLError, OSError) as error:
        raise RuntimeError("could not reach the server (%s)" % type(error).__name__)


# ---------------------------------------------------------------- command line

def counts_line(snapshot):
    found = snapshot["summary"]["checks"]
    return "%s: %d items, %d errors, %d warnings, %d notes" % (
        snapshot["project"]["name"], snapshot["summary"]["items"], found["error"], found["warn"], found["info"],
    )


def repo_args(values):
    extra = {}
    for value in values or ():
        alias, sep, path = value.partition("=")
        if not sep or not ALIAS.match(alias) or not path:
            raise ValueError("--repo takes ALIAS=FOLDER, such as design=../acme-design")
        extra[alias] = str(Path(path).expanduser().resolve())
    return extra


def run_snapshot(args, home):
    results = select_projects(home, args.project, args.path, repo_args(args.repo))
    status = 0
    for name, project, reason in results:
        if project is None:
            say("%s: %s" % (name or "project", reason), sys.stderr)
            status = 1
            continue
        snapshot = make_snapshot(project, load_status(home, project.name))
        if args.print:
            sys.stdout.buffer.write(dump(snapshot).encode("utf-8"))
            sys.stdout.flush()
            continue
        path = save_snapshot(home, snapshot)
        say(counts_line(snapshot))
        say("  saved %s" % path)
    return status


def run_status(args, home):
    entry = record_status(
        home, args.project, args.stage, args.state, args.checkpoint, args.date, getattr(args, "next"),
        args.check or (), args.clear_checks, args.reset,
    )
    if not entry:
        say("%s %s: status removed" % (args.project, args.stage))
    else:
        say("%s %s: %s" % (args.project, args.stage, entry.get("state", "state not set")))
    return 0


def run_build(args, home):
    path, snapshots, notes = build_hub(home, args.project, args.out, scan=not args.no_scan)
    for note in notes:
        say(note, sys.stderr)
    for snapshot in snapshots:
        say(counts_line(snapshot))
    say("Hub page: %s" % path)
    return 0


def run_push(args, home):
    for line in push(home, args.project, args.url, args.dry_run):
        say(line)
    return 0


def run_remove(args, home):
    for line in remove(home, args.project, args.url, args.dry_run):
        say(line)
    return 0


def parser():
    top = argparse.ArgumentParser(prog="hub.py", description="CORTHEX hub: stages, checks and trace links of your projects.")
    top.add_argument("--home", help="the folder that holds .corthex (default: your home folder)")
    top.add_argument("--version", action="version", version="corthex-nexus " + VERSION)
    commands = top.add_subparsers(dest="command", required=True)

    snap = commands.add_parser("snapshot", help="read a project's stage sources and save a snapshot")
    snap.add_argument("project", nargs="*", help="registered project names (default: the project of the current folder)")
    snap.add_argument("--path", help="read the project in this folder instead")
    snap.add_argument("--repo", action="append", metavar="ALIAS=FOLDER", help="local checkout of another repository of the project")
    snap.add_argument("--print", action="store_true", help="print the snapshot instead of saving it")

    stat = commands.add_parser("status", help="record a stage's progress, last checkpoint and next action")
    stat.add_argument("project")
    stat.add_argument("stage", choices=STAGE_KEYS)
    stat.add_argument("--state", choices=STATES)
    stat.add_argument("--checkpoint", help="the last human checkpoint: what was approved, by whom, where")
    stat.add_argument("--date", help="the date of that checkpoint, YYYY-MM-DD")
    stat.add_argument("--next", help="the next action")
    stat.add_argument("--check", nargs=2, action="append", metavar=("LEVEL", "MESSAGE"), help="add a review finding; LEVEL is error, warn or info")
    stat.add_argument("--clear-checks", action="store_true", help="remove this stage's review findings first")
    stat.add_argument("--reset", action="store_true", help="remove everything recorded for this stage")

    build = commands.add_parser("build", help="refresh the snapshots and write the hub page")
    build.add_argument("project", nargs="*", help="only these registered projects (default: all)")
    build.add_argument("--out", help="write the page here (default: ~/.corthex/hub/index.html)")
    build.add_argument("--no-scan", action="store_true", help="use the saved snapshots without reading the projects again")

    send_cmd = commands.add_parser("push", help="send saved snapshots to your own NEXUS server")
    send_cmd.add_argument("project", nargs="*", help="projects to send (default: all in nexus.push)")
    send_cmd.add_argument("--url", help="the server address (default: CORTHEX_NEXUS_URL, then nexus.url in the profile)")
    send_cmd.add_argument("--dry-run", action="store_true", help="show what would be sent without sending it")

    drop = commands.add_parser("remove", help="remove projects from your own NEXUS server")
    drop.add_argument("project", nargs="+", help="projects to remove from the server")
    drop.add_argument("--url", help="the server address (default: CORTHEX_NEXUS_URL, then nexus.url in the profile)")
    drop.add_argument("--dry-run", action="store_true", help="show what would be removed without removing it")
    return top


def main(argv=None):
    args = parser().parse_args(argv)
    home = Path(args.home).expanduser().resolve() if args.home else Path.home()
    commands = {"snapshot": run_snapshot, "status": run_status, "build": run_build, "push": run_push, "remove": run_remove}
    try:
        return commands[args.command](args, home)
    except (ValueError, RuntimeError) as error:
        say("hub.py %s: %s" % (args.command, error), sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
