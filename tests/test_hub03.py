"""corthex-hub/0.3, NEXUS v3's TASK-428 to TASK-430: the sources of stages 03, 08 and 09, and the format a push sends.

TASK-428 (SPEC-006, SPEC-008, SPEC-009, API-242): one picture per user flow, screen definition and mockup page, with its
part and key and the file's whole text as source.text, no translation, and the mockup page that stage 09's `page` names.
TASK-429 (SPEC-001, SPEC-005, API-242, API-243): 0.3 only to a server whose held-commit answer lists it, a commit held in
0.2 sent again in 0.3 once, and a budget within the server's 8 MiB. TASK-430 (SPEC-014): the versions.

Every HTTP peer is synthetic and on this device, and nothing is fetched. The repositories are synthetic too, except in
ProductTreeTest, which reads corthex-nexus's own tree from a local clone that CORTHEX_NEXUS_CHECKOUT names and is
skipped without one. The answers of API-242 and API-243 are the examples of the NEXUS v3 contract (api/openapi.yaml of
kodonghui/corthex-nexus at f557726), copied here.
"""
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_hub import NOW, SCRIPT, TEMPLATES, hub, output_blocks
from test_hub02 import GitSourcesFixture
from test_hub_revision import TOKEN, RevisionCase, problem

FORMATS = hub.companion("snapshot03")
OLD, NEW = "corthex-hub/0.2", "corthex-hub/0.3"
TEXT_STAGES = ("03-user-flow", "08-screen-states", "09-mockup")
MIB = 1024 * 1024

FLOW = """# FL-{n} {title}

Goal: {title}.

```mermaid
flowchart TD
  A(["Start<br/>REQ-001"]) e1@--> B["{title}<br/>REQ-001"]
  B e2@--> Z(["End"])
```
"""
SCREEN = """# SCR-{n} {title}

Path: `/{path}`. Flows: FL-001.

## States

| State | What the user sees | From responses |
| --- | --- | --- |
| SCR-{n}#normal | The {path} list. | API-001#200 |
| SCR-{n}#empty | No {path} yet. | API-001#200 |
"""
PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Shop mockup</title>
<style>:root {{ --brand: #0f62fe; }} body {{ color: var(--brand); }}</style></head>
<body><main>{body}</main><script>document.title = "Shop";</script></body>
</html>
"""


def size(snapshot):
    return len(hub.dump(snapshot, compact=True).encode("utf-8"))


class SourcesFixture(GitSourcesFixture):
    """The 0.2 fixture's repository with user flows, screen definitions and a mockup page beside their listings,
    translations and other files, laid out as corthex-nexus lays them out."""

    PAGE_SETTING = "design/mockup/shop.html"

    def setUp(self):
        super().setUp()
        self.settings_with(page=self.PAGE_SETTING)
        flows = self.repo / "docs/03-user-flow"
        self.write(flows / "README.md", "# User flows\n\n| Flow | Goal |\n| --- | --- |\n"
                   "| [FL-001 Sign up](FL-001-sign-up.md) | Sign up |\n| [FL-002 Check out](FL-002-check-out.md) | Pay |\n")
        self.write(flows / "README.ko.md", "# 사용자 흐름\n\n| 흐름 | 목표 |\n| --- | --- |\n| [FL-001 가입](FL-001-sign-up.md) | 가입 |\n")
        self.write(flows / "FL-001-sign-up.md", FLOW.format(n="001", title="Sign up"))
        self.write(flows / "FL-001-sign-up.ko.md", FLOW.format(n="001", title="가입"))
        self.write(flows / "FL-002-check-out.md", FLOW.format(n="002", title="Check out"))
        self.write(flows / "notes.md", "# Notes\n\nOpen questions about the flows; REQ-001 is mentioned.\n")
        screens = self.repo / "docs/08-screens"
        self.write(screens / "README.md", "# Screens\n\n| Screen | States |\n| --- | --- |\n| [SCR-001 Orders](SCR-001.md) | normal, empty |\n")
        self.write(screens / "SCR-001.md", SCREEN.format(n="001", title="Orders", path="orders"))
        self.write(screens / "SCR-001.ko.md", SCREEN.format(n="001", title="주문", path="orders"))
        self.write(screens / "SCR-002.md", SCREEN.format(n="002", title="Cart", path="cart"))
        self.write(screens / "wireframes.html", "<!doctype html><title>Wireframes</title><p>SCR-001</p>\n")
        self.write(self.repo / "design/base.tokens.json", '{"brand": {"$value": "#0f62fe", "$type": "color"}}\n')
        self.write(self.repo / "design/mockup/shop.html", PAGE.format(body="Orders, cart and checkout"))
        self.write(self.repo / "design/mockup/shop.ko.html", PAGE.format(body="주문, 장바구니, 결제"))
        self.head = self.commit("flows, screens and the mockup page")
        self.git("update-ref", "refs/remotes/origin/main", self.head)

    def settings_with(self, page):
        self.project(stages={"01-domain": {"source": "docs/01-domain/"}, "05-erd": {"source": "db/schema.sql"},
                             "07-sitemap": {"source": "docs/07-sitemap/"},
                             "09-mockup": {"source": "design/base.tokens.json", "page": page}})

    def make(self, schema=NEW):
        ((_, project, reason),) = hub.select_projects(self.home, [], self.repo)
        self.assertIsNotNone(project, reason)
        return hub.make_snapshot(project, hub.load_status(self.home, project.name), NOW, home=self.home, schema=schema)

    def texts(self, snapshot):
        return [p for p in snapshot["pictures"] if p["stage"] in TEXT_STAGES]

    def keys(self, snapshot):
        return [(p["stage"], p["key"]) for p in self.texts(snapshot)]

    def committed(self, rel):
        return self.git("show", self.head + ":" + rel).replace("\r\n", "\n") + "\n"


class Snapshot03Test(SourcesFixture):
    """TASK-428: what a 0.3 snapshot carries (SPEC-006, SPEC-008, SPEC-009, API-242's Snapshot)."""

    EXPECTED = [("03-user-flow", "docs/03-user-flow/FL-001-sign-up.md"), ("03-user-flow", "docs/03-user-flow/FL-002-check-out.md"),
                ("08-screen-states", "docs/08-screens/SCR-001.md"), ("08-screen-states", "docs/08-screens/SCR-002.md"),
                ("09-mockup", "design/mockup/shop.html")]

    def test_one_picture_per_flow_screen_and_page_with_the_files_whole_text(self):
        snapshot = self.make()
        self.assertEqual((snapshot["schema"], snapshot["generator"]), (NEW, "corthex-nexus 0.6.0"))
        self.assertEqual(self.keys(snapshot), self.EXPECTED)
        for picture in self.texts(snapshot):
            with self.subTest(key=picture["key"]):
                self.assertEqual(set(picture), {"part", "stage", "key", "commit", "time", "source"})
                self.assertEqual((picture["part"], picture["commit"]), ("", self.head))
                self.assertEqual(picture["time"], snapshot["repos"]["."]["default"]["time"])
                self.assertEqual(picture["source"], {"text": (self.repo / picture["key"]).read_text(encoding="utf8")})
        # No translation copy, listing, other format or file that defines no flow.
        sent = " ".join(key for _, key in self.keys(snapshot))
        for name in (".ko.", "README", "notes.md", "wireframes", "base.tokens"):
            self.assertNotIn(name, sent)
        # The 0.2 pictures stay as they are, before the new ones.
        self.assertEqual([p["stage"] for p in snapshot["pictures"]][:3], ["01-domain", "05-erd", "07-sitemap"])
        self.assertTrue(all("key" not in p for p in snapshot["pictures"][:3]))
        self.assertEqual(snapshot["left_out"], [])
        self.assertLessEqual(size(snapshot), FORMATS.MAX_SNAPSHOT_BYTES)

    def test_a_02_snapshot_carries_none_of_them(self):
        snapshot = self.make(OLD)
        self.assertEqual(snapshot["schema"], OLD)
        self.assertEqual([p["stage"] for p in snapshot["pictures"]], ["01-domain", "05-erd", "07-sitemap"])
        self.assertEqual(snapshot, dict(self.snapshot(), generated_at=snapshot["generated_at"]))
        self.assertFalse(self.found(snapshot, "mockup-page-missing"))

    def test_the_text_comes_from_the_fetched_default_commit(self):
        self.write(self.repo / "docs/03-user-flow/FL-001-sign-up.md", FLOW.format(n="001", title="Uncommitted"))
        self.write(self.repo / "docs/03-user-flow/FL-003-later.md", FLOW.format(n="003", title="Later"))
        snapshot = self.make()
        flow = next(p for p in self.texts(snapshot) if p["key"].endswith("FL-001-sign-up.md"))
        self.assertEqual(flow["source"]["text"], FLOW.format(n="001", title="Sign up"))
        self.assertEqual(self.keys(snapshot), self.EXPECTED)

    def test_the_stage_skills_templates_are_sent(self):
        for path, skill, stage, block in TEMPLATES:
            if stage in ("03-user-flow", "08-screen-states"):
                self.write(self.repo / path, output_blocks(skill, stage)[block])
        self.head = self.commit("templates")
        self.git("update-ref", "refs/remotes/origin/main", self.head)
        keys = self.keys(self.make())
        self.assertIn(("03-user-flow", "docs/03-user-flow/FL-001.md"), keys)
        self.assertIn(("08-screen-states", "docs/08-screens/SCR-002.md"), keys)

    def test_a_project_of_its_own_id_formats(self):
        self.write(self.repo / "docs/03-user-flow/UF-07-returns.md", FLOW.format(n="007", title="Returns").replace("# FL-007", "# UF-07"))
        self.head = self.commit("a flow numbered by the project's own format")
        self.git("update-ref", "refs/remotes/origin/main", self.head)
        self.project(stages={"09-mockup": {"page": self.PAGE_SETTING}}, ids={"flow": {"prefix": ["FL", "UF"], "digits": 3}})
        self.assertIn(("03-user-flow", "docs/03-user-flow/UF-07-returns.md"), self.keys(self.make()))

    def test_parts_follow_the_02_rule(self):
        self.project(parts=["shop"], stages={"09-mockup": {"page": self.PAGE_SETTING}})
        snapshot = self.make()
        parts = {p["key"]: p["part"] for p in self.texts(snapshot)}
        self.assertEqual(parts["design/mockup/shop.html"], "shop")
        self.assertEqual(parts["docs/03-user-flow/FL-001-sign-up.md"], "")
        unknown = [c["message"] for c in self.found(snapshot, "part-unknown") if c["stage"] in TEXT_STAGES]
        self.assertEqual(len(unknown), 4)
        self.assertIn("docs/08-screens/SCR-002.md: document belongs to no declared part", unknown)

    def test_the_mockup_page_setting(self):
        cases = {
            "a folder of pages": ("design/mockup/", ["design/mockup/shop.html"], None),
            "a page that is not there": ("design/mockup/none.html", [], "mockup-page-missing"),
            "a path that leaves the repository": ("../shop.html", [], "mockup-page-invalid"),
            "an absolute path": ("C:/shop.html", [], "mockup-page-invalid"),
            "not a path": (7, [], "mockup-page-invalid"),
            "an empty path": ("  ", [], "mockup-page-invalid"),
        }
        for name, (page, keys, rule) in cases.items():
            with self.subTest(name):
                self.project(stages={"09-mockup": {"source": "design/base.tokens.json", "page": page}})
                snapshot = self.make()
                self.assertEqual([key for stage, key in self.keys(snapshot) if stage == "09-mockup"], keys)
                if rule:
                    self.assertEqual(len(self.found(snapshot, rule)), 1)
        self.project(stages={"09-mockup": {"source": "design/base.tokens.json"}})
        snapshot = self.make()
        self.assertEqual([key for stage, key in self.keys(snapshot) if stage == "09-mockup"], [], "no page, no mockup")
        self.assertFalse(self.found(snapshot, "mockup-page-missing") + self.found(snapshot, "mockup-page-invalid"))

    def test_a_source_in_another_repository_or_a_skipped_stage(self):
        self.project(repos={"design": "https://example.com/team/shop-design"},
                     stages={"03-user-flow": {"skip": True}, "08-screen-states": {"source": "design:screens/"},
                             "09-mockup": {"page": "design:mockup/shop.html"}})
        snapshot = self.make()
        self.assertEqual(self.texts(snapshot), [])
        self.assertEqual(snapshot["left_out"], [{"part": "", "stage": "08-screen-states", "why": "other-repository"},
                                                {"part": "", "stage": "09-mockup", "why": "other-repository"}])

    def test_a_file_over_1_mib_is_left_out_and_counted(self):
        self.write(self.repo / "docs/03-user-flow/FL-009-big.md", FLOW.format(n="009", title="Big") + "x" * MIB)
        self.head = self.commit("a flow over 1 MiB")
        self.git("update-ref", "refs/remotes/origin/main", self.head)
        snapshot = self.make()
        self.assertNotIn(("03-user-flow", "docs/03-user-flow/FL-009-big.md"), self.keys(snapshot))
        self.assertEqual(snapshot["left_out"], [{"part": "", "stage": "03-user-flow", "why": "size", "key": "docs/03-user-flow/FL-009-big.md"}])
        (partial,) = [c for c in self.found(snapshot, "picture-partial") if "FL-009" in c["message"]]
        self.assertEqual(partial["level"], "warn")

    def test_the_text_is_redacted_as_every_other_string(self):
        self.write(self.repo / "docs/08-screens/SCR-003.md", SCREEN.format(n="003", title="Help", path="help") +
                   "\nWrite to help@example.com for a refund.\n")
        self.head = self.commit("a screen with an email address")
        self.git("update-ref", "refs/remotes/origin/main", self.head)
        text = next(p for p in self.texts(self.make()) if p["key"].endswith("SCR-003.md"))["source"]["text"]
        self.assertIn("Write to [redacted] for a refund.", text)
        self.assertNotIn("help@example.com", text)


class Budget03Test(SourcesFixture):
    """TASK-429: a budget within the server's 8 MiB; whole pictures go first, largest first (SPEC-001)."""

    def test_the_budget_is_within_the_servers_8_mib(self):
        self.assertEqual(hub.MAX_SNAPSHOT_BYTES, 1000 * 1000, "a server of before takes 1 MiB, so 0.2 keeps its limit")
        self.assertEqual(FORMATS.budget(OLD, hub.MAX_SNAPSHOT_BYTES), hub.MAX_SNAPSHOT_BYTES)
        self.assertEqual(FORMATS.budget(NEW, hub.MAX_SNAPSHOT_BYTES), 8 * 1000 * 1000)
        self.assertLess(FORMATS.budget(NEW, hub.MAX_SNAPSHOT_BYTES) + 200, 8 * MIB, "room for replaces")
        with self.assertRaises(ValueError):
            FORMATS.budget("corthex-hub/0.4", hub.MAX_SNAPSHOT_BYTES)

    def test_a_snapshot_over_the_02_limit_is_whole_in_03(self):
        # A mockup page of 0.9 MiB and five screens: more than 0.2 carries, well within 0.3.
        self.write(self.repo / "design/mockup/shop.html", PAGE.format(body="<p>Product</p>" * (int(0.9 * MIB) // 14)))
        for n in range(3, 8):
            self.write(self.repo / ("docs/08-screens/SCR-00%d.md" % n), SCREEN.format(n="00%d" % n, title="Screen", path="s%d" % n) + "y" * 30000)
        self.head = self.commit("a large mockup page")
        self.git("update-ref", "refs/remotes/origin/main", self.head)
        snapshot = self.make()
        self.assertGreater(size(snapshot), hub.MAX_SNAPSHOT_BYTES)
        self.assertLessEqual(size(snapshot), FORMATS.MAX_SNAPSHOT_BYTES)
        self.assertEqual((snapshot["left_out"], snapshot["truncated"]), ([], False))
        self.assertEqual(len(self.texts(snapshot)), 10)

    def test_the_largest_whole_picture_goes_first_named_by_its_key(self):
        self.write(self.repo / "design/mockup/shop.html", PAGE.format(body="<p>Product</p>" * 4000))
        self.head = self.commit("a larger mockup page")
        self.git("update-ref", "refs/remotes/origin/main", self.head)
        whole = size(self.make())
        with mock.patch.object(FORMATS, "MAX_SNAPSHOT_BYTES", whole - 1000):
            snapshot = self.make()
        self.assertNotIn("design/mockup/shop.html", [p.get("key") for p in snapshot["pictures"]])
        self.assertEqual(len(snapshot["pictures"]), 3 + 4)
        self.assertEqual(snapshot["left_out"], [{"part": "", "stage": "09-mockup", "why": "size", "key": "design/mockup/shop.html"}])
        (check,) = self.found(snapshot, "picture-left-out")
        self.assertEqual(check["message"], "a whole picture is left out to keep the snapshot under its size limit")
        self.assertFalse(snapshot["truncated"])


class SnapshotCommandTest(SourcesFixture):
    """The snapshot command makes either format; a saved 0.3 snapshot is read back (TASK-431 uses --format)."""

    def run_hub(self, *words):
        env = {key: value for key, value in os.environ.items() if not key.startswith(("CORTHEX_NEXUS_", "NEXUS_DEV_"))}
        return subprocess.run([sys.executable, str(SCRIPT), "--home", str(self.home)] + list(words), cwd=str(self.repo),
                              env=env, capture_output=True, text=True, encoding="utf8", timeout=120)

    def test_snapshot_print_in_each_format(self):
        for words, schema, count in (([], OLD, 0), (["--format", OLD], OLD, 0), (["--format", NEW], NEW, 5)):
            with self.subTest(words=words):
                result = self.run_hub("snapshot", "--path", str(self.repo), "--print", *words)
                self.assertEqual(result.returncode, 0, result.stderr)
                snapshot = json.loads(result.stdout)
                self.assertEqual((snapshot["schema"], len(self.texts(snapshot))), (schema, count))
        result = self.run_hub("snapshot", "--path", str(self.repo), "--print", "--format", "corthex-hub/0.4")
        self.assertEqual((result.returncode, result.stdout), (2, ""))
        self.assertIn("invalid choice", result.stderr)

    def test_a_saved_03_snapshot_is_read_back(self):
        self.register()
        result = self.run_hub("snapshot", "acme-shop", "--format", NEW)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(hub.stored_snapshots(self.home)["acme-shop"]["schema"], NEW)
        result = self.run_hub("build", "--no-scan")
        self.assertEqual(result.returncode, 0, result.stderr)
        page = (self.home / ".corthex/hub/index.html").read_text(encoding="utf8")
        self.assertIn('"schema":"corthex-hub/0.3"', page)
        self.assertNotIn("<script>document.title", page, "the page's text stays escaped inside the data block")


class FormatChoiceTest(unittest.TestCase):
    """TASK-429: the format comes from the held-commit answer (API-243's formats and format)."""

    def test_the_newest_format_that_the_answer_lists_and_the_hub_makes(self):
        cases = [(None, OLD), ({}, OLD), ({"project": "acme", "default_commit": "a" * 40}, OLD),
                 ({"formats": [OLD]}, OLD), ({"formats": [OLD, NEW]}, NEW), ({"formats": [NEW]}, NEW),
                 ({"formats": [NEW, OLD, "corthex-hub/0.4"]}, NEW), ({"formats": ["corthex-hub/0.4"]}, OLD),
                 ({"formats": NEW}, OLD), ({"formats": [1, None, {"name": NEW}]}, OLD), ("formats", OLD)]
        for held, wanted in cases:
            with self.subTest(held=held):
                self.assertEqual(FORMATS.choose(held), wanted)

    def test_a_commit_held_in_an_older_format_is_completed(self):
        cases = [({"format": OLD}, NEW, True), ({"format": NEW}, NEW, False), ({"format": None}, NEW, False), ({}, NEW, False),
                 ({"format": "corthex-hub/0.4"}, NEW, False), ({"format": OLD}, OLD, False), ({"format": "corthex-hub/0.1"}, OLD, False),
                 ({"format": "0.2"}, NEW, False), ({"format": ["corthex-hub/0.2"]}, NEW, False), (None, NEW, False)]
        for held, schema, wanted in cases:
            with self.subTest(held=held, schema=schema):
                self.assertIs(FORMATS.completes(held, schema), wanted)


# API-242's answers, from the contract's examples.
COMMIT = "5f2c8a1e9b0d4c7a3e6f8b2d1c0a9e8f7b6d5c4a"
DRAWN = {"project": "acme", "revision": 4, "commit": COMMIT, "replaced": "0a1b2c3d4e5f60718293a4b5c6d7e8f901234567", "created": False,
         "same_commit": False, "diagrams": {"drawn": 2, "unchanged": 11, "failed": 0, "removed": 0}, "failures": [], "refused": [],
         "confirmations_invalidated": 1, "change_sets_reflected": 0, "threads_moved": 0}
SAME = dict(DRAWN, replaced=None, same_commit=True, diagrams={"drawn": 0, "unchanged": 13, "failed": 0, "removed": 0}, confirmations_invalidated=0)
CREATED = dict(DRAWN, revision=1, replaced=None, created=True, diagrams={"drawn": 13, "unchanged": 0, "failed": 0, "removed": 0},
               confirmations_invalidated=0)
REFUSALS_242 = [
    (400, "invalid_request", {"field": "text"}), (400, "invalid_snapshot", {"field": "project.name"}),
    (400, "unsupported_format", {"versions": [OLD, NEW]}), (401, "access_missing", {}), (403, "agent_only", {}),
    (409, "commit_not_replaced", {"held_commit": "0a1b2c3d4e5f60718293a4b5c6d7e8f901234567"}),
    (409, "older_snapshot", {"revision": 3}), (409, "repository_mismatch", {}),
    (413, "snapshot_too_large", {"limit": 8388608}), (415, "json_required", {}), (500, "internal", {}),
]
REFUSALS_243 = [(401, "access_missing"), (403, "agent_only"), (500, "internal")]


class PushCase(RevisionCase):
    HELD = "/api/snapshots/acme/held"

    def setUp(self):
        super().setUp()
        self.settings("acme", stages={"09-mockup": {"source": "design/base.tokens.json", "page": "design/mockup/shop.html"}})
        self.write(self.repo / "docs/03-user-flow/FL-001-sign-up.md", FLOW.format(n="001", title="Sign up"))
        self.write(self.repo / "docs/03-user-flow/FL-001-sign-up.ko.md", FLOW.format(n="001", title="가입"))
        self.write(self.repo / "docs/08-screens/SCR-001.md", SCREEN.format(n="001", title="Orders", path="orders"))
        self.write(self.repo / "design/mockup/shop.html", PAGE.format(body="Orders"))
        self.start_commit = self.checkout()
        self.publish(self.start_commit)

    def posts(self):
        return [call["body"] for call in self.peer.calls if call["method"] == "POST"]

    def held(self, commit, fmt=OLD, formats=(OLD, NEW)):
        answer = {"project": "acme", "default_commit": commit, "revision": 4 if commit else None}
        if formats is not None:
            answer.update(formats=list(formats), format=fmt if commit else None)
        return 200, answer

    def keys(self, body):
        return sorted((p["stage"], p["key"]) for p in body["pictures"] if p["stage"] in TEXT_STAGES)


class Push03Test(PushCase):
    """TASK-429 in a session's push: 0.3 only to a server that lists it, and a first push as 0.2 (API-242, API-243)."""

    SENT = [("03-user-flow", "docs/03-user-flow/FL-001-sign-up.md"), ("08-screen-states", "docs/08-screens/SCR-001.md"),
            ("09-mockup", "design/mockup/shop.html")]

    def setUp(self):
        super().setUp()
        self.profile()
        self.register()

    def test_a_server_that_lists_03_gets_03(self):
        newer = self.commit("newer")
        self.publish(newer)
        self.peer.on("GET", self.HELD, self.held(self.start_commit))
        self.peer.on("POST", "/api/snapshots", (200, DRAWN))
        code, rows, err = self.hub("push", "acme")
        self.assertEqual((code, rows[0]["outcome"], rows[0]["answer"]), (0, "done", DRAWN), err)
        (body,) = self.posts()
        self.assertEqual((body["schema"], body["replaces"], body["repos"]["."]["default"]["commit"]), (NEW, self.start_commit, newer))
        self.assertEqual(self.keys(body), self.SENT)
        self.assertTrue(all(len(p["key"]) <= 300 and set(p["source"]) == {"text"} for p in body["pictures"] if p["stage"] in TEXT_STAGES))
        saved = json.loads((self.home / ".corthex/hub/snapshots/acme.json").read_text(encoding="utf8"))
        self.assertEqual(saved["schema"], NEW, "the saved snapshot is the one sent")

    def test_the_same_commit_held_in_02_goes_again_in_03(self):
        self.peer.on("GET", self.HELD, self.held(self.start_commit, OLD))
        self.peer.on("POST", "/api/snapshots", (200, SAME))
        code, rows, err = self.hub("push", "acme")
        self.assertEqual((code, rows[0]["outcome"], rows[0]["answer"]), (0, "done", SAME), err)
        (body,) = self.posts()
        self.assertEqual(body["schema"], NEW)
        self.assertNotIn("replaces", body)

    def test_a_server_of_before_gets_02(self):
        newer = self.commit("newer")
        self.publish(newer)
        for formats in (None, [OLD], ["corthex-hub/0.4"]):
            with self.subTest(formats=formats):
                self.peer.calls.clear()
                self.peer.on("GET", self.HELD, self.held(self.start_commit, formats=formats))
                self.peer.on("POST", "/api/snapshots", (200, {"project": "acme", "revision": 5}))
                code, rows, err = self.hub("push", "acme")
                self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
                (body,) = self.posts()
                self.assertEqual((body["schema"], self.keys(body)), (OLD, []))

    def test_a_first_push_goes_as_02(self):
        self.peer.on("GET", self.HELD, problem(404, "project_not_found"))
        self.peer.on("POST", "/api/snapshots", (201, CREATED))
        code, rows, err = self.hub("push", "acme")
        self.assertEqual((code, rows[0]["outcome"], rows[0]["failure"]), (1, "refused", "first push needs --first"), err)
        code, rows, err = self.hub("push", "acme", "--first")
        self.assertEqual((code, rows[0]["outcome"], rows[0]["answer"]), (0, "done", CREATED), err)
        (body,) = self.posts()
        self.assertEqual((body["schema"], self.keys(body)), (OLD, []))

    def test_every_answer_of_api_242(self):
        self.peer.on("GET", self.HELD, self.held(self.start_commit))
        for status, answer in ((200, DRAWN), (200, SAME), (201, CREATED)):
            with self.subTest(status=status, answer=answer["same_commit"]):
                self.peer.on("POST", "/api/snapshots", (status, answer))
                code, rows, err = self.hub("push", "acme")
                self.assertEqual((code, rows[0]["outcome"], rows[0]["answer"]), (0, "done", answer), err)
        for status, code_name, members in REFUSALS_242:
            with self.subTest(status=status, code=code_name):
                self.peer.on("POST", "/api/snapshots", problem(status, code_name, traceId="17feabe66e19073e", **members))
                code, rows, err = self.hub("push", "acme")
                self.assertEqual((code, rows[0]["outcome"], rows[0]["problem"]["code"]), (1, "refused", code_name), err)
                for key, value in members.items():
                    self.assertEqual(rows[0]["problem"][key], value)
                self.assertEqual(list((self.home / ".corthex/hub/outbox").glob("acme/*.json")), [], "a push never waits")
        self.assertTrue(all(body["schema"] == NEW for body in self.posts()))

    def test_every_answer_of_api_243(self):
        self.peer.on("POST", "/api/snapshots", (200, DRAWN))
        self.peer.on("GET", self.HELD, self.held(self.start_commit, NEW))
        code, rows, err = self.hub("push", "acme")
        self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
        self.peer.calls.clear()
        for status, code_name in REFUSALS_243:
            with self.subTest(status=status, code=code_name):
                self.peer.on("GET", self.HELD, problem(status, code_name))
                code, rows, err = self.hub("push", "acme")
                self.assertEqual((code, rows[0]["outcome"], rows[0]["problem"]["code"]), (1, "refused", code_name), err)
        self.peer.on("GET", self.HELD, problem(404, "project_not_found"))
        code, rows, err = self.hub("push", "acme")
        self.assertEqual((code, rows[0]["outcome"], rows[0]["failure"]), (1, "refused", "first push needs --first"), err)
        self.assertEqual(self.posts(), [], "a refused read sends nothing")


class PushJob03Test(PushCase):
    """TASK-429 in a repository's push job: a commit held in 0.2 goes again in 0.3, once (API-242, API-243)."""

    def setUp(self):
        super().setUp()
        self.env = dict(TOKEN, CORTHEX_NEXUS_URL=self.peer.url)

    def job(self):
        return self.hub("push", "--job", env=self.env)

    def test_a_commit_held_in_02_is_sent_again_in_03_once(self):
        server = {"format": OLD}

        def held(call):
            return self.held(self.start_commit, server["format"])

        def store(call):
            server["format"] = call["body"]["schema"]
            return 200, SAME
        self.peer.on("GET", self.HELD, (held, None))
        self.peer.on("POST", "/api/snapshots", (store, None))
        code, rows, err = self.job()
        self.assertEqual((code, rows[0]["outcome"], rows[0]["answer"]), (0, "done", {"sent": True, "pushed": SAME}), err)
        (body,) = self.posts()
        self.assertEqual((body["schema"], body["repos"]["."]["default"]["commit"]), (NEW, self.start_commit))
        self.assertNotIn("replaces", body)
        self.assertEqual(len(self.keys(body)), 3)
        for _ in range(2):
            code, rows, err = self.job()
            self.assertEqual((code, rows[0]["outcome"], rows[0]["answer"]), (0, "done", {"sent": False, "why": "already-held"}), err)
        self.assertEqual(len(self.posts()), 1, "once")

    def test_a_commit_held_as_it_would_be_sent_is_already_held(self):
        cases = {"held in 0.3": self.held(self.start_commit, NEW), "a server of before": self.held(self.start_commit, formats=None),
                 "a server that lists only 0.2": self.held(self.start_commit, OLD, [OLD])}
        for name, answer in cases.items():
            with self.subTest(name):
                self.peer.on("GET", self.HELD, answer)
                code, rows, err = self.job()
                self.assertEqual((code, rows[0]["outcome"], rows[0]["answer"]), (0, "done", {"sent": False, "why": "already-held"}), err)
        self.assertEqual(self.posts(), [])

    def test_an_older_commit_is_not_sent_in_a_newer_format(self):
        held = self.commit("held")
        self.peer.on("GET", self.HELD, self.held(held, OLD))
        code, rows, err = self.job()
        self.assertEqual((code, rows[0]["answer"]), (0, {"sent": False, "why": "already-held"}), err)
        self.assertEqual(self.posts(), [])

    def test_a_newer_commit_goes_in_03(self):
        newer = self.commit("newer")
        self.publish(newer)
        self.peer.on("GET", self.HELD, self.held(self.start_commit, OLD))
        self.peer.on("POST", "/api/snapshots", (200, DRAWN))
        code, rows, err = self.job()
        self.assertEqual((code, rows[0]["answer"]), (0, {"sent": True, "pushed": DRAWN}), err)
        (body,) = self.posts()
        self.assertEqual((body["schema"], body["replaces"]), (NEW, self.start_commit))

    def test_every_answer_of_api_242_and_243(self):
        newer = self.commit("newer")
        self.publish(newer)
        self.peer.on("GET", self.HELD, self.held(self.start_commit, NEW))
        for status, answer in ((200, DRAWN), (201, CREATED)):
            with self.subTest(status=status):
                self.peer.on("POST", "/api/snapshots", (status, answer))
                code, rows, err = self.job()
                self.assertEqual((code, rows[0]["answer"]), (0, {"sent": True, "pushed": answer}), err)
        for status, code_name, members in REFUSALS_242:
            with self.subTest(status=status, code=code_name):
                self.peer.on("POST", "/api/snapshots", problem(status, code_name, **members))
                code, rows, err = self.job()
                self.assertEqual((code, rows[0]["outcome"], rows[0]["problem"]["code"]), (1, "refused", code_name), err)
        posts = len(self.posts())
        for status, code_name in REFUSALS_243:
            with self.subTest(status=status, code=code_name):
                self.peer.on("GET", self.HELD, problem(status, code_name))
                code, rows, err = self.job()
                self.assertEqual((code, rows[0]["outcome"], rows[0]["problem"]["code"]), (1, "refused", code_name), err)
        self.peer.on("GET", self.HELD, problem(404, "project_not_found"))
        code, rows, err = self.job()
        self.assertEqual((code, rows[0]["answer"]), (0, {"sent": False, "why": "first-push-waits"}), err)
        self.assertEqual(len(self.posts()), posts, "a refused or missing read sends nothing")


# The commit of kodonghui/corthex-nexus whose tree TASK-428 and TASK-429 name: main when its WBS was approved. Any clone
# that has it will do, however far main has moved since. TASK-431 proves the same again in the product repository's CI,
# with the hub that it pins.
PRODUCT_COMMIT = "f557726736bb98464791615178a6fc5a72933023"
# The mockup page that TASK-432 names in the product's .corthex/project.json.
PRODUCT_PAGE = "design/mockup/nexus-mockup.html"


@unittest.skipUnless(os.environ.get("CORTHEX_NEXUS_CHECKOUT"),
                     "set CORTHEX_NEXUS_CHECKOUT to a local clone of kodonghui/corthex-nexus that has commit " + PRODUCT_COMMIT)
class ProductTreeTest(unittest.TestCase):
    """TASK-428 and TASK-429 on corthex-nexus's own tree at PRODUCT_COMMIT, read from a local clone; nothing is fetched.

    The tree goes into a new repository whose default branch holds it, as a clone's does, and a second commit names the
    mockup page in stage 09's `page`, as TASK-432 does. The hub then prints both formats, as TASK-431 runs it.
    """

    @classmethod
    def setUpClass(cls):
        git = hub.git_program()
        if git is None:
            raise unittest.SkipTest("Git is not installed")
        folder = tempfile.TemporaryDirectory(prefix="corthex-nexus-tree-")
        cls.addClassCleanup(folder.cleanup)
        base = Path(folder.name).resolve()
        checkout = Path(os.environ["CORTHEX_NEXUS_CHECKOUT"]).expanduser().resolve()
        cls.repo, cls.home = base / "corthex-nexus", base / "home"
        env = {"HOME": str(cls.home), "USERPROFILE": str(cls.home), "PATH": os.environ.get("PATH", ""), "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1", "GIT_NO_REPLACE_OBJECTS": "1",
               "GIT_AUTHOR_NAME": "Fixture author", "GIT_AUTHOR_EMAIL": "fixture@example.com",
               "GIT_COMMITTER_NAME": "Fixture author", "GIT_COMMITTER_EMAIL": "fixture@example.com"}
        for key in ("SystemRoot", "WINDIR", "SYSTEMROOT", "TEMP", "TMP"):
            if key in os.environ:
                env[key] = os.environ[key]

        def run(where, *words):
            return subprocess.run([git, "-C", str(where)] + list(words), env=env, capture_output=True, timeout=120)

        if run(checkout, "cat-file", "-e", PRODUCT_COMMIT + "^{commit}").returncode:
            raise unittest.SkipTest("the checkout in CORTHEX_NEXUS_CHECKOUT does not have commit " + PRODUCT_COMMIT)
        archive = run(checkout, "archive", "--format=tar", PRODUCT_COMMIT)
        if archive.returncode:
            raise unittest.SkipTest("the checkout lacks objects of commit " + PRODUCT_COMMIT + ", and nothing is fetched")
        cls.tree = run(checkout, "rev-parse", PRODUCT_COMMIT + "^{tree}").stdout.decode("ascii").strip()
        cls.repo.mkdir(parents=True)
        cls.home.mkdir()
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as bundle:
            for member in bundle.getmembers():
                if member.name.startswith(("/", "\\")) or ".." in Path(member.name).parts or not (member.isfile() or member.isdir()):
                    raise AssertionError("unexpected archive member: " + member.name)
            if hasattr(tarfile, "data_filter"):
                bundle.extractall(str(cls.repo), filter="data")
            else:
                bundle.extractall(str(cls.repo))

        def must(*words):
            result = run(cls.repo, *words)
            if result.returncode:
                raise AssertionError("git " + words[0] + ": " + result.stderr.decode("utf8", "replace"))
            return result.stdout.decode("utf8").strip()

        must("init", "-q")
        must("symbolic-ref", "HEAD", "refs/heads/main")
        must("config", "commit.gpgsign", "false")
        must("config", "core.hooksPath", str(base / "no-hooks"))
        must("config", "remote.origin.url", "https://github.com/kodonghui/corthex-nexus.git")
        must("add", "-A")
        must("commit", "--no-verify", "-q", "-m", "corthex-nexus at " + PRODUCT_COMMIT)
        cls.copied = must("rev-parse", "HEAD^{tree}")
        settings = cls.repo / ".corthex" / "project.json"
        data = json.loads(settings.read_text(encoding="utf8"))
        data["stages"]["09-mockup"]["page"] = PRODUCT_PAGE
        with open(str(settings), "w", encoding="utf8", newline="\n") as handle:
            handle.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        must("commit", "--no-verify", "-q", "-am", "Name the mockup page, as TASK-432 does")
        must("update-ref", "refs/remotes/origin/main", must("rev-parse", "HEAD"))
        must("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        cls.snapshots = {}
        for schema in (OLD, NEW):
            result = subprocess.run([sys.executable, str(SCRIPT), "--home", str(cls.home), "snapshot", "--path", str(cls.repo),
                                     "--print", "--format", schema], cwd=str(cls.repo), env=env, capture_output=True, timeout=300)
            if result.returncode:
                raise AssertionError(result.stderr.decode("utf8", "replace"))
            cls.snapshots[schema] = json.loads(result.stdout.decode("utf8"))

    def test_the_tree_is_the_products_own(self):
        self.assertEqual(self.copied, self.tree)

    def test_13_flows_5_screens_and_the_mockup_page_and_no_translation(self):
        snapshot = self.snapshots[NEW]
        texts = [p for p in snapshot["pictures"] if p["stage"] in TEXT_STAGES]
        counts = {stage: sum(1 for p in texts if p["stage"] == stage) for stage in TEXT_STAGES}
        self.assertEqual(counts, {"03-user-flow": 13, "08-screen-states": 5, "09-mockup": 1})
        self.assertEqual([p["key"] for p in texts if p["stage"] == "09-mockup"], [PRODUCT_PAGE])
        self.assertTrue(all(p["key"].startswith("docs/03-user-flow/FL-") for p in texts if p["stage"] == "03-user-flow"))
        self.assertTrue(all(p["key"].startswith("docs/08-screens/SCR-") for p in texts if p["stage"] == "08-screen-states"))
        self.assertEqual([p["key"] for p in texts if ".ko." in p["key"]], [])
        for picture in texts:
            with self.subTest(key=picture["key"]):
                with open(str(self.repo / picture["key"]), encoding="utf8", newline="") as handle:
                    self.assertEqual(picture["source"]["text"], handle.read())
        self.assertEqual((snapshot["left_out"], snapshot["truncated"]), ([], False))
        self.assertEqual([p["stage"] for p in self.snapshots[OLD]["pictures"]], ["01-domain", "05-erd", "07-sitemap"])

    def test_the_03_snapshot_fits_its_budget(self):
        old, new = size(self.snapshots[OLD]), size(self.snapshots[NEW])
        self.assertLessEqual(old, hub.MAX_SNAPSHOT_BYTES)
        self.assertLessEqual(new, FORMATS.MAX_SNAPSHOT_BYTES)
        # The WBS gives about 505 KB for these picture sources, of which the mockup page is 427 KB.
        added = sum(size(p) for p in self.snapshots[NEW]["pictures"] if p["stage"] in TEXT_STAGES)
        self.assertTrue(480 * 1000 < added < 530 * 1000, added)
        sys.stderr.write("\ncorthex-nexus at %s: 0.2 snapshot %d bytes, 0.3 snapshot %d bytes, pictures of 03, 08 and 09 %d bytes, "
                         "budget %d\n" % (PRODUCT_COMMIT[:7], old, new, added, FORMATS.MAX_SNAPSHOT_BYTES))


class VersionsTest(unittest.TestCase):
    """TASK-430 (SPEC-014): every version field of the hub plugin at 0.6.0."""

    def test_the_hub_and_its_client_say_0_6_0(self):
        self.assertEqual(hub.VERSION, "0.6.0")
        client = hub.companion("transport").Client("http://127.0.0.1:1", {})
        self.assertEqual(client.version, "0.6.0")
        root = SCRIPT.parents[3]
        for manifest in ("plugin.json", ".claude-plugin/plugin.json"):
            with self.subTest(manifest=manifest):
                self.assertEqual(json.loads((root / manifest).read_text(encoding="utf8"))["version"], "0.6.0")
        self.assertIn('\n  version: "0.6.0"\n', (SCRIPT.parents[1] / "SKILL.md").read_text(encoding="utf8"))


if __name__ == "__main__":
    unittest.main()
