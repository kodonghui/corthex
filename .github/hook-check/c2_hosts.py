"""TASK-099: installed Claude Code and Codex run C2 at release 0.3.0 against local test servers.

Usage: python c2_hosts.py OUTDIR

TC-253, TC-254, TC-255 and TC-257 of stage 12. The plugin on `main` says 0.2.x
until the release (TASK-051), so the check stages a copy of the marketplace
whose corthex-memory manifests say 0.3.0 and whose hooks file is the release's
`hooks/hooks-0.3.0.json`; nothing else of the package changes. Both hosts run
in one made-up home with one demo project, so that a decision curated from one
host's session reaches the other's. The hosts' own model is the hook check's
mock on 127.0.0.1, and the memory worker's Anthropic and OpenAI endpoints are a
second local server here, with keys made up for the run; no provider is
called.

Four sessions, each one prompt that states a decision with a marker:

1. Claude Code, with the end-of-turn trigger at one turn: its end-of-turn hook
   starts the worker.
2. Codex, likewise; its start summary, or the recall for its prompt, must
   show decision 1.
3. Claude Code, with the default trigger of ten turns: its session end hook
   starts the worker; it must show decision 2.
4. Codex, likewise; it must show decision 3.

Each session start also launches the worker (API-001), and the prompt hook
marks the turn, so the start's worker may curate the prompt; its requests are
answered at once, and the host's model answers only once that worker has let
the project go. From then on the memory server holds each curate request until
the host process has exited, then answers with the turn's decision and an item
for the agent's answer; the worker that the trigger started must then apply
them, and its run log must list each of the items it added (TC-253).

While a session runs and its request is held, the processes' command lines are
read, every half second (every two on Windows, where reading them is slow).
Both memory keys are markers, which must reach the server and appear in no
file of the memory store and in no command line (TC-254). The case also needs
evidence that it looked: for each host, a prompt whose recall ranked the items
(`injected` or `below` in the injection log), and in each session a reading of
the command lines that showed the memory worker. Then Claude Code runs once
more with CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1 (TC-257).

Any failure that the worker or a hook notes in the failure log fails TC-253,
with two exceptions that the summary lists: a lock that stayed busy, and a
recall that gave up at its window (API-010). The prompt hook still returns in
time after such a recall, with the outcome `deadline`, and the prompt goes on
without a recall block; how often that happens is a matter of the machine's
speed, which TC-256 measures, so the case counts it and does not fail on it.
The report keeps the number of command lines read, never the lines.
It writes report.json and prints a summary, and exits 1 when a case fails.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run as hookcheck  # noqa: E402

RELEASE = "0.3.0"
DIMS = 512
HOLD_SECONDS = 120
QUIET = 3.0
SETTLE_SECONDS = 90
DECISIONS = (
    # (host, trigger turns, the marker, the user's prompt)
    ("claude", 1, "DEC-ALPHA-ship.py",
     "결정: 배포 스크립트 이름은 DEC-ALPHA-ship.py로 합니다. 이 이름을 기억해 두세요."),
    ("codex", 1, "DEC-BRAVO-check",
     "DEC-ALPHA-ship.py 배포 스크립트를 쓰겠습니다. 결정: 검사 명령은 DEC-BRAVO-check로 합니다."),
    ("claude", 10, "DEC-CHARLIE-docs",
     "DEC-BRAVO-check 검사 명령으로 확인합니다. 결정: 문서 폴더는 DEC-CHARLIE-docs로 합니다."),
    ("codex", 10, "DEC-DELTA-tag",
     "DEC-CHARLIE-docs 문서 폴더를 씁니다. 결정: 릴리스 태그 접두어는 DEC-DELTA-tag로 합니다."),
)
HOST_NAMES = {"claude": "claude-code", "codex": "codex"}
WORDS = re.compile(r"[0-9A-Za-z가-힣._-]+")
REASON = re.compile(r"--reason (\S+)")
MODEL_PATH = re.compile(r"/v1/(messages|responses)(\?|$)")
SAMPLE_SECONDS = 2.0 if os.name == "nt" else 0.5
RANKED = ("injected", "below")
# A state answer that keeps the state as it is: five empty parts (state-2).
KEEP_STATE = {"state": {"goal": [], "decisions": [], "progress": [], "blockers": [], "next": []}}


def stage(repository, output):
    """A copy of the marketplace whose corthex-memory is release 0.3.0 with the release's hooks file."""
    target = output / "source"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for name in (".claude-plugin", ".agents/plugins", "plugins"):
        shutil.copytree(repository / name, target / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    memory = target / "plugins/corthex-memory"
    for manifest in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        path = memory / manifest
        value = json.loads(path.read_text(encoding="utf-8"))
        value["version"] = RELEASE
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    staged = memory / "hooks/hooks-0.3.0.json"
    os.replace(str(staged), str(memory / "hooks/hooks.json"))
    return target, memory


def line(marker):
    """The state line, and the item text, that the memory server's answer gives a decision."""
    return "The user decided " + marker + "."


def vector(text):
    """A made-up embedding: each word of the text adds to one of DIMS buckets, so shared words come close."""
    values = [0.0] * DIMS
    for word in WORDS.findall(text.lower()):
        bucket = int.from_bytes(word.encode("utf-8")[:8].ljust(8, b"\0"), "big") * 2654435761 % DIMS
        values[bucket] += 1.0
    if not any(values):
        values[0] = 1.0
    return values


def event(kind, **data):
    return ("event: " + kind + "\ndata: " + json.dumps(dict(type=kind, **data), ensure_ascii=False) + "\n\n").encode("utf-8")


def request_kind(value):
    """The kind of a memory request: curate, merge or state."""
    return ET.fromstring(value["messages"][0]["content"]).get("kind")


def curate_stream(answer):
    text = json.dumps(answer, ensure_ascii=False)
    message = dict(type="message", role="assistant", content=[],
                   usage={"input_tokens": 1200, "output_tokens": 1, "cache_creation_input_tokens": 0,
                          "cache_read_input_tokens": 0})
    return (event("message_start", message=message) +
            event("content_block_start", index=0, content_block={"type": "text", "text": ""}) +
            event("content_block_delta", index=0, delta={"type": "text_delta", "text": text}) +
            event("content_block_stop", index=0) +
            event("message_delta", delta={"stop_reason": "end_turn"}, usage={"output_tokens": 300}) +
            event("message_stop"))


class MemoryServer:
    """The memory worker's and the prompt hook's Anthropic and OpenAI endpoints, on 127.0.0.1.

    After `hold()` a curate request is held until `release()`. An answer adds each marked decision of the
    request's user entries as a decision item with a state line, and each agent entry as a fact. Embeddings
    are answered at once.
    """

    def __init__(self):
        self.requests, self.held = [], threading.Event()
        self.gate, self.holding = threading.Event(), False
        self.mutex = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                headers = {key.lower(): value for key, value in self.headers.items()}
                row = {"path": self.path, "at": time.time(), "headers": headers}
                with outer.mutex:
                    outer.requests.append(row)
                try:
                    value = json.loads(body)
                    if self.path.endswith("/count_tokens"):
                        return outer.send(self, b'{"error":{"type":"api_error"}}', 500, "application/json")
                    if self.path.endswith("/embeddings"):
                        data = [{"object": "embedding", "index": n, "embedding": vector(text)}
                                for n, text in enumerate(value["input"])]
                        document = {"object": "list", "model": value["model"], "data": data,
                                    "usage": {"prompt_tokens": 9 * len(data), "total_tokens": 9 * len(data)}}
                        row["kind"] = "embeddings"
                        return outer.send(self, json.dumps(document).encode("utf-8"), 200, "application/json")
                    row["kind"] = request_kind(value)
                    row["decisions"] = outer.decisions(value)
                    row["content"] = value["messages"][0]["content"]
                    answer = outer.answer(value)
                    row["titles"] = [change["title"] for change in (answer.get("changes") or answer.get("merges") or [])
                                     ] if isinstance(answer, dict) else []
                    row["holding"] = outer.holding
                    if outer.holding:
                        outer.held.set()
                        row["released"] = outer.gate.wait(HOLD_SECONDS)
                    row["answered"] = time.time()
                    body = answer if isinstance(answer, bytes) else curate_stream(answer)
                    return outer.send(self, body, 200, "text/event-stream")
                except (OSError, ValueError, KeyError, TypeError) as error:
                    row["error"] = repr(error)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d" % self.server.server_port

    @staticmethod
    def send(handler, body, status, mime):
        handler.send_response(status)
        handler.send_header("Content-Type", mime)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("request-id", "req_fixture")
        handler.end_headers()
        handler.wfile.write(body)
        handler.wfile.flush()

    @staticmethod
    def entries(value):
        root = ET.fromstring(value["messages"][0]["content"])
        return [(entry.get("id"), entry.get("speaker"), entry.text or "") for entry in root.iter("entry")]

    @staticmethod
    def items(value):
        """The request's items, as {id: title}."""
        root = ET.fromstring(value["messages"][0]["content"])
        return {item.get("id"): item.findtext("title") or "" for item in root.iter("item")}

    def decisions(self, value):
        return [marker for _, _, _, marker in self.marked(value)]

    def marked(self, value):
        found = []
        for ident, speaker, text in self.entries(value):
            if speaker != "user":
                continue
            for _, _, marker, _ in DECISIONS:
                if "결정:" in text and marker in text.split("결정:", 1)[1]:
                    found.append((ident, speaker, text, marker))
        return found

    def answer(self, value):
        kind = request_kind(value)
        if kind == "merge":
            return {"merges": [], "conflicts": []}
        if kind == "state":
            return KEEP_STATE
        changes, added = [], []
        for ident, _, _, marker in self.marked(value):
            changes.append({"action": "add", "targets": [], "kind": "decision",
                            "quotes": [{"entry": ident, "words": marker}],
                            "title": "Decision " + marker, "text": line(marker), "conflicts": []})
            added.append({"part": "decisions", "after": "", "text": line(marker),
                          "cites": [], "changes": [len(changes)]})
        for ident, speaker, text in self.entries(value):
            words = text.split()
            if speaker == "agent" and words:
                changes.append({"action": "add", "targets": [], "kind": "fact",
                                "quotes": [{"entry": ident, "words": words[0]}],
                                "title": "Answer " + ident, "text": "The agent answered in " + ident + ".",
                                "conflicts": []})
        return {"changes": changes, "state": {"change": [], "add": added, "remove": []}}

    def hold(self):
        self.holding = True

    def release(self):
        self.gate.set()

    def rearm(self):
        self.holding = False
        self.gate.clear()
        self.held.clear()

    def close(self):
        self.gate.set()
        self.server.shutdown()
        self.server.server_close()


def command_lines():
    """Every process's command line that this user can read, as the system lists them; raises when it cannot."""
    if os.name == "nt":
        args = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                "Get-CimInstance Win32_Process | ForEach-Object { $_.CommandLine }"]
    else:
        args = ["ps", "-axww", "-o", "args="]
    done = subprocess.run(args, capture_output=True, timeout=120 if os.name == "nt" else 60)
    lines = done.stdout.decode("utf-8", "replace").splitlines()
    if done.returncode != 0 or not lines:
        raise subprocess.SubprocessError("%s exited %d with %d lines" % (args[0], done.returncode, len(lines)))
    return lines


def workers(lines):
    return [text for text in lines if "scripts/worker.py" in text.replace("\\", "/")]


def configure(home, turns):
    path = home / ".corthex/corthex-memory/configuration.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["triggers"] = {"turns": turns, "minutes": 30}
    value["recall"] = dict(value.get("recall") or {}, threshold=0.2)
    value["models"] = dict(value.get("models") or {}, dims=DIMS)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def store_files(home):
    folder = home / ".corthex/corthex-memory"
    return [path for path in folder.rglob("*") if path.is_file()]


def during(row, host, started, ended):
    """Whether a log line of the memory store is one host's, written between two times; the lines name no session."""
    at = datetime.strptime(row["at"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()
    return row.get("host") == host and started - 1 <= at <= ended + 1


def hook_rows(home, host, started, ended):
    """The hook timing lines (TBL-005) of one host between two times."""
    return [row for path in sorted((home / ".corthex/corthex-memory/logs").glob("hooks-*.jsonl"))
            for row in map(json.loads, path.read_text(encoding="utf-8").splitlines())
            if during(row, host, started, ended)]


def failure_rows(home):
    return [json.loads(line) for path in sorted((home / ".corthex/corthex-memory/logs").glob("failures-*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines()]


def late_recall(row):
    """A failure line of a recall that gave up at its window, as API-010 means it to: the prompt hook's own note."""
    return row.get("hook") == "prompt" and row.get("step") == "recall" and row.get("error") == "deadline"


def items(home):
    found = {}
    for path in (home / ".corthex/corthex-memory/projects/demo/layer/items").glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        found[value["id"]] = value
    return found


def settled(home, titles, timeout=SETTLE_SECONDS):
    """Wait until the worker applied the held answers' items and released the project's curation lease."""
    started = time.time()
    root = home / ".corthex/corthex-memory/projects/demo"
    missing = set(titles)
    while time.time() - started < timeout:
        missing = set(titles) - {value.get("title") for value in items(home).values()}
        if (titles and not missing and not (root / "curation.lock").exists() and
                not list((root / "unprocessed").iterdir())):
            return {"applied": True, "seconds": round(time.time() - started, 2), "titles": sorted(titles)}
        time.sleep(0.2)
    return {"applied": False, "seconds": round(time.time() - started, 2), "missing": sorted(missing)}


def runs_saved(home):
    """The items that each curation's run log (TBL-121) lists as saved, by item: the run's ID."""
    found = {}
    for path in (home / ".corthex/corthex-memory/projects/demo/runs").glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("kind") == "curate":
            for item in value.get("saved", []):
                found[item] = value["id"]
    return found


def prompt_injections(home):
    """The injection log's prompt lines (TBL-007), as (host, outcome); each file is named after its host."""
    rows = []
    for path in sorted((home / ".corthex/corthex-memory/projects/demo/injections").glob("*.jsonl")):
        host = "codex" if path.name.startswith("codex-") else "claude"
        for text in path.read_text(encoding="utf-8").splitlines():
            value = json.loads(text)
            if value.get("where") == "prompt":
                rows.append((host, value.get("outcome")))
    return rows


def model_bodies(log):
    if not log.exists():
        return []
    return [json.loads(line)["body"] for line in log.read_text(encoding="utf-8").splitlines()
            if re.search(r"/v1/(messages|responses)(\?|$)", json.loads(line)["path"])]


class Hosts:
    def __init__(self, out):
        self.out, self.mock, self.memory = out, hookcheck.Mock(), MemoryServer()
        self.mock.stream = self.after_start_worker
        self.source, self.plugin = stage(hookcheck.REPO, out)
        hookcheck.REPO, hookcheck.MEMORY = self.source, self.plugin
        self.home, self.demo = hookcheck.prepare(out / "shared")
        self.keys = {"CORTHEX_MEMORY_ANTHROPIC_API_KEY": "MARKERANTHROPIC" + secrets.token_hex(16),
                     "CORTHEX_MEMORY_OPENAI_API_KEY": "MARKEROPENAI" + secrets.token_hex(16)}
        # The command lines read stay here, out of the report: a crash writes the report as it stands.
        self.lines, self.count = [], 0
        self.report = {"release": RELEASE, "store": self.store_kind(), "installs": {}, "sessions": [],
                       "command_lines": 0}

    def mask(self, text):
        for key in self.keys.values():
            text = text.replace(key, "<marker>")
        return text

    def after_start_worker(self, path, model):
        """The host's model answers once the worker that the start hook launched has ended.

        Each session start launches the worker (API-001), which holds the project's curation lease while it
        runs and may curate the prompt that the prompt hook marked; a trigger at the end of the turn finds that
        lease fresh and starts none (SPEC-012). Waiting until the lease has been gone for QUIET seconds and no
        `--reason start` worker runs lets the triggers of the turn's end start their own, whose curate
        requests the memory server then holds. Only a model request waits; the mock answers anything else.
        """
        if MODEL_PATH.search(path):
            lock = self.home / ".corthex/corthex-memory/projects/demo/curation.lock"
            started = quiet = time.time()
            while time.time() - started < 60:
                if lock.exists():
                    quiet = time.time()
                elif time.time() - quiet >= QUIET:
                    try:
                        if not any("--reason start" in text for text in workers(command_lines())):
                            break
                    except (OSError, subprocess.SubprocessError):
                        pass
                    quiet = time.time() - QUIET + 0.5
                time.sleep(0.1)
            self.memory.hold()
        return hookcheck.Mock.stream(path, model)

    def store_kind(self):
        record = json.loads((self.home / ".corthex/corthex-memory/store.json").read_text(encoding="utf-8"))
        return {"format": record.get("format"), "release": record.get("release")}

    def environment(self, host):
        env = hookcheck.base_env(self.home)
        env.update(self.keys)
        env.update(CORTHEX_MEMORY_ANTHROPIC_BASE_URL=self.memory.url, CORTHEX_MEMORY_OPENAI_BASE_URL=self.memory.url)
        base = self.out / host
        if host == "claude":
            env.update(CLAUDE_CONFIG_DIR=str(base / "config"), ANTHROPIC_API_KEY="sk-ant-" + secrets.token_hex(12),
                       ANTHROPIC_BASE_URL="http://127.0.0.1:%d" % self.mock.port,
                       CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", DISABLE_AUTOUPDATER="1")
        else:
            codex_home = base / "codex-home"
            if not codex_home.exists():
                # Written once: `codex plugin add` adds the plugins' switches to this file.
                codex_home.mkdir(parents=True)
                (codex_home / "config.toml").write_text(hookcheck.CODEX_CONFIG % self.mock.port, encoding="utf-8")
            env.update(CODEX_HOME=str(codex_home), MOCK_KEY="fixture-" + secrets.token_hex(12))
        return env

    def install(self, host):
        env = self.environment(host)
        exe = shutil.which(host, path=env["PATH"])
        if not exe:
            raise RuntimeError(host + " not found")
        version = hookcheck.short(hookcheck.run([exe, "--version"], env, self.demo, timeout=60)["stdout"], 80)
        if host == "claude":
            steps = [("marketplace corthex", ["plugin", "marketplace", "add", str(self.source)]),
                     ("install corthex-memory", ["plugin", "install", "corthex-memory@corthex"])]
        else:
            steps = [("marketplace corthex", ["plugin", "marketplace", "add", str(self.source)]),
                     ("add corthex", ["plugin", "add", "corthex@corthex"]),
                     ("add corthex-memory", ["plugin", "add", "corthex-memory@corthex"])]
        self.report["installs"][host] = {"version": version,
                                         "steps": hookcheck.install_steps(exe, env, self.demo, steps)}
        return exe

    def session(self, host, exe, prompt, extra=None, label=None, folder=None):
        env = self.environment(host)
        env.update(extra or {})
        # Each session has its own request log: the mock appends, and the bodies are read back per session.
        number, self.count = self.count, self.count + 1
        log = self.out / host / ("requests-%d.jsonl" % number)
        self.mock.log = log
        stdin = ""
        if host == "claude":
            args = [exe, "-p", prompt, "--output-format", "json"]
        else:
            # On Windows `codex` is an npm .cmd shim, and cmd.exe ends an argument at its first line break:
            # a prompt of several lines goes in on stdin, which `codex exec -` reads as the prompt.
            if "\n" in prompt:
                prompt, stdin = "-", prompt
            args = [exe, "exec", "--json", "--skip-git-repo-check", "--ephemeral", "--dangerously-bypass-hook-trust",
                    prompt]
        sampler = Sampler(self.memory)
        sampler.start()
        started = time.time()
        done = hookcheck.run(args, env, folder or self.demo, stdin=stdin, timeout=180)
        ended = time.time()
        (self.out / host / ("output-%d.txt" % number)).write_text(
            hookcheck.scrub_mock_key(done["stdout"] + "\n--- stderr ---\n" + done["stderr"],
                                     env.get("ANTHROPIC_API_KEY") or env.get("MOCK_KEY")), encoding="utf-8")
        self.mock.log = None
        for key in (env.get("ANTHROPIC_API_KEY"), env.get("MOCK_KEY")):
            if key:
                done = hookcheck.scrub_mock_key(done, key)
        try:
            session = hookcheck.native_session(host, done)
        except AssertionError:
            session = None
        return {"host": host, "label": label, "session": session, "exit": done["exit"], "seconds": done["seconds"],
                "started": started, "ended": ended, "bodies": model_bodies(log), "sampler": sampler,
                "stderr": hookcheck.short(done["stderr"], 400)}

    def decide(self, number, exes):
        host, turns, marker, prompt = DECISIONS[number]
        configure(self.home, turns)
        self.memory.rearm()
        before = len(self.memory.requests)
        result = self.session(host, exes[host], prompt, label="decision %d" % (number + 1))
        sampler = result.pop("sampler")
        # The curate request is held: the worker must still be running after the host process has ended.
        held = self.memory.held.wait(30)
        sampler.stop(after=2.0)
        curate = [row for row in self.memory.requests[before:] if row.get("kind") == "curate"]
        waiting = [row for row in curate if row.get("holding")]
        result["held_after_exit"] = bool(held and waiting and not self.memory.gate.is_set())
        result["held_sent_before_exit"] = bool(waiting) and waiting[0]["at"] <= result["ended"]
        self.memory.release()
        titles = {title for row in waiting for title in row["titles"]}
        result["settled"] = settled(self.home, sorted(titles))
        result["decision"] = settled(self.home, ["Decision " + marker], timeout=5)["applied"]
        # The run log must list each item that the held answers added (TBL-121): a log that the worker could
        # not write leaves the run unlisted and notes the failure, which the lock-busy exception must not hide.
        added = [ident for ident, value in items(self.home).items() if value.get("title") in titles]
        logged = runs_saved(self.home)
        result["run_logged"] = {"items": len(added), "unlisted": [ident for ident in added if ident not in logged],
                                "runs": sorted({logged[ident] for ident in added if ident in logged})}
        result["curate_requests"] = {"answered at once": len(curate) - len(waiting), "held": len(waiting)}
        result["curate_decisions"] = [row.get("decisions") for row in curate]
        rows = hook_rows(self.home, HOST_NAMES[host], result["started"], result["ended"])
        result["hooks"] = {row["hook"]: {"outcome": row["outcome"], "ms": row.get("ms")} for row in rows}
        result["workers"] = [self.mask(text) for text in sampler.workers]
        result["reasons"] = sorted({match for text in sampler.workers for match in REASON.findall(text)})
        result["expected_reason"] = "end-of-turn" if turns == 1 else "end"
        result["command_reads"] = {"reads": sampler.reads, "lines": len(sampler.lines),
                                   "errors": [self.mask(text) for text in sampler.errors[:5]]}
        self.lines.extend(sampler.lines)
        # The curator's line for the earlier decision, which only the start summary or recall can carry.
        earlier = [line(DECISIONS[number - 1][2])] if number else []
        result["shows_earlier"] = {text: any(text in body for body in result["bodies"]) for text in earlier}
        result.pop("bodies")
        self.report["sessions"].append(result)
        return result

    def scrub(self, exe):
        """TC-257: Claude Code with CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1 and both memory keys set."""
        configure(self.home, 10)
        before = len(self.memory.requests)
        self.memory.rearm()
        self.memory.release()
        result = self.session("claude", exe, "DEC-DELTA-tag 태그 접두어를 다시 알려 주세요. 짧게 답해 주세요.",
                              extra={"CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1"}, label="scrub")
        sampler = result.pop("sampler")
        sampler.stop()
        self.lines.extend(sampler.lines)
        bodies = result.pop("bodies")
        time.sleep(3)
        sent = [row for row in self.memory.requests[before:]]
        result["memory_requests"] = [row.get("kind") for row in sent]
        result["notice"] = any("CLAUDE_CODE_SUBPROCESS_ENV_SCRUB" in body for body in bodies)
        result["recalled"] = any(line("DEC-DELTA-tag") in body for body in bodies)
        result["keys_reached_hooks"] = bool(sent)
        rows = hook_rows(self.home, HOST_NAMES["claude"], result["started"], result["ended"])
        result["hooks"] = {row["hook"]: {"outcome": row["outcome"], "ms": row.get("ms")} for row in rows}
        self.report["scrub"] = result
        return result

    def traces(self):
        """TC-254: the markers reach the memory server and appear in no stored file and no command line."""
        found = {}
        for name, key in self.keys.items():
            stored = [path.relative_to(self.home).as_posix() for path in store_files(self.home)
                      if key.encode("utf-8") in path.read_bytes()]
            lines = sum(1 for line in self.lines if key in line)
            sent = sum(1 for row in self.memory.requests if key in json.dumps(row["headers"]))
            found[name] = {"files_with_marker": stored, "command_lines_with_marker": lines, "requests_with_key": sent}
        self.report["keys"] = found
        self.report["command_lines"] = len(self.lines)
        # The recall half of the case: each host's prompt hook ranked the items with the OpenAI key.
        recalls = {}
        for host, outcome in prompt_injections(self.home):
            recalls.setdefault(host, {}).setdefault(outcome, 0)
            recalls[host][outcome] += 1
        self.report["recalls"] = recalls
        return found


class Sampler(threading.Thread):
    """Reads the processes' command lines every SAMPLE_SECONDS while it runs, keeping the memory worker's."""

    def __init__(self, memory):
        super().__init__(daemon=True)
        self.lines, self.workers, self.errors, self.halt = [], [], [], threading.Event()
        self.reads = 0
        self.memory = memory

    def run(self):
        while not self.halt.is_set():
            try:
                found = command_lines()
                self.reads += 1
            except (OSError, subprocess.SubprocessError) as error:
                self.errors.append(repr(error))
                found = []
            self.lines.extend(found)
            for line in workers(found):
                if hookcheck.short(line, 400) not in self.workers:
                    self.workers.append(hookcheck.short(line, 400))
            self.halt.wait(SAMPLE_SECONDS)

    def stop(self, after=0.0):
        if after:
            time.sleep(after)
        self.halt.set()
        self.join(timeout=150)


def verdicts(report):
    sessions = report["sessions"]
    hooks_ok = all(row["outcome"] == "ok" for value in sessions for row in value["hooks"].values())
    late = [row for row in report.get("failures", []) if late_recall(row)]

    def returned(value):
        # Each hook's outcome is `ok`. The prompt hook's may be `deadline` only when this session's own failure
        # line says that its recall gave up at its window: any other step that a deadline cut fails the case.
        own = [row for row in late if during(row, HOST_NAMES[value["host"]], value["started"], value["ended"])]
        return all(row["outcome"] == "ok" or (hook == "prompt" and row["outcome"] == "deadline" and bool(own))
                   for hook, row in value["hooks"].items())

    per = {}
    for value in sessions:
        per[value["label"]] = {
            "exit": value["exit"] == 0,
            "four hooks ok or late in recall": set(value["hooks"]) >= {"start", "prompt", "end-of-turn", "end"} and
            returned(value),
            "trigger started the worker": value["expected_reason"] in value["reasons"],
            "worker held after the host ended": value["held_after_exit"],
            "held results applied after release": value["settled"]["applied"],
            "run log lists the applied items": value["run_logged"]["items"] > 0 and
            not value["run_logged"]["unlisted"],
            "command lines read, with the worker": value["command_reads"]["reads"] > 0 and bool(value["workers"]),
            "decision curated": value["decision"],
            "earlier decision shown": all(value["shows_earlier"].values()),
        }
    triggers = {value["label"]: value["reasons"] for value in sessions}
    keys = report.get("keys", {})
    # A failure that the worker or a hook noted, such as a run log it could not write, fails the case. A lock
    # that stayed busy is reported but passes: `model_usage` appends a usage line once, on a best-effort basis,
    # so a hook and the worker appending at once may leave one out and note it. So is a late recall.
    blocking = [row for row in report.get("failures", []) if row.get("error") != "lock-busy" and not late_recall(row)]
    tc253 = bool(per) and not blocking and all(
        v["exit"] and v["four hooks ok or late in recall"] and v["trigger started the worker"] and
        v["worker held after the host ended"] and v["held results applied after release"] and
        v["run log lists the applied items"] for v in per.values())
    # TC-254 needs evidence that it looked: a ranked recall in each host, and command lines read in each
    # session while the memory worker ran.
    recalls = report.get("recalls", {})
    recalled = {host: sum(count for outcome, count in recalls.get(host, {}).items() if outcome in RANKED)
                for host in HOST_NAMES}
    tc254 = (bool(keys) and all(not v["files_with_marker"] and not v["command_lines_with_marker"] and
                                v["requests_with_key"] > 0 for v in keys.values()) and
             all(recalled.values()) and report.get("command_lines", 0) > 0 and bool(per) and
             all(v["command lines read, with the worker"] for v in per.values()))
    tc255 = bool(per) and all(v["earlier decision shown"] and v["decision curated"] for v in per.values())
    scrub = report.get("scrub", {})
    tc257 = bool(scrub) and scrub.get("exit") == 0 and (
        scrub["keys_reached_hooks"] or (scrub["notice"] and not scrub["memory_requests"]))
    return {"sessions": per, "triggers": triggers, "hooks_ok": hooks_ok, "blocking_failures": blocking,
            "late recalls": len(late), "ranked recalls": recalled,
            "TC-253": tc253, "TC-254": tc254, "TC-255": tc255, "TC-257": tc257,
            "TC-257 observed": "keys reached the hooks" if scrub.get("keys_reached_hooks") else
            "keys kept from the hooks" if scrub else "not run"}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    out = Path(sys.argv[1]).resolve() / "c2-hosts"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    report, hosts = {}, None
    try:
        hosts = Hosts(out)
        report = hosts.report
        exes = {host: hosts.install(host) for host in ("claude", "codex")}
        for number in range(len(DECISIONS)):
            hosts.decide(number, exes)
        hosts.scrub(exes["claude"])
        hosts.traces()
        report["failures"] = [{key: row.get(key) for key in ("at", "hook", "step", "error", "host")}
                              for row in failure_rows(hosts.home)]
    except Exception:
        report["crash"] = traceback.format_exc()
    finally:
        if hosts is not None:
            hosts.memory.close()
            report["command_lines"] = len(hosts.lines)
            if "crash" in report:
                report["crash"] = hosts.mask(report["crash"])
            report["memory_requests"] = [{key: row.get(key) for key in ("path", "kind", "decisions", "released",
                                                                         "content", "error")}
                                         for row in hosts.memory.requests]
    report["verdicts"] = verdicts(report) if "crash" not in report else {}
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    cases = ("TC-253", "TC-254", "TC-255", "TC-257")
    text = ["== C2 in installed hosts at %s ==" % RELEASE]
    if "crash" in report:
        text.append(report["crash"])
    else:
        for host, value in report["installs"].items():
            text.append("%s %s: installs %s" % (host, value["version"], "ok" if all(
                step["exit"] == 0 for step in value["steps"].values()) else value["steps"]))
        for label, value in report["verdicts"]["sessions"].items():
            text.append("%s: %s" % (label, ", ".join("%s %s" % (k, "yes" if v else "NO") for k, v in value.items())))
        text.append("workers seen, by reason: " + json.dumps(report["verdicts"]["triggers"]))
        text.append("keys: " + json.dumps(report.get("keys", {})))
        text.append("command lines read: %d; ranked recalls by host: %s" % (
            report.get("command_lines", 0), json.dumps(report["verdicts"]["ranked recalls"])))
        text.append("TC-257: " + report["verdicts"]["TC-257 observed"] + "; " + json.dumps(
            {key: report["scrub"].get(key) for key in ("notice", "memory_requests", "recalled")}))
        text.append("failure log: " + json.dumps(report.get("failures", [])))
        text.append("failures that fail TC-253: " + json.dumps(report["verdicts"]["blocking_failures"]))
        text.append("recalls that gave up at their window, counted and not failed: %d" %
                    report["verdicts"]["late recalls"])
        for case in cases:
            text.append("%s: %s" % (case, "pass" if report["verdicts"][case] else "FAIL"))
    print("\n".join(text))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write("```\n%s\n```\n" % "\n".join(text))
    return 0 if report["verdicts"] and all(report["verdicts"][case] for case in cases) else 1


if __name__ == "__main__":
    sys.exit(main())
