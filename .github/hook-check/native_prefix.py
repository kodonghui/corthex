"""Native background-agent notification and prefix drift, with loopback replies."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import threading

import run as runner
from network_proxy import NetworkProxy
from tool_turn import sse

MARKER = "PREFIX_TASK_FIXTURE_314159"
PREFIXES = ("<task-notification>", "<cross-session-message", "<teammate-message")


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("output"); args = parser.parse_args()
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=False)
    repository = runner.REPO; target = output / "source"; target.mkdir()
    for folder in (".claude-plugin", ".agents/plugins", "plugins"):
        shutil.copytree(repository / folder, target / folder)
    memory = target / "plugins/corthex-memory"
    originals = {p.relative_to(memory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in memory.rglob("*") if p.is_file()}
    shutil.copyfile(Path(__file__).with_name("measure_hook.py"), memory / "scripts/measure_hook.py")
    hooks = memory / "hooks/hooks.json"; text = hooks.read_text(encoding="utf-8"); assert text.count("/scripts/hook.py") == 20
    hooks.write_text(text.replace("/scripts/hook.py", "/scripts/measure_hook.py"), encoding="utf-8")
    old_repository, old_memory, old_run, old_env, old_prepare = runner.REPO, runner.MEMORY, runner.run, runner.base_env, runner.prepare
    proxy, model = NetworkProxy(), runner.Mock()
    observed, retained, parent_calls = [], {}, []
    lock = threading.Lock(); handler = model.server.RequestHandlerClass; original_handler = handler.handle_any
    def serialized(request):
        with lock:
            return original_handler(request)
    handler.do_GET = handler.do_POST = serialized
    def environment(home):
        return dict(old_env(home), **proxy.environment(), HOOKCHECK_MEASURE_DIR=str(output / "measurements"),
                    HOOKCHECK_CAPTURE_INPUT_DIR=str(output / "inputs"))
    def prepare(base):
        home, project = old_prepare(base)
        (project / "prefix-fixture.txt").write_text("synthetic fixture only\n", encoding="utf-8")
        return home, project
    def execute(command, *a, **kw):
        if "-p" in command:
            command += ["--max-turns", "8", "--allowedTools", "Read", "Agent"]
            kw["timeout"] = 90
        done = old_run(command, *a, **kw)
        if "-p" in command:
            retained["session"] = runner.native_session("claude", done)
        return done
    def stream(path, name):
        request = json.loads(json.loads(model.log.read_text(encoding="utf-8").splitlines()[-1])["body"])
        users = [part.get("text", "") for message in request.get("messages", []) if message.get("role") == "user"
                 for part in (message["content"] if isinstance(message.get("content"), list) else [{"type":"text", "text":message.get("content", "")}]) if part.get("type") == "text"]
        prefixes = {prefix for value in users for prefix in PREFIXES if value.lstrip().startswith(prefix)}
        observed.extend(sorted(prefixes))
        child = any(MARKER in value and not value.lstrip().startswith(PREFIXES) for value in users)
        if child or observed or len(parent_calls) >= 6:
            return runner.Mock.stream(path, name)
        parent_calls.append(True); number = len(parent_calls)
        tool = "Agent" if number == 1 else "Read"
        value = {"description":"Synthetic prefix fixture", "prompt":MARKER + "; reply with a short synthetic completion only.",
                 "run_in_background":True} if tool == "Agent" else {"file_path":str(output / "claude/work/demo/prefix-fixture.txt")}
        return sse([
            {"type":"message_start", "message":{"id":"msg_prefix_" + str(number),"type":"message","role":"assistant","model":name,
                "content":[],"stop_reason":None,"stop_sequence":None,"usage":{"input_tokens":3,"output_tokens":0}}},
            {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"toolu_prefix_" + str(number),"name":tool,"input":{}}},
            {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":json.dumps(value)}},
            {"type":"content_block_stop","index":0},
            {"type":"message_delta","delta":{"stop_reason":"tool_use","stop_sequence":None},"usage":{"output_tokens":8}},
            {"type":"message_stop"}])
    runner.REPO, runner.MEMORY, runner.run, runner.base_env, runner.prepare = target, memory, execute, environment, prepare
    model.stream = stream
    report = {"os":platform.system(),"real_model":False,"user_store":False,"original_runtime_sha256s":originals}
    try:
        runner.market(output / "hk")
        result = runner.claude("prefix", output, model, output / "hk", [])
        report["host"] = result
        assert result["run"]["exit"] == 0
        inputs = [json.loads(p.read_bytes()) for p in (output / "inputs").glob("*.json")]
        notices = [v for v in inputs if v.get("prompt", "").lstrip().startswith("<task-notification>")]
        assert len(notices) == 1, "The actual native completion notification must reach the prompt hook"
        notice = notices[0]; task = re.search(r"<task-id>([^<]+)</task-id>", notice["prompt"])[1]
        assert "<status>completed</status>" in notice["prompt"] and notice["session_id"] == retained["session"]
        launched = []
        for line in (output / "claude/requests.jsonl").read_text(encoding="utf-8").splitlines():
            body = json.loads(json.loads(line)["body"])
            for message in body.get("messages", []):
                for item in message["content"] if isinstance(message.get("content"), list) else []:
                    if item.get("type") == "tool_result" and item.get("tool_use_id") == "toolu_prefix_1" and not item.get("is_error"):
                        value = json.dumps(item.get("content"), ensure_ascii=False)
                        if "Async agent launched successfully." in value and "agentId: " + task in value:
                            launched.append(True)
        assert launched, "The native notification's task must be the successfully launched background agent"
        root = output / "claude/home/.corthex/corthex-memory"
        assert not any(any(mark in p.read_bytes() for mark in (MARKER.encode(), b"<task-notification>")) for p in root.rglob("*") if p.is_file())
        assert all(result["capture"][key] for key in ("start_ok","prompt_ok","answer_ok","end_ok","same_turn","korean_intact","boundary_ok","failures_ok","timings_ok"))
        assert sorted(result["capture"]["hook_outcomes"]["prompt"]) == ["left-out", "ok"]
        assert all(hashlib.sha256((memory / name).read_bytes()).hexdigest() == value for name,value in originals.items() if name != "hooks/hooks.json")
        report.update(verified=True, native_agent_launch_matches_completion=True, observed_prompt_prefixes=["<task-notification>"],
                      unobserved_prompt_prefixes=list(PREFIXES[1:]), prefix_filter_version="host-prompts-1",
                      scope="One actual native notification branch, not a claim about unobserved team/cross-session branches")
    finally:
        runner.REPO, runner.MEMORY, runner.run, runner.base_env, runner.prepare = old_repository, old_memory, old_run, old_env, old_prepare
        model.server.shutdown(); model.server.server_close(); report["host_proxy"] = proxy.finish()
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("CORTHEX_NATIVE_PREFIX=" + json.dumps({"verified":report.get("verified"),"os":report["os"],
          "observed":report.get("observed_prompt_prefixes"),"unobserved":report.get("unobserved_prompt_prefixes")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
