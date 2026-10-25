"""Checks the corthex-memory work breakdown of stage 10, docs/10-wbs/memory.md: its tasks against the
functional spec, the memory store and the interfaces, and its table of outcomes against stage 06."""

import re
import unittest
from collections import Counter

from _common import ROOT, load_json, read_text

DOCS = ROOT / "docs"
DOC = DOCS / "10-wbs" / "memory.md"
TRANSLATION = DOCS / "10-wbs" / "memory.ko.md"
API = DOCS / "06-api"
STEPS = ["C1", "C2", "C3"]
COLUMNS = ["ID", "Task", "From", "Touches", "Depends on", "Owner", "Estimate", "Done when", "Status"]
STATUS = re.compile(r"todo|in progress|done \(#\d+\)|removed \(\d{4}-\d{2}-\d{2}\)")
TESTED = "its outcomes have passing tests"
SHARED = ["Every command", "Every model call", "The failure log of the hooks and the memory worker"]
# What a hook adds to the outcomes of its section: its input cannot be read, or no host can be told.
HOOK_INPUT = ["bad-input", "unknown-host"]
ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth"]
# `SPEC-009's first and third` names those acceptance criteria; `SPEC-005's` alone names them all.
CLAIM = re.compile(r"(SPEC-\d{3})'s((?:,? (?:and )?(?:(?:first|last) two|%s)\b)*)" % "|".join(ORDINALS))


def section(text, heading):
    """From heading, the whole line or its start, to the next heading of the same level or above."""
    start = re.search("^" + re.escape(heading), text, re.M).start()
    level = heading.split(" ", 1)[0]
    ends = [text.find("\n" + "#" * size + " ", start + len(heading)) for size in range(1, len(level) + 1)]
    ends = [end for end in ends if end != -1]
    return text[start:min(ends)] if ends else text[start:]


def tables(text):
    """Every Markdown table in text, as lists of rows of cells, the header row first."""
    found, rows = [], []
    for line in text.splitlines() + [""]:
        if line.startswith("|"):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif rows:
            found.append([rows[0]] + rows[2:])
            rows = []
    return found


def ticked(cell):
    return re.findall(r"`([^`]+)`", cell)


def ids(cell):
    # A Korean particle follows an ID without a space, so `\b` cannot end it.
    return re.findall(r"(?<![A-Za-z0-9-])[A-Z]+-\d{3}(?![0-9])", cell)


def listed(cell):
    """The IDs of a cell that holds IDs separated by commas, or `none`."""
    return [] if cell == "none" else [item.strip() for item in cell.split(",")]


def criteria_counts():
    """{SPEC: the number of its acceptance criteria}, from the functional spec."""
    counts = {}
    for rows in tables(read_text(DOCS / "04-functional-spec" / "memory.md")):
        if rows[0][:2] == ["ID", "Behaviour"]:
            column = rows[0].index("Acceptance criteria")
            for row in rows[1:]:
                counts[row[0]] = len(re.findall(r"(?:^|\. )Given ", row[column]))
    return counts


def claimed(text, counts):
    """[(SPEC, [numbers of its acceptance criteria])] in the order that text names them."""
    found = []
    for spec, words in CLAIM.findall(text):
        count = counts[spec]
        numbers = []
        for word in re.findall(r"(?:first|last) two|\w+", words):
            if word == "first two":
                numbers += [1, 2]
            elif word == "last two":
                numbers += [count - 1, count]
            elif word != "and":
                numbers.append(ORDINALS.index(word) + 1)
        found.append((spec, numbers or list(range(1, count + 1))))
    return found


def tested_by(cell):
    """[(task, codes, or None for all of the row)] of a Tested by cell."""
    found = []
    for part in cell.split("; "):
        match = re.fullmatch(r"(TASK-\d{3})(?: \((`[^`]+`(?:, `[^`]+`)*)\))?", part)
        if not match:
            raise AssertionError("cannot read %r" % part)
        found.append((match.group(1), ticked(match.group(2)) if match.group(2) else None))
    return found


class WorkBreakdownTest(unittest.TestCase):
    def setUp(self):
        self.doc = read_text(DOC)
        self.steps = {}
        for step in STEPS:
            (rows,) = tables(section(self.doc, "## %s: " % step))
            self.steps[step] = rows
        self.tasks = {}
        for step in STEPS:
            for row in self.steps[step][1:]:
                self.assertNotIn(row[0], self.tasks)
                self.tasks[row[0]] = dict(zip(COLUMNS, row), step=step)
        self.current = {key: task for key, task in self.tasks.items() if not task["Status"].startswith("removed")}

    def test_each_step_has_the_task_table(self):
        for step in STEPS:
            with self.subTest(step=step):
                header, rows = self.steps[step][0], self.steps[step][1:]
                self.assertEqual(header, COLUMNS)
                self.assertTrue(rows)
                self.assertTrue(all(len(row) == len(COLUMNS) for row in rows))
                self.assertEqual([row[0] for row in rows], sorted(row[0] for row in rows))
        # Tasks are never renumbered or deleted, so their numbers have no gap.
        self.assertEqual(sorted(self.tasks), ["TASK-%03d" % n for n in range(1, len(self.tasks) + 1)])

    def test_every_behaviour_has_tasks(self):
        specs = re.findall(r"^\| (SPEC-\d{3}) \|", read_text(DOCS / "04-functional-spec" / "memory.md"), re.M)
        for key, task in self.tasks.items():
            with self.subTest(task=key):
                self.assertTrue(listed(task["From"]))
                self.assertLessEqual(set(listed(task["From"])), set(specs))
        built = {spec for task in self.current.values() for spec in listed(task["From"])}
        self.assertEqual(built, set(specs))

    def test_every_interface_and_record_is_touched(self):
        interfaces = [row[0] for row in tables(section(read_text(API / "memory.md"), "## Interfaces"))[0][1:]]
        records = re.findall(r"^\| (TBL-\d{3}) \|", read_text(DOCS / "05-erd" / "memory.md"), re.M)
        for key, task in self.tasks.items():
            with self.subTest(task=key):
                self.assertLessEqual(set(listed(task["Touches"])), set(interfaces + records))
        touched = {item for task in self.current.values() for item in listed(task["Touches"])}
        self.assertEqual(touched, set(interfaces + records))

    def test_dependencies(self):
        for key, task in self.tasks.items():
            with self.subTest(task=key):
                for other in listed(task["Depends on"]):
                    self.assertIn(other, self.tasks)
                    self.assertNotEqual(other, key)
                    self.assertLessEqual(STEPS.index(self.tasks[other]["step"]), STEPS.index(task["step"]), other + " is of a later step")
                    if key in self.current:
                        self.assertIn(other, self.current, other + " is removed")
        state = {}

        def visit(key, path):
            if state.get(key) == "done":
                return
            self.assertNotEqual(state.get(key), "open", "a cycle: " + " -> ".join(path + [key]))
            state[key] = "open"
            for other in listed(self.tasks[key]["Depends on"]):
                visit(other, path + [key])
            state[key] = "done"

        for key in self.tasks:
            visit(key, [])

    def test_owner_estimate_done_when_and_status(self):
        for key, task in self.tasks.items():
            with self.subTest(task=key):
                self.assertIn(task["Owner"], ("agent", "maintainer"))
                self.assertIn(task["Estimate"], ("S", "M", "L"))
                self.assertTrue(task["Task"] and task["Done when"].endswith("."))
                self.assertRegex(task["Status"], "^(%s)$" % STATUS.pattern)

    def test_a_task_that_touches_an_interface_tests_its_outcomes(self):
        for key, task in self.tasks.items():
            with self.subTest(task=key):
                touches = any(item.startswith("API-") for item in listed(task["Touches"]))
                self.assertEqual(TESTED in task["Done when"], touches)

    def test_every_acceptance_criterion_is_named(self):
        criteria = criteria_counts()
        self.assertEqual(len(criteria), 39)
        named = {spec: set() for spec in criteria}
        for key, task in self.current.items():
            with self.subTest(task=key):
                text = task["Done when"]
                claims = claimed(text, criteria)
                self.assertEqual([spec for spec, _ in claims], re.findall(r"SPEC-\d{3}", text), "name a behaviour as SPEC-NNN's")
                for spec, numbers in claims:
                    self.assertIn(spec, listed(task["From"]))
                    self.assertTrue(all(1 <= number <= criteria[spec] for number in numbers), spec)
                    named[spec] |= set(numbers)
        for spec, count in criteria.items():
            with self.subTest(spec=spec):
                self.assertEqual(named[spec], set(range(1, count + 1)))

    def test_decisions_name_existing_tasks(self):
        (rows,) = tables(section(self.doc, "## Decisions the tasks wait for"))
        for row in rows[1:]:
            with self.subTest(decision=row[0]):
                self.assertTrue(row[1] == "All of them" or ids(row[1]))
                self.assertLessEqual(set(re.findall(r"TASK-\d{3}", row[1])), set(self.current))


class OutcomesTest(unittest.TestCase):
    """The table of outcomes follows stage 06, and each task that builds an interface tests its part."""

    def setUp(self):
        doc = read_text(DOC)
        self.api = read_text(API / "memory.md")
        (rows,) = tables(section(doc, "## Outcomes"))
        self.assertEqual(rows[0], ["Interface", "Outcomes", "Tested by"])
        self.rows = {row[0]: (ticked(row[1]), row[2]) for row in rows[1:]}
        self.order = [row[0] for row in rows[1:]]
        self.interfaces = {row[0]: row for row in tables(section(self.api, "## Interfaces"))[0][1:]}
        self.tasks = {}
        for step in STEPS:
            (task_rows,) = tables(section(doc, "## %s: " % step))
            self.tasks.update((row[0], dict(zip(COLUMNS, row))) for row in task_rows[1:])
        errors = section(self.api, "## Error codes")
        self.failures = [ticked(row[0])[0] for row in tables(section(errors, "### Hooks and the memory worker"))[0][1:]]
        model = tables(section(errors, "### Model calls"))[0][1:]
        self.model = [code for row in model for code in (ticked(row[2]) if not ticked(row[0]) else ticked(row[0]))]
        self.sync = [ticked(row[0])[0] for row in tables(section(errors, "### Sync"))[0][1:]]
        self.commands = [ticked(row[0])[0] for row in tables(section(errors, "### Command results"))[0][1:]]
        self.timings = ticked(section(errors, "### Hook timings").split(":", 1)[1])

    def of_kind(self, kind):
        return [key for key, row in self.interfaces.items() if row[2] == kind]

    def test_every_interface_has_a_row(self):
        self.assertEqual(self.order, list(self.interfaces) + SHARED)
        known = {"ok"} | set(self.failures + self.model + self.sync + self.commands + self.timings)
        for key, (codes, _) in self.rows.items():
            with self.subTest(row=key):
                self.assertTrue(codes)
                self.assertEqual(len(codes), len(set(codes)))
                self.assertLessEqual(set(codes), known)

    def test_hooks_have_their_sections_outcomes(self):
        self.assertLessEqual(set(HOOK_INPUT), set(self.failures))
        for key in self.of_kind("hook"):
            with self.subTest(interface=key):
                text = section(self.api, "### %s (%s)" % (self.interfaces[key][1], key))
                (line,) = [line for line in text.splitlines() if line.startswith("Outcomes: ")]
                self.assertEqual(self.rows[key][0], ticked(line.split(". ")[0]) + HOOK_INPUT)

    def test_commands_have_their_results_codes(self):
        schema = load_json(API / "memory-result.schema.json")["$defs"]
        branches = {}
        for branch in schema["data-of-each-command"]["else"]["anyOf"]:
            code = branch["properties"]["code"]
            branches[branch["properties"]["command"]["const"]] = code["enum"] if "enum" in code else [code["const"]]
        for key in self.of_kind("command"):
            with self.subTest(interface=key):
                codes = branches[ticked(self.interfaces[key][1])[0]]
                self.assertEqual(self.rows[key][0], ["ok"] + [code for code in codes if code != "ok"])
        self.assertEqual(self.rows["Every command"][0], schema["any-command-codes"]["enum"])
        branch_codes = {code for key in self.of_kind("command") for code in self.rows[key][0]}
        self.assertEqual(branch_codes | set(self.rows["Every command"][0]), {"ok"} | set(self.commands))

    def test_model_calls_have_their_outcomes(self):
        answers = re.findall(r"^#### .+ answers \((API-\d{3})\)$", self.api, re.M)
        outcomes = [ticked(row[1])[0] for row in tables(section(self.api, "#### Outcomes of an answer"))[0][1:]]
        embeddings = ids(re.search(r"^### Embeddings \((.+)\)$", self.api, re.M).group(1))
        for key in self.of_kind("model call"):
            with self.subTest(interface=key):
                expected = outcomes if key in answers else ["ok", "bad-vector"] if key in embeddings else ["ok"]
                self.assertEqual(self.rows[key][0], expected)
        # The codes that no single call has are those that every model call can have.
        own = {code for key in self.of_kind("model call") + self.of_kind("background process") for code in self.rows[key][0]}
        self.assertEqual(set(self.rows["Every model call"][0]), set(self.model) - own)

    def test_git_and_the_failure_log_have_their_codes(self):
        git = [code for key in self.of_kind("Git") for code in self.rows[key][0] if code != "ok"]
        self.assertEqual(set(git), set(self.sync))
        self.assertEqual(self.rows[SHARED[2]][0], self.failures)
        for key in self.of_kind("background process"):
            self.assertLessEqual(set(self.rows[key][0]), {"ok"} | set(self.failures + self.model))

    def test_tested_by_covers_each_row(self):
        for key, (codes, cell) in self.rows.items():
            with self.subTest(row=key):
                parts = tested_by(cell)
                names = [task for task, _ in parts]
                self.assertEqual(len(names), len(set(names)))
                covered = set()
                for task, some in parts:
                    self.assertIn(task, self.tasks)
                    if some is not None:
                        self.assertTrue(set(some) < set(codes), task)
                    covered |= set(codes if some is None else some)
                self.assertEqual(covered, set(codes))
                if key in self.interfaces:
                    touching = {task for task, row in self.tasks.items() if key in listed(row["Touches"]) and not row["Status"].startswith("removed")}
                    self.assertEqual(set(names), touching)


class TranslationTest(unittest.TestCase):
    def test_the_translation_keeps_every_table(self):
        source, translation = tables(read_text(DOC)), tables(read_text(TRANSLATION))
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
                        for column in ("ID", "Owner", "Estimate", "Status"):
                            index = COLUMNS.index(column)
                            self.assertEqual(other[index], row[index], column)


if __name__ == "__main__":
    unittest.main()
