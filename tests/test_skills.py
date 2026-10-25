"""Checks that every skill follows the Agent Skills format and stays portable."""

import unittest

from _common import KEBAB, PLUGINS, SKILL_KEYS, load_json, local_links, read_text, skill_files, split_frontmatter

CORE_SKILLS = {
    "corthex", "corthex-discover", "corthex-define", "corthex-contract",
    "corthex-screen", "corthex-build", "corthex-present", "corthex-record", "corthex-uxui",
}
MAX_DESCRIPTION = 1024
MAX_BODY_LINES = 500


class SkillFormatTest(unittest.TestCase):
    def test_core_skill_set(self):
        names = {path.parent.name for path in (PLUGINS / "corthex" / "skills").glob("*/SKILL.md")}
        self.assertEqual(names, CORE_SKILLS)

    def test_frontmatter(self):
        for path in skill_files():
            plugin = path.parents[2]
            manifest = load_json(plugin / ".claude-plugin" / "plugin.json")
            with self.subTest(skill=path.parent.name):
                fields, body = split_frontmatter(read_text(path))
                self.assertLessEqual(set(fields), SKILL_KEYS)
                name = fields["name"]
                self.assertEqual(name, path.parent.name)
                self.assertRegex(name, KEBAB)
                self.assertLessEqual(len(name), 64)
                description = fields["description"]
                self.assertTrue(description.strip())
                self.assertLessEqual(len(description), MAX_DESCRIPTION)
                self.assertEqual(fields.get("license"), manifest["license"])
                self.assertEqual(fields["metadata"].get("version"), manifest["version"])
                self.assertEqual(fields["metadata"].get("author"), manifest["author"]["name"])
                self.assertLessEqual(len(body.splitlines()), MAX_BODY_LINES)

    def test_frontmatter_quotes_what_yaml_reads_differently(self):
        for value in ("a: b", "ends:", "a #b", "[a]", "- a", "*a", "1.0", "true", "null"):
            for line in ("description: %s\n", "metadata:\n  version: %s\n"):
                with self.subTest(value=value, line=line):
                    with self.assertRaises(ValueError):
                        split_frontmatter("---\n" + line % value + "---\n")
        fields, _ = split_frontmatter(
            '---\ndescription: "a: b"\nlicense: a:b, http://x.y\nmetadata:\n  version: "1.0"\n---\n'
        )
        self.assertEqual(fields["description"], "a: b")
        self.assertEqual(fields["license"], "a:b, http://x.y")
        self.assertEqual(fields["metadata"]["version"], "1.0")

    def test_names_are_unique(self):
        names = [path.parent.name for path in skill_files()]
        self.assertEqual(len(names), len(set(names)))

    def test_links_stay_inside_the_skill(self):
        for path in skill_files():
            skill = path.parent
            for doc in [path] + sorted(skill.glob("references/*.md")):
                for target in local_links(read_text(doc)):
                    with self.subTest(doc=str(doc.relative_to(PLUGINS)), target=target):
                        resolved = (doc.parent / target).resolve()
                        self.assertTrue(resolved.exists(), "broken link")
                        self.assertTrue(str(resolved).startswith(str(skill.resolve())), "link leaves the skill")


if __name__ == "__main__":
    unittest.main()
