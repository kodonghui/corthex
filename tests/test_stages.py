"""Checks the 13-stage contract: every stage has the six slots and a home skill."""

import json
import re
import unittest

from _common import KEBAB, PLUGINS, read_text

SKILLS = PLUGINS / "corthex" / "skills"
STAGES = [
    ("01-domain", "corthex-discover"),
    ("02-prd", "corthex-define"),
    ("03-user-flow", "corthex-define"),
    ("04-functional-spec", "corthex-define"),
    ("05-erd", "corthex-contract"),
    ("06-api", "corthex-contract"),
    ("07-sitemap", "corthex-screen"),
    ("08-screen-states", "corthex-screen"),
    ("09-mockup", "corthex-screen"),
    ("10-wbs", "corthex-build"),
    ("11-development", "corthex-build"),
    ("12-qa", "corthex-build"),
    ("13-presentation", "corthex-present"),
]
SLOTS = ["Inputs", "Outputs", "Human view", "Sync", "Human checkpoints", "Trace IDs"]
STAGE_SKILLS = sorted({skill for _, skill in STAGES})
TRUTH = {"source", "human"}
ID_KINDS = [
    "context", "term", "requirement", "flow", "spec", "table", "api",
    "screen", "task", "test", "bug", "decision", "scene",
]
PROJECT_FIELDS = {"name", "title", "team", "language", "records", "repos", "ids", "stages"}
STAGE_FIELDS = {"human", "link", "source", "truth", "note", "skip"}
PREFIX = re.compile(r"^[A-Z][A-Z0-9]*$")


def section(text, heading):
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


def table(text):
    """The body rows of the first Markdown table in text, as lists of cells."""
    lines = [line for line in text.splitlines() if line.startswith("|")]
    return [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines[2:]]


def codes(cell):
    return re.findall(r"\b[0-9]{3}\b|default", cell)


def yaml_children(lines, parent):
    """{key: lines} one level under the first `parent:` line of a YAML block."""
    start = next(i for i, line in enumerate(lines) if line.strip() == parent + ":")
    indent = len(lines[start]) - len(lines[start].lstrip())
    children, key = {}, None
    for line in lines[start + 1:]:
        depth = len(line) - len(line.lstrip())
        if line.strip() and depth <= indent:
            break
        if depth == indent + 2:
            key, _, value = line.strip().partition(":")
            key = key.strip('"')
            children[key] = [value.strip()] if value.strip() else []
        elif key and line.strip():
            children[key].append(line.strip())
    return children


class StageContractTest(unittest.TestCase):
    def test_every_stage_fills_six_slots(self):
        for key, skill in STAGES:
            with self.subTest(stage=key):
                text = read_text(SKILLS / skill / "references" / (key + ".md"))
                for slot in SLOTS:
                    rows = [line for line in text.splitlines() if line.startswith("| %s |" % slot)]
                    self.assertEqual(len(rows), 1, slot)
                    self.assertTrue(rows[0].split("|")[2].strip(), slot + " is empty")

    def test_stage_skills_link_their_stages(self):
        for key, skill in STAGES:
            with self.subTest(stage=key):
                self.assertIn("references/%s.md" % key, read_text(SKILLS / skill / "SKILL.md"))

    def test_stage_skills_share_one_procedure(self):
        blocks = {skill: section(read_text(SKILLS / skill / "SKILL.md"), "## How a stage runs") for skill in STAGE_SKILLS}
        first = blocks[STAGE_SKILLS[0]]
        for skill, block in blocks.items():
            with self.subTest(skill=skill):
                self.assertEqual(block, first)

    def test_unreachable_human_views_keep_their_rules(self):
        contract = section(read_text(SKILLS / "corthex" / "references" / "stage-contract.md"), "## Human views the AI cannot reach")
        texts = {"stage-contract.md": contract}
        for skill in STAGE_SKILLS:
            steps = section(read_text(SKILLS / skill / "SKILL.md"), "## How a stage runs")
            texts[skill] = next(line for line in steps.splitlines() if line.startswith("5. **Sync.**"))
        rules = [
            "new export at the start", "before each", "date of the copy you used",
            "`truth: human`", "as proposed, not as done",
            "`truth: source`", "done once it is in the source", "not yet updated until a newer export shows the change",
        ]
        for name, text in texts.items():
            with self.subTest(text=name):
                for rule in rules:
                    self.assertIn(rule, text)
                # Changes stay proposed only where the human view is the truth.
                at = [text.index(rule) for rule in rules[3:]]
                self.assertEqual(at, sorted(at))

    def test_entry_skill_routes_every_stage(self):
        entry = read_text(SKILLS / "corthex" / "SKILL.md")
        for skill in STAGE_SKILLS + ["corthex-record"]:
            self.assertIn("`%s`" % skill, entry)

    def test_contract_lists_every_stage(self):
        contract = read_text(SKILLS / "corthex" / "references" / "stage-contract.md")
        for key, skill in STAGES:
            with self.subTest(stage=key):
                row = next(line for line in contract.splitlines() if line.startswith("| `%s` |" % key))
                self.assertIn("`%s`" % skill, row)

    def test_id_kinds_are_documented(self):
        for doc in ("stage-contract.md", "project.md"):
            text = read_text(SKILLS / "corthex" / "references" / doc)
            for kind in ID_KINDS:
                with self.subTest(doc=doc, kind=kind):
                    self.assertIn("`%s`" % kind, text)

    def test_project_example(self):
        with open(SKILLS / "corthex" / "assets" / "project.example.json", encoding="utf-8") as handle:
            project = json.load(handle)
        self.assertLessEqual(set(project), PROJECT_FIELDS)
        self.assertRegex(project["name"], KEBAB)
        repos = project.get("repos", {})
        for alias, location in repos.items():
            self.assertRegex(alias, KEBAB)
            self.assertTrue(location)
        for kind, value in project.get("ids", {}).items():
            with self.subTest(ids=kind):
                self.assertIn(kind, ID_KINDS)
                if isinstance(value, str):
                    self.assertRegex(value, PREFIX)
                    continue
                prefixes = value["prefix"] if isinstance(value["prefix"], list) else [value["prefix"]]
                self.assertTrue(prefixes)
                for prefix in prefixes:
                    self.assertRegex(prefix, PREFIX)
                self.assertIn(value["digits"], range(1, 7))
        keys = {key for key, _ in STAGES}
        for key, stage in project["stages"].items():
            with self.subTest(stage=key):
                self.assertIn(key, keys)
                self.assertLessEqual(set(stage), STAGE_FIELDS)
                self.assertIn(stage["truth"], TRUTH)
                self.assertTrue(stage["human"])
                source = stage.get("source")
                if source is None:
                    continue
                self.assertTrue(source)
                self.assertNotIn("\\", source)
                alias, sep, path = source.rpartition(":")
                if sep:
                    self.assertIn(alias, repos)
                self.assertFalse(path.startswith("/"), "source paths are relative")

    def test_profile_example(self):
        with open(SKILLS / "corthex" / "assets" / "profile.example.json", encoding="utf-8") as handle:
            profile = json.load(handle)
        for key in ("address_as", "language", "records", "ask_before"):
            self.assertIn(key, profile)
        self.assertIsInstance(profile["ask_before"], list)


class ContractFirstTest(unittest.TestCase):
    """The back end, the front end and QA work from the responses in the API contract."""

    def reference(self, key):
        return read_text(SKILLS / dict(STAGES)[key] / "references" / (key + ".md"))

    def responses(self):
        return table(section(self.reference("06-api"), "## Responses"))

    def template(self):
        text = self.reference("06-api")
        block = text[text.index("```yaml", text.index("## Output template")):]
        return block[:block.index("\n```\n")].splitlines()

    def test_the_api_template_accounts_for_each_response(self):
        lines = self.template()
        listed = yaml_children(lines, "responses")
        omitted = yaml_children(lines, "omit")
        self.assertFalse(set(listed) & set(omitted))
        for row in self.responses():
            with self.subTest(response=row[0]):
                self.assertTrue(set(codes(row[0])) & (set(listed) | set(omitted)), "listed or omitted")
        for code, body in listed.items():
            with self.subTest(listed=code):
                self.assertIn("examples:", body)
        for code, reason in omitted.items():
            with self.subTest(omitted=code):
                self.assertTrue(reason, "an omitted response gives its reason")
        self.assertIn("401", listed, "the operation needs a signed-in caller")

    def test_the_api_template_lists_its_error_codes(self):
        lines = self.template()
        errors = {code: int(re.search(r"status: ([0-9]{3})", value[0]).group(1)) for code, value in yaml_children(lines, "errors").items()}
        enum = next(line for line in lines if line.strip().startswith("code: {type: string, enum:"))
        self.assertEqual(re.search(r"\[(.*)\]", enum).group(1).split(", "), list(errors), "the code member allows only the listed codes")
        for response, body in yaml_children(lines, "responses").items():
            if response.startswith("2"):
                continue
            with self.subTest(response=response):
                self.assertIn("application/problem+json:", body)
                examples = [re.search(r"status: ([0-9]{3}), code: (\w+)", line) for line in body if line.startswith("value:")]
                self.assertTrue(examples and all(examples))
                for example in examples:
                    status, code = int(example.group(1)), example.group(2)
                    self.assertEqual(errors.get(code), status, "the example's code is listed with its status")
                    if response == "default":
                        self.assertNotIn(str(status), yaml_children(lines, "responses"))
                    else:
                        self.assertEqual(status, int(response))

    def test_every_response_leads_to_a_screen_state(self):
        text = self.reference("08-screen-states")
        states = {row[0] for row in table(section(text, "## States"))}
        mapping = table(section(text, "## Responses and states"))
        self.assertLessEqual({row[1] for row in mapping}, states)
        self.assertLessEqual({"normal", "empty"}, {row[1] for row in mapping})
        mapped = {code for row in mapping for code in codes(row[0])}
        for row in self.responses()[1:]:
            with self.subTest(response=row[0]):
                self.assertLessEqual(set(codes(row[0])), mapped)

    def test_qa_has_a_case_for_each_response_and_state(self):
        text = self.reference("12-qa")
        self.assertIn("Every response in the API contract and every applicable screen state has a test case.", section(text, "## Checks"))
        template = text[text.index("## Output template"):]
        self.assertRegex(template, r"\bAPI-[0-9]{3}#[0-9]{3}\b")
        self.assertRegex(template, r"\bSCR-[0-9]{3}#[a-z]+\b")

    def test_development_reports_provided_and_accepted_apart(self):
        checks = section(self.reference("11-development"), "## Checks")
        self.assertIn("contract tests pass", checks)
        self.assertIn("provided, when the back end passes its contract tests", checks)
        self.assertIn("accepted, when the front end works against the real server", checks)

    def test_tests_never_run_against_production(self):
        for key in ("06-api", "11-development", "12-qa"):
            with self.subTest(stage=key):
                self.assertRegex(self.reference(key), r"development or staging server[^.]*, never (on )?production")


if __name__ == "__main__":
    unittest.main()
