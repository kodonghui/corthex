#!/usr/bin/env python3
"""Check Mermaid flowcharts against the corthex-diagram visual grammar.

Reads `.mmd` and `.mermaid` files whole, the ```mermaid blocks of other files
such as Markdown, and standard input for `-`. Prints one summary line per
flowchart and one line per finding:

    <file>:<line>: <rule> <error|warn>: <message>

Exit status: 0 when no error was found, 1 when an error was found, 2 when a
file could not be read. Other diagram types are named and skipped. A flowchart
with `%% grammar: structure` draws a structure, not a flow: only its syntax,
Korean line breaks and colours are checked.

It only reads: it changes no file and sends nothing.
"""

import argparse
import re
import sys

GRAMMAR_VERSION = "1"

KINDS = {  # box kind -> Mermaid shapes that draw it
    "term": {"stadium", "terminal", "pill"},
    "doc": {"doc", "document"},
    "store": {"cyl", "cylinder", "db", "database", "das", "lin-cyl", "h-cyl", "horizontal-cylinder"},
    "proc": {"rect", "proc", "process", "rectangle"},
    "decide": {"diam", "diamond", "decision", "question"},
    "llm": {"fr-rect", "framed-rectangle", "subproc", "subprocess", "subroutine"},
    "grade": {"rect", "proc", "process", "rectangle"},
}
HINTS = {
    "term": "`@{ shape: stadium }` or `id([text])`",
    "doc": "`@{ shape: doc }`",
    "store": "`@{ shape: cyl }` or `id[(text)]`",
    "proc": "`@{ shape: rect }` or `id[text]`",
    "decide": "`@{ shape: diam }` or `id{text}`",
    "llm": "`@{ shape: fr-rect }` or `id[[text]]`",
    "grade": "`@{ shape: rect }` or `id[text]`",
}
MODIFIERS = {"key", "gap", "ghost"}
LINES = {"write", "read", "pass", "gradeLine"}
LINE_ARROW = {"write": "thick", "read": "thick", "pass": "normal", "gradeLine": "dotted"}
ARROW_FORM = {"thick": "==>", "normal": "-->", "dotted": "-.->"}
LEGEND_TITLES = {"legend", "범례"}
GAP_NOTES = ("not in the source", "원문에 없음", "원문에 따로 없음")
WRAP_DEFAULT = 120
MAX_TAGS = 3
NAMED_COLOURS = {
    "black": "000000", "white": "ffffff", "gray": "808080", "grey": "808080", "silver": "c0c0c0",
    "lightgray": "d3d3d3", "lightgrey": "d3d3d3", "darkgray": "a9a9a9", "darkgrey": "a9a9a9",
    "dimgray": "696969", "dimgrey": "696969", "red": "ff0000", "maroon": "800000", "orange": "ffa500",
    "yellow": "ffff00", "olive": "808000", "lime": "00ff00", "green": "008000", "aqua": "00ffff",
    "cyan": "00ffff", "teal": "008080", "blue": "0000ff", "navy": "000080", "fuchsia": "ff00ff",
    "magenta": "ff00ff", "purple": "800080",
}
NO_FILL = {"none", "transparent"}
CJK_RE = re.compile("[\u1100-\u11ff\u3040-\u30ff\u3130-\u318f\u3400-\u9fff\uac00-\ud7a3]")

# Classic node syntax, longest openers first.
BRACKETS = [
    ("(((", ")))", "dbl-circ"), ("([", "])", "stadium"), ("[(", ")]", "cyl"),
    ("[[", "]]", "fr-rect"), ("((", "))", "circle"), ("{{", "}}", "hex"),
    ("[/", "/]", "lean-r"), ("[\\", "\\]", "lean-l"), ("[/", "\\]", "trap-b"),
    ("[\\", "/]", "trap-t"), ("{", "}", "diam"), ("(", ")", "rounded"),
    ("[", "]", "rect"), (">", "]", "odd"),
]
ID = r"\w[\w-]*"
ARROW = r"<?(?:-{2,}|={2,}|-\.+-|-\.|~{3,})[>ox]?"
EDGE_RE = re.compile(r"(?:(" + ID + r")@)?(" + ARROW + r")(?:\s*\|([^|]*)\|)?")
OPEN_LABEL = {"--": r"-{2,}[>ox]?", "==": r"={2,}[>ox]?", "-.": r"\.-+[>ox]?"}
FLOWCHART_RE = re.compile(r"^\s*(?:flowchart|graph)\b", re.M)
DIAGRAM_RE = re.compile(r"^\s*([A-Za-z][\w-]*)", re.M)


def read_blocks(path, text):
    """Return (first line number, source) for each Mermaid block in a file."""
    if path == "-" or path.lower().endswith((".mmd", ".mermaid")):
        return [(1, text)]
    blocks = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r"\s*(`{3,}|~{3,})\s*mermaid\s*$", lines[i])
        if not m:
            i += 1
            continue
        fence, start, body = m.group(1), i + 2, []
        i += 1
        while i < len(lines) and not re.match(r"\s*" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}\s*$", lines[i]):
            body.append(lines[i])
            i += 1
        blocks.append((start, "\n".join(body)))
        i += 1
    return blocks


def label_width(text):
    """Rough width in px at Mermaid's default font, calibrated on Mermaid 12.1 renders."""
    width = 0.0
    for ch in re.sub(r"<[^>]+>", "", text):
        if CJK_RE.match(ch):
            width += 16
        elif ch == " ":
            width += 4
        else:
            width += 8.5
    return width


def split_top(text, seps):
    """Split text at characters in seps that are outside quotes and brackets."""
    parts, buf, depth, quote = [], [], 0, False
    for ch in text:
        if quote:
            buf.append(ch)
            quote = ch != '"'
            continue
        if ch == '"':
            quote = True
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0 and ch in seps:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))
    return parts


def arrow_family(arrow):
    if "~" in arrow:
        return "invisible"
    if "=" in arrow:
        return "thick"
    if "." in arrow:
        return "dotted"
    return "normal"


def split_chain(text):
    """Split one statement into node texts and edges: [node, edge, node, ...]."""
    parts, buf, i, depth, quote = [], [], 0, 0, False
    while i < len(text):
        ch = text[i]
        if quote:
            buf.append(ch)
            quote = ch != '"'
            i += 1
            continue
        if ch == '"':
            quote = True
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0:
            m = EDGE_RE.match(text, i)
            if m and (m.group(1) is None or i == 0 or text[i - 1] in " \t)]}"):
                eid, arrow, label = m.group(1), m.group(2), m.group(3)
                end = m.end()
                if arrow in OPEN_LABEL and m.group(3) is None:
                    close = re.compile(r"\s+(" + OPEN_LABEL[arrow] + r")(?=\s|$|\w)")
                    c = close.search(text, end)
                    if c:
                        label, arrow, end = text[end:c.start()].strip(), arrow + c.group(1), c.end()
                if len(arrow) >= 3:
                    parts.append("".join(buf))
                    parts.append({"id": eid, "arrow": arrow, "label": (label or "").strip()})
                    buf = []
                    i = end
                    continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def parse_node(token):
    """Return (id, shape or None, label or None, inline class or None) for one node text."""
    token = token.strip()
    m = re.match(r"(" + ID + r")\s*@\{(.*)\}\s*(:::\s*([\w-]+))?\s*$", token, re.S)
    if m:
        body = m.group(2)
        shape = re.search(r"\bshape:\s*\"?([\w-]+)", body)
        label = re.search(r"\blabel:\s*\"((?:[^\"\\]|\\.)*)\"", body) or re.search(r"\blabel:\s*([^,}]+)", body)
        return (m.group(1), shape.group(1) if shape else "rect", label.group(1).strip() if label else None,
                m.group(4), bool(m.group(3)))
    m = re.match(r"(" + ID + r")(.*?)(?::::\s*([\w-]+))?\s*$", token, re.S)
    if not m:
        return None
    nid, rest, cls = m.group(1), m.group(2).strip(), m.group(3)
    if not rest:
        return (nid, None, None, cls, False)
    for opener, closer, shape in BRACKETS:
        if rest.startswith(opener) and rest.endswith(closer) and len(rest) >= len(opener) + len(closer):
            inner = rest[len(opener):len(rest) - len(closer)].strip()
            if len(inner) >= 2 and inner[0] == '"' and inner[-1] == '"':
                inner = inner[1:-1]
            return (nid, shape, inner, cls, False)
    return (nid, None, None, cls, False)


def statements(src):
    """Yield (line number, statement) pairs with comments removed."""
    for no, raw in enumerate(src.splitlines(), 1):
        line = raw.strip()
        if line.startswith("%%"):
            continue
        line = re.sub(r"\s%%.*$", "", line)
        for part in split_top(line, ";"):
            part = part.strip()
            if part:
                yield no, part


def parse(src):
    diagram = {"nodes": {}, "edges": [], "classes": {}, "classdefs": {}, "styles": {},
               "subgraphs": [], "legend": set(), "wrap": WRAP_DEFAULT, "legend_below": False,
               "errors": [], "unread": [], "structure": False, "first": 1}
    front = re.match(r"\s*---\s*\n(.*?)\n---\s*\n", src, re.S)
    offset = 0
    if front:
        offset = src[:front.end()].count("\n")
        src = src[front.end():]
    width = re.search(r"wrappingWidth\"?\s*:\s*(\d+)", (front.group(1) if front else "") + src[:2000])
    if width:
        diagram["wrap"] = min(WRAP_DEFAULT, int(width.group(1)))
    diagram["legend_below"] = bool(re.search(r"%%\s*legend\s*:\s*below", src, re.I))
    diagram["structure"] = bool(re.search(r"%%\s*grammar\s*:\s*structure", src, re.I))
    nodes, classes = diagram["nodes"], diagram["classes"]
    stack = []
    seen_header = False
    in_description = False
    for no, line in statements(src):
        no += offset
        if not seen_header:
            seen_header = True
            diagram["first"] = no
            if FLOWCHART_RE.match(line):
                continue
        if in_description:  # the lines of a multi-line `accDescr { ... }`
            in_description = "}" not in line
            continue
        if re.match(r"accDescr\s*\{", line):
            in_description = "}" not in line.split("{", 1)[1]
            continue
        word = line.split()[0]
        if word in ("direction", "linkStyle", "click", "accTitle", "accDescr") or line.startswith(("accTitle:", "accDescr")):
            continue
        if word == "subgraph":
            m = re.match(r"subgraph\s+(" + ID + r")?\s*(?:\[\s*\"?(.*?)\"?\s*\])?\s*$", line)
            sid = m.group(1) if m and m.group(1) else line[len("subgraph"):].strip().strip('"')
            title = (m.group(2) if m and m.group(2) else sid).strip().strip('"')
            diagram["subgraphs"].append({"id": sid, "title": title, "line": no})
            stack.append(sid.lower() in LEGEND_TITLES or title.strip().lower() in LEGEND_TITLES)
            continue
        if line == "end":
            if stack:
                stack.pop()
            continue
        if word == "classDef":
            parts = line.split(None, 2)
            props = {}
            if len(parts) > 2:
                for prop in parts[2].split(","):
                    if ":" in prop:
                        key, value = prop.split(":", 1)
                        props[key.strip()] = value.strip()
            for name in parts[1].split(","):
                diagram["classdefs"][name.strip()] = {"props": props, "line": no}
            continue
        if word == "class":
            parts = line.split(None, 2)
            if len(parts) == 3:
                for ident in parts[1].split(","):
                    for cls in parts[2].split(","):
                        classes.setdefault(ident.strip(), set()).add(cls.strip())
            continue
        if word == "style":
            parts = line.split(None, 2)
            if len(parts) == 3:
                props = dict(p.split(":", 1) for p in parts[2].split(",") if ":" in p)
                diagram["styles"][parts[1]] = {"props": {k.strip(): v.strip() for k, v in props.items()}, "line": no}
            continue
        if re.match(ID + r"\s*@\{", line) and not re.search(r"\b(shape|label)\s*:", line) and not re.search(ARROW, line.split("}", 1)[-1]):
            continue  # line properties such as e1@{ animate: true }
        if re.search(r"@\{[^}]*\}\s*:::", line):
            diagram["errors"].append((no, "`@{ ... }:::class` does not parse in Mermaid 12; put the class on a `class` line"))
        in_legend = any(stack)
        parts = split_chain(line)
        previous = None
        unread = False
        for index, part in enumerate(parts):
            if isinstance(part, dict):
                continue
            current = []
            for token in split_top(part, "&"):
                if not token.strip():
                    continue
                node = parse_node(token)
                if node is None:
                    continue
                nid, shape, label, cls, _ = node
                entry = nodes.setdefault(nid, {"shape": None, "label": None, "line": no})
                if shape is not None:
                    entry["shape"], entry["label"], entry["line"] = shape, label, no
                if cls:
                    classes.setdefault(nid, set()).add(cls)
                if in_legend:
                    diagram["legend"].add(nid)
                current.append(nid)
            if previous is not None and index >= 2 and isinstance(parts[index - 1], dict):
                edge = parts[index - 1]
                for src_id in previous:
                    for dst_id in current:
                        diagram["edges"].append({"id": edge["id"], "src": src_id, "dst": dst_id, "arrow": edge["arrow"],
                                                 "family": arrow_family(edge["arrow"]), "label": edge["label"], "line": no,
                                                 "legend": in_legend})
            if current:
                previous = current
            elif part.strip():
                unread = True
        if unread:
            diagram["unread"].append((no, "the lint could not read this statement, so its boxes and lines are not "
                                          "checked; check that it renders"))
    subgraph_ids = {s["id"] for s in diagram["subgraphs"]}
    for sid in subgraph_ids:
        if sid in nodes and nodes[sid]["shape"] is None:
            del nodes[sid]
    for entry in nodes.values():
        if entry["shape"] is None:
            entry["shape"], entry["label"] = "rect", entry["label"]
    return diagram


def hex_rgb(value):
    """An RGB triple for a hex or basic named CSS colour, or None for anything else."""
    value = (value or "").replace("!important", "").strip().lower()
    value = NAMED_COLOURS.get(value, value).lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
        return None
    return [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def contrast(a, b):
    def luminance(rgb):
        rgb = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def tags_of(label):
    return re.findall(r"^\s*\[([^\]]+)\]", label or "")


def check(src, wrap=None):
    """Return (findings, boxes, lines); each finding is (line, rule, severity, message)."""
    d = parse(src)
    if wrap is not None:
        d["wrap"] = wrap
    out = [(no, "G0", "error", msg) for no, msg in d["errors"]]
    out += [(no, "G0", "warn", msg) for no, msg in d["unread"]]
    nodes, classes, edges = d["nodes"], d["classes"], d["edges"]
    ghosts = {nid for nid in nodes if "ghost" in classes.get(nid, set()) or nid in d["legend"]}
    kind_of = {}
    for nid, node in nodes.items():
        if nid in ghosts:
            continue
        cls = classes.get(nid, set())
        label = node["label"] or ""
        for part in re.split(r"<br\s*/?>", label):
            width = label_width(part)
            if CJK_RE.search(part) and width > d["wrap"] - 5:
                out.append((node["line"], "G6", "warn", "label line '{}' of {} is about {:.0f}px; Mermaid breaks Korean "
                            "lines near {}px, even inside a word; break it with <br/> between words or shorten it".format(
                                part.strip(), nid, width, d["wrap"])))
        if d["structure"]:
            continue
        if "gap" in cls and not any(note in label.lower() for note in GAP_NOTES):
            out.append((node["line"], "G11", "warn", "box {} is marked not in the source; say so in its label, "
                        "such as '(not in the source)'".format(nid)))
        kinds = sorted(c for c in cls if c in KINDS)
        if len(kinds) != 1:
            have = ", ".join(sorted(cls)) or "none"
            out.append((node["line"], "G1", "error", "box {} needs exactly one kind class of {}; it has {}. A diagram of "
                        "a structure rather than a flow says `%% grammar: structure`".format(
                            nid, ", ".join(sorted(KINDS)), have)))
            continue
        kind = kinds[0]
        kind_of[nid] = kind
        if node["shape"] not in KINDS[kind]:
            out.append((node["line"], "G2", "error", "box {} is {} but drawn as '{}'; draw it with {}".format(
                nid, kind, node["shape"], HINTS[kind])))
    if d["structure"]:
        out += colour_findings(d)
        out.sort(key=lambda f: (f[0], f[1]))
        return out, len([n for n in nodes if n not in ghosts]), len([e for e in edges if e["family"] != "invisible"])
    flow = [e for e in edges if not e["legend"] and e["src"] not in ghosts and e["dst"] not in ghosts
            and e["family"] != "invisible"]
    for e in flow:
        e["kind"] = next((c for c in sorted(classes.get(e["id"] or "", ())) if c in LINES), None)
    unclassed = []
    for e in flow:
        s, t = kind_of.get(e["src"]), kind_of.get(e["dst"])
        if s is None or t is None:
            continue
        name = "{}->{}".format(e["src"], e["dst"])
        want = "write" if t == "store" else "read" if s == "store" else None
        if want and e["kind"] != want:
            out.append((e["line"], "G3", "error", "line {} touches a store, so it is a '{}' line; it is '{}'".format(
                name, want, e["kind"] or "unmarked")))
        elif not want and e["kind"] in ("write", "read"):
            out.append((e["line"], "G3", "error", "line {} is '{}' but touches no store".format(name, e["kind"])))
        elif t == "grade" and e["kind"] != "gradeLine":
            out.append((e["line"], "G3", "warn", "line {} leads to a grading box, so it is a 'gradeLine'".format(name)))
        elif e["kind"] is None and not want:
            unclassed.append(name)
        if e["kind"] and LINE_ARROW[e["kind"]] != e["family"]:
            out.append((e["line"], "G10", "warn", "line {} is '{}', drawn '{}' in this grammar, but uses '{}'".format(
                name, e["kind"], ARROW_FORM[LINE_ARROW[e["kind"]]], e["arrow"])))
    if unclassed:
        shown = ", ".join(unclassed[:6]) + (" and {} more".format(len(unclassed) - 6) if len(unclassed) > 6 else "")
        out.append((d["first"], "G3", "warn", "{} line(s) have no line kind (write, read, pass, gradeLine): {}; give each "
                    "an ID such as `A e1@--> B` and a `class` line".format(len(unclassed), shown)))
    for nid, kind in kind_of.items():
        outgoing = [e for e in flow if e["src"] == nid]
        incoming = [e for e in flow if e["dst"] == nid]
        line = nodes[nid]["line"]
        if kind == "decide" and (len(outgoing) < 2 or any(not e["label"] for e in outgoing)):
            out.append((line, "G4", "error", "decision {} needs two or more branches, each labelled".format(nid)))
        if kind == "store" and incoming and not outgoing:
            out.append((line, "G9", "warn", "store {} is written but never read: is a read line missing?".format(nid)))
        if kind == "store" and outgoing and not incoming:
            out.append((line, "G9", "warn", "store {} is read but never written: is the step that fills it missing?".format(nid)))
        if kind in ("proc", "llm", "decide") and not outgoing:
            out.append((line, "G8", "warn", "{} {} has no outgoing line: where does its result go?".format(kind, nid)))
    used_kinds = set(kind_of.values())
    used_lines = {e["kind"] for e in flow if e["kind"]}
    used_tags = sorted({t for nid in kind_of for t in tags_of(nodes[nid]["label"])})
    used_marks = {c for nid in kind_of for c in classes.get(nid, set()) if c in ("key", "gap")}
    legend_nodes = [nid for nid in nodes if nid in d["legend"]]
    needs_legend = len(used_kinds) >= 3 or bool(used_lines - {"pass"}) or bool(used_tags) or bool(used_marks)
    if needs_legend and not d["legend_below"]:
        if not legend_nodes:
            out.append((d["first"], "G5", "warn", "no legend: add a subgraph titled Legend (or 범례) showing the kinds, lines "
                        "and tags used, or a legend table under the diagram with `%% legend: below` in the source"))
        else:
            legend_kinds = {c for nid in legend_nodes for c in classes.get(nid, set()) if c in KINDS}
            legend_lines = {c for e in edges if e["legend"] for c in classes.get(e["id"] or "", set()) if c in LINES}
            legend_text = " ".join(nodes[nid]["label"] or "" for nid in legend_nodes)
            missing = sorted(used_kinds - legend_kinds) + sorted(used_lines - legend_lines)
            missing += ["[{}]".format(t) for t in used_tags if "[{}]".format(t) not in legend_text]
            missing += [mark for mark in sorted(used_marks)
                        if not any(mark in classes.get(nid, set()) for nid in legend_nodes)]
            if missing:
                out.append((d["first"], "G5", "warn", "the legend does not show: {}".format(", ".join(missing))))
    if len(used_tags) > MAX_TAGS:
        out.append((d["first"], "G12", "warn", "{} tag kinds ({}); keep to {} or fewer".format(
            len(used_tags), ", ".join(used_tags), MAX_TAGS)))
    out += colour_findings(d)
    out.sort(key=lambda f: (f[0], f[1]))
    return out, len([n for n in nodes if n not in ghosts]), len(flow)


def colour_findings(d):
    """G7: every fill has a text colour, and the two have a contrast of at least 4.5:1."""
    out = []
    for where, table in (("classDef", d["classdefs"]), ("style", d["styles"])):
        for name, entry in sorted(table.items()):
            props = entry["props"]
            fill_value, color_value = props.get("fill"), props.get("color")
            if not fill_value or fill_value.strip().lower() in NO_FILL:
                continue
            if not color_value:
                out.append((entry["line"], "G7", "warn", "{} {} sets a fill but no text colour; a dark theme can make "
                            "the text light on this fill".format(where, name)))
                continue
            fill, color = hex_rgb(fill_value), hex_rgb(color_value)
            if fill is None or color is None:
                out.append((entry["line"], "G7", "warn", "{} {}: contrast not checked, because '{}' is not a hex or "
                            "basic named colour".format(where, name, fill_value if fill is None else color_value)))
            elif contrast(fill, color) < 4.5:
                out.append((entry["line"], "G7", "error", "{} {}: text contrast {:.1f}:1 is under 4.5:1".format(
                    where, name, contrast(fill, color))))
    return out


def kind_name(src):
    body = re.sub(r"\A\s*---\s*\n.*?\n---\s*\n", "", src, flags=re.S)
    for line in body.splitlines():
        line = line.strip()
        if line and not line.startswith("%%"):
            m = DIAGRAM_RE.match(line)
            return m.group(1) if m else line[:20]
    return "empty"


def read(name):
    """A file's text, or standard input's for -, read as UTF-8 whatever the console's encoding."""
    if name == "-":
        stream = getattr(sys.stdin, "buffer", None)
        return stream.read().decode("utf-8-sig") if stream else sys.stdin.read()
    with open(name, encoding="utf-8-sig") as handle:
        return handle.read()


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Check Mermaid flowcharts against the corthex-diagram visual grammar.")
    parser.add_argument("files", nargs="+", help=".mmd or .mermaid files, files with ```mermaid blocks, or - for standard input")
    parser.add_argument("--wrap", type=int, help="width in px at which the target breaks Korean label lines (default {})".format(WRAP_DEFAULT))
    parser.add_argument("--version", action="version", version="diagram-check, grammar version " + GRAMMAR_VERSION)
    args = parser.parse_args(argv)
    status = 0
    for path in args.files:
        try:
            text = read(path)
        except (OSError, UnicodeDecodeError) as exc:
            print("{}: cannot read: {}".format(path, exc), file=sys.stderr)
            status = 2
            continue
        blocks = read_blocks(path, text)
        if not blocks:
            print("{}: no Mermaid block".format(path))
        for start, src in blocks:
            kind = kind_name(src)
            if kind not in ("flowchart", "graph"):
                print("{}:{}: {} block, not checked: the grammar checks flowcharts".format(path, start, kind))
                continue
            findings, boxes, lines = check(src, args.wrap)
            print("{}:{}: {} boxes, {} lines, {} findings".format(path, start, boxes, lines, len(findings)))
            for no, rule, severity, message in findings:
                print("{}:{}: {} {}: {}".format(path, start + no - 1, rule, severity, message))
                if severity == "error" and status == 0:
                    status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
