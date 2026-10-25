"""Checks the corthex-memory test plan of stage 12, docs/12-qa/memory.md: its cases against the user flows,
the functional spec, the memory store, the requirements and the work breakdown of stage 10, its tables
and counts against its cases, and its Korean translation."""

import re
import unittest
from collections import Counter

from _common import ROOT, read_text
from test_memory_wbs import SHARED, STEPS, claimed, criteria_counts, ids, listed, section, tables, tested_by, ticked
from test_memory_wbs import COLUMNS as TASK_COLUMNS

DOCS = ROOT / "docs"
DOC = DOCS / "12-qa" / "memory.md"
TRANSLATION = DOCS / "12-qa" / "memory.ko.md"
STAGE = ROOT / "plugins" / "corthex" / "skills" / "corthex-build" / "references" / "12-qa.md"
COLUMNS = ["ID", "Case", "From", "Task", "Runs as", "Steps", "Expected", "Last result"]
RUNS = ["contract", "api", "e2e", "agent", "manual", "real"]
# The From prefixes of the codes that every command, every model call, and the hooks and the memory worker
# in the failure log can have: the last three rows of stage 10's outcomes.
TOKENS = dict(zip(["commands", "model-calls", "failure-log"], SHARED))
LAST = re.compile(r"not run|removed \(\d{4}-\d{2}-\d{2}\).+|(?:pass|fail|blocked)\b.* \(commit [0-9a-f]{7,40}\).*")
# A Korean particle after an ID depends on how its number ends when read aloud: 2, 4, 5 and 9 end with a
# vowel, 1, 7 and 8 with ㄹ, and the others, 0 and the tens, hundreds and thousands, with another consonant.
PARTICLES = {"이": "가", "은": "는", "을": "를", "과": "와", "으로": "로"}
ID_PARTICLE = re.compile(r"(?:REQ|FL|SPEC|TBL|API|TASK|TC|BUG)-\d{1,6}(?:#(\d+))?(으로|이|가|은|는|을|를|과|와|로)(?![가-힣])")


def fitting_particle(number, particle):
    pair = next((first, second) for first, second in PARTICLES.items() if particle in (first, second))
    last = int(number) % 10
    if pair[0] == "으로":
        return pair[0] if last in (0, 3, 6) else pair[1]
    return pair[1] if last in (2, 4, 5, 9) else pair[0]


def wrong_particles(text):
    found = []
    for match in ID_PARTICLE.finditer(text):
        number = match.group(1) or re.search(r"-(\d+)", match.group(0)).group(1)
        if fitting_particle(number, match.group(2)) != match.group(2):
            found.append(match.group(0))
    return found


def outcome(token):
    """(row of stage 10's outcomes, code) that a From token names, or None."""
    base, _, code = token.partition("#")
    if code and base in TOKENS:
        return TOKENS[base], code
    if code and base.startswith("API-"):
        return base, code
    return None


class TestPlanTest(unittest.TestCase):
    def setUp(self):
        self.doc = read_text(DOC)
        self.steps, self.cases = {}, {}
        for step in STEPS:
            (rows,) = tables(section(self.doc, "## %s: " % step))
            self.steps[step] = rows
            for row in rows[1:]:
                self.assertNotIn(row[0], self.cases)
                case = dict(zip(COLUMNS, row), step=step)
                case.update(tasks=listed(case["Task"]), runs=listed(case["Runs as"]), tokens=listed(case["From"]))
                self.cases[row[0]] = case
        self.current = {key: case for key, case in self.cases.items() if not case["Last result"].startswith("removed")}
        wbs = read_text(DOCS / "10-wbs" / "memory.md")
        self.tasks = {}
        for step in STEPS:
            (rows,) = tables(section(wbs, "## %s: " % step))
            self.tasks.update((row[0], dict(zip(TASK_COLUMNS, row), step=step)) for row in rows[1:])
        (rows,) = tables(section(wbs, "## Outcomes"))
        self.outcomes = {row[0]: (ticked(row[1]), tested_by(row[2])) for row in rows[1:]}
        self.criteria = criteria_counts()
        self.requirements = {}
        for rows in tables(read_text(DOCS / "02-prd" / "memory.md")):
            if rows[0][:4] == ["ID", "Requirement", "Type", "Priority"]:
                self.requirements.update((row[0], row) for row in rows[1:])
        self.nonfunctional = [key for key, row in self.requirements.items() if row[2] == "non-functional"]
        folder = DOCS / "03-user-flow" / "memory"
        self.flows = sorted(path.name[:6] for path in folder.glob("FL-*.md") if not path.name.endswith(".ko.md"))
        self.records = re.findall(r"^\| (TBL-\d{3}) \|", read_text(DOCS / "05-erd" / "memory.md"), re.M)

    def named(self, cell):
        found = listed(cell)
        self.assertTrue(found)
        self.assertEqual(len(found), len(set(found)))
        self.assertLessEqual(set(found), set(self.cases))
        return found

    def test_each_step_has_the_case_table(self):
        for step in STEPS:
            with self.subTest(step=step):
                header, rows = self.steps[step][0], self.steps[step][1:]
                self.assertEqual(header, COLUMNS)
                self.assertTrue(rows)
                self.assertTrue(all(len(row) == len(COLUMNS) and all(row) for row in rows))
        # Cases are never renumbered or deleted, so their numbers run step by step without a gap.
        self.assertEqual(list(self.cases), ["TC-%03d" % n for n in range(1, len(self.cases) + 1)])
        titles = Counter(case["Case"] for case in self.cases.values())
        self.assertEqual([title for title, count in titles.items() if count > 1], [])
        for key, case in self.cases.items():
            with self.subTest(case=key):
                self.assertRegex(case["Last result"], "^(%s)$" % LAST.pattern)

    def test_each_case_has_tasks_of_its_step(self):
        for key, case in self.cases.items():
            with self.subTest(case=key):
                self.assertTrue(case["tasks"])
                self.assertEqual(len(case["tasks"]), len(set(case["tasks"])))
                for task in case["tasks"]:
                    self.assertIn(task, self.tasks)
                    self.assertEqual(self.tasks[task]["step"], case["step"], task)
                    if key in self.current:
                        self.assertFalse(self.tasks[task]["Status"].startswith("removed"), task + " is removed")
        written = {task for case in self.current.values() for task in case["tasks"]}
        current = {key for key, task in self.tasks.items() if not task["Status"].startswith("removed")}
        self.assertEqual(current - written, set(), "tasks without cases")

    def test_each_case_says_how_it_runs(self):
        for key, case in self.cases.items():
            with self.subTest(case=key):
                runs = case["runs"]
                self.assertEqual([run for run in RUNS if run in runs], runs)
                # `real` marks how a case runs, not a way of running alone.
                self.assertNotEqual(runs, ["real"])

    def test_from_names_what_exists(self):
        for key, case in self.cases.items():
            with self.subTest(case=key):
                tokens = case["tokens"]
                self.assertEqual(len(tokens), len(set(tokens)))
                self.assertTrue(any(re.fullmatch(r"(?:FL|SPEC|REQ)-\d{3}(?:#\d+)?", token) for token in tokens), "no flow, behaviour or requirement")
                for token in tokens:
                    named = outcome(token)
                    criterion = re.fullmatch(r"(SPEC-\d{3})#(\d+)", token)
                    if named:
                        self.assertIn(named[0], self.outcomes, token)
                        self.assertIn(named[1], self.outcomes[named[0]][0], token)
                    elif criterion:
                        self.assertIn(criterion.group(1), self.criteria, token)
                        self.assertTrue(1 <= int(criterion.group(2)) <= self.criteria[criterion.group(1)], token)
                    elif token.startswith("SPEC-"):
                        self.assertIn(token, self.criteria)
                    elif token.startswith("FL-"):
                        self.assertIn(token, self.flows)
                    elif token.startswith("REQ-"):
                        self.assertIn(token, self.requirements)
                    else:
                        self.assertIn(token, self.records)

    def test_every_criterion_has_a_case_for_each_task_that_names_it(self):
        claims = set()
        for key, task in self.tasks.items():
            if not task["Status"].startswith("removed"):
                for spec, numbers in claimed(task["Done when"], self.criteria):
                    claims |= {("%s#%d" % (spec, number), key) for number in numbers}
        self.assertEqual(len({criterion for criterion, _ in claims}), sum(self.criteria.values()))
        covered = set()
        for key, case in self.current.items():
            for token in case["tokens"]:
                if re.fullmatch(r"SPEC-\d{3}#\d+", token):
                    with self.subTest(case=key, criterion=token):
                        self.assertTrue({(token, task) for task in case["tasks"]} & claims, "named by none of its tasks")
                    covered |= {(token, task) for task in case["tasks"]}
        self.assertEqual(sorted(claims - covered), [])

    def test_every_outcome_has_a_case_for_each_task_that_tests_it(self):
        expected = set()
        for row, (codes, parts) in self.outcomes.items():
            for task, some in parts:
                expected |= {(row, code, task) for code in (codes if some is None else some)}
        covered = set()
        for case in self.current.values():
            for token in case["tokens"]:
                if outcome(token):
                    covered |= {outcome(token) + (task,) for task in case["tasks"]}
        self.assertEqual(sorted(expected - covered), [])

    def test_every_flow_is_walked(self):
        for flow in self.flows:
            with self.subTest(flow=flow):
                self.assertTrue(any(flow in case["tokens"] and "agent" in case["runs"] for case in self.current.values()))
        (rows,) = tables(section(self.doc, "## Walking the flows"))
        self.assertEqual(rows[0], ["Flow", "Path", "Cases"])
        self.assertEqual(sorted({row[0] for row in rows[1:]}), self.flows)
        for row in rows[1:]:
            with self.subTest(flow=row[0], path=row[1]):
                self.named(row[2])

    def test_kinds_of_cases(self):
        (stage,) = [rows for rows in tables(section(read_text(STAGE), "## Kinds of cases")) if rows[0][0] == "Kind"]
        (rows,) = tables(section(self.doc, "## Kinds of cases"))
        self.assertEqual(rows[0], ["Kind", "Where it applies", "Cases"])
        self.assertEqual([row[0] for row in rows[1:]], [row[0] for row in stage[1:]])
        for row in rows[1:]:
            with self.subTest(kind=row[0]):
                if row[2] == "none":
                    self.assertTrue(row[1].startswith("Not applicable: "), "say why")
                else:
                    found = self.named(row[2])
                    self.assertEqual(found, sorted(found))

    def test_ai_calls(self):
        spec = section(read_text(DOCS / "04-functional-spec" / "memory.md"), "## AI calls")
        (rows,) = tables(section(self.doc, "## AI calls"))
        self.assertEqual(rows[0], ["AI call", "Inside its scope", "Outside its scope", "Never sent", "Real model"])
        self.assertEqual([row[0] for row in rows[1:]], re.findall(r"^### (.+)$", spec, re.M))
        for row in rows[1:]:
            with self.subTest(call=row[0]):
                for cell in row[1:]:
                    self.named(cell)
                for key in listed(row[4]):
                    self.assertIn("real", self.cases[key]["runs"], key)

    def test_requirements(self):
        (rows,) = tables(section(self.doc, "## Non-functional requirements"))
        self.assertEqual(rows[0], ["Requirement", "Priority", "What it asks", "Cases", "How it is checked"])
        self.assertEqual([row[0] for row in rows[1:]], self.nonfunctional)
        naming = {req: [key for key, case in self.cases.items() if req in case["tokens"]] for req in self.nonfunctional}
        for row in rows[1:]:
            with self.subTest(requirement=row[0]):
                self.assertEqual(row[1], self.requirements[row[0]][3])
                self.assertTrue(naming[row[0]])
                self.assertEqual(listed(row[3]), naming[row[0]])
        (rows,) = tables(section(self.doc, "## Performance"))
        self.assertEqual(rows[0], ["Requirement", "What it asks", "Cases", "Measured", "Load", "Where"])
        for row in rows[1:]:
            with self.subTest(requirement=row[0]):
                self.assertLessEqual(set(self.named(row[2])), set(naming[row[0]]))

    def test_notes_of_earlier_stages(self):
        (rows,) = tables(section(self.doc, "## Notes of earlier stages"))
        self.assertEqual(rows[0], ["Stage", "Note", "Cases"])
        self.assertLessEqual({row[0] for row in rows[1:]}, {"03", "04", "05", "06"})
        for row in rows[1:]:
            with self.subTest(note=row[1]):
                if row[2] != "every case of the C1, C2 and C3 tables":
                    self.named(row[2])

    def test_coverage_counts_the_cases(self):
        text = section(self.doc, "## Coverage")
        passing = [case for case in self.current.values() if case["Last result"].startswith("pass")]
        tokens = {token for case in passing for token in case["tokens"]}
        rows = {(row, code) for row, (codes, _) in self.outcomes.items() for code in codes}
        found = re.search(r"cover (\d+) of (\d+) flows, (\d+) of (\d+) acceptance criteria, (\d+) of (\d+) outcomes and (\d+) of (\d+) non-functional requirements", text)
        self.assertEqual([int(number) for number in found.groups()], [
            len(tokens & set(self.flows)), len(self.flows),
            len({token for token in tokens if re.fullmatch(r"SPEC-\d{3}#\d+", token)}), sum(self.criteria.values()),
            len({outcome(token) for token in tokens if outcome(token)}), len(rows),
            len(tokens & set(self.nonfunctional)), len(self.nonfunctional)])
        walked = {token for case in passing if "agent" in case["runs"] for token in case["tokens"] if token in self.flows}
        self.assertEqual(re.search(r"walked (\d+) of (\d+) flows", text).groups(), (str(len(walked)), str(len(self.flows))))
        counts = Counter(case["step"] for case in self.cases.values())
        found = re.search(r"The plan has (\d+) cases: (\d+) for C1, (\d+) for C2 and (\d+) for C3", text)
        self.assertEqual([int(number) for number in found.groups()], [len(self.cases)] + [counts[step] for step in STEPS])
        (rows,) = tables(text)
        self.assertEqual(rows[0], ["Runs as"] + STEPS + ["All"])
        self.assertEqual([row[0] for row in rows[1:]], ["`%s`" % run for run in RUNS])
        for row in rows[1:]:
            with self.subTest(runs=row[0]):
                each = [sum(ticked(row[0])[0] in case["runs"] for case in self.cases.values() if case["step"] == step) for step in STEPS]
                self.assertEqual(row[1:], [str(count) for count in each + [sum(each)]])


class TranslationTest(unittest.TestCase):
    def test_the_translation_keeps_every_table(self):
        source, translation = read_text(DOC), read_text(TRANSLATION)
        self.assertEqual(len(re.findall(r"^#+ ", translation, re.M)), len(re.findall(r"^#+ ", source, re.M)))
        source, translation = tables(source), tables(translation)
        self.assertEqual(len(translation), len(source))
        for number, (rows, others) in enumerate(zip(source, translation)):
            self.assertEqual(len(others), len(rows), "table %d" % (number + 1))
            for row, other in zip(rows[1:], others[1:]):
                with self.subTest(row=row[0]):
                    self.assertEqual(len(other), len(row))
                    for cell, theirs in zip(row, other):
                        self.assertEqual(Counter(ids(theirs)), Counter(ids(cell)))
                        self.assertEqual(Counter(ticked(theirs)), Counter(ticked(cell)))
                    if rows[0] == COLUMNS:
                        for column in ("ID", "From", "Task", "Runs as"):
                            index = COLUMNS.index(column)
                            self.assertEqual(other[index], row[index], column)
                        self.assertEqual(other[-1] == "실행 전", row[-1] == "not run")
                        self.assertEqual(re.findall(r"[0-9a-f]{7,40}(?=\))", other[-1]), re.findall(r"[0-9a-f]{7,40}(?=\))", row[-1]))

    def test_particles_fit_the_ids(self):
        self.assertEqual(wrong_particles(read_text(TRANSLATION)), [])
        self.assertEqual(wrong_particles("TC-028가 TC-100를 TASK-057와 TC-003로"), ["TC-028가", "TC-100를", "TASK-057와", "TC-003로"])
        self.assertEqual(wrong_particles("TC-028이 TC-100을 TASK-059와 FL-012로 SPEC-002#1로 TC-003으로"), [])


if __name__ == "__main__":
    unittest.main()
