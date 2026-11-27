"""The hub with NEXUS v3: status --nexus builds v3's stage address offline, and propose sends source_path.

The in-process cases use synthetic clients; the CLI cases run hub.py against the scripted peer on this
device that the design revision's tests use. No real server, service token or network is used.
"""
import io
import json
import os
from unittest import mock
from types import SimpleNamespace
from pathlib import Path, PurePosixPath, PureWindowsPath

from test_hub import HubCase, NOW, hub
from test_hub02 import FakeClient
from test_hub_revision import TOKEN, RevisionCase, problem

CMD = hub.companion("commands")
BOX = hub.companion("outbox")
HTTP = hub.companion("transport")
RECORD = hub.companion("records")
SESSION = "test-session"
CHECKPOINT = "nk_" + "d" * 12
V3 = {"project": "acme-shop", "default_commit": None, "formats": ["corthex-hub/0.2", "corthex-hub/0.3"], "format": None}
V2 = {"project": "acme-shop", "default_commit": None}
NO_FILE = "source_path names no file the drawing reads"
SEVERAL = "source_path is needed: the drawing reads several files"


class CheckoutPathTest(HubCase):
    """A --source-file's path made relative to the checkout, with / on every platform."""

    def test_windows_paths_inside_and_outside_the_checkout(self):
        root = PureWindowsPath("C:\\work\\acme-shop")
        self.assertEqual(CMD.checkout_path(PureWindowsPath("C:\\work\\acme-shop\\db\\schema.sql"), root), "db/schema.sql")
        self.assertEqual(CMD.checkout_path(PureWindowsPath("C:\\work\\acme-shop\\docs\\01-domain\\a.md"), root), "docs/01-domain/a.md")
        # Windows compares paths without case; the file's own spelling is kept.
        self.assertEqual(CMD.checkout_path(PureWindowsPath("c:\\WORK\\acme-shop\\DB\\Schema.sql"), root), "DB/Schema.sql")
        for outside in ("C:\\work\\acme-shop-copy\\db\\schema.sql", "D:\\work\\acme-shop\\db\\schema.sql", "C:\\work\\schema.sql",
                        "\\\\server\\share\\acme-shop\\db\\schema.sql"):
            with self.subTest(outside=outside):
                self.assertIsNone(CMD.checkout_path(PureWindowsPath(outside), root))
        self.assertIsNone(CMD.checkout_path(root, root))

    def test_posix_paths_inside_and_outside_the_checkout(self):
        root = PurePosixPath("/work/acme-shop")
        self.assertEqual(CMD.checkout_path(PurePosixPath("/work/acme-shop/db/schema.sql"), root), "db/schema.sql")
        for outside in ("/work/acme-shop-copy/db/schema.sql", "/tmp/schema.sql", "/work/schema.sql"):
            with self.subTest(outside=outside):
                self.assertIsNone(CMD.checkout_path(PurePosixPath(outside), root))
        self.assertIsNone(CMD.checkout_path(root, root))

    def test_a_real_file_inside_and_outside_the_checkout(self):
        inside, outside = self.repo / "db" / "schema.sql", self.base / "elsewhere" / "schema.sql"
        for path in (inside, outside):
            self.write(path, "CREATE TABLE t (id INT);\n")
        root = hub.plain_path(self.repo.resolve())
        self.assertEqual(CMD.checkout_path(hub.plain_path(inside.resolve()), root), "db/schema.sql")
        self.assertIsNone(CMD.checkout_path(hub.plain_path(outside.resolve()), root))

    def test_source_path_is_a_plain_repository_path(self):
        self.assertEqual(CMD.repository_path("db\\schema.sql"), "db/schema.sql")
        self.assertEqual(CMD.repository_path("docs/01-domain/orders.md"), "docs/01-domain/orders.md")
        self.assertEqual(CMD.repository_path("a" * 296 + ".sql"), "a" * 296 + ".sql")
        for wrong in ("", "a" * 297 + ".sql", "/db/schema.sql", "\\db\\schema.sql", "C:/db/schema.sql", "c:schema.sql",
                      "\\\\server\\share\\schema.sql", "db/../schema.sql", "./db/schema.sql", "db//schema.sql", "db/",
                      "db/.", "db/sche\nma.sql", "db/sche\x7fma.sql"):
            with self.subTest(wrong=wrong), self.assertRaises(CMD.CommandLine):
                CMD.repository_path(wrong)


class SourcePathTest(HubCase):
    """propose's local checks of source_path, each passing and failing before anything is sent or kept."""

    def setUp(self):
        super().setUp()
        self.settings()
        self.write(self.home / ".corthex/profile.json", {"nexus": {"url": "https://nexus.example.com", "push": ["acme-shop"]}})

    def settings(self, **fields):
        stages = {"01-domain": {"source": "docs/01-domain/"}, "05-erd": {"source": "db/schema.sql"},
                  "07-sitemap": {"source": "docs/07-sitemap/"}}
        stages.update(fields.pop("stages", {}))
        self.project(stages=stages, **fields)
        self.register()

    def file(self, rel, text="text\n"):
        path = self.repo.joinpath(*rel.split("/"))
        self.write(path, text)
        return path

    def propose(self, stage, *words, client=None, env=None):
        args = hub.parser().parse_args(["propose", "acme-shop", "--stage", stage, "--item", "TBL-001", "--reason", "Reason",
                                        "--change", "Change", "--session", SESSION] + list(words))
        client = client or FakeClient()
        rows = CMD.execute(args, self.home, vars(hub), env=env or {}, client_factory=lambda *a, **k: client)
        return rows, client

    def sent(self, stage, *words, env=None):
        rows, client = self.propose(stage, *words, env=env)
        self.assertEqual(rows[0]["outcome"], "done")
        self.assertEqual(len(client.calls), 1)
        return client.calls[0][2]

    def refused(self, stage, *words, says, env=None):
        client = FakeClient()
        with self.assertRaises(CMD.CommandLine) as caught:
            self.propose(stage, *words, client=client, env=env)
        self.assertIn(says, str(caught.exception))
        self.assertEqual(client.calls, [])
        self.assertEqual(BOX.Outbox(self.home, "acme-shop").files(), [])

    def test_a_file_in_the_checkout_sends_its_repository_path(self):
        path = self.file("db/schema.sql", "CREATE TABLE orders (id INT);\n")
        body = self.sent("05-erd", "--source-file", str(path))
        self.assertEqual((body["source_text"], body["source_path"]), ("CREATE TABLE orders (id INT);\n", "db/schema.sql"))
        # The same path given again is taken; another one is refused.
        self.assertEqual(self.sent("05-erd", "--source-file", str(path), "--source-path", "db/schema.sql")["source_path"], "db/schema.sql")
        self.refused("05-erd", "--source-file", str(path), "--source-path", "db/other.sql",
                     says="--source-path names db/other.sql, but --source-file is db/schema.sql")

    def test_a_file_outside_the_checkout_needs_source_path(self):
        outside = self.base / "proposed" / "schema.sql"
        self.write(outside, "CREATE TABLE orders (id INT);\n")
        self.refused("05-erd", "--source-file", str(outside), says="add --source-path")
        self.assertEqual(self.sent("05-erd", "--source-file", str(outside), "--source-path", "db/schema.sql")["source_path"], "db/schema.sql")
        # A Windows path's separators go out as / on every platform.
        self.assertEqual(self.sent("05-erd", "--source-file", str(outside), "--source-path", "db\\schema.sql")["source_path"], "db/schema.sql")

    def test_source_path_goes_only_with_source_file(self):
        self.refused("05-erd", "--source-path", "db/schema.sql", says="--source-path goes only with --source-file")
        body = self.sent("05-erd")
        self.assertNotIn("source_text", body)
        self.assertNotIn("source_path", body)

    def test_the_path_is_under_the_stages_source(self):
        inside = self.file("docs/01-domain/orders.md")
        self.assertEqual(self.sent("01-domain", "--source-file", str(inside))["source_path"], "docs/01-domain/orders.md")
        elsewhere = self.file("docs/02-prd/orders.md")
        self.refused("01-domain", "--source-file", str(elsewhere), says="is not under 01-domain's source")
        self.refused("05-erd", "--source-file", str(self.file("db/schema2.sql")), says="is not under 05-erd's source")

    def test_the_extension_is_one_the_stage_reads(self):
        for rel, stage in (("docs/01-domain/orders.markdown", "01-domain"), ("docs/07-sitemap/site.yml", "07-sitemap"),
                           ("docs/07-sitemap/site.YAML", "07-sitemap")):
            with self.subTest(rel=rel):
                self.assertEqual(self.sent(stage, "--source-file", str(self.file(rel)))["source_path"], rel)
        for rel, stage in (("docs/01-domain/orders.txt", "01-domain"), ("docs/07-sitemap/site.json", "07-sitemap")):
            with self.subTest(rel=rel):
                self.refused(stage, "--source-file", str(self.file(rel)), says="is not a file that " + stage + "'s picture reads")

    def test_a_translation_beside_its_original_is_refused(self):
        lone = self.file("docs/01-domain/orders.ko.md")
        self.assertEqual(self.sent("01-domain", "--source-file", str(lone))["source_path"], "docs/01-domain/orders.ko.md")
        self.file("docs/01-domain/orders.md")
        self.refused("01-domain", "--source-file", str(lone), says="is a translation of docs/01-domain/orders.md")
        outside = self.base / "proposed.md"
        self.write(outside, "text\n")
        self.refused("01-domain", "--source-file", str(outside), "--source-path", "docs/01-domain/orders.ko.md", says="is a translation")

    def test_a_name_that_looks_like_a_secret_is_refused(self):
        for rel in ("docs/01-domain/secrets.md", "docs/01-domain/credentials/orders.md", "docs/01-domain/api-keys.md"):
            with self.subTest(rel=rel):
                self.refused("01-domain", "--source-file", str(self.file(rel)), says="looks like a secret's")
        self.assertEqual(self.sent("01-domain", "--source-file", str(self.file("docs/01-domain/secretary.md")))["source_path"],
                         "docs/01-domain/secretary.md")

    def test_the_checkout_is_found_as_can_send_finds_it(self):
        path = self.file("db/schema.sql")
        here = os.getcwd()
        os.chdir(str(self.repo))
        try:
            # A checkout that the list of projects does not name is the current folder's.
            self.write(self.home / ".corthex/projects.json", {"projects": []})
            self.assertEqual(self.sent("05-erd", "--source-file", str(path))["source_path"], "db/schema.sql")
            # A session's environment, with neither a profile nor a list of projects, reads its own checkout only.
            for name in ("projects.json", "profile.json"):
                (self.home / ".corthex" / name).unlink()
            env = {"CORTHEX_NEXUS_URL": "https://nexus.example.com", "CORTHEX_NEXUS_PUSH": "acme-shop"}
            self.assertEqual(self.sent("05-erd", "--source-file", str(path), env=env)["source_path"], "db/schema.sql")
            self.project(name="acme-other")
            self.refused("05-erd", "--source-file", str(path), env=env, says="not this checkout's project")
        finally:
            os.chdir(here)

    def test_a_tagged_file_that_the_source_selects_is_not_a_translation(self):
        self.settings(stages={"01-domain": {"source": "docs/01-domain/orders.ko.md"}})
        tagged, original = self.file("docs/01-domain/orders.ko.md"), self.file("docs/01-domain/orders.md")
        self.assertEqual(self.sent("01-domain", "--source-file", str(tagged))["source_path"], "docs/01-domain/orders.ko.md")
        self.refused("01-domain", "--source-file", str(original), says="is not under 01-domain's source")

    def test_the_file_belongs_to_the_commands_part(self):
        self.settings(parts=["orders", "billing"])
        orders, shared = self.file("docs/01-domain/orders.md"), self.file("docs/01-domain/shared.md")
        self.assertEqual(self.sent("01-domain", "--part", "orders", "--source-file", str(orders))["source_path"], "docs/01-domain/orders.md")
        self.assertEqual(self.sent("01-domain", "--source-file", str(shared))["source_path"], "docs/01-domain/shared.md")
        self.refused("01-domain", "--source-file", str(orders), says="belongs to the part orders, not to the project as a whole: add --part orders")
        self.refused("01-domain", "--part", "billing", "--source-file", str(orders), says="belongs to the part orders, not to --part billing")
        self.refused("01-domain", "--part", "orders", "--source-file", str(shared), says="belongs to no part, not to --part orders")

    def test_a_stage_without_a_picture_from_this_checkout_is_refused(self):
        path = self.file("docs/07-sitemap/site.yaml")
        cases = (({"07-sitemap": {"skip": True}}, "is skipped"),
                 ({"07-sitemap": {"human": "figma"}}, "has no source"),
                 ({"07-sitemap": {"source": "design:docs/07-sitemap/"}}, "in another repository"))
        for stages, says in cases:
            with self.subTest(says=says):
                self.settings(stages=stages, repos={"design": "https://example.com/acme/design"})
                self.refused("07-sitemap", "--source-file", str(path), says=says)
        self.settings()
        self.assertEqual(self.sent("07-sitemap", "--source-file", str(path))["source_path"], "docs/07-sitemap/site.yaml")

    def test_a_project_without_a_checkout_here_is_refused(self):
        source = self.base / "schema.sql"
        self.write(source, "text\n")
        self.write(self.home / ".corthex/projects.json", {"projects": []})
        self.refused("05-erd", "--source-file", str(source), "--source-path", "db/schema.sql", says="needs the project's checkout")

    def test_the_two_refusals_of_source_path_print_their_detail(self):
        path = self.file("db/schema.sql")
        for detail in (NO_FILE, SEVERAL):
            with self.subTest(detail=detail):
                answer = HTTP.result("refused", problem={"status": 400, "code": "invalid_request", "field": "source_path", "detail": detail})
                rows, _ = self.propose("05-erd", "--source-file", str(path), client=FakeClient([answer]))
                self.assertEqual(rows[0]["outcome"], "refused")
                said = []
                self.assertEqual(CMD.emit(hub.parser().parse_args(["propose", "acme-shop", "--stage", "05-erd", "--item", "TBL-001",
                                                                    "--reason", "r", "--change", "c"]), rows, SimpleNamespace(say=said.append, one_line=hub.one_line)), 1)
                self.assertIn("  invalid_request: " + detail, said)
                self.assertEqual(BOX.Outbox(self.home, "acme-shop").files(), [])


class StatusLinkTest(HubCase):
    """status --nexus without --where, offline: the link follows this device's last read of the server."""

    URL = "https://nexus.example.com/"

    def setUp(self):
        super().setUp()
        self.project(parts=["orders"])
        self.register()
        self.write(self.home / ".corthex/profile.json", {"nexus": {"url": self.URL, "push": ["acme-shop"]}})

    def known(self, v3, url=None):
        RECORD.remember_server(self.home, url or self.URL, v3, SimpleNamespace(**vars(hub)))

    def status(self, *words, part="orders"):
        args = hub.parser().parse_args(["status", "acme-shop", "05-erd", "--repository", "--checkpoint", "ERD passed in NEXUS",
                                        "--by", "the maintainer", "--date", "2026-11-24", "--nexus", CHECKPOINT] +
                                       (["--part", part] if part else []) + list(words))
        project = hub.select_projects(self.home, ["acme-shop"])[0][1]
        err = io.StringIO()
        # status contacts no server: any connection or client fails the test.
        with mock.patch("socket.socket.connect", side_effect=AssertionError("status contacted a server")), \
                mock.patch.object(HTTP, "Client", side_effect=AssertionError("status made a client")), mock.patch("sys.stderr", err):
            entry, _ = RECORD.write(project, self.home, args, vars(hub), NOW)
        return entry["checkpoints"][-1], err.getvalue()

    def test_v3_gets_its_stage_address_without_a_fragment(self):
        self.known(True, "HTTPS://Nexus.Example.com")
        checkpoint, said = self.status()
        self.assertEqual(checkpoint, {"approved": "ERD passed in NEXUS", "by": "the maintainer", "nexus": CHECKPOINT,
                                      "where": "https://nexus.example.com/p/acme-shop/orders/05-erd", "date": "2026-11-24"})
        self.assertEqual(said, "")

    def test_a_project_without_parts_gets_the_underscore(self):
        self.project()
        self.known(True)
        self.assertEqual(self.status(part=None)[0]["where"], "https://nexus.example.com/p/acme-shop/_/05-erd")
        self.known(False)
        self.assertEqual(self.status(part=None)[0]["where"], "https://nexus.example.com/overview/acme-shop/_/05-erd#" + CHECKPOINT)

    def test_an_older_server_keeps_its_overview_link(self):
        self.known(False)
        self.assertEqual(self.status()[0]["where"], "https://nexus.example.com/overview/acme-shop/orders/05-erd#" + CHECKPOINT)

    def test_without_a_record_of_the_server_status_records_no_link_and_says_how(self):
        for other in (None, "https://other.example.com"):
            with self.subTest(other=other):
                if other:
                    # A record of another server, even NEXUS v3, says nothing of the profile's address.
                    self.known(True, other)
                checkpoint, said = self.status()
                self.assertNotIn("where", checkpoint)
                self.assertEqual(checkpoint["nexus"], CHECKPOINT)
                self.assertIn("recorded without its link", said)
                self.assertIn("pass --where with the checkpoint's https link, or run todo once against that server", said)
                self.assertTrue((self.repo / ".corthex/stages/orders.json").is_file())

    def test_a_record_that_names_another_address_is_not_read(self):
        self.known(True)
        path = RECORD.server_file(self.home, RECORD.server_url(self.URL), SimpleNamespace(**vars(hub)))
        self.write(path, {"format": 1, "url": "https://other.example.com", "v3": True, "read": NOW})
        self.assertNotIn("where", self.status()[0])

    def test_the_record_keeps_no_token_and_no_project_data(self):
        self.known(True)
        files = list((self.home / ".corthex/hub/servers").glob("*.json"))
        self.assertEqual(len(files), 1)
        data = json.loads(files[0].read_text(encoding="utf8"))
        self.assertEqual(set(data), {"format", "url", "v3", "read"})
        self.assertEqual((data["url"], data["v3"]), ("https://nexus.example.com", True))

    def test_where_keeps_status_as_it_was(self):
        self.known(True)
        checkpoint, said = self.status("--where", "https://nexus.example.com/elsewhere")
        self.assertEqual((checkpoint["where"], said), ("https://nexus.example.com/elsewhere", ""))

    def test_no_address_names_nexus_url(self):
        self.write(self.home / ".corthex/profile.json", {"nexus": {"push": ["acme-shop"]}})
        with self.assertRaisesRegex(ValueError, "set nexus.url or --where"):
            self.status()
        self.assertFalse((self.repo / ".corthex/stages/orders.json").exists())


class ServerRecordTest(HubCase):
    """push and todo keep the record of the server that status builds its links from."""

    def setUp(self):
        super().setUp()
        self.project()
        self.register()
        self.write(self.home / ".corthex/profile.json", {"nexus": {"url": "https://nexus.example.com", "push": ["acme-shop"]}})

    def run_command(self, words, *answers):
        args = hub.parser().parse_args(words)
        client = FakeClient(list(answers))
        return CMD.execute(args, self.home, vars(hub), env={}, client_factory=lambda *a, **k: client)

    def known(self):
        return RECORD.known_server(self.home, "https://nexus.example.com", SimpleNamespace(**vars(hub)))

    def test_push_keeps_whether_the_server_lists_0_3(self):
        self.assertIsNone(self.known())
        self.run_command(["push", "acme-shop"], HTTP.result("done", answer=V3), HTTP.result("done", answer={}))
        self.assertIs(self.known(), True)
        self.run_command(["push", "acme-shop"], HTTP.result("done", answer=V2), HTTP.result("done", answer={}))
        self.assertIs(self.known(), False)

    def test_todo_keeps_whether_the_to_do_is_v3s(self):
        todo = {"project": "acme-shop", "default_commit": None, "session": SESSION, "read_at": None,
                "comments": {"total": 0, "entries": []}, "discrepancies": {"total": 0, "entries": []},
                "reflections": {"total": 0, "entries": []}, "checkpoints": {"total": 0, "entries": []},
                "waiting_for_user": 0, "taken": 0}
        words = ["todo", "acme-shop", "--session", SESSION]
        self.run_command(words, HTTP.result("done", answer=todo))
        self.assertIs(self.known(), False)
        self.run_command(words, HTTP.result("done", answer=dict(todo, steps={"total": 0, "entries": []})))
        self.assertIs(self.known(), True)
        # A space that the server does not hold says nothing of the server.
        self.run_command(words, HTTP.result("refused", problem={"status": 404, "code": "space_not_found"}))
        self.assertIs(self.known(), True)


class CommandLineTest(RevisionCase):
    """hub.py itself against the scripted peer: status contacts none, and the two 400 answers of propose."""

    HELD = "/api/snapshots/acme/held"

    def setUp(self):
        super().setUp()
        self.profile()
        self.register()

    def status(self, *words, env=TOKEN):
        return self.hub("status", "acme", "05-erd", "--repository", "--checkpoint", "ERD passed in NEXUS", "--by", "the maintainer",
                        "--date", "2026-11-24", "--nexus", CHECKPOINT, *words, env=env)

    def test_status_contacts_no_server(self):
        self.peer.on("GET", self.HELD, (200, dict(V3, project="acme")))
        code, rows, err = self.status()
        self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
        self.assertIn("run todo once against that server", err)
        code, rows, err = self.status("--where", "https://nexus.example.com/p/acme/_/05-erd")
        self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
        self.assertEqual(self.peer.calls, [])

    def test_propose_prints_the_detail_of_both_refusals(self):
        self.write(self.repo / "db/schema.sql", "CREATE TABLE orders (id INT);\n")
        for detail in (NO_FILE, SEVERAL):
            with self.subTest(detail=detail):
                self.peer.on("POST", "/api/spaces/acme/proposals", problem(400, "invalid_request", detail=detail, field="source_path"))
                words = ("propose", "acme", "--stage", "05-erd", "--item", "TBL-001", "--reason", "Reason", "--change", "Change",
                         "--source-file", str(self.repo / "db/schema.sql"), "--session", SESSION)
                code, out, err = self.hub(*words, env=TOKEN, json_lines=False)
                self.assertEqual(code, 1, err)
                self.assertIn("acme: propose refused\n  invalid_request: " + detail + "\n", out)
                code, rows, err = self.hub(*words, env=TOKEN)
                self.assertEqual((code, rows[0]["outcome"], rows[0]["problem"]["detail"]), (1, "refused", detail), err)
                posted = [c["body"] for c in self.peer.calls if c["method"] == "POST"]
                self.assertEqual(posted[-1]["source_path"], "db/schema.sql")
                self.assertEqual(list((self.home / ".corthex/hub/outbox").glob("acme/*.json")), [])


class SkillTextTest(HubCase):
    """The agents' rules for these changes, in the hub's skill and the stage skills' NEXUS work."""

    ROOT = Path(__file__).resolve().parents[1]

    def read(self, rel):
        return (self.ROOT / rel).read_text(encoding="utf8")

    def test_another_way_goes_inside_the_reason(self):
        for path in sorted((self.ROOT / "plugins/corthex/skills").glob("*/references/nexus-work.md")):
            with self.subTest(skill=path.parent.parent.name):
                text = path.read_text(encoding="utf8")
                self.assertIn("NEXUS has no field for another way. When you have another way worth weighing, write it inside the "
                              "proposal's reason, as its last sentence, in the form NEXUS shows, in the user's language: "
                              "`Other way: …` in English, `다른 방법: …` in Korean.", text)
        hub_skill = self.read("plugins/corthex-nexus/skills/corthex-hub/SKILL.md")
        self.assertIn("write it inside `--reason`, as its last sentence, in the form NEXUS shows, in the user's language: "
                      "`Other way: …` in English, `다른 방법: …` in Korean.", hub_skill)

    def test_the_hub_skill_says_where_status_takes_its_link_and_what_propose_checks(self):
        text = self.read("plugins/corthex-nexus/skills/corthex-hub/SKILL.md")
        for words in ("`status` contacts no server. Without `--where`, the link comes from this device's last read",
                      "`<nexus.url>/p/<project>/<part or _>/<stage>`",
                      "`<nexus.url>/overview/<project>/<part or _>/<stage>#<checkpoint>`, as before",
                      "or run `todo` once against that server to refresh the record",
                      "refuses the command line (exit 2)", "more than 300 characters", "`.yaml` or `.yml` for 07",
                      "`orders.ko.md` next to `orders.md`", "without `--part`, it belongs to no part",
                      "`" + NO_FILE + "`", "`" + SEVERAL + "`"):
            with self.subTest(words=words):
                self.assertIn(words, text)
        self.assertNotIn("the overview link", self.read("plugins/corthex/skills/corthex/references/nexus-work.md"))
