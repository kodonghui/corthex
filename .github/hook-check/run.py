"""Runs the corthex-memory session start hook on Windows in Claude Code and Codex.

Usage: python run.py LABEL OUTDIR [HOSTS]

Both hosts talk only to a mock model server on 127.0.0.1 that records each
request and answers 400, with fake keys, so no model is called. Each host gets
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
import signal
import shutil
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MEMORY = REPO / "plugins" / "corthex-memory"
DIAG = Path(__file__).resolve().parent / "diag.py"
GIT_BASH = Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Git" / "bin" / "bash.exe"
CONTEXT = "CORTHEX session context"
ASK = "MARK-ASK-7731"
KEEP = (
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "PATH", "TEMP", "TMP",
    "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS", "OS", "USERNAME", "USERDOMAIN", "COMPUTERNAME",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "PROGRAMDATA", "COMMONPROGRAMFILES",
    "COMMONPROGRAMFILES(X86)", "COMMONPROGRAMW6432", "PSMODULEPATH",
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
    """Model API stand-in: writes each request to the current log and answers 400."""

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
                payload = json.dumps({"type": "error", "error": {"type": "invalid_request_error",
                                                                   "message": "mock server"}}).encode()
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
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


def run(args, env, cwd=None, stdin="", timeout=180, line=None):
    """Runs a process with a timeout that also ends its children; line is a raw command line for cmd.exe."""
    start = time.time()
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
    return {"exit": code, "seconds": round(time.time() - start, 1),
            "stdout": out.decode("utf-8", "replace"), "stderr": err.decode("utf-8", "replace")}


def short(text, size=300):
    text = " ".join(text.split())
    return text if len(text) <= size else text[:size] + "..."


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


def claude(label, out, mock, folder, plugins):
    base = out / "claude"
    home, demo = prepare(base)
    env = base_env(home)
    env.update({"CLAUDE_CONFIG_DIR": str(base / "config"), "ANTHROPIC_API_KEY": "sk-ant-dummy-test",
                "ANTHROPIC_BASE_URL": "http://127.0.0.1:%d" % mock.port,
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1",
                "HOOKCHECK_LOG": str(base / "diag")})
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
    done = run([exe, "-p", "hello CLAUDE-" + label, "--output-format", "json",
                "--debug-file", str(base / "debug.txt")], env, demo, timeout=180)
    time.sleep(1)
    mock.log = None
    result["run"] = {"exit": done["exit"], "seconds": done["seconds"], "stdout": short(done["stdout"], 500),
                     "stderr": short(done["stderr"], 500)}
    result["requests"] = requests(base / "requests.jsonl")
    result["hooks"] = diag_records(base / "diag")
    debug = base / "debug.txt"
    result["debug"] = matching(debug.read_text(encoding="utf-8", errors="replace"), r"hook|bash|powershell|pwsh|shell", 120) if debug.exists() else []
    return result


def codex(label, out, mock, folder, plugins):
    base = out / "codex"
    home, demo = prepare(base)
    codex_home = base / "codex-home"
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / "config.toml").write_text(CODEX_CONFIG % mock.port, encoding="utf-8")
    env = base_env(home)
    env.update({"CODEX_HOME": str(codex_home), "MOCK_KEY": "x", "HOOKCHECK_LOG": str(base / "diag")})
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
    done = run([exe, "exec", "--json", "--skip-git-repo-check", "--ephemeral", "--dangerously-bypass-hook-trust",
                "hello CODEX-" + label], env, demo, timeout=180)
    time.sleep(1)
    mock.log = None
    result["run"] = {"exit": done["exit"], "seconds": done["seconds"]}
    result["requests"] = requests(base / "requests.jsonl")
    result["hooks"] = diag_records(base / "diag")
    result["output"] = matching(done["stdout"] + "\n" + done["stderr"], r"hook|error|warn|shell|powershell", 80)
    return result


def with_context(result):
    """The model requests of a host's run, and how many of them carry the memory context."""
    model = [q for q in result.get("requests", []) if re.search(r"/v1/(messages|responses)(\?|$)", q["path"])]
    return model, sum(1 for q in model if q["context"])


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
        for tag, records in sorted(r["hooks"].items()):
            for record in records:
                chain = " <- ".join(p["name"] or "?" for p in record["parents"])
                first = record["parents"][0]["cmdline"] if record["parents"] else ""
                lines.append("  hook %s (%s): %s | shell: %s | script %s" % (tag, record["source"], chain, short(first, 260), record["script"]))
    return "\n".join(lines)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    label = sys.argv[1]
    out = Path(sys.argv[2]).resolve() / label
    expected = [host for host in (sys.argv[3] if len(sys.argv) > 3 else "").split(",") if host]
    out.mkdir(parents=True, exist_ok=True)
    report = {"label": label}
    mock = Mock()
    plugins = market(out / "hk")
    sections = (("facts", facts), ("shells", lambda: shells(out)),
                ("claude", lambda: claude(label, out, mock, out / "hk", plugins)),
                ("codex", lambda: codex(label, out, mock, out / "hk", plugins)))
    for name, step in sections:
        try:
            report[name] = step()
        except Exception:
            report[name] = {"crash": traceback.format_exc()}
    missing = [host for host in expected if not with_context(report.get(host, {}))[1]]
    report["expected"] = {"hosts": expected, "missing": missing}
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    text = summary(report) + "\nmemory context expected from %s: %s" % (
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
