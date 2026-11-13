"""The hub's commands for NEXUS's design revision (0.4.0), one method per case of its stage 12.

Each case runs the actual hub.py in a child process, with an isolated home, a synthetic project
checkout and a scripted HTTP peer on this device. No real server, service token or network is
used; the token values are synthetic. The method names keep the QA cases' TC IDs.
"""
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "plugins/corthex-nexus/skills/corthex-hub/scripts/hub.py"
TOKEN = {"CORTHEX_NEXUS_CLIENT_ID": "synthetic-client-id", "CORTHEX_NEXUS_CLIENT_SECRET": "synthetic-client-secret"}
REMOTE = "https://nexus.example.invalid"
# The contract's Time and SessionLabel, which the session reads file uses (SessionReads).
TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z\Z")
LABEL = re.compile(r"[A-Za-z0-9._:-]{1,100}\Z")


def utc(seconds=0):
    """A time in the contract's Time form, the given seconds from now by this device's clock."""
    moment = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def session_reads_valid(data, project):
    """The contract's SessionReads, with TBL-125's one entry for each session, the newest first."""
    if not (isinstance(data, dict) and set(data) == {"format", "project", "reads"} and type(data["format"]) is int and
            data["format"] == 1 and data["project"] == project and isinstance(data["reads"], list)):
        return False
    for entry in data["reads"]:
        if not (isinstance(entry, dict) and "at" in entry and set(entry) <= {"session", "at"} and
                isinstance(entry["at"], str) and TIME.fullmatch(entry["at"]) and
                ("session" not in entry or isinstance(entry["session"], str) and LABEL.fullmatch(entry["session"]))):
            return False
    times, sessions = [entry["at"] for entry in data["reads"]], [entry.get("session") for entry in data["reads"]]
    return times == sorted(times, reverse=True) and len(set(sessions)) == len(sessions)


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


class Todo:
    """A synthetic space's agent to-do, answered as the built contract does, with read_at by this device's clock.

    Its entries hold only their IDs and the times of the unread rule, which is what the hub reads of them.
    """

    TIMES = {"comments": "last_at", "discrepancies": "opened_at", "reflections": "made_at", "checkpoints": "passed_at"}

    def __init__(self):
        self.lists = {key: [] for key in self.TIMES}
        self.with_read_at, self.answered = True, []

    def add(self, kind, ident, when, **fields):
        entry = {"id": ident, self.TIMES[kind]: when}
        entry.update(fields)
        self.lists[kind].append(entry)
        return ident

    def __call__(self, call):
        read_at = utc()
        self.answered.append((call["session"], read_at))
        answer = {"project": "acme", "default_commit": None, "session": call["session"]}
        if self.with_read_at:
            answer["read_at"] = read_at
        answer.update({key: {"total": len(entries), "entries": list(entries)} for key, entries in self.lists.items()})
        answer.update(waiting_for_user=0, taken=0)
        return 200, answer


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

    def start(self, *words, env=None, cwd=None, json_lines=True):
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
        return subprocess.Popen(argv, cwd=str(cwd or self.repo), env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def finish(self, process, json_lines=True):
        try:
            raw_out, raw_err = process.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise
        out, err = raw_out.decode("utf8"), raw_err.decode("utf8")
        for secret in TOKEN.values():
            self.assertNotIn(secret, out + err)
        if not json_lines:
            return process.returncode, out, err
        rows = [json.loads(line) for line in out.splitlines() if line.strip()]
        return process.returncode, rows, err

    def hub(self, *words, env=None, cwd=None, json_lines=True):
        return self.finish(self.start(*words, env=env, cwd=cwd, json_lines=json_lines), json_lines)

    def git(self, *words):
        program = shutil.which("git")
        if program is None:
            self.skipTest("Git is not installed")
        env = {"HOME": str(self.home), "USERPROFILE": str(self.home), "PATH": os.environ.get("PATH", ""),
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0",
               "GIT_AUTHOR_NAME": "Fixture author", "GIT_AUTHOR_EMAIL": "fixture@example.com",
               "GIT_COMMITTER_NAME": "Fixture author", "GIT_COMMITTER_EMAIL": "fixture@example.com"}
        for key in ("SystemRoot", "WINDIR", "SYSTEMROOT"):
            if os.name == "nt" and key in os.environ:
                env[key] = os.environ[key]
        result = subprocess.run([program, "-C", str(self.repo)] + list(words), env=env, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf8", "replace"))
        return result.stdout.decode("utf8").strip()

    def commit(self, message):
        self.write(self.repo / "notes.md", message + "\n")
        self.git("add", ".")
        self.git("commit", "--no-verify", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def checkout(self):
        """Make the project's folder a Git repository with a first commit (SPEC-105 finds its default branch by publish)."""
        shutil.rmtree(str(self.repo / ".git"))
        self.git("init", "-q")
        self.git("symbolic-ref", "HEAD", "refs/heads/main")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", str(self.base / "no-hooks"))
        self.git("config", "remote.origin.url", "https://example.invalid/acme.git")
        return self.commit("start")

    def publish(self, commit):
        """The remote's default branch at the commit, as a fetch and git remote set-head leave it."""
        self.git("update-ref", "refs/remotes/origin/main", commit)
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")


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


class SessionReadsTest(RevisionCase):
    """TASK-289: the session's reads and todo --if-due (API-138, SPEC-191, SPEC-187, TBL-125)."""

    def setUp(self):
        super().setUp()
        self.reads_path = self.home / ".corthex/hub/reads/acme.json"
        self.space = Todo()
        self.peer.on("GET", "/api/spaces/acme/todo", (self.space, None))
        self.profile()
        self.register()

    def kept(self, *reads):
        self.write(self.reads_path, {"format": 1, "project": "acme", "reads": list(reads)})

    def reads(self):
        data = json.loads(self.reads_path.read_text(encoding="utf8"))
        self.assertTrue(session_reads_valid(data, "acme"), data)
        return data

    def test_TC_1691_todo_done_the_sessions_read_is_kept(self):
        first = [self.space.add("comments", "nc_" + "a" * 12, utc(-120)),
                 self.space.add("discrepancies", "nd_" + "c" * 12, utc(-90)),
                 self.space.add("reflections", "ne_" + "d" * 12, utc(-60)),
                 self.space.add("checkpoints", "nk_" + "e" * 12, utc(-30), state="passed", withdrawn_at=None)]
        code, rows, err = self.hub("todo", "acme", "--session", "s-1")
        self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
        read_1 = self.space.answered[-1][1]
        self.assertEqual(self.reads(), {"format": 1, "project": "acme", "reads": [{"session": "s-1", "at": read_1}]})
        self.assertEqual((rows[0]["read"], rows[0]["since"]), (True, None))
        self.assertEqual(rows[0]["new"], {"comments": [first[0]], "discrepancies": [first[1]], "reflections": [first[2]], "checkpoints": [first[3]]})
        self.assertEqual(rows[0]["remarks"], [])
        # Written between the two reads: a comment, and the withdrawal of a checkpoint passed before the first.
        later = [self.space.add("comments", "nc_" + "b" * 12, utc()),
                 self.space.add("checkpoints", "nk_" + "f" * 12, utc(-3600), state="withdrawn", withdrawn_at=utc())]
        code, rows, err = self.hub("todo", "acme", "--session", "s-1")
        self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
        read_2 = self.space.answered[-1][1]
        self.assertEqual((rows[0]["read"], rows[0]["since"]), (True, read_1))
        self.assertEqual(rows[0]["new"], {"comments": [later[0]], "discrepancies": [], "reflections": [], "checkpoints": [later[1]]})
        self.assertEqual(self.reads()["reads"], [{"session": "s-1", "at": read_2}])
        code, out, err = self.hub("todo", "acme", "--session", "s-1", json_lines=False)
        self.assertEqual(code, 0, err)
        self.assertIn("\n  read: yes\n  since: " + read_2 + "\n  new: ", out)
        self.assertEqual([(c["method"], c["path"], c["session"]) for c in self.peer.calls], [("GET", "/api/spaces/acme/todo", "s-1")] * 3)

    def test_TC_1692_todo_failed_nothing_is_kept(self):
        closed = socket.socket()
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]
        closed.close()
        self.profile("http://127.0.0.1:%d" % port)
        self.kept({"session": "s-1", "at": utc(-25 * 3600)})
        before = self.reads_path.read_bytes()
        for words in ([], ["--if-due"]):
            with self.subTest(words=words):
                code, rows, _ = self.hub("todo", "acme", "--session", "s-1", *words)
                self.assertEqual((code, rows[0]["outcome"], rows[0]["failure"]), (1, "failed", "no network"))
                self.assertEqual((rows[0]["read"], rows[0]["answer"], rows[0]["new"]), (False, None, None))
                self.assertEqual(self.reads_path.read_bytes(), before)

    def test_TC_1693_todo_if_due_done_not_due(self):
        waiting = self.seed_write()
        # 23 and 2 hours old, and half an hour ahead, which a clock set a little wrong gives.
        for seconds in (-23 * 3600, -2 * 3600, 30 * 60):
            with self.subTest(seconds=seconds):
                at = utc(seconds)
                self.kept({"session": "s-1", "at": at})
                code, rows, err = self.hub("todo", "acme", "--session", "s-1", "--if-due")
                self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
                self.assertEqual((rows[0]["read"], rows[0]["answer"], rows[0]["since"], rows[0]["new"]), (False, None, at, None))
                self.assertEqual(rows[0]["outbox"], {"sent": 0, "dropped": 0, "waiting": 0})
        self.assertEqual(self.peer.calls, [])
        self.assertTrue(waiting.is_file(), "a read that is not due sends no outbox")
        self.assertFalse((self.home / ".corthex/hub/outbox/acme.guard").exists())

    def test_TC_1694_todo_if_due_done_due(self):
        day = 24 * 3600
        cases = [("a read 25 hours old", [{"session": "s-1", "at": utc(-25 * 3600)}]),
                 ("no file", None),
                 ("a file that is not JSON", "{not json"),
                 ("a file of another project", {"format": 1, "project": "beta", "reads": [{"session": "s-1", "at": utc(-60)}]}),
                 ("an entry in another form", [{"session": "s-1", "at": "yesterday"}]),
                 ("no entry for the session", [{"session": "s-2", "at": utc(-60)}]),
                 # The device's clock a day ahead of the server's makes the kept time a day old,
                 # and a day behind makes it a day ahead.
                 ("the device's clock a day ahead", [{"session": "s-1", "at": utc(-day - 120)}]),
                 ("the device's clock a day behind", [{"session": "s-1", "at": utc(day)}])]
        for name, reads in cases:
            with self.subTest(name):
                if self.reads_path.exists():
                    self.reads_path.unlink()
                if isinstance(reads, list):
                    self.kept(*reads)
                elif reads is not None:
                    self.write(self.reads_path, reads)
                calls = len(self.peer.calls)
                code, rows, err = self.hub("todo", "acme", "--session", "s-1", "--if-due")
                self.assertEqual((code, rows[0]["outcome"], rows[0]["read"]), (0, "done", True), err)
                self.assertEqual(len(self.peer.calls), calls + 1)
                kept = self.reads()["reads"]
                self.assertEqual([entry for entry in kept if entry.get("session") == "s-1"], [{"session": "s-1", "at": self.space.answered[-1][1]}])
                if name == "no entry for the session":
                    self.assertEqual(kept[1:], reads, "another session's entry stays")

    def test_TC_1695_todo_two_hubs_at_once(self):
        processes = [self.start("todo", "acme", "--session", label) for label in ("s-1", "s-2")]
        for process in processes:
            code, rows, err = self.finish(process)
            # Whichever hub comes second may find the project's outbox lease taken; it then reads nothing.
            self.assertIn((code, rows[0]["outcome"], rows[0]["failure"]),
                          [(0, "done", None), (1, "failed", "another hub is sending this project's outbox")], err)
        answered = {}
        for session, at in self.space.answered:
            answered.setdefault(session, set()).add(at)
        reads = self.reads()["reads"]
        for entry in reads:
            self.assertIn(entry["at"], answered.get(entry.get("session"), set()), "no session takes another's read for its own")
        for label in ("s-1", "s-2"):
            with self.subTest(session=label):
                mine = [entry for entry in self.reads()["reads"] if entry.get("session") == label]
                calls = len(self.peer.calls)
                code, rows, err = self.hub("todo", "acme", "--session", label, "--if-due")
                self.assertEqual((code, rows[0]["outcome"], rows[0]["read"]), (0, "done", not mine), err)
                self.assertEqual(len(self.peer.calls), calls + (0 if mine else 1), "a session whose entry was lost reads again as due")
        self.assertEqual(sorted(entry["session"] for entry in self.reads()["reads"]), ["s-1", "s-2"])

    def test_TC_1696_todo_sessions_without_a_label_share_one_entry(self):
        code, rows, err = self.hub("todo", "acme")
        self.assertEqual((code, rows[0]["read"]), (0, True), err)
        self.assertEqual(self.reads()["reads"], [{"at": self.space.answered[-1][1]}])
        self.assertIsNone(self.peer.calls[-1]["session"])
        # An hour later, by the kept time, a session without a label is not due: it uses the same entry.
        hour_ago = utc(-3600)
        self.kept({"at": hour_ago})
        code, rows, err = self.hub("todo", "acme", "--if-due")
        self.assertEqual((code, rows[0]["outcome"], rows[0]["read"], rows[0]["since"]), (0, "done", False, hour_ago), err)
        self.assertEqual(len(self.peer.calls), 1)
        # A labeled session takes no read of the unlabeled entry for its own.
        code, rows, err = self.hub("todo", "acme", "--if-due", env={"CORTHEX_NEXUS_SESSION": "s-1"})
        self.assertEqual((code, rows[0]["read"]), (0, True), err)
        self.assertEqual(self.reads()["reads"], [{"session": "s-1", "at": self.space.answered[-1][1]}, {"at": hour_ago}])

    def test_a_server_of_before_keeps_no_read(self):
        self.space.with_read_at = False
        for words in ([], ["--if-due"], ["--if-due"]):
            with self.subTest(words=words):
                code, rows, err = self.hub("todo", "acme", "--session", "s-1", *words)
                self.assertEqual((code, rows[0]["outcome"], rows[0]["read"], rows[0]["since"], rows[0]["new"], rows[0]["remarks"]),
                                 (0, "done", True, None, None, ["server-older"]), err)
        self.assertEqual(len(self.peer.calls), 3)
        self.assertFalse(self.reads_path.exists())
        code, out, _ = self.hub("todo", "acme", "--session", "s-1", json_lines=False)
        self.assertIn("  server-older: the server is of before the design revision", out)

    def test_a_project_without_a_space_keeps_nothing(self):
        self.peer.on("GET", "/api/spaces/acme/todo", problem(404, "space_not_found"))
        for words in ([], ["--if-due"]):
            with self.subTest(words=words):
                code, rows, err = self.hub("todo", "acme", "--session", "s-1", *words)
                self.assertEqual((code, rows[0]["outcome"], rows[0]["read"], rows[0]["since"]), (0, "done", True, None), err)
                self.assertEqual(rows[0]["new"], {"comments": [], "discrepancies": [], "reflections": [], "checkpoints": []})
                self.assertEqual(rows[0]["answer"]["comments"], {"total": 0, "entries": []})
        self.assertEqual(len(self.peer.calls), 2)
        self.assertFalse(self.reads_path.exists())


class FirstPushTest(RevisionCase):
    """TASK-290: a project's first push only with --first (API-136, SPEC-111, REQ-107)."""

    HELD = "/api/snapshots/acme/held"

    def setUp(self):
        super().setUp()
        self.profile()
        self.register()
        self.peer.on("POST", "/api/snapshots", (201, {"project": "acme", "stored": True}))

    def posts(self):
        return [call["body"] for call in self.peer.calls if call["method"] == "POST"]

    def test_TC_1674_push_refused_the_first_push_waits(self):
        self.peer.on("GET", self.HELD, problem(404, "project_not_found"))
        code, rows, err = self.hub("push", "acme")
        self.assertEqual((code, rows[0]["outcome"], rows[0]["failure"]), (1, "refused", "first push needs --first"), err)
        code, out, _ = self.hub("push", "acme", json_lines=False)
        self.assertEqual(code, 1)
        self.assertIn("  first push needs --first\n  the first push of this project to this server waits for the user's yes", out)
        self.assertEqual([(c["method"], c["path"]) for c in self.peer.calls], [("GET", self.HELD)] * 2)
        self.assertEqual(list((self.home / ".corthex/hub/outbox").glob("acme/*.json")), [])

    def test_TC_1675_push_first_done(self):
        self.peer.on("GET", self.HELD, problem(404, "project_not_found"))
        code, rows, err = self.hub("push", "acme", "--first")
        self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
        self.assertEqual(rows[0]["answer"], {"project": "acme", "stored": True})
        self.assertEqual(len(self.posts()), 1)
        self.assertEqual(self.posts()[0]["project"]["name"], "acme")
        self.assertNotIn("replaces", self.posts()[0])

    def test_TC_1676_push_first_wrong_command_line(self):
        self.peer.on("GET", self.HELD, problem(404, "project_not_found"))
        for words in (["push", "--first"], ["push", "acme", "beta", "--first"]):
            with self.subTest(words=words):
                code, rows, err = self.hub(*words)
                self.assertEqual((code, rows), (2, []))
                self.assertIn("--first takes exactly one project", err)
        self.assertEqual(self.peer.calls, [])

    def test_TC_1677_push_first_on_a_project_that_the_server_holds(self):
        held = self.checkout()
        child = self.commit("next")
        self.publish(child)
        self.peer.on("GET", self.HELD, (200, {"project": "acme", "default_commit": held}))
        for words in (["push", "acme"], ["push", "acme", "--first"]):
            with self.subTest(words=words):
                code, rows, err = self.hub(*words)
                self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
        self.assertEqual([(body["replaces"], body["repos"]["."]["default"]["commit"]) for body in self.posts()], [(held, child)] * 2)

    def test_TC_1678_push_a_removed_project_is_a_first_push_again(self):
        self.peer.on("GET", self.HELD, (200, {"project": "acme", "default_commit": None}))
        code, rows, err = self.hub("push", "acme")
        self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
        # The user removes the project on the server; the server then holds no such project.
        self.peer.on("GET", self.HELD, problem(404, "project_not_found"))
        code, rows, _ = self.hub("push", "acme")
        self.assertEqual((code, rows[0]["outcome"], rows[0]["failure"]), (1, "refused", "first push needs --first"))
        code, rows, err = self.hub("push", "acme", "--first")
        self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
        self.assertEqual(len(self.posts()), 2)

    def test_TC_1679_push_dry_run_asks_the_server_nothing(self):
        self.peer.on("GET", self.HELD, problem(404, "project_not_found"))
        code, rows, err = self.hub("push", "acme", "--dry-run")
        self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
        self.assertEqual((rows[0]["answer"]["held_commit"], rows[0]["answer"]["first_push"]), ("checked when sent", "checked when sent"))
        code, out, _ = self.hub("push", "acme", "--dry-run", json_lines=False)
        self.assertEqual(code, 0)
        self.assertIn('"first_push": "checked when sent"', out)
        self.assertEqual(self.peer.calls, [])


if __name__ == "__main__":
    unittest.main()
