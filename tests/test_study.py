"""Checks that the corthex-study skill keeps its rules for keys, records, standard terms and claim tags."""

import unittest

from _common import PLUGINS, read_text

SKILLS = PLUGINS / "corthex" / "skills"
SKILL = SKILLS / "corthex-study"
REFERENCES = ("structure", "writing", "experiments", "publish")
TAGS = (("fact", "사실"), ("interpretation", "해석"), ("run", "실행"), ("assumption", "가정"))


class StudySkillTest(unittest.TestCase):
    def test_skill_links_every_reference(self):
        body = read_text(SKILL / "SKILL.md")
        for name in REFERENCES:
            with self.subTest(reference=name):
                self.assertIn("(references/%s.md" % name, body)

    def test_experiments_keep_keys_out_of_sight(self):
        text = read_text(SKILL / "references" / "experiments.md")
        self.assertIn("Never print a key", text)
        self.assertIn("delete it at the end", text)
        self.assertIn("revoke it and issue a new one", text)
        self.assertIn("permission for paid calls", text)

    def test_records_follow_the_profile_and_reuse_the_row(self):
        self.assertIn("`records.study`", read_text(SKILL / "SKILL.md"))
        self.assertIn("`records.study`", read_text(SKILLS / "corthex" / "references" / "profile.md"))
        publish = read_text(SKILL / "references" / "publish.md")
        self.assertIn("reuse the row for the same question", publish)
        self.assertIn("uncheck read", publish)
        self.assertIn('<meta charset="utf-8">', publish)

    def test_titles_and_terms_keep_standard_terms(self):
        writing = read_text(SKILL / "references" / "writing.md")
        self.assertIn("Never replace a standard term with a coined native word or a metaphor", writing)
        self.assertIn("Pure Korean (순한국말) is not the goal", writing)
        structure = read_text(SKILL / "references" / "structure.md")
        self.assertIn("it is not a slogan, a metaphor or a coined word", structure)
        self.assertIn("never rename them with coined words or metaphors", read_text(SKILL / "SKILL.md"))

    def test_claim_tags_are_listed_in_english_and_korean(self):
        text = read_text(SKILL / "references" / "writing.md")
        for english, korean in TAGS:
            with self.subTest(tag=english):
                self.assertIn("`[%s]`" % english, text)
                self.assertIn("`[%s]`" % korean, text)


if __name__ == "__main__":
    unittest.main()
