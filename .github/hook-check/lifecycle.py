"""Five actual native session sources; synthetic consent and loopback models."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid

import run as runner
from native_terminal import Terminal
from network_proxy import NetworkProxy
from lifecycle_prompt import wait_quiet_store, write_start


def raw(home):
    return {p.relative_to(home).as_posix():p.read_bytes().splitlines()
            for p in (home / ".corthex/corthex-memory").glob("projects/*/raw/*.jsonl")}


def delta(home, before):
    return [json.loads(line) for name, lines in raw(home).items() for line in lines[len(before.get(name, [])):]]


def qualify(rows, source):
    expected = "start" if source == "startup" else source
    starts = [v for v in rows if v["kind"] == "start" and v.get("event") == expected]
    assert len(starts) == 1, "The requested native start source must occur once"
    session = starts[0]["session"]
    scoped = [v for v in rows if v["session"] == session]
    assert [v["kind"] for v in scoped] == ["start", "prompt", "answer", "end"]
    assert all("text" not in scoped[i] for i in (0, 3))
    assert scoped[1]["text"] == runner.PROMPT and scoped[2]["text"] == runner.REPLY
    assert scoped[1]["turn"] == scoped[2]["turn"]
    return {"verified":True,"source":source,"session":session,"entries":scoped,
            "other_session_entries":len(rows) - len(scoped)}


def wait_capture(home, before, source, timeout=6):
    started = time.monotonic()
    while True:
        try:
            result = qualify(delta(home, before), source)
            result["capture_wait_ms"] = round((time.monotonic() - started) * 1000, 3)
            return result
        except (AssertionError, PermissionError, FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
            # A replacement/shared handle or a partial append is not a complete
            # snapshot. Retry the whole read within the original capture budget;
            # persistent read errors and invalid captures still fail at expiry.
            if time.monotonic() - started >= timeout:
                raise
            time.sleep(.025)


def paced_package(repository, output):
    """Declare the lifecycle-only wrapper; keep every product child unchanged."""
    target = output / "source"
    target.mkdir()
    for name in (".claude-plugin", ".agents/plugins", "plugins"):
        shutil.copytree(repository / name, target / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    original, copied = repository / "plugins/corthex-memory", target / "plugins/corthex-memory"
    hashes = {p.relative_to(original).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
              for p in original.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    assert all(hashlib.sha256((copied / name).read_bytes()).hexdigest() == value for name,value in hashes.items())
    hooks = copied / "hooks/hooks.json"
    value = json.loads(hooks.read_bytes())
    for event in ("SessionStart", "UserPromptSubmit"):
        for group in value["hooks"][event]:
            for hook in group["hooks"]:
                for key in ("command", "commandWindows"):
                    hook[key] = hook[key].replace("/scripts/hook.py", "/scripts/lifecycle_prompt.py")
    hooks.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    helper = copied / "scripts/lifecycle_prompt.py"
    shutil.copyfile(Path(__file__).with_name("lifecycle_prompt.py"), helper)
    report = {"candidate_sha256s":hashes, "instrumented_hooks_sha256":hashlib.sha256(hooks.read_bytes()).hexdigest(),
              "prompt_wrapper_sha256":hashlib.sha256(helper.read_bytes()).hexdigest(),
              "original_children_unchanged":all(hashlib.sha256((copied / name).read_bytes()).hexdigest() == digest
                                               for name,digest in hashes.items() if name != "hooks/hooks.json")}
    (output / "lifecycle-instrumentation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    assert report["original_children_unchanged"]
    return target


def retain_store_evidence(home, output):
    """Expose only the disposable memory store, including on failed runs.

    upload-artifact omits hidden folders. Preserve these redacted raw entries and
    safe diagnostic logs under a visible folder, never the host's account files.
    """
    root = home / ".corthex/corthex-memory"
    for pattern in ("projects/*/raw/*.jsonl", "logs/*.jsonl"):
        for path in root.glob(pattern):
            target = output / "store-evidence" / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())


def pacing_evidence(base):
    rows = [json.loads(p.read_bytes()) for p in (base / "prompt-gates").glob("*.json")
            if not p.name.startswith("start-") and p.name != "generation.json"]
    prompts = [v for v in rows if v["hook"] == "prompt"]
    assert prompts and all(v.get("exit") == 0 and v.get("original_child_started") is True
                           and v["start_completion"].get("completed") is True
                           and v["start_completion"].get("exit") == 0
                           and v["generation"] == v["start_completion"].get("generation")
                           and v["generation"]["source"] == v["start_completion"].get("event_source")
                           and v["start_completion"]["child_ended_ns"] <= v["child_started_ns"]
                           for v in prompts), "Every native prompt must follow an observed completed start"
    return {"verified":True, "prompt_children":len(prompts), "worker_completion_claimed":False,
            "whole_hook_timings_claimed":False}


def arm_start(env, source):
    output = Path(env["HOOKCHECK_LIFECYCLE_GATES"])
    output.mkdir(parents=True, exist_ok=True)
    value = {"id":uuid.uuid4().hex, "source":source, "armed_ns":time.monotonic_ns()}
    write_start(output / "generation.json", value)
    archive = output / "generations"; archive.mkdir(exist_ok=True)
    write_start(archive / (value["id"] + ".json"), value)


def recording(command, env, project):
    args = [sys.executable, "-B", str(runner.MEMORY / "skills/corthex-memory/scripts/memory.py"), command, "--folder", str(project)]
    done = runner.run(args, env, project); assert done["exit"] == 0
    value = json.loads(done["stdout"])
    if value["outcome"] == "confirm":
        done = runner.run(args + ["--confirm", value["confirm"]], env, project); assert done["exit"] == 0
        value = json.loads(done["stdout"])
    assert value["outcome"] == "done"


class Stream:
    def __init__(self, command, env, project):
        if "HOOKCHECK_LIFECYCLE_GATES" in env:
            arm_start(env, "startup")
        self.process = subprocess.Popen(command, env=env, cwd=project, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, start_new_session=os.name != "nt")
        self.rows, self.pending, self.errors = [], queue.Queue(), []
        def read():
            for line in self.process.stdout:
                row = json.loads(line); self.rows.append(row); self.pending.put(row)
        threading.Thread(target=read, daemon=True).start()
        threading.Thread(target=lambda:self.errors.append(self.process.stderr.read().decode("utf-8", "replace")), daemon=True).start()

    def send(self, text):
        data = {"type":"user", "message":{"role":"user", "content":text}}
        self.process.stdin.write((json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")); self.process.stdin.flush()
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            row = self.pending.get(timeout=max(.1, deadline - time.monotonic()))
            if row.get("type") == "result":
                assert not row.get("is_error"), "The native command must succeed"
                return row
        raise AssertionError("No native stream result")

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            runner.end_tree(self.process)
            self.process.wait()
        return {"exit":self.process.returncode,"events":self.rows,"stderr":self.errors}


def claude_command(source, exe, env, project, home, output):
    recording("off", env, project)
    stream = Stream([exe, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose"], env, project)
    try:
        stream.send(runner.PROMPT)  # Seed actual host history while recording is off.
        before = raw(home)
        recording("on", env, project)
        arm_start(env, source)
        result = stream.send("/" + source)
        assert result.get("local_command") == source
        stream.send(runner.PROMPT)
    finally:
        done = stream.close()
        (output / ("claude-" + source + ".json")).write_text(json.dumps(done, ensure_ascii=False) + "\n", encoding="utf-8")
    assert done["exit"] == 0
    return wait_capture(home, before, source)


def codex_terminal(source, exe, env, project, home, output, seed):
    if source in ("clear", "compact"):
        recording("off", env, project)
    command = [exe, "--no-daemon", "--no-alt-screen", "--dangerously-bypass-hook-trust", "--dangerously-bypass-approvals-and-sandbox"]
    if source == "fork":
        command += ["fork", seed]
    arm_start(env, "fork" if source == "fork" else "startup")
    terminal = Terminal(command, env, project, output / ("codex-" + source + "-terminal.bin"))
    def turn():
        offset = len(terminal.data); terminal.line(runner.PROMPT)
        terminal.wait(lambda:b"7501;state=done" in terminal.data[offset:])
    try:
        terminal.wait(lambda:b"7501;state=idle" in terminal.data)
        if source in ("clear", "compact"):
            turn()
            recording("on", env, project)
        before = raw(home)
        if source in ("clear", "compact"):
            offset = len(terminal.data)
            arm_start(env, source)
            terminal.line("/" + source)
            if source == "compact":
                # Codex runs this start hook at the next turn, after the UI compacted.
                terminal.wait(lambda:b"Context compacted" in terminal.data[offset:] and b"7501;state=done" in terminal.data[offset:])
            else:
                until = time.monotonic() + .5; terminal.wait(lambda:time.monotonic() > until)
        turn()
        terminal.line("/quit")
        terminal.wait(lambda:terminal.status is not None)
    finally:
        status = terminal.close()
    assert status == 0
    return wait_capture(home, before, source)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("output"); args = parser.parse_args()
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=False)
    original_run, original_env = runner.run, runner.base_env
    original_repo, original_memory = runner.REPO, runner.MEMORY
    runner.REPO = paced_package(original_repo, output)
    runner.MEMORY = runner.REPO / "plugins/corthex-memory"
    proxy = NetworkProxy(); retained = {}
    runner.base_env = lambda home:dict(original_env(home), HOOKCHECK_LIFECYCLE_GATES=str(home.parent / "prompt-gates"), **proxy.environment())
    def execute(command, env, cwd=None, **kw):
        # Persistent history is necessary for the host's real resume/fork operations.
        command = [part for part in command if part != "--ephemeral"]
        if "-p" in command or "exec" in command:
            source = "fork" if "--fork-session" in command else (
                "resume" if "--resume" in command or "resume" in command else "startup")
            arm_start(env, source)
        done = original_run(command, env, cwd, **kw)
        if "-p" in command or "exec" in command:
            retained.update(exe=command[0],env=env,project=cwd,done=done)
        return done
    runner.run = execute
    report = {"os":platform.system(),"real_model":False,"user_store":False,"hosts":{},"versions":{},"pacing":{}}
    try:
        runner.market(output / "hk")
        for host in ("claude", "codex"):
            model = runner.Mock()
            try:
                initial = getattr(runner, host)("lifecycle", output, model, output / "hk", [])
                report["versions"][host] = initial["version"]
                exe, env, project = retained["exe"], retained["env"], retained["project"]
                seed = runner.native_session(host, retained["done"]); home = output / host / "home"
                results = {"startup":wait_capture(home, {}, "startup")}
                report["hosts"][host] = results
                for source in (("resume", "fork") if host == "claude" else ("resume",)):
                    before = raw(home)
                    command = [exe,"-p",runner.PROMPT,"--resume",seed,"--output-format","json"] if host == "claude" else [exe,"exec","resume","--json","--skip-git-repo-check","--dangerously-bypass-hook-trust",seed,runner.PROMPT]
                    if source == "fork": command += ["--fork-session"]
                    done = runner.run(command, env, project); assert done["exit"] == 0
                    results[source] = wait_capture(home, before, source)
                for source in ("clear", "compact") if host == "claude" else (() if os.name == "nt" else ("clear", "compact", "fork")):
                    results[source] = (claude_command(source,exe,env,project,home,output) if host == "claude" else
                                       codex_terminal(source,exe,env,project,home,output,seed))
                report["pacing"][host] = pacing_evidence(output / host)
            finally:
                model.server.shutdown(); model.server.server_close()
                home = output / host / "home"
                if home.exists():
                    retain_store_evidence(home, output / host)
        report.update(verified=True, windows_codex_operator_sources=["clear","compact","fork"] if os.name == "nt" else [])
    finally:
        runner.run, runner.base_env = original_run, original_env
        runner.REPO, runner.MEMORY = original_repo, original_memory
        report["host_proxy"] = proxy.finish()
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("CORTHEX_LIFECYCLE=" + json.dumps({"verified":report.get("verified"),"os":report["os"],
          "sources":{h:list(rows) for h,rows in report["hosts"].items()},"operator_sources":report.get("windows_codex_operator_sources")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
