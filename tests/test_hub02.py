"""NEXUS 0.2 boundary tests. Every repository and HTTP peer is synthetic."""
import contextlib
import http.server
import io
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from test_hub import HubCase, NOW, SCRIPT, hub, output_blocks

H = SimpleNamespace(**vars(hub))
SNAPSHOT = hub.companion("snapshot02")
BOX = hub.companion("outbox")
CMD = hub.companion("commands")
HTTP = hub.companion("transport")
RECORD = hub.companion("records")
SESSION = "test-session"
COMMENT = "nc_" + "a" * 12
PROPOSAL = "np_" + "b" * 12
EDIT = "ne_" + "c" * 12
CHECKPOINT = "nk_" + "d" * 12
DISCREPANCY = "nd_" + "e" * 12


class GitSourcesFixture(HubCase):
    def setUp(self):
        super().setUp()
        if hub.git_program() is None:
            self.skipTest("Git is not installed")
        self.project(stages={"01-domain": {"source": "docs/01-domain/"},
                             "05-erd": {"source": "db/schema.sql"},
                             "07-sitemap": {"source": "docs/07-sitemap/"}})
        self.register()
        self.git("init")
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        self.git("config", "user.name", "Fixture author")
        self.git("config", "user.email", "fixture@example.com")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", str(self.base / "empty-hooks"))
        self.git("config", "remote.origin.url", "git@example.com:team/shop.git")
        self.write(self.repo / "docs/01-domain/domain.md", "## CTX-001 Original\nPurpose: baseline\n")
        self.write(self.repo / "db/schema.sql", "-- TBL-001 original | CTX-001 | terms: TERM-001\nCREATE TABLE original (id INTEGER PRIMARY KEY);\n")
        self.write(self.repo / "docs/07-sitemap/site.yaml", "- id: SCR-001\n  name: Original\n  path: /original\n  access: everyone\n  terms: none\n")
        self.record = {"format": 1, "project": "acme-shop", "stages": {"05-erd": {
            "state": "done", "checkpoints": [{"approved": "Original tables", "by": "the maintainer", "date": "2026-11-03"}],
            "next": "Original next", "updated": NOW}}}
        self.write(self.repo / ".corthex/stages.json", self.record)
        self.original = self.commit("baseline")
        self.git("update-ref", "refs/remotes/origin/main", self.original)
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")

    def git(self, *args):
        value = hub.run_git(self.repo, args)
        self.assertIsNotNone(value, "fixture Git command failed: " + args[0])
        return value.decode("utf8").strip()

    def commit(self, message):
        self.git("add", ".")
        with mock.patch.dict(os.environ, {"GIT_AUTHOR_DATE": NOW, "GIT_COMMITTER_DATE": NOW}):
            self.git("commit", "--no-verify", "-m", message)
        return self.git("rev-parse", "HEAD")


class GitSourcesTest(GitSourcesFixture):
    def test_bom_git_objects_match_the_working_tree_text_reader(self):
        for path in ("docs/01-domain/domain.md", "db/schema.sql", "docs/07-sitemap/site.yaml", ".corthex/stages.json"):
            current = self.repo / path
            current.write_text("\ufeff" + current.read_text(encoding="utf8"), encoding="utf8")
        head = self.commit("BOM sources")
        self.git("update-ref", "refs/remotes/origin/main", head)
        snapshot = self.snapshot()
        by_stage = {p["stage"]: p["source"] for p in snapshot["pictures"]}
        self.assertEqual(by_stage["01-domain"]["contexts"][0]["id"], "CTX-001")
        self.assertEqual(by_stage["05-erd"]["tables"][0]["name"], "original")
        self.assertEqual(by_stage["07-sitemap"]["screens"][0]["id"], "SCR-001")
        self.assertEqual(snapshot["stages"]["05-erd"]["state"], "done")

    def test_picture_file_budget_ignores_unsupported_files(self):
        self.project(stages={"05-erd": {"source": "db/"}})
        for index in range(400):
            self.write(self.repo / ("db/a-%03d.png" % index), "not a picture source")
        head = self.commit("unrelated binary filenames")
        self.git("update-ref", "refs/remotes/origin/main", head)
        snapshot = self.snapshot()
        picture = next(p for p in snapshot["pictures"] if p["stage"] == "05-erd")
        self.assertEqual(picture["source"]["tables"][0]["id"], "TBL-001")
        self.assertFalse(any("supported sources omitted" in c["message"] for c in snapshot["checks"]))

    def test_supported_sources_over_the_budget_have_an_explicit_check(self):
        self.project(stages={"05-erd": {"source": "db/"}})
        for index in range(400):
            self.write(self.repo / ("db/a-%03d.sql" % index), "CREATE TABLE t%d (id INT);\n" % index)
        head = self.commit("supported source overflow")
        self.git("update-ref", "refs/remotes/origin/main", head)
        snapshot = self.snapshot()
        picture = next(p for p in snapshot["pictures"] if p["stage"] == "05-erd")
        self.assertEqual(len(picture["source"]["tables"]), 400)
        warning = next(c for c in self.found(snapshot, "picture-partial") if c.get("args", {}).get("omitted"))
        self.assertEqual(warning["args"], {"limit": 400, "omitted": 1})
        self.assertIn("db/schema.sql:1", warning["message"])

    def test_default_objects_exclude_branch_and_uncommitted_material(self):
        self.git("checkout", "-b", "work")
        self.write(self.repo / "db/schema.sql", "CREATE TABLE branch_only (id INT);\n")
        self.commit("work branch")
        self.write(self.repo / "docs/01-domain/domain.md", "## CTX-999 Uncommitted\n")
        changed = json.loads(json.dumps(self.record))
        changed["stages"]["05-erd"]["next"] = "Working tree next"
        self.write(self.repo / ".corthex/stages.json", changed)
        snapshot = self.snapshot()
        self.assertEqual(snapshot["schema"], "corthex-hub/0.2")
        self.assertEqual(snapshot["repos"]["."]["url"], "https://example.com/team/shop")
        self.assertEqual(snapshot["repos"]["."]["default"]["commit"], self.original)
        self.assertTrue(all(p["commit"] == self.original for p in snapshot["pictures"]))
        domain, erd, sitemap = [next(p["source"] for p in snapshot["pictures"] if p["stage"] == s)
                                for s in SNAPSHOT.PICTURE_STAGES]
        self.assertEqual([c["id"] for c in domain["contexts"]], ["CTX-001"])
        self.assertEqual([t["name"] for t in erd["tables"]], ["original"])
        self.assertEqual(sitemap["screens"][0]["name"], "Original")
        stage = snapshot["stages"]["05-erd"]
        self.assertEqual((stage["state"], stage["next"], stage["checkpoint"]), ("done", "Original next", "Original tables"))
        self.assertEqual(snapshot["records"], {"from": "repository", "commit": self.original,
                                              "time": snapshot["repos"]["."]["default"]["time"]})

    def test_no_default_head_has_no_pictures_and_explicit_fallback(self):
        self.git("symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
        snapshot = self.snapshot()
        self.assertEqual(snapshot["pictures"], [])
        self.assertEqual(snapshot["records"], {"from": "status-file"})
        self.assertTrue(self.found(snapshot, "pictures-not-sent"))
        self.assertTrue(self.found(snapshot, "records-in-status-file"))

    def test_parts_use_longest_prefix_and_unknown_documents_stay_project_wide(self):
        self.project(parts=["web", "web-api"], stages={"01-domain": {"source": "docs/01-domain/"}, "05-erd": {"source": "remote:db/"}})
        for name, ident in (("web.md", "CTX-002"), ("web-api/board.md", "CTX-003")):
            self.write(self.repo / "docs/01-domain" / name, "## " + ident + " Context\n")
        head = self.commit("parts")
        self.git("update-ref", "refs/remotes/origin/main", head)
        snapshot = self.snapshot()
        boards = {p["part"]: p["source"] for p in snapshot["pictures"] if p["stage"] == "01-domain"}
        self.assertEqual(set(boards), {"", "web", "web-api"})
        self.assertEqual(boards["web-api"]["contexts"][0]["id"], "CTX-003")
        self.assertTrue(self.found(snapshot, "part-unknown"))
        self.assertEqual([p["part"] for p in snapshot["left_out"] if p["stage"] == "05-erd"], ["web", "web-api"])

    def test_invalid_repository_record_does_not_fall_back_to_device_done(self):
        hub.record_status(self.home, "acme-shop", "05-erd", "done", "Device approval", "2026-11-03")
        self.write(self.repo / ".corthex/stages.json", "not JSON")
        head = self.commit("invalid record")
        self.git("update-ref", "refs/remotes/origin/main", head)
        snapshot = self.snapshot()
        self.assertEqual(snapshot["records"]["from"], "repository")
        self.assertEqual(snapshot["stages"]["05-erd"]["state"], "unknown")
        self.assertTrue(self.found(snapshot, "records-invalid"))

    def test_safe_object_reader_does_not_execute_filters_or_fsmonitor(self):
        marker = self.base / "executed"
        dangerous = '"' + sys.executable + '" -c "open(' + repr(str(marker)) + ',\'w\').close()"'
        self.git("config", "core.fsmonitor", dangerous)
        self.git("config", "filter.danger.clean", dangerous)
        (self.repo / ".git/info/attributes").write_text("*.md filter=danger\n", encoding="utf8")
        self.assertTrue(self.snapshot()["pictures"])
        self.assertFalse(marker.exists())

    def test_largest_whole_picture_is_omitted_before_items(self):
        columns = ",\n".join("column_" + str(i) + " VARCHAR(120)" for i in range(150))
        self.write(self.repo / "db/schema.sql", "-- TBL-001 large | CTX-001 | terms: none\nCREATE TABLE large (" + columns + ");\n")
        head = self.commit("large ERD fixture")
        self.git("update-ref", "refs/remotes/origin/main", head)
        normal = self.snapshot()
        erd = next(p for p in normal["pictures"] if p["stage"] == "05-erd")
        limit = len(hub.dump(normal, compact=True).encode("utf8")) - len(hub.dump(erd, compact=True).encode("utf8")) + 512
        with mock.patch.object(hub, "MAX_SNAPSHOT_BYTES", limit):
            snapshot = self.snapshot()
        self.assertEqual(snapshot["left_out"][0], {"part": "", "stage": "05-erd", "why": "size"})
        self.assertEqual({p["stage"] for p in snapshot["pictures"]}, {"01-domain", "07-sitemap"})
        self.assertEqual(snapshot["items"], normal["items"])
        self.assertLessEqual(len(hub.dump(snapshot, compact=True).encode("utf8")), limit)

    def test_git_replacement_refs_cannot_change_the_reported_default_bytes(self):
        self.git("checkout", "-b", "work-replacement")
        self.write(self.repo / "docs/01-domain/domain.md", "## CTX-999 Work branch\n")
        replacement = self.commit("work replacement")
        self.git("replace", self.original, replacement)
        snapshot = self.snapshot()
        board = next(p for p in snapshot["pictures"] if p["stage"] == "01-domain")
        self.assertEqual(board["commit"], self.original)
        self.assertEqual([c["id"] for c in board["source"]["contexts"]], ["CTX-001"])


class PictureReadersTest(unittest.TestCase):
    def parse(self, name, text, path=None):
        checks = []
        helper = SimpleNamespace(**vars(hub), picture_ids=hub.IdFormat({}))
        data = hub.companion(name).parse([(path or "fixture." + {"domain": "md", "erd": "sql", "sitemap": "yaml"}[name], text)], checks, helper, "demo")
        return data, checks

    def test_stage_templates_name_their_represented_terms(self):
        erd, _ = self.parse("erd", output_blocks("corthex-contract", "05-erd")[0])
        orders = next(table for table in erd["tables"] if table["name"] == "orders")
        self.assertEqual(orders["terms"], ["TERM-001"])
        sitemap, _ = self.parse("sitemap", output_blocks("corthex-screen", "07-sitemap")[0])
        screens = {screen["id"]: screen for screen in sitemap["screens"]}
        self.assertEqual(screens["SCR-001"]["terms"], [])
        self.assertEqual(screens["SCR-002"]["terms"], ["TERM-001"])
        self.assertEqual(screens["SCR-002"]["context"], "CTX-001")

    def test_struck_timeline_boundaries_do_not_leave_phantom_events(self):
        for sequence, expected in (("~~Old~~ → Saved", [["Saved"]]),
                ("Started → ~~Old~~", [["Started"]]), ("~~Old~~ → ~~Gone~~", []),
                ("Started → ~~Old~~ → Saved", [["Started"], ["Saved"]]),
                ("Started → Saved", [["Started"], ["Saved"]])):
            with self.subTest(sequence=sequence):
                text = "## CTX-001 Shop\n\n| Lane | Events |\n| --- | --- |\n| User | " + sequence + " |\n"
                data, checks = self.parse("domain", text)
                self.assertEqual(data["timeline"][0]["places"], expected)
                self.assertEqual(checks, [])

    def test_struck_domain_terms_commands_and_events_are_not_resurrected(self):
        text = ("## CTX-001 Shop\n"
                "| Context | Type | Aggregates |\n| --- | --- | --- |\n| CTX-001 | core | ~~Old order (TERM-001)~~, Live order (TERM-003) |\n\n"
                "| Given by | Read model | Command | Aggregate | Events |\n| --- | --- | --- | --- | --- |\n"
                "| User | Summary | Save | Live order | ~~Old event~~, Saved |\n"
                "| ~~Old user~~ | ~~Old summary~~ | ~~Old command~~ | ~~Old order (TERM-001)~~ | ~~Old event~~ |\n\n"
                "| ID | Term |\n| --- | --- |\n| ~~TERM-001~~ | ~~Old order~~ |\n| TERM-002 | Summary |\n| TERM-003 | Live order |\n")
        data, checks = self.parse("domain", text)
        self.assertEqual([row["name"] for row in data["aggregates"]], ["Live order"])
        self.assertEqual([row["name"] for row in data["read_models"]], ["Summary"])
        self.assertEqual(data["contexts"][0]["rows"][0]["events"], ["Saved"])
        self.assertNotIn("Old", json.dumps(data))
        self.assertEqual(checks, [])

    def test_command_rows_outside_context_headings_keep_their_names(self):
        row = "| Given by | Read model | Command | Aggregate | Events |\n| --- | --- | --- | --- | --- |\n| User | Summary | Save | Order | Saved |\n"
        data, checks = self.parse("domain", row + "\n## CTX-001 Shop\nPurpose: Sales\n\n## Other section\n" + row)
        contexts = {context["id"]: context for context in data["contexts"]}
        self.assertEqual(contexts[""]["name"], "")
        self.assertEqual(contexts[""]["rows"][0]["command"], "Save")
        self.assertEqual(contexts["CTX-001"]["rows"][0]["command"], "Save")
        self.assertEqual({model["context"] for model in data["read_models"]}, {"", "CTX-001"})
        self.assertEqual(len([c for c in checks if c["rule"] == "picture-partial"]), 2)
        self.assertTrue(all("" not in c.get("ids", []) for c in checks))

    def test_nested_heading_retains_context_and_contextless_document_adds_no_board(self):
        row = "| Given by | Read model | Command | Aggregate | Events |\n| --- | --- | --- | --- | --- |\n| User | none | Save | none | Saved |\n"
        helper = SimpleNamespace(**vars(hub), picture_ids=hub.IdFormat({}))
        checks = []
        data = hub.companion("domain").parse([("valid.md", "## CTX-001 Shop\n### Commands\n" + row),
            ("no-context.md", "| Lane | Events |\n| --- | --- |\n| Unassigned | Bad event |\n" + row)], checks, helper, "demo")
        self.assertEqual(len(data["contexts"]), 1)
        self.assertEqual(len(data["contexts"][0]["rows"]), 1)
        self.assertNotIn("timeline", data)
        self.assertEqual(len(checks), 1)
        self.assertIn("no-context.md:1", checks[0]["message"])

    def test_sql_removed_vocabulary_and_computed_indexes_do_not_invent_columns(self):
        for status in sorted(hub.REMOVED):
            with self.subTest(status=status):
                data, checks = self.parse("erd", "-- TBL-001 orders | status: " + status + " | terms: none\nCREATE TABLE orders (code TEXT);\n")
                self.assertTrue(data["tables"][0]["removed"])
                self.assertEqual(checks, [])
        for name in ("deleted_accounts", "cancelled_orders", "obsolete_records", "removed", "accounts"):
            for annotation in (" | status: active", "", " | 상태: active"):
                with self.subTest(name=name, annotation=annotation):
                    data, _ = self.parse("erd", "-- TBL-001 " + name + " | terms: none" + annotation +
                        "\nCREATE TABLE " + name + " (id INTEGER PRIMARY KEY);\n")
                    self.assertFalse(data["tables"][0]["removed"])
        for metadata in ("(CTX-001, deleted)", "| obsolete", "| status: active | removed"):
            data, _ = self.parse("erd", "-- TBL-001 accounts " + metadata + "\nCREATE TABLE accounts (id INT);\n")
            self.assertEqual(data["tables"][0]["removed"], "active" not in metadata)
        data, _ = self.parse("erd", "-- TBL-001 Deleted account history (CTX-001, terms: none)\nCREATE TABLE accounts (id INT);\n")
        self.assertFalse(data["tables"][0]["removed"])
        for name in ('"ledger (status: deleted)"', '"ledger (obsolete)"', '[ledger (deleted)]',
                     '`ledger (deprecated)`', '"ledger ""(status: deleted)"""',
                     '[ledger ]](deleted)]', '`ledger ``(deprecated)`'):
            for suffix in ("", " | status: active"):
                with self.subTest(quoted_name=name, suffix=suffix):
                    data, _ = self.parse("erd", "-- TBL-001 " + name + " (CTX-001, terms: none)" + suffix +
                        "\nCREATE TABLE " + name + " (id INT);\n")
                    self.assertFalse(data["tables"][0]["removed"])
        for value in ("'deleted'", '"obsolete"', '`deprecated`'):
            data, _ = self.parse("erd", "-- TBL-001 accounts | status: " + value + "\nCREATE TABLE accounts (id INT);\n")
            self.assertTrue(data["tables"][0]["removed"])
        data, _ = self.parse("erd", "-- TBL-001 Owner's account history (CTX-001, terms: none) | status: obsolete\nCREATE TABLE accounts (id INT);\n")
        self.assertTrue(data["tables"][0]["removed"])
        data, checks = self.parse("erd", "CREATE TABLE orders (code TEXT, id INT);\n"
            "CREATE UNIQUE INDEX valid ON orders (code COLLATE nocase DESC);\n"
            "CREATE UNIQUE INDEX function_value ON orders (lower(code));\n"
            "CREATE UNIQUE INDEX mixed ON orders (id, lower(code));\n")
        self.assertEqual(data["tables"][0]["unique"], [{"columns": ["code"], "partial": False}])
        self.assertEqual(len(checks), 2)
        self.assertTrue(all(c["rule"] == "picture-partial" for c in checks))

    def test_english_and_korean_domain_forms_and_ambiguous_terms(self):
        for language in ("en", "ko"):
            context, kind, aggregates = ("Context", "Type", "Aggregates") if language == "en" else ("컨텍스트", "종류", "애그리거트")
            text = ("| " + context + " | " + kind + " | " + aggregates + " |\n| --- | --- | --- |\n| CTX-001 Shop | core | Order |\n"
                    "## CTX-001 Shop\nPurpose: Sales\n"
                    "| Given by | Read model | Command | Aggregate | Events |\n| --- | --- | --- | --- | --- |\n| Policy: created | Summary | Create | Order | Created |\n"
                    "\n| ID | Term |\n| --- | --- |\n| TERM-001 | Order |\n| TERM-002 | Order |\n| TERM-003 | Summary |\n"
                    "\n| Lane | Events |\n| --- | --- |\n| Sales | Created → Paid or Cancelled |\n")
            data, checks = self.parse("domain", text)
            self.assertEqual(data["contexts"][0]["type"], "core")
            self.assertTrue(data["contexts"][0]["rows"][0]["policy"])
            self.assertEqual(data["aggregates"][0]["term"], "TERM-001")
            self.assertEqual(data["read_models"][0]["term"], "TERM-003")
            self.assertEqual(data["timeline"][0]["places"], [["Created"], ["Paid", "Cancelled"]])
            self.assertTrue(any(c["rule"] == "board-term-missing" for c in checks))

    def test_each_alter_action_keeps_its_own_foreign_key_and_delete_rule(self):
        for first, expected in (("", ""), (" ON DELETE RESTRICT", "restrict"), (" ON DELETE SET NULL", "set null")):
            with self.subTest(first=first):
                text = ('CREATE TABLE orders (buyer_id INT, region_id INT, seller_id INT);\n'
                        'ALTER TABLE orders ADD CONSTRAINT "buyer, link" FOREIGN KEY (buyer_id, region_id)\n'
                        'REFERENCES buyers(id, region)' + first + ',\n'
                        'ADD CONSTRAINT seller_link FOREIGN KEY (seller_id) REFERENCES sellers(id) ON DELETE CASCADE,\n'
                        'ALTER COLUMN buyer_id TYPE NUMERIC(12, 2);\n')
                data, checks = self.parse("erd", text, "fixture.sql")
                keys = data["tables"][0]["foreign_keys"]
                self.assertEqual([(key["columns"], key["table"], key["references"], key["on_delete"]) for key in keys],
                    [(["buyer_id", "region_id"], "buyers", ["id", "region"], expected),
                     (["seller_id"], "sellers", ["id"], "cascade")])
                self.assertEqual([key["where"] for key in keys], ["fixture.sql:3", "fixture.sql:4"])
                self.assertEqual(checks, [])

    def test_sql_types_keys_foreign_keys_and_partial_indexes(self):
        data, checks = self.parse("erd", """-- TBL-001 orders | CTX-001 | terms: TERM-001
CREATE TABLE orders (id INTEGER PRIMARY KEY, owner_id BIGINT NOT NULL,
 amount NUMERIC(12, 2), code VARCHAR(80) UNIQUE,
 CONSTRAINT uq UNIQUE (owner_id, code), FOREIGN KEY (owner_id) REFERENCES owners(id) ON DELETE CASCADE);
CREATE UNIQUE INDEX active_code ON orders(code) WHERE amount > 0;
ALTER TABLE orders ADD FOREIGN KEY (code) REFERENCES codes(value) ON DELETE SET NULL;
-- without a table: TERM-002
""")
        table = data["tables"][0]
        self.assertEqual(table["id"], "TBL-001")
        self.assertEqual(table["terms"], ["TERM-001"])
        self.assertEqual(table["primary_key"], ["id"])
        self.assertEqual([c["type"] for c in table["columns"]], ["INTEGER", "BIGINT", "NUMERIC(12, 2)", "VARCHAR(80)"])
        self.assertEqual([c["null"] for c in table["columns"]], [False, False, True, True])
        self.assertEqual({tuple(k["columns"]) for k in table["unique"]}, {("code",), ("owner_id", "code")})
        self.assertTrue(any(k["partial"] for k in table["unique"]))
        self.assertEqual([k["on_delete"] for k in table["foreign_keys"]], ["cascade", "set null"])
        self.assertEqual(data["without_table"], ["TERM-002"])
        self.assertEqual(checks, [])

    def test_nested_sitemap_keeps_idless_parents_and_explicit_none(self):
        data, checks = self.parse("sitemap", """# without a screen: TERM-009
- name: 'Home #1'
  path: /
  terms: none
  children:
    - id: SCR-001
      name: Detail
      path: /detail
      terms: [CTX-001, TERM-001]
      flows:
        - FL-001
      status: removed
""")
        self.assertEqual(len(data["screens"]), 2)
        self.assertEqual(data["screens"][0]["terms"], [])
        child = data["screens"][1]
        self.assertEqual((child["parent"], child["context"], child["terms"], child["flows"], child["removed"]), (0, "CTX-001", ["TERM-001"], ["FL-001"], True))
        self.assertEqual(data["without_screen"], ["TERM-009"])
        self.assertEqual(checks, [])

    def test_malformed_or_executable_yaml_is_not_an_empty_current_picture(self):
        for text in ("- name: !execute unsafe\n", "- name: [unterminated\n", "root: mapping\n", "- name: &alias unsafe\n"):
            with self.subTest(text=text):
                data, checks = self.parse("sitemap", text)
                self.assertIsNone(data)
                self.assertTrue(any(c["rule"] == "picture-partial" for c in checks))


class SettingsAndRecordsTest(HubCase):
    def record_fixture(self):
        self.project(parts=["nexus", "other"])
        self.register()
        self.record_target = self.repo / ".corthex/stages/nexus.json"
        data = {"format": 1, "project": "acme-shop", "part": "nexus", "stages": {
            "05-erd": {"state": "in_progress", "checkpoints": [], "next": "Original", "updated": NOW}}}
        self.write(self.record_target, data)
        self.write(self.repo / ".corthex/stages/other.json", dict(data, part="other"))
        return hub.select_projects(self.home, ["acme-shop"])[0][1]

    def record_args(self, stage):
        return hub.parser().parse_args(["status", "acme-shop", stage, "--part", "nexus", "--repository",
                                       "--state", "in_progress", "--next", stage + " next"])

    def test_record_identity_uses_stable_native_windows_information(self):
        self.record_fixture()
        identity = RECORD.directory_identity(self.record_target.parent)
        if os.name == "nt":
            with mock.patch.object(RECORD.os, "stat", side_effect=AssertionError("version-dependent stat was used")):
                self.assertEqual(RECORD.directory_identity(self.record_target.parent), identity)
            self.assertEqual(RECORD.directory_identity(Path(str(self.record_target.parent).upper())), identity)
        else:
            stat = self.record_target.parent.stat()
            self.assertEqual(identity, (stat.st_dev, stat.st_ino))

    @unittest.skipUnless(os.name == "nt", "Windows junction control")
    def test_record_guard_refuses_a_junction_into_the_repository(self):
        project = self.record_fixture()
        destination = self.repo / "guard-destination"
        destination.mkdir()
        root = self.home / ".corthex/hub/record-locks"
        root.parent.mkdir(parents=True, exist_ok=True)
        command = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/cmd.exe"
        made = subprocess.run([str(command), "/d", "/c", "mklink", "/J", str(root), str(destination)],
                              capture_output=True, timeout=10)
        if made.returncode:
            self.skipTest("junction creation is unavailable")
        before = self.record_target.read_bytes()
        try:
            self.assertFalse(root.is_symlink())
            with self.assertRaisesRegex(ValueError, "redirected"):
                RECORD.write(project, self.home, self.record_args("02-prd"), vars(hub), NOW)
            self.assertEqual(self.record_target.read_bytes(), before)
            self.assertEqual(list(destination.iterdir()), [])
        finally:
            os.rmdir(str(root))

    def test_record_guard_refuses_a_hardlinked_leaf_before_initialization(self):
        project = self.record_fixture()
        guard = RECORD.guard_path(self.record_target)
        unrelated = self.base / "unrelated-empty-file"
        unrelated.write_bytes(b"")
        os.link(str(unrelated), str(guard))
        before = self.record_target.read_bytes()
        with self.assertRaisesRegex(ValueError, "another hub"):
            RECORD.write(project, self.home, self.record_args("02-prd"), vars(hub), NOW)
        self.assertEqual(unrelated.read_bytes(), b"")
        self.assertEqual(self.record_target.read_bytes(), before)

    def test_record_guard_refuses_metadata_inside_the_repository(self):
        project = self.record_fixture()
        before = self.record_target.read_bytes()
        with mock.patch.object(RECORD, "guard_home", return_value=self.repo):
            with self.assertRaisesRegex(ValueError, "outside the repository"):
                RECORD.write(project, self.home, self.record_args("02-prd"), vars(hub), NOW)
        self.assertEqual(self.record_target.read_bytes(), before)
        self.assertFalse(list(self.repo.rglob("*.guard")))

    def test_record_read_modify_replace_serializes_threads(self):
        project = self.record_fixture()
        first_read, second_read, release = threading.Event(), threading.Event(), threading.Event()
        original = hub.load_json
        errors = []
        def read(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            if Path(path) == self.record_target:
                if threading.current_thread().name == "record-first":
                    first_read.set()
                    if not release.wait(5):
                        raise RuntimeError("synthetic writer was not released")
                else:
                    second_read.set()
            return value
        def update(stage):
            try:
                RECORD.write(project, self.home, self.record_args(stage), vars(hub), NOW)
            except Exception as error:
                errors.append(type(error).__name__)
        first = threading.Thread(name="record-first", target=update, args=("02-prd",))
        second = threading.Thread(name="record-second", target=update, args=("03-user-flow",))
        with mock.patch.object(hub, "load_json", side_effect=read):
            try:
                first.start()
                self.assertTrue(first_read.wait(5))
                second.start()
                self.assertFalse(second_read.wait(0.25), "the second writer read before the first published")
            finally:
                release.set()
                first.join(5)
                if second.ident is not None:
                    second.join(5)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(set(hub.load_json(self.record_target)["stages"]), {"02-prd", "03-user-flow", "05-erd"})

    def start_record_writer(self, home, stage, tag, wait=False):
        probe = self.base / "record-writer.py"
        probe.write_text('''import importlib.util, sys, time
from pathlib import Path
spec = importlib.util.spec_from_file_location("record_writer_probe", sys.argv[1])
hub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hub)
home, target, base = map(Path, sys.argv[2:5])
stage, tag, wait = sys.argv[5:8]
original = hub.load_json
def read(path, *args, **kwargs):
    value = original(path, *args, **kwargs)
    if Path(path) == target:
        (base / (tag + "-read")).write_text("read", encoding="utf8")
        if wait == "1":
            deadline = time.monotonic() + 10
            while not (base / "release").exists():
                if time.monotonic() > deadline:
                    raise RuntimeError("synthetic writer was not released")
                time.sleep(.01)
    return value
hub.load_json = read
(base / (tag + "-ready")).write_text("ready", encoding="utf8")
raise SystemExit(hub.main(["--home", str(home), "--json", "status", "acme-shop", stage,
    "--part", "nexus", "--repository", "--state", "in_progress", "--next", tag]))
''', encoding="utf8")
        env = {key: value for key, value in os.environ.items() if not key.startswith(("CORTHEX_NEXUS_", "NEXUS_DEV_"))}
        env.update(HOME=str(self.home), USERPROFILE=str(self.home), PYTHONIOENCODING="utf-8")
        return subprocess.Popen([sys.executable, str(probe), str(SCRIPT), str(home), str(self.record_target),
            str(self.base), stage, tag, "1" if wait else "0"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def wait_record_marker(self, name):
        deadline = time.monotonic() + 5
        while not (self.base / name).exists():
            self.assertLess(time.monotonic(), deadline, "the synthetic writer did not reach its marker")
            time.sleep(0.01)

    def test_record_processes_with_different_profiles_keep_both_stages(self):
        self.record_fixture()
        other = self.base / "other-profile"
        self.write(other / ".corthex/projects.json", {"projects": [{"name": "acme-shop", "path": str(self.repo)}]})
        sibling = (self.repo / ".corthex/stages/other.json").read_bytes()
        first = self.start_record_writer(self.home, "02-prd", "first", True)
        second = None
        try:
            self.wait_record_marker("first-read")
            second = self.start_record_writer(other, "03-user-flow", "second")
            self.wait_record_marker("second-ready")
            time.sleep(0.25)
            self.assertFalse((self.base / "second-read").exists(), "a second profile bypassed the record guard")
            self.write(self.base / "release", "go")
            first.communicate(timeout=10)
            second.communicate(timeout=10)
            self.assertEqual((first.returncode, second.returncode), (0, 0))
        finally:
            for process in (first, second):
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.communicate(timeout=10)
        self.assertEqual(set(hub.load_json(self.record_target)["stages"]), {"02-prd", "03-user-flow", "05-erd"})
        self.assertEqual((self.repo / ".corthex/stages/other.json").read_bytes(), sibling)
        self.assertFalse(list(self.repo.rglob("*.guard")))

    def test_killed_record_writer_releases_native_guard_without_partial_data(self):
        project = self.record_fixture()
        original = self.record_target.read_bytes()
        first = self.start_record_writer(self.home, "02-prd", "crashed", True)
        try:
            self.wait_record_marker("crashed-read")
            first.terminate()
            first.communicate(timeout=10)
            self.assertEqual(self.record_target.read_bytes(), original)
            RECORD.write(project, self.home, self.record_args("03-user-flow"), vars(hub), NOW)
            self.assertEqual(set(hub.load_json(self.record_target)["stages"]), {"03-user-flow", "05-erd"})
        finally:
            if first.poll() is None:
                first.terminate()
                first.communicate(timeout=10)

    def test_canonical_origins_remove_transport_credentials_and_suffix(self):
        upper_host = "example.com".upper()
        for raw in ("git@" + upper_host + ":team/shop.git", "ssh://git@" + upper_host + ":2222/team/shop.git/", "https://user:password@" + upper_host + "/team/shop.git", "http://" + upper_host + "/team/shop/"):
            self.assertEqual(SNAPSHOT.canonical_origin(raw, H), "https://example.com/team/shop")
        self.assertEqual(SNAPSHOT.canonical_origin("file:///local/repo", H), "")

    def test_sensitive_links_are_omitted_whole_and_home_paths_are_redacted(self):
        token = "synthetic-component"
        value = {"url": "https://example.com/?token=" + token, "where": "docs/example.md:1", "title": str(self.home / "folder"),
                 "link": "https://example.com/?email=person%40example.com"}
        safe = CMD.scrub(value, self.home, {"CORTHEX_NEXUS_CLIENT_SECRET": token}, H)
        self.assertNotIn("url", safe)
        self.assertNotIn("link", safe)
        self.assertEqual(safe["where"], value["where"])
        self.assertTrue(safe["title"].startswith("~"))

    def test_ask_before_precedence_invalid_fallback_and_limit(self):
        checks = []
        self.write(self.home / ".corthex/profile.json", {"ask_before": ["deploys", "payments"]})
        value = SNAPSHOT.ask_before({"ask_before": []}, self.home, checks, H)
        self.assertEqual(value, {"entries": [], "source": "project", "left_out": ["deploys", "payments"]})
        value = SNAPSHOT.ask_before({"ask_before": "bad"}, self.home, checks, H)
        self.assertEqual(value["source"], "profile")
        self.assertTrue(any(c["rule"] == "ask-before-invalid" for c in checks))
        value = SNAPSHOT.ask_before({"ask_before": ["action " + str(i) for i in range(35)]}, self.home, checks, H)
        self.assertEqual(len(value["entries"]), 30)
        self.assertTrue(any(c["rule"] == "ask-before-long" for c in checks))

    def test_project_entries_that_repeat_an_inherited_one_keep_it(self):
        checks = []
        self.write(self.home / ".corthex/profile.json", {"ask_before": ["deploys", "payments", "deletions", "publishing"]})
        value = SNAPSHOT.ask_before({"ask_before": ["Deletions (repositories, data)", "payments and plan changes", "publishing-only drafts"]},
                                    self.home, checks, H)
        self.assertEqual(value["source"], "project")
        self.assertEqual(value["left_out"], ["deploys", "publishing"])
        self.assertEqual(checks, [])

    def test_default_ask_before_agrees_with_core_example(self):
        from _common import PLUGINS
        text = (PLUGINS / "corthex/skills/corthex/references/profile.md").read_text(encoding="utf8")
        import re
        match = re.search(r'"ask_before"\s*:\s*(\[[^\]]*\])', text)
        self.assertIsNotNone(match)
        self.assertEqual(SNAPSHOT.DEFAULT_ASK_BEFORE, json.loads(match.group(1)))

    def test_unsafe_checkpoint_link_is_omitted_and_bad_dates_do_not_make_done(self):
        record = {"format": 1, "project": "acme-shop", "stages": {"05-erd": {"state": "done", "checkpoints": [
            {"approved": "Tables", "by": "maintainer", "date": "2026-11-03", "where": "https://example.com/?email=person%40example.com"}], "next": "API", "updated": NOW}}}
        helper = SimpleNamespace(**vars(hub), picture_ids=hub.IdFormat({}))
        checks = []
        result = SNAPSHOT.read_record(json.dumps(record), "acme-shop", "", ".corthex/stages.json", checks, helper)
        self.assertNotIn("where", result["05-erd"]["checkpoints"][0])
        record["stages"]["05-erd"]["checkpoints"][0]["date"] = "2026-02-30"
        result = SNAPSHOT.read_record(json.dumps(record), "acme-shop", "", ".corthex/stages.json", checks, helper)
        self.assertEqual(result["05-erd"]["state"], "in_progress")
        self.assertEqual(result["05-erd"]["checkpoints"], [])

    def test_one_invalid_stage_does_not_erase_another_record(self):
        raw = {"format": 1, "project": "acme-shop", "stages": {
            "05-erd": {"state": "in_progress", "checkpoints": [], "next": "API", "updated": NOW},
            "06-api": {"state": "invented", "checkpoints": [], "next": "Review", "updated": NOW}}}
        helper = SimpleNamespace(**vars(hub), picture_ids=hub.IdFormat({}))
        checks = []
        result = SNAPSHOT.read_record(json.dumps(raw), "acme-shop", "", ".corthex/stages.json", checks, helper)
        self.assertEqual(result["05-erd"]["state"], "in_progress")
        self.assertNotIn("06-api", result)
        self.assertEqual(checks[-1]["stage"], "06-api")

    def test_repository_status_preserves_other_parts_and_writes_ordered_lf_json(self):
        self.project(parts=["orders", "billing"])
        self.register()
        untouched = self.repo / ".corthex/stages/billing.json"
        self.write(untouched, {"format": 1, "project": "acme-shop", "part": "billing", "stages": {}})
        before = untouched.read_bytes()
        args = hub.parser().parse_args(["status", "acme-shop", "05-erd", "--part", "orders", "--state", "done", "--checkpoint", "Order tables", "--by", "the maintainer", "--date", "2026-11-03", "--repository"])
        project = hub.select_projects(self.home, ["acme-shop"])[0][1]
        entry, target = RECORD.write(project, self.home, args, vars(hub), NOW)
        self.assertEqual(entry["state"], "done")
        self.assertEqual(untouched.read_bytes(), before)
        raw = target.read_bytes()
        self.assertTrue(raw.endswith(b"\n"))
        self.assertNotIn(b"\r", raw)
        self.assertEqual(list(json.loads(raw)), ["format", "project", "part", "stages"])
        self.assertNotIn("where", json.loads(raw)["stages"]["05-erd"]["checkpoints"][0])

    def test_bad_part_paths_are_refused_without_writes(self):
        self.project(parts=["../outside"])
        project = hub.select_projects(self.home, [], self.repo)[0][1]
        args = hub.parser().parse_args(["status", "acme-shop", "05-erd", "--part", "../outside", "--repository"])
        with self.assertRaises(ValueError):
            RECORD.write(project, self.home, args, vars(hub), NOW)
        self.assertFalse((self.repo / ".corthex/outside.json").exists())

    def test_records_writer_never_follows_a_symlink(self):
        self.project()
        project = hub.select_projects(self.home, [], self.repo)[0][1]
        link, outside = self.repo / ".corthex/stages.json", self.base / "outside.json"
        self.write(outside, {"format": 1, "project": "acme-shop", "stages": {}})
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("symlinks are unavailable")
        before = outside.read_bytes()
        args = hub.parser().parse_args(["status", "acme-shop", "05-erd", "--repository"])
        with self.assertRaises(ValueError):
            RECORD.write(project, self.home, args, vars(hub), NOW)
        self.assertEqual(outside.read_bytes(), before)


class FakeClient:
    def __init__(self, answers=()):
        self.answers, self.calls = list(answers), []

    def call(self, method, path, body=None, session=None, write=None):
        self.calls.append((method, path, body, session, write))
        return self.answers.pop(0) if self.answers else HTTP.result("done", answer={"ok": True})


class OutboxTest(HubCase):
    def setUp(self):
        super().setUp()
        self.now = 1800000000.0
        self.box = BOX.Outbox(self.home, "acme-shop", clock=lambda: self.now)

    def make(self, text="Synthetic reply"):
        return self.box.make("reply", "/api/spaces/acme-shop/comments/" + COMMENT + "/replies", SESSION, {"text": text})

    def keep(self, text="Synthetic reply"):
        with self.box.lease() as lease:
            data = self.make(text)
            self.box.save(data, {"failure": "no network"}, lease)
        return data

    def test_retry_keeps_original_id_body_session_and_order(self):
        first = self.keep()
        self.now += 1
        second = self.keep("Second reply")
        client = FakeClient([HTTP.result("failed", failure="HTTP 503", retry=True)])
        with self.box.lease() as lease:
            stats, waiting = self.box.drain(client, lease)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0][2:], (first["body"], SESSION, first["write"]))
        self.assertEqual([row["write"] for row in waiting], [first["write"], second["write"]])
        self.assertEqual(waiting[0]["tries"], 2)
        self.assertEqual(stats["waiting"], 2)
        client = FakeClient()
        with self.box.lease() as lease:
            stats, waiting = self.box.drain(client, lease)
        self.assertEqual([call[4] for call in client.calls], [first["write"], second["write"]])
        self.assertEqual(stats["sent"], 2)
        self.assertEqual(self.box.files(), [])

    def test_millisecond_ties_follow_creation_order_without_changing_time(self):
        made = []
        with self.box.lease() as lease:
            for letter, text in (("z", "first"), ("0", "second")):
                with mock.patch.object(BOX.secrets, "choice", return_value=letter):
                    data = self.make(text)
                self.box.save(data, {"failure": "no network"}, lease)
                made.append(data["made"])
            client = FakeClient()
            self.box.drain(client, lease)
        self.assertEqual(made[0], made[1])
        self.assertEqual([call[2]["text"] for call in client.calls], ["first", "second"])
        self.assertFalse(self.box.order_path.exists())

    def test_list_shows_metadata_without_text_or_network(self):
        data = self.keep("Never print this body")
        client = FakeClient()
        with self.box.lease() as lease:
            stats, waiting = self.box.drain(client, lease, send=False)
        encoded = json.dumps(waiting)
        self.assertNotIn("Never print", encoded)
        self.assertIn(data["write"], encoded)
        self.assertEqual(client.calls, [])
        self.assertEqual(stats["waiting"], 1)

    def test_seven_day_expiry_and_permanent_refusal_are_reported_and_dropped(self):
        old = self.keep()
        self.now += BOX.SEVEN_DAYS
        recent = self.keep("Recent")
        client = FakeClient([HTTP.result("refused", problem={"status": 409, "code": "comment_closed"})])
        with self.box.lease() as lease:
            stats, _ = self.box.drain(client, lease)
        self.assertEqual(stats["dropped"], 2)
        self.assertEqual(client.calls[0][4], recent["write"])
        self.assertEqual(stats["notices"][0], {"write": old["write"], "failure": "expired after 7 days"})
        self.assertEqual(stats["notices"][1]["problem"]["code"], "comment_closed")

    def test_busy_lease_accepts_only_an_unsent_unique_append(self):
        with self.box.lease() as lease:
            with self.assertRaises(BOX.Busy):
                with self.box.lease():
                    self.fail("two owners")
            data = self.make()
            self.box.save(data, {"failure": "another hub is sending"}, None, count_attempt=False)
            self.assertEqual(self.box.load(self.box.files()[0])["tries"], 0)
            lease.renew()
        self.assertFalse(self.box.lease().path.exists())

    def test_stale_takeover_fences_the_old_owner(self):
        old = self.box.lease().__enter__()
        self.now += 121
        with self.box.lease() as replacement:
            with self.assertRaises(BOX.Lost):
                old.renew()
            with self.assertRaises(BOX.Lost):
                self.box.save(self.make(), {"failure": "late"}, old)
            old.__exit__(None, None, None)
            self.assertEqual(replacement.read()["owner"], replacement.owner)

    def test_another_process_cannot_own_the_live_lease(self):
        source = ("import importlib.util,pathlib,sys; "
                  "s=importlib.util.spec_from_file_location('queue',sys.argv[1]); "
                  "m=importlib.util.module_from_spec(s);s.loader.exec_module(m); "
                  "m.Lease(pathlib.Path(sys.argv[2]),'acme-shop').__enter__()")
        # Match the real clock for this subprocess; a forged old test clock
        # must not make its still-held lease look stale to a second process.
        box = BOX.Outbox(self.home, "acme-shop")
        with box.lease():
            result = subprocess.run([sys.executable, "-c", source, BOX.__file__, str(box.root)],
                                    capture_output=True, timeout=15, cwd=str(self.base))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"Busy", result.stderr)

    def test_corrupt_or_redirected_file_is_never_sent(self):
        self.keep()
        target = self.box.files()[0]
        raw = json.loads(target.read_text(encoding="utf8"))
        raw["path"] = "https://example.com/stolen"
        BOX.atomic(target, raw)
        client = FakeClient()
        with self.box.lease() as lease:
            stats, _ = self.box.drain(client, lease)
        self.assertEqual(client.calls, [])
        self.assertEqual(stats["dropped"], 1)
        self.assertEqual(stats["notices"][0]["failure"], "invalid outbox file")

    def test_symlink_queue_file_does_not_read_or_delete_its_target(self):
        outside = self.base / "outside.json"
        self.write(outside, {"private": "synthetic"})
        self.box.folder.mkdir(parents=True)
        link = self.box.folder / "invalid.json"
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("symlinks are unavailable")
        before = outside.read_bytes()
        with self.box.lease() as lease:
            stats, _ = self.box.drain(FakeClient(), lease)
        self.assertEqual(outside.read_bytes(), before)
        self.assertFalse(link.is_symlink())
        self.assertEqual(stats["dropped"], 1)

    def test_removal_clears_crashed_temporary_files_and_preserves_unrelated_files(self):
        self.keep()
        (self.box.folder / ".queue.unique.tmp").write_text("synthetic", encoding="utf8")
        marker = self.box.folder / "user-note.txt"
        marker.write_text("preserve", encoding="utf8")
        with self.box.lease() as lease:
            self.box.clear(lease)
        self.assertEqual(self.box.files(), [])
        self.assertEqual(marker.read_text(encoding="utf8"), "preserve")
        self.assertFalse((self.box.folder / ".queue.unique.tmp").exists())


class CommandOutcomesTest(HubCase):
    def setUp(self):
        super().setUp()
        self.project()
        self.register()
        self.write(self.home / ".corthex/profile.json", {"nexus": {"url": "https://nexus.example.com", "push": ["acme-shop"]}})

    def execute(self, words, client=None, env=None):
        args = hub.parser().parse_args(words)
        client = client or FakeClient()
        rows = CMD.execute(args, self.home, vars(hub), env=env or {}, client_factory=lambda *a, **k: client)
        return args, rows, client

    def test_all_eighteen_commands_exist(self):
        parser = hub.parser()
        actions = next(action for action in parser._actions if hasattr(action, "choices") and isinstance(action.choices, dict))
        self.assertEqual(set(actions.choices), {"snapshot", "status", "build"} | CMD.ANSWERED)
        self.assertEqual(CMD.ANSWERED - CMD.NETWORK, {"can-send"})
        self.assertEqual(len(actions.choices), 19)

    def test_agent_writes_match_paths_bodies_and_new_write_ids(self):
        cases = [
            (["comment", "acme-shop", "--stage", "01-domain", "--quote", "Quoted", "--text", "Comment"], "comment", "/comments", {"text": "Comment", "item": ""}),
            (["reply", "acme-shop", COMMENT, "--text", "Reply"], "reply", "/comments/" + COMMENT + "/replies", {"text": "Reply"}),
            (["answered", "acme-shop", COMMENT], "answered", "/comments/" + COMMENT + "/answered", {}),
            (["decide", "acme-shop", COMMENT, "--link", "https://example.com/decision"], "decision", "/comments/" + COMMENT + "/decisions", {"link": "https://example.com/decision"}),
            (["propose", "acme-shop", "--stage", "05-erd", "--item", "TBL-001", "--reason", "Reason", "--change", "Change"], "proposal", "/proposals", {"items": ["TBL-001"]}),
            (["withdraw", "acme-shop", PROPOSAL], "withdraw-proposal", "/proposals/" + PROPOSAL + "/withdraw", {}),
            (["reflect", "acme-shop", EDIT, "reflected", "--commit", "a" * 40], "report-edit", "/edits/" + EDIT + "/report", {"event": "reflected", "commit": "a" * 40}),
            (["record", "acme-shop", CHECKPOINT, "opened", "--pr", "https://example.com/pr/1"], "report-checkpoint", "/checkpoints/" + CHECKPOINT + "/report", {"event": "opened"}),
        ]
        writes = set()
        for words, request, suffix, expected in cases:
            with self.subTest(command=words[0]):
                args, rows, client = self.execute(words + ["--session", SESSION])
                self.assertEqual(rows[0]["outcome"], "done")
                method, path, body, session, write = client.calls[-1]
                self.assertEqual((method, path, session), ("POST", "/api/spaces/acme-shop" + suffix, SESSION))
                for key, value in expected.items():
                    self.assertEqual(body[key], value)
                self.assertRegex(write, BOX.WRITE)
                writes.add(write)
                self.assertIn(request, BOX.REQUESTS)
        self.assertEqual(len(writes), 8)

    def test_every_write_outcome_has_the_documented_exit_code(self):
        answers = [(HTTP.result("done", answer={"ok": True}), 0, "done"),
                   (HTTP.result("refused", problem={"status": 409, "code": "comment_closed"}), 1, "refused"),
                   (HTTP.result("failed", failure="no network", retry=True), 3, "kept")]
        for answer, code, expected in answers:
            with self.subTest(expected=expected):
                args, rows, _ = self.execute(["reply", "acme-shop", COMMENT, "--text", "Text", "--session", SESSION, "--json"], FakeClient([answer]))
                output = []
                self.assertEqual(CMD.emit(args, rows, SimpleNamespace(say=output.append)), code)
                self.assertEqual(json.loads(output[0])["outcome"], expected)

    def test_no_token_write_is_redacted_and_kept_without_credentials(self):
        token_id, token_secret = "synthetic-client-component", "synthetic-secret-component"
        env = {"CORTHEX_NEXUS_CLIENT_ID": token_id, "CORTHEX_NEXUS_CLIENT_SECRET": token_secret}
        text = "Values " + token_id + " " + token_secret + " person@example.com " + str(self.home)
        _, rows, _ = self.execute(["reply", "acme-shop", COMMENT, "--text", text, "--session", SESSION],
                                  FakeClient([HTTP.result("failed", failure="no service token", retry=True)]), env)
        self.assertEqual(rows[0]["outcome"], "kept")
        files = BOX.Outbox(self.home, "acme-shop").files()
        self.assertEqual(len(files), 1)
        raw = files[0].read_text(encoding="utf8")
        for secret in (token_id, token_secret, "person@example.com", str(self.home)):
            self.assertNotIn(secret, raw)
        self.assertIn("[redacted]", raw)
        self.assertIn("~", raw)

    def test_invalid_cli_inputs_exit_before_contact_or_queue(self):
        invalid = [
            ["reply", "acme-shop", COMMENT, "--text", "Text"],
            ["reply", "acme-shop", PROPOSAL, "--text", "Text", "--session", SESSION],
            ["decide", "acme-shop", COMMENT, "--link", "https://example.com/person%40example.com", "--session", SESSION],
            ["reflect", "acme-shop", EDIT, "reflected", "--session", SESSION],
            ["comment", "acme-shop", "--stage", "01-domain", "--item", "not-a-trace-id", "--text", "Text", "--session", SESSION],
        ]
        for words in invalid:
            with self.subTest(words=words[0]):
                client = FakeClient()
                with self.assertRaises(CMD.CommandLine):
                    self.execute(words, client)
                self.assertEqual(client.calls, [])
        self.assertEqual(BOX.Outbox(self.home, "acme-shop").files(), [])

    def test_comment_takes_any_stage_and_says_what_the_agent_asks(self):
        # 0.3.0: a comment on any of the 13 stages, on the stage as a whole without
        # --item and without --quote, and --asks on the agent's comment or reply.
        self.assertEqual(CMD.STAGE_KEYS, hub.STAGE_KEYS)
        cases = [
            (["comment", "acme-shop", "--stage", "04-functional-spec", "--text", "Whole stage", "--asks", "checkpoint", "--look-first", "SPEC-001"],
             "/comments", {"stage": "04-functional-spec", "item": "", "text": "Whole stage", "asks": "checkpoint", "look_first": "SPEC-001"}),
            (["comment", "acme-shop", "--stage", "02-prd", "--item", "REQ-001", "--text", "On an item"],
             "/comments", {"stage": "02-prd", "item": "REQ-001", "text": "On an item"}),
            (["comment", "acme-shop", "--stage", "05-erd", "--item", "TBL-001", "--text", "Asks", "--asks", "answer"],
             "/comments", {"stage": "05-erd", "item": "TBL-001", "asks": "answer"}),
            (["reply", "acme-shop", COMMENT, "--text", "Recommend B", "--asks", "recommended"],
             "/comments/" + COMMENT + "/replies", {"text": "Recommend B", "asks": "recommended"}),
            (["reply", "acme-shop", COMMENT, "--text", "Done"], "/comments/" + COMMENT + "/replies", {"text": "Done"}),
        ]
        # 0.4.0: a checkpoint request reads the agent to-do first (SPEC-191), here a server's answer with read_at.
        lists = {key: {"total": 0, "entries": []} for key in ("comments", "discrepancies", "reflections", "checkpoints")}
        todo = dict(lists, project="acme-shop", default_commit=None, session=SESSION, read_at="2026-11-13T00:00:00.000Z", waiting_for_user=0, taken=0)
        for words, suffix, expected in cases:
            with self.subTest(words=words):
                first = [HTTP.result("done", answer=todo)] if "checkpoint" in words else []
                _, rows, client = self.execute(words + ["--session", SESSION], FakeClient(first))
                self.assertEqual(rows[0]["outcome"], "done")
                if first:
                    self.assertEqual(client.calls[0][:2], ("GET", "/api/spaces/acme-shop/todo"))
                method, path, body, _, _ = client.calls[-1]
                self.assertEqual((method, path), ("POST", "/api/spaces/acme-shop" + suffix))
                for key, value in expected.items():
                    self.assertEqual(body[key], value)
                self.assertNotIn("quote", body)
                if "asks" not in expected:
                    self.assertNotIn("asks", body)
        refused = [
            ["comment", "acme-shop", "--stage", "02-prd", "--text", "Text", "--asks", "maybe"],
            ["comment", "acme-shop", "--stage", "99-x", "--text", "Text"],
            ["propose", "acme-shop", "--stage", "02-prd", "--item", "REQ-001", "--reason", "Reason", "--change", "Change"],
            ["answered", "acme-shop", COMMENT, "--asks", "answer"],
            ["decide", "acme-shop", COMMENT, "--link", "https://example.com/decision", "--asks", "answer"],
        ]
        for words in refused:
            with self.subTest(words=words):
                client = FakeClient()
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
                    self.execute(words + ["--session", SESSION], client)
                self.assertEqual(caught.exception.code, 2)
                self.assertEqual(client.calls, [])
        self.assertEqual(BOX.Outbox(self.home, "acme-shop").files(), [])

    def test_claims_are_never_queued_and_todo_404_is_empty(self):
        for command in ("claim", "release"):
            _, rows, client = self.execute([command, "acme-shop", COMMENT, "--session", SESSION],
                                           FakeClient([HTTP.result("failed", failure="timeout", retry=True)]))
            self.assertEqual(rows[0]["outcome"], "failed")
            self.assertEqual(client.calls[-1][0], "POST" if command == "claim" else "DELETE")
            self.assertIsNone(client.calls[-1][4])
            self.assertEqual(BOX.Outbox(self.home, "acme-shop").files(), [])
        _, rows, _ = self.execute(["todo", "acme-shop"], FakeClient([HTTP.result("refused", problem={"status": 404, "code": "space_not_found"})]))
        self.assertEqual(rows[0]["outcome"], "done")
        self.assertEqual(rows[0]["answer"]["comments"]["entries"], [])

    def test_push_dry_run_does_not_contact_server_or_outbox(self):
        box = BOX.Outbox(self.home, "acme-shop")
        with box.lease() as lease:
            box.save(box.make("reply", "/api/spaces/acme-shop/comments/" + COMMENT + "/replies", SESSION, {"text": "Old"}), {"failure": "no network"}, lease)
        before = box.files()[0].read_bytes()
        _, rows, client = self.execute(["push", "--dry-run"])
        self.assertEqual(client.calls, [])
        self.assertEqual(box.files()[0].read_bytes(), before)
        self.assertEqual(rows[0]["answer"]["held_commit"], "checked when sent")

    def test_remove_preview_uses_get_and_only_real_removal_clears_queue(self):
        box = BOX.Outbox(self.home, "acme-shop")
        with box.lease() as lease:
            box.save(box.make("reply", "/api/spaces/acme-shop/comments/" + COMMENT + "/replies", SESSION, {"text": "Old"}), {"failure": "no network"}, lease)
        _, rows, client = self.execute(["remove", "acme-shop", "--dry-run"])
        self.assertEqual(client.calls[0][0:2], ("GET", "/api/snapshots/acme-shop/removal"))
        self.assertTrue(box.files())
        _, rows, client = self.execute(["remove", "acme-shop"], FakeClient([HTTP.result("refused", problem={"status": 404, "code": "project_not_found"})]))
        self.assertEqual(client.calls[0][0], "DELETE")
        self.assertEqual(rows[0]["outcome"], "done")
        self.assertIn("next_push", rows[0]["answer"])
        self.assertEqual(box.files(), [])

    def test_local_commands_have_one_json_envelope_per_project(self):
        for words in (["snapshot", "acme-shop", "--json"],
                      ["status", "acme-shop", "05-erd", "--state", "in_progress", "--json"],
                      ["build", "--json"]):
            with self.subTest(command=words[0]):
                result = subprocess.run([sys.executable, str(SCRIPT), "--home", str(self.home)] + list(words),
                                        cwd=str(self.base), capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf8"))
                rows = [json.loads(line) for line in result.stdout.decode("utf8").splitlines()]
                self.assertEqual(len(rows), 1)
                self.assertEqual((rows[0]["command"], rows[0]["project"], rows[0]["outcome"]), (words[0], "acme-shop", "done"))
                self.assertEqual(set(rows[0]), {"command", "project", "outcome", "answer", "problem", "failure", "outbox", "remarks"})

    def test_local_json_errors_do_not_crash_the_error_handler(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = hub.main(["--home", str(self.home), "status", "acme-shop", "05-erd", "--part", "unknown", "--repository", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["outcome"], "failed")

    def test_response_keys_and_parser_errors_cannot_print_token_components(self):
        token = "SYNTHETIC_COMPONENT_TO_REDACT"
        args, rows, _ = self.execute(["todo", "acme-shop", "--json"], FakeClient([HTTP.result("done", answer={token: {"nested": token}})]),
                                     {"CORTHEX_NEXUS_CLIENT_SECRET": token})
        output = []
        CMD.emit(args, rows, SimpleNamespace(say=output.append))
        self.assertNotIn(token, "".join(output))
        error = io.StringIO()
        with mock.patch.dict(os.environ, {"CORTHEX_NEXUS_CLIENT_SECRET": token}), contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as caught:
            hub.main(["comment", "acme-shop", "--stage", token, "--text", "Text"])
        self.assertEqual(caught.exception.code, 2)
        self.assertNotIn(token, error.getvalue())

    def test_current_write_is_durable_before_send_and_survives_lease_loss(self):
        box = BOX.Outbox(self.home, "acme-shop")
        replacement = []

        class TakeoverClient(FakeClient):
            def call(self, method, path, body=None, session=None, write=None):
                files = box.files()
                self_data = box.load(files[0])
                if self_data["write"] != write:
                    raise AssertionError("the original write must be durable before HTTP")
                os.utime(box.lease().path, (time.time() - 121, time.time() - 121))
                owner = box.lease().__enter__()
                replacement.append(owner)
                with owner.owned():
                    BOX.atomic(files[0], dict(self_data, tries=7, failure="new holder state"))
                return super().call(method, path, body, session, write)

        client = TakeoverClient([HTTP.result("failed", failure="timeout", retry=True)])
        try:
            _, rows, _ = self.execute(["reply", "acme-shop", COMMENT, "--text", "Keep original", "--session", SESSION], client)
            self.assertEqual(rows[0]["outcome"], "kept")
            held = box.load(box.files()[0])
            self.assertEqual((held["write"], held["tries"], held["failure"]), (client.calls[0][4], 7, "new holder state"))
        finally:
            for lease in replacement:
                lease.__exit__(None, None, None)

    def test_failed_persistence_gives_one_redacted_recovery_copy_only_to_output(self):
        secret = "synthetic-component-for-recovery"
        args = hub.parser().parse_args(["reply", "acme-shop", COMMENT, "--text", "Recover " + secret, "--session", SESSION, "--json"])
        with mock.patch.object(BOX, "atomic", side_effect=PermissionError("unavailable")):
            rows = CMD.execute(args, self.home, vars(hub), env={"CORTHEX_NEXUS_CLIENT_SECRET": secret}, client_factory=lambda *a, **k: FakeClient())
        recovery = rows[0]["recovery"]
        self.assertEqual(rows[0]["outcome"], "failed")
        self.assertRegex(recovery["write"], BOX.WRITE)
        self.assertEqual(recovery["body"]["text"], "Recover [redacted]")
        output = []
        self.assertEqual(CMD.emit(args, rows, SimpleNamespace(say=output.append)), 1)
        self.assertEqual(len(output), 1)
        self.assertEqual(output[0].count("Recover [redacted]"), 1)
        self.assertNotIn(secret, output[0])
        self.assertEqual(BOX.Outbox(self.home, "acme-shop").files(), [])

    def test_native_lease_unlink_failure_keeps_one_known_outcome_without_replay(self):
        original = Path.unlink

        def failure(path, *args, **kwargs):
            if path.name == "acme-shop.lock":
                raise PermissionError("synthetic lease cleanup failure")
            return original(path, *args, **kwargs)

        for words in (["reply", "acme-shop", COMMENT, "--text", "Accepted", "--session", SESSION], ["todo", "acme-shop"]):
            box = BOX.Outbox(self.home, "acme-shop")
            if box.lease().path.exists():
                box.lease().path.unlink()
            with mock.patch.object(Path, "unlink", failure):
                args, rows, client = self.execute(words + ["--json"])
            output = []
            self.assertEqual(CMD.emit(args, rows, SimpleNamespace(say=output.append)), 0)
            self.assertEqual(len(output), 1)
            self.assertEqual(json.loads(output[0])["outcome"], "done")
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(box.files(), [])
            self.assertNotIn("recovery", rows[0])

    def test_text_file_utf8_and_source_file_are_validated_before_send(self):
        bad = self.base / "bad.txt"
        bad.write_bytes(b"\xff")
        with self.assertRaises(CMD.CommandLine):
            self.execute(["reply", "acme-shop", COMMENT, "--text-file", str(bad), "--session", SESSION])
        source = self.base / "source.sql"
        source.write_text("CREATE TABLE example (id INT);\n", encoding="utf8")
        _, rows, client = self.execute(["propose", "acme-shop", "--stage", "05-erd", "--item", "TBL-001", "--reason", "Reason", "--change", "Change", "--source-file", str(source), "--session", SESSION])
        self.assertEqual(client.calls[0][2]["source_text"], source.read_text(encoding="utf8"))

    def test_a_concurrent_append_cannot_bypass_the_prequeued_fresh_write(self):
        box = BOX.Outbox(self.home, "acme-shop")
        with box.lease() as lease:
            old = box.make("reply", "/api/spaces/acme-shop/comments/" + COMMENT + "/replies", SESSION, {"text": "Old"})
            box.save(old, {"failure": "no network"}, lease)
        parent = self

        class AppendingClient(FakeClient):
            def call(self, *args, **kwargs):
                if not self.calls:
                    parent.execute(["reply", "acme-shop", COMMENT, "--text", "Concurrent", "--session", SESSION])
                return super().call(*args, **kwargs)

        _, rows, client = self.execute(["reply", "acme-shop", COMMENT, "--text", "Fresh", "--session", SESSION], AppendingClient())
        self.assertEqual([call[2]["text"] for call in client.calls], ["Old", "Fresh"])
        self.assertEqual(rows[0]["outcome"], "done")
        self.assertEqual(rows[0]["outbox"]["waiting"], 1)
        self.assertEqual({box.load(p)["body"]["text"] for p in box.files()}, {"Concurrent"})

    def test_all_agent_write_commands_handle_done_refused_kept_and_invalid_cli(self):
        commands = [["comment", "acme-shop", "--stage", "01-domain", "--quote", "Quote", "--text", "Text"],
                    ["reply", "acme-shop", COMMENT, "--text", "Text"], ["answered", "acme-shop", COMMENT],
                    ["decide", "acme-shop", COMMENT, "--link", "https://example.com/decision"],
                    ["propose", "acme-shop", "--stage", "05-erd", "--item", "TBL-001", "--reason", "Reason", "--change", "Change"],
                    ["withdraw", "acme-shop", PROPOSAL], ["reflect", "acme-shop", EDIT, "needs-user"],
                    ["record", "acme-shop", CHECKPOINT, "closed", "--pr", "https://example.com/pr/1"]]
        for words in commands:
            for response, expected in ((HTTP.result("done", answer={"ok": True}), "done"),
                                       (HTTP.result("refused", problem={"status": 400, "code": "invalid_request"}), "refused"),
                                       (HTTP.result("failed", failure="no network", retry=True), "kept")):
                with self.subTest(command=words[0], outcome=expected):
                    with BOX.Outbox(self.home, "acme-shop").lease() as lease:
                        BOX.Outbox(self.home, "acme-shop").clear(lease)
                    _, rows, _ = self.execute(words + ["--session", SESSION], FakeClient([response]))
                    self.assertEqual(rows[0]["outcome"], expected)
            with self.subTest(command=words[0], outcome="invalid CLI"), self.assertRaises(CMD.CommandLine):
                self.execute(words)
            with self.subTest(command=words[0], outcome="failed persistence"):
                with BOX.Outbox(self.home, "acme-shop").lease() as lease:
                    BOX.Outbox(self.home, "acme-shop").clear(lease)
                output = io.StringIO()
                with mock.patch.dict(os.environ, {"CORTHEX_NEXUS_CLIENT_ID": "", "CORTHEX_NEXUS_CLIENT_SECRET": ""}), \
                     mock.patch.object(BOX, "atomic", side_effect=PermissionError("outbox unavailable")), contextlib.redirect_stdout(output):
                    code = hub.main(["--home", str(self.home), "--json"] + words + ["--session", SESSION])
                self.assertEqual(code, 1)
                self.assertEqual(json.loads(output.getvalue())["outcome"], "failed")


class AncestryTest(GitSourcesFixture):
    def test_same_descendant_ancestor_diverged_and_missing_commits(self):
        project = hub.select_projects(self.home, ["acme-shop"])[0][1]
        snapshot = self.snapshot()
        self.assertIsNone(CMD.commit_replacement(snapshot, {"default_commit": None}, project, False, H))
        self.assertIsNone(CMD.commit_replacement(snapshot, {"default_commit": self.original}, project, False, H))
        self.assertNotIn("replaces", snapshot)
        self.write(self.repo / "another.txt", "child")
        child = self.commit("child, with the same commit time")
        self.git("update-ref", "refs/remotes/origin/main", child)
        snapshot = self.snapshot()
        self.assertIsNone(CMD.commit_replacement(snapshot, {"default_commit": self.original}, project, False, H))
        self.assertEqual(snapshot["replaces"], self.original)
        self.assertIn("behind", CMD.commit_replacement({"repos": {".": {"default": {"commit": self.original}}}}, {"default_commit": child}, project, True, H))
        self.git("checkout", "-b", "rewritten", self.original)
        self.write(self.repo / "alternative.txt", "alternative")
        diverged = self.commit("alternative, with the same time")
        snapshot = {"repos": {".": {"default": {"commit": diverged}}}}
        refusal = CMD.commit_replacement(snapshot, {"default_commit": child}, project, False, H)
        self.assertIn(child, refusal)
        self.assertIn(diverged, refusal)
        self.assertIsNone(CMD.commit_replacement(snapshot, {"default_commit": child}, project, True, H))
        self.assertEqual(snapshot["replaces"], child)
        self.assertIn("not in this checkout", CMD.commit_replacement(snapshot, {"default_commit": "f" * 40}, project, True, H))
        self.assertIn("no default branch", CMD.commit_replacement({"repos": {}}, {"default_commit": child}, project, True, H))


class Peer(http.server.BaseHTTPRequestHandler):
    mode, status, redirect, received = "json", 200, "", []

    def do_GET(self):
        type(self).received.append({"path": self.path, "headers": dict(self.headers)})
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        if type(self).redirect:
            self.send_header("Location", type(self).redirect)
        body = json.dumps({"status": type(self).status, "code": "access_missing"} if type(self).status == 403 else {"ok": True}).encode("utf8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            for byte in body if type(self).mode == "trickle" else [body]:
                self.wfile.write(bytes([byte]) if isinstance(byte, int) else byte)
                self.wfile.flush()
                if type(self).mode == "trickle":
                    time.sleep(0.04)
        except (OSError, ValueError):
            pass

    def log_message(self, *args):
        pass


class TransportTest(unittest.TestCase):
    def setUp(self):
        Peer.mode, Peer.status, Peer.redirect, Peer.received = "json", 200, "", []
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Peer)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_headers_and_quoted_write_id_only_reach_configured_peer(self):
        client = HTTP.Client(self.base, {"CORTHEX_NEXUS_CLIENT_ID": "synthetic-id", "CORTHEX_NEXUS_CLIENT_SECRET": "synthetic-secret"})
        write = "nw_" + "a" * 12
        answer = client.call("GET", "/api/check", session=SESSION, write=write)
        self.assertEqual(answer["outcome"], "done")
        headers = {key.lower(): value for key, value in Peer.received[0]["headers"].items()}
        self.assertEqual(headers["idempotency-key"], '"' + write + '"')
        self.assertEqual(headers["nexus-session"], SESSION)
        self.assertEqual(headers["cf-access-client-id"], "synthetic-id")
        self.assertNotIn("synthetic-id", repr(client))

    def test_redirect_is_not_followed_and_access_failure_is_retryable(self):
        Peer.status, Peer.redirect = 302, self.base + "/forbidden"
        result = HTTP.Client(self.base, {}).call("GET", "/api/redirect")
        self.assertEqual(result["failure"], "refused token")
        self.assertTrue(result["retry"])
        self.assertEqual(len(Peer.received), 1)
        Peer.status, Peer.redirect = 403, ""
        result = HTTP.Client(self.base, {}).call("GET", "/api/access")
        self.assertEqual(result["problem"]["code"], "access_missing")
        self.assertTrue(result["retry"])

    def test_missing_token_and_unsafe_urls_or_paths_do_not_contact_network(self):
        result = HTTP.Client("https://nexus.example.com", {}).call("GET", "/api/check")
        self.assertEqual((result["failure"], result["retry"]), ("no service token", True))
        for base in ("http://example.com", "https://user:password@example.com", "https://example.com/?query", "https://example.com/#fragment", "https://example.com:invalid"):
            with self.subTest(base=base), self.assertRaises(ValueError):
                HTTP.Client(base, {})
        client = HTTP.Client(self.base, {})
        for path in ("//example.com/api/", "/api/../other", "/api/%2e%2e/other", "/api/a?token"):
            with self.assertRaises(ValueError):
                client.call("GET", path)
        self.assertEqual(Peer.received, [])

    def test_deadline_bounds_a_body_that_keeps_the_socket_busy(self):
        Peer.mode = "trickle"
        start = time.monotonic()
        result = HTTP.Client(self.base, {}, timeout=0.15).call("GET", "/api/slow")
        elapsed = time.monotonic() - start
        self.assertEqual((result["failure"], result["retry"]), ("timeout", True))
        self.assertLess(elapsed, 1.5)

    def test_cancelled_dns_lookup_cannot_later_send_headers(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        original = HTTP.socket.getaddrinfo

        def delayed(*args, **kwargs):
            entered.set()
            release.wait(2)
            try:
                return original(*args, **kwargs)
            finally:
                finished.set()

        with mock.patch.object(HTTP.socket, "getaddrinfo", delayed):
            # Leave room for the platform's first SSL/context initialization
            # before entering DNS; the DNS gate itself remains blocked.
            result = HTTP.Client(self.base, {}, timeout=0.5).call("GET", "/api/late")
            self.assertTrue(entered.is_set())
            self.assertEqual(result["failure"], "timeout")
            release.set()
            self.assertTrue(finished.wait(2))
            time.sleep(0.05)
        self.assertEqual(Peer.received, [])

    def test_https_handler_uses_the_supported_context_argument(self):
        handler = HTTP.DeadlineHTTPS(HTTP.Deadline())
        with mock.patch.object(handler, "do_open", return_value="opened") as opened:
            self.assertEqual(handler.https_open(HTTP.urllib.request.Request("https://example.com")), "opened")
        self.assertEqual(set(opened.call_args[1]), {"context"})


if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
