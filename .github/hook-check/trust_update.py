"""Observe the native Codex update/retrust UI in a disposable Unix home."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import zipfile

import run as runner
from native_terminal import Terminal
from network_proxy import NetworkProxy

OLD = "dfc6a2c68d01c840f41206074b6a498cbf06bf27"

def before_retrust_files(home):
    files = runner.native_evidence.persistent_files(home)
    root = home / ".corthex/corthex-memory"
    files.update({p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in (root / "logs").glob("*.jsonl")})
    return files


def trust_hooks(terminal, path, expected):
    def screen(offset=0):
        return re.sub(rb"\x1b\[[0-?]*[ -/]*[@-~]", b"", bytes(terminal.data[offset:]))
    terminal.wait(lambda: b"Hooks need review" in screen() and b"Trust" in screen())
    before = screen()
    assert re.search(rb"\b" + str(expected).encode() + rb" hooks? (?:is|are) new or changed", before)
    # The popup can be drawn while startup terminal probes still consume input.
    terminal.key(b"", pause=.5)
    offset = len(terminal.data)
    # Enter opens the default review choice. Use the panel's advertised action;
    # a cursor key at the startup popup can be consumed before it is interactive.
    terminal.key(b"\r")
    terminal.wait(lambda: b"Lifecycle hooks from config and enabled plugins." in screen(offset)
                  and b"t trust all" in screen(offset))
    terminal.key(b"t")
    terminal.wait(lambda: len(re.findall(r"(?m)^trusted_hash\s*=", path.read_text(encoding="utf-8"))) == expected)


def archive():
    packed = subprocess.check_output(["git", "-C", str(runner.REPO), "archive", "--format=zip", OLD,
                                      ".agents/plugins", ".claude-plugin", "plugins"])
    with zipfile.ZipFile(io.BytesIO(packed)) as source:
        result = {}
        for entry in source.infolist():
            name = Path(entry.filename)
            assert not name.is_absolute() and ".." not in name.parts
            assert stat.S_IFMT(entry.external_attr >> 16) != stat.S_IFLNK
            if not entry.is_dir():
                result[entry.filename] = source.read(entry)
        return result


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("output"); args = parser.parse_args()
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=False)
    assert os.name != "nt", "Windows has a separately recorded operator UI run"
    files = archive()
    market = output / "market"
    for name, content in files.items():
        target = market / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
    home, project = runner.prepare(output / "state")
    config = output / "codex-home"; config.mkdir()
    model, proxy = runner.Mock(), NetworkProxy()
    model.log = output / "requests.jsonl"
    path = config / "config.toml"; path.write_text(runner.CODEX_CONFIG % model.port, encoding="utf-8")
    env = dict(runner.base_env(home), **proxy.environment())
    env.update(CODEX_HOME=str(config), MOCK_KEY="synthetic-local-fixture")
    exe = shutil.which("codex", path=env["PATH"]); assert exe
    report = {"os":platform.system(), "real_model":False, "user_store":False, "old_source":OLD, "steps":[]}
    def execute(label, command):
        done = runner.run([exe] + command, env, project, timeout=120)
        (output / (label + ".json")).write_text(json.dumps(done, ensure_ascii=False) + "\n", encoding="utf-8")
        assert done["exit"] == 0, label
        report["steps"].append({"phase":label,"exit":done["exit"]})
        return done
    def review(label, expected):
        command = [exe, "--no-daemon", "--no-alt-screen", "--dangerously-bypass-approvals-and-sandbox"]
        assert not any("hook-trust" in part for part in command)
        terminal = Terminal(command, env, project, output / (label + "-terminal.bin"))
        try:
            trust_hooks(terminal, path, expected)
        finally:
            status = terminal.close()
        assert status == 0
        return {"new_or_changed":expected, "native_review_observed":True, "trusted_by_operator_fixture":True,
                "terminal_sha256":hashlib.sha256(terminal.data).hexdigest()}
    try:
        execute("marketplace", ["plugin", "marketplace", "add", str(market)])
        old = execute("install-old", ["plugin", "add", "corthex-memory@corthex", "--json"])
        assert json.loads(old["stdout"])["version"] == "0.1.0"
        report["old_review"] = review("old", 1)
        execute("old-session", ["exec", "--json", "--skip-git-repo-check", "--ephemeral", runner.PROMPT])
        before = before_retrust_files(home)
        replacement = {}
        for folder in (".agents/plugins", ".claude-plugin", "plugins/corthex-memory"):
            replacement.update({p.relative_to(runner.REPO).as_posix():p.read_bytes()
                                for p in (runner.REPO / folder).rglob("*") if p.is_file()})
        for name in set(files) - set(replacement):
            if name.startswith("plugins/corthex-memory/"):
                target = (market / name).resolve(); target.relative_to((market / "plugins/corthex-memory").resolve()); target.unlink()
        for name, content in replacement.items():
            target = market / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
        new = execute("install-new", ["plugin", "add", "corthex-memory@corthex", "--json"])
        version = json.loads((runner.MEMORY / ".claude-plugin/plugin.json").read_bytes())["version"]
        assert json.loads(new["stdout"])["version"] == version
        execute("untrusted-session", ["exec", "--json", "--skip-git-repo-check", "--ephemeral", runner.PROMPT])
        assert before == before_retrust_files(home), "No raw, timing or failure writes before retrust"
        report["new_review"] = review("new", 4)
        done = execute("trusted-session", ["exec", "--json", "--skip-git-repo-check", "--ephemeral", runner.PROMPT])
        session = runner.native_session("codex", done)
        report["capture"] = runner.wait_for_capture(home, host="codex", session=session)
        assert all(report["capture"][key] for key in ("start_ok", "prompt_ok", "answer_ok", "end_ok", "same_turn", "korean_intact", "boundary_ok", "timings_ok", "failures_ok"))
        status = runner.run([sys.executable, "-B", str(runner.MEMORY / "skills/corthex-memory/scripts/memory.py"),
                             "status", "--folder", str(project)], env, project)
        (output / "status.json").write_text(json.dumps(status, ensure_ascii=False) + "\n", encoding="utf-8")
        hooks = {row["hook"]:row for row in json.loads(status["stdout"])["data"]["hooks"] if row["host"] == "codex"}
        assert status["exit"] == 0 and all(hooks[name]["last"] for name in ("start", "prompt", "end-of-turn", "end"))
        caches = list((config / "plugins/cache/corthex/corthex-memory").glob(version)); assert len(caches) == 1
        report["cache_sha256s"] = {p.relative_to(runner.MEMORY).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in runner.MEMORY.rglob("*") if p.is_file()}
        assert all(hashlib.sha256((caches[0] / name).read_bytes()).hexdigest() == value for name, value in report["cache_sha256s"].items())
        report.update(verified=True, no_recording_before_retrust=True, bypass_hook_trust=False)
    finally:
        model.server.shutdown(); model.server.server_close(); report["host_proxy"] = proxy.finish()
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("CORTHEX_TRUST_UPDATE=" + json.dumps({"verified":report.get("verified"),"os":report["os"],
          "old_review":report.get("old_review"),"new_review":report.get("new_review"),
          "no_recording_before_retrust":report.get("no_recording_before_retrust"),"cache_files":len(report.get("cache_sha256s",{}))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
