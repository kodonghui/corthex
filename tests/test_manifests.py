"""Checks for the marketplace files and the plugin manifests."""

import re
import unittest

from _common import KEBAB, PLUGINS, ROOT, load_json, plugin_dirs

AGENT_PLUGINS_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
AGENT_PLUGINS_KEYS = {
    "$schema", "name", "version", "description", "author", "homepage",
    "repository", "license", "keywords", "extensions",
}
AGENT_PLUGINS_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,62}[a-z0-9])?$")
MARKETPLACE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
CODEX_INSTALLATION = {"AVAILABLE", "INSTALLED_BY_DEFAULT", "NOT_AVAILABLE"}
SHARED_FIELDS = ("name", "version", "description", "author", "homepage", "repository", "license", "keywords")
LICENSE = "Apache-2.0"


def codex_manifest(plugin):
    """The manifest Codex reads: the root plugin.json, or .codex-plugin/plugin.json without one."""
    root = plugin / "plugin.json"
    return load_json(root if root.exists() else plugin / ".codex-plugin" / "plugin.json")


class MarketplaceTest(unittest.TestCase):
    def setUp(self):
        self.claude = load_json(ROOT / ".claude-plugin" / "marketplace.json")
        self.codex = load_json(ROOT / ".agents" / "plugins" / "marketplace.json")

    def test_claude_marketplace_fields(self):
        name = self.claude["name"]
        self.assertRegex(name, MARKETPLACE_NAME)
        self.assertNotIn("..", name)
        self.assertTrue(self.claude["owner"]["name"])
        self.assertTrue(self.claude.get("description"))
        self.assertTrue(self.claude["plugins"])

    def test_claude_entries_point_to_plugins(self):
        for entry in self.claude["plugins"]:
            with self.subTest(plugin=entry["name"]):
                self.assertRegex(entry["name"], KEBAB)
                source = entry["source"]
                self.assertTrue(source.startswith("./plugins/"), source)
                self.assertNotIn("..", source)
                self.assertNotIn("\\", source)
                plugin = ROOT / source[2:]
                manifest = load_json(plugin / ".claude-plugin" / "plugin.json")
                self.assertEqual(entry["name"], manifest["name"])
                # plugin.json owns the version; an entry version only causes a warning.
                self.assertNotIn("version", entry)

    def test_codex_marketplace_matches_claude(self):
        self.assertEqual(self.codex["name"], self.claude["name"])
        claude_sources = {e["name"]: e["source"] for e in self.claude["plugins"]}
        codex_entries = {e["name"]: e for e in self.codex["plugins"]}
        self.assertEqual(set(codex_entries), set(claude_sources))
        for name, entry in codex_entries.items():
            with self.subTest(plugin=name):
                self.assertEqual(entry["source"]["source"], "local")
                self.assertEqual(entry["source"]["path"], claude_sources[name])
                self.assertIn(entry["policy"]["installation"], CODEX_INSTALLATION)
                self.assertTrue(entry["policy"]["authentication"])
                self.assertTrue(entry["category"])

    def test_every_plugin_is_listed(self):
        listed = {e["source"] for e in self.claude["plugins"]}
        on_disk = {"./plugins/" + p.name for p in plugin_dirs()}
        self.assertEqual(listed, on_disk)


class ManifestTest(unittest.TestCase):
    def test_both_manifests_agree(self):
        for plugin in plugin_dirs():
            with self.subTest(plugin=plugin.name):
                claude = load_json(plugin / ".claude-plugin" / "plugin.json")
                codex = codex_manifest(plugin)
                self.assertEqual(claude["name"], plugin.name)
                self.assertRegex(claude["version"], SEMVER)
                self.assertEqual(claude["license"], LICENSE)
                for field in SHARED_FIELDS:
                    self.assertEqual(claude.get(field), codex.get(field), field)

    def test_each_plugin_has_one_codex_manifest(self):
        for plugin in plugin_dirs():
            with self.subTest(plugin=plugin.name):
                root = (plugin / "plugin.json").exists()
                folder = (plugin / ".codex-plugin" / "plugin.json").exists()
                self.assertNotEqual(root, folder, "keep one of plugin.json and .codex-plugin/plugin.json")

    def test_hook_plugins_have_no_root_manifest(self):
        # Codex CLI 0.164.0 skips a plugin's hooks when the plugin has a root
        # plugin.json, even next to .codex-plugin/plugin.json (openai/codex#39895,
        # reproduced on 2026-10-23). A plugin with hooks uses .codex-plugin only.
        for plugin in plugin_dirs():
            if (plugin / "hooks").exists():
                with self.subTest(plugin=plugin.name):
                    self.assertFalse((plugin / "plugin.json").exists())
                    self.assertTrue((plugin / ".codex-plugin" / "plugin.json").exists())

    def test_portable_manifest_follows_agent_plugins(self):
        for plugin in plugin_dirs():
            if not (plugin / "plugin.json").exists():
                continue
            with self.subTest(plugin=plugin.name):
                portable = load_json(plugin / "plugin.json")
                self.assertEqual(portable["$schema"], AGENT_PLUGINS_SCHEMA)
                self.assertLessEqual(set(portable), AGENT_PLUGINS_KEYS)
                name = portable["name"]
                self.assertRegex(name, AGENT_PLUGINS_NAME)
                self.assertNotIn("--", name)
                self.assertNotIn("..", name)
                for namespace in portable.get("extensions", {}):
                    self.assertIn(".", namespace, "extension keys are reverse-domain names")

    def test_core_plugin_is_skills_only(self):
        # The core plugin must stay portable to Codex, OpenAI's directory and
        # other Agent Plugins clients, so it carries skills and nothing else.
        core = PLUGINS / "corthex"
        manifest = load_json(core / ".claude-plugin" / "plugin.json")
        for key in ("hooks", "commands", "agents", "mcpServers", "lspServers", "userConfig", "channels"):
            self.assertNotIn(key, manifest)
        for folder in ("hooks", "commands", "agents", "monitors"):
            self.assertFalse((core / folder).exists(), folder)
        for name in (".mcp.json", "mcp.json", ".lsp.json"):
            self.assertFalse((core / name).exists(), name)
        self.assertNotIn("hooks", load_json(core / "plugin.json").get("extensions", {}).get("com.openai", {}))


class LicenseTest(unittest.TestCase):
    def test_each_plugin_ships_the_license(self):
        root_license = (ROOT / "LICENSE").read_bytes()
        self.assertIn(b"Apache License", root_license)
        for plugin in plugin_dirs():
            with self.subTest(plugin=plugin.name):
                self.assertEqual((plugin / "LICENSE").read_bytes(), root_license)
                if (ROOT / "NOTICE").exists():
                    self.assertEqual((plugin / "NOTICE").read_bytes(), (ROOT / "NOTICE").read_bytes())


if __name__ == "__main__":
    unittest.main()
