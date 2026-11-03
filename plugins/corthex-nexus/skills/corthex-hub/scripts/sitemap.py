"""Read the stage-07 YAML list form using only the Python standard library.

This deliberately supports the documented form, not YAML tags, constructors,
aliases, executable expressions or a general-purpose YAML implementation.
"""
import json
import re


class Invalid(ValueError):
    def __init__(self, line, message):
        self.line = line
        super().__init__(message)


def uncomment(text):
    quoted, escaped = None, False
    for i, c in enumerate(text):
        if quoted == '"' and c == "\\" and not escaped:
            escaped = True
            continue
        if c in "\"'" and not escaped:
            if quoted == c:
                quoted = None
            elif quoted is None:
                quoted = c
        if c == "#" and quoted is None and (i == 0 or text[i - 1].isspace()):
            return text[:i].rstrip()
        escaped = False
    return text.rstrip()


def scalar(text, line):
    text = text.strip()
    if not text:
        return None
    if text[0] in "!&*{|>" or text.startswith("<<:"):
        raise Invalid(line, "YAML is outside the stage-07 template form")
    if text.startswith('"'):
        try:
            value = json.loads(text)
        except ValueError:
            raise Invalid(line, "invalid double-quoted YAML scalar")
        if not isinstance(value, str):
            raise Invalid(line, "expected a text scalar")
        return value
    if text.startswith("'"):
        if not text.endswith("'") or len(text) < 2:
            raise Invalid(line, "unterminated single-quoted YAML scalar")
        return text[1:-1].replace("''", "'")
    if text.startswith("["):
        if not text.endswith("]"):
            raise Invalid(line, "unterminated inline YAML list")
        contents = text[1:-1].strip()
        values, current, quote, escaped = [], [], None, False
        for c in contents + ",":
            if c == "," and quote is None:
                if "".join(current).strip():
                    values.append(scalar("".join(current), line))
                current = []
                continue
            current.append(c)
            if c in "\"'" and not escaped:
                quote = None if quote == c else c if quote is None else quote
            escaped = c == "\\" and not escaped
        if quote:
            raise Invalid(line, "unterminated quoted list value")
        return values
    if re.search(r"\s:\s", text):
        raise Invalid(line, "a colon in a scalar needs quotes")
    return text


def read_yaml(text):
    lines = []
    for number, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw[:len(raw) - len(raw.lstrip())]:
            raise Invalid(number, "tabs cannot indent the template")
        clean = uncomment(raw)
        if not clean.strip() or clean.strip() in ("---", "..."):
            continue
        lines.append((len(clean) - len(clean.lstrip()), clean.strip(), number))

    def pair(text, line):
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_-]*):(?:\s+(.*)|\s*)", text)
        if not match:
            raise Invalid(line, "expected a template key and colon")
        return match.group(1), match.group(2) or ""

    def entry(result, key, raw, i, indent, line):
        if key in result:
            raise Invalid(line, "duplicate YAML key")
        if raw:
            result[key] = scalar(raw, line)
        elif i < len(lines) and lines[i][0] > indent:
            result[key], i = block(i, lines[i][0])
        else:
            result[key] = None
        return i

    def block(i, indent):
        sequence = lines[i][1].startswith("- ") or lines[i][1] == "-"
        result = [] if sequence else {}
        while i < len(lines) and lines[i][0] == indent:
            _, text, line = lines[i]
            if sequence:
                if not text.startswith("- "):
                    raise Invalid(line, "mixed sequence and mapping")
                rest = text[2:]
                i += 1
                if re.match(r"[A-Za-z_][A-Za-z0-9_-]*:", rest):
                    item = {"__line__": line}
                    key, raw = pair(rest, line)
                    i = entry(item, key, raw, i, indent + 2, line)
                    while i < len(lines) and lines[i][0] == indent + 2:
                        _, text, number = lines[i]
                        key, raw = pair(text, number)
                        i = entry(item, key, raw, i + 1, indent + 2, number)
                    result.append(item)
                else:
                    result.append(scalar(rest, line))
            else:
                key, raw = pair(text, line)
                i = entry(result, key, raw, i + 1, indent, line)
            if i < len(lines) and lines[i][0] > indent:
                raise Invalid(lines[i][2], "unexpected YAML indentation")
        return result, i

    if not lines:
        return []
    result, end = block(0, lines[0][0])
    if end != len(lines):
        raise Invalid(lines[end][2], "unexpected YAML indentation")
    if not isinstance(result, list):
        raise Invalid(lines[0][2], "the sitemap template is a list of screens")
    return result


def parse(documents, checks, h, part):
    picture = {"format": 1, "screens": [], "without_screen": []}
    read_files = 0

    def issue(file, line, message):
        row = h.check("picture-partial", "warn", file + ":" + str(line) + ": " + message, stage="07-sitemap")
        if part:
            row["part"] = part
        checks.append(row)

    for file, text in documents:
        for line in text.splitlines():
            marker = re.match(r"\s*#\s*without a screen\s*:\s*(.*)", line, re.I)
            if marker:
                picture["without_screen"].extend(x for x, kind, _ in h.picture_ids.find(marker.group(1)) if kind == "term")
        try:
            roots = read_yaml(text)
        except Invalid as error:
            issue(file, error.line, str(error))
            continue
        read_files += 1

        def walk(nodes, parent=None, depth=0):
            if depth > 100:
                issue(file, 1, "screen nesting exceeds 100 levels")
                return
            for node in nodes:
                if len(picture["screens"]) >= 500:
                    issue(file, 1, "more than 500 screens; later screens are omitted")
                    return
                if not isinstance(node, dict):
                    issue(file, 1, "a screen must be a mapping")
                    continue
                line = node.get("__line__", 1)
                trace = lambda text, kind: [x for x, found, _ in h.picture_ids.find(text) if found == kind]
                value = lambda key, limit=120: h.one_line(node.get(key), limit)
                ids = trace(value("id"), "screen")
                screen = {"id": ids[0] if ids else "", "name": value("name"), "path": value("path", 300), "access": value("access"),
                    "flows": [], "context": "", "removed": h.norm(value("status")) in h.REMOVED, "where": file + ":" + str(line)}
                flows = node.get("flows", [])
                if isinstance(flows, list):
                    screen["flows"] = list(dict.fromkeys(x for v in flows if isinstance(v, str) for x in trace(v, "flow")))[:50]
                elif flows is not None:
                    issue(file, line, "flows must be a list")
                if "terms" in node:
                    terms = node["terms"]
                    if isinstance(terms, list):
                        joined = " ".join(x for x in terms if isinstance(x, str))
                        contexts = trace(joined, "context")
                        screen["context"] = contexts[0] if contexts else ""
                        screen["terms"] = list(dict.fromkeys(trace(joined, "term")))[:20]
                    elif isinstance(terms, str) and terms.casefold() == "none":
                        screen["terms"] = []
                    else:
                        issue(file, line, "terms must be a list or none")
                if parent is not None:
                    screen["parent"] = parent
                index = len(picture["screens"])
                picture["screens"].append(screen)
                children = node.get("children", [])
                if isinstance(children, list):
                    walk(children, index, depth + 1)
                elif children is not None:
                    issue(file, line, "children must be a list")
        walk(roots)
    picture["without_screen"] = list(dict.fromkeys(picture["without_screen"]))[:500]
    return picture if read_files else None
