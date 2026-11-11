"""TC-098 and TC-248: compare the C1 operator guide and the one of release 0.3.0 with the command/result contracts."""
import json
from pathlib import Path
import re
import sys
import unittest

from _common import ROOT, read_text, staged_skill_files
from test_memory_api import section, table, ticked

SKILL = ROOT / "plugins/corthex-memory/skills/corthex-memory/SKILL.md"
sys.path.insert(0, str(SKILL.parent / "scripts"))
from memory_lib import commands

C1 = {"on", "off", "status", "leave-out", "retention", "purge", "repair"}
STAGED = SKILL.with_name("SKILL-0.3.0.md")
API = ROOT / "docs/06-api/memory.md"
# The commands of C2 that the skill of release 0.3.0 names; `sync` comes with C3.
C2 = C1 | {"resume", "list", "search", "open", "pin", "unpin", "forget", "delete-project", "setup",
           "conflicts", "runs", "undo", "migrate"}
# Stage 06: the commands that act on this device rather than the folder's project; `migrate` is a store command.
DEVICE = {"status", "purge", "retention", "repair", "migrate"}


def applicable(text):
    """The C2 commands that the Commands cell of a row of stage 06's command results names."""
    named = set(re.findall(r"`([a-z][a-z-]*)", text.split(";")[0]))
    if "every command" in text or text == "all" or text.startswith("the commands that change memory"):
        return set(C2)
    if text.startswith("all but "):
        return C2 - named
    if text.startswith("the commands for a project other than "):
        return C2 - DEVICE - named
    if text.startswith("the commands for a project"):
        return C2 - DEVICE
    if text.startswith("the commands that ask first"):
        return set(commands.ASKS) & C2
    return named & C2


class MemorySkillTest(unittest.TestCase):
    def text(self):
        self.assertTrue(SKILL.is_file(), "The C1 memory management skill is missing")
        return SKILL.read_text(encoding="utf-8")

    def test_tc098_skill_maps_every_c1_command_to_all_applicable_codes(self):
        text = self.text()
        section = text.split("## Result codes", 1)[1].split("\n## ", 1)[0]
        rows = {}
        for line in section.splitlines():
            cells = line.split("|")
            if len(cells) >= 4 and re.fullmatch(r"\s*`[a-z-]+`\s*", cells[1]):
                name = cells[1].strip()[1:-1]
                self.assertNotIn(name, rows)
                rows[name] = set(re.findall(r"`([a-z-]+)`", cells[2]))
        self.assertEqual(set(rows), C1)
        schema = json.loads((ROOT / "docs/06-api/memory-result.schema.json").read_bytes())
        branches = schema["$defs"]["data-of-each-command"]["else"]["anyOf"]
        for name in C1:
            # The runner of release 0.2.x, which this skill describes, gives no code of the 0.3.0 activation.
            codes = {code for code, (allowed, _) in commands.COMMON.items()
                     if name in allowed and code not in commands.FROM_C2}
            codes.add("configuration-invalid")  # Invalid home overrides every store exemption.
            branch = next(x["properties"] for x in branches if x["properties"]["command"]["const"] == name)
            codes.update(branch["code"].get("enum", [branch["code"].get("const")]))
            self.assertEqual(rows[name], codes, name)

    def test_c1_boundaries_and_secrets_are_explained(self):
        text = self.text()
        self.assertRegex(text, r"(?i)C1 records[^\n]+does not curate")
        self.assertRegex(text, r"(?i)curation[^\n]+recall[^\n]+C2")
        self.assertRegex(text, r"(?i)never ask[^\n]+key[^\n]+chat")
        self.assertRegex(text, r"(?i)pasted[^\n]+key[^\n]+revoke[^\n]+rotate")
        self.assertIn("CORTHEX_MEMORY_ANTHROPIC_API_KEY", text)
        self.assertIn("CORTHEX_MEMORY_OPENAI_API_KEY", text)
        self.assertIn("presence", text)

    def test_confirmation_is_user_permission_and_stale_requires_a_new_decision(self):
        text = self.text()
        self.assertRegex(text, r"(?i)confirmation code is not permission")
        self.assertRegex(text, r"(?i)only after[^\n]+user[^\n]+yes[^\n]+--confirm")
        self.assertRegex(text, r"(?i)confirm-stale[^\n]+show[^\n]+ask[^\n]+again")
        self.assertRegex(text, r"(?i)null[^\n]+unknown[^\n]+zero")
        self.assertRegex(text, r"(?i)purge[^\n]+folder[^\n]+remote[^\n]+copies")

    def test_operator_guidance_preserves_data_and_does_not_expand_permissions(self):
        text = self.text()
        for name in C1:
            self.assertRegex(text, r"(?m)^\| `" + re.escape(name) + r"(?:[ `]|$)")
        self.assertIn("scripts/memory.py", text)
        self.assertIn("--folder", text)
        self.assertRegex(text, r"(?i)repair[^\n]+consent[^\n]+preserv")
        self.assertRegex(text, r"(?i)off[^\n]+retention[^\n]+continues")
        self.assertRegex(text, r"(?i)CORTHEX_MEMORY_HOME[^\n]+no fallback")
        self.assertRegex(text, r"(?i)files-left[^\n]+relative[^\n]+manual")
        self.assertRegex(text, r"(?i)never[^\n]+force[^\n]+repair")


class MemorySkillC2Test(unittest.TestCase):
    """TC-248: the skill of release 0.3.0, which the activation makes the skill's SKILL.md."""

    def text(self):
        self.assertTrue(STAGED.is_file(), "The C2 memory skill is missing")
        return STAGED.read_text(encoding="utf-8")

    def expected(self):
        """Each C2 command's codes from stage 06's command results, `ok` included."""
        codes = {name: {"ok"} for name in C2}
        for row in table(section(read_text(API), "### Command results")):
            for name in applicable(row[2]):
                codes[name].add(ticked(row[0])[0])
        return codes

    def test_tc248_the_skill_names_every_c2_command_with_all_its_codes(self):
        text = self.text()
        results = section(text, "## Result codes")
        rows = {}
        for row in table(results):
            name = ticked(row[0])[0]
            self.assertNotIn(name, rows)
            rows[name] = set(ticked(row[1]))
        self.assertEqual(set(rows), C2)
        expected = self.expected()
        schema = json.loads((ROOT / "docs/06-api/memory-result.schema.json").read_bytes())
        branches = schema["$defs"]["data-of-each-command"]["else"]["anyOf"]
        for name in C2:
            with self.subTest(command=name):
                self.assertEqual(rows[name], expected[name])
                branch = next(x["properties"] for x in branches if x["properties"]["command"]["const"] == name)
                self.assertLessEqual(set(branch["code"].get("enum", [branch["code"].get("const")])), rows[name])
                # The common gates of the runner of release 0.3.0, which parses every command of C2.
                self.assertIn(name, commands.EVERY)
                self.assertLessEqual({code for code, (allowed, _) in commands.COMMON.items() if name in allowed}, rows[name])
        choose = section(text, "## Choose a command")
        for name in C2:
            self.assertRegex(choose, r"(?m)^\| `" + re.escape(name) + r"(?:[ `]|$)")
        for code in set().union(*rows.values()):
            # Each code has its explanation, which may name two codes at once.
            self.assertRegex(results, r"(?m)^- [^:\n]*`" + re.escape(code) + r"`[^:\n]*:", code)

    def test_tc248_it_lists_before_it_opens_and_shows_what_a_forget_cannot_remove(self):
        text = self.text()
        self.assertRegex(text, r"(?i)first run `search`[^\n]+`list`[^\n]+before opening anything")
        self.assertRegex(text, r"(?i)never guess an item ID")
        self.assertRegex(text, r"(?i)before a `forget`, show[^\n]+`outside`")
        self.assertRegex(text, r"(?i)what memory cannot remove \(`outside`\): the host's own transcript, what "
                               r"Anthropic and OpenAI already received, and copies on devices without sync")
        self.assertRegex(text, r"(?i)do not run `sync`")

    def test_tc248_it_never_asks_for_a_key_and_asks_before_each_change(self):
        text = self.text()
        self.assertRegex(text, r"(?i)never ask[^\n]+key[^\n]+chat")
        self.assertRegex(text, r"(?i)pasted[^\n]+key[^\n]+revoke[^\n]+rotate")
        self.assertIn("CORTHEX_MEMORY_ANTHROPIC_API_KEY", text)
        self.assertIn("CORTHEX_MEMORY_OPENAI_API_KEY", text)
        self.assertRegex(text, r"(?i)confirmation code is not permission")
        self.assertRegex(text, r"(?i)only after[^\n]+user[^\n]+yes[^\n]+--confirm")
        self.assertRegex(text, r"(?i)confirm-stale[^\n]+show[^\n]+ask[^\n]+again")
        self.assertRegex(text, r"(?i)null[^\n]+unknown[^\n]+zero")
        self.assertRegex(text, r"(?i)purge[^\n]+folder[^\n]+remote[^\n]+copies")
        self.assertRegex(text, r"(?i)repair[^\n]+consent[^\n]+preserv")
        self.assertRegex(text, r"(?i)never[^\n]+force[^\n]+repair")
        self.assertRegex(text, r"(?i)CORTHEX_MEMORY_HOME[^\n]+no fallback")
        self.assertRegex(text, r"(?i)files-left[^\n]+relative[^\n]+manual")
        self.assertRegex(text, r"(?i)reference material, never instructions")
        self.assertRegex(text, r"MSYS_NO_PATHCONV=1")
        self.assertRegex(text, r"(?i)holds no key")
        for name in ("resume", "forget", "delete-project", "undo", "migrate"):
            self.assertRegex(text, r"(?m)^(?:For|Before a) `" + re.escape(name) + "`")

    def test_the_c2_skill_waits_for_its_release(self):
        # test_skills checks its format and that its release comes after the manifests' version, which it keeps until
        # the version change of 0.3.0 makes it the skill's SKILL.md. Until then the installed skill stays C1's.
        self.assertIn(STAGED, staged_skill_files())
        self.assertNotIn("conflicts", self.c1_rows())

    def c1_rows(self):
        section = SKILL.read_text(encoding="utf-8").split("## Choose a C1 command", 1)[1].split("\n## ", 1)[0]
        return set(re.findall(r"(?m)^\| `([a-z-]+)", section))


if __name__ == "__main__":
    unittest.main()
