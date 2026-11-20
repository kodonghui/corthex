"""Checks the corthex-diagram skill: its grammar reference and the lint that checks Mermaid flowcharts against it."""

import ast
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _common import PLUGINS, read_text

SKILLS = PLUGINS / "corthex" / "skills"
SKILL = SKILLS / "corthex-diagram"
SCRIPT = SKILL / "scripts" / "diagram-check.py"
GRAMMAR = SKILL / "references" / "grammar.md"

HEADER = """flowchart TB
  classDef term fill:#e7f5ff,stroke:#1c7ed6,color:#212529
  classDef store fill:#e6fcf5,stroke:#0c8599,color:#212529
  classDef proc fill:#f8f9fa,stroke:#495057,color:#212529
  classDef decide fill:#f3f0ff,stroke:#7048e8,color:#212529
  classDef grade fill:#ffffff,stroke:#868e96,stroke-dasharray:6 4,color:#212529
"""


def load():
    spec = importlib.util.spec_from_file_location("corthex_diagram_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


diagram_check = load()


def rules(src, wrap=None):
    """The (rule, severity) pairs the lint finds in a Mermaid source, in order."""
    findings, _, _ = diagram_check.check(src, wrap)
    return [(rule, severity) for _, rule, severity, _ in findings]


def messages(src):
    findings, _, _ = diagram_check.check(src)
    return [message for _, _, _, message in findings]


def example():
    """The worked example in the grammar reference."""
    return re.search(r"```mermaid\n(.*?)```", read_text(GRAMMAR), re.S).group(1)


def run(*args, stdin=None, environment=None, cwd=None):
    if environment is None:
        environment = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, str(SCRIPT)] + [str(arg) for arg in args], input=stdin,
                          capture_output=True, timeout=60, env=environment, cwd=cwd)


class ScriptShapeTest(unittest.TestCase):
    def test_parses_as_python_3_8(self):
        ast.parse(read_text(SCRIPT), feature_version=(3, 8))

    def test_imports_only_the_standard_library_and_writes_nothing(self):
        allowed = {"argparse", "re", "sys"}
        for node in ast.walk(ast.parse(read_text(SCRIPT))):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module.split(".")[0]]
            else:
                continue
            for name in names:
                with self.subTest(module=name):
                    self.assertIn(name, allowed)
        source = read_text(SCRIPT)
        self.assertNotRegex(source, r"open\([^)]*['\"][wax]")
        self.assertIn("It only reads: it changes no file and sends nothing.", source)

    def test_the_skill_documents_the_command_with_quoted_paths(self):
        text = read_text(SKILL / "SKILL.md")
        self.assertIn("`python3 '<absolute skill directory>/scripts/diagram-check.py' -- '<file>'`", text)


class GrammarTest(unittest.TestCase):
    def test_the_worked_example_passes(self):
        findings, boxes, lines = diagram_check.check(example())
        self.assertEqual(findings, [])
        self.assertEqual((boxes, lines), (17, 18))

    def test_the_tables_name_the_classes_the_lint_knows(self):
        text = read_text(GRAMMAR)
        rows = re.findall(r"^\| [^|]+ \| `(\w+)` \|", text, re.M)
        known = set(diagram_check.KINDS) | diagram_check.LINES | diagram_check.MODIFIERS
        self.assertEqual(set(rows), known - {"ghost"})
        for kind, form in (("term", "stadium"), ("doc", "doc"), ("store", "cyl"), ("proc", "rect"),
                           ("decide", "diam"), ("llm", "fr-rect"), ("grade", "rect")):
            with self.subTest(kind=kind):
                self.assertIn(form, diagram_check.KINDS[kind])
                self.assertRegex(text, r"\| `%s` \| `@\{ shape: %s \}`" % (kind, re.escape(form)))

    def test_the_colour_block_is_the_example_s_and_every_pair_is_readable(self):
        text = read_text(GRAMMAR)
        block = re.search(r"```text\n(classDef .*?)```", text, re.S).group(1).split("\n")
        block = [line for line in block if line]
        example_lines = [line.strip() for line in example().split("\n") if line.strip().startswith("classDef")]
        self.assertEqual(block, example_lines)
        self.assertNotIn("G7", [rule for rule, _ in rules("flowchart TB\n" + "\n".join(block))])

    def test_the_version_matches(self):
        self.assertIn("Version %s." % diagram_check.GRAMMAR_VERSION, read_text(GRAMMAR))


class CheckTest(unittest.TestCase):
    def test_a_missing_read_line_is_found(self):
        src = HEADER + """
  A@{ shape: rect, label: "Embed" }
  S@{ shape: cyl, label: "Index" }
  B@{ shape: rect, label: "Search" }
  A e1@==> S
  A e2@--> B
  class A,B proc
  class S store
  class e1 write
  class e2 pass
"""
        found = rules(src)
        self.assertIn(("G9", "warn"), found)
        self.assertIn(("G8", "warn"), found)
        self.assertIn(("G5", "warn"), found)

    def test_lines_that_touch_a_store_must_be_write_or_read(self):
        src = HEADER + """
  S@{ shape: cyl, label: "Index" }
  B@{ shape: rect, label: "Search" }
  C@{ shape: rect, label: "Rank" }
  S e1@--> B
  B e2@==> C
  class S store
  class B,C proc
  class e1 pass
  class e2 read
"""
        found = messages(src)
        self.assertTrue(any("S->B touches a store, so it is a 'read' line; it is 'pass'" in m for m in found), found)
        self.assertTrue(any("B->C is 'read' but touches no store" in m for m in found), found)

    def test_kinds_and_shapes(self):
        src = HEADER + """
  A[(Index)]
  B@{ shape: rect, label: "Ask" }
  C["Plain"]
  class A proc
  class B term
"""
        found = messages(src)
        self.assertTrue(any("box A is proc but drawn as 'cyl'" in m for m in found), found)
        self.assertTrue(any("box B is term but drawn as 'rect'; draw it with `@{ shape: stadium }`" in m for m in found), found)
        self.assertTrue(any("box C needs exactly one kind class" in m for m in found), found)

    def test_a_decision_needs_labelled_branches(self):
        src = HEADER + """
  D{Found?}
  X[Use it]
  Y[Search again]
  D e1@-->|yes| X
  D e2@--> Y
  class D decide
  class X,Y proc
  class e1,e2 pass
"""
        self.assertIn(("G4", "error"), rules(src))
        src = src.replace("D e2@--> Y", "D e2@-- no --> Y")
        self.assertNotIn(("G4", "error"), rules(src))

    def test_korean_lines_that_break_inside_words_are_found(self):
        def box(label):
            return HEADER + '  A@{ shape: rect, label: "%s" }\n  class A proc\n' % label

        self.assertIn(("G6", "warn"), rules(box("출처 페이지 적중")))
        self.assertIn(("G6", "warn"), rules(box("Notion 문서 11개")))
        self.assertNotIn(("G6", "warn"), rules(box("출처 페이지<br/>적중")))
        self.assertNotIn(("G6", "warn"), rules(box("문서 참조 단서")))
        self.assertNotIn(("G6", "warn"), rules(box("Key facts in the answer text")))
        self.assertNotIn(("G6", "warn"), rules(box("출처 페이지 적중"), wrap=240))
        # The frontmatter cannot widen the limit: no target is known to honour it yet.
        self.assertIn(("G6", "warn"), rules("---\nconfig:\n  flowchart:\n    wrappingWidth: 240\n---\n" + box("출처 페이지 적중")))

    def test_colours_need_a_readable_text_colour(self):
        found = rules("flowchart TB\n  classDef a fill:#fff9db,stroke:#e67700\n  classDef b fill:#ffffff,color:#cccccc\n"
                      "  style X fill:#000,color:#111\n")
        self.assertEqual(found.count(("G7", "warn")), 1)
        self.assertEqual(found.count(("G7", "error")), 2)
        # Basic named colours are read; other values are named as not checked rather than as missing.
        self.assertEqual(rules("flowchart TB\n  classDef a fill:#ffffff,color:black\n"), [])
        self.assertEqual(rules("flowchart TB\n  classDef a fill:#fff,color:lightgrey\n"), [("G7", "error")])
        found = messages("flowchart TB\n  classDef a fill:#fff,color:var(--ink)\n  classDef ghost fill:none,stroke:none\n")
        self.assertEqual(len(found), 1, found)
        self.assertIn("contrast not checked, because 'var(--ink)'", found[0])

    def test_a_class_after_the_shape_syntax_does_not_parse(self):
        src = HEADER + '  A@{ shape: rect, label: "Embed" }:::proc\n'
        self.assertIn(("G0", "error"), rules(src))

    def test_marks_tags_and_the_legend(self):
        src = HEADER + """
  subgraph LEG["범례"]
    k1@{ shape: rect, label: "Process" }
    t1["[chunk] part of a page"]
  end
  A@{ shape: rect, label: "[chunk] Embed" }
  B@{ shape: rect, label: "[page] Expand" }
  C@{ shape: rect, label: "Merge rule" }
  D@{ shape: rect, label: "[row] Pick" }
  E@{ shape: rect, label: "[table] Join" }
  A e1@--> B
  B e2@--> C
  C e3@--> D
  D e4@--> E
  E e5@--> A
  class k1,A,B,C,D,E proc
  class C gap
  class t1 ghost
  class e1,e2,e3,e4,e5 pass
"""
        found = messages(src)
        self.assertTrue(any("box C is marked not in the source" in m for m in found), found)
        self.assertTrue(any("4 tag kinds" in m for m in found), found)
        self.assertTrue(any("the legend does not show: pass, [page], [row], [table], gap" in m for m in found), found)
        self.assertNotIn(("G5", "warn"), rules(src.replace('subgraph LEG["범례"]', "subgraph LEG").replace(
            "  end\n", "  end\n  %% legend: below\n", 1)))

    def test_line_kinds_use_their_arrows(self):
        src = HEADER + """
  A@{ shape: rect, label: "Pick" }
  G@{ shape: rect, label: "Hit" }
  B@{ shape: rect, label: "Answer" }
  A e1@--> G
  A e2@-.-> B
  class A,B proc
  class G grade
  class e1 gradeLine
  class e2 pass
"""
        found = messages(src)
        self.assertTrue(any("line A->G is 'gradeLine', drawn '-.->' in this grammar, but uses '-->'" in m for m in found), found)
        self.assertTrue(any("line A->B is 'pass', drawn '-->' in this grammar, but uses '-.->'" in m for m in found), found)

    def test_reads_the_common_ways_to_write_lines(self):
        src = HEADER + """
  A[One] & B[Two] e1@--> C[Three]
  C-->D[Four]; D -- yes --> E[Five]
  E ==>|done| F([End])
  E ~~~ A
  class A,B,C,D,E proc
  class F term
"""
        diagram = diagram_check.parse(src)
        pairs = [(e["src"], e["dst"], e["label"], e["family"]) for e in diagram["edges"]]
        self.assertEqual(pairs, [("A", "C", "", "normal"), ("B", "C", "", "normal"), ("C", "D", "", "normal"),
                                 ("D", "E", "yes", "normal"), ("E", "F", "done", "thick"), ("E", "A", "", "invisible")])
        self.assertEqual(diagram["nodes"]["F"]["shape"], "stadium")
        self.assertEqual(diagram["nodes"]["A"]["label"], "One")

    def test_reads_a_dotted_line_with_its_label_inline(self):
        src = HEADER + """
  D{ok?} e1@-. no .-> B[b]
  D e2@-->|yes| C[c]
  B e3@--> G[g]
  class D decide
  class B,C proc
  class G grade
  class e1,e2 pass
  class e3 gradeLine
"""
        diagram = diagram_check.parse(src)
        pairs = [(e["src"], e["dst"], e["label"], e["family"]) for e in diagram["edges"]]
        self.assertEqual(pairs, [("D", "B", "no", "dotted"), ("D", "C", "yes", "normal"), ("B", "G", "", "normal")])
        self.assertEqual(diagram["nodes"]["D"]["shape"], "diam")
        found = rules(src)
        self.assertNotIn(("G2", "error"), found)
        self.assertNotIn(("G4", "error"), found)

    def test_reads_korean_ids_and_names_statements_it_cannot_read(self):
        findings, boxes, lines = diagram_check.check("flowchart TB\n  수집[수집] --> 저장[(색인)]\n")
        self.assertEqual((boxes, lines), (2, 1))
        self.assertEqual([(rule, severity) for _, rule, severity, _ in findings], [("G1", "error"), ("G1", "error")])
        found = messages(HEADER + '  "A quoted statement" --> B\n')
        self.assertTrue(any("could not read this statement" in m for m in found), found)

    def test_skips_a_description_written_over_several_lines(self):
        src = HEADER + """  accTitle: Order flow
  accDescr {
    Shows how the order flows
    from the cart to the confirmation
  }
  A([Start]) e1@--> B([End])
  class A,B term
  class e1 pass
"""
        self.assertEqual(rules(src), [])

    def test_a_mark_alone_needs_a_legend(self):
        src = HEADER + """
  A([Start]) e1@--> B[Merge] e2@--> C([End])
  class A,C term
  class B proc
  class B key
  class e1,e2 pass
"""
        self.assertEqual(rules(src), [("G5", "warn")])
        self.assertEqual(rules(src.replace("  class B key\n", "")), [])

    def test_a_structure_is_checked_for_syntax_line_breaks_and_colours_only(self):
        src = """flowchart LR
  %% grammar: structure
  ordering["CTX-001 Ordering"] -->|"order number"| payment["CTX-002 결제와 환불을 맡는 컨텍스트"]
  payment -.->|"Payment failed"| ordering
  classDef ctx fill:#ffffff,color:#cccccc
"""
        findings, boxes, lines = diagram_check.check(src)
        self.assertEqual((boxes, lines), (2, 2))
        self.assertEqual(sorted(rule for _, rule, _, _ in findings), ["G6", "G7"])
        self.assertIn(("G1", "error"), rules(src.replace("  %% grammar: structure\n", "")))

    def test_every_flowchart_in_the_skills_passes(self):
        for path in sorted(SKILLS.glob("*/**/*.md")):
            for start, src in diagram_check.read_blocks(str(path), read_text(path)):
                if diagram_check.kind_name(src) not in ("flowchart", "graph"):
                    continue
                with self.subTest(path=path.relative_to(SKILLS).as_posix(), line=start):
                    self.assertEqual(diagram_check.check(src)[0], [])


class CommandTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_exit_codes_lines_and_other_diagram_types(self):
        good = self.base / "good.mmd"
        good.write_text(example(), encoding="utf-8")
        page = self.base / "page.md"
        page.write_text("# Page\n\n```mermaid\nsequenceDiagram\n  A->>B: hi\n```\n\nText\n\n```mermaid\n" + HEADER
                        + '  A@{ shape: rect, label: "Embed" }:::proc\n```\n', encoding="utf-8")
        before = sorted(path.name for path in self.base.iterdir())

        result = run(good)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("good.mmd:1: 17 boxes, 18 lines, 0 findings", result.stdout.decode("utf-8"))

        result = run(good, page)
        self.assertEqual(result.returncode, 1, result.stderr)
        out = result.stdout.decode("utf-8")
        self.assertIn("page.md:4: sequenceDiagram block, not checked", out)
        self.assertIn("page.md:11: 1 boxes, 0 lines, 2 findings", out)
        self.assertIn("page.md:17: G0 error:", out)

        result = run("-", stdin="﻿".encode("utf-8") + example().encode("utf-8"),
                     environment={key: value for key, value in os.environ.items() if key != "PYTHONIOENCODING"})
        self.assertEqual(result.returncode, 0, result.stderr)

        result = run(self.base / "missing.mmd", good)
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot read", result.stderr.decode("utf-8"))
        self.assertEqual(sorted(path.name for path in self.base.iterdir()), before)


class LinksTest(unittest.TestCase):
    def test_other_skills_hand_diagrams_to_this_one(self):
        for path in (SKILLS / "corthex" / "SKILL.md", SKILLS / "corthex-record" / "SKILL.md",
                     SKILLS / "corthex-study" / "references" / "structure.md",
                     SKILLS / "corthex-define" / "references" / "03-user-flow.md",
                     SKILLS / "corthex-uxui" / "SKILL.md"):
            with self.subTest(path=path.relative_to(SKILLS).as_posix()):
                self.assertIn("`corthex-diagram`", read_text(path))


if __name__ == "__main__":
    unittest.main()
