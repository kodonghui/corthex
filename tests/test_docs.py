"""Checks the public docs: links resolve, and every page has its translation."""

import unittest

from _common import ROOT, local_links, read_text

TRANSLATION = ".ko.md"
# Instructions for coding agents, written in English only.
AGENT_FILES = {"AGENTS.md", "CLAUDE.md"}


def doc_files():
    return sorted(ROOT.glob("*.md")) + sorted((ROOT / "docs").rglob("*.md"))


class DocsTest(unittest.TestCase):
    def test_links_resolve_inside_the_repository(self):
        for doc in doc_files():
            for target in local_links(read_text(doc)):
                with self.subTest(doc=str(doc.relative_to(ROOT)), target=target):
                    resolved = (doc.parent / target).resolve()
                    self.assertTrue(resolved.exists(), "broken link")
                    self.assertTrue(str(resolved).startswith(str(ROOT)), "link leaves the repository")

    def test_every_page_has_english_and_korean(self):
        for doc in doc_files():
            name = doc.name
            if name in AGENT_FILES:
                continue
            pair = name[: -len(TRANSLATION)] + ".md" if name.endswith(TRANSLATION) else name[:-3] + TRANSLATION
            with self.subTest(doc=str(doc.relative_to(ROOT))):
                self.assertTrue((doc.parent / pair).exists(), "missing " + pair)


if __name__ == "__main__":
    unittest.main()
