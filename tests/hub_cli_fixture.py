"""TASK-250 CLI acceptance fixtures, stdlib Python >=3.8 only.

An external loopback fixture exercises the actual hub main/transport/outbox.
It is deliberately not a product handler, Access, deployed or 3OS receipt.
The runner never loads USER credentials, installs a dependency or removes files.
"""
import collections
import datetime
import hashlib
import http.server
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

from hub_cli_reviewed import REVIEWED_040

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures" / "hub_cli"
PIN = "3570fb0c755b50c314ca26f0361c72a71fe22d0d"
PREFIX = "plugins/corthex-nexus/skills/corthex-hub/scripts/"
RUNTIME = ("hub.py", "commands.py", "domain.py", "erd.py", "outbox.py", "records.py", "sitemap.py", "snapshot02.py", "transport.py")
WRITES = {"comment", "reply", "answered", "decide", "propose", "withdraw", "reflect", "record"}
SESSIONS = WRITES | {"claim", "release"}
EXITS = {"done": 0, "command-line-invalid": 2, "failed": 1, "refused": 1, "kept": 3}
ENVELOPE = {"command", "project", "outcome", "answer", "problem", "failure", "outbox", "remarks"}
# 0.4.0: a todo result also says whether it read, since when, and what is new (API-138).
TODO_READ = {"read", "since", "new"}
WRITE_RE = re.compile(r'"(nw_[0-9a-hjkmnp-tv-z]{12})"\Z')
PRIVATE_MARKER = "qa-sensitive@example.com"
# Reviewed release changes after the accepted pin, each mapped back to the audited bytes.
# 0.2.2 changes the version fields and lets a project ask_before entry keep an inherited
# entry it repeats with a qualifier, as "deletions (data)" keeps "deletions". 0.3.0 changes
# the version fields again, lets `comment` take any of the 13 stages, with an empty item for
# the stage as a whole and no quote needed, and gives `comment` and `reply` `--asks`; nothing else.
# 0.4.0's changes, the design revision's commands, are in hub_cli_reviewed.py and are applied first,
# so that these pairs then meet the 0.3.0 bytes that they were made for.
REVIEWED = {
    "hub.py": ((b'VERSION = "0.3.0"\n', b'VERSION = "0.2.0"\n'),),
    "transport.py": ((b'version="0.3.0", timeout=30', b'version="0.2.0", timeout=30'),),
    "commands.py": (
        (b'PICTURE_STAGES = ("01-domain", "05-erd", "07-sitemap")\n'
         b'# 0.3.0: a comment takes any of the 13 stages, and the agent\'s comment or reply says what it asks of the user.\n'
         b'STAGE_KEYS = ("01-domain", "02-prd", "03-user-flow", "04-functional-spec", "05-erd", "06-api", "07-sitemap",\n'
         b'              "08-screen-states", "09-mockup", "10-wbs", "11-development", "12-qa", "13-presentation")\n'
         b'ASKS = ("answer", "recommended", "checkpoint")\n',
         b'PICTURE_STAGES = ("01-domain", "05-erd", "07-sitemap")\n'),
        (b'        if args.asks:\n'
         b'            body["asks"] = args.asks\n'
         b'        name, path = "comment", base + "/comments"\n',
         b'        if not body["item"] and not body.get("quote"):\n'
         b'            raise CommandLine("a comment on the picture needs --quote")\n'
         b'        name, path = "comment", base + "/comments"\n'),
        (b'        body["text"] = text_value(args, "text", True)\n'
         b'        if args.asks:\n'
         b'            body["asks"] = args.asks\n'
         b'        name, path = "reply"',
         b'        body["text"] = text_value(args, "text", True)\n'
         b'        name, path = "reply"'),
        (b'choices=STAGE_KEYS if name == "comment" else PICTURE_STAGES)', b'choices=PICTURE_STAGES)'),
        (b'        if name in ("comment", "reply"):\n'
         b'            parser.add_argument("--asks", choices=ASKS)\n', b''),
    ),
    "snapshot02.py": ((
        b'    listed = [x.casefold() for x in entries]\n'
        b'\n'
        b'    def kept(entry):\n'
        b'        # A project entry keeps an inherited one when it repeats it, alone or with a qualifier after it,\n'
        b'        # as "deletions (repositories, data)" keeps "deletions".\n'
        b'        word = entry.casefold()\n'
        b'        return any(x == word or (x.startswith(word) and x[len(word):len(word) + 1] in (" ", "(")) for x in listed)\n'
        b'\n'
        b'    return {"entries": entries, "source": source,\n'
        b'            "left_out": [x for x in inherited[0] if not kept(x)] if source == "project" else []}\n',
        b'    return {"entries": entries, "source": source,\n'
        b'            "left_out": [x for x in inherited[0] if x not in entries] if source == "project" else []}\n'),),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf8")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(value))


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def check(observations, label, actual, expected=True):
    ok = actual == expected
    def projection(value):
        if value is None or isinstance(value, (int, float, bool)):
            return value
        if isinstance(value, str) and re.fullmatch(r"[a-z][a-z_-]{0,40}", value):
            return value
        encoded = json_bytes(value)
        return {"kind": type(value).__name__, "sha256": sha(encoded), "itemsOrChars": len(value)}
    observations.append({"assertion": label, "passed": ok, "actual": projection(actual), "expected": projection(expected)})
    if not ok:
        raise AssertionError(label)


def verify_runtime(checkout):
    """Bind this acceptance fixture to the audited runtime, independently of HEAD.

    Later branch commits may contain unrelated core/template work. The nine
    runtime files must still equal the product's accepted hub pin, normalizing
    checkout CRLF and the explicitly reviewed release changes in REVIEWED.
    Every other byte, including the wire schemas, stays pinned. The returned
    file hashes describe the actual source, not its normalized baseline.
    """
    pin = json.loads((FIXTURES / "runtime-pin.json").read_text(encoding="utf8"))
    if pin["commit"] != PIN or set(pin["files"]) != set(RUNTIME):
        raise ValueError("CLI fixture runtime pin metadata differs")
    rows = []
    for name in RUNTIME:
        source = (checkout / PREFIX / name).read_bytes().replace(b"\r\n", b"\n")
        actual = sha(source)
        for new, old in REVIEWED_040.get(name, ()) + REVIEWED.get(name, ()):
            if source.count(new) == 1:
                source = source.replace(new, old, 1)
        if sha(source) != pin["files"][name]:
            raise ValueError("CLI fixture runtime differs from audited pin: " + name)
        rows.append({"file": name, "lfSha256": actual,
                     "auditedBaselineLfSha256": pin["files"][name],
                     "reviewedNormalization": actual != sha(source)})
    git = None
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        folder = Path(entry)
        if not entry or not folder.is_absolute() or folder.resolve() == Path.cwd().resolve():
            continue
        candidate = folder / ("git.exe" if os.name == "nt" else "git")
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            git = str(candidate)
            break
    return git, rows


def endpoint(bundle, command):
    ids = bundle["ids"]
    if command == "todo":
        return "GET", "/api/spaces/" + bundle["project"] + "/todo"
    row = bundle["success"][command]
    return row["method"], row["pathTemplate"].format(project=bundle["project"], comment=ids["c"], proposal=ids["p"],
                                                   edit=ids["e"], checkpoint=ids["k"], entry=ids["c"])


class Fixture:
    """Scripted HTTP only. Its model/effect is explicitly synthetic, not SQLite."""
    def __init__(self, bundle, command):
        self.bundle, self.command = bundle, command
        self.mode = "success"
        self.calls, self.problems, self.write_ids = [], [], []
        self.applied_ids = set()
        self.applied_effects = 0
        self.snapshot_posts = 0
        self.claimed = command == "release"
        self.project_present = command != "push"
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.handle_request()

            def do_POST(self):
                self.handle_request()

            def do_DELETE(self):
                self.handle_request()

            def handle_request(self):
                owner.respond(self)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def state(self):
        return {"syntheticAppliedEffects": self.applied_effects, "snapshotPosts": self.snapshot_posts,
                "claimed": self.claimed, "projectPresent": self.project_present}

    def respond(self, handler):
        command = "reply" if self.command == "outbox" else self.command
        expected_method, expected_path = endpoint(self.bundle, command)
        held = handler.command == "GET" and handler.path == "/api/snapshots/" + self.bundle["project"] + "/held" and command == "push"
        error = None
        if not held and (handler.command, handler.path) != (expected_method, expected_path):
            error = "unexpected_method_or_route"
        length = int(handler.headers.get("Content-Length", "0"))
        if not 0 <= length <= 1024 * 1024:
            error = "body_not_bounded"
        raw = handler.rfile.read(length) if error is None else b""
        try:
            body = json.loads(raw.decode("utf8")) if raw else None
        except (ValueError, UnicodeError):
            body, error = None, "request_not_json"
        write_header = handler.headers.get("Idempotency-Key")
        session_header = handler.headers.get("Nexus-Session")
        has_auth = any(handler.headers.get(name) is not None for name in ("Authorization", "Cookie", "CF-Access-Client-Id", "CF-Access-Client-Secret"))
        if has_auth:
            error = "credential_header_forbidden"
        is_write = command in WRITES and not held
        write_match = WRITE_RE.fullmatch(write_header or "")
        if is_write and (not write_match or session_header != self.bundle["session"]):
            error = "write_identity_or_session_invalid"
        if not is_write and write_header is not None:
            error = "non_queued_command_has_write_id"
        if command in {"claim", "release"} and session_header != self.bundle["session"]:
            error = "claim_session_invalid"
        safe_body = PRIVATE_MARKER not in raw.decode("utf8", errors="replace")
        if not safe_body:
            error = "unredacted_synthetic_email_sent"
        if write_match:
            self.write_ids.append(write_match[1])
        body_checks = self.request_checks(command, body, held)
        if not all(body_checks.values()):
            error = "request_shape_or_argument_mapping"
        if error:
            self.problems.append(error)
            status, answer = 418, {"status": 418, "code": "fixture_mismatch"}
        elif self.mode == "unavailable":
            status, answer = 503, None
        elif self.mode == "refused":
            status, answer = self.bundle["refused"]["status"], self.bundle["refused"]["body"]
        elif held:
            status, answer = 404, {"type": "about:blank", "title": "Not Found", "status": 404,
                                   "code": "project_not_found", "detail": "Synthetic project has no held snapshot."}
        else:
            success = self.bundle["success"][command]
            status, answer = success["status"], success["body"]
            if is_write:
                if write_match[1] not in self.applied_ids:
                    self.applied_ids.add(write_match[1])
                    self.applied_effects += 1
            elif command == "push":
                self.snapshot_posts += 1
                self.project_present = True
                self.applied_effects += 1
            elif command == "remove":
                self.project_present = False
                self.applied_effects += 1
            elif command in {"claim", "release"}:
                self.claimed = command == "claim"
                self.applied_effects += 1
        payload = json_bytes(answer) if answer is not None else b"Synthetic service unavailable."
        self.calls.append({"method": handler.command, "routeEnum": "held" if held else command,
                           "status": status, "requestBytes": len(raw), "responseBytes": len(payload),
                           "jsonRequest": body is not None, "credentialHeadersAbsent": not has_auth,
                           "sessionMatchesFixture": session_header == self.bundle["session"] if command in SESSIONS else session_header is None,
                           "writeIdentityValid": bool(write_match) if is_write else write_header is None,
                           "requestBodyChecks": body_checks, "requestRedacted": safe_body,
                           "requestBodySha256": sha(raw)})
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json" if answer is not None else "text/plain")
        handler.send_header("Content-Length", str(len(payload)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        try:
            handler.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            self.problems.append("fixture_response_not_consumed")

    def request_checks(self, command, body, held):
        if held or command in {"todo", "show", "remove", "release", "claim"}:
            return {"documentedNoBody": body is None}
        if command == "push":
            return {"snapshotObject": isinstance(body, dict), "snapshot02": isinstance(body, dict) and body.get("schema") == "corthex-hub/0.2",
                    "projectNameFixed": isinstance(body, dict) and body.get("project", {}).get("name") == self.bundle["project"]}
        if not isinstance(body, dict):
            return {"requestObject": False}
        if command == "comment":
            return {"part": body.get("part") == "sample", "stage": body.get("stage") == "05-erd", "item": body.get("item") == "TBL-001",
                    "textRedacted": "[redacted]" in body.get("text", ""), "homeRedacted": "~" in body.get("text", "")}
        if command == "reply":
            return {"text": isinstance(body.get("text"), str) and bool(body["text"])}
        if command == "answered" or command == "withdraw":
            return {"emptyObject": body == {}}
        if command == "decide":
            return {"link": body.get("link") == "https://example.invalid/pr/1", "textRedacted": "[redacted]" in body.get("text", "")}
        if command == "propose":
            return {"part": body.get("part") == "sample", "stage": body.get("stage") == "05-erd", "items": body.get("items") == ["TBL-001"],
                    "reasonRedacted": "[redacted]" in body.get("reason", ""), "changeRedacted": "[redacted]" in body.get("change", "")}
        if command == "reflect" or command == "record":
            return {"openedEvent": body.get("event") == "opened", "pullRequest": body.get("pull_request") == "https://example.invalid/pr/1"}
        return {"recognizedCommand": False}


def queue_files(home, project):
    folder = home / ".corthex/hub/outbox" / project
    return sorted(folder.glob("*.json")) if folder.is_dir() else []


def queue_data(home, project):
    return [json.loads(path.read_text(encoding="utf8")) for path in queue_files(home, project)]


def text_values(value):
    if isinstance(value, dict):
        return "\n".join(text_values(item) for item in value.values())
    if isinstance(value, list):
        return "\n".join(text_values(item) for item in value)
    return value if isinstance(value, str) else ""


def queue_contract_valid(row, bundle):
    required = {"format", "write", "project", "request", "path", "session", "made", "body", "tries"}
    requests = {"comment", "proposal", "reply", "answered", "decision", "withdraw-proposal", "report-edit", "report-checkpoint"}
    return (required <= set(row) <= required | {"failure"} and row["format"] == 1 and
            bool(re.fullmatch(r"nw_[0-9a-hjkmnp-tv-z]{12}", row["write"])) and row["project"] == bundle["project"] and
            row["request"] in requests and row["path"].startswith("/api/spaces/" + bundle["project"] + "/") and
            row["session"] == bundle["session"] and row["made"].endswith("Z") and isinstance(row["body"], dict) and
            type(row["tries"]) is int and row["tries"] >= 0 and
            ("failure" not in row or isinstance(row["failure"], str) and len(row["failure"]) <= 120))


def seed_queue(home, bundle, count=2):
    """Contract-format fixtures, not Outbox.make/save or other production code."""
    made = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=1)
    for index in range(count):
        moment = made + datetime.timedelta(milliseconds=index)
        stamp = moment.strftime("%Y%m%dT%H%M%S") + "%03dZ" % (moment.microsecond // 1000)
        ident = "nw_" + "%012d" % (index + 1)
        value = {"format": 1, "write": ident, "project": bundle["project"], "request": "reply",
                 "path": "/api/spaces/" + bundle["project"] + "/comments/" + bundle["ids"]["c"] + "/replies",
                 "session": bundle["session"], "made": moment.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                 "body": {"text": "Synthetic queued text [redacted]"}, "tries": 0}
        write_json(home / ".corthex/hub/outbox" / bundle["project"] / (stamp + "." + ident + ".json"), value)


def child_env(home, temp, git):
    env = {"HOME": str(home), "USERPROFILE": str(home), "TEMP": str(temp), "TMP": str(temp),
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1",
           "PATH": os.pathsep.join((str(Path(sys.executable).parent), str(Path(git).parent) if git else str(Path(sys.executable).parent)))}
    for key in ("SystemRoot", "WINDIR", "SYSTEMROOT"):
        if os.name == "nt" and key in os.environ:
            env[key] = os.environ[key]
    return env


def cli_words(command, bundle, home, invalid=False):
    project, ids = bundle["project"], bundle["ids"]
    sensitive = "Fixture text " + PRIVATE_MARKER + " " + str(home)
    words = {
        "snapshot": ["snapshot", project], "status": ["status", project, "05-erd", "--state", "in_progress"],
        "push": ["push", project], "remove": ["remove", project], "todo": ["todo", project],
        "comment": ["comment", project, "--stage", "05-erd", "--part", "sample", "--item", "TBL-001", "--text", sensitive],
        "reply": ["reply", project, ids["c"], "--text", sensitive], "answered": ["answered", project, ids["c"]],
        "decide": ["decide", project, ids["c"], "--link", "https://example.invalid/pr/1", "--text", sensitive],
        "propose": ["propose", project, "--stage", "05-erd", "--part", "sample", "--item", "TBL-001", "--reason", sensitive, "--change", sensitive],
        "withdraw": ["withdraw", project, ids["p"]], "reflect": ["reflect", project, ids["e"], "opened", "--pr", "https://example.invalid/pr/1"],
        "record": ["record", project, ids["k"], "opened", "--pr", "https://example.invalid/pr/1"],
        "show": ["show", project, ids["c"]], "claim": ["claim", project, ids["c"]], "release": ["release", project, ids["c"]],
        "outbox": ["outbox", project, "--send"]}[command]
    if command in SESSIONS and not invalid:
        words += ["--session", bundle["session"]]
    if invalid and command not in SESSIONS:
        words += ["--fixture-unknown-option"]
    return words + ["--json"]


def invoke(case_dir, phase, hub, home, server, words, env, observations, expected_exit, expected_outcome):
    guard_file = case_dir / (phase + "-network-guard.json")
    argv = [sys.executable, "-B", str(FIXTURES / "child.py"), "--hub", str(hub), "--port", str(server.server.server_port),
            "--guard-receipt", str(guard_file), "--", "--home", str(home)] + words
    begin = utc()
    process = subprocess.run(argv, cwd=str(case_dir), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
    stdout, stderr = process.stdout.decode("utf8"), process.stderr.decode("utf8")
    try:
        rows = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        json_valid = True
    except ValueError:
        rows, json_valid = [], False
    guard = json.loads(guard_file.read_text(encoding="utf8")) if guard_file.is_file() else None
    projection = [{"command": row.get("command"), "project": row.get("project"), "outcome": row.get("outcome"),
                   "answerKeys": sorted(row["answer"]) if isinstance(row.get("answer"), dict) else None,
                   "problemCode": (row.get("problem") or {}).get("code"), "failurePresent": bool(row.get("failure")),
                   "outbox": {key: (row.get("outbox") or {}).get(key, 0) for key in ("sent", "dropped", "waiting")}}
                  for row in rows if isinstance(row, dict)]
    result = {"phase": phase, "startedAtUtc": begin, "finishedAtUtc": utc(), "actualExit": process.returncode,
              "stdoutSha256": sha(process.stdout), "stderrSha256": sha(process.stderr), "stdoutJsonValid": json_valid,
              "stdoutBytes": len(process.stdout), "stderrBytes": len(process.stderr), "stdoutProjection": projection,
              "stderrHasArgparseError": "error:" in stderr, "networkGuard": guard,
              "rawStdoutStderrBodiesPersisted": False}
    # Save the actual observation before any acceptance assertion can fail.
    write_json(case_dir / (phase + "-observations.json"), result)
    check(observations, phase + ":exit", process.returncode, expected_exit)
    check(observations, phase + ":synthetic private marker not printed", PRIVATE_MARKER not in stdout + stderr)
    check(observations, phase + ":fixture home not printed", str(home).lower() not in (stdout + stderr).lower())
    check(observations, phase + ":guard receipt exists", guard is not None)
    check(observations, phase + ":no external connection attempted", guard["blockedConnectionAttempts"], 0)
    check(observations, phase + ":no external resolution attempted", guard["blockedResolutionAttempts"], 0)
    check(observations, phase + ":stdout JSON valid", json_valid)
    if expected_outcome == "command-line-invalid":
        check(observations, phase + ":no JSON result after argparse rejection", rows, [])
        check(observations, phase + ":argparse diagnostic", "error:" in stderr)
    else:
        check(observations, phase + ":one JSON envelope", len(rows), 1)
        row = rows[0]
        check(observations, phase + ":outcome", row.get("outcome"), expected_outcome)
        check(observations, phase + ":envelope keys", sorted(row), sorted(ENVELOPE | (TODO_READ if words[0] == "todo" else set())))
        check(observations, phase + ":project", row["project"], server.bundle["project"])
        check(observations, phase + ":command", row["command"], words[0])
    if expected_outcome == "kept":
        check(observations, phase + ":kept text omitted from actual console", "Fixture text" not in stdout and "Synthetic queued text" not in stdout)
    return rows[0] if rows else None, result


def run_case(case, work, hub, git, bundle):
    case_dir = work / case["id"]
    home, temp, repo = case_dir / "home", case_dir / "temp", case_dir / "repository"
    for path in (home / ".corthex", temp, repo / ".corthex"):
        path.mkdir(parents=True)
    write_json(repo / ".corthex/project.json", {"name": bundle["project"], "title": "Synthetic CLI fixture", "team": True})
    write_json(home / ".corthex/projects.json", {"projects": [{"name": bundle["project"], "path": str(repo)}]})
    observations, phases = [], []
    result = {"id": case["id"], "title": case["title"], "originalExpected": case["expected"],
              "executed": False, "passed": False, "sourceVerdictChanged": False,
              "scope": "actual CLI + loopback scripted HTTP + isolated filesystem; no product handler or deployed Access"}
    command, outcome = case["command"], case["outcome"]
    server = None
    try:
        with Fixture(bundle, command) as server:
            profile = {"nexus": {"url": "http://127.0.0.1:" + str(server.server.server_port), "push": [bundle["project"]]}}
            if command == "outbox" and outcome == "refused":
                profile["nexus"]["push"] = []
            if command == "outbox" and outcome == "failed":
                profile["nexus"].pop("url")
            write_json(home / ".corthex/profile.json", profile)
            baseline = server.state()
            if command == "snapshot" and outcome == "failed":
                (home / ".corthex/hub/snapshots" / (bundle["project"] + ".json")).mkdir(parents=True)
            if command == "remove" and outcome == "done":
                seed_queue(home, bundle)
            if command == "outbox" and outcome in {"done", "kept"}:
                seed_queue(home, bundle)
            env = child_env(home, temp, git)
            check(observations, "child environment has no service credentials", not any(k.startswith(("NEXUS_DEV_", "CORTHEX_NEXUS_")) for k in env))
            server.mode = "refused" if outcome == "refused" else "unavailable" if outcome in {"failed", "kept"} else "success"
            words = cli_words(command, bundle, home, invalid=outcome == "command-line-invalid")
            row, phase = invoke(case_dir, "initial", hub, home, server, words, env, observations, EXITS[outcome], outcome)
            phases.append(phase)
            result["executed"] = True
            if outcome == "command-line-invalid":
                check(observations, "invalid CLI sends no HTTP", len(server.calls), 0)
                check(observations, "invalid CLI leaves no queued write", len(queue_files(home, bundle["project"])), 0)
                check(observations, "invalid CLI does not affect fixture data", server.state(), baseline)
            elif outcome in {"failed", "refused"}:
                check(observations, "non-kept failure leaves no queued write", len(queue_files(home, bundle["project"])), 0)
                check(observations, "failure/refusal has no synthetic server effect", server.state(), baseline)
                if outcome == "refused" and command != "outbox":
                    check(observations, "documented refusal Problem Details preserved", row["problem"], bundle["refused"]["body"])
                check(observations, "failure/refusal sends only its one expected request", len(server.calls), 0 if command in {"snapshot", "outbox"} else 1)
                if command == "outbox" and outcome == "refused":
                    check(observations, "outbox local refusal kind", row["failure"], "not in nexus.push")
                if outcome == "failed":
                    check(observations, "documented failure is present", bool(row["failure"]))
                    if command == "snapshot":
                        check(observations, "snapshot storage fault remains the fixture directory", (home / ".corthex/hub/snapshots" / (bundle["project"] + ".json")).is_dir())
                    else:
                        expected_failure = "no NEXUS address, or the configured address is invalid" if command == "outbox" else "HTTP 503"
                        check(observations, "exact documented failure kind", row["failure"], expected_failure)
            elif outcome == "done":
                check(observations, "done removes transient or drained queue files", len(queue_files(home, bundle["project"])), 0)
                check(observations, "success request count has no duplicate sends", len(server.calls), 2 if command in {"push", "outbox"} else 1)
                if command == "outbox":
                    check(observations, "outbox reports both fixture sends", row["outbox"]["sent"], 2)
                    check(observations, "outbox sends original admission order", server.write_ids, ["nw_000000000001", "nw_000000000002"])
                    check(observations, "two distinct queued writes applied once", server.applied_effects, 2)
                else:
                    expected_answer = dict(bundle["success"][command]["body"])
                    if command == "remove":
                        expected_answer["next_push"] = "brings this project back with an empty space; remove it from nexus.push to stop pushes"
                    check(observations, "documented success answer is preserved", row["answer"], expected_answer)
                    if command in WRITES:
                        check(observations, "fresh success sent one write only", len(server.write_ids), 1)
                        check(observations, "fresh success has one synthetic effect", server.applied_effects, 1)
                    if command == "push":
                        check(observations, "fresh snapshot is posted once", server.snapshot_posts, 1)
                        stored = json.loads((home / ".corthex/hub/snapshots" / (bundle["project"] + ".json")).read_text(encoding="utf8"))
                        check(observations, "fresh snapshot was also saved locally", stored["schema"], "corthex-hub/0.2")
                    if command == "remove":
                        check(observations, "successful remove affects synthetic project", server.project_present, False)
                    if command in {"claim", "release"}:
                        check(observations, "claim/release synthetic effect", server.claimed, command == "claim")
                    if command == "show":
                        check(observations, "read has no synthetic data effect", server.state(), baseline)
            elif outcome == "kept":
                pending = queue_data(home, bundle["project"])
                expected_count = 2 if command == "outbox" else 1
                check(observations, "kept write count", len(pending), expected_count)
                check(observations, "persisted queue matches documented OutboxFile fields", all(queue_contract_valid(item, bundle) for item in pending))
                check(observations, "kept response reports actual waiting files", row["outbox"]["waiting"], expected_count)
                check(observations, "kept retry reason is preserved", row["failure"], "HTTP 503")
                first_id = pending[0]["write"]
                check(observations, "kept queue is redacted", all(PRIVATE_MARKER not in text_values(item) and str(home).lower() not in text_values(item).lower() for item in pending))
                check(observations, "kept request has no synthetic effect", server.state(), baseline)
                if command != "outbox":
                    appended_row, phase = invoke(case_dir, "append-behind-waiting-head", hub, home, server, words, env, observations, 3, "kept")
                    phases.append(phase)
                    pending = queue_data(home, bundle["project"])
                    check(observations, "second invocation is queued behind head", len(pending), 2)
                    check(observations, "append response reports both waiting files", appended_row["outbox"]["waiting"], 2)
                    check(observations, "waiting head retried with original identity", server.write_ids, [first_id, first_id])
                    check(observations, "new second write has distinct identity", len({item["write"] for item in pending}), 2)
                identities = [item["write"] for item in pending]
                check(observations, "oldest waiting write remains head", identities[0], first_id)
                server.mode = "success"
                _, phase = invoke(case_dir, "retry-drain", hub, home, server, cli_words("outbox", bundle, home), env, observations, 0, "done")
                phases.append(phase)
                check(observations, "retry drain preserves admission order and identities", server.write_ids[-2:], identities)
                check(observations, "retry drain removes both files", len(queue_files(home, bundle["project"])), 0)
                check(observations, "retry drain sends exactly two distinct writes", len(server.applied_ids), 2)
                check(observations, "retry drain reports sent2 waiting0", phase["stdoutProjection"][0]["outbox"], {"sent": 2, "dropped": 0, "waiting": 0})
                repeated_bodies = collections.defaultdict(set)
                for ident, call in zip(server.write_ids, server.calls):
                    repeated_bodies[ident].add(call["requestBodySha256"])
                check(observations, "every retry preserves its original body", all(len(values) == 1 for values in repeated_bodies.values()))
            check(observations, "HTTP fixture detected no contract/route/privacy mismatch", server.problems, [])
            check(observations, "no credential headers sent", all(call["credentialHeadersAbsent"] for call in server.calls))
            result.update(passed=True, requests=server.calls, syntheticFinalState=server.state(),
                          fixtureServerIsProductHandler=False, networkRequests=len(server.calls))
    except Exception as error:
        # Safe failure category only; do not persist traceback/argv/body/home.
        result.update(errorClass=type(error).__name__, failedAssertion=str(error) if isinstance(error, AssertionError) else "harness_or_runtime_error")
    if server is not None:
        result.update(requests=server.calls, syntheticFinalState=server.state(), fixtureProblems=server.problems,
                      networkRequests=len(server.calls), fixtureServerIsProductHandler=False)
    result["executed"] = (case_dir / "initial-observations.json").is_file()
    result.update(assertions=observations, phases=phases)
    write_json(case_dir / "result.json", result)
    return result

