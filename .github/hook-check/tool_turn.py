"""Actual native tool outputs stay outside C1 memory; the model is loopback."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import time

import run as runner
from network_proxy import NetworkProxy

MARKER = "TOOL_ONLY_FIXTURE_938107"


def sse(events):
    return b"".join(("event: " + value["type"] + "\ndata: " + json.dumps(value, ensure_ascii=False) + "\n\n").encode("utf-8") for value in events)


def tool_stream(host, output):
    called = []
    def stream(path, model):
        if not any(endpoint in path for endpoint in ("/messages", "/responses")) or called:
            return runner.Mock.stream(path, model)
        called.append(True)
        if host == "claude":
            data = json.dumps({"file_path": str((output / host / "work/demo" / (MARKER + ".txt")).resolve())})
            return sse([
                {"type":"message_start","message":{"id":"msg_tool_fixture","type":"message","role":"assistant","model":model,
                    "content":[],"stop_reason":None,"stop_sequence":None,"usage":{"input_tokens":3,"output_tokens":0}}},
                {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":"toolu_fixture","name":"Read","input":{}}},
                {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":data}},
                {"type":"content_block_stop","index":0},
                {"type":"message_delta","delta":{"stop_reason":"tool_use","stop_sequence":None},"usage":{"output_tokens":8}},
                {"type":"message_stop"}])
        code = "text(" + json.dumps(MARKER) + ");"
        item = {"id":"ctc_fixture","type":"custom_tool_call","call_id":"call_fixture","namespace":"functions","name":"exec","input":code}
        response = {"id":"resp_tool_fixture","object":"response","created_at":int(time.time()),"model":model,
                    "status":"completed","output":[item],"error":None,"usage":{"input_tokens":3,"output_tokens":8,"total_tokens":11}}
        events = [
            {"type":"response.created","response":dict(response,status="in_progress",output=[])},
            {"type":"response.output_item.added","output_index":0,"item":dict(item,input="")},
            {"type":"response.custom_tool_call_input.delta","output_index":0,"item_id":item["id"],"delta":code},
            {"type":"response.custom_tool_call_input.done","output_index":0,"item_id":item["id"],"input":code},
            {"type":"response.output_item.done","output_index":0,"item":item},
            {"type":"response.completed","response":response}]
        for number, event in enumerate(events):
            event["sequence_number"] = number
        return sse(events)
    return stream


def qualify(output, host, result):
    calls, inputs, outputs = 0, [], []
    for line in (output / host / "requests.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if not any(x in row["path"] for x in ("/messages", "/responses")) or "/count_tokens" in row["path"]:
            continue
        body = json.loads(row["body"])
        calls += 1
        if host == "claude":
            for message in body.get("messages", []):
                content = message.get("content")
                for item in content if isinstance(content, list) else []:
                    if item.get("type") == "tool_use" and item.get("name") == "Read" and MARKER in json.dumps(item.get("input")):
                        inputs.append(item)
                    if item.get("type") == "tool_result" and item.get("tool_use_id") == "toolu_fixture" and not item.get("is_error") and MARKER in json.dumps(item.get("content")):
                        outputs.append(item)
        else:
            for item in body.get("input", []):
                if item.get("type") == "custom_tool_call" and item.get("namespace") == "functions" and item.get("name") == "exec" and item.get("input") == "text(" + json.dumps(MARKER) + ");":
                    inputs.append(item)
                if item.get("type") == "custom_tool_call_output" and item.get("call_id") == "call_fixture":
                    parts = item.get("output", [])
                    if any(p.get("text") == MARKER for p in parts) and any("Script completed" in p.get("text", "") for p in parts):
                        outputs.append(item)
    assert calls == 2 and inputs and outputs, "The native tool must actually succeed"
    assert result["run"]["exit"] == 0 and all(result["capture"][k] for k in ("start_ok", "prompt_ok", "answer_ok", "end_ok", "same_turn", "korean_intact", "timings_ok", "failures_ok", "boundary_ok"))
    root = output / host / "home/.corthex/corthex-memory"
    assert not any(MARKER.encode() in p.read_bytes() for p in root.rglob("*") if p.is_file())
    transcripts = []
    if host == "claude":
        raw = next(root.glob("projects/*/raw/*.jsonl"))
        session = json.loads(raw.read_bytes().splitlines()[0])["session"]
        projects = (output / host / "config/projects").resolve()
        owned = Path("\\\\?\\" + str(projects)) if os.name == "nt" else projects
        for path in owned.rglob("*.jsonl"):
            if path.name != session + ".jsonl":
                continue
            path.relative_to(owned)
            content = path.read_bytes()
            if MARKER.encode() in content:
                transcripts.append({"name":path.name,"bytes":len(content),"sha256":hashlib.sha256(content).hexdigest()})
        assert transcripts, "The actual transcript must hold the tool marker"
    return {"version":result["version"],"successful_tool": "Read" if host == "claude" else "functions.exec",
            "model_requests":calls,"memory_marker_occurrences":0,"capture":result["capture"],"transcripts":transcripts}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("output"); args = parser.parse_args()
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=False)
    original_env, original_prepare = runner.base_env, runner.prepare
    proxy = NetworkProxy()
    def environment(home):
        return dict(original_env(home), **proxy.environment())
    def provision(base):
        home, project = original_prepare(base)
        (project / (MARKER + ".txt")).write_text(MARKER + "\n", encoding="utf-8")
        return home, project
    runner.base_env, runner.prepare = environment, provision
    report = {"os":platform.system(),"python":platform.python_version(),"real_model":False,"user_store":False,"hosts":{}}
    try:
        runner.market(output / "hk")
        for host in ("claude", "codex"):
            model = runner.Mock(); model.stream = tool_stream(host, output)
            try:
                result = getattr(runner, host)("toolturn", output, model, output / "hk", [])
                (output / (host + "-native.json")).write_text(json.dumps(result, ensure_ascii=False) + "\n", encoding="utf-8")
                report["hosts"][host] = qualify(output, host, result)
            finally:
                model.server.shutdown(); model.server.server_close()
        report["verified"] = True
    finally:
        runner.base_env, runner.prepare = original_env, original_prepare
        report["host_proxy"] = proxy.finish()
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("CORTHEX_TOOL_TURN=" + json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
