"""The hub's commands for NEXUS's design revision (0.4.0), one method per case of its stage 12.

Each case runs the actual hub.py in a child process, with an isolated home, a synthetic project
checkout and a scripted HTTP peer on this device. No real server, service token or network is
used; the token values are synthetic. The method names keep the QA cases' TC IDs.
"""
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins/corthex-nexus/skills/corthex-hub/scripts/hub.py"
TOKEN = {"CORTHEX_NEXUS_CLIENT_ID": "synthetic-client-id", "CORTHEX_NEXUS_CLIENT_SECRET": "synthetic-client-secret"}
REMOTE = "https://nexus.example.invalid"


class Peer:
    """A scripted NEXUS on 127.0.0.1 that records each request. Not the product's handler."""

    def __init__(self):
        self.calls, self.routes = [], {}
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                owner.answer(self)

            do_POST = do_DELETE = do_GET

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.server.server_port

    def on(self, method, path, *answers):
        """Answer a route with (status, body) pairs in turn, the last one again; a function gets the call."""
        self.routes[(method, path)] = list(answers)

    def answer(self, handler):
        length = int(handler.headers.get("Content-Length") or 0)
        raw = handler.rfile.read(length) if length else b""
        call = {"method": handler.command, "path": handler.path, "body": json.loads(raw.decode("utf8")) if raw else None,
                "session": handler.headers.get("Nexus-Session"), "write": handler.headers.get("Idempotency-Key"),
                "token": (handler.headers.get("CF-Access-Client-Id"), handler.headers.get("CF-Access-Client-Secret"))}
        self.calls.append(call)
        answers = self.routes.get((handler.command, handler.path))
        if not answers:
            status, payload = 404, {"status": 404, "code": "not_found", "detail": "no such path"}
        else:
            status, payload = answers.pop(0) if len(answers) > 1 else answers[0]
            if callable(status):
                status, payload = status(call)
        data = json.dumps(payload).encode("utf8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json" if status < 400 else "application/problem+json")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def problem(status, code, **members):
    body = {"type": "about:blank", "title": "Refused", "status": status, "code": code, "detail": "Synthetic " + code + "."}
    body.update(members)
    return status, body


class RevisionCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="corthex-revision-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.home = self.base / "home"
        (self.home / ".corthex").mkdir(parents=True)
        self.repo = self.base / "work" / "acme"
        self.settings("acme")
        self.peer = Peer()
        self.addCleanup(self.peer.close)

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False), encoding="utf8")

    def settings(self, name, folder=None, **fields):
        folder = folder or self.repo
        (folder / ".git").mkdir(parents=True, exist_ok=True)
        value = {"name": name, "title": "Synthetic project"}
        value.update(fields)
        self.write(folder / ".corthex/project.json", value)
        return folder

    def profile(self, url=None, push=("acme",)):
        nexus = {"push": list(push)}
        if url is not False:
            nexus["url"] = url or self.peer.url
        self.write(self.home / ".corthex/profile.json", {"nexus": nexus})

    def register(self, name="acme", folder=None):
        self.write(self.home / ".corthex/projects.json", {"projects": [{"name": name, "path": str(folder or self.repo)}]})

    def seed_write(self, project="acme"):
        """One waiting reply in the outbox, in the contract's OutboxFile form."""
        made = "2099-01-01T00:00:00.000Z"
        path = self.home / ".corthex/hub/outbox" / project / ("20990101T000000000Z.nw_000000000001.json")
        self.write(path, {"format": 1, "write": "nw_000000000001", "project": project, "request": "reply",
                          "path": "/api/spaces/" + project + "/comments/nc_" + "a" * 12 + "/replies",
                          "session": "s-1", "made": made, "body": {"text": "Waiting reply"}, "tries": 0})
        return path

    def hub(self, *words, env=None, cwd=None, json_lines=True):
        git = shutil.which("git")
        folders = [str(Path(sys.executable).parent)] + ([str(Path(git).parent)] if git else [])
        environment = {"HOME": str(self.home), "USERPROFILE": str(self.home), "PATH": os.pathsep.join(folders),
                       "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1",
                       "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
                       "TEMP": str(self.base), "TMP": str(self.base)}
        for key in ("SystemRoot", "WINDIR", "SYSTEMROOT"):
            if os.name == "nt" and key in os.environ:
                environment[key] = os.environ[key]
        environment.update(env or {})
        argv = [sys.executable, "-B", str(SCRIPT), "--home", str(self.home)] + list(words) + (["--json"] if json_lines else [])
        result = subprocess.run(argv, cwd=str(cwd or self.repo), env=environment, capture_output=True, timeout=60)
        out, err = result.stdout.decode("utf8"), result.stderr.decode("utf8")
        for secret in TOKEN.values():
            self.assertNotIn(secret, out + err)
        if not json_lines:
            return result.returncode, out, err
        rows = [json.loads(line) for line in out.splitlines() if line.strip()]
        return result.returncode, rows, err


class SessionEnvironmentTest(RevisionCase):
    """TASK-288: a session's environment, and can-send (API-179, SPEC-190, SPEC-192)."""

    def test_TC_1663_can_send_done_the_session_can_send(self):
        self.profile(REMOTE)
        self.register()
        waiting = self.seed_write()
        code, rows, err = self.hub("can-send", "acme", env=TOKEN)
        self.assertEqual(code, 0, err)
        self.assertEqual(rows[0]["outcome"], "done")
        self.assertEqual(rows[0]["answer"], {"can_send": True, "missing": [], "expected": True, "source": "profile"})
        self.assertEqual(rows[0]["remarks"], [])
        self.assertEqual(self.peer.calls, [])
        self.assertTrue(waiting.is_file(), "can-send must not send the outbox")

    def test_TC_1664_can_send_done_each_thing_missing(self):
        self.register()
        cases = [({"push": ["acme"]}, TOKEN, ["nexus.url"]),
                 ({"url": "http://nexus.example.invalid", "push": ["acme"]}, TOKEN, ["nexus.url"]),
                 ({"url": REMOTE, "push": ["beta"]}, TOKEN, ["nexus.push"]),
                 ({"url": REMOTE, "push": ["acme"]}, {"CORTHEX_NEXUS_CLIENT_SECRET": TOKEN["CORTHEX_NEXUS_CLIENT_SECRET"]}, ["CORTHEX_NEXUS_CLIENT_ID"]),
                 ({"url": REMOTE, "push": ["acme"]}, {"CORTHEX_NEXUS_CLIENT_ID": TOKEN["CORTHEX_NEXUS_CLIENT_ID"]}, ["CORTHEX_NEXUS_CLIENT_SECRET"])]
        for nexus, env, missing in cases:
            with self.subTest(missing=missing, nexus=nexus):
                self.write(self.home / ".corthex/profile.json", {"nexus": nexus})
                code, rows, err = self.hub("can-send", "acme", env=env)
                self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
                self.assertEqual(rows[0]["answer"]["missing"], missing)
                self.assertFalse(rows[0]["answer"]["can_send"])
        self.assertEqual(self.peer.calls, [])

    def test_TC_1665_can_send_done_from_the_environment(self):
        cases = [({"CORTHEX_NEXUS_PUSH": "acme"}, ["CORTHEX_NEXUS_URL"]),
                 ({"CORTHEX_NEXUS_URL": REMOTE, "CORTHEX_NEXUS_PUSH": "beta"}, ["CORTHEX_NEXUS_PUSH"]),
                 ({"CORTHEX_NEXUS_URL": REMOTE, "CORTHEX_NEXUS_PUSH": "beta, acme"}, [])]
        for variables, missing in cases:
            with self.subTest(missing=missing):
                env = dict(TOKEN)
                env.update(variables)
                code, rows, err = self.hub("can-send", "acme", env=env)
                self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
                self.assertEqual(rows[0]["answer"]["source"], "environment")
                self.assertEqual(rows[0]["answer"]["missing"], missing)
                self.assertEqual(rows[0]["answer"]["can_send"], not missing)
        self.assertFalse((self.home / ".corthex/profile.json").exists())
        self.assertEqual(self.peer.calls, [])

    def test_TC_1666_can_send_done_expected_on_a_nexus_server_or_not(self):
        self.register()
        cases = [({"on_nexus": True}, ["beta"], True), ({}, ["acme"], True), ({}, ["beta"], False),
                 # Another form than a boolean counts as not set.
                 ({"on_nexus": "yes"}, ["beta"], False)]
        for fields, push, expected in cases:
            with self.subTest(fields=fields, push=push):
                self.settings("acme", **fields)
                self.profile(REMOTE, push)
                code, rows, err = self.hub("can-send", "acme", env=TOKEN)
                self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
                self.assertIs(rows[0]["answer"]["expected"], expected)

    def test_TC_1667_can_send_done_a_server_on_the_device(self):
        self.profile()
        self.register()
        code, rows, err = self.hub("can-send", "acme")
        self.assertEqual(code, 0, err)
        self.assertEqual(rows[0]["answer"], {"can_send": True, "missing": [], "expected": True, "source": "profile"})
        self.assertEqual(self.peer.calls, [])

    def test_TC_1668_can_send_refused(self):
        self.profile(REMOTE)
        self.register()
        code, rows, _ = self.hub("can-send", "ghost", env=TOKEN)
        self.assertEqual((code, rows[0]["outcome"]), (1, "refused"))
        self.assertEqual(rows[0]["answer"], None)
        self.assertFalse((self.home / ".corthex/hub/outbox/ghost").exists())
        (self.home / ".corthex/profile.json").unlink()
        (self.home / ".corthex/projects.json").unlink()
        code, rows, _ = self.hub("can-send", "ghost", env=TOKEN)
        self.assertEqual((code, rows[0]["outcome"]), (1, "refused"))
        self.assertIn("not this checkout's project", rows[0]["failure"])
        self.assertEqual(self.peer.calls, [])

    def test_TC_1669_a_session_environment_reads_the_checkouts_own_project(self):
        self.peer.on("GET", "/api/spaces/acme/todo", (200, {"project": "acme", "default_commit": None, "session": "s-1", "read_at": None,
                      "comments": {"total": 0, "entries": []}, "discrepancies": {"total": 0, "entries": []},
                      "reflections": {"total": 0, "entries": []}, "checkpoints": {"total": 0, "entries": []},
                      "waiting_for_user": 0, "taken": 0}))
        env = dict(TOKEN, CORTHEX_NEXUS_URL=self.peer.url, CORTHEX_NEXUS_PUSH="acme", CORTHEX_NEXUS_SESSION="s-1")
        code, rows, err = self.hub("todo", "acme", env=env)
        self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
        self.assertEqual([(c["method"], c["path"], c["session"], c["token"]) for c in self.peer.calls],
                         [("GET", "/api/spaces/acme/todo", "s-1", (TOKEN["CORTHEX_NEXUS_CLIENT_ID"], TOKEN["CORTHEX_NEXUS_CLIENT_SECRET"]))])
        self.assertTrue((self.home / ".corthex/hub/outbox/acme.guard").is_file())
        self.assertFalse((self.home / ".corthex/profile.json").exists())

    def test_TC_1670_a_session_environment_refuses_another_project(self):
        env = dict(TOKEN, CORTHEX_NEXUS_URL=self.peer.url, CORTHEX_NEXUS_PUSH="acme,beta")
        code, rows, _ = self.hub("push", "beta", env=env)
        self.assertEqual((code, rows[0]["outcome"]), (1, "refused"))
        self.assertTrue(rows[0]["failure"].startswith("not this checkout's project"))
        self.assertIn("acme", rows[0]["failure"])
        self.assertIn("beta", rows[0]["failure"])
        self.assertEqual(self.peer.calls, [])

    def test_TC_1671_a_session_environment_refuses_without_a_project(self):
        env = dict(TOKEN, CORTHEX_NEXUS_URL=self.peer.url, CORTHEX_NEXUS_PUSH="acme")
        empty = self.base / "work" / "empty"
        (empty / ".git").mkdir(parents=True)
        nameless = self.settings("Not A Name", self.base / "work" / "nameless")
        for folder in (empty, nameless):
            with self.subTest(folder=folder.name):
                code, rows, _ = self.hub("todo", "acme", env=env, cwd=folder)
                self.assertEqual((code, rows[0]["outcome"], rows[0]["failure"]), (1, "refused", "no project in this checkout"))
        self.assertEqual(self.peer.calls, [])

    def test_TC_1672_a_session_environment_refuses_a_project_not_in_its_push_list(self):
        self.settings("other")
        env = dict(TOKEN, CORTHEX_NEXUS_URL=self.peer.url, CORTHEX_NEXUS_PUSH="acme")
        code, rows, err = self.hub("snapshot", env=env)
        self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
        self.assertTrue((self.home / ".corthex/hub/snapshots/other.json").is_file())
        for words in (["push"], ["todo", "other"]):
            with self.subTest(command=words[0]):
                code, rows, _ = self.hub(*words, env=env)
                self.assertEqual((code, rows[0]["outcome"], rows[0]["failure"]), (1, "refused", "not in CORTHEX_NEXUS_PUSH"))
        self.assertEqual(self.peer.calls, [])

    def test_TC_1673_the_push_lists_variable_is_ignored_with_a_profile(self):
        self.profile()
        self.register()
        self.peer.on("GET", "/api/spaces/acme/todo", problem(404, "space_not_found"))
        env = dict(CORTHEX_NEXUS_PUSH="beta")
        code, rows, err = self.hub("todo", "acme", env=env)
        self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
        self.assertEqual(rows[0]["remarks"], ["push-variable-ignored"])
        code, rows, _ = self.hub("todo", "beta", env=env)
        self.assertEqual((code, rows[0]["failure"]), (1, "not in nexus.push"))
        code, out, _ = self.hub("todo", "acme", env=env, json_lines=False)
        self.assertIn("  push-variable-ignored: CORTHEX_NEXUS_PUSH is ignored", out)
        self.assertEqual([c["path"] for c in self.peer.calls], ["/api/spaces/acme/todo"] * 2)

    def test_on_nexus_in_another_form_is_a_warning_of_the_snapshot(self):
        self.register()
        self.settings("acme", on_nexus="yes")
        code, rows, err = self.hub("snapshot", "acme")
        self.assertEqual(code, 0, err)
        checks = [c for c in rows[0]["answer"]["snapshot"]["checks"] if c["rule"] == "on-nexus-invalid"]
        self.assertEqual([(c["level"], c["message"]) for c in checks], [("warn", "on_nexus is not true or false, so it counts as not set")])
        self.settings("acme", on_nexus=False)
        code, rows, err = self.hub("snapshot", "acme")
        self.assertFalse([c for c in rows[0]["answer"]["snapshot"]["checks"] if c["rule"] == "on-nexus-invalid"])


if __name__ == "__main__":
    unittest.main()
