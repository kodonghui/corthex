"""TC-425–428: the 0.3.0 activation's first step (TASK-117), the command runner behind the version condition.

The tests set the release that the code reads, `activation._release`, since the
plugin on `main` keeps its 0.2.x version until the release (TASK-051).
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import ROOT, load_json
from test_memory_api import fits

SCRIPTS = ROOT / "plugins/corthex-memory/skills/corthex-memory/scripts"
sys.path.insert(0, str(SCRIPTS))
from memory_lib import activation, c2_status, c2_store, commands, format2, migration_command, status, store

ITEM, OTHER = "i_7f3k2m9q4x1v", "i_2b8d0w5n6c3r"
ARGV = {
    "on": [], "off": [], "status": [], "resume": [], "list": [], "search": ["words"], "open": [ITEM],
    "pin": [ITEM], "unpin": [ITEM], "forget": [ITEM], "delete-project": [], "purge": [], "leave-out": [],
    "retention": ["300"], "sync": ["off"], "setup": ["--at", "/workspace/demo"], "repair": [],
    "conflicts": [], "runs": [], "undo": ["r_7f3k2m9q4x1v"], "migrate": [],
}
C1_HANDLERS = {"on", "off", "status", "leave-out", "retention", "purge", "repair"}


def release(version):
    return mock.patch.object(activation, "_release", [version])


class ActivationTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name).resolve()
        self.root, home, self.project = (self.folder / name for name in ("memory", "home", "project"))
        self.project.mkdir()
        (home / ".corthex").mkdir(parents=True)
        (home / ".corthex/projects.json").write_text(
            json.dumps({"projects": [{"name": "demo", "path": str(self.project)}]}), encoding="utf-8")
        patch = mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home),
                                             "CORTHEX_MEMORY_HOME": str(self.root)})
        patch.start()
        self.addCleanup(patch.stop)
        for name in ("CORTHEX_MEMORY_ANTHROPIC_API_KEY", "CORTHEX_MEMORY_OPENAI_API_KEY"):
            os.environ.pop(name, None)
        self.schema = load_json(ROOT / "docs/06-api/memory-result.schema.json")

    def run_command(self, *argv, handlers=None):
        value, code = commands.run(["--folder", str(self.project)] + list(argv), handlers)
        self.assertEqual(fits(self.schema, value), [], value)
        return value

    def turn_on(self, version):
        with release(version):
            asked = self.run_command("on")
            self.assertEqual(asked["outcome"], "confirm")
            self.assertEqual(self.run_command("on", "--confirm", asked["confirm"])["outcome"], "done")
        return json.loads((self.root / "store.json").read_text(encoding="utf-8"))

    def confirmed(self, *argv):
        asked = self.run_command(*argv)
        self.assertEqual(asked["outcome"], "confirm", asked)
        return self.run_command(*argv, "--confirm", asked["confirm"])

    def probe(self, calls):
        def handler(context):
            calls.append(context)
            return commands.common_result(context.command, "lock-busy")
        return {name: handler for name in ARGV}

    def answers(self):
        """{command: (code, reached its handler, context)} with every handler a probe, at release 0.3.0."""
        found = {}
        with release("0.3.0"):
            for command, extra in ARGV.items():
                calls = []
                value = self.run_command(command, *extra, handlers=self.probe(calls))
                found[command] = (value["code"], bool(calls), calls[0] if calls else None)
        return found

    def test_tc425_the_version_condition(self):
        self.assertFalse(activation.c2("0.2.1"))
        for version in ("0.3.0", "0.3.1", "0.10.0", "1.0"):
            self.assertTrue(activation.c2(version), version)
        for version in ("", "0.3.x", None):
            with release(version):
                self.assertFalse(activation.c2())
        with mock.patch.object(activation, "_release", []), \
                mock.patch.object(activation, "_MANIFEST", self.folder / "missing.json"):
            self.assertFalse(activation.c2())
        manifest = load_json(ROOT / "plugins/corthex-memory/.codex-plugin/plugin.json")
        with mock.patch.object(activation, "_release", []):
            self.assertEqual(activation.release(), manifest["version"])
        self.assertIs(migration_command.release, activation.release)
        # Below 0.3.0 the runner parses no command of LATER, finds no kind and keeps C1's handlers.
        self.turn_on("0.3.0")
        with release("0.2.1"), mock.patch.object(activation, "store_kind") as kind:
            for command in commands.LATER:
                value = self.run_command(command, *ARGV[command])
                self.assertEqual((value["command"], value["code"]), ("none", "usage"))
            self.assertEqual(self.run_command("status")["code"], "store-newer")
            kind.assert_not_called()
        self.assertEqual(set(commands._handlers(False, None)), C1_HANDLERS)
        handlers = commands._handlers(True, activation.FORMAT_2)
        self.assertEqual(set(handlers), commands.EVERY - {"sync"})
        self.assertIs(handlers["status"], c2_status.status)
        self.assertIs(commands._handlers(True, activation.FORMAT_1)["status"], status.status)
        # From 0.3.0 each command reaches its handler on a format-2 store, through the format-2 binding.
        header = json.loads((self.root / "store.json").read_text(encoding="utf-8"))
        for command, (code, reached, context) in self.answers().items():
            with self.subTest(command=command):
                self.assertEqual((code, reached), ("lock-busy", True))
                self.assertEqual(context.kind, activation.FORMAT_2)
                self.assertEqual(context.format, 2)
                bound = isinstance(context.memory, c2_store.CommandStore)
                self.assertEqual(bound, command not in ("purge", "migrate"))
                if command != "migrate":
                    self.assertEqual(context.record["device"] if context.record else None,
                                     None if command == "purge" else header["device"])

    def test_tc426_each_kind_of_store_gets_its_answer(self):
        made = self.turn_on("0.2.0")
        original = (self.root / "store.json").read_bytes()
        found = self.answers()
        for command, (code, reached, context) in found.items():
            with self.subTest(kind="format 1", command=command):
                if command in commands.CURATED:
                    self.assertEqual((code, reached), ("migration-needed", False))
                else:
                    self.assertEqual((code, reached), ("lock-busy", True))
                    self.assertEqual((context.kind, context.format), (activation.FORMAT_1, 1))
        migrating = dict(made, format=2, release="0.3.0", migrating={"from": 1, "to": 2, "started": made["made"]})
        newer = dict(made, format=3)
        mixed = dict(made, format=2, release="0.3.0")
        cases = (("migrating", migrating, None, {"purge", "migrate"}, "migration-needed"),
                 ("migrating backup", made, migrating, {"purge", "migrate"}, "migration-needed"),
                 ("newer", newer, None, {"purge", "migrate"}, "store-newer"),
                 ("mixed", mixed, made, {"purge", "repair", "migrate"}, "store-damaged"),
                 ("unreadable", None, None, {"purge", "repair", "migrate"}, "store-damaged"))
        for label, primary, backup, reaching, refusal in cases:
            if primary is None:
                (self.root / "store.json").write_bytes(b"{")
            else:
                (self.root / "store.json").write_text(json.dumps(primary), encoding="utf-8")
            if backup is not None:
                (self.root / "store.json.bak").write_text(json.dumps(backup), encoding="utf-8")
            for command, (code, reached, context) in self.answers().items():
                with self.subTest(kind=label, command=command):
                    if command in reaching:
                        self.assertEqual((code, reached), ("lock-busy", True))
                        if command == "repair":
                            self.assertIsNone(context.record)
                    else:
                        self.assertEqual((code, reached), (refusal, False))
            if (self.root / "store.json.bak").exists():
                (self.root / "store.json.bak").unlink()
        # A format-1 backup restores a store record that cannot be read, as C1's gate does.
        (self.root / "store.json").write_bytes(b"{")
        (self.root / "store.json.bak").write_bytes(original)
        code, reached, context = self.answers()["status"]
        self.assertEqual((code, context.kind), ("lock-busy", activation.FORMAT_1))
        self.assertEqual((self.root / "store.json").read_bytes(), original)
        # Without a memory folder, `on` gets a format-2 store and the others C1's gates.
        shutil.rmtree(str(self.root))
        for command, (code, reached, context) in self.answers().items():
            with self.subTest(kind="none", command=command):
                if command in ("on", "purge", "repair", "migrate"):
                    self.assertEqual((code, reached), ("lock-busy", True))
                    self.assertEqual((context.kind, context.format), (activation.NONE, 2))
                else:
                    self.assertEqual((code, reached), ("no-store", False))
        self.assertFalse(self.root.exists())

    def test_tc427_c1_commands_on_a_format_2_store(self):
        header = self.turn_on("0.3.0")
        self.assertEqual((header["format"], header["release"]), (2, "0.3.0"))
        self.assertEqual(format2.parse_store((self.root / "store.json").read_bytes()), header)
        folder = self.root / "projects/demo"
        for name in ("raw", "unprocessed", "notices", "injections", "layer/items", "layer/tombstones", "runs"):
            self.assertTrue((folder / name).is_dir(), name)
        for name in ("layer/state.json", "layer/state-removed.json", "layer/pins.json", "layer/item-list.txt",
                     "state-history.jsonl", "layer/conflicts.json"):
            self.assertTrue((folder / name).is_file(), name)
        format2.parse_curation((folder / "curation.json").read_bytes())
        with release("0.3.0"):
            value = self.run_command("status")
            self.assertEqual((value["code"], value["data"]["store"]["format"]), ("ok", 2))
            self.assertEqual(self.run_command("off")["outcome"], "done")
            self.assertEqual(self.run_command("on")["outcome"], "done")
            value = self.run_command("leave-out", "--kind", "prompt")
            self.assertEqual((value["outcome"], value["data"]["kinds"]), ("done", ["prompt"]))
            self.assertEqual(self.run_command("retention", "300")["outcome"], "done")
            self.assertEqual(self.confirmed("retention", "30")["outcome"], "done")
            document = json.loads((self.root / "configuration.json").read_text(encoding="utf-8"))
            self.assertEqual(document["retention"]["days"], 30)
            self.assertEqual(document["projects"]["demo"]["left_out"]["kinds"], ["prompt"])
            # purge counts the items that no tombstone names, as delete-project does.
            for name in (ITEM, OTHER):
                (folder / "layer/items" / (name + ".json")).write_text("{}", encoding="utf-8")
            (folder / "layer/tombstones" / (OTHER + ".json")).write_text("{}", encoding="utf-8")
            value = self.run_command("purge")
            self.assertEqual((value["outcome"], value["data"]["projects"], value["data"]["deleted"]["items"]),
                             ("confirm", ["demo"], 1))
            self.assertEqual(self.run_command("delete-project")["data"]["deleted"]["items"], 1)
            self.assertEqual(json.loads((self.root / "store.json").read_text(encoding="utf-8")), header)
        # A format-1 store keeps C1's status, which says that migrate comes first.
        shutil.rmtree(str(self.root))
        self.turn_on("0.2.0")
        with release("0.2.1"):
            below = self.run_command("status")["say"]
        with release("0.3.0"):
            value = self.run_command("status")
        self.assertNotIn("migrate", below)
        self.assertEqual(value["data"]["store"]["format"], 1)
        self.assertIn("migrate command", value["say"])

    def test_tc428_repair_writes_the_projects_format_and_migrate_accepts_it(self):
        self.assertTrue(migration_command._supported("0.2.0", "0.3.0"))
        self.assertTrue(migration_command._supported("0.3.0", "0.3.0"))
        self.assertTrue(migration_command._supported("0.3.0", "0.4.0"))
        for source in ("0.3.1", "0.1.0", "0.2.2", "x"):
            self.assertFalse(migration_command._supported(source, "0.3.0"), source)
        # A store that only C1 code paths wrote gets a format-1 record of this release, which migrate moves.
        self.turn_on("0.2.0")
        (self.root / "store.json").write_bytes(b"{")
        with release("0.3.0"):
            value = self.confirmed("repair")
            record = json.loads((self.root / "store.json").read_text(encoding="utf-8"))
            self.assertEqual((value["code"], record["format"], record["release"]), ("ok", 1, "0.3.0"))
            self.assertEqual(self.run_command("list")["code"], "migration-needed")
            value = self.confirmed("migrate")
            self.assertEqual((value["outcome"], value["data"]["phase"]), ("done", "migrated"))
            self.assertEqual(json.loads((self.root / "store.json").read_text(encoding="utf-8"))["format"], 2)
            self.assertEqual(self.run_command("list")["outcome"], "nothing")
        # A format-2 store, a pair of different formats and a store without projects get a format-2 record.
        for label in ("format 2", "mixed", "no project"):
            shutil.rmtree(str(self.root))
            made = self.turn_on("0.3.0")
            if label == "mixed":
                (self.root / "store.json.bak").write_text(json.dumps(dict(made, format=1, release="0.2.0")),
                                                          encoding="utf-8")
            else:
                (self.root / "store.json").write_bytes(b"{")
            if label == "no project":
                shutil.rmtree(str(self.root / "projects"))
            with release("0.3.0"):
                value = self.confirmed("repair")
                record = format2.parse_store((self.root / "store.json").read_bytes())
                with self.subTest(store=label):
                    self.assertEqual((value["code"], record["release"]), ("ok", "0.3.0"))
                    self.assertNotEqual(record["device"], made["device"])
                    self.assertFalse((self.root / "store.json.bak").exists())
                    self.assertEqual(self.run_command("repair")["outcome"], "nothing")
        # A migration that stopped is migrate's to finish, never repair's.
        migrating = dict(record, migrating={"from": 1, "to": 2, "started": record["made"]})
        (self.root / "store.json").write_text(json.dumps(migrating), encoding="utf-8")
        before = (self.root / "store.json").read_bytes()
        with release("0.3.0"):
            self.assertEqual(self.run_command("repair")["code"], "migration-needed")
        self.assertEqual((self.root / "store.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
