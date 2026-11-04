"""TC-099: a consistent C1 package and current public recording documentation."""
import json
from pathlib import Path
import unittest

from _common import ROOT, load_json, read_text, split_frontmatter

PLUGIN = ROOT / "plugins/corthex-memory"
COMPAT = "session_start.py"


class MemoryReleaseTest(unittest.TestCase):
    def test_tc099_memory_versions_and_capture_description_agree(self):
        manifests = [load_json(PLUGIN / name / "plugin.json") for name in (".claude-plugin", ".codex-plugin")]
        self.assertEqual([m["version"] for m in manifests], ["0.2.1", "0.2.1"])
        fields, _ = split_frontmatter(read_text(PLUGIN / "skills/corthex-memory/SKILL.md"))
        self.assertEqual(fields["metadata"]["version"], "0.2.1")
        for manifest in manifests:
            description = manifest["description"].lower()
            for word in ("record", "prompt", "answer", "enabled", "c1"):
                self.assertIn(word, description)
        self.assertEqual(manifests[0]["description"], manifests[1]["description"])

    def test_current_entrypoints_and_runtime_docs_do_not_use_the_removed_entry(self):
        self.assertFalse((PLUGIN / "scripts" / COMPAT).exists())
        for path in PLUGIN.rglob("*"):
            if path.is_file() and path.suffix in (".py", ".json", ".md"):
                self.assertNotIn(COMPAT, read_text(path), str(path.relative_to(ROOT)))
        for name in ("README.md", "README.ko.md", "docs/architecture.md", "docs/architecture.ko.md", "docs/06-api/memory.md", "docs/06-api/memory.ko.md"):
            self.assertNotIn(COMPAT, read_text(ROOT / name), name)
        hooks = load_json(PLUGIN / "hooks/hooks.json")["hooks"]
        self.assertEqual(set(hooks), {"SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"})

    def test_readmes_state_recording_location_consent_and_c1_boundary(self):
        for name, words in (("README.md", ("consent", "100 days", "C2")),
                            ("README.ko.md", ("동의", "100일", "C2"))):
            text = read_text(ROOT / name)
            for word in ("0.2.1", "~/.corthex/corthex-memory/", "CORTHEX_MEMORY_HOME", "C1") + words:
                self.assertIn(word, text, name)
        for name in (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json"):
            catalogue = load_json(ROOT / name)
            entry = next(e for e in catalogue["plugins"] if e["name"] == "corthex-memory")
            self.assertNotIn("version", entry)  # The source plugin manifest owns the version.
            path = entry["source"] if isinstance(entry["source"], str) else entry["source"]["path"]
            self.assertEqual((ROOT / path).resolve(), PLUGIN.resolve())


if __name__ == "__main__":
    unittest.main()
