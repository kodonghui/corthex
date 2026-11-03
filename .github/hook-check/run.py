"""Runs session context and recording hooks in isolated Claude Code and Codex.

Usage: python run.py LABEL OUTDIR [HOSTS] [--evidence] [--benchmark100]

Both hosts talk only to a mock model server on 127.0.0.1 that records each
request and streams a fixed Korean answer, with fake keys, so no model is called. Each host gets
its own home folder, settings folder and demo project. Three test plugins show
how the host started each hook: a shell, its command line and its parents.
The script reports what reached the model. It exits 1 when a host named in
HOSTS, such as claude,codex, sent no request with the memory context, and 0
otherwise; any other failure is part of the report.
"""

import gzip
import json
import os
import platform
import re
import secrets
import signal
import shutil
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import native_evidence
import benchmark_hooks
import native_benchmark
from network_proxy import NetworkProxy

REPO = Path(__file__).resolve().parents[2]
MEMORY = REPO / "plugins" / "corthex-memory"
DIAG = Path(__file__).resolve().parent / "diag.py"
GIT_BASH = Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Git" / "bin" / "bash.exe"
CONTEXT = "CORTHEX session context"
ASK = "MARK-ASK-7731"
PROMPT = "한국어 질문을 기록해 주세요."
REPLY = "한국어 최종 답변을 기록합니다."
KEEP = (
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "PATH", "TEMP", "TMP",
    "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "OS", "USERNAME", "USERDOMAIN", "COMPUTERNAME",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "PROGRAMDATA", "COMMONPROGRAMFILES",
    "COMMONPROGRAMFILES(X86)", "COMMONPROGRAMW6432", "PSMODULEPATH", "TMPDIR", "LANG", "LC_ALL",
)
CODEX_CONFIG = """model_provider = "mock"

[model_providers.mock]
name = "mock"
base_url = "http://127.0.0.1:%d/v1"
env_key = "MOCK_KEY"
wire_api = "responses"
request_max_retries = 0
stream_max_retries = 0
"""


class Mock:
    """Local-only Messages/Responses stand-in; completes a turn without tools."""

    def __init__(self):
        self.log = None
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def handle_any(self):
                if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
                    body = b""
                    while True:
                        size = int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)
                        if not size:
                            self.rfile.readline()
                            break
                        body += self.rfile.read(size)
                        self.rfile.readline()
                else:
                    length = int(self.headers.get("Content-Length") or 0)
                    body = self.rfile.read(length) if length else b""
                encoding = self.headers.get("Content-Encoding") or ""
                if encoding == "gzip":
                    body = gzip.decompress(body)
                if mock.log:
                    with open(mock.log, "a", encoding="utf-8") as handle:
                        handle.write(json.dumps({"method": self.command, "path": self.path, "encoding": encoding,
                                                 "body": body.decode("utf-8", "replace")}) + "\n")
                request = json.loads(body) if body else {}
                if "/messages/count_tokens" in self.path:
                    payload, content_type = b'{"input_tokens":3}', "application/json"
                else:
                    payload = mock.stream(self.path, request.get("model", "mock"))
                    content_type = "text/event-stream"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = handle_any

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @staticmethod
    def stream(path, model):
        # Protocol shapes: developers.openai.com/api/reference/resources/responses/streaming-events
        # and platform.claude.com/docs/en/build-with-claude/streaming.
        if "/responses" in path:
            part = {"type": "output_text", "text": REPLY, "annotations": [], "logprobs": []}
            item = {"id": "msg_fixture", "type": "message", "role": "assistant", "status": "completed", "content": [part]}
            response = {"id": "resp_fixture", "object": "response", "created_at": int(time.time()),
                        "model": model, "status": "completed", "output": [item], "error": None,
                        "usage": {"input_tokens": 3, "output_tokens": 8, "total_tokens": 11}}
            events = [
                {"type": "response.created", "response": dict(response, status="in_progress", output=[])},
                {"type": "response.output_item.added", "output_index": 0, "item": dict(item, status="in_progress", content=[])},
                {"type": "response.content_part.added", "item_id": item["id"], "output_index": 0, "content_index": 0, "part": dict(part, text="")},
                {"type": "response.output_text.delta", "item_id": item["id"], "output_index": 0, "content_index": 0, "delta": REPLY},
                {"type": "response.output_text.done", "item_id": item["id"], "output_index": 0, "content_index": 0, "text": REPLY},
                {"type": "response.content_part.done", "item_id": item["id"], "output_index": 0, "content_index": 0, "part": part},
                {"type": "response.output_item.done", "output_index": 0, "item": item},
                {"type": "response.completed", "response": response},
            ]
            for number, event in enumerate(events):
                event["sequence_number"] = number
        else:
            events = [
                {"type": "message_start", "message": {"id": "msg_fixture", "type": "message", "role": "assistant",
                    "model": model, "content": [], "stop_reason": None, "stop_sequence": None,
                    "usage": {"input_tokens": 3, "output_tokens": 0}}},
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": REPLY}},
                {"type": "content_block_stop", "index": 0},
                {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 8}},
                {"type": "message_stop"},
            ]
        return "".join("event: " + event["type"] + "\ndata: " + json.dumps(event, ensure_ascii=False) + "\n\n" for event in events).encode("utf-8")


def run(args, env, cwd=None, stdin="", timeout=180, line=None):
    """Runs a process with a timeout that also ends its children; line is a raw command line for cmd.exe."""
    start = time.time()
    started_ns = native_evidence.clock_ns()
    try:
        process = subprocess.Popen(line or args, env=env, cwd=cwd, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=os.name != "nt")
    except OSError as error:
        return {"exit": None, "error": str(error), "stdout": "", "stderr": "", "seconds": 0}
    try:
        out, err = process.communicate(stdin.encode("utf-8"), timeout=timeout)
        code = process.returncode
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
        else:
            os.killpg(process.pid, signal.SIGKILL)
        out, err = process.communicate()
        code = "timeout"
    return {"exit": code, "seconds": round(time.time() - start, 1), "pid": process.pid,
            "started_monotonic_ns": started_ns, "ended_monotonic_ns": native_evidence.clock_ns(),
            "stdout": out.decode("utf-8", "replace"), "stderr": err.decode("utf-8", "replace")}


def short(text, size=300):
    text = " ".join(text.split())
    return text if len(text) <= size else text[:size] + "..."


def scrub_mock_key(value, key):
    if isinstance(value, str):
        return value.replace(key, "[mock-key]")
    if isinstance(value, list):
        return [scrub_mock_key(item, key) for item in value]
    if isinstance(value, dict):
        return {name: scrub_mock_key(item, key) for name, item in value.items()}
    return value


def base_env(home):
    env = {key: os.environ[key] for key in KEEP if key in os.environ}
    roaming, local = home / "AppData" / "Roaming", home / "AppData" / "Local"
    for folder in (roaming, local):
        folder.mkdir(parents=True, exist_ok=True)
    env.update({"HOME": str(home), "USERPROFILE": str(home), "HOMEDRIVE": home.drive, "HOMEPATH": str(home)[len(home.drive):],
                "APPDATA": str(roaming), "LOCALAPPDATA": str(local), "NO_PROXY": "127.0.0.1,localhost"})
    return env


def prepare(base):
    """A home folder with a profile and a demo project, as a user would have them."""
    home, demo = base / "home", base / "work" / "demo"
    (home / ".corthex").mkdir(parents=True, exist_ok=True)
    (demo / ".corthex").mkdir(parents=True, exist_ok=True)
    profile = {"address_as": "사용자님", "language": "ko", "ask_before": ["deploys", ASK]}
    (home / ".corthex" / "profile.json").write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    project = {"name": "demo", "stages": {"05-erd": {"human": "erd-editor", "source": "db/schema.sql", "truth": "human"}}}
    (demo / ".corthex" / "project.json").write_text(json.dumps(project), encoding="utf-8")
    (home / ".corthex/projects.json").write_text(json.dumps({"projects": [{"name": "demo", "path": str(demo)}]}), encoding="utf-8")
    scripts = MEMORY / "skills/corthex-memory/scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    command = [sys.executable, "-B", str(scripts / "memory.py"), "on", "--folder", str(demo)]
    environment = base_env(home)
    preview = run(command, environment, demo)
    assert preview["exit"] == 0, preview
    proposed = json.loads(preview["stdout"])
    assert preview["exit"] == 0 and proposed["outcome"] == "confirm"
    applied = run(command + ["--confirm", proposed["confirm"]], environment, demo)
    final = json.loads(applied["stdout"])
    assert applied["exit"] == 0 and final["outcome"] == "done"
    (base / "bootstrap.json").write_text(json.dumps({"preview": proposed, "result": final,
        "synthetic_fixture_response": "yes", "real_user_consent": False}, ensure_ascii=False), encoding="utf-8")
    return home, demo


def market(folder):
    """Test marketplace hk with three plugins whose hooks record how they were started."""
    plugins = {
        "hk-diag": [
            {"type": "command", "command": 'python -I "{abs}/diag.py" abs'},
            {"type": "command", "command": 'python -I "${CLAUDE_PLUGIN_ROOT}/diag.py" placeholder'},
        ],
        "hk-win": [
            {"type": "command", "command": 'python -I "%CLAUDE_PLUGIN_ROOT%/diag.py" percent'},
            {"type": "command", "command": 'python -I "$env:CLAUDE_PLUGIN_ROOT/diag.py" psenv'},
            {"type": "command", "command": "python", "args": ["-I", "${CLAUDE_PLUGIN_ROOT}/diag.py", "exec"]},
            {"type": "command", "command": 'py -3 -I "{abs}/diag.py" py'},
        ],
        "hk-win-cw": [
            {"type": "command", "command": 'python -I "{abs}/diag.py" command',
             "commandWindows": 'python -I "{abs}/diag.py" commandWindows'},
        ],
    }
    if os.name != "nt":
        plugins = {"hk-diag": plugins["hk-diag"]}
    claude, codex = [], []
    for name, hooks in plugins.items():
        root = folder / "plugins" / name
        absolute = root.as_posix()
        for manifest in (".claude-plugin", ".codex-plugin"):
            (root / manifest).mkdir(parents=True, exist_ok=True)
            (root / manifest / "plugin.json").write_text(json.dumps(
                {"name": name, "version": "0.0.1", "description": "Windows hook check"}), encoding="utf-8")
        (root / "hooks").mkdir(exist_ok=True)
        filled = []
        for hook in hooks:
            hook = dict(hook, timeout=60)
            for key in ("command", "commandWindows"):
                if key in hook:
                    hook[key] = hook[key].replace("{abs}", absolute)
            filled.append(hook)
        (root / "hooks" / "hooks.json").write_text(json.dumps(
            {"hooks": {"SessionStart": [{"hooks": filled}]}}, indent=2), encoding="utf-8")
        shutil.copy(DIAG, root / "diag.py")
        claude.append({"name": name, "source": "./plugins/" + name, "description": "Windows hook check"})
        codex.append({"name": name, "source": {"source": "local", "path": "./plugins/" + name},
                      "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                      "category": "Productivity"})
    (folder / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (folder / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
        {"name": "hk", "owner": {"name": "test"}, "plugins": claude}, indent=2), encoding="utf-8")
    (folder / ".agents" / "plugins").mkdir(parents=True, exist_ok=True)
    (folder / ".agents" / "plugins" / "marketplace.json").write_text(json.dumps(
        {"name": "hk", "interface": {"displayName": "Hook check"}, "plugins": codex}, indent=2), encoding="utf-8")
    return list(plugins)


def facts():
    env = dict(os.environ)
    names = ("python3", "python", "py", "bash", "sh", "pwsh", "powershell", "cmd", "git", "node", "claude", "codex")
    found = {name: shutil.which(name, path=env.get("PATH")) for name in names}
    result = {"platform": platform.platform(), "python": sys.version.split()[0], "found": found,
              "git_bash": str(GIT_BASH) if GIT_BASH.exists() else None}
    system = os.environ.get("SystemRoot")
    result["wsl_launcher"] = str(Path(system)/"System32/bash.exe") if os.name == "nt" and system else None
    folders = (Path(folder.strip('"')) for folder in env.get("PATH", "").split(os.pathsep))
    result["bash_candidates"] = [str(folder/name) for folder in folders if folder.is_absolute() for name in ("bash.exe", "sh.exe") if (folder/name).is_file()] if os.name == "nt" else []
    for name in ("pwsh", "powershell"):
        if found[name]:
            result[name + "_version"] = run([found[name], "-NoProfile", "-NonInteractive", "-Command",
                                             "$PSVersionTable.PSVersion.ToString()"], env, timeout=60)["stdout"].strip()
    apps = Path(env.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps"
    result["windows_apps_python"] = sorted(p.name for p in apps.glob("python*")) if apps.is_dir() else None
    return result


def shells(out):
    """The corthex-memory hook commands run directly in each shell: `command` as written and with the
    path filled in, and `commandWindows` in PowerShell."""
    home, demo = prepare(out / "shells")
    env = base_env(home)
    env["CLAUDE_PLUGIN_ROOT"] = str(MEMORY)
    hooks = json.loads((MEMORY / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    hook = hooks["hooks"]["SessionStart"][0]["hooks"][0]
    command = hook["command"]
    forms = {"as written": command, "path filled in": command.replace("${CLAUDE_PLUGIN_ROOT}", str(MEMORY))}
    if "commandWindows" in hook:
        forms["commandWindows"] = hook["commandWindows"]
    event = json.dumps({"session_id": "check", "cwd": str(demo), "hook_event_name": "SessionStart", "source": "startup"})
    found = {"git-bash": str(GIT_BASH) if GIT_BASH.exists() else None,
             "pwsh": shutil.which("pwsh", path=env["PATH"]),
             "powershell": shutil.which("powershell", path=env["PATH"]),
             "cmd": shutil.which("cmd", path=env["PATH"])}
    results = {"command": command}
    for shell, exe in found.items():
        for form, text in forms.items():
            if form == "commandWindows" and shell not in ("pwsh", "powershell"):
                continue
            key = "%s, %s" % (shell, form)
            if not exe:
                results[key] = "shell missing"
                continue
            if shell == "git-bash":
                done = run([exe, "-c", text], env, demo, event, 60)
            elif shell == "cmd":
                done = run(None, env, demo, event, 60, line='"%s" /d /s /c "%s"' % (exe, text))
            else:
                done = run([exe, "-NoProfile", "-NonInteractive", "-Command", text], env, demo, event, 60)
            results[key] = {"exit": done["exit"], "context": CONTEXT in done["stdout"], "stderr": short(done["stderr"])}
    return results


def requests(path):
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            body = row["body"]
            rows.append({"path": row["path"], "bytes": len(body), "encoding": row["encoding"],
                         "context": body.count(CONTEXT), "ask": body.count(ASK),
                         "diag": sorted(set(re.findall(r"HOOKDIAG-([A-Za-z]+)", body)))})
    return rows


def diag_records(folder):
    records = {}
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        record = json.loads(path.read_text(encoding="utf-8"))
        chain = [{"name": p.get("name"), "cmdline": short(p.get("cmdline", ""), 400)} for p in record["parents"]]
        records.setdefault(record["tag"], []).append({"script": record["script"], "source": record["source"],
                                                      "env": record["env"], "parents": chain})
    return records


def matching(text, pattern, limit):
    lines = [short(line, 400) for line in text.splitlines() if re.search(pattern, line, re.I)]
    return lines[:limit]


def install_steps(exe, env, cwd, steps):
    results = {}
    for name, args in steps:
        done = run([exe] + args, env, cwd, timeout=180)
        results[name] = {"exit": done["exit"], "output": short(done["stdout"] + " " + done["stderr"], 400)}
    return results


def capture_benchmark(plugin, host, base, pins, model):
    # Measure the original package, rather than the native observation's barrier worker.
    worker = native_evidence.digest(plugin / "scripts/worker.py")
    assert worker == pins["worker"]
    assert native_evidence.digest(plugin / "scripts/hook.py") == native_evidence.digest(MEMORY / "scripts/hook.py")
    value = native_benchmark.measure(plugin.parents[1], host, base / "benchmark-native", model, samples=100)
    value["worker_sha256"] = worker
    value["goal_status"] = "pass" if value["meets_100_ms_target"] else "fail"
    return value


def native_session(host, done):
    field = "session_id" if host == "claude" else "thread_id"
    events = [json.loads(line) for line in done["stdout"].splitlines() if line.lstrip().startswith("{")]
    ids = {value[field] for value in events if value.get(field)}
    assert len(ids) == 1 and all(isinstance(value, str) for value in ids), "native CLI session identity missing"
    return ids.pop()


def claude(label, out, mock, folder, plugins, pins=None, benchmark_plugin=None):
    base = out / "claude"
    home, demo = prepare(base)
    env = base_env(home)
    env.update({"CLAUDE_CONFIG_DIR": str(base / "config"), "ANTHROPIC_API_KEY": "sk-ant-" + secrets.token_hex(12),
                "ANTHROPIC_BASE_URL": "http://127.0.0.1:%d" % mock.port,
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1",
                "HOOKCHECK_LOG": str(base / "diag")})
    if pins:
        settings, old = native_evidence.configure_lifetime(base, home, pins)
        env.update(settings, HOOKCHECK_MEASURE_DIR=str(base / "measurements"), HOOKCHECK_CAPTURE_INPUT_DIR=str(base / "inputs"))
    exe = shutil.which("claude", path=env["PATH"])
    if not exe:
        return {"error": "claude not found"}
    result = {"version": short(run([exe, "--version"], env, demo, timeout=60)["stdout"], 80)}
    steps = [("marketplace corthex", ["plugin", "marketplace", "add", str(REPO)]),
             ("marketplace hk", ["plugin", "marketplace", "add", str(folder)]),
             ("install corthex-memory", ["plugin", "install", "corthex-memory@corthex"])]
    steps += [("install " + name, ["plugin", "install", name + "@hk"]) for name in plugins]
    result["install"] = install_steps(exe, env, demo, steps)
    mock.log = base / "requests.jsonl"
    network = NetworkProxy() if pins else None
    memory_network = NetworkProxy() if pins else None
    if network:
        env.update(network.environment(), HOOKCHECK_MEMORY_PROXY=memory_network.url)
    done = run([exe, "-p", PROMPT, "--output-format", "json",
                "--debug-file", str(base / "debug.txt")], env, demo, timeout=180)
    done = scrub_mock_key(done, env["ANTHROPIC_API_KEY"])
    session = native_session("claude", done)
    captured = wait_for_capture(home, host="claude-code", session=session)
    if pins:
        result["outer_clock"] = native_evidence.external_clocks(base)
        result["input_identity"] = native_evidence.input_identity(base, session)
        result["input_contract"] = native_evidence.input_contract(base, "claude", result["version"], session)
        done["hooks_ended_monotonic_ns"] = max((row["ended_monotonic_ns"] for row in result["outer_clock"]["rows"]), default=0)
        result["lifetime"] = native_evidence.release_lifetime(base, env, done, old)
        memory_observed, host_observed = memory_network.finish(), network.finish()
        result["network"] = {"verified": memory_observed["verified"] and host_observed["positive_control"],
                             "memory": memory_observed, "host": host_observed,
                             "attribution": "dedicated child proxy for product hooks and inherited workers; host proxy kept separate"}
        result["reinstall"] = native_evidence.reinstall(exe, "claude", env, demo, home, run)
        captured = capture(home, host="claude-code", session=session)
    if benchmark_plugin is not None:
        result["benchmark"] = capture_benchmark(benchmark_plugin, "claude", base, pins, mock)
    mock.log = None
    result["run"] = {"exit": done["exit"], "seconds": done["seconds"], "pid": done.get("pid"),
                     "started_monotonic_ns": done.get("started_monotonic_ns"), "ended_monotonic_ns": done.get("ended_monotonic_ns"), "stdout": short(done["stdout"], 500),
                     "stderr": short(done["stderr"], 500)}
    result["requests"] = requests(base / "requests.jsonl")
    result["capture"] = captured
    result["hooks"] = diag_records(base / "diag")
    debug = base / "debug.txt"
    result["debug"] = matching(debug.read_text(encoding="utf-8", errors="replace").replace(env["ANTHROPIC_API_KEY"], "[mock-key]"), r"hook|bash|powershell|pwsh|shell", 120) if debug.exists() else []
    return scrub_mock_key(result, env["ANTHROPIC_API_KEY"])


def codex(label, out, mock, folder, plugins, pins=None, benchmark_plugin=None):
    base = out / "codex"
    home, demo = prepare(base)
    codex_home = base / "codex-home"
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / "config.toml").write_text(CODEX_CONFIG % mock.port, encoding="utf-8")
    env = base_env(home)
    env.update({"CODEX_HOME": str(codex_home), "MOCK_KEY": "fixture-" + secrets.token_hex(12), "HOOKCHECK_LOG": str(base / "diag")})
    if pins:
        settings, old = native_evidence.configure_lifetime(base, home, pins)
        env.update(settings, HOOKCHECK_MEASURE_DIR=str(base / "measurements"), HOOKCHECK_CAPTURE_INPUT_DIR=str(base / "inputs"))
    exe = shutil.which("codex", path=env["PATH"])
    if not exe:
        return {"error": "codex not found"}
    result = {"version": short(run([exe, "--version"], env, demo, timeout=60)["stdout"], 80)}
    steps = [("marketplace corthex", ["plugin", "marketplace", "add", str(REPO)]),
             ("marketplace hk", ["plugin", "marketplace", "add", str(folder)]),
             ("add corthex", ["plugin", "add", "corthex@corthex"]),
             ("add corthex-memory", ["plugin", "add", "corthex-memory@corthex"])]
    steps += [("add " + name, ["plugin", "add", name + "@hk"]) for name in plugins]
    result["install"] = install_steps(exe, env, demo, steps)
    mock.log = base / "requests.jsonl"
    network = NetworkProxy() if pins else None
    memory_network = NetworkProxy() if pins else None
    if network:
        env.update(network.environment(), HOOKCHECK_MEMORY_PROXY=memory_network.url)
    done = run([exe, "exec", "--json", "--skip-git-repo-check", "--ephemeral", "--dangerously-bypass-hook-trust",
                PROMPT], env, demo, timeout=180)
    done = scrub_mock_key(done, env["MOCK_KEY"])
    session = native_session("codex", done)
    captured = wait_for_capture(home, host="codex", session=session)
    if pins:
        result["outer_clock"] = native_evidence.external_clocks(base)
        result["input_identity"] = native_evidence.input_identity(base, session)
        result["input_contract"] = native_evidence.input_contract(base, "codex", result["version"], session)
        done["hooks_ended_monotonic_ns"] = max((row["ended_monotonic_ns"] for row in result["outer_clock"]["rows"]), default=0)
        result["lifetime"] = native_evidence.release_lifetime(base, env, done, old)
        memory_observed, host_observed = memory_network.finish(), network.finish()
        result["network"] = {"verified": memory_observed["verified"] and host_observed["positive_control"],
                             "memory": memory_observed, "host": host_observed,
                             "attribution": "dedicated child proxy for product hooks and inherited workers; host proxy kept separate"}
        result["reinstall"] = native_evidence.reinstall(exe, "codex", env, demo, home, run)
        captured = capture(home, host="codex", session=session)
    if benchmark_plugin is not None:
        result["benchmark"] = capture_benchmark(benchmark_plugin, "codex", base, pins, mock)
    mock.log = None
    result["run"] = {"exit": done["exit"], "seconds": done["seconds"], "pid": done.get("pid"),
                     "started_monotonic_ns": done.get("started_monotonic_ns"), "ended_monotonic_ns": done.get("ended_monotonic_ns")}
    result["requests"] = requests(base / "requests.jsonl")
    result["capture"] = captured
    result["hooks"] = diag_records(base / "diag")
    result["output"] = matching(done["stdout"] + "\n" + done["stderr"], r"hook|error|warn|shell|powershell", 80)
    return scrub_mock_key(result, env["MOCK_KEY"])


def with_context(result):
    """The model requests of a host's run, and how many of them carry the memory context."""
    model = [q for q in result.get("requests", []) if re.search(r"/v1/(messages|responses)(\?|$)", q["path"])]
    return model, sum(1 for q in model if q["context"])


def capture(home, host=None, session=None):
    """Retain only counts and comparisons of the generated conversation."""
    memory = home / ".corthex/corthex-memory"
    rows = [json.loads(line) for path in memory.glob("projects/*/raw/*.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()]
    scoped = [row for row in rows if (host is None or row.get("host") == host) and (session is None or row.get("session") == session)]
    prompts = [row for row in scoped if row.get("kind") == "prompt" and row.get("text") == PROMPT]
    answers = [row for row in scoped if row.get("kind") == "answer" and row.get("text", "").strip() == REPLY]
    starts = [row for row in scoped if row.get("kind") == "start" and "text" not in row]
    endings = [row for row in scoped if row.get("kind") == "end" and "text" not in row]
    paired = {(p["host"], p["session"]) for p in prompts for a in answers
              if p["host"] == a["host"] and p["session"] == a["session"] and p["turn"] == a["turn"]}
    boundary_matches = lambda records: any((row.get("host"), row.get("session")) in paired for row in records)
    timings = [json.loads(line) for path in memory.glob("logs/hooks-*.jsonl")
               for line in path.read_text(encoding="utf-8").splitlines()]
    timings = [row for row in timings if host is None or row.get("host") == host]
    timing_ok = all(any(row.get("hook") == hook and row.get("outcome") == "ok" for row in timings)
                    for hook in ("start", "prompt", "end-of-turn", "end"))
    failures = [json.loads(line) for path in memory.glob("logs/failures-*.jsonl")
                for line in path.read_text(encoding="utf-8").splitlines()]
    outcomes = {hook: [row["outcome"] for row in timings if row.get("hook") == hook]
                for hook in ("start", "prompt", "end-of-turn", "end")}
    return {"entries": len(rows), "prompt_ok": bool(prompts), "answer_ok": bool(answers),
            "start_ok": "ok" in outcomes["start"] and boundary_matches(starts),
            "end_ok": boundary_matches(endings), "same_turn": bool(paired),
            "korean_intact": bool(prompts) and bool(answers), "timings_ok": timing_ok,
            "failures_ok": not failures,
            "boundary_ok": all(row.get("kind") in ("start", "prompt", "answer", "end") and
                               (row.get("kind") not in ("start", "end") or "text" not in row) for row in rows),
            "hook_outcomes": outcomes, "failure_errors": sorted({row["error"] for row in failures})}


def wait_for_capture(home,timeout=6,host=None,session=None):
    """Observe an already launched hook through its final timing line.

    A host can return while its SessionEnd command is still starting. Once all
    timings exist, retain their verdict even on failure; never rerun a hook.
    """
    started = time.perf_counter()
    value = capture(home, host=host, session=session)
    while not all(value["hook_outcomes"].values()) and time.perf_counter()-started < timeout:
        time.sleep(0.05)
        value = capture(home, host=host, session=session)
    value["capture_wait_ms"] = round((time.perf_counter()-started)*1000,3)
    return value


def summary(report):
    lines = ["== %s ==" % report["label"]]
    f = report.get("facts", {})
    if "found" in f:
        lines.append("%s | Python %s | Git Bash: %s | pwsh %s | powershell %s | WindowsApps python: %s" % (
            f["platform"], f["python"], "yes" if f["git_bash"] else "no", f.get("pwsh_version", "-"),
            f.get("powershell_version", "-"), f["windows_apps_python"]))
        lines.append("on PATH: " + ", ".join("%s=%s" % (k, v or "-") for k, v in f["found"].items()))
    for key, value in report.get("shells", {}).items():
        if key == "command":
            continue
        if isinstance(value, dict):
            value = "exit %s, context %s%s" % (value["exit"], "yes" if value["context"] else "no",
                                               ", stderr: " + value["stderr"] if value["stderr"] else "")
        lines.append("shell %s: %s" % (key, value))
    for host in ("claude", "codex"):
        r = report.get(host, {})
        if "run" not in r:
            lines.append("%s: %s" % (host, short(json.dumps(r), 600)))
            continue
        bad = {k: v for k, v in r["install"].items() if v["exit"] != 0}
        lines.append("%s %s: installs %s; run exit %s in %ss" % (host, r["version"], "ok" if not bad else bad, r["run"]["exit"], r["run"]["seconds"]))
        model, context = with_context(r)
        lines.append("  model requests %d, with memory context %d, with profile marker %d, hook markers %s" % (
            len(model), context, sum(1 for q in model if q["ask"]),
            sorted({t for q in model for t in q["diag"]})))
        lines.append("  recording: " + json.dumps(r.get("capture", {}), sort_keys=True))
        if "outer_clock" in r:
            for timing in r["outer_clock"]["rows"]:
                lines.append("  %s whole child process: %.3f ms, exit %s (interpreter startup included; wrapper/host startup excluded)" % (
                    timing["hook"], timing["milliseconds"], timing["exit"]))
            lines.append("  controlled native-worker lifetime: %s; uninstall/reinstall preserves store: %s; outer samples alone make no p95 claim" % (
                r.get("lifetime", {}).get("verified"), r.get("reinstall", {}).get("verified")))
        if "benchmark" in r:
            bench = r["benchmark"]
            for row in bench["rows"]:
                lines.append("  %s: n=%d, entries=1000, median %.3f ms, p95 %.3f ms, target<100ms=%s" % (
                    row["hook"],row["samples"],row["median_ms"],row["p95_ms"],row["under_100_ms"]))
            lines.append("  REQ-011 Should target: " + bench["goal_status"] + "; measurement validity is separate from the product goal")
            if not bench["meets_100_ms_target"]:
                print("::warning title=REQ-011 performance goal::Capture hook p95 exceeds 100 ms; retain the failed QA goal for its issue and trial go/no-go.")
        for tag, records in sorted(r["hooks"].items()):
            for record in records:
                chain = " <- ".join(p["name"] or "?" for p in record["parents"])
                first = record["parents"][0]["cmdline"] if record["parents"] else ""
                lines.append("  hook %s (%s): %s | shell: %s | script %s" % (tag, record["source"], chain, short(first, 260), record["script"]))
    return "\n".join(lines)


def shell_variant_ok(label, info):
    found = info.get("found", {})
    if label in ("git-bash","no-git-bash","powershell-5.1-only") and (not isinstance(found,dict) or not found or "crash" in info):
        return False
    bashes, launcher = [found.get("bash")] + info.get("bash_candidates", []), info.get("wsl_launcher")
    no_bash = not info.get("git_bash") and all(not bash or bool(launcher) and Path(bash).as_posix().casefold() == Path(launcher).as_posix().casefold() for bash in bashes)
    if label == "no-git-bash":
        return no_bash
    if label == "powershell-5.1-only":
        return no_bash and not found.get("pwsh") and bool(found.get("powershell")) and info.get("powershell_version", "").startswith("5.1.")
    return label != "git-bash" or bool(info.get("git_bash"))


def main():
    global REPO, MEMORY
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    label = sys.argv[1]
    out = Path(sys.argv[2]).resolve() / label
    expected = [host for host in (sys.argv[3] if len(sys.argv) > 3 else "").split(",") if host]
    out.mkdir(parents=True, exist_ok=True)
    report = {"label": label}
    flags = set(sys.argv[4:])
    if flags - {"--evidence", "--benchmark100"} or "--benchmark100" in flags and "--evidence" not in flags:
        raise ValueError("--benchmark100 requires --evidence; unknown fixture option")
    evidence = "--evidence" in flags
    benchmark_plugin = MEMORY if "--benchmark100" in flags else None
    pins = None
    if evidence:
        REPO, pins = native_evidence.package_copy(REPO, out)
        MEMORY = REPO / "plugins/corthex-memory"
        report["instrumentation"] = pins
    mock = Mock()
    plugins = market(out / "hk")
    if evidence:
        plugins = []
    sections = (("facts", facts), ("shells", lambda: {} if evidence else shells(out)),
                ("claude", lambda: claude(label, out, mock, out / "hk", plugins, pins, benchmark_plugin)),
                ("codex", lambda: codex(label, out, mock, out / "hk", plugins, pins, benchmark_plugin)))
    for name, step in sections:
        try:
            report[name] = step()
        except Exception:
            report[name] = {"crash": traceback.format_exc()}
    missing = [host for host in expected if report.get(host, {}).get("run", {}).get("exit") != 0 or
               not report.get(host, {}).get("install") or
               any(row.get("exit") != 0 for row in report.get(host, {}).get("install", {}).values()) or
               not with_context(report.get(host, {}))[1] or
               not all(report.get(host, {}).get("capture", {}).get(key)
                       for key in ("start_ok", "prompt_ok", "answer_ok", "end_ok", "same_turn", "korean_intact",
                                   "timings_ok", "failures_ok", "boundary_ok"))]
    report["shell_variant_ok"] = shell_variant_ok(label, report.get("facts", {}))
    if not report["shell_variant_ok"]:
        missing = sorted(set(missing) | set(expected))
    if evidence:
        missing = sorted(set(missing) | {host for host in expected if not all(
            report.get(host, {}).get(name, {}).get("verified") for name in ("lifetime", "network", "reinstall", "outer_clock", "input_identity", "input_contract"))})
    if benchmark_plugin is not None:
        missing = sorted(set(missing) | {host for host in expected if not all(
            report.get(host, {}).get("benchmark", {}).get(key) for key in ("verified", "measurement_valid"))})
    report["expected"] = {"hosts": expected, "missing": missing}
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    text = summary(report) + "\nrequired context, hooks and native evidence from %s: %s" % (
        ", ".join(expected) or "no host", "missing from " + ", ".join(missing) if missing else "ok")
    print(text)
    print("== %s: full report ==" % label)
    print(json.dumps(report, indent=1, ensure_ascii=False))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write("```\n%s\n```\n" % text)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
