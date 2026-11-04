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
from lifecycle import retain_store_evidence

MARKER = "PREFIX_TASK_FIXTURE_314159"
PREFIXES = ("<task-notification>", "<cross-session-message", "<teammate-message", "<agent-message")

def controller_hashes():
    folder = Path(__file__).resolve().parent
    names = ("native_prefix.py", "cross_session.py", "measure_hook.py", "lifecycle.py", "run.py", "network_proxy.py", "tool_turn.py")
    return {name:hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in names}


def measured_copy(output):
    repository = runner.REPO; target = output / "source"; target.mkdir()
    for folder in (".claude-plugin", ".agents/plugins", "plugins"):
        shutil.copytree(repository / folder, target / folder, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    memory = target / "plugins/corthex-memory"
    originals = {p.relative_to(memory).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in memory.rglob("*") if p.is_file()}
    shutil.copyfile(Path(__file__).with_name("measure_hook.py"), memory / "scripts/measure_hook.py")
    hooks = memory / "hooks/hooks.json"; text = hooks.read_text(encoding="utf-8"); assert text.count("/scripts/hook.py") == 20
    hooks.write_text(text.replace("/scripts/hook.py", "/scripts/measure_hook.py"), encoding="utf-8")
    (output / "native-instrumentation.json").write_text(json.dumps({
        "candidate_sha256s": originals, "modified_hook_config_sha256": hashlib.sha256(hooks.read_bytes()).hexdigest(),
        "measurement_helper_sha256": hashlib.sha256((memory / "scripts/measure_hook.py").read_bytes()).hexdigest(),
        "scope": "QA hook configuration and input/clock observer; original product children unchanged; not an agent walk"
    }, indent=2) + "\n", encoding="utf-8")
    return target, memory, originals


def tool_reply(tool, value, call_id, model):
    return sse([
        {"type":"message_start", "message":{"id":"msg_" + call_id,"type":"message","role":"assistant","model":model,
            "content":[],"stop_reason":None,"stop_sequence":None,"usage":{"input_tokens":3,"output_tokens":0}}},
        {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":call_id,"name":tool,"input":{}}},
        {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":json.dumps(value)}},
        {"type":"content_block_stop","index":0},
        {"type":"message_delta","delta":{"stop_reason":"tool_use","stop_sequence":None},"usage":{"output_tokens":8}},
        {"type":"message_stop"}])


def installed_copy(config, memory, originals):
    version = json.loads((memory / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
    cache = config / "plugins/cache/corthex/corthex-memory" / version
    expected = dict(originals)
    for name in ("hooks/hooks.json", "scripts/measure_hook.py"):
        expected[name] = hashlib.sha256((memory / name).read_bytes()).hexdigest()
    actual = {name:hashlib.sha256((cache / name).read_bytes()).hexdigest() for name in expected}
    assert actual == expected, "The actual installed package must match the declared QA copy"
    return {"verified":True,"relative_cache":cache.relative_to(config).as_posix(),"sha256s":actual}


def successful_send(requests, call_id, target, marker):
    """Require actual native tool input and its positive acknowledgement."""
    sent, returned = [], []
    for request in requests:
        for message in request.get("messages", []):
            for item in message["content"] if isinstance(message.get("content"), list) else []:
                if item.get("type") == "tool_use" and item.get("id") == call_id:
                    sent.append(item["name"] == "SendMessage" and item["input"]["to"] == target and marker in item["input"]["message"])
                if item.get("type") == "tool_result" and item.get("tool_use_id") == call_id:
                    values = [json.loads(part["text"]) for part in item.get("content", []) if part.get("type") == "text"]
                    returned.append(not item.get("is_error") and any(v.get("success") is True for v in values))
    assert sent and all(sent) and returned and all(returned), "Actual native SendMessage must succeed to the owned destination"
    return {"native_send_succeeded":True, "target":target}


def qualify_own_parent(inputs, requests, parent_session, task, marker):
    notices = [v for v in inputs if v.get("prompt", "").lstrip().startswith("<agent-message")]
    assert len(notices) == 1, "The native own-parent message must reach the prompt hook once"
    own = notices[0]
    assert own["session_id"] == parent_session and marker in own["prompt"]
    assert re.search(r'<agent-message from="([^"]+)"', own["prompt"])[1] == task
    send = successful_send(requests, "toolu_child_2", "main", marker)
    return dict(send, verified=True, agent_id=task, receiver_session=parent_session)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("output"); parser.add_argument("--kind", choices=("task", "agent"), default="task"); args = parser.parse_args()
    marker = MARKER if args.kind == "task" else "AGENT_ONLY_FIXTURE_141421"
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=False)
    target, memory, originals = measured_copy(output)
    old_repository, old_memory, old_run, old_env, old_prepare = runner.REPO, runner.MEMORY, runner.run, runner.base_env, runner.prepare
    proxy, model = NetworkProxy(), runner.Mock()
    observed, retained, parent_calls, child_calls = [], {}, [], []
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
            command += ["--max-turns", "8", "--allowedTools", "Read", "Agent", "ToolSearch", "SendMessage"]
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
        child = any(marker in value and not value.lstrip().startswith(PREFIXES) for value in users)
        if child:
            if args.kind == "agent" and len(child_calls) < 2:
                child_calls.append(True); number = len(child_calls)
                tool, value = (("ToolSearch", {"query":"select:SendMessage"}) if number == 1 else
                               ("SendMessage", {"to":"main", "message":marker + " synthetic own-parent message only."}))
                return tool_reply(tool, value, "toolu_child_" + str(number), name)
            return runner.Mock.stream(path, name)
        if "<task-notification>" in observed or len(parent_calls) >= 6:
            return runner.Mock.stream(path, name)
        parent_calls.append(True); number = len(parent_calls)
        tool = "Agent" if number == 1 else "Read"
        value = {"description":"Synthetic prefix fixture", "prompt":marker + "; reply using only the synthetic own-parent tools.",
                 "run_in_background":True} if tool == "Agent" else {"file_path":str(output / "claude/work/demo/prefix-fixture.txt")}
        return tool_reply(tool, value, "toolu_prefix_" + str(number), name)
    runner.REPO, runner.MEMORY, runner.run, runner.base_env, runner.prepare = target, memory, execute, environment, prepare
    model.stream = stream
    report = {"os":platform.system(),"real_model":False,"user_store":False,"original_runtime_sha256s":originals,"kind":args.kind,"controller_sha256s":controller_hashes()}
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
        agent_notices = [v for v in inputs if v.get("prompt", "").lstrip().startswith("<agent-message")]
        if args.kind == "agent":
            requests = [json.loads(json.loads(line)["body"]) for line in (output / "claude/requests.jsonl").read_text(encoding="utf-8").splitlines()]
            report["native_own_parent_message"] = qualify_own_parent(inputs, requests, retained["session"], task, marker)
        else:
            assert not agent_notices
        root = output / "claude/home/.corthex/corthex-memory"
        assert not any(any(mark in p.read_bytes() for mark in (marker.encode(), b"<task-notification>", b"<agent-message")) for p in root.rglob("*") if p.is_file())
        assert all(result["capture"][key] for key in ("start_ok","prompt_ok","answer_ok","end_ok","same_turn","korean_intact","boundary_ok","failures_ok","timings_ok"))
        assert sorted(result["capture"]["hook_outcomes"]["prompt"]) == (["left-out", "left-out", "ok"] if args.kind == "agent" else ["left-out", "ok"])
        assert all(hashlib.sha256((memory / name).read_bytes()).hexdigest() == value for name,value in originals.items() if name != "hooks/hooks.json")
        actual_prefixes = sorted({prefix for value in inputs for prefix in PREFIXES if value.get("prompt", "").lstrip().startswith(prefix)})
        assert actual_prefixes == (["<agent-message", "<task-notification>"] if args.kind == "agent" else ["<task-notification>"])
        report["installed_copy"] = installed_copy(output / "claude/config", memory, originals)
        assert report["controller_sha256s"] == controller_hashes(), "QA controller source changed during execution"
        report.update(verified=True, native_agent_launch_matches_completion=True, observed_prompt_prefixes=actual_prefixes,
                      unobserved_prompt_prefixes=[p for p in PREFIXES if p not in actual_prefixes], prefix_filter_version="host-prompts-2",
                      scope="Only actually observed own-parent native branches; legacy teams and cross-session delivery are separate")
    finally:
        runner.REPO, runner.MEMORY, runner.run, runner.base_env, runner.prepare = old_repository, old_memory, old_run, old_env, old_prepare
        model.server.shutdown(); model.server.server_close(); report["host_proxy"] = proxy.finish()
        retain_store_evidence(output / "claude/home", output / "claude")
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("CORTHEX_NATIVE_PREFIX=" + json.dumps({"verified":report.get("verified"),"os":report["os"],
          "observed":report.get("observed_prompt_prefixes"),"unobserved":report.get("unobserved_prompt_prefixes")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
