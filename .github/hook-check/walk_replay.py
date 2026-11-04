"""C1 agent-flow state replays with installed hosts and loopback model replies.

Real-model language/consent judgements stay in the walk report. These replays
exercise the resulting CLI operations and native hook inputs without provider
accounts. Lifecycle-only pacing is declared, never a timing or race fix.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

import run as runner
from lifecycle import arm_start, paced_package, retain_store_evidence


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def snapshot(home):
    root = home / ".corthex/corthex-memory"
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and p.suffix not in (".lock", ".tmp", ".stale")}


def records(home):
    """Current logical data; start workers may maintain backups and diagnostics."""
    return {name: value for name, value in snapshot(home).items()
            if not name.startswith("logs/") and not name.endswith(".bak")}


def remembered(home):
    """Retention may refresh progress/markers; recording must keep current memory."""
    values = records(home)
    protected = {name: value for name, value in values.items()
                 if name in ("store.json", "configuration.json") or "/raw/" in name or "/layer/" in name}
    for name, value in values.items():
        if name.endswith("/curation.json"):
            record = json.loads(value)
            record.pop("logs", None)  # Retention repairs these raw progress keys.
            protected[name] = json.dumps(record, sort_keys=True).encode("utf-8")
    return protected


def raw_rows(home, session):
    return [json.loads(line) for path in (home / ".corthex/corthex-memory").glob("projects/*/raw/*.jsonl")
            for line in path.read_bytes().splitlines() if json.loads(line).get("session") == session]


def entrypoint_replays(output):
    """Replay exceptional C1 paths through existing real subprocess regressions."""
    names = [
        "test_memory_hook_recording.HookRecordingTest.test_tc044_missing_empty_and_nonstring_answers_have_no_entry",
        "test_memory_start_hook.StartHookTest.test_tc068_readonly_store_preserves_deadlines_and_exits_without_changes",
        "test_memory_start_hook.StartHookTest.test_tc069_composition_errors_keep_base_fixed_notice_and_safe_diagnostics",
        "test_memory_start_hook.StartHookTest.test_actual_session_start_runs_all_project_retention_and_cleanup_after_hook_exit",
        "test_memory_raw_log.RawLogTest.test_tc029_kill_writers_during_1000_appends_preserves_returned_writes",
        "test_memory_redaction.MemoryRedactionTest.test_tc023_each_generated_format_is_redacted_before_any_write",
        "test_memory_walk_replay.WalkReplayGuardTest",
    ]
    repository = Path(__file__).resolve().parents[2]
    env = runner.base_env(output / "api-home")
    env["PYTHONPATH"] = str(repository / "tests")
    done = runner.run([sys.executable, "-B", "-m", "unittest", "-v"] + names, env, repository)
    save(output / "entrypoint-replays.json", dict(done, cases=names, real_model=False, user_store=False))
    assert done["exit"] == 0, "C1 entrypoint regression failed"
    return {"exit": done["exit"], "cases": names, "seconds": done["seconds"]}


class Replay:
    def __init__(self, host, lang, base, retained, model):
        self.host, self.lang, self.base, self.model = host, lang, base, model
        self.exe, self.env, self.project = retained["exe"], retained["env"], retained["project"]
        self.home = Path(self.env["HOME"])
        config = Path(self.env["CLAUDE_CONFIG_DIR"] if host == "claude" else self.env["CODEX_HOME"])
        scripts = list((config / "plugins/cache/corthex/corthex-memory").glob("*/skills/corthex-memory/scripts/memory.py"))
        assert len(scripts) == 1
        self.script = scripts[0]
        candidate = {p.relative_to(runner.MEMORY).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in runner.MEMORY.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
        installed = {name: hashlib.sha256((self.script.parents[3] / name).read_bytes()).hexdigest()
                     for name in candidate}
        assert installed == candidate, "The installed replay package differs from its declared source"
        self.report = {"host": host, "language": lang, "commands": [], "command_runs": [], "turns": [],
                       "real_model": False, "user_store": False,
                       "semantic_agent_reply_claimed": False,
                       "source_sha256s": candidate, "installed_sha256s": installed}

    def command(self, command, *arguments, confirm=False, folder=None):
        args = [sys.executable, "-B", str(self.script), "--folder", str(folder or self.project), command] + list(arguments)
        done = runner.run(args, self.env, self.project)
        self.report["command_runs"].append(done)
        value = json.loads(done["stdout"])
        self.report["commands"].append(value)
        assert done["exit"] == (1 if value["outcome"] in ("failed", "refused") else 0)
        if confirm:
            assert value["outcome"] == "confirm"
            done = runner.run(args + ["--confirm", value["confirm"]], self.env, self.project)
            self.report["command_runs"].append(done)
            value = json.loads(done["stdout"])
            self.report["commands"].append(value)
            assert done["exit"] == 0 and value["outcome"] == "done"
        return value

    def turn(self, label, expected, prompt=None, folder=None, installed=True):
        output = self.base / "observations"
        before = {p.name for p in output.glob("*.json")}
        folder = folder or self.project
        prompt = prompt or ("한국어 재생 질문 " if self.lang == "ko" else "English replay prompt ") + label
        arm_start(self.env, "startup")
        args = ([self.exe, "-p", prompt, "--output-format", "json"] if self.host == "claude" else
                [self.exe, "exec", "--json", "--skip-git-repo-check", "--ephemeral",
                 "--dangerously-bypass-hook-trust", prompt])
        record = {"label": label, "prompt": prompt, "expected_kinds": expected, "verified": False}
        self.report["turns"].append(record)
        try:
            done = runner.run(args, self.env, folder)
            safe = done
            for key in ("ANTHROPIC_API_KEY", "MOCK_KEY"):
                if self.env.get(key):
                    safe = runner.scrub_mock_key(safe, self.env[key])
            record["native_run"] = safe
            assert done["exit"] == 0, "Native replay failed: " + label
            session = runner.native_session(self.host, done)
            record["session"] = session
            deadline = time.monotonic() + 6
            while True:
                observed = [json.loads(p.read_bytes()) for p in output.glob("*.json") if p.name not in before]
                record["hooks"] = sorted(observed, key=lambda row: row["started_ns"])
                if not installed or any(v["hook"] == "end" and v["input"].get("session_id") == session for v in observed):
                    break
                assert time.monotonic() < deadline, "Native End observation missing: " + label
                time.sleep(.025)
            if installed:
                assert len(observed) == 4
                assert all(v["input"].get("session_id") == session for v in observed), "Unrelated native session observation"
                assert all(sum(v["hook"] == hook for v in observed) == 1
                           for hook in ("start", "prompt", "end-of-turn", "end"))
                assert all(v["exit"] == 0 and not v["stderr"] for v in observed)
                starts = [v for v in observed if v["hook"] == "start"]
                context = json.loads(starts[0]["stdout"])["hookSpecificOutput"]["additionalContext"]
                assert "CORTHEX session context" in context and len(context.encode("utf-8")) < 8000
            else:
                assert not observed
            rows = raw_rows(self.home, session)
            record["raw"] = rows
            assert [v["kind"] for v in rows] == expected, (label, rows)
            prompts = [v for v in rows if v["kind"] == "prompt"]
            answers = [v for v in rows if v["kind"] == "answer"]
            if prompts and answers:
                assert prompts[0]["turn"] == answers[0]["turn"]
            if answers:
                assert answers[0]["text"].strip() == runner.REPLY
            record["verified"] = True
        finally:
            failing = sys.exc_info()[0] is not None
            export_error = None
            try:
                retain_store_evidence(self.home, self.base / "turns" / label)
            except OSError as error:
                export_error = type(error).__name__
                record["export_error"] = export_error
                record["verified"] = False
            save(self.base / (label + ".json"), record)
            if export_error and not failing:
                raise AssertionError("Could not retain safe memory evidence: " + export_error)

    def walk(self):
        memory = self.home / ".corthex/corthex-memory"
        self.command("purge", confirm=True)
        proposal = self.command("on")
        assert proposal["outcome"] == "confirm" and proposal["data"]["consent"]["version"] == 1
        assert not memory.exists()  # No is withholding this confirmation, not another command.
        self.turn("no-consent", [])
        assert not memory.exists()
        outside = self.base / "no-project"; outside.mkdir()
        refused = self.command("on", folder=outside)
        assert refused["code"] == "not-in-project"
        self.turn("no-project", [], folder=outside)
        self.env.update(CORTHEX_MEMORY_ANTHROPIC_API_KEY="synthetic-anthropic-walk",
                        CORTHEX_MEMORY_OPENAI_API_KEY="synthetic-openai-walk")
        enabled = self.command("on", confirm=True)
        assert set(enabled["data"]["keys"].values()) == {"present"}
        marker = "PRIVATE_REPLAY_81723"
        self.turn("record-private", ["start", "prompt", "answer", "end"],
                  prompt=("정상 질문 " if self.lang == "ko" else "Normal prompt ") + "<private>" + marker + "</private>")
        assert all(marker.encode() not in value for value in snapshot(self.home).values())
        self.command("leave-out", "secret-data")
        excluded = self.project / "secret-data"; excluded.mkdir()
        self.turn("folder-left-out", [], folder=excluded)
        self.command("leave-out", "--kind", "answer")
        self.turn("answer-left-out", ["start", "prompt", "end"])
        both = self.command("leave-out", "--kind", "prompt")
        assert "nothing to read" in both["say"].lower()
        self.turn("both-text-left-out", ["start", "end"])
        self.command("leave-out", "--kind", "prompt", "--kind", "answer", "--remove")
        self.command("leave-out", "--kind", "boundary")
        self.turn("boundary-left-out", ["prompt", "answer"])
        self.command("leave-out", "--kind", "boundary", "--remove")
        self.env.pop("CORTHEX_MEMORY_ANTHROPIC_API_KEY")
        self.env.pop("CORTHEX_MEMORY_OPENAI_API_KEY")
        status = self.command("status")
        assert set(status["data"]["keys"].values()) == {"missing"}
        self.command("off")
        before = records(self.home)
        current_memory = remembered(self.home)
        self.turn("off", [])
        after = records(self.home)
        changed = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
        save(self.base / "off-maintenance.json", {"changed_auxiliary_paths": changed,
             "preserved_current_memory": current_memory == remembered(self.home),
             "retention_continues": True})
        assert current_memory == remembered(self.home), changed
        # The plugin is still installed: exercise the C1 purge/no-store gate.
        before = remembered(self.home)
        self.command("purge")
        assert before == remembered(self.home)
        protected = {p: p.read_bytes() for p in (self.home / ".corthex/profile.json",
                      self.home / ".corthex/projects.json", self.project / ".corthex/project.json")}
        self.command("purge", confirm=True)
        assert not memory.exists() and all(p.read_bytes() == data for p, data in protected.items())
        self.turn("purged-installed", [])
        assert not memory.exists()
        return self.report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    args = parser.parse_args()
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=False)
    original_run, original_env, original_repo, original_memory = runner.run, runner.base_env, runner.REPO, runner.MEMORY
    retained = {}
    report = {"real_model": False, "user_store": False, "runs": []}
    report["controller_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    try:
        runner.REPO = paced_package(original_repo, output)
        runner.MEMORY = runner.REPO / "plugins/corthex-memory"
        helper = runner.MEMORY / "scripts/walk_replay_hook.py"
        shutil.copyfile(Path(__file__).with_name("walk_replay_hook.py"), helper)
        hooks = runner.MEMORY / "hooks/hooks.json"
        text = hooks.read_text(encoding="utf-8").replace("/scripts/lifecycle_prompt.py", "/scripts/walk_replay_hook.py")
        text = text.replace("/scripts/hook.py", "/scripts/walk_replay_hook.py")
        hooks.write_bytes(text.encode("utf-8"))
        report["instrumentation"] = {"hooks_sha256": hashlib.sha256(hooks.read_bytes()).hexdigest(),
                                     "observer_sha256": hashlib.sha256(helper.read_bytes()).hexdigest(),
                                     "start_prompt_pacing": "lifecycle_prompt.py; unchanged original product children",
                                     "whole_hook_timing_claimed": False}
        runner.base_env = lambda home: dict(original_env(home),
            HOOKCHECK_LIFECYCLE_GATES=str(home.parent / "gates"),
            HOOKCHECK_WALK_OBSERVATIONS=str(home.parent / "observations"))
        def execute(command, env, cwd=None, **kwargs):
            if command and ("-p" in command or "exec" in command):
                arm_start(env, "startup")
                retained.update(exe=command[0], env=env, project=cwd)
            done = original_run(command, env, cwd, **kwargs)
            if command and ("-p" in command or "exec" in command):
                safe = done
                for key in ("ANTHROPIC_API_KEY", "MOCK_KEY"):
                    if env.get(key):
                        safe = runner.scrub_mock_key(safe, env[key])
                save(Path(env["HOME"]).parent / "native-runs" / (str(time.monotonic_ns()) + ".json"), safe)
            return done
        runner.run = execute
        runner.market(output / "hk")
        for lang in ("ko", "en"):
            for host in ("claude", "codex"):
                base = output / lang
                model = runner.Mock()
                try:
                    initial = getattr(runner, host)("walk", base, model, output / "hk", [])
                    assert initial["run"]["exit"] == 0
                    profile = Path(retained["env"]["HOME"]) / ".corthex/profile.json"
                    values = json.loads(profile.read_bytes()); values["language"] = lang; save(profile, values)
                    replay = Replay(host, lang, base / host, retained, model)
                    replay.report["version"] = initial["version"]
                    report["runs"].append(replay.report)
                    replay.walk()
                finally:
                    model.server.shutdown(); model.server.server_close()
        report["entrypoint_replays"] = entrypoint_replays(output)
        report["verified"] = True
    finally:
        runner.run, runner.base_env, runner.REPO, runner.MEMORY = original_run, original_env, original_repo, original_memory
        save(output / "result.json", report)
    print("CORTHEX_WALK_REPLAY=" + json.dumps({"verified": report.get("verified"),
          "host_language_runs": len(report["runs"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
