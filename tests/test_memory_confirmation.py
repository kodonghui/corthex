"""Keep the confirmed MEMORY decisions consistent across the stage sources and fixtures."""

import re
import unittest
from collections import Counter

from _common import ROOT, load_json, read_text
from test_memory_api import code_block, fits
from test_memory_wbs import D3_SUPERSEDED, section, tables

DOCS = ROOT / "docs"
STAGES = ("02-prd", "04-functional-spec", "05-erd", "06-api", "10-wbs", "12-qa")


def definitions(text, prefix):
    return {row[0]: row for rows in tables(text) for row in rows[1:]
            if re.fullmatch(prefix + r"-\d{3}", row[0])}


class ConfirmationTest(unittest.TestCase):
    def test_requirement_ids_priorities_and_confirmed_decisions(self):
        text = read_text(DOCS / "02-prd/memory.md")
        requirements = definitions(text, "REQ")
        self.assertEqual(list(requirements), ["REQ-%03d" % n for n in list(range(1, 66)) + [194, 195, 196] + list(range(219, 226))])
        for key in ("REQ-194", "REQ-195", "REQ-196", "REQ-219", "REQ-220", "REQ-221", "REQ-222", "REQ-224", "REQ-225"):
            self.assertEqual(requirements[key][3], "Should")
            self.assertEqual(requirements[key][-1], "active")
        self.assertEqual(requirements["REQ-223"][3], "Could")
        self.assertEqual(requirements["REQ-223"][-1], "active")
        for key in ("REQ-031", "REQ-033", "REQ-034", "REQ-042", "REQ-046", "REQ-061"):
            self.assertEqual(requirements[key][-1], "active")
        for number in range(219, 226):
            self.assertIn("Decision 2026-11-03", requirements["REQ-%03d" % number][5])
        decisions = section(text, "## Decisions in force")
        for number in range(1, 5):
            self.assertRegex(decisions, r"\| 2026-10-27 \| \*\*D%d\.\*\*" % number)
        self.assertIn("Passed on 2026-10-27:", section(text, "## For the checkpoint"))
        for word in ("Postgres", "pgvector", "HTTPS", "standard library", "revocable", "no direct"):
            self.assertIn(word, requirements["REQ-042"][1])
        self.assertEqual(requirements["REQ-044"][1], "The memory plugin shall never sync raw logs or the search index.")

    def test_retention_default_range_fixtures_and_consent(self):
        schema = load_json(DOCS / "06-api/memory-configuration.schema.json")
        retention = schema["properties"]["retention"]["properties"]["days"]
        self.assertEqual((retention["default"], retention["minimum"], retention["maximum"]), (100, 1, 3650))
        for days in (1, 100, 3650):
            self.assertEqual(fits(schema, {"retention": {"days": days}}), [])
        for days in (0, 3651):
            self.assertTrue(fits(schema, {"retention": {"days": days}}))
        examples = load_json(DOCS / "06-api/memory-examples.json")
        self.assertEqual(examples["configuration"]["valid"]["with-sync"]["retention"]["days"], 100)
        self.assertEqual(examples["result"]["valid"]["on-done"]["data"]["retention_days"], 100)
        consent = examples["result"]["valid"]["on-asks"]["data"]["consent"]
        self.assertEqual(consent["version"], 1)
        self.assertIn("100 days", consent["text"])
        self.assertIn("Anthropic", consent["text"])
        self.assertIn("OpenAI", consent["text"])
        self.assertIn("Sync is off until you turn it on; then only the curated memory goes to a sync server that you run, through its HTTPS gateway.", consent["text"])
        for name, heading in (("memory.md", "### Consent text, version 1"), ("memory.ko.md", "### 동의 문구, 판 1")):
            self.assertEqual(code_block(read_text(DOCS / "06-api" / name), heading, "text").rstrip("\n"), consent["text"])
        for stage in STAGES:
            for suffix in (".md", ".ko.md"):
                text = read_text(DOCS / stage / ("memory" + suffix))
                self.assertNotRegex(text, r"\b30[- ]days?\b|30일")
        self.assertEqual(schema["properties"]["triggers"]["properties"]["minutes"]["default"], 30)
        self.assertEqual(schema["properties"]["models"]["properties"]["curator"]["default"], "claude-haiku-5-5")
        self.assertEqual(schema["properties"]["models"]["properties"]["effort"]["default"], "xhigh")

    def test_answered_decision_history_and_nexus_ownership_are_preserved(self):
        for name, heading, link in (("memory.md", "## Open decisions", "memory.md#open-decisions"),
                                    ("memory.ko.md", "## 열린 결정", "memory.ko.md#열린-결정")):
            text = read_text(DOCS / "02-prd" / name)
            history = section(text, heading)
            (rows,) = tables(history)
            self.assertEqual([row[0] for row in rows[1:]], ["D1", "D2", "D3", "D4"])
            for row in rows[1:]:
                self.assertEqual(len(row), 5)
                self.assertIn("2026-10-27", row[-1])
                if row[0] != "D3":
                    self.assertEqual(row[-1], "decided 2026-10-27")
            self.assertIn("NEXUS", rows[3][3])
            self.assertIn("Postgres", rows[3][3])
            self.assertIn("claude -p", rows[4][3])
            # The NEXUS PRD and its links moved to the product repository.
            # Its pinned upstream-link checks run there; this repository keeps
            # the original MEMORY decisions and an explicit ownership route.
            self.assertIn("kodonghui/corthex-nexus", read_text(ROOT / "AGENTS.md"))
            scope = section(text, "## 범위" if name.endswith(".ko.md") else "## Scope")
            outside = next(line for line in scope.splitlines() if line.startswith("- 제외:" if name.endswith(".ko.md") else "- Out:"))
            self.assertNotIn("NEXUS", outside)

    def test_bilingual_confirmation_is_at_each_reviewed_statement(self):
        functional = read_text(DOCS / "04-functional-spec/memory.ko.md")
        (rows,) = tables(section(functional, "## 사용자 흐름이 넘긴 질문의 답"))
        answers = {int(re.match(r"\d+", row[0]).group()): row[1] for row in rows[1:]}
        for point, requirement in ((4, "REQ-029"), (7, "REQ-054"), (12, "REQ-053")):
            self.assertIn("2026-10-27", answers[point])
            self.assertIn(requirement, answers[point])
            self.assertNotIn("고쳐야", answers[point])
        api = read_text(DOCS / "06-api/memory.ko.md")
        gateway = next(line for line in api.splitlines() if line.startswith("로컬 기억 플러그인"))
        self.assertIn("HTTPS", gateway)
        self.assertIn("C3", gateway)
        wbs = read_text(DOCS / "10-wbs/memory.ko.md")
        status = next(line for line in wbs.splitlines() if line.startswith("- `상태`"))
        self.assertIn(D3_SUPERSEDED, status)
        self.assertIn("실행하지 않습니다", status)
        for name in ("memory.md", "memory.ko.md"):
            intro = section(read_text(DOCS / "10-wbs" / name), "## C3: ").split("\n\n")[1]
            self.assertIn(D3_SUPERSEDED, intro)
            self.assertIn("0.4.0", intro)
        qa = read_text(DOCS / "12-qa/memory.ko.md")
        result = next(line for line in qa.splitlines() if line.startswith("- `마지막 결과`"))
        self.assertIn(D3_SUPERSEDED, result)
        self.assertIn("실행 결과가 아닙니다", result)
        coverage = section(qa, "## 커버리지").split("\n\n")[1]
        self.assertIn(D3_SUPERSEDED, coverage)
        self.assertIn("37", coverage)

    def test_legacy_git_design_is_marked_without_replacing_the_contract(self):
        for stage in STAGES[1:]:
            for suffix in (".md", ".ko.md"):
                text = read_text(DOCS / stage / ("memory" + suffix))
                self.assertIn(D3_SUPERSEDED, text)
                self.assertNotRegex(text, r"\| (?:open \(D[1-4]\)|proposed) \|")
        specs = definitions(read_text(DOCS / "04-functional-spec/memory.md"), "SPEC")
        for key in ("SPEC-026", "SPEC-027", "SPEC-028"):
            self.assertEqual(specs[key][-1], D3_SUPERSEDED)
        self.assertEqual(specs["SPEC-029"][-1], "active")
        records = definitions(read_text(DOCS / "05-erd/memory.md"), "TBL")
        for key in ("TBL-006", "TBL-018"):
            self.assertEqual(records[key][-1], D3_SUPERSEDED)
        for key in ("TBL-011", "TBL-017"):
            self.assertEqual(records[key][-1], "active")
        schema = load_json(DOCS / "06-api/memory-configuration.schema.json")
        self.assertIn(D3_SUPERSEDED, schema["properties"]["sync"]["description"])
        self.assertEqual(schema["properties"]["sync"]["required"], ["address"])

    def test_new_requirements_have_spec_flow_and_case_links(self):
        specs = definitions(read_text(DOCS / "04-functional-spec/memory.md"), "SPEC")
        for spec, requirement in (("SPEC-011", "REQ-195"), ("SPEC-021", "REQ-196"),
                                  ("SPEC-023", "REQ-196"), ("SPEC-037", "REQ-194")):
            self.assertIn(requirement, specs[spec][2])
        flows = DOCS / "03-user-flow/memory"
        for number, requirement in ((3, "REQ-196"), (4, "REQ-196"), (5, "REQ-195"), (11, "REQ-194")):
            path = next(path for path in flows.glob("FL-%03d-*.md" % number) if not path.name.endswith(".ko.md"))
            self.assertIn(requirement, read_text(path).splitlines()[4])
        cases = definitions(read_text(DOCS / "12-qa/memory.md"), "TC")
        for case, requirement in (("TC-244", "REQ-195"), ("TC-245", "REQ-194"), ("TC-203", "REQ-196")):
            self.assertIn(requirement, cases[case][2])

    def test_checkpoint_and_project_notes_record_confirmation(self):
        project = load_json(ROOT / ".corthex/project.json")
        for stage in STAGES:
            self.assertIn("2026-10-27", project["stages"][stage]["note"])
            self.assertIn("Passed on 2026-10-27:", section(read_text(DOCS / stage / "memory.md"), "## For the checkpoint"))
        self.assertIn("Passed on 2026-10-27:", section(read_text(DOCS / "03-user-flow/memory/README.md"), "## For the checkpoint"))

    def test_requirement_and_spec_translations_keep_ids_numbers_and_status(self):
        for stage, prefix in (("02-prd", "REQ"), ("04-functional-spec", "SPEC"), ("05-erd", "TBL")):
            source = definitions(read_text(DOCS / stage / "memory.md"), prefix)
            translated = definitions(read_text(DOCS / stage / "memory.ko.md"), prefix)
            self.assertEqual(list(source), list(translated))
            for key, row in source.items():
                other = translated[key]
                if len(row) >= 7:
                    self.assertEqual(row[-1], other[-1], key)
                if key == "SPEC-009":
                    self.assertEqual(Counter(re.findall(r"\d+", row[4] + row[6])),
                                     Counter(re.findall(r"\d+", other[4] + other[6])))
                for english, korean in zip(row, other):
                    self.assertEqual(Counter(re.findall(r"[A-Z]+-\d{3}", english)),
                                     Counter(re.findall(r"[A-Z]+-\d{3}", korean)), key)


if __name__ == "__main__":
    unittest.main()
