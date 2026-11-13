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


def text_of(lines, characters):
    """A request's text of the given lines and characters, in plain words that no redaction changes."""
    filler = "Stage 04 is ready for your checkpoint. "
    width = characters - (lines - 1)
    each, rest = divmod(width, lines)
    rows = [(filler * (each // len(filler) + 2))[:each + (1 if index < rest else 0)].rstrip(" ") or "x" for index in range(lines)]
    rows = [row + "." * (each + (1 if index < rest else 0) - len(row)) for index, row in enumerate(rows)]
    text = "\n".join(rows)
    assert len(text) == characters and text.count("\n") == lines - 1, (len(text), text.count("\n"))
    return text


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


class CheckpointRequestTest(RevisionCase):
    """TASK-291: a checkpoint request in form, after a read of the to-do (API-139, API-140, SPEC-197, SPEC-191, TC-1427, TC-1452)."""

    MADE = "nc_" + "q" * 12
    OPEN = "nc_" + "r" * 12
    TODO = "/api/spaces/acme/todo"
    COMMENTS = "/api/spaces/acme/comments"

    def setUp(self):
        super().setUp()
        self.reads_path = self.home / ".corthex/hub/reads/acme.json"
        self.box = self.home / ".corthex/hub/outbox/acme"
        self.replies = self.COMMENTS + "/" + self.OPEN + "/replies"
        self.space = Todo()
        self.peer.on("GET", self.TODO, (self.space, None))
        self.peer.on("POST", self.COMMENTS, (201, {"id": self.MADE, "state": "open", "asks": "checkpoint"}))
        self.peer.on("POST", self.replies, (201, {"comment": {"id": self.OPEN, "asks": "checkpoint"}, "reply": {"seq": 2}}))
        self.profile()
        self.register()
        self.kept(utc(-60))

    def kept(self, at):
        self.write(self.reads_path, {"format": 1, "project": "acme", "reads": [{"session": "s-1", "at": at}]})

    def request(self, *words, text="Stage 04 is ready for your checkpoint.\nLook at SPEC-194 first.", look="SPEC-194",
                command=("comment", "acme", "--stage", "04-functional-spec"), asks=True, json_lines=True, env=None):
        path = self.base / "request.txt"
        self.write(path, text)
        argv = list(command) + (["--asks", "checkpoint"] if asks else []) + ["--text-file", str(path), "--session", "s-1"]
        if look is not None:
            argv += ["--look-first", look]
        return self.hub(*(argv + list(words)), json_lines=json_lines, env=env)

    def posts(self):
        return [call for call in self.peer.calls if call["method"] == "POST"]

    @staticmethod
    def counts(row):
        return {key: row["outbox"][key] for key in ("sent", "dropped", "waiting")}

    @staticmethod
    def key(call):
        """The write ID that a call carries, without the quotes of its Idempotency-Key header."""
        return (call["write"] or "").strip('"')

    def waiting(self):
        return [json.loads(path.read_text(encoding="utf8")) for path in sorted(self.box.glob("*.json"))] if self.box.is_dir() else []

    def queue(self, write, body, made):
        """A checkpoint request that waits in the outbox, in the contract's OutboxFile form."""
        moment = datetime.strptime(made, "%Y-%m-%dT%H:%M:%S.%fZ")
        name = moment.strftime("%Y%m%dT%H%M%S") + ("%03d" % (moment.microsecond // 1000)) + "Z." + write + ".json"
        self.write(self.box / name, {"format": 1, "write": write, "project": "acme", "request": "comment", "path": self.COMMENTS,
                                     "session": "s-1", "made": made, "body": body, "tries": 1, "failure": "no network"})

    def test_TC_1697_comment_asks_checkpoint_done(self):
        text = text_of(10, 1200)
        code, rows, err = self.request(text=text)
        self.assertEqual((code, rows[0]["outcome"], rows[0]["failure"], rows[0]["remarks"]), (0, "done", None, []), err)
        self.assertEqual([(call["method"], call["path"]) for call in self.peer.calls], [("GET", self.TODO), ("POST", self.COMMENTS)])
        self.assertEqual(self.posts()[0]["body"], {"part": "", "stage": "04-functional-spec", "item": "", "text": text,
                                                   "asks": "checkpoint", "look_first": "SPEC-194"})
        self.assertEqual(self.posts()[0]["session"], "s-1")
        self.assertEqual(rows[0]["answer"]["id"], self.MADE)
        self.assertEqual((self.waiting(), self.counts(rows[0])), ([], {"sent": 1, "dropped": 0, "waiting": 0}))
        # The read before the request is now the session's last.
        self.assertEqual(json.loads(self.reads_path.read_text(encoding="utf8"))["reads"], [{"session": "s-1", "at": self.space.answered[-1][1]}])

    def test_TC_1698_the_three_forms_of_the_thing_to_look_at_first(self):
        cases = [("SPEC-194", [], "SPEC-194"),
                 ("https://example.invalid/review/7?tab=diff", [], "https://example.invalid/review/7?tab=diff"),
                 ("stage", ["--part", "orders"], self.peer.url + "/p/acme/orders/04-functional-spec"),
                 ("stage", [], self.peer.url + "/p/acme/_/04-functional-spec")]
        for look, words, sent in cases:
            with self.subTest(look=look, words=words):
                code, rows, err = self.request(*words, look=look)
                self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
                body = self.posts()[-1]["body"]
                self.assertEqual((body["look_first"], body["part"]), (sent, words[1] if words else ""))

    def test_TC_1699_wrong_command_line_out_of_form(self):
        # 1,196 characters as written and 1,201 once the token's value, pasted in by mistake, is masked as [redacted].
        masked = text_of(1, 1190) + " cid-1"
        cases = [("--item", dict(words=("--item", "SPEC-194")), "leave out --item"),
                 ("11 lines", dict(text=text_of(11, 300)), "the text has 11 lines and 300 characters"),
                 ("1,201 characters after redaction", dict(text=masked, env={"CORTHEX_NEXUS_CLIENT_ID": "cid-1"}),
                  "the text has 1 line and 1201 characters"),
                 ("no --look-first", dict(look=None), "add --look-first"),
                 ("--look-first without --asks checkpoint", dict(asks=False), "--look-first goes only with --asks checkpoint")]
        for name, options, said in cases:
            with self.subTest(name):
                words = options.pop("words", ())
                code, out, err = self.request(*words, json_lines=False, **options)
                self.assertEqual((code, out), (2, ""), err)
                self.assertIn(said, err)
        self.assertEqual((self.peer.calls, self.waiting()), ([], []))

    def test_TC_1452_a_request_of_twelve_lines_sends_nothing(self):
        code, out, err = self.request(text=text_of(12, 600), json_lines=False)
        self.assertEqual(code, 2, err)
        self.assertIn("shorten it to at most 10 lines and 1,200 characters", err)
        self.assertEqual((self.peer.calls, self.waiting()), ([], []))

    def test_TC_1427_the_to_do_is_read_first_whatever_the_time_of_the_last_read(self):
        # A read a minute old, two days old, an hour ahead, and none at all.
        for at in (utc(-60), utc(-2 * 24 * 3600), utc(3600), None):
            with self.subTest(at=at):
                if at is None:
                    self.reads_path.unlink()
                else:
                    self.kept(at)
                calls = len(self.peer.calls)
                code, rows, err = self.request()
                self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
                self.assertEqual([(call["method"], call["path"]) for call in self.peer.calls[calls:]],
                                 [("GET", self.TODO), ("POST", self.COMMENTS)])

    def test_TC_1700_refused_read_the_to_do_first(self):
        self.kept(utc(-600))
        # The user's reply on the stage's comment came after the session's read before.
        self.space.add("comments", self.OPEN, utc(-60), part="", stage="04-functional-spec")
        code, rows, err = self.request()
        self.assertEqual((code, rows[0]["outcome"], rows[0]["failure"]), (1, "refused", "read the to-do first"), err)
        self.assertEqual(rows[0]["new"], {"comments": [self.OPEN], "discrepancies": [], "reflections": [], "checkpoints": []})
        self.assertEqual((self.posts(), self.waiting()), ([], []))
        code, rows, err = self.request()
        self.assertEqual((code, rows[0]["outcome"], rows[0]["failure"]), (0, "done", None), err)
        self.assertEqual([call["path"] for call in self.posts()], [self.COMMENTS])

    def test_a_request_held_back_says_why_in_words(self):
        self.kept(utc(-600))
        self.space.add("discrepancies", "nd_" + "c" * 12, utc(-60))
        code, out, err = self.request(json_lines=False)
        self.assertEqual(code, 1, err)
        self.assertIn("acme: comment refused\n  read the to-do first\n  entries came in since the session's read before", out)
        self.assertIn('"discrepancies": ["nd_' + "c" * 12 + '"]', out)

    def test_TC_1701_done_sent_as_a_reply(self):
        self.peer.on("POST", self.COMMENTS, problem(409, "checkpoint_requested", comment=self.OPEN))
        code, rows, err = self.request()
        self.assertEqual((code, rows[0]["outcome"], rows[0]["remarks"]), (0, "done", ["sent-as-reply"]), err)
        first, second = self.posts()
        self.assertEqual((first["path"], second["path"]), (self.COMMENTS, self.replies))
        self.assertEqual(second["body"], {"text": first["body"]["text"], "asks": "checkpoint", "look_first": "SPEC-194"})
        self.assertNotEqual(self.key(second), self.key(first))
        self.assertEqual(second["session"], "s-1")
        self.assertEqual(rows[0]["answer"], {"comment": {"id": self.OPEN, "asks": "checkpoint"}, "reply": {"seq": 2}})
        self.assertEqual((self.waiting(), self.counts(rows[0])), ([], {"sent": 1, "dropped": 0, "waiting": 0}))
        code, out, _ = self.request(json_lines=False)
        self.assertIn("  sent-as-reply: the stage had an open checkpoint request, so the request went as a reply on it", out)
        # From the outbox: a request kept earlier goes the same way at the next contact.
        body = {"part": "", "stage": "04-functional-spec", "item": "", "text": "Kept request", "asks": "checkpoint", "look_first": "SPEC-194"}
        self.queue("nw_" + "k" * 12, body, utc(-300))
        calls = len(self.peer.calls)
        code, rows, err = self.hub("outbox", "acme", "--send")
        self.assertEqual((code, rows[0]["outcome"], rows[0]["remarks"]), (0, "done", ["sent-as-reply"]), err)
        sent = self.peer.calls[calls:]
        self.assertEqual([(call["path"], self.key(call) == "nw_" + "k" * 12) for call in sent], [(self.COMMENTS, True), (self.replies, False)])
        self.assertEqual(sent[1]["body"], {"text": "Kept request", "asks": "checkpoint", "look_first": "SPEC-194"})
        self.assertEqual(self.waiting(), [])
        self.assertFalse((self.home / ".corthex/hub/outbox/acme.order").exists())

    def test_TC_1702_queued(self):
        closed = socket.socket()
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]
        closed.close()
        # No answer to the read of the to-do: the request waits with its write ID.
        self.profile("http://127.0.0.1:%d" % port)
        code, rows, err = self.request()
        self.assertEqual((code, rows[0]["outcome"], rows[0]["failure"]), (3, "kept", "no network"), err)
        kept = self.waiting()
        self.assertEqual([(entry["request"], entry["body"]["look_first"]) for entry in kept], [("comment", "SPEC-194")])
        self.profile()
        code, rows, err = self.hub("outbox", "acme", "--send")
        self.assertEqual((code, rows[0]["outcome"], rows[0]["outbox"]["sent"]), (0, "done", 1), err)
        self.assertEqual([(call["path"], self.key(call)) for call in self.posts()], [(self.COMMENTS, kept[0]["write"])])
        self.hub("outbox", "acme", "--send")
        self.assertEqual(len(self.posts()), 1, "sent once")
        # The read answered and the write not: it waits again with its write ID.
        self.peer.on("POST", self.COMMENTS, problem(503, "unavailable"), (201, {"id": self.MADE, "state": "open"}))
        code, rows, err = self.request()
        self.assertEqual((code, rows[0]["outcome"], rows[0]["problem"]["status"]), (3, "kept", 503), err)
        kept = self.waiting()
        self.assertEqual(len(kept), 1)
        code, rows, err = self.hub("outbox", "acme", "--send")
        self.assertEqual((code, rows[0]["outcome"], rows[0]["outbox"]["sent"]), (0, "done", 1), err)
        self.assertEqual([self.key(call) for call in self.posts()[1:]], [kept[0]["write"]] * 2)
        self.assertEqual(self.waiting(), [])

    def test_TC_1703_reply_asks_again(self):
        # The user replied on the stage's request before the session's last read.
        self.space.add("comments", self.OPEN, utc(-120), part="", stage="04-functional-spec")
        code, rows, err = self.request(look="stage", command=("reply", "acme", self.OPEN))
        self.assertEqual((code, rows[0]["outcome"], rows[0]["remarks"]), (0, "done", []), err)
        self.assertEqual([(call["method"], call["path"]) for call in self.peer.calls], [("GET", self.TODO), ("POST", self.replies)])
        self.assertEqual(self.posts()[0]["body"], {"text": "Stage 04 is ready for your checkpoint.\nLook at SPEC-194 first.", "asks": "checkpoint",
                                                   "look_first": self.peer.url + "/p/acme/_/04-functional-spec"})
        self.assertEqual(rows[0]["answer"]["comment"], {"id": self.OPEN, "asks": "checkpoint"})

    def test_a_reply_reads_its_stage_from_the_server(self):
        self.peer.on("GET", self.COMMENTS + "/" + self.OPEN, (200, {"id": self.OPEN, "part": "orders", "stage": "05-erd", "replies": []}))
        code, rows, err = self.request(look="stage", command=("reply", "acme", self.OPEN))
        self.assertEqual((code, rows[0]["outcome"]), (0, "done"), err)
        self.assertEqual([call["path"] for call in self.peer.calls], [self.TODO, self.COMMENTS + "/" + self.OPEN, self.replies])
        self.assertEqual(self.posts()[0]["body"]["look_first"], self.peer.url + "/p/acme/orders/05-erd")

    def test_a_reply_whose_stage_cannot_be_read_keeps_nothing(self):
        said = "the comment's stage could not be read, so nothing was kept; send the request again"
        code, rows, err = self.request(look="stage", command=("reply", "acme", self.OPEN))
        self.assertEqual((code, rows[0]["outcome"], rows[0]["failure"]), (1, "failed", said), err)
        self.assertEqual((self.posts(), self.waiting()), ([], []))
        closed = socket.socket()
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]
        closed.close()
        self.profile("http://127.0.0.1:%d" % port)
        code, rows, err = self.request(look="stage", command=("reply", "acme", self.OPEN))
        self.assertEqual((code, rows[0]["outcome"], rows[0]["failure"]), (1, "failed", said), err)
        self.assertEqual(self.waiting(), [])
        # A reply with the stage's ID or address waits as any write does.
        code, rows, err = self.request(command=("reply", "acme", self.OPEN))
        self.assertEqual((code, rows[0]["outcome"]), (3, "kept"), err)

    def test_a_server_of_before_gets_the_old_form(self):
        self.space.with_read_at = False
        code, rows, err = self.request()
        self.assertEqual((code, rows[0]["outcome"], rows[0]["remarks"]), (0, "done", ["server-older"]), err)
        body = self.posts()[0]["body"]
        self.assertNotIn("look_first", body)
        self.assertEqual((body["text"], body["asks"]), ("Stage 04 is ready for your checkpoint.\nLook at SPEC-194 first.\nSPEC-194", "checkpoint"))

    def test_a_refused_read_sends_and_keeps_nothing(self):
        self.peer.on("GET", self.TODO, problem(403, "not_allowed"))
        code, rows, err = self.request()
        self.assertEqual((code, rows[0]["outcome"], rows[0]["problem"]["code"]), (1, "refused", "not_allowed"), err)
        self.assertEqual((self.posts(), self.waiting()), ([], []))


class RemoveTest(RevisionCase):
    """TASK-292: remove sends no removal; it reads the project's data and gives its address (API-137, API-177, SPEC-115, SPEC-202)."""

    DATA = "/api/spaces/acme/data"
    DRY_RUN = "/api/snapshots/acme/removal"

    def setUp(self):
        super().setUp()
        self.profile()
        self.register()

    @staticmethod
    def data():
        """A project's data in the contract's ProjectData form, with an entry of each open kind."""
        removal = {"project": "acme",
                   "deletes": {"snapshot": True, "space": True, "pictures": 2, "discrepancies": 1, "comments": 2, "replies": 1,
                               "decisions": 0, "proposals": 1, "edits": 1, "checkpoints": 1},
                   "open": {"comments": {"total": 2, "ids": ["nc_" + "a" * 12, "nc_" + "b" * 12]},
                            "proposals": {"total": 1, "ids": ["np_" + "c" * 12]},
                            "reflections": {"total": 1, "ids": ["ne_" + "d" * 12]},
                            "checkpoints": {"total": 1, "ids": ["nk_" + "e" * 12]}}}
        return {"project": "acme", "title": "Synthetic project", "repository": None, "commit": None, "revision": 4,
                "generated_at": "2026-11-13T09:00:00+09:00", "pushed_at": "2026-11-13T00:00:01.000Z", "space": True,
                "read_at": None, "read_session": None, "unread_since": None, "removal": removal}

    def test_TC_1688_remove_done_the_dry_run_and_the_address(self):
        answer = self.data()
        self.peer.on("GET", self.DATA, (200, answer))
        waiting = self.seed_write()
        for words in ([], ["--dry-run"]):
            with self.subTest(words=words):
                code, rows, err = self.hub("remove", "acme", *words)
                self.assertEqual((code, rows[0]["outcome"], rows[0]["remarks"]), (0, "done", []), err)
                self.assertEqual((rows[0]["answer"], rows[0]["address"]), (answer, self.peer.url + "/p/acme#data"))
        self.assertEqual([(call["method"], call["path"]) for call in self.peer.calls], [("GET", self.DATA)] * 2)
        self.assertTrue(waiting.is_file(), "the project's outbox stays")
        code, out, err = self.hub("remove", "acme", json_lines=False)
        self.assertEqual(code, 0, err)
        self.assertIn("\n  address: " + self.peer.url + "/p/acme#data\n  no removal was sent: the user removes the project", out)
        self.assertIn('"ids": [\n          "np_' + "c" * 12, out)

    def test_TC_1689_remove_done_nothing_to_remove(self):
        self.peer.on("GET", self.DATA, problem(404, "project_not_found"))
        code, rows, err = self.hub("remove", "acme")
        self.assertEqual((code, rows[0]["outcome"], rows[0]["answer"]), (0, "done", {"nothing_to_remove": True}), err)
        self.assertNotIn("address", rows[0])
        code, out, _ = self.hub("remove", "acme", json_lines=False)
        self.assertIn("  nothing to remove: the server holds no such project", out)
        self.assertEqual([call["method"] for call in self.peer.calls], ["GET", "GET"])

    def test_TC_1690_a_write_that_waits_for_a_removed_project(self):
        waiting = self.seed_write()
        replies = "/api/spaces/acme/comments/nc_" + "a" * 12 + "/replies"
        self.peer.on("POST", replies, problem(404, "project_not_found"))
        self.peer.on("GET", "/api/spaces/acme/todo", problem(404, "space_not_found"))
        code, rows, err = self.hub("todo", "acme", "--session", "s-1")
        self.assertEqual((code, rows[0]["outcome"], rows[0]["outbox"]["dropped"]), (0, "done", 1), err)
        self.assertEqual(rows[0]["outbox"]["notices"][0]["problem"]["code"], "project_not_found")
        self.assertFalse(waiting.exists())
        # The command goes on after the write is dropped.
        self.assertEqual([(call["method"], call["path"]) for call in self.peer.calls], [("POST", replies), ("GET", "/api/spaces/acme/todo")])

    def test_a_server_of_before_shows_its_dry_run(self):
        dry = self.data()["removal"]
        self.peer.on("GET", self.DRY_RUN, (200, dry))
        code, rows, err = self.hub("remove", "acme")
        self.assertEqual((code, rows[0]["outcome"], rows[0]["answer"], rows[0]["remarks"]), (0, "done", dry, ["server-older"]), err)
        self.assertNotIn("address", rows[0])
        self.assertEqual([call["path"] for call in self.peer.calls], [self.DATA, self.DRY_RUN])
        code, out, _ = self.hub("remove", "acme", json_lines=False)
        self.assertIn("  no removal was sent: this server has no project's data yet", out)
        self.peer.on("GET", self.DRY_RUN, problem(404, "project_not_found"))
        code, rows, err = self.hub("remove", "acme")
        self.assertEqual((code, rows[0]["answer"], rows[0]["remarks"]), (0, {"nothing_to_remove": True}, ["server-older"]), err)

    def test_a_refusal_is_reported_and_removes_nothing(self):
        self.peer.on("GET", self.DATA, problem(403, "not_allowed"))
        code, rows, err = self.hub("remove", "acme")
        self.assertEqual((code, rows[0]["outcome"], rows[0]["problem"]["code"]), (1, "refused", "not_allowed"), err)
        self.assertEqual([call["method"] for call in self.peer.calls], ["GET"])


if __name__ == "__main__":
    unittest.main()
