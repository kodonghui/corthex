"""Checks the NEXUS server in nexus/: the files it shares with the plugin, its
Worker settings and, with Node 22.5 or later, hub.py talking to it on this
machine. The server's own checks run with `node --test nexus/test/*.test.js`."""

import json
import shutil
import subprocess
import unittest
import urllib.error
import urllib.request

import test_hub as hub_tests
from _common import ROOT, read_text

hub = hub_tests.hub
NEXUS = ROOT / "nexus"
SNAPSHOTS = "/api/snapshots"
DATA_BLOCK = '<script id="hub-data" type="application/json">'
_node = []


def node_with_sqlite():
    """The node command when it has the SQLite module the stand-in database uses."""
    if not _node:
        node = shutil.which("node")
        if node:
            found = subprocess.run([node, "-e", "require('node:sqlite')"], capture_output=True, timeout=60)
            node = node if found.returncode == 0 else None
        _node.append(node)
    return _node[0]


def jsonc(path):
    """A wrangler.jsonc file whose comments take whole lines."""
    lines = [line for line in read_text(path).splitlines() if not line.strip().startswith("//")]
    return json.loads("\n".join(lines))


class FilesTest(unittest.TestCase):
    def test_shared_files_are_copies(self):
        pairs = (
            (NEXUS / "src" / "hub.html", hub_tests.TEMPLATE),
            (NEXUS / "LICENSE", ROOT / "LICENSE"),
            (NEXUS / "NOTICE", ROOT / "NOTICE"),
        )
        for copy, source in pairs:
            with self.subTest(copy=str(copy.relative_to(ROOT))):
                self.assertEqual(copy.read_bytes(), source.read_bytes(), "copy %s again" % source.relative_to(ROOT))

    def test_worker_settings(self):
        config = jsonc(NEXUS / "wrangler.jsonc")
        self.assertTrue((NEXUS / config["main"]).is_file())
        self.assertIs(config["workers_dev"], False)
        self.assertIs(config["preview_urls"], False)
        # Static assets would take the Access check (ctx.access) away from the Worker.
        self.assertNotIn("assets", config)
        self.assertEqual([route["pattern"] for route in config["routes"]], ["nexus.example.com"])
        (database,) = config["d1_databases"]
        self.assertEqual(database["binding"], "DB")
        self.assertNotIn("database_id", database, "the shared file names no one's database")
        self.assertIn({"type": "Text", "globs": ["**/*.html"], "fallthrough": True}, config["rules"])
        self.assertEqual(config["vars"], {"NEXUS_LANGUAGE": "en", "ACCESS_AUD": ""})


class ServerCase(hub_tests.HubCase):
    """A project made from the stage templates and the server running on this machine."""

    access = True

    def setUp(self):
        node = node_with_sqlite()
        if not node:
            self.skipTest("needs Node 22.5 or later")
        super().setUp()
        args = [node, str(NEXUS / "test" / "serve.js")] + ([] if self.access else ["--no-access"])
        server = subprocess.Popen(args, cwd=str(NEXUS), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop, server)
        self.url = server.stdout.readline().decode("utf-8").strip()
        self.assertTrue(self.url.startswith("http://127.0.0.1:"), "the server did not start")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for path, skill, stage, block in hub_tests.TEMPLATES:
            blocks = hub_tests.output_blocks(skill, stage)
            self.write(self.repo / path, "\n".join(blocks) if block is None else blocks[block])
        self.project()
        self.register()
        self.write(self.home / ".corthex" / "profile.json", {"language": "en", "nexus": {"url": self.url, "push": ["acme-shop"]}})
        hub.record_status(self.home, "acme-shop", "02-prd", "done", "PRD approved in the kickoff review", "2026-01-12",
                          "Write the user flows", [("warn", "SPEC-001 contradicts REQ-002 on refunds")], now=hub_tests.NOW)

    def stop(self, server):
        server.stdin.close()
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
        server.stdout.close()

    def save(self, now=hub_tests.NOW):
        ((_, project, reason),) = hub.select_projects(self.home, [], self.repo)
        self.assertIsNotNone(project, reason)
        snapshot = hub.make_snapshot(project, hub.load_status(self.home, project.name), now)
        hub.save_snapshot(self.home, snapshot)
        return json.loads(read_text(hub.snapshot_path(self.home, "acme-shop")))

    def get(self, path):
        """The status and body of a GET request."""
        try:
            with self.opener.open(self.url + path, timeout=30) as response:
                return response.getcode(), response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8")


class ServerTest(ServerCase):
    def test_push_show_and_remove(self):
        sent = self.save()
        self.assertGreater(len(sent["items"]), 10)
        self.assertEqual(hub.push(self.home, env={}), ["acme-shop: sent, HTTP 200, revision 1"])
        code, text = self.get(SNAPSHOTS)
        listed = [(p["name"], p["revision"], p["generated_at"]) for p in json.loads(text)["projects"]]
        self.assertEqual((code, listed), (200, [("acme-shop", 1, sent["generated_at"])]))
        code, text = self.get(SNAPSHOTS + "/acme-shop")
        self.assertEqual((code, json.loads(text)), (200, sent))
        code, page = self.get("/")
        start = page.index(DATA_BLOCK) + len(DATA_BLOCK)
        data = json.loads(page[start:page.index("</script>", start)])
        self.assertEqual((code, data["origin"], data["projects"]), (200, "server", [sent]))

        self.assertEqual(hub.push(self.home, env={}), ["acme-shop: sent, HTTP 200, revision 2"])
        self.save(now="2026-01-11T10:00:00+09:00")
        with self.assertRaisesRegex(RuntimeError, r"^the server refused it \(HTTP 409\): the server holds a newer snapshot of acme-shop"):
            hub.push(self.home, env={})

        self.assertEqual(hub.remove(self.home, ["acme-shop"], env={}), ["acme-shop: removed from the server"])
        self.assertEqual(hub.remove(self.home, ["acme-shop"], env={}), ["acme-shop: not on the server"])
        self.assertEqual(self.get(SNAPSHOTS), (200, '{"projects":[]}'))


class WithoutAccessTest(ServerCase):
    access = False

    def test_nothing_is_shown_or_stored(self):
        self.save()
        with self.assertRaises(RuntimeError) as caught:
            hub.push(self.home, env={})
        self.assertEqual(str(caught.exception), "the server refused it (HTTP 403): Cloudflare Access did not check this request; protect this Worker with Access first")
        for path in ("/", SNAPSHOTS, SNAPSHOTS + "/acme-shop"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path)[0], 403)


if __name__ == "__main__":
    unittest.main()
