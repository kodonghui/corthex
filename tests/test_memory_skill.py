"""TC-098: compare the C1 operator guide with real command/result contracts."""
import json
from pathlib import Path
import re
import sys
import unittest

from _common import ROOT

SKILL = ROOT / "plugins/corthex-memory/skills/corthex-memory/SKILL.md"
sys.path.insert(0, str(SKILL.parent / "scripts"))
from memory_lib import commands

C1 = {"on", "off", "status", "leave-out", "retention", "purge", "repair"}


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
            codes = {code for code, (allowed, _) in commands.COMMON.items() if name in allowed}
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


if __name__ == "__main__":
    unittest.main()
