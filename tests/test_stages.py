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
# Sticky colours a Miro board accepts by name.
MIRO_COLOURS = {
    "black", "blue", "cyan", "dark_blue", "dark_green", "gray", "green", "light_blue",
    "light_green", "light_pink", "light_yellow", "orange", "pink", "red", "violet", "yellow",
}
LEGEND = [
    "Domain event", "External system", "Command", "Hotspot",
    "Actor", "Aggregate", "Policy", "Read model",
]


def section(text, heading):
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


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

    def test_event_storming_legend(self):
        board = read_text(SKILLS / "corthex-discover" / "references" / "event-storming-board.md")
        rows = [line.split("|")[1:-1] for line in section(board, "## Legend").splitlines() if line.startswith("| ")]
        colours = {row[0].strip(): row[2].strip().strip("`") for row in rows[2:]}
        self.assertEqual(list(colours), LEGEND)
        for element, colour in colours.items():
            with self.subTest(element=element):
                self.assertIn(colour, MIRO_COLOURS)
        # One colour per kind, so the kind of a sticky can be read from its colour.
        self.assertEqual(len(set(colours.values())), len(colours))

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


if __name__ == "__main__":
    unittest.main()
