"""The original sixteen CLI criteria, with actual plain/JSON exits and effects.

Only installed Git, isolated files and the accepted loopback-only child/peer
are used. No production function is patched and no external HTTP is allowed.
The named methods preserve original TC IDs; newer59/build tests stay separate.
"""
import collections
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import hub_cli_fixture as fixture

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = json.loads((ROOT / "tests/fixtures/hub_cli/wire.json").read_text(encoding="utf8"))
PROJECT = BUNDLE["project"]
PRIVATE_MARKER = fixture.PRIVATE_MARKER
ENVELOPE = {"command", "project", "outcome", "answer", "problem", "failure", "outbox", "remarks"}
EMPTY_TODO = {key: {"total": 0, "entries": []}
              for key in ("comments", "discrepancies", "reflections", "checkpoints")}
EMPTY_TODO.update(waiting_for_user=0, taken=0)


def file_state(folder):
    return {str(path.relative_to(folder)).replace("\\", "/"): fixture.sha(path.read_bytes())
            for path in folder.rglob("*") if path.is_file()}


def home_data_state(home):
    # The native control guard and reserved admission-order sidecar are not
    # queued write bodies or project/profile data. Observe them separately.
    return {name: value for name, value in file_state(home).items()
            if name != ".corthex/hub/outbox/" + PROJECT + ".order" and
            not re.fullmatch(r"\.corthex/hub/record-locks/[0-9a-f]{64}\.guard", name)}


def string_values(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from string_values(key)
            yield from string_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from string_values(item)


def private_output_absent(value, home):
    """Compare decoded strings; JSON escaping must not hide a Windows path."""
    normalize = lambda text: re.sub(r"/+", "/", text.replace("\\", "/")).casefold()
    forbidden = (normalize(str(home)), normalize(PRIVATE_MARKER))
    return all(not any(part in normalize(text) for part in forbidden) for text in string_values(value))


def expected_recovery_fields(command):
    """Independent expectations for the exact CLI arguments in this fixture."""
    base, ids = "/api/spaces/" + PROJECT, BUNDLE["ids"]
    text = "Fixture text [redacted] ~"
    cases = {
        "comment": ("comment", "/comments", {"part": "sample", "stage": "05-erd", "item": "TBL-001", "text": text}),
        "reply": ("reply", "/comments/" + ids["c"] + "/replies", {"text": text}),
        "answered": ("answered", "/comments/" + ids["c"] + "/answered", {}),
        "decide": ("decision", "/comments/" + ids["c"] + "/decisions", {"link": "https://example.invalid/pr/1", "text": text}),
        "propose": ("proposal", "/proposals", {"part": "sample", "stage": "05-erd", "items": ["TBL-001"], "reason": text, "change": text}),
        "withdraw": ("withdraw-proposal", "/proposals/" + ids["p"] + "/withdraw", {}),
        "reflect": ("report-edit", "/edits/" + ids["e"] + "/report", {"event": "opened", "pull_request": "https://example.invalid/pr/1"}),
        "record": ("report-checkpoint", "/checkpoints/" + ids["k"] + "/report", {"event": "opened", "pull_request": "https://example.invalid/pr/1"}),
    }
    operation, suffix, body = cases[command]
    return {"format": 1, "project": PROJECT, "session": BUNDLE["session"], "tries": 0,
            "request": operation, "path": base + suffix, "body": body}


def recovery_matches_invocation(recovery, command):
    return all(recovery.get(key) == value for key, value in expected_recovery_fields(command).items())


def observation_value(value):
    """Keep assertions exact while adapting sets/bytes to the safe reporter."""
    if isinstance(value, bytes):
        return {"byteCount": len(value), "sha256": fixture.sha(value)}
    if isinstance(value, Path):
        return {"pathSha256": fixture.sha(str(value).encode("utf8"))}
    if isinstance(value, (set, frozenset)):
        return sorted((observation_value(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    if isinstance(value, (list, tuple)):
        return [observation_value(item) for item in value]
    if isinstance(value, dict):
        return {key: observation_value(item) for key, item in value.items()}
    return value


def plain_objects(text):
    """Read documented human answer/recovery objects without changing output."""
    result, position, decoder = [], 0, json.JSONDecoder()
    while position < len(text):
        start = text.find("{", position)
        if start < 0:
            break
        try:
            value, used = decoder.raw_decode(text[start:])
        except ValueError:
            position = start + 1
            continue
        result.append(value)
        position = start + used
    return result


class Original16Peer(fixture.Fixture):
    """The accepted scripted peer, with additional actual request-redaction checks."""
    def __init__(self, bundle, command, home):
        super().__init__(bundle, command)
        self.fixture_home = home

    def request_checks(self, command, body, held):
        checks = super().request_checks(command, body, held)
        if isinstance(body, dict):
            text = fixture.text_values(body)
            checks["fixtureEmailAbsent"] = PRIVATE_MARKER not in text
            checks["fixtureHomeAbsent"] = str(self.fixture_home).lower() not in text.lower()
        return checks


class HubOriginalCli16Test(unittest.TestCase):
    observations = {}

    @classmethod
    def setUpClass(cls):
        cls.git, cls.runtime_before = fixture.verify_runtime(ROOT)
        if not cls.git or not Path(cls.git).is_absolute():
            raise AssertionError("installed absolute Git required")
        cls.script = ROOT / fixture.PREFIX / "hub.py"
        cls.child = ROOT / "tests/fixtures/hub_cli/child.py"
        cls.observations = {}

    @classmethod
    def tearDownClass(cls):
        _, after = fixture.verify_runtime(ROOT)
        if after != cls.runtime_before:
            raise AssertionError("original16 tests changed the accepted runtime")

    def check(self, label, actual, expected=True):
        fixture.check(self.record["checks"], label, observation_value(actual), observation_value(expected))

    def git_run(self, *words):
        result = subprocess.run([self.git] + list(words), cwd=str(self.base), env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.check("synthetic Git setup", result.returncode, 0)

    def prepare(self, command, mode, bundle=None):
        self.record = {"mode": mode, "checks": [], "phases": [], "passed": False,
                       "scope": "actual CLI + isolated files + scripted loopback; no product handler"}
        type(self).observations.setdefault(self._testMethodName, []).append(self.record)
        self.temporary = tempfile.TemporaryDirectory(prefix="corthex-cli16-")
        self.base = Path(self.temporary.name).resolve()
        self.temp_parent = Path(tempfile.gettempdir()).resolve()
        self.addCleanup(self.clean_owned, self.temporary, self.base, self.temp_parent)
        self.home, self.repo, self.temp = self.base / "home", self.base / "project", self.base / "temp"
        for path in (self.home / ".corthex", self.repo / ".corthex", self.temp):
            path.mkdir(parents=True)
        self.env = fixture.child_env(self.home, self.temp, self.git)
        self.env["GIT_ALLOW_PROTOCOL"] = ""
        self.env["QA_CLI16_SENTINEL"] = PRIVATE_MARKER
        self.check("no service credential environment", not any(key.startswith(("CORTHEX_NEXUS_", "NEXUS_DEV_")) for key in self.env))
        template, hooks = self.base / "empty-template", self.base / "empty-hooks"
        template.mkdir()
        hooks.mkdir()
        self.git_run("init", "--initial-branch=main", "--template=" + str(template), str(self.repo))
        fixture.write_json(self.repo / ".corthex/project.json",
                           {"name": PROJECT, "title": "Synthetic " + PRIVATE_MARKER,
                            "team": False, "parts": ["sample", "other"]})
        doc = self.repo / "docs/02-prd/requirements.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("# Synthetic requirements\n\n## REQ-001\n\nLocal original16 fixture.\n", encoding="utf8")
        self.git_run("-C", str(self.repo), "add", ".")
        self.git_run("-C", str(self.repo), "-c", "core.hooksPath=" + str(hooks),
                     "-c", "user.name=Fixture", "-c", "user.email=fixture@example.com", "commit", "-m", "Synthetic fixture")
        self.git_run("-C", str(self.repo), "remote", "add", "origin", "https://example.com/synthetic/project.git")
        self.git_run("-C", str(self.repo), "update-ref", "refs/remotes/origin/main", "HEAD")
        self.git_run("-C", str(self.repo), "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        fixture.write_json(self.home / ".corthex/projects.json", {"projects": [{"name": PROJECT, "path": str(self.repo)}]})
        self.peer = Original16Peer(bundle or copy.deepcopy(BUNDLE), command, self.home)
        self.peer.__enter__()
        self.addCleanup(self.peer.__exit__, None, None, None)
        fixture.write_json(self.home / ".corthex/profile.json", {"nexus": {
            "url": "http://127.0.0.1:" + str(self.peer.server.server_port), "push": [PROJECT]}})
        # A pre-existing empty control guard is not a queued write. Avoid
        # mistaking its legitimate first creation for a project-data effect.
        guard = self.home / ".corthex/hub/outbox" / (PROJECT + ".guard")
        guard.parent.mkdir(parents=True)
        guard.write_bytes(b"\0")
        self.mode = mode

    @staticmethod
    def clean_owned(temporary, base, parent):
        resolved = Path(temporary.name).resolve()
        if resolved != base or resolved.parent != parent or not resolved.name.startswith("corthex-cli16-"):
            raise AssertionError("refuse cleanup outside exact owned temporary")
        temporary.cleanup()

    def invoke(self, words, code, outcome, label, local=False):
        guard_file = self.base / ("guard-%d.json" % len(self.record["phases"]))
        arguments = list(words) + (["--json"] if self.mode == "json" else [])
        args = [sys.executable, "-I", "-S", "-B", "-X", "utf8", str(self.child),
                "--hub", str(self.script), "--port", str(self.peer.server.server_port),
                "--guard-receipt", str(guard_file), "--", "--home", str(self.home)] + arguments
        before = len(self.peer.calls)
        result = subprocess.run(args, cwd=str(self.repo), env=self.env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=30)
        stdout, stderr = result.stdout.decode("utf8"), result.stderr.decode("utf8")
        guard = json.loads(guard_file.read_text(encoding="utf8")) if guard_file.is_file() else None
        phase = {"label": label, "startedOutputMode": self.mode, "actualExit": result.returncode,
                 "stdoutSha256": fixture.sha(result.stdout), "stderrSha256": fixture.sha(result.stderr),
                 "stdoutBytes": len(result.stdout), "stderrBytes": len(result.stderr),
                 "networkGuard": guard, "httpRequests": len(self.peer.calls) - before,
                 "rawStreamsPersisted": False}
        self.record["phases"].append(phase)
        self.check(label + ": exact CLI exit", result.returncode, code)
        self.check(label + ": sensitive marker excluded", PRIVATE_MARKER not in stdout + stderr)
        self.check(label + ": no traceback", "Traceback" not in stdout + stderr)
        self.check(label + ": socket guard receipt", guard is not None)
        self.check(label + ": external connects0", guard["blockedConnectionAttempts"], 0)
        self.check(label + ": external resolutions0", guard["blockedResolutionAttempts"], 0)
        if code == 2:
            self.check(label + ": decoded output privacy", private_output_absent([stdout, stderr, plain_objects(stderr)], self.home))
            self.check(label + ": argparse stdout empty", stdout, "")
            self.check(label + ": argparse diagnostic retained", "usage:" in stderr and "error:" in stderr)
            phase["outcome"] = "command-line-invalid"
            return None, stdout, stderr
        if self.mode == "json":
            try:
                rows = [json.loads(line) for line in stdout.splitlines() if line.strip()]
            except ValueError:
                rows = []
            self.check(label + ": one envelope", len(rows), 1)
            self.check(label + ": decoded output privacy", private_output_absent([rows, stderr, plain_objects(stderr)], self.home))
            row = rows[0]
            self.check(label + ": envelope keys", set(row), ENVELOPE | ({"recovery"} if "recovery" in row else set()))
            self.check(label + ": command/project/outcome", (row.get("command"), row.get("project"), row.get("outcome")), (words[0], PROJECT, outcome))
            self.check(label + ": JSON stderr empty", stderr, "")
            phase["outcome"] = row.get("outcome")
            phase["failurePresent"] = bool(row.get("failure"))
            phase["answerKeys"] = sorted(row["answer"]) if isinstance(row.get("answer"), dict) else None
            return row, stdout, stderr
        privacy_stdout = stdout
        if local and words[0] == "snapshot" and code == 0:
            saved_line = "  saved " + str(self.home / ".corthex/hub/snapshots" / (PROJECT + ".json"))
            self.check(label + ": one documented saved-path exception", stdout.splitlines().count(saved_line), 1)
            privacy_stdout = "\n".join(line for line in stdout.splitlines() if line != saved_line)
        self.check(label + ": decoded output privacy", private_output_absent([privacy_stdout, stderr, plain_objects(stdout), plain_objects(stderr)], self.home))
        if not local:
            self.check(label + ": documented plain heading", stdout.splitlines()[0], PROJECT + ": " + words[0] + " " + outcome)
            self.check(label + ": plain stderr empty", stderr, "")
        phase["outcome"] = outcome
        return None, stdout, stderr

    def no_queue(self):
        self.check("post-call project queue empty", fixture.queue_files(self.home, PROJECT), [])
        self.check("post-call all queue JSON empty", [p.name for p in self.home.rglob("*.json") if "outbox" in p.relative_to(self.home).parts], [])

    def finish(self):
        self.check("peer contract/route/privacy matches", self.peer.problems, [])
        self.check("no credential headers sent", all(call["credentialHeadersAbsent"] for call in self.peer.calls))
        self.record.update(passed=True, networkRequests=len(self.peer.calls), syntheticFinalState=self.peer.state(),
                           fixtureServerIsProductHandler=False, queueFiles=len(fixture.queue_files(self.home, PROJECT)))

    def snapshot_done(self):
        for mode in ("plain", "json"):
            with self.subTest(mode=mode):
                self.prepare("reply", mode)
                before = file_state(self.repo)
                saved = self.home / ".corthex/hub/snapshots" / (PROJECT + ".json")
                row, stdout, _ = self.invoke(["snapshot", PROJECT], 0, "done", "snapshot-initial", local=True)
                self.check("snapshot saved", saved.is_file())
                first = json.loads(saved.read_text(encoding="utf8"))
                self.check("saved snapshot schema/project", (first["schema"], first["project"]["name"]), ("corthex-hub/0.2", PROJECT))
                self.check("saved snapshot source item", sum(item.get("id") == "REQ-001" for item in first["items"]), 1)
                self.check("saved snapshot sensitive title redacted", PRIVATE_MARKER not in saved.read_text(encoding="utf8"))
                if row is not None:
                    self.check("JSON snapshot equals actual file", row["answer"]["snapshot"], first)
                else:
                    self.check("plain documented snapshot count", any(line.startswith(PROJECT + ": ") for line in stdout.splitlines()))
                    self.check("plain documented saved path", "  saved " + str(saved) in stdout)
                files = set(file_state(self.home))
                self.invoke(["snapshot", PROJECT], 0, "done", "snapshot-repeat", local=True)
                second = json.loads(saved.read_text(encoding="utf8"))
                self.check("repeat semantic snapshot items/summary", (second["items"], second["summary"]), (first["items"], first["summary"]))
                self.check("repeat does not create duplicate files", set(file_state(self.home)), files)
                self.check("exactly one saved snapshot", len(list(saved.parent.glob("*.json"))), 1)
                self.check("no temporary write", len(list(self.home.rglob("*.tmp"))), 0)
                self.check("snapshot reads project only", file_state(self.repo), before)
                self.check("snapshot HTTP0", len(self.peer.calls), 0)
                self.no_queue()
                self.finish()

    def status_case(self, failed=False):
        for mode in ("plain", "json"):
            with self.subTest(mode=mode):
                self.prepare("reply", mode)
                other = self.repo / ".corthex/stages/other.json"
                fixture.write_json(other, {"format": 1, "project": PROJECT, "part": "other", "stages": {}})
                other_before, home_before, repo_before = other.read_bytes(), home_data_state(self.home), file_state(self.repo)
                words = ["status", PROJECT, "05-erd", "--part", "unknown" if failed else "sample", "--repository", "--state", "in_progress", "--next", "Review " + PRIVATE_MARKER + " " + str(self.home)]
                for attempt in ("initial", "repeat"):
                    row, stdout, stderr = self.invoke(words, 1 if failed else 0, "failed" if failed else "done", "status-" + attempt, local=True)
                    if failed:
                        if row is not None:
                            self.check("status failure described", row["failure"], "--part must name a part declared in the project settings")
                            self.check("status failure no answer/outbox", (row["answer"], row["outbox"]), (None, {"sent": 0, "dropped": 0, "waiting": 0}))
                        else:
                            self.check("plain status failure described", stderr.strip(), "hub.py status: --part must name a part declared in the project settings")
                        self.check("failed status home data unchanged", home_data_state(self.home), home_before)
                        self.check("failed status project unchanged", file_state(self.repo), repo_before)
                    else:
                        target = self.repo / ".corthex/stages/sample.json"
                        self.check("actual repository record exists", target.is_file())
                        data = json.loads(target.read_text(encoding="utf8"))
                        entry = data["stages"]["05-erd"]
                        self.check("exact status record identity", (data["format"], data["project"], data["part"], list(data["stages"])), (1, PROJECT, "sample", ["05-erd"]))
                        self.check("exact status record data", (entry["state"], entry["next"], entry["checkpoints"]), ("in_progress", "Review [redacted] ~", []))
                        if row is not None:
                            self.check("JSON status equals saved record", row["answer"], {"stage": "05-erd", "record": entry, "from": "repository"})
                        else:
                            self.check("plain status saved diagnostic", stdout.strip(), PROJECT + " 05-erd: repository record saved")
                        self.check("one target record only", len(list(target.parent.glob("sample*.json"))), 1)
                        self.check("other part preserved", other.read_bytes(), other_before)
                        self.check("status home data unchanged", home_data_state(self.home), home_before)
                        guards = list((self.home / ".corthex/hub/record-locks").glob("*.guard"))
                        self.check("one native record control guard", len(guards), 1)
                        self.check("control guard contains no project payload", guards[0].read_bytes(), b"\0")
                    self.no_queue()
                self.check("status HTTP0", len(self.peer.calls), 0)
                self.finish()

    def todo_done(self):
        for mode in ("plain", "json"):
            with self.subTest(mode=mode):
                bundle = copy.deepcopy(BUNDLE)
                bundle["refused"] = {"status": 404, "body": {"type": "about:blank", "title": "Not Found", "status": 404, "code": "space_not_found", "detail": "Synthetic empty space."}}
                self.prepare("todo", mode, bundle)
                self.peer.mode = "refused"
                baseline, home_before, repo_before = self.peer.state(), file_state(self.home), file_state(self.repo)
                for attempt in ("initial", "repeat"):
                    row, stdout, _ = self.invoke(["todo", PROJECT], 0, "done", "todo-" + attempt)
                    answer = row["answer"] if row is not None else plain_objects(stdout)[0]
                    self.check("documented complete empty todo", answer, EMPTY_TODO)
                    self.check("todo has no synthetic mutation", self.peer.state(), baseline)
                    self.no_queue()
                self.check("one GET per todo invocation", [(x["method"], x["routeEnum"], x["status"]) for x in self.peer.calls], [("GET", "todo", 404)] * 2)
                self.check("todo home unchanged", file_state(self.home), home_before)
                self.check("todo project unchanged", file_state(self.repo), repo_before)
                self.finish()

    def comment_invalid(self):
        for mode in ("plain", "json"):
            with self.subTest(mode=mode):
                self.prepare("comment", mode)
                windows_home = r"C:\owned\synthetic-home"
                escaped = json.dumps({"nested": [{"where": windows_home}]})
                self.check("old raw home guard misses JSON escaping", windows_home not in escaped)
                self.check("decoded recursive guard rejects escaped home", private_output_absent(json.loads(escaped), windows_home), False)
                self.check("normalized guard rejects alternate separators", private_output_absent({"nested": [windows_home.replace("\\", "/")]}, windows_home), False)
                encoded_marker = json.dumps({"nested": [PRIVATE_MARKER]}).replace(PRIVATE_MARKER, "".join("\\u%04x" % ord(char) for char in PRIVATE_MARKER))
                self.check("old raw marker guard misses JSON unicode escaping", PRIVATE_MARKER not in encoded_marker)
                self.check("decoded guard rejects escaped marker", private_output_absent(json.loads(encoded_marker), windows_home), False)
                before, project_before, state_before = file_state(self.home), file_state(self.repo), self.peer.state()
                self.invoke(["comment", PROJECT, "--stage", PRIVATE_MARKER, "--text", "Invalid", "--session", BUNDLE["session"]], 2, "command-line-invalid", "actual-comment-parser")
                self.check("exact parser HTTP0", len(self.peer.calls), 0)
                self.check("exact parser home unchanged", file_state(self.home), before)
                self.check("exact parser project unchanged", file_state(self.repo), project_before)
                self.check("exact parser fixture state unchanged", self.peer.state(), state_before)
                self.no_queue()
                self.finish()

    def failed_write(self, command):
        for mode in ("plain", "json"):
            with self.subTest(mode=mode):
                self.prepare(command, mode)
                obstruction = self.home / ".corthex/hub/outbox" / PROJECT
                obstruction.parent.mkdir(parents=True, exist_ok=True)
                obstruction.write_text("Owned synthetic regular-file parent.\n", encoding="utf8")
                before, project_before, state_before = home_data_state(self.home), file_state(self.repo), self.peer.state()
                words = fixture.cli_words(command, BUNDLE, self.home)[:-1]
                prior_recovery_id = None
                for attempt in ("initial", "repeat"):
                    row, stdout, _ = self.invoke(words, 1, "failed", command + "-actual-local-failure-" + attempt)
                    expected_failure = "write lost from outbox; server receipt unconfirmed"
                    if row is not None:
                        self.check("exact documented failure member", row["failure"], expected_failure)
                        self.check("failure answer absent", row["answer"], None)
                        recovery = row["recovery"]
                    else:
                        self.check("plain documented failure", expected_failure in stdout)
                        self.check("one plain recovery heading", stdout.count("Recovery copy for the calling agent, once"), 1)
                        objects = plain_objects(stdout)
                        self.check("one plain recovery object", len(objects), 1)
                        recovery = objects[0]
                    self.check("actual recovery OutboxFile", fixture.queue_contract_valid(recovery, BUNDLE))
                    self.check("recovery remains redacted", private_output_absent(recovery, self.home))
                    self.check("specific recovery operation target redacted payload", recovery_matches_invocation(recovery, command))
                    self.check("recovery exact invocation fields", {key: recovery.get(key) for key in expected_recovery_fields(command)}, expected_recovery_fields(command))
                    if prior_recovery_id is not None:
                        self.check("separate invocation has fresh recovery ID", recovery["write"] != prior_recovery_id)
                    prior_recovery_id = recovery["write"]
                    for field in ("request", "path", "body"):
                        mutant = copy.deepcopy(recovery)
                        mutant[field] = ("reply" if recovery["request"] != "reply" else "comment") if field == "request" else "/api/spaces/" + PROJECT + "/wrong-target" if field == "path" else {"wrong": "[redacted]"}
                        self.check("old generic recovery accepts wrong " + field, fixture.queue_contract_valid(mutant, BUNDLE))
                        self.check("old ID association accepts wrong " + field, mutant["write"], recovery["write"])
                        self.check("invocation guard rejects wrong " + field, recovery_matches_invocation(mutant, command), False)
                    self.check("same actual obstruction remains", obstruction.is_file())
                    self.check("failed write home data unchanged", home_data_state(self.home), before)
                    order = obstruction.parent / (PROJECT + ".order")
                    self.check("reserved ordering metadata exists", order.is_file())
                    self.check("ordering metadata is only current recovery ID", json.loads(order.read_text(encoding="utf8")), [recovery["write"]])
                    self.check("failed write project unchanged", file_state(self.repo), project_before)
                    self.check("failed write HTTP0", len(self.peer.calls), 0)
                    self.check("failed write synthetic state unchanged", self.peer.state(), state_before)
                    self.no_queue()
                self.finish()

    def reply_case(self, outcome):
        for mode in ("plain", "json"):
            with self.subTest(mode=mode):
                self.prepare("reply", mode)
                words = fixture.cli_words("reply", BUNDLE, self.home)[:-1]
                baseline = self.peer.state()
                self.peer.mode = "success" if outcome == "done" else "refused" if outcome == "refused" else "unavailable"
                row, stdout, _ = self.invoke(words, {"done": 0, "refused": 1, "kept": 3}[outcome], outcome, "reply-initial")
                if outcome == "done":
                    self.check("exact documented reply answer", row["answer"] if row is not None else plain_objects(stdout)[0], BUNDLE["success"]["reply"]["body"])
                    self.check("one accepted write and effect", (len(self.peer.calls), len(self.peer.applied_ids), self.peer.applied_effects), (1, 1, 1))
                    self.no_queue()
                    self.drain_empty("done-repeat-drain", 1)
                    self.drain_empty("done-repeat-empty-again", 1)
                elif outcome == "refused":
                    problem = BUNDLE["refused"]["body"]
                    if row is not None:
                        self.check("exact emitted refusal problem", row["problem"], problem)
                        self.check("refused waiting0", row["outbox"]["waiting"], 0)
                    else:
                        self.check("plain refusal code/detail", problem["code"] in stdout and problem["detail"] in stdout)
                    self.no_queue()
                    self.check("refusal has no synthetic effect", self.peer.state(), baseline)
                    self.invoke(words, 1, "refused", "reply-refused-repeat")
                    self.no_queue()
                    self.check("one refusal request per invocation", len(self.peer.calls), 2)
                    self.check("repeat refusal no mutation", self.peer.state(), baseline)
                else:
                    if row is not None:
                        self.check("exact kept failure/waiting", (row["failure"], row["outbox"]["waiting"]), ("HTTP 503", 1))
                    else:
                        self.check("plain kept failure/waiting", "HTTP 503" in stdout and '"waiting": 1' in stdout)
                    self.check("ordinary kept output omits text", "Fixture text" not in stdout)
                    pending = fixture.queue_data(self.home, PROJECT)
                    self.check("actual one kept file", len(pending), 1)
                    first = pending[0]["write"]
                    self.invoke(words, 3, "kept", "append-behind-kept-head")
                    pending = fixture.queue_data(self.home, PROJECT)
                    self.check("two actual waiting writes", len(pending), 2)
                    self.check("queue contract", all(fixture.queue_contract_valid(item, BUNDLE) for item in pending))
                    self.check("queue private fields excluded", all(PRIVATE_MARKER not in fixture.text_values(item) and str(self.home).lower() not in fixture.text_values(item).lower() for item in pending))
                    self.check("actual text is redacted", all("[redacted]" in item["body"]["text"] and "~" in item["body"]["text"] for item in pending))
                    identities = [item["write"] for item in pending]
                    self.check("original head retained", identities[0], first)
                    self.check("distinct admitted writes", len(set(identities)), 2)
                    self.check("pending head alone retried before drain", self.peer.write_ids, [first, first])
                    self.check("kept sends have no effect", self.peer.state(), baseline)
                    self.peer.mode = "success"
                    drained, drain_out, _ = self.invoke(["outbox", PROJECT, "--send"], 0, "done", "actual-outbox-cli-drain")
                    stats = drained["outbox"] if drained is not None else plain_objects(drain_out)[-1]
                    self.check("actual CLI drain sent2 waiting0", {key: stats[key] for key in ("sent", "dropped", "waiting")}, {"sent": 2, "dropped": 0, "waiting": 0})
                    self.check("actual CLI drain has no refusal notices", stats.get("notices", []), [])
                    self.check("actual CLI FIFO IDs", self.peer.write_ids[-2:], identities)
                    self.check("two accepted effects only", (len(self.peer.applied_ids), self.peer.applied_effects), (2, 2))
                    bodies = collections.defaultdict(set)
                    for identity, call in zip(self.peer.write_ids, self.peer.calls):
                        bodies[identity].add(call["requestBodySha256"])
                    self.check("all retries keep original body", all(len(values) == 1 for values in bodies.values()))
                    self.no_queue()
                    self.drain_empty("kept-drain-repeat-no-replay", 4)
                self.finish()

    def drain_empty(self, label, expected_calls):
        effects = self.peer.applied_effects
        row, stdout, _ = self.invoke(["outbox", PROJECT, "--send"], 0, "done", label)
        if row is not None:
            self.check("empty drain zero stats", {key: row["outbox"][key] for key in ("sent", "dropped", "waiting")}, {"sent": 0, "dropped": 0, "waiting": 0})
            self.check("empty drain no refusal notices", row["outbox"].get("notices", []), [])
        else:
            self.check("plain zero counts not fabricated or printed", "  outbox:" not in stdout)
        self.check("empty drain documented empty writes", row["answer"] if row is not None else plain_objects(stdout)[0], {"writes": []})
        self.check("empty retry sends no duplicate", len(self.peer.calls), expected_calls)
        self.check("empty retry applies no duplicate", self.peer.applied_effects, effects)
        self.no_queue()

    def test_TC_1139_snapshot_done(self): self.snapshot_done()
    def test_TC_1142_status_done(self): self.status_case()
    def test_TC_1144_status_failed(self): self.status_case(failed=True)
    def test_TC_1156_todo_done(self): self.todo_done()
    def test_TC_1161_comment_command_line_invalid(self): self.comment_invalid()
    def test_TC_1163_comment_failed(self): self.failed_write("comment")
    def test_TC_1165_reply_done(self): self.reply_case("done")
    def test_TC_1167_reply_refused(self): self.reply_case("refused")
    def test_TC_1168_reply_failed(self): self.failed_write("reply")
    def test_TC_1169_reply_kept(self): self.reply_case("kept")
    def test_TC_1173_answered_failed(self): self.failed_write("answered")
    def test_TC_1178_decide_failed(self): self.failed_write("decide")
    def test_TC_1183_propose_failed(self): self.failed_write("propose")
    def test_TC_1188_withdraw_failed(self): self.failed_write("withdraw")
    def test_TC_1193_reflect_failed(self): self.failed_write("reflect")
    def test_TC_1198_record_failed(self): self.failed_write("record")


if __name__ == "__main__":
    unittest.main()
