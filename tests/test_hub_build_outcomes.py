"""Build's three original CLI outcomes, in plain and explicit JSON modes.

The existing test_hub*.py discovery runs these six methods on every hosted
compatibility cell. All homes/projects are synthetic. This tests a local HTML
builder, not a deployed NEXUS handler, Access account or browser rendering.
"""
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

import hub_cli_fixture as fixture

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "qa-build-fixture"
PRIVATE_MARKER = fixture.PRIVATE_MARKER
ENVELOPE = {"command", "project", "outcome", "answer", "problem", "failure", "outbox"}


def file_state(folder):
    """Compare effects without retaining fixture paths or file bodies."""
    return {str(path.relative_to(folder)).replace("\\", "/"): fixture.sha(path.read_bytes())
            for path in folder.rglob("*") if path.is_file()}


class LocalPeer(http.server.BaseHTTPRequestHandler):
    """An unexpected loopback request must fail the test, never simulate failure."""
    requests = []

    def unexpected(self):
        type(self).requests.append(self.command)
        payload = b'{"code":"unexpected_build_request"}'
        self.send_response(418)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    do_GET = do_POST = do_HEAD = do_DELETE = do_PUT = unexpected

    def log_message(self, *args):
        pass


class HubBuildOutcomeTest(unittest.TestCase):
    observations = {}

    @classmethod
    def setUpClass(cls):
        cls.git, cls.runtime_before = fixture.verify_runtime(ROOT)
        if not cls.git or not Path(cls.git).is_absolute() or not Path(cls.git).is_file():
            raise AssertionError("an installed absolute Git executable is required")
        cls.script = ROOT / fixture.PREFIX / "hub.py"
        cls.child = ROOT / "tests" / "fixtures" / "hub_cli" / "child.py"
        cls.observations = {}
        LocalPeer.requests = []
        cls.peer = http.server.ThreadingHTTPServer(("127.0.0.1", 0), LocalPeer)
        cls.peer.daemon_threads = True
        cls.thread = threading.Thread(target=cls.peer.serve_forever,
                                      kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.close_peer)

    @classmethod
    def close_peer(cls):
        cls.peer.shutdown()
        cls.peer.server_close()
        cls.thread.join(timeout=2)

    @classmethod
    def tearDownClass(cls):
        _, cls.runtime_after = fixture.verify_runtime(ROOT)
        if cls.runtime_before != cls.runtime_after:
            raise AssertionError("build tests changed the pinned runtime")

    def check(self, label, actual, expected=True):
        # Existing helper projects unexpected strings to hashes and raises only
        # the assertion label; failed CI must not print raw fixture output/home.
        fixture.check(self.record["checks"], label, actual, expected)

    def setUp(self):
        self.record = {"method": self._testMethodName, "checks": [], "phases": [],
                       "sourceVerdictChanged": False, "fullTcPassClaimed": False,
                       "scope": "actual local CLI and owned files; no product server/browser"}
        type(self).observations[self._testMethodName] = self.record
        self.temporary = tempfile.TemporaryDirectory(prefix="corthex-build-")
        self.base = Path(self.temporary.name).resolve()
        self.temp_parent = Path(tempfile.gettempdir()).resolve()
        self.addCleanup(self.clean_owned_temporary)
        self.check("temporary fixture has owned absolute target",
                   self.base.parent == self.temp_parent and self.base.name.startswith("corthex-build-"))
        self.home, self.repo, self.temp = self.base / "home", self.base / "project", self.base / "temp"
        for path in (self.home / ".corthex", self.repo / ".corthex", self.temp):
            path.mkdir(parents=True)
        self.env = fixture.child_env(self.home, self.temp, self.git)
        self.env["GIT_ALLOW_PROTOCOL"] = ""
        self.env["QA_BUILD_SENTINEL"] = PRIVATE_MARKER
        self.check("child environment has no service credentials",
                   not any(key.startswith(("CORTHEX_NEXUS_", "NEXUS_DEV_")) for key in self.env))
        self.check("child PATH contains only installed absolute folders",
                   all(Path(part).is_absolute() and Path(part).resolve() != self.repo
                       for part in self.env["PATH"].split(os.pathsep)))
        template, hooks = self.base / "git-empty-template", self.base / "git-empty-hooks"
        template.mkdir()
        hooks.mkdir()
        self.git_run("init", "--initial-branch=main", "--template=" + str(template), str(self.repo))
        fixture.write_json(self.repo / ".corthex" / "project.json",
                           {"name": PROJECT, "title": "Synthetic local build", "team": False})
        doc = self.repo / "docs" / "02-prd" / "requirements.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("# Synthetic requirements\n\n## REQ-001\n\nLocal build fixture.\n", encoding="utf8")
        self.git_run("-C", str(self.repo), "add", ".")
        self.git_run("-C", str(self.repo), "-c", "core.hooksPath=" + str(hooks),
                     "-c", "user.name=QA Fixture", "-c", "user.email=qa@example.com",
                     "commit", "-m", "Synthetic local build fixture")
        self.git_run("-C", str(self.repo), "config", "remote.origin.url",
                     "https://github.com/example/qa-build-fixture")
        self.git_run("-C", str(self.repo), "update-ref", "refs/remotes/origin/main", "HEAD")
        self.git_run("-C", str(self.repo), "symbolic-ref", "refs/remotes/origin/HEAD",
                     "refs/remotes/origin/main")
        fixture.write_json(self.home / ".corthex" / "projects.json",
                           {"projects": [{"name": PROJECT, "path": str(self.repo)}]})
        fixture.write_json(self.home / ".corthex" / "profile.json",
                           {"language": "en", "nexus": {"url": "http://127.0.0.1:" +
                            str(self.peer.server_port), "push": [PROJECT]}})

    def clean_owned_temporary(self):
        resolved = Path(self.temporary.name).resolve()
        if resolved != self.base or resolved.parent != self.temp_parent or not resolved.name.startswith("corthex-build-"):
            raise AssertionError("refusing cleanup outside the exact owned temporary fixture")
        self.temporary.cleanup()

    def git_run(self, *words):
        result = subprocess.run([self.git] + list(words), cwd=str(self.base), env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.check("synthetic local Git setup succeeds", result.returncode, 0)

    def invoke(self, words, expected_exit, mode, label):
        guard_file = self.base / ("guard-%d.json" % len(self.record["phases"]))
        before = len(LocalPeer.requests)
        args = [sys.executable, "-I", "-S", "-B", "-X", "utf8", str(self.child),
                "--hub", str(self.script), "--port", str(self.peer.server_port),
                "--guard-receipt", str(guard_file), "--", "--home", str(self.home)] + words
        process = subprocess.run(args, cwd=str(self.repo), env=self.env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        stdout, stderr = process.stdout.decode("utf8"), process.stderr.decode("utf8")
        guard = json.loads(guard_file.read_text(encoding="utf8")) if guard_file.is_file() else None
        self.record["phases"].append({"label": label, "requestedOutput": mode,
            "actualExit": process.returncode, "stdoutBytes": len(process.stdout),
            "stderrBytes": len(process.stderr), "stdoutSha256": fixture.sha(process.stdout),
            "stderrSha256": fixture.sha(process.stderr), "networkGuard": guard,
            "rawStreamsPersisted": False})
        self.check(label + ": exact exit", process.returncode, expected_exit)
        self.check(label + ": no sensitive fixture phrase", PRIVATE_MARKER not in stdout + stderr)
        self.check(label + ": no traceback", "Traceback" not in stdout + stderr)
        self.check(label + ": no HTTP request", len(LocalPeer.requests) - before, 0)
        self.check(label + ": socket guard receipt", guard is not None)
        for key in ("allowedLoopbackConnections", "blockedConnectionAttempts", "blockedResolutionAttempts"):
            self.check(label + ": " + key, guard[key], 0)
        if expected_exit == 2:
            self.check(label + ": argparse stdout empty", stdout, "")
            self.check(label + ": argparse diagnostic retained", "usage:" in stderr and "error:" in stderr)
            self.check(label + ": invalid build option named", "--fixture-build-invalid" in stderr)
            return None
        if mode == "json":
            try:
                rows = [json.loads(line) for line in stdout.splitlines() if line.strip()]
            except ValueError:
                rows = []
            self.check(label + ": one JSON envelope", len(rows), 1)
            row = rows[0]
            self.check(label + ": envelope keys", sorted(row), sorted(ENVELOPE))
            self.check(label + ": build command", row.get("command"), "build")
            self.check(label + ": synthetic project", row.get("project"), PROJECT)
            self.check(label + ": outcome", row.get("outcome"), "done" if expected_exit == 0 else "failed")
            self.check(label + ": no queued envelope", row.get("outbox"), {"sent": 0, "dropped": 0, "waiting": 0})
            self.check(label + ": fixture home redacted", str(self.home).lower() not in stdout.lower())
            self.check(label + ": JSON stderr empty", stderr, "")
            if expected_exit == 1:
                self.check(label + ": local failure described", bool(row.get("failure")))
                self.check(label + ": failed answer empty", row.get("answer"), None)
            return row
        if expected_exit == 1:
            self.check(label + ": plain failure stdout empty", stdout, "")
            self.check(label + ": plain local failure diagnostic", stderr.startswith("hub.py build: "))
            self.check(label + ": failure home redacted", str(self.home).lower() not in stderr.lower())
        else:
            self.check(label + ": plain count line", any(line.startswith(PROJECT + ": ") for line in stdout.splitlines()))
            self.check(label + ": documented plain path line",
                       "Hub page: " + str(self.home / ".corthex" / "hub" / "index.html") in stdout)
            self.check(label + ": plain success stderr empty", stderr, "")
        return None

    def no_queue(self):
        self.check("no project outbox file", len(fixture.queue_files(self.home, PROJECT)), 0)
        self.check("no other queued file", sum(1 for path in self.home.rglob("*")
                   if path.is_file() and "outbox" in path.relative_to(self.home).parts), 0)

    def read_page(self):
        output = self.home / ".corthex" / "hub" / "index.html"
        self.check("HTML actually exists", output.is_file())
        text = output.read_text(encoding="utf8")
        marker = '<script id="hub-data" type="application/json">'
        self.check("one page bootstrap", text.count(marker), 1)
        self.check("one HTML document", text.lower().count("<!doctype html>"), 1)
        start = text.index(marker) + len(marker)
        data = json.loads(text[start:text.index("</script>", start)])
        self.check("documented page schema", data["schema"], "corthex-hub-page/0.2")
        self.check("local page origin", data["origin"], "local")
        self.check("local page has no server spaces", data["spaces"], {})
        self.check("one synthetic project", [item["project"]["name"] for item in data["projects"]], [PROJECT])
        return data

    def done(self, mode):
        before = file_state(self.repo)
        words = ["build", PROJECT] + (["--json"] if mode == "json" else [])
        row = self.invoke(words, 0, mode, "initial")
        data = self.read_page()
        snapshot = self.home / ".corthex" / "hub" / "snapshots" / (PROJECT + ".json")
        self.check("saved snapshot exists", snapshot.is_file())
        cached = snapshot.read_bytes()
        if row is not None:
            self.check("JSON summary matches actual page", row["answer"]["summary"], data["projects"][0]["summary"])
        files = set(file_state(self.home))
        self.invoke(words + ["--no-scan"], 0, mode, "repeat-no-scan")
        self.read_page()
        self.check("repeat does not duplicate file names", sorted(file_state(self.home)), sorted(files))
        self.check("repeat preserves saved snapshot", snapshot.read_bytes() == cached)
        self.check("one snapshot after repeat", len(list(snapshot.parent.glob("*.json"))), 1)
        self.check("no temporary write remains", len(list(self.home.rglob("*.tmp"))), 0)
        self.check("project is read-only", file_state(self.repo), before)
        self.no_queue()

    def invalid(self, mode):
        before, project_before = file_state(self.home), file_state(self.repo)
        words = ["build", PROJECT, "--no-scan"] + (["--json"] if mode == "json" else [])
        self.invoke(words + ["--fixture-build-invalid=" + PRIVATE_MARKER], 2, mode, "invalid")
        self.check("invalid command changes no home file", file_state(self.home), before)
        self.check("invalid command changes no project file", file_state(self.repo), project_before)
        self.check("invalid command creates no page", not (self.home / ".corthex" / "hub" / "index.html").exists())
        self.no_queue()

    def failed(self, mode):
        # Prepare a genuine cached snapshot/page. The failed build uses --no-scan
        # so only its output write can fail; no network exception is injected.
        self.invoke(["build", PROJECT], 0, "plain", "prepare-cached-source")
        self.read_page()
        obstruction = self.home / ".corthex" / PRIVATE_MARKER
        obstruction.write_text("Synthetic regular-file parent.\n", encoding="utf8")
        target = obstruction / "index.html"
        before, project_before = file_state(self.home), file_state(self.repo)
        words = ["build", PROJECT, "--no-scan", "--out", str(target)] + (["--json"] if mode == "json" else [])
        self.invoke(words, 1, mode, "real-local-write-failure")
        self.check("failure retains actual regular-file obstruction", obstruction.is_file())
        self.check("failed target was not created", not target.exists())
        self.check("failure preserves home/page/source bytes", file_state(self.home), before)
        self.check("failure preserves project bytes", file_state(self.repo), project_before)
        self.no_queue()

    def test_TC_1145_build_done_plain(self):
        self.done("plain")

    def test_TC_1145_build_done_json(self):
        self.done("json")

    def test_TC_1146_build_command_line_invalid_plain(self):
        self.invalid("plain")

    def test_TC_1146_build_command_line_invalid_json(self):
        self.invalid("json")

    def test_TC_1147_build_failed_plain(self):
        self.failed("plain")

    def test_TC_1147_build_failed_json(self):
        self.failed("json")


if __name__ == "__main__":
    unittest.main()
