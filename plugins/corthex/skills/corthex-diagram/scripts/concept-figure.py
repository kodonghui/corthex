#!/usr/bin/env python3
"""Draw a concept figure: nodes kept in fixed places on stacked layers, walked step by step.

Reads a JSON spec (see ../references/concept.md), checks it, and writes SVG:
one file for the structure, one per frame, or every frame on one sheet.
Standard library only; Python 3.8 or later. It reads the spec and writes only
the output path it is given, or standard output.
"""

import argparse
import json
import math
import re
import sys
from xml.sax.saxutils import escape

FONT = "'IBM Plex Sans KR', 'Noto Sans KR', 'Apple SD Gothic Neo', 'Malgun Gothic', 'Noto Sans CJK KR', sans-serif"
CJK_RE = re.compile(r"[ᄀ-ᇿ　-鿿가-힯豈-﫿＀-￯]")
STATES = ("current", "candidates", "visited", "dropped", "result")
FRAME_KEYS = {"title", "note", "layer", "current", "candidates", "visited", "dropped", "result",
              "path", "descend", "distances", "list", "marks", "greedy"}
TOP_KEYS = {"title", "caption", "lang", "view", "layers", "nodes", "links", "relations", "query",
            "frames", "marks", "labels", "size"}

COLOURS = {
    "ink": "#212529", "ink2": "#495057", "faint": "#adb5bd", "line": "#adb5bd", "line_off": "#dee2e6",
    "plane": "#f8f9fa", "plane_edge": "#ced4da", "plane_on": "#f1f7fe", "plane_on_edge": "#74c0fc",
    "node": "#ffffff", "node_edge": "#868e96",
    "current": "#1971c2", "current_edge": "#1864ab",
    "candidates": "#d0ebff", "candidates_edge": "#1971c2",
    "visited": "#e9ecef", "visited_edge": "#adb5bd",
    "dropped": "#ffffff", "dropped_edge": "#adb5bd",
    "result": "#2f9e44", "result_edge": "#2b8a3e",
    "query": "#e03131", "path": "#1971c2", "relation": "#7048e8", "copy": "#ced4da",
    "card": "#ffffff", "step_on": "#1971c2", "step_off": "#ced4da",
}

WORDS = {
    "en": {"query": "Question", "current": "Node being checked", "candidates": "Kept in the list",
           "visited": "Checked", "dropped": "Dropped", "result": "Result", "path": "Move",
           "descend": "Down one layer, same node", "link": "Link for search", "relation": "Relation",
           "copy": "Same node on another layer", "distance": "Distance from the question",
           "list": "List, nearest first", "steps": "Steps", "made_up": "Distances come from the figure's own coordinates."},
    "ko": {"query": "질문", "current": "지금 보는 노드", "candidates": "목록에 남김",
           "visited": "확인함", "dropped": "버림", "result": "결과", "path": "이동",
           "descend": "같은 노드로 한 층 내려감", "link": "검색용 연결", "relation": "관계",
           "copy": "다른 층의 같은 노드", "distance": "질문까지 거리",
           "list": "목록 (가까운 순)", "steps": "단계", "made_up": "거리는 그림 좌표로 계산한 값입니다."},
}


# ---------- text ----------

def text_width(text, size):
    """Estimate the drawn width of text in px: CJK about 1 em, Latin about 0.56 em."""
    width = 0.0
    for ch in text:
        if CJK_RE.match(ch):
            width += size * 1.0
        elif ch == " ":
            width += size * 0.28
        elif ch in "il.,:;'|!()[]":
            width += size * 0.3
        else:
            width += size * 0.56
    return width


def wrap(text, size, width):
    """Wrap text at spaces to lines no wider than width; a word longer than width stays whole."""
    lines, line = [], ""
    for word in text.split():
        trial = word if not line else line + " " + word
        if text_width(trial, size) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


# ---------- spec ----------

class Spec:
    def __init__(self, data):
        self.data = data
        self.findings = []
        self.lang = data.get("lang", "en") if data.get("lang") in WORDS else "en"
        self.words = dict(WORDS[self.lang])
        self.words.update(data.get("labels") or {})
        layers = data.get("layers") or [{"id": "L0", "label": ""}]
        self.layers = [layer["id"] for layer in layers]
        self.layer_label = {layer["id"]: layer.get("label", layer["id"]) for layer in layers}
        self.layer_index = {lid: i for i, lid in enumerate(self.layers)}
        self.view = data.get("view") or ("flat" if len(self.layers) == 1 else "stack")
        if self.view not in ("stack", "flat"):
            raise ValueError("view must be stack or flat")
        self.nodes = {}
        for node in data.get("nodes") or []:
            self.nodes[node["id"]] = node
        self.links = data.get("links") or {}
        self.relations = data.get("relations") or {}
        self.query = data.get("query")
        self.frames = data.get("frames") or []

    def add(self, code, level, message):
        self.findings.append((code, level, message))

    def top(self, nid):
        """Index of the highest layer a node reaches (0 is the top layer)."""
        node = self.nodes[nid]
        return self.layer_index.get(node.get("layer", self.layers[-1]), len(self.layers) - 1)

    def on_layer(self, nid, lid):
        return nid in self.nodes and self.top(nid) <= self.layer_index[lid]

    def dist(self, nid):
        node, q = self.nodes[nid], self.query
        return math.hypot(node["x"] - q["x"], node["y"] - q["y"]) / 100.0

    def edges(self, lid):
        pairs = [tuple(p) for p in self.links.get(lid, [])]
        pairs += [tuple(r[:2]) for r in self.relations.get(lid, [])]
        return pairs

    def neighbours(self, lid, nid):
        out = set()
        for a, b in self.edges(lid):
            if a == nid:
                out.add(b)
            if b == nid:
                out.add(a)
        return out


def check(spec):
    """Check the spec; return the findings as (code, level, message)."""
    s = spec
    for key in s.data:
        if key not in TOP_KEYS:
            s.add("F1", "warn", "unknown key '{}' is ignored".format(key))
    if not s.nodes:
        s.add("F1", "error", "the spec has no nodes")
        return s.findings
    for nid, node in s.nodes.items():
        for axis in ("x", "y"):
            value = node.get(axis)
            if not isinstance(value, (int, float)) or not 0 <= value <= 100:
                s.add("F3", "error", "node {} needs {} between 0 and 100".format(nid, axis))
        if node.get("layer", s.layers[-1]) not in s.layer_index:
            s.add("F2", "error", "node {} names an unknown layer '{}'".format(nid, node.get("layer")))
    if s.query and not all(isinstance(s.query.get(a), (int, float)) and 0 <= s.query.get(a) <= 100 for a in ("x", "y")):
        s.add("F3", "error", "the question needs x and y between 0 and 100")
    if any(f[1] == "error" for f in s.findings):
        return s.findings
    for kind, table in (("link", s.links), ("relation", s.relations)):
        for lid, pairs in table.items():
            if lid not in s.layer_index:
                s.add("F2", "error", "{}s name an unknown layer '{}'".format(kind, lid))
                continue
            for pair in pairs:
                for nid in pair[:2]:
                    if nid not in s.nodes:
                        s.add("F2", "error", "{} {}-{} on {} names an unknown node {}".format(kind, pair[0], pair[1], lid, nid))
                    elif not s.on_layer(nid, lid):
                        s.add("F4", "error", "{} {}-{} is on {}, but {} does not reach that layer".format(kind, pair[0], pair[1], lid, nid))
    # Nodes too close to read on one layer.
    for lid in s.layers:
        here = [n for n in s.nodes if s.on_layer(n, lid)]
        for i, a in enumerate(here):
            for b in here[i + 1:]:
                pa, pb = s.nodes[a], s.nodes[b]
                if abs(pa["x"] - pb["x"]) < 6 and abs(pa["y"] - pb["y"]) < 12:
                    s.add("F8", "warn", "nodes {} and {} overlap on {}; move one".format(a, b, lid))
        if len(here) > 20:
            s.add("F10", "warn", "{} nodes on {}; above about 20 a reader cannot follow a walk".format(len(here), lid))
    if len(s.frames) > 8:
        s.add("F10", "warn", "{} frames; split a series longer than about 8".format(len(s.frames)))
    for no, frame in enumerate(s.frames, 1):
        check_frame(s, no, frame)
    return s.findings


def check_frame(s, no, frame):
    where = "frame {}".format(no)
    for key in frame:
        if key not in FRAME_KEYS:
            s.add("F1", "warn", "{}: unknown key '{}' is ignored".format(where, key))
    if not frame.get("title"):
        s.add("F9", "warn", "{} has no title; each step needs one line".format(where))
    lid = frame.get("layer")
    if lid is not None and lid not in s.layer_index:
        s.add("F2", "error", "{} names an unknown layer '{}'".format(where, lid))
        return
    named = []
    for state in STATES:
        value = frame.get(state)
        named += [value] if isinstance(value, str) else list(value or [])
    named += list(frame.get("distances") or []) + list(frame.get("list") or []) + list((frame.get("marks") or {}).keys())
    for pair in frame.get("path") or []:
        named += list(pair)
    if frame.get("descend"):
        named.append(frame["descend"])
    for nid in named:
        if nid not in s.nodes:
            s.add("F2", "error", "{} names an unknown node {}".format(where, nid))
        elif lid is not None and not s.on_layer(nid, lid):
            s.add("F6", "error", "{} shows {} on {}, but {} does not reach that layer".format(where, nid, lid, nid))
    if any(f[1] == "error" and f[2].startswith((where + " ", where + ":")) for f in s.findings):
        return
    if (frame.get("path") or frame.get("descend") or any(frame.get(k) for k in STATES)) and lid is None:
        s.add("F6", "error", "{} marks nodes but names no layer".format(where))
        return
    for a, b in frame.get("path") or []:
        if b not in s.neighbours(lid, a):
            s.add("F5", "error", "{}: the move {}->{} follows no link on {}".format(where, a, b, lid))
        elif frame.get("greedy") and s.query and s.dist(b) >= s.dist(a):
            s.add("F7", "error", "{}: a greedy move must get closer to the question, but {} ({:.2f}) is not closer than {} ({:.2f})".format(
                where, b, s.dist(b), a, s.dist(a)))
    down = frame.get("descend")
    if down:
        below = s.layer_index[lid] + 1
        if below >= len(s.layers):
            s.add("F11", "error", "{}: cannot go down from the lowest layer".format(where))
        elif not s.on_layer(down, s.layers[below]):
            s.add("F11", "error", "{}: {} is not on the layer below".format(where, down))
    if frame.get("list") and s.query:
        dists = [s.dist(n) for n in frame["list"]]
        if dists != sorted(dists):
            s.add("F12", "warn", "{}: keep the list nearest first: {}".format(where, ", ".join(frame["list"])))
    if (frame.get("distances") or frame.get("list") or frame.get("greedy")) and not s.query:
        s.add("F2", "error", "{} measures distances, but the spec has no question".format(where))


# ---------- layout ----------

class Layout:
    LABEL_W = 96
    PANEL_W = 300
    MARGIN = 28
    R = 13

    def __init__(self, spec, active=None, panel=False):
        s = spec
        size = s.data.get("size") or {}
        self.stack = s.view == "stack"
        if self.stack:
            self.pw = size.get("width", 540)
            self.skew = size.get("skew", 90)
            self.gap = size.get("gap", 40)
            plain = size.get("depth", 180)
            focus = size.get("focus_depth", 250)
            context = size.get("context_depth", 96)
            self.depths = [plain if active is None else (focus if lid == active else context) for lid in s.layers]
        else:
            self.pw = size.get("width", 440)
            self.skew = 0
            self.gap = size.get("gap", 40) if len(s.layers) > 1 else 0
            self.depths = [size.get("depth", 400)] * len(s.layers)
        self.x0 = self.MARGIN + self.LABEL_W
        self.y0 = self.MARGIN + 8
        self.tops = []
        y = self.y0
        for depth in self.depths:
            self.tops.append(y)
            y += depth + self.gap
        self.planes_bottom = y - self.gap
        self.panel = panel
        self.plane_right = self.x0 + self.pw + self.skew
        self.width = self.plane_right + self.MARGIN + (self.PANEL_W + 24 if panel else 0)

    def point(self, li, x, y):
        depth = self.depths[li]
        pad = min(14, depth * 0.12)
        px = self.x0 + x / 100.0 * self.pw + (1 - y / 100.0) * self.skew
        py = self.tops[li] + pad + y / 100.0 * (depth - 2 * pad)
        return px, py

    def corners(self, li):
        top, depth = self.tops[li], self.depths[li]
        return [(self.x0 + self.skew, top), (self.x0 + self.pw + self.skew, top),
                (self.x0 + self.pw, top + depth), (self.x0, top + depth)]


class Placer:
    """Put labels where they cover no node, star or earlier label."""

    def __init__(self):
        self.boxes = []

    def block(self, x, y, w, h):
        self.boxes.append((x, y, x + w, y + h))

    @staticmethod
    def box(x, y, w, h, anchor):
        left = x - w / 2 if anchor == "middle" else (x - w if anchor == "end" else x)
        return (left - 2, y - h + 2, left + w + 2, y + 4)

    def overlap(self, box):
        total = 0.0
        for b in self.boxes:
            dx = min(box[2], b[2]) - max(box[0], b[0])
            dy = min(box[3], b[3]) - max(box[1], b[1])
            if dx > 0 and dy > 0:
                total += dx * dy
        return total

    def place(self, candidates, w, h):
        best, best_cost = None, None
        for x, y, anchor in candidates:
            box = self.box(x, y, w, h, anchor)
            cost = self.overlap(box)
            if cost == 0:
                best = (x, y, anchor)
                break
            if best_cost is None or cost < best_cost:
                best, best_cost = (x, y, anchor), cost
        x, y, anchor = best
        b = self.box(x, y, w, h, anchor)
        self.boxes.append(b)
        return best


# ---------- drawing ----------

HALO = ' paint-order="stroke" stroke="#ffffff" stroke-width="3.5" stroke-linejoin="round"'


def t(x, y, text, size=13, fill=None, weight=400, anchor="start", extra=""):
    return '<text x="{:.1f}" y="{:.1f}" font-size="{}" font-weight="{}" fill="{}" text-anchor="{}"{}>{}</text>'.format(
        x, y, size, weight, fill or COLOURS["ink"], anchor, extra, escape(text))


def line(a, b, colour, width=1.2, dash=None, marker=None, opacity=1.0):
    return '<line x1="{:.1f}" y1="{:.1f}" x2="{:.1f}" y2="{:.1f}" stroke="{}" stroke-width="{}"{}{}{}/>'.format(
        a[0], a[1], b[0], b[1], colour, width,
        ' stroke-dasharray="{}"'.format(dash) if dash else "",
        ' marker-end="url(#arrow)"' if marker else "",
        ' opacity="{}"'.format(opacity) if opacity < 1 else "")


def shorten(a, b, start, end):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy) or 1.0
    return ((a[0] + dx * start / length, a[1] + dy * start / length),
            (b[0] - dx * end / length, b[1] - dy * end / length))


def star(cx, cy, r, colour):
    pts = []
    for i in range(10):
        angle = math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.45
        pts.append("{:.1f},{:.1f}".format(cx + rad * math.cos(angle), cy - rad * math.sin(angle)))
    return '<polygon points="{}" fill="{}" stroke="#ffffff" stroke-width="1.2"/>'.format(" ".join(pts), colour)


def node_style(state):
    if state is None:
        return COLOURS["node"], COLOURS["node_edge"], COLOURS["ink"], ""
    fill, edge = COLOURS[state], COLOURS[state + "_edge"]
    text = "#ffffff" if state in ("current", "result") else (COLOURS["faint"] if state == "dropped" else COLOURS["ink"])
    dash = ' stroke-dasharray="3 2"' if state == "dropped" else ""
    return fill, edge, text, dash


def frame_states(frame):
    """Map each node to its state in a frame; later states win (result over current over list)."""
    state = {}
    for key in ("visited", "dropped", "candidates", "current", "result"):
        value = frame.get(key)
        for nid in ([value] if isinstance(value, str) else (value or [])):
            state[nid] = key
    return state


def around(px, py, gap, w):
    """Label spots around a point: above, below, right, left, then the corners."""
    return [(px, py - gap - 3, "middle"), (px, py + gap + 13, "middle"),
            (px + gap + 3, py + 4.5, "start"), (px - gap - 3, py + 4.5, "end"),
            (px + gap, py - gap, "start"), (px - gap, py - gap, "end"),
            (px + gap, py + gap + 10, "start"), (px - gap, py + gap + 10, "end")]


def draw(spec, frame_no=None):
    """Return the SVG text for the structure (frame_no None) or one frame of the series."""
    s = spec
    frame = s.frames[frame_no - 1] if frame_no else {}
    active = frame.get("layer") if frame_no else None
    lay = Layout(s, active, panel=bool(frame_no))
    states = frame_states(frame) if frame_no else {}
    used = set()
    out, labels = [], []
    placer = Placer()
    R = lay.R

    def at(li, nid):
        node = s.nodes[nid]
        return lay.point(li, node["x"], node["y"])

    # Planes, back (top) to front (bottom), with their names.
    for li, lid in enumerate(s.layers):
        on = active is None or lid == active
        pts = " ".join("{:.1f},{:.1f}".format(x, y) for x, y in lay.corners(li))
        focus = frame_no and lid == active
        out.append('<polygon points="{}" fill="{}" stroke="{}" stroke-width="1.2" opacity="{}"/>'.format(
            pts, COLOURS["plane_on"] if focus else COLOURS["plane"],
            COLOURS["plane_on_edge"] if focus else COLOURS["plane_edge"], 1 if on else 0.6))
        label_y = lay.tops[li] + lay.depths[li] / 2
        out.append(t(lay.x0 - 14, label_y - 2, s.layer_label[lid], 15, COLOURS["ink"] if on else COLOURS["faint"], 700, "end"))
        if lay.stack:
            count = sum(1 for n in s.nodes if s.on_layer(n, lid))
            noun = "개" if s.lang == "ko" else (" node" if count == 1 else " nodes")
            out.append(t(lay.x0 - 14, label_y + 16, "{}{}".format(count, noun), 12, COLOURS["ink2"] if on else COLOURS["faint"], 400, "end"))

    # Every node and star is a place no label may cover.
    for li, lid in enumerate(s.layers):
        for nid in s.nodes:
            if s.on_layer(nid, lid):
                px, py = at(li, nid)
                placer.block(px - R - 1, py - R - 1, 2 * R + 2, 2 * R + 2)
        if s.query:
            qx, qy = lay.point(li, s.query["x"], s.query["y"])
            placer.block(qx - 11, qy - 11, 22, 22)

    # The same node on every layer it reaches, joined by a dotted line.
    if lay.stack:
        for nid in s.nodes:
            first = s.top(nid)
            if first < len(s.layers) - 1:
                a, b = at(first, nid), at(len(s.layers) - 1, nid)
                out.append(line((a[0], a[1] + R), (b[0], b[1] - R), COLOURS["copy"], 1, "2 3"))
                used.add("copy")
        if s.query:
            a = lay.point(0, s.query["x"], s.query["y"])
            b = lay.point(len(s.layers) - 1, s.query["x"], s.query["y"])
            out.append(line(a, b, COLOURS["query"], 1, "2 3", opacity=0.35))

    # Links and relations.
    for li, lid in enumerate(s.layers):
        on = active is None or lid == active
        for a, b in s.links.get(lid, []):
            out.append(line(at(li, a), at(li, b), COLOURS["line"] if on else COLOURS["line_off"], 1.4 if on else 1))
            used.add("link")
        for rel in s.relations.get(lid, []):
            pa, pb = at(li, rel[0]), at(li, rel[1])
            out.append(line(pa, pb, COLOURS["relation"], 2.2 if on else 1.2, opacity=1 if on else 0.4))
            used.add("relation")
            if len(rel) > 2 and on:
                w = text_width(rel[2], 11.5)
                spots = [((pa[0] + pb[0]) / 2 + dx, (pa[1] + pb[1]) / 2 + dy, "middle") for dx, dy in ((0, -6), (0, 14), (16, -6), (-16, 14))]
                x, y, anchor = placer.place(spots, w, 13)
                labels.append(t(x, y, rel[2], 11.5, COLOURS["relation"], 600, anchor, HALO))

    # Distances from the question, on the active layer.
    if frame_no and s.query and active is not None:
        li = s.layer_index[active]
        q = lay.point(li, s.query["x"], s.query["y"])
        for nid in frame.get("distances") or []:
            p = at(li, nid)
            a, b = shorten(q, p, 10, R + 2)
            out.append(line(a, b, COLOURS["query"], 1.2, "4 3"))
            used.add("distance")
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / length, dx / length
            text = "{:.2f}".format(s.dist(nid))
            w = text_width(text, 12)
            spots = []
            for f in (0.5, 0.35, 0.65, 0.25, 0.75):
                mx, my = a[0] + dx * f, a[1] + dy * f
                for side in (1, -1):
                    spots.append((mx + nx * 11 * side, my + ny * 11 * side + 4, "middle"))
            x, y, anchor = placer.place(spots, w, 14)
            labels.append(t(x, y, text, 12, COLOURS["query"], 700, anchor, HALO))

    # Moves along links, and the way down.
    if frame_no and active is not None:
        li = s.layer_index[active]
        for a, b in frame.get("path") or []:
            a2, b2 = shorten(at(li, a), at(li, b), R + 2, R + 3)
            out.append(line(a2, b2, COLOURS["path"], 3.2, marker=True))
            used.add("path")
        down = frame.get("descend")
        if down:
            pa, pb = at(li, down), at(li + 1, down)
            out.append(line((pa[0], pa[1] + R + 2), (pb[0], pb[1] - R - 3), COLOURS["path"], 2.6, "6 4", True))
            used.add("descend")

    # Nodes and the question, back to front.
    for li, lid in enumerate(s.layers):
        on = active is None or lid == active
        for nid, node in s.nodes.items():
            if not s.on_layer(nid, lid):
                continue
            px, py = at(li, nid)
            state = states.get(nid) if (frame_no and lid == active) else None
            if state:
                used.add(state)
            fill, edge, ink, dash = node_style(state)
            width = 2.8 if state in ("candidates", "current", "result") else 1.6
            out.append('<g opacity="{}"><circle cx="{:.1f}" cy="{:.1f}" r="{}" fill="{}" stroke="{}" stroke-width="{}"{}/>'.format(
                1 if on else 0.45, px, py, R, fill, edge, width, dash))
            label = node.get("label", nid)
            if text_width(label, 13) <= R * 2 - 4:
                out.append(t(px, py + 4.5, label, 13, ink, 700, "middle"))
            else:
                x, y, anchor = placer.place(around(px, py, R + 3, text_width(label, 12.5)), text_width(label, 12.5), 15)
                labels.append(t(x, y, label, 12.5, COLOURS["ink"], 600, anchor, HALO))
            if state == "dropped":
                out.append(t(px + R - 1, py - R + 3, "×", 14, COLOURS["ink2"], 700, "middle"))
            out.append("</g>")
        if s.query:
            qx, qy = lay.point(li, s.query["x"], s.query["y"])
            out.append('<g opacity="{}">'.format(1 if on else 0.45) + star(qx, qy, 11, COLOURS["query"]) + "</g>")
            used.add("query")
            if on:
                word = s.query.get("label", s.words["query"])
                w = text_width(word, 12.5)
                x, y, anchor = placer.place(around(qx, qy, 12, w), w, 15)
                labels.append(t(x, y, word, 12.5, COLOURS["query"], 700, anchor, HALO))

    # Marks: short words beside a node. A spec mark sits on the node's top layer, a frame mark on the frame's layer.
    marks = [(nid, word, s.top(nid)) for nid, word in (s.data.get("marks") or {}).items() if nid in s.nodes]
    if frame_no and active is not None:
        marks += [(nid, word, s.layer_index[active]) for nid, word in (frame.get("marks") or {}).items() if nid in s.nodes]
    for nid, word, li in marks:
        px, py = at(li, nid)
        on = active is None or s.layers[li] == active
        w = text_width(word, 12.5)
        x, y, anchor = placer.place(around(px, py, R + 3, w), w, 15)
        labels.append(t(x, y, word, 12.5, COLOURS["ink"] if on else COLOURS["faint"], 700, anchor, HALO))

    out += labels

    # The step panel.
    panel_bottom = draw_panel(s, lay, frame_no, out) if frame_no else lay.planes_bottom

    # The legend: only what this picture uses.
    legend_y = max(lay.planes_bottom, panel_bottom) + 34
    legend, legend_h = draw_legend(s, lay, used, legend_y, bool(frame_no and (frame.get("distances") or frame.get("list"))))
    height = legend_y + legend_h + 14

    title = s.data.get("title", "")
    if frame_no and frame.get("title"):
        title = "{} · {}".format(title, frame["title"]) if title else frame["title"]
    head = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="{w:.0f}" height="{h:.0f}" viewBox="0 0 {w:.0f} {h:.0f}" role="img" font-family="{f}">'.format(
            w=lay.width, h=height, f=FONT.replace("'", "&apos;")),
        "<title>{}</title>".format(escape(title)),
    ]
    if s.data.get("caption"):
        head.append("<desc>{}</desc>".format(escape(s.data["caption"])))
    head.append('<defs><marker id="arrow" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="4" markerHeight="4" orient="auto-start-reverse">'
                '<path d="M0,0 L10,5 L0,10 z" fill="{}"/></marker></defs>'.format(COLOURS["path"]))
    head.append('<rect x="0" y="0" width="{:.0f}" height="{:.0f}" rx="10" fill="{}"/>'.format(lay.width, height, COLOURS["card"]))
    return "\n".join(head + out + legend + ["</svg>"]) + "\n"


def draw_panel(s, lay, frame_no, out):
    x = lay.plane_right + lay.MARGIN + 8
    width = lay.PANEL_W
    y = lay.y0 + 4
    out.append(t(x, y + 8, s.words["steps"], 13, COLOURS["ink2"], 700))
    y += 30
    for no, frame in enumerate(s.frames, 1):
        now = no == frame_no
        done = no < frame_no
        colour = COLOURS["step_on"] if now else (COLOURS["ink2"] if done else COLOURS["step_off"])
        out.append('<circle cx="{:.1f}" cy="{:.1f}" r="10" fill="{}"/>'.format(x + 10, y - 4, colour))
        out.append(t(x + 10, y + 0.5, str(no), 12, "#ffffff", 700, "middle"))
        lines = wrap(frame.get("title", ""), 13.5, width - 30)
        for i, text in enumerate(lines):
            out.append(t(x + 28, y + i * 18, text, 13.5, COLOURS["ink"] if (now or done) else COLOURS["faint"], 700 if now else 400))
        y += 18 * max(1, len(lines)) + 4
        if now and frame.get("note"):
            for text in wrap(frame["note"], 12.5, width - 30):
                out.append(t(x + 28, y, text, 12.5, COLOURS["ink2"]))
                y += 17
            y += 2
        if now and frame.get("list") and s.query:
            out.append(t(x + 28, y, s.words["list"], 12, COLOURS["ink2"], 700))
            y += 6
            bx = x + 28
            for nid in frame["list"]:
                label = "{} {:.2f}".format(s.nodes[nid].get("label", nid), s.dist(nid))
                w = text_width(label, 12) + 14
                if bx + w > x + width:
                    bx = x + 28
                    y += 26
                out.append('<rect x="{:.1f}" y="{:.1f}" width="{:.1f}" height="20" rx="10" fill="{}" stroke="{}" stroke-width="1.5"/>'.format(
                    bx, y, w, COLOURS["candidates"], COLOURS["candidates_edge"]))
                out.append(t(bx + w / 2, y + 14, label, 12, COLOURS["ink"], 600, "middle"))
                bx += w + 6
            y += 34
        y += 8
    return y


def draw_legend(s, lay, used, y, made_up):
    words = s.words
    items = []
    order = ["query", "current", "candidates", "visited", "dropped", "result", "path", "descend",
             "link", "relation", "copy", "distance"]
    for key in order:
        if key in used:
            items.append(key)
    out = []
    x = lay.MARGIN + 6
    row_y = y
    out.append('<line x1="{}" y1="{:.1f}" x2="{:.0f}" y2="{:.1f}" stroke="#e9ecef" stroke-width="1"/>'.format(
        lay.MARGIN, y - 22, lay.width - lay.MARGIN, y - 22))
    for key in items:
        label = words[key]
        w = 30 + text_width(label, 12.5) + 22
        if x + w > lay.width - lay.MARGIN:
            x = lay.MARGIN + 6
            row_y += 26
        cx, cy = x + 10, row_y - 4
        if key == "query":
            out.append(star(cx, cy, 9, COLOURS["query"]))
        elif key in STATES:
            fill, edge, _, dash = node_style(key)
            out.append('<circle cx="{:.1f}" cy="{:.1f}" r="8" fill="{}" stroke="{}" stroke-width="2"{}/>'.format(cx, cy, fill, edge, dash))
        elif key == "path":
            out.append(line((x, cy), (x + 22, cy), COLOURS["path"], 3.2, marker=True))
        elif key == "descend":
            out.append(line((cx, cy - 10), (cx, cy + 8), COLOURS["path"], 2.6, "6 4", True))
        elif key == "link":
            out.append(line((x, cy), (x + 20, cy), COLOURS["line"], 1.6))
        elif key == "relation":
            out.append(line((x, cy), (x + 20, cy), COLOURS["relation"], 2.2))
        elif key == "copy":
            out.append(line((cx, cy - 9), (cx, cy + 9), COLOURS["copy"], 1.4, "2 3"))
        elif key == "distance":
            out.append(line((x, cy), (x + 20, cy), COLOURS["query"], 1.3, "4 3"))
        out.append(t(x + 28, row_y, label, 12.5, COLOURS["ink2"]))
        x += w
    height = row_y - y + 12
    if made_up:
        out.append(t(lay.MARGIN + 6, row_y + 24, words["made_up"], 11.5, COLOURS["ink2"]))
        height += 22
    return out, height


def sheet(spec, numbers):
    """Put several frames side by side on one sheet, two to a row."""
    parts = [draw(spec, n) for n in numbers]
    sizes = []
    for svg in parts:
        m = re.search(r'width="(\d+)" height="(\d+)"', svg)
        sizes.append((int(m.group(1)), int(m.group(2))))
    cols = 2 if len(parts) > 1 else 1
    col_w = max(w for w, _ in sizes)
    rows = [sizes[i:i + cols] for i in range(0, len(sizes), cols)]
    total_h = sum(max(h for _, h in row) for row in rows) + 16 * (len(rows) - 1)
    total_w = col_w * cols + 16 * (cols - 1)
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="{}" height="{}" viewBox="0 0 {} {}">'.format(total_w, total_h, total_w, total_h)]
    y = 0
    k = 0
    for row in rows:
        x = 0
        for w, h in row:
            inner = parts[k].split("\n", 1)[1].rsplit("</svg>", 1)[0]
            inner = inner.replace('id="arrow"', 'id="arrow{}"'.format(k)).replace("url(#arrow)", "url(#arrow{})".format(k))
            out.append('<svg x="{}" y="{}" width="{}" height="{}" font-family="{}">{}</svg>'.format(x, y, w, h, FONT.replace("'", "&apos;"), inner))
            x += col_w + 16
            k += 1
        y += max(h for _, h in row) + 16
    out.append("</svg>")
    return "\n".join(out) + "\n"


# ---------- command line ----------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Draw and check a concept figure from a JSON spec.")
    parser.add_argument("spec", help="the JSON spec, or - for standard input")
    parser.add_argument("-o", "--out", help="output SVG path; with frames, -1, -2 ... are added before .svg")
    parser.add_argument("--frame", type=int, help="draw only this frame (1 is the first)")
    parser.add_argument("--structure", action="store_true", help="draw only the structure, with no frame")
    parser.add_argument("--sheet", help="draw these frames on one sheet, such as 4,6")
    parser.add_argument("--check", action="store_true", help="only check the spec")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        if args.spec == "-":
            stream = getattr(sys.stdin, "buffer", None)
            text = stream.read().decode("utf-8-sig") if stream else sys.stdin.read()
        else:
            with open(args.spec, encoding="utf-8-sig") as handle:
                text = handle.read()
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("the spec is not a JSON object")
    except (OSError, ValueError) as exc:
        print("{}: cannot read: {}".format(args.spec, exc), file=sys.stderr)
        return 2
    try:
        spec = Spec(data)
        findings = check(spec)
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        print("F1 error: the spec does not have the expected shape ({}: {}); see references/concept.md".format(type(exc).__name__, exc))
        return 1
    for code, level, message in findings:
        print("{} {}: {}".format(code, level, message))
    errors = sum(1 for f in findings if f[1] == "error")
    print("{}: {} nodes, {} layers, {} frames, {} findings".format(
        args.spec, len(spec.nodes), len(spec.layers), len(spec.frames), len(findings)))
    if errors or args.check:
        return 1 if errors else 0
    outputs = []
    if args.sheet:
        numbers = [int(n) for n in args.sheet.split(",") if n.strip()]
        outputs.append((args.out, sheet(spec, numbers)))
    elif args.frame:
        outputs.append((args.out, draw(spec, args.frame)))
    elif args.structure or not spec.frames:
        outputs.append((args.out, draw(spec)))
    else:
        for no in range(1, len(spec.frames) + 1):
            path = None
            if args.out:
                path = re.sub(r"(\.svg)?$", "-{}.svg".format(no), args.out, count=1)
            outputs.append((path, draw(spec, no)))
    for path, svg in outputs:
        if path:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(svg)
            print("wrote {}".format(path))
        else:
            sys.stdout.write(svg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
