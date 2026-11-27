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
read, every half second (every two on Windows, where reading them is slow),
and once more while the request is held, when the worker is certainly running.
Both memory keys are markers, which must reach the server and appear in no
file of the memory store and in no command line (TC-254); a file of the store
that cannot be read fails the case, since it may hold one. The case also needs
evidence that it looked: for each host, a prompt whose recall ranked the items
(`injected` or `below` in the injection log), and in each session a reading of
the command lines that showed the memory worker. A host whose recalls gave up
at their window and ranked nothing gets one more session of one prompt before
that evidence is judged, as the walk replays ask such a prompt once more. Then
Claude Code runs once more with CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1 (TC-257):
either each key comes in a request, which shows that the keys reached the
hooks, or the start summary shows the notice and no request comes at all; one
key without the other fails the case. Its requests are counted from a moment
when no worker holds the project or runs to the next such moment after the
session; a worker that is still there after SETTLE_SECONDS, before or after,
fails the case, since its requests could not be told from the session's own.
A worker's command line names its plugin's folder and its project, never its
home. The hosts install the plugin under this run's folder, so a worker is
this run's only when the path of its script begins with that folder: the
memory workers of another home, such as those of the user's own sessions on the
same machine, are neither waited for nor kept in the report. A run empties
OUTDIR/c2-hosts and uses it again, so it does not start while a memory worker
whose script lies there still runs, such as one that an interrupted run left
going: that worker would count as this run's. A wait that ran out leaves in
the report what it saw as it ended: the lease at its last look, for how long no
lease had been seen, and this run's memory workers' command lines by the last
reading since a look last met the lease or, when there was none, by one made
then, after which the lease is looked at once more; that reading is kept
whatever the look after it met.

Any failure that the worker or a hook notes in the failure log fails TC-253,
with two exceptions that the summary lists: a lock that stayed busy, and a
recall that gave up at its window (API-010), whose line says `deadline` or
`timeout`. The prompt hook then returns with the outcome `deadline`, and the
prompt goes on without a recall block; how often that happens is a matter of
the machine's speed, which TC-256 measures, so the case counts it and does not
fail on it. The hooks that can start the worker, at the session's start, at
the end of a turn and at the session's end, must each return within their own
deadline by their timing line (TBL-005); the prompt hook's time is TC-256's.
The report keeps the number of command lines that were read for TC-254: every
line of the sessions' readings and of the readings of the waits that follow a
session, when no session's readings run. Of the lines themselves it keeps only
this run's memory workers', with a key in them masked.
It writes report.json and prints a summary, and exits 1 when a case fails. It
exits 2 without a run, and leaves the folder as it was, while a memory worker
of the folder still runs or when the command lines cannot be read to tell.
"""
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import xml.etree.ElementTree as ET
from xml.parsers import expat

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run as hookcheck  # noqa: E402

RELEASE = "0.3.0"
DIMS = 512
HOLD_SECONDS = 120
QUIET = 3.0
START_WORKER_SECONDS = 60
SETTLE_SECONDS = 90
# How often the reading of the command lines that follows a session's readings is tried until one works, and
# the seconds between two tries.
LAST_READINGS, LAST_READING_PAUSE = 3, 1.0
# The seconds between two reads of a file of the memory store that a worker may be writing just now, how often
# the failure log is read for the hosts to ask once more until a read works (`Hosts.late_only`), and how often
# the store's files are read for the markers until every file could be read (`marked_files`).
STORE_READ_PAUSE, FAILURE_LOG_READS, STORE_READ_PASSES = 0.5, 3, 5
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
# The prompt of a session that only asks a recall once more (`Hosts.recall_again`).
AGAIN = "DEC-BRAVO-check 검사 명령을 다시 알려 주세요. 짧게 답해 주세요."
HOST_NAMES = {"claude": "claude-code", "codex": "codex"}
WORDS = re.compile(r"[0-9A-Za-z가-힣._-]+")
REASON = re.compile(r"--reason (\S+)")
MODEL_PATH = re.compile(r"/v1/(messages|responses)(\?|$)")
SAMPLE_SECONDS = 2.0 if os.name == "nt" else 0.5
# The extensions that a host's program may have: on Windows npm installs it as a `.cmd` shim.
HOST_EXTENSIONS = (".exe", ".cmd", ".bat") if os.name == "nt" else ("",)
RANKED = ("injected", "below")
# The own deadlines, in milliseconds, of the hooks that can start the worker (`memory_lib.hooks.SECONDS`).
DEADLINE_MS = {"start": 1000, "end-of-turn": 300, "end": 500}
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
    if staged.exists():  # Until the release makes it the plugin's hooks file (TASK-051).
        os.replace(str(staged), str(memory / "hooks/hooks.json"))
    return target, memory


def line(marker):
    """The state line, and the item text, that the memory server's answer gives a decision."""
    return "The user decided " + marker + "."


def vector(text, dims=DIMS):
    """A made-up embedding: `dims` numbers for a text, the same for the same text.

    It does not tell texts apart by their words. A word's bucket comes from its first eight bytes read as one
    number, whose low bits are zero for a word of up to six bytes: every such word adds to bucket 0, and
    nearly every text comes close to every other. A recall against it shows that the hook embeds, ranks and
    injects, and which items it leaves out, never that what it injects matches the prompt.
    """
    values = [0.0] * dims
    for word in WORDS.findall(text.lower()):
        bucket = int.from_bytes(word.encode("utf-8")[:8].ljust(8, b"\0"), "big") * 2654435761 % dims
        values[bucket] += 1.0
    if not any(values):
        values[0] = 1.0
    return values


def marker_keys():
    """Both memory keys, made up for the run as markers that the checks can look for."""
    return {"CORTHEX_MEMORY_ANTHROPIC_API_KEY": "MARKERANTHROPIC" + secrets.token_hex(16),
            "CORTHEX_MEMORY_OPENAI_API_KEY": "MARKEROPENAI" + secrets.token_hex(16)}


def memory_urls(url):
    """The variables that send the memory worker's and the prompt hook's requests to the local server."""
    return {"CORTHEX_MEMORY_ANTHROPIC_BASE_URL": url, "CORTHEX_MEMORY_OPENAI_BASE_URL": url}


def event(kind, **data):
    return ("event: " + kind + "\ndata: " + json.dumps(dict(type=kind, **data), ensure_ascii=False) + "\n\n").encode("utf-8")


def stopped_stream(reason, output=1):
    """A provider's answer that stopped for `reason` before any text, with `output` tokens counted as written."""
    message = dict(type="message", role="assistant", content=[],
                   usage={"input_tokens": 900, "output_tokens": 1, "cache_creation_input_tokens": 0,
                          "cache_read_input_tokens": 0})
    return (event("message_start", message=message) +
            event("message_delta", delta={"stop_reason": reason}, usage={"output_tokens": output}) +
            event("message_stop"))


def document(value):
    """The XML of a memory request, as its root element.

    A document type is refused. The package's requests have none, and without one a request declares no
    entity, so nothing in it expands: this server parses whatever a local process posts to it.
    """
    builder, parser = ET.TreeBuilder(), expat.ParserCreate()

    def refuse(*_):
        raise ValueError("a memory request has no document type")

    parser.buffer_text = True
    parser.StartDoctypeDeclHandler = refuse
    parser.StartElementHandler, parser.EndElementHandler = builder.start, builder.end
    parser.CharacterDataHandler = builder.data
    try:
        parser.Parse(value["messages"][0]["content"], True)
    except expat.ExpatError as error:
        raise ValueError("a memory request that is not XML: %s" % error) from error
    return builder.close()


def request_kind(value):
    """The kind of a memory request: curate, merge or state."""
    return document(value).get("kind")


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


# The signals that interrupt a check, by the names that a system has.
INTERRUPTS = ("SIGINT", "SIGTERM", "SIGHUP")


def serve(server):
    """Start the thread that serves `server`, which takes no signal that interrupts a check.

    Python runs a signal's handler in the main thread, and a wait of the main thread ends for a signal only
    when that thread received it. A signal that another thread received leaves the main thread waiting: a
    check that waits for a process would run its handler only once that process had ended. Linux gives a signal
    to another thread when the main one has a signal pending, as the second of two that come at once, and that
    thread can then take both. So the serving thread starts with these signals blocked, and with it each thread
    that it starts for a request; the thread that calls this keeps its own mask. A system without a mask for a
    thread's signals, as Windows, gives a thread no such signal.
    """
    mask = getattr(signal, "pthread_sigmask", None)
    before = None
    if mask is not None:
        before = mask(signal.SIG_BLOCK, [getattr(signal, name) for name in INTERRUPTS if hasattr(signal, name)])
    try:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    finally:
        if mask is not None:
            mask(signal.SIG_SETMASK, before)


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
                        tokens = outer.count(value)
                        if tokens is None:
                            return outer.send(self, b'{"error":{"type":"api_error"}}', 500, "application/json")
                        row["kind"] = "count"
                        return outer.send(self, json.dumps({"input_tokens": tokens}).encode("utf-8"), 200,
                                          "application/json")
                    if self.path.endswith("/embeddings"):
                        reply = outer.embeddings(value)
                        row["kind"] = "embeddings"
                        if reply is None:
                            return outer.send(self, b'{"error":{"type":"invalid_request_error"}}', 401,
                                              "application/json")
                        return outer.send(self, json.dumps(reply).encode("utf-8"), 200, "application/json")
                    row["kind"] = request_kind(value)
                    row["decisions"] = outer.decisions(value)
                    row["content"] = value["messages"][0]["content"]
                    answer = outer.answer(value)
                    row["titles"] = [change["title"] for change in (answer.get("changes") or answer.get("merges") or [])
                                     ] if isinstance(answer, dict) else []
                    row["holding"] = outer.holding
                    if row["holding"]:
                        outer.held.set()
                        row["released"] = outer.gate.wait(HOLD_SECONDS)
                    row["answered"] = time.time()
                    body = answer if isinstance(answer, bytes) else curate_stream(answer)
                    return outer.send(self, body, 200, "text/event-stream")
                except (OSError, ValueError, KeyError, TypeError) as error:
                    row["error"] = repr(error)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        serve(self.server)
        self.url = "http://127.0.0.1:%d" % self.server.server_port

    def count(self, value):
        """The count that a count request gets; None for the provider's error, which is what these checks expect."""
        return None

    def embeddings(self, value):
        """The answer that an embedding request gets: a vector of the length that it asks for, for each of its
        texts. None is the provider's refusal of the request, HTTP 401, which the package does not try again."""
        dims = value.get("dimensions", DIMS)
        data = [{"object": "embedding", "index": n, "embedding": vector(text, dims)}
                for n, text in enumerate(value["input"])]
        return {"object": "list", "model": value["model"], "data": data,
                "usage": {"prompt_tokens": 9 * len(data), "total_tokens": 9 * len(data)}}

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
        root = document(value)
        return [(entry.get("id"), entry.get("speaker"), entry.text or "") for entry in root.iter("entry")]

    @staticmethod
    def items(value):
        """The request's items, as {id: title}."""
        root = document(value)
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


def program(name, path=None, extensions=None):
    """A program's full path, from the absolute folders of PATH: Windows would try the current folder first.

    On Windows the name is tried with `.exe`, or in each folder with each of `extensions` in their order,
    which a host's lookup gives (HOST_EXTENSIONS). `path` stands for the environment's PATH.
    """
    if path is None:
        path = os.environ.get("PATH", "")
    if extensions is None:
        extensions = (".exe",) if os.name == "nt" else ("",)
    for folder in path.split(os.pathsep):
        folder = folder.strip('"')
        if not os.path.isabs(folder):
            continue
        for extension in extensions:
            found = os.path.join(folder, name + extension)
            if os.path.isfile(found) and os.access(found, os.X_OK):
                return found
    raise OSError(name + " is in no absolute folder of PATH")


def command_lines():
    """Every process's command line that this user can read, as the system lists them; raises when it cannot."""
    if os.name == "nt":
        args = [program("powershell"), "-NoProfile", "-NonInteractive", "-Command",
                "Get-CimInstance Win32_Process | ForEach-Object { $_.CommandLine }"]
    else:
        args = [program("ps"), "-axww", "-o", "args="]
    done = subprocess.run(args, capture_output=True, timeout=120 if os.name == "nt" else 60)
    lines = done.stdout.decode("utf-8", "replace").splitlines()
    if done.returncode != 0 or not lines:
        raise subprocess.SubprocessError("%s exited %d with %d lines" % (args[0], done.returncode, len(lines)))
    return lines


# The system's own rule for the case of a path, which `comparable` uses: a test gives `comparable` alone the rule
# of Windows through this name.
normcase = os.path.normcase
WORKER_SCRIPT = "scripts/worker.py"


def comparable(text):
    """A path or a command line as `workers` compares them: with one kind of slash and, on Windows, one case."""
    return normcase(text).replace("\\", "/")


def workers(lines, run_folder=None):
    """The memory workers' command lines; with `run_folder`, only those of the plugin that this run installed.

    A worker's command line names its plugin's folder and its project, never its home. The hosts install the
    plugin under this run's folder, so `run_folder`, that folder as `comparable` gives it, tells a worker of
    another home, such as one of the user's own sessions, apart. Only the path of the worker's script counts:
    the folder begins it, at the start of the line or after a space, a quote or `=`, and it reaches
    `scripts/worker.py` with no space or quote on the way and ends there. A line that names the folder anywhere
    else, such as in the interpreter's path, at the end of a longer path or in a file beside the script
    (`worker.py.bak`), is not one of the run's workers. Without `run_folder` every memory worker counts, of any
    home; each reading that `Hosts` makes gives its folder (`run_folder_of`).
    """
    # The script's name ends at a space, a quote or the line's end.
    end = re.escape(WORKER_SCRIPT) + r"(?=$|[\s\"'])"
    if run_folder is None:
        script = re.compile(end)
    else:
        script = re.compile(r"(?:^|(?<=[\s\"'=]))" + re.escape(run_folder.rstrip("/") + "/") + r"[^\s\"']*" + end)
    return [text for text in lines if script.search(comparable(text))]


def run_folder_of(out):
    """The run's folder as `workers` takes it: resolved, as the hosts install the plugin under it, then `comparable`.

    An OUTDIR given through a link, or on Windows by a short name, names the folder that the workers' script paths
    hold only once it is resolved (on macOS /var is /private/var).
    """
    return comparable(str(Path(out).resolve()))


def running(text, seen=None, run_folder=None):
    """Whether one of the memory workers (`workers`) runs whose line holds `text`; a failed reading counts as one.

    `seen`, a dict, is given what this reading showed: under `workers` those workers' lines, or under `unread`
    the error that it failed with. Under `lines`, a Counter, it keeps every line of this reading and of each
    reading that it was given before, for TC-254: a line read more than once is kept once, with its count.
    """
    try:
        lines = command_lines()
        found, error = [line for line in workers(lines, run_folder) if text in line], None
    except (OSError, subprocess.SubprocessError) as failed:
        lines, found, error = [], None, repr(failed)
    if seen is not None:
        seen.pop("workers", None)
        seen.pop("unread", None)
        seen.update({"workers": found} if error is None else {"unread": error})
        seen.setdefault("lines", Counter()).update(lines)
    return error is not None or bool(found)


def tried(read):
    """Calls `read`, which says whether it worked, until it works, LAST_READINGS times at most; whether it did.

    What made a reading fail may pass, so LAST_READING_PAUSE seconds come between two tries.
    """
    for left in range(LAST_READINGS, 0, -1):
        if read():
            return True
        if left > 1:
            time.sleep(LAST_READING_PAUSE)
    return False


def left_running(out):
    """The memory workers whose script lies under `out` and that still run, and the error of a reading that failed.

    A run empties OUTDIR/c2-hosts and uses it again, and `workers` takes a worker whose script lies there for one
    of the run's own: a worker that an interrupted run left going would count as this run's, and the waits would
    wait for it. The reading is tried as a session's last one is (`tried`); one that keeps failing cannot tell,
    and gives its last error as `repr` shows it, which names a program that is missing.

    A host that such a run left going is not looked for: `run` ends a host and its children when the run is
    interrupted or the session runs out of time, so only a run killed outright leaves one, and a host's command
    line names no path in the folder.
    """
    sampler = Sampler(run_folder_of(out))
    if tried(sampler.read):
        return sampler.workers, None
    return [], sampler.errors[-1]


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


def marked_files(home, keys, passes=STORE_READ_PASSES):
    """The memory store's files that hold each key, as {name: [path]}, and the files that could not be read.

    A worker may still be writing: a pass that meets a file which went away meanwhile, or which the system
    keeps from being read, is taken again. What the last pass could not read is returned, and fails TC-254.
    """
    while True:
        found, unread, passes = {name: [] for name in keys}, [], passes - 1
        try:
            paths = store_files(home)
        except OSError as error:
            paths, unread = [], ["the store's folders: " + type(error).__name__]
        for path in paths:
            name = path.relative_to(home).as_posix()
            try:
                data = path.read_bytes()
            except OSError:
                unread.append(name)
                continue
            for key, value in keys.items():
                if value.encode("utf-8") in data:
                    found[key].append(name)
        if not unread or passes <= 0:
            return found, unread
        time.sleep(STORE_READ_PAUSE)


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


def carries(row, key):
    """Whether a request to the memory server came with the key in one of its headers."""
    return key in json.dumps(row["headers"])


def unanswered(rows):
    """The held requests that the server has not answered: after HOLD_SECONDS it answers by itself."""
    return [row for row in rows if row.get("holding") and "answered" not in row]


def late_recall(row):
    """A failure line of a recall that gave up at its window, as API-010 means it to: the prompt hook's own note.

    Its code is `timeout` when the embedding's request was out as its time ended, and `deadline` otherwise.
    """
    return (row.get("hook") == "prompt" and row.get("step") == "recall" and
            row.get("error") in ("deadline", "timeout"))


def items(home, project="demo"):
    """A project's items, by ID."""
    found = {}
    for path in (home / ".corthex/corthex-memory/projects" / project / "layer/items").glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        found[value["id"]] = value
    return found


def busy(root, turns=True):
    """Whether a worker holds the project, or a turn waits for one.

    Turns wait for nothing while curation is stopped (TC-268), and after a curation that the script refused
    they wait for the next trigger (`turns=False`): then only the lease counts.
    """
    if (root / "curation.lock").exists():
        return True
    if not turns or not ((root / "unprocessed").is_dir() and any((root / "unprocessed").iterdir())):
        return False
    try:
        return "stopped" not in json.loads((root / "curation.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True


def look(root, turns=True):
    """One look at the project for `quiet`: whether it counts as busy, and what the look showed (`busy`)."""
    try:
        state = busy(root, turns)
    except OSError as error:
        # A folder that the worker is changing just now: the next look reads it.
        return True, "unread: " + type(error).__name__
    return state, state


def quiet(root, timeout=SETTLE_SECONDS, turns=True, worker=None, seen=None, run_folder=None):
    """Wait until the project has not been busy for QUIET seconds; whether that came within `timeout`.

    With `worker`, no memory worker of `run_folder` (`workers`) may run then whose command line holds that
    text, `""` for any: a worker that a hook has just launched does not hold the lease yet. A reading of the
    command lines that is under way as `timeout` ends is waited for, so the wait may last longer by that
    reading.

    `seen`, a dict, is given what the wait saw. `busy` is what its last look showed of the project: whether it
    was busy, or `unread` with the kind of the error that kept the look from telling, which counts as busy.
    `workers` or `unread` is the last reading of the command lines since a look last met the project busy, and
    `lines` every reading's lines (`running`). A wait that ran out also gives `calm`, the seconds since a look
    last met the project busy or since the wait began. With `worker`, when no reading was made since that look,
    it then reads the command lines once more, which takes the reading's time as well, and looks at the project
    once more right after that reading. That reading is kept whatever the look after it met: the two, and
    `calm` after them, show the wait's end, apart by no more than the reading's own time. Within the wait a
    busy look drops the reading before it, since another reading may follow; at the end none does.
    """
    # `counted_from` is the moment from which QUIET seconds are counted, `last_busy` that of the last busy look.
    started = counted_from = last_busy = time.time()
    while time.time() - started < timeout:
        moving, state = look(root, turns)
        if seen is not None:
            if moving:
                # What an earlier reading of the command lines showed is not what this look met.
                seen.pop("workers", None)
                seen.pop("unread", None)
            seen["busy"] = state
        if moving:
            counted_from = last_busy = time.time()
        elif time.time() - counted_from >= QUIET:
            if worker is None or not running(worker, seen, run_folder):
                return True
            counted_from = time.time() - QUIET + 0.5  # The command lines are read again in half a second.
        time.sleep(0.2)
    if seen is not None:
        if worker is not None and "workers" not in seen and "unread" not in seen:
            running(worker, seen, run_folder)
            moving, seen["busy"] = look(root, turns)
            if moving:
                last_busy = time.time()
        seen["calm"] = round(time.time() - last_busy, 1)
    return False


def waits_line(labels):
    """The summary's line for the sessions whose model answered after the wait for the start's worker ran out."""
    return "sessions whose model answered after %d s of waiting for the start's worker: %s" % (
        START_WORKER_SECONDS, json.dumps(labels, ensure_ascii=False))


def named(output, label=None):
    """A session's name in the report's lists: its label and its output file's place in the output folder."""
    return "%s (%s)" % (label, output) if label else output


def settled(home, titles, timeout=SETTLE_SECONDS):
    """Wait until the worker applied the held answers' items and released the project's curation lease.

    Without titles nothing was held, so there is nothing to wait for and nothing was applied.
    """
    started = time.time()
    root = home / ".corthex/corthex-memory/projects/demo"
    missing = set(titles)
    while titles and time.time() - started < timeout:
        try:
            missing = set(titles) - {value.get("title") for value in items(home).values()}
            if not missing and not busy(root):
                return {"applied": True, "seconds": round(time.time() - started, 2), "titles": sorted(titles)}
        except (OSError, ValueError):
            pass  # A file that the worker is replacing just now: the next look reads it.
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


def injection_lines(root):
    """A project's injection log lines (TBL-007), each with the name of its file, which begins with its host."""
    return [(path.name, json.loads(text)) for path in sorted((root / "injections").glob("*.jsonl"))
            for text in path.read_text(encoding="utf-8").splitlines()]


def prompt_injections(home):
    """The demo project's prompt lines of the injection log, as (host, outcome)."""
    return [("codex" if name.startswith("codex-") else "claude", value.get("outcome"))
            for name, value in injection_lines(home / ".corthex/corthex-memory/projects/demo")
            if value.get("where") == "prompt"]


def model_bodies(log):
    if not log.exists():
        return []
    return [json.loads(line)["body"] for line in log.read_text(encoding="utf-8").splitlines()
            if MODEL_PATH.search(json.loads(line)["path"])]


class Hosts:
    # Model requests of one session may wait at once: under this lock one of them names the session.
    naming = threading.Lock()

    def __init__(self, out, memory=None):
        self.out, self.mock = out, hookcheck.Mock()
        self.memory = MemoryServer() if memory is None else memory
        self.mock.stream = self.after_start_worker
        self.source, self.plugin = stage(hookcheck.REPO, out)
        hookcheck.REPO, hookcheck.MEMORY = self.source, self.plugin
        self.home, self.demo = hookcheck.prepare(out / "shared")
        # Both hosts install the plugin under this run's folder, which tells this run's memory workers apart.
        self.run_folder = run_folder_of(out)
        self.keys = marker_keys()
        # The command lines read stay here, out of the report: a crash writes the report as it stands. A line
        # read more than once is kept once, with its count.
        self.lines, self.count, self.label = Counter(), 0, None
        self.report = {"release": RELEASE, "store": self.store_kind(), "installs": {}, "sessions": [],
                       "command_lines": 0}

    def mask(self, text):
        for key in self.keys.values():
            text = text.replace(key, "<marker>")
        return text

    def shown(self, lines):
        """Command lines as the report shows them, a key masked before a long line is cut: none is left in part."""
        return [hookcheck.short(self.mask(text), 400) for text in lines]

    def after_start_worker(self, path, model):
        """The host's model answers once the worker that the start hook launched has ended.

        Each session start launches the worker (API-001), which holds the project's curation lease while it
        runs and may curate the prompt that the prompt hook marked; a trigger at the end of the turn finds that
        lease fresh and starts none (SPEC-012). Waiting until the lease has been gone for QUIET seconds and no
        `--reason start` worker runs lets the triggers of the turn's end start their own, whose curate
        requests the memory server then holds. Only a model request waits; the mock answers anything else.
        """
        if MODEL_PATH.search(path):
            root = self.home / ".corthex/corthex-memory/projects/demo"
            if not quiet(root, START_WORKER_SECONDS, turns=False, worker="--reason start",
                         run_folder=self.run_folder):
                # The session goes on, and its checks say what failed; the report names the session once.
                with self.naming:
                    waits = self.report.setdefault("start_worker_waits_given_up", [])
                    if self.label not in waits:
                        waits.append(self.label)
            self.memory.hold()
        return hookcheck.Mock.stream(path, model)

    def store_kind(self):
        record = json.loads((self.home / ".corthex/corthex-memory/store.json").read_text(encoding="utf-8"))
        return {"format": record.get("format"), "release": record.get("release")}

    def environment(self, host):
        env = hookcheck.base_env(self.home)
        env.update(self.keys)
        env.update(memory_urls(self.memory.url))
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
        exe = program(host, env["PATH"], HOST_EXTENSIONS)
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

    def session(self, host, exe, prompt, extra=None, label=None, folder=None, sample=True):
        """One session of one prompt; with `sample` the command lines are read while it runs (TC-254)."""
        env = self.environment(host)
        env.update(extra or {})
        # Each session has its own request log: the mock appends, and the bodies are read back per session.
        number, self.count = self.count, self.count + 1
        log = self.out / host / ("requests-%d.jsonl" % number)
        output = self.out / host / ("output-%d.txt" % number)
        # The output file names the session: the artifact of every check that runs sessions holds it.
        self.label = named(output.relative_to(self.out).as_posix(), label)
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
        sampler = Sampler(self.run_folder) if sample else None
        if sampler:
            sampler.start()
        started = time.time()
        done = hookcheck.run(args, env, folder or self.demo, stdin=stdin, timeout=180)
        ended = time.time()
        output.write_text(hookcheck.scrub_mock_key(done["stdout"] + "\n--- stderr ---\n" + done["stderr"],
                                                   env.get("ANTHROPIC_API_KEY") or env.get("MOCK_KEY")),
                          encoding="utf-8")
        self.mock.log = None
        for key in (env.get("ANTHROPIC_API_KEY"), env.get("MOCK_KEY")):
            if key:
                done = hookcheck.scrub_mock_key(done, key)
        try:
            session = hookcheck.native_session(host, done)
        except (AssertionError, ValueError, TypeError):
            session = None  # No one session ID, or an output line that is not the JSON it starts as.
        return {"host": host, "label": label, "session": session, "exit": done["exit"], "seconds": done["seconds"],
                "started": started, "ended": ended, "bodies": model_bodies(log), "sampler": sampler,
                "stderr": hookcheck.short(done["stderr"], 400)}

    def timings(self, host, result):
        """The timing lines (TBL-005) of one session's hooks, by hook."""
        rows = hook_rows(self.home, HOST_NAMES[host], result["started"], result["ended"])
        return {row["hook"]: {"outcome": row["outcome"], "ms": row.get("ms")} for row in rows}

    def rested(self):
        """Wait until no worker holds the demo project or runs any more; whether that came within SETTLE_SECONDS.

        A turn may stay unprocessed, as it does without the keys. A worker that a hook has just launched does
        not hold the lease yet, so the command lines are read as well, and only this run's memory workers are
        waited for (`workers`). No session's readings run during this wait, so every line of each of its
        readings counts for TC-254. A wait that ran out leaves in the report the session that it followed and
        what it saw as it ended (`quiet`): the lease at its last look, for how many seconds no lease had been
        seen, and this run's workers' command lines or the error of the last reading since the lease was last
        seen, or else of the reading made as the wait ended, which is kept although the look after it may have
        met the lease. A reading that failed counts as a worker.
        """
        seen = {}
        gone = quiet(self.home / ".corthex/corthex-memory/projects/demo", turns=False, worker="", seen=seen,
                     run_folder=self.run_folder)
        self.lines.update(seen.get("lines", ()))
        if not gone:
            left = {"after": self.label, "lease": seen.get("busy"), "calm_seconds": seen.get("calm")}
            if "workers" in seen:
                left["workers"] = self.shown(seen["workers"])
            if "unread" in seen:
                left["unread"] = self.mask(seen["unread"])
            self.report.setdefault("workers_left", []).append(left)
        return gone

    def decide(self, number, exes):
        host, turns, marker, prompt = DECISIONS[number]
        configure(self.home, turns)
        self.memory.rearm()
        before = len(self.memory.requests)
        result = self.session(host, exes[host], prompt, label="decision %d" % (number + 1))
        sampler = result.pop("sampler")
        # The curate request is held: the worker must still be running after the host process has ended.
        held = self.memory.held.wait(30)
        curate = [row for row in self.memory.requests[before:] if row.get("kind") == "curate"]
        waiting = [row for row in curate if row.get("holding")]
        # Judged before the reading below, which takes its time: the server answers a held request by itself
        # after HOLD_SECONDS.
        result["held_after_exit"] = bool(held and unanswered(waiting) and not self.memory.gate.is_set())
        result["held_sent_before_exit"] = bool(waiting) and waiting[0]["at"] <= result["ended"]
        # One more reading while the request is held: the worker is then running, wherever the readings'
        # own rhythm stands. Should the readings outlast HOLD_SECONDS the worker may be gone by then, and a
        # session whose readings showed no worker fails TC-254.
        sampler.stop(last=True)
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
        result["hooks"] = self.timings(host, result)
        result["workers"] = self.shown(sampler.workers)
        result["reasons"] = sorted({match for text in sampler.workers for match in REASON.findall(text)})
        result["expected_reason"] = "end-of-turn" if turns == 1 else "end"
        result["command_reads"] = {"reads": sampler.reads, "lines": sum(sampler.lines.values()),
                                   "errors": [self.mask(text) for text in sampler.errors[:5]]}
        self.lines.update(sampler.lines)
        # The curator's line for the earlier decision, which only the start summary or recall can carry.
        earlier = [line(DECISIONS[number - 1][2])] if number else []
        result["shows_earlier"] = {text: any(text in body for body in result["bodies"]) for text in earlier}
        result.pop("bodies")
        self.report["sessions"].append(result)
        return result

    def scrub(self, exe):
        """TC-257: Claude Code with CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1 and both memory keys set."""
        configure(self.home, 10)
        # Every request from here on counts as this session's, so no worker of an earlier one may be left.
        gone = self.rested()
        before = len(self.memory.requests)
        self.memory.rearm()
        self.memory.release()
        result = self.session("claude", exe, "DEC-DELTA-tag 태그 접두어를 다시 알려 주세요. 짧게 답해 주세요.",
                              extra={"CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1"}, label="scrub")
        sampler = result.pop("sampler")
        sampler.stop()
        self.lines.update(sampler.lines)
        bodies = result.pop("bodies")
        # A worker that has the keys sends its requests before it ends. Without them this session's turn
        # stays unprocessed, so the count waits for the workers and not for the turn.
        result["workers_gone"] = {"before": gone, "after": self.rested()}
        sent = self.memory.requests[before:]
        result["memory_requests"] = [row.get("kind") for row in sent]
        result["notice"] = any("CLAUDE_CODE_SUBPROCESS_ENV_SCRUB" in body for body in bodies)
        result["recalled"] = any(line("DEC-DELTA-tag") in body for body in bodies)
        # Only a request that carries a key shows that this key reached the hooks.
        result["keys_reached_hooks"] = {name: any(carries(row, key) for row in sent)
                                        for name, key in self.keys.items()}
        result["hooks"] = self.timings("claude", result)
        self.report["scrub"] = result
        return result

    def late_only(self):
        """The hosts that have no ranked recall so far and one that gave up at its window.

        Such a recall leaves `late` in the injection log, or, where that line's lock stayed busy, only the
        prompt hook's note in the failure log. A worker may be writing that log just now, so a read of it that
        fails is tried again, FAILURE_LOG_READS times in all. A log that stays unread leaves the injection log
        to decide and is named in the report; the run's end reads it again, strictly.
        """
        found, noted = {}, set()
        for host, outcome in prompt_injections(self.home):
            found.setdefault(host, set()).add(outcome)
        for left in range(FAILURE_LOG_READS, 0, -1):
            try:
                noted = {row.get("host") for row in failure_rows(self.home) if late_recall(row)}
                break
            except (OSError, ValueError) as error:
                if left > 1:
                    time.sleep(STORE_READ_PAUSE)
                else:
                    # Only the error's kind: its text may hold what the log holds.
                    self.report["late_notes_unread"] = type(error).__name__
        return [host for host, name in HOST_NAMES.items() if not found.get(host, set()).intersection(RANKED) and
                ("late" in found.get(host, ()) or name in noted)]

    def recall_again(self, host, exe):
        """One more session of one prompt in a host whose recalls gave up at their window (TC-254's evidence).

        A slow runner makes a recall give up (API-010), which TC-253 counts and does not fail on. Claude Code
        has one prompt here whose recall can rank, so that prompt's recall is asked once more, as the walk
        replays do; a host that still has no ranked recall fails TC-254.
        """
        configure(self.home, 10)
        self.memory.rearm()
        self.memory.release()
        result = self.session(host, exe, AGAIN, label="recall again (%s)" % host)
        sampler = result.pop("sampler")
        sampler.stop()
        self.lines.update(sampler.lines)
        result.pop("bodies")
        # Its worker ends before another session asks a recall, which reads the index that the worker keeps.
        result["rested"] = self.rested()
        result["hooks"] = self.timings(host, result)
        self.report.setdefault("recall_again", []).append(result)
        return result

    def traces(self):
        """TC-254: the markers reach the memory server and appear in no stored file and no command line."""
        found = {}
        stored, unread = marked_files(self.home, self.keys)
        for name, key in self.keys.items():
            lines = sum(count for text, count in self.lines.items() if key in text)
            sent = sum(1 for row in self.memory.requests if carries(row, key))
            found[name] = {"files_with_marker": stored[name], "command_lines_with_marker": lines,
                           "requests_with_key": sent}
        self.report["keys"] = found
        self.report["unread_files"] = unread
        self.report["command_lines"] = sum(self.lines.values())
        # The recall half of the case: each host's prompt hook ranked the items with the OpenAI key.
        recalls = {}
        for host, outcome in prompt_injections(self.home):
            recalls.setdefault(host, {}).setdefault(outcome, 0)
            recalls[host][outcome] += 1
        self.report["recalls"] = recalls
        return found


class Sampler(threading.Thread):
    """Reads the processes' command lines every SAMPLE_SECONDS while it runs.

    It keeps every line, for TC-254, a line read more than once once with its count (a Counter), and apart from
    them the memory workers' lines of `run_folder` (`workers`), this run's folder as `comparable` gives it;
    without it, every memory worker's.
    """

    def __init__(self, run_folder=None):
        super().__init__(daemon=True)
        self.lines, self.workers, self.errors, self.halt = Counter(), [], [], threading.Event()
        self.reads, self.run_folder = 0, run_folder

    def read(self):
        """One reading of the command lines; whether it worked."""
        try:
            found = command_lines()
        except (OSError, subprocess.SubprocessError) as error:
            self.errors.append(repr(error))
            return False
        self.reads += 1
        self.lines.update(found)
        for line in workers(found, self.run_folder):
            if line not in self.workers:
                self.workers.append(line)
        return True

    def run(self):
        while not self.halt.is_set():
            self.read()
            self.halt.wait(SAMPLE_SECONDS)

    def stop(self, last=False):
        """End the readings; with `last`, one more follows them in the caller's thread, tried until it works."""
        self.halt.set()
        self.join(timeout=150)
        if last:
            tried(self.read)


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

    def in_time(value):
        # SPEC-013#1: a hook that can start the worker returns within its own deadline, by its timing line.
        # The prompt hook starts none, and its time is TC-256's (REQ-034).
        return all(isinstance(value["hooks"].get(hook, {}).get("ms"), int) and
                   value["hooks"][hook]["ms"] <= limit for hook, limit in DEADLINE_MS.items())

    per = {}
    for value in sessions:
        per[value["label"]] = {
            "exit": value["exit"] == 0,
            "four hooks ok or late in recall": set(value["hooks"]) >= {"start", "prompt", "end-of-turn", "end"} and
            returned(value),
            "worker-starting hooks within their deadlines": in_time(value),
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
        v["exit"] and v["four hooks ok or late in recall"] and
        v["worker-starting hooks within their deadlines"] and v["trigger started the worker"] and
        v["worker held after the host ended"] and v["held results applied after release"] and
        v["run log lists the applied items"] for v in per.values())
    # TC-254 needs evidence that it looked: a ranked recall in each host, and command lines read in each
    # session while the memory worker ran.
    recalls = report.get("recalls", {})
    recalled = {host: sum(count for outcome, count in recalls.get(host, {}).items() if outcome in RANKED)
                for host in HOST_NAMES}
    tc254 = (bool(keys) and all(not v["files_with_marker"] and not v["command_lines_with_marker"] and
                                v["requests_with_key"] > 0 for v in keys.values()) and
             not report.get("unread_files") and all(recalled.values()) and
             report.get("command_lines", 0) > 0 and bool(per) and
             all(v["command lines read, with the worker"] for v in per.values()))
    tc255 = bool(per) and all(v["earlier decision shown"] and v["decision curated"] for v in per.values())
    scrub = report.get("scrub", {})
    # Either both keys reached the hooks, whose requests then carried them, or the start summary said that
    # they did not and nothing was sent. A host that passes one key and keeps the other fails the case, and
    # so does a count that did not begin and end at a moment without a worker. A worker that was left then
    # sent requests that are not the session's, or that were still to come; a reading of the command lines
    # that failed, or a report that has no such moments, does not show that none was left.
    reached = scrub.get("keys_reached_hooks") or {}
    kept = not any(reached.values())
    gone = scrub.get("workers_gone") or {}
    counted = bool(gone) and all(gone.values())
    tc257 = bool(scrub) and counted and scrub.get("exit") == 0 and bool(
        reached and all(reached.values()) or kept and scrub["notice"] and not scrub["memory_requests"])
    return {"sessions": per, "triggers": triggers, "hooks_ok": hooks_ok, "blocking_failures": blocking,
            "late recalls": len(late), "ranked recalls": recalled,
            "TC-253": tc253, "TC-254": tc254, "TC-255": tc255, "TC-257": tc257,
            "TC-257 observed": "not run" if not scrub
            else "the requests were not counted between two moments without a worker"
            if not counted else "keys kept from the hooks" if kept else "keys reached the hooks"
            if all(reached.values()) else "only one key reached the hooks"}


def summarize(text):
    """Adds `text` to the job's summary when the run is a step of GitHub Actions."""
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write("```\n%s\n```\n" % text)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    out = Path(sys.argv[1]).resolve() / "c2-hosts"
    left, unread = left_running(out)
    if left or unread:
        # The folder stays as it was, with no report: the worker that is left may still be writing into it. The
        # reason goes to the error output and, in CI, to the job's summary.
        said = "c2_hosts.py did not run: " + (
            "memory workers whose script lies in %s are still running (%d); run it again once they have ended, "
            "or give another OUTDIR" % (out, len(left)) if left else
            "the command lines could not be read (%s), so no memory worker left in %s by an earlier run could be "
            "ruled out" % (unread, out))
        print(said, file=sys.stderr)
        summarize(said)
        return 2
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
        for host in hosts.late_only():
            hosts.recall_again(host, exes[host])
        hosts.scrub(exes["claude"])
        hosts.traces()
        report["failures"] = [{key: row.get(key) for key in ("at", "hook", "step", "error", "host")}
                              for row in failure_rows(hosts.home)]
    except Exception:
        report["crash"] = traceback.format_exc()
    finally:
        if hosts is not None:
            hosts.memory.close()
            report["command_lines"] = sum(hosts.lines.values())
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
        if report.get("unread_files"):
            text.append("store files that could not be read, which fails TC-254: " +
                        json.dumps(report["unread_files"]))
        text.append("command lines read: %d; ranked recalls by host: %s" % (
            report.get("command_lines", 0), json.dumps(report["verdicts"]["ranked recalls"])))
        for value in report.get("recall_again", []):
            text.append("%s: its recalls had given up at their window, so one more prompt was asked; exit %s; "
                        "no worker left afterwards: %s" % (value["label"], value["exit"],
                                                           "yes" if value["rested"] else "NO"))
        if report.get("late_notes_unread"):
            text.append("the failure log could not be read as the hosts to ask once more were looked for (%s), so "
                        "the injection log alone decided" % report["late_notes_unread"])
        if report.get("start_worker_waits_given_up"):
            text.append(waits_line(report["start_worker_waits_given_up"]))
        text.append("TC-257: " + report["verdicts"]["TC-257 observed"] + "; " + json.dumps(
            {key: report["scrub"].get(key) for key in ("notice", "memory_requests", "recalled", "workers_gone")}))
        if report.get("workers_left"):
            text.append("waits for the workers that ran out, each with the lease at its last look, its seconds "
                        "without a lease and this run's memory workers' command lines as it ended, or why they "
                        "could not be read: " +
                        json.dumps(report["workers_left"], ensure_ascii=False))
        text.append("failure log: " + json.dumps(report.get("failures", [])))
        text.append("failures that fail TC-253: " + json.dumps(report["verdicts"]["blocking_failures"]))
        text.append("recalls that gave up at their window, counted and not failed: %d" %
                    report["verdicts"]["late recalls"])
        for case in cases:
            text.append("%s: %s" % (case, "pass" if report["verdicts"][case] else "FAIL"))
    print("\n".join(text))
    summarize("\n".join(text))
    return 0 if report["verdicts"] and all(report["verdicts"][case] for case in cases) else 1


if __name__ == "__main__":
    sys.exit(main())
