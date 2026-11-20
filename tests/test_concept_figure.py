"""Checks corthex-diagram's concept figures: the script that draws them, its checks and the worked HNSW example."""

import ast
import copy
import importlib.util
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from _common import PLUGINS, read_text

SKILL = PLUGINS / "corthex" / "skills" / "corthex-diagram"
SCRIPT = SKILL / "scripts" / "concept-figure.py"
EXAMPLE = SKILL / "assets" / "hnsw-search.json"
GUIDE = SKILL / "references" / "concept.md"
SVG = "{http://www.w3.org/2000/svg}"


def load():
    spec = importlib.util.spec_from_file_location("corthex_concept_figure", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


figure = load()


def example():
    return json.loads(read_text(EXAMPLE))


def codes(data):
    return [(code, level) for code, level, _ in figure.check(figure.Spec(data))]


def small(**frame):
    """Two layers: A and B reach the top, C only the bottom; the question sits near C."""
    data = {
        "layers": [{"id": "L1", "label": "Top"}, {"id": "L0", "label": "Bottom"}],
        "nodes": [{"id": "A", "x": 10, "y": 20, "layer": "L1"}, {"id": "B", "x": 60, "y": 30, "layer": "L1"},
                  {"id": "C", "x": 80, "y": 80}],
        "links": {"L1": [["A", "B"]], "L0": [["A", "B"], ["B", "C"]]},
        "query": {"x": 85, "y": 85},
        "frames": [],
    }
    if frame:
        data["frames"].append(dict({"title": "A step"}, **frame))
    return data


def hnsw_search(data, layer, entry, ef):
    """The search on one layer from the HNSW paper (Malkov and Yashunin, algorithm 2), on the example's points."""
    nodes = {n["id"]: n for n in data["nodes"]}
    q = data["query"]

    def dist(nid):
        return math.hypot(nodes[nid]["x"] - q["x"], nodes[nid]["y"] - q["y"])

    def neighbours(nid):
        return sorted({b if a == nid else a for a, b in data["links"][layer] if nid in (a, b)})

    visited, candidates, found = {entry}, [entry], [entry]
    while candidates:
        candidates.sort(key=dist)
        c = candidates.pop(0)
        if dist(c) > dist(max(found, key=dist)):
            break
        for e in neighbours(c):
            if e in visited:
                continue
            visited.add(e)
            if len(found) < ef or dist(e) < dist(max(found, key=dist)):
                candidates.append(e)
                found.append(e)
                if len(found) > ef:
                    found.remove(max(found, key=dist))
    return sorted(found, key=dist), visited


class ExampleTest(unittest.TestCase):
    def test_the_worked_example_has_no_findings(self):
        self.assertEqual(codes(example()), [])

    def test_the_example_follows_a_real_hnsw_search(self):
        data = example()
        frames = data["frames"]
        found, _ = hnsw_search(data, "L2", "E", 1)
        self.assertEqual(found, [frames[0]["current"]])
        self.assertEqual(frames[0]["descend"], found[0])
        found, visited = hnsw_search(data, "L1", found[0], 1)
        self.assertEqual(found, [frames[1]["current"]])
        self.assertEqual(set(frames[1]["visited"]) | {frames[1]["current"]}, visited)
        entry = found[0]
        found, _ = hnsw_search(data, "L0", entry, 3)
        self.assertEqual(found, frames[4]["list"])
        self.assertEqual(found[0], frames[4]["result"])
        found, visited = hnsw_search(data, "L0", entry, 1)
        self.assertEqual(found, [frames[5]["result"]])
        self.assertEqual(set(frames[5]["visited"]) | {frames[5]["result"]}, visited)
        self.assertNotEqual(frames[5]["result"], frames[4]["result"])

    def test_a_node_keeps_its_place_on_every_layer(self):
        spec = figure.Spec(example())
        for active in (None, "L2", "L0"):
            lay = figure.Layout(spec, active)
            for nid, node in spec.nodes.items():
                xs = {round(lay.point(li, node["x"], node["y"])[0], 3)
                      for li, lid in enumerate(spec.layers) if spec.on_layer(nid, lid)}
                with self.subTest(active=active, node=nid):
                    self.assertEqual(len(xs), 1)

    def test_every_frame_draws_as_valid_svg_with_its_step_column(self):
        spec = figure.Spec(example())
        structure = ET.fromstring(figure.draw(spec))
        self.assertEqual(structure.tag, SVG + "svg")
        placements = sum(1 for nid in spec.nodes for lid in spec.layers if spec.on_layer(nid, lid))
        self.assertEqual(len(structure.findall(".//" + SVG + "circle")), placements)
        for no, frame in enumerate(spec.frames, 1):
            svg = figure.draw(spec, no)
            root = ET.fromstring(svg)
            texts = [el.text for el in root.iter(SVG + "text")]
            with self.subTest(frame=no):
                self.assertIn(frame["title"], root.find(SVG + "title").text)
                for other in spec.frames:
                    self.assertIn(figure.wrap(other["title"], 13.5, figure.Layout.PANEL_W - 30)[0], texts)
                self.assertIn("Distances come from the figure's own coordinates.", texts)

    def test_the_legend_shows_only_what_the_picture_uses(self):
        spec = figure.Spec(example())
        texts = [el.text for el in ET.fromstring(figure.draw(spec)).iter(SVG + "text")]
        self.assertIn("Link kept for search (no meaning)", texts)
        self.assertIn("Same node on another layer", texts)
        for word in ("Result", "Dropped", "Move", "Distance from the question"):
            self.assertNotIn(word, texts)
        texts = [el.text for el in ET.fromstring(figure.draw(spec, 5)).iter(SVG + "text")]
        for word in ("Result", "Dropped", "Kept in the list", "Distance from the question"):
            self.assertIn(word, texts)


class CheckTest(unittest.TestCase):
    def test_a_good_frame_has_no_findings(self):
        self.assertEqual(codes(small(layer="L1", current="B", visited=["A"], path=[["A", "B"]], descend="B", greedy=True)), [])

    def test_each_mistake_is_named(self):
        cases = [
            (small(layer="L0", path=[["A", "C"]]), ("F5", "error")),
            (small(layer="L1", current="C"), ("F6", "error")),
            (small(layer="L1", path=[["B", "A"]], greedy=True), ("F7", "error")),
            (small(layer="L0", descend="C"), ("F11", "error")),
            (small(layer="L0", list=["A", "C"]), ("F12", "warn")),
            (small(layer="L0", current="Z"), ("F2", "error")),
            (small(current="A"), ("F6", "error")),
        ]
        for data, expected in cases:
            with self.subTest(expected=expected, frame=data["frames"][0]):
                self.assertIn(expected, codes(data))
        data = small()
        data["links"]["L1"].append(["A", "C"])
        self.assertIn(("F4", "error"), codes(data))
        data = small()
        data["nodes"][0]["x"] = 120
        self.assertIn(("F3", "error"), codes(data))
        data = small()
        data["nodes"].append({"id": "D", "x": 81, "y": 82})
        self.assertIn(("F8", "warn"), codes(data))
        data = small(layer="L0", distances=["C"])
        del data["query"]
        self.assertIn(("F2", "error"), codes(data))
        data = small()
        data["colour"] = "red"
        self.assertIn(("F1", "warn"), codes(data))
        data = small(layer="L0", current="C")
        data["frames"] = data["frames"] * 9
        self.assertIn(("F10", "warn"), codes(data))

    def test_flat_view_and_relations(self):
        data = {"lang": "ko", "nodes": [{"id": "Q1", "x": 20, "y": 30, "label": "알레르기 문서"}, {"id": "Q2", "x": 70, "y": 60}],
                "relations": {"L0": [["Q1", "Q2", "포함"]]}, "query": {"x": 50, "y": 50}}
        spec = figure.Spec(data)
        self.assertEqual(spec.view, "flat")
        self.assertEqual(figure.check(spec), [])
        texts = [el.text for el in ET.fromstring(figure.draw(spec)).iter(SVG + "text")]
        for word in ("포함", "알레르기 문서", "관계", "질문"):
            self.assertIn(word, texts)


def run(*args, stdin=None, cwd=None, environment=None):
    return subprocess.run([sys.executable, str(SCRIPT)] + [str(a) for a in args], input=stdin,
                          capture_output=True, cwd=cwd, env=environment, timeout=60)


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_writes_one_file_per_frame_and_nothing_else(self):
        out = self.base / "out"
        out.mkdir()
        result = run("-o", out / "hnsw.svg", "--", EXAMPLE, cwd=self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["hnsw-{}.svg".format(n) for n in range(1, 7)])
        self.assertEqual(sorted(p.name for p in self.base.iterdir()), ["out"])
        for path in out.iterdir():
            ET.parse(str(path))
        result = run("--sheet", "5,6", "-o", out / "compare.svg", "--", EXAMPLE)
        self.assertEqual(result.returncode, 0, result.stderr)
        sheet = ET.parse(str(out / "compare.svg")).getroot()
        self.assertEqual(len(sheet.findall(SVG + "svg")), 2)

    def test_check_writes_nothing_and_errors_fail(self):
        result = run("--check", "-o", self.base / "x.svg", "--", EXAMPLE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"0 findings", result.stdout)
        self.assertEqual(list(self.base.iterdir()), [])
        bad = self.base / "bad.json"
        bad.write_text(json.dumps(small(layer="L0", path=[["A", "C"]])), encoding="utf-8")
        result = run("-o", self.base / "x.svg", "--", bad)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"F5 error", result.stdout)
        self.assertEqual(sorted(p.name for p in self.base.iterdir()), ["bad.json"])

    def test_unreadable_and_misshapen_specs(self):
        broken = self.base / "broken.json"
        broken.write_text("{", encoding="utf-8")
        result = run(broken)
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot read", result.stderr.decode("utf-8"))
        shape = self.base / "shape.json"
        shape.write_text(json.dumps({"nodes": [{"x": 1}]}), encoding="utf-8")
        result = run(shape)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"F1 error", result.stdout)
        result = run(self.base / "missing.json")
        self.assertEqual(result.returncode, 2)

    def test_korean_on_standard_output_without_a_console_encoding(self):
        data = copy.deepcopy(small(layer="L1", current="B"))
        data["lang"] = "ko"
        environment = {key: value for key, value in os.environ.items() if key != "PYTHONIOENCODING"}
        result = run("--frame", "1", "-", stdin="﻿".encode("utf-8") + json.dumps(data).encode("utf-8"), environment=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        svg = result.stdout.decode("utf-8")
        self.assertIn("지금 보는 노드", svg)
        ET.fromstring(svg[svg.index("<svg"):])


class SourceTest(unittest.TestCase):
    def test_standard_library_only_and_no_network(self):
        tree = ast.parse(read_text(SCRIPT))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module.split(".")[0])
        self.assertLessEqual(imported, {"argparse", "json", "math", "re", "sys", "xml"})

    def test_the_guide_is_linked_and_names_every_check(self):
        guide = read_text(GUIDE)
        self.assertLess(len(guide.splitlines()), 500)
        for code in ("F{}".format(n) for n in range(1, 13)):
            self.assertIn("| {} |".format(code), guide)
        source = read_text(SCRIPT)
        for code in ("F{}".format(n) for n in range(1, 13)):
            self.assertIn('"{}"'.format(code), source)
        self.assertIn("references/concept.md", read_text(SKILL / "SKILL.md"))
        self.assertIn("concept.md", read_text(SKILL / "references" / "choose.md"))
        self.assertIn("../assets/hnsw-search.json", guide)


if __name__ == "__main__":
    unittest.main()
