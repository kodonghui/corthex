"""Two owned synthetic sessions, real native IPC, and fixed loopback replies."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import secrets
import shutil
import time
import uuid

import run as runner
from lifecycle import Stream, retain_store_evidence
from native_prefix import measured_copy, tool_reply, successful_send, installed_copy, controller_hashes
from network_proxy import NetworkProxy

MARKER = "CROSS_ONLY_FIXTURE_161803"


def qualify_delivery(prompts, requests, receiver_session, names, marker):
    messages = [v for v in prompts if v.get("prompt", "").lstrip().startswith("<cross-session-message")]
    assert len(messages) == 1, "The owned receiver must receive exactly one native cross-session prompt"
    actual = messages[0]
    assert actual["session_id"] == receiver_session and marker in actual["prompt"]
    assert re.search(r'from-name="([^"]+)"', actual["prompt"])[1] == names["sender"]
    return successful_send(requests, "toolu_cross_2", names["receiver"], marker)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("output"); args = parser.parse_args()
    output = Path(args.output).resolve(); output.mkdir(parents=True, exist_ok=False)
    source, memory, originals = measured_copy(output)
    old_repository, old_memory = runner.REPO, runner.MEMORY
    runner.REPO, runner.MEMORY = source, memory
    config = output / "config"; config.mkdir()
    proxy = NetworkProxy(); models = {name:runner.Mock() for name in ("receiver", "sender")}
    names = {name:"fixture_" + name + "_" + uuid.uuid4().hex[:12] for name in models}
    profiles, receiver, report = {}, None, {"os":platform.system(), "real_model":False, "user_store":False,
        "other_user_sessions_contacted":False, "original_runtime_sha256s":originals, "owned_names":names, "controller_sha256s":controller_hashes()}
    try:
        for name in models:
            folder = output / name; home, project = runner.prepare(folder)
            env = dict(runner.base_env(home), **proxy.environment())
            env.update(CLAUDE_CONFIG_DIR=str(config), ANTHROPIC_API_KEY="sk-ant-" + secrets.token_hex(12),
                       ANTHROPIC_BASE_URL="http://127.0.0.1:%d" % models[name].port,
                       CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", DISABLE_AUTOUPDATER="1",
                       HOOKCHECK_MEASURE_DIR=str(folder / "measurements"), HOOKCHECK_CAPTURE_INPUT_DIR=str(folder / "inputs"))
            models[name].log = folder / "requests.jsonl"; profiles[name] = (home, project, env)
        exe = shutil.which("claude", path=profiles["receiver"][2]["PATH"]); assert exe
        for command in (["plugin","marketplace","add",str(source)], ["plugin","install","corthex-memory@corthex"]):
            done = runner.run([exe] + command, profiles["receiver"][2], profiles["receiver"][1]); assert done["exit"] == 0
        settings = json.dumps({"crossSessionInbound":"accept", "isolatePeerMachines":True})
        report["explicit_settings"] = json.loads(settings)
        receiver = Stream([exe,"-p","--input-format","stream-json","--output-format","stream-json","--verbose",
                           "--name",names["receiver"],"--settings",settings], profiles["receiver"][2], profiles["receiver"][1])
        first = receiver.send(runner.PROMPT); assert receiver.process.poll() is None
        report.update(receiver_session=first["session_id"], receiver_pid=receiver.process.pid)
        sequence = []
        def stream(path, model):
            if "/messages" not in path or "/count_tokens" in path or len(sequence) >= 2:
                return runner.Mock.stream(path, model)
            assert receiver.process.poll() is None and config.resolve().parent == output
            sequence.append(True); number = len(sequence)
            tool, value = (("ToolSearch",{"query":"select:SendMessage"}) if number == 1 else
                           ("SendMessage",{"to":names["receiver"],"message":MARKER + " synthetic owned-session message only."}))
            return tool_reply(tool, value, "toolu_cross_" + str(number), model)
        models["sender"].stream = stream
        sender = runner.run([exe,"-p",runner.PROMPT,"--output-format","json","--max-turns","5",
                            "--allowedTools","ToolSearch","SendMessage","--name",names["sender"],"--settings",settings],
                            profiles["sender"][2],profiles["sender"][1],timeout=90)
        report["sender"] = runner.scrub_mock_key(sender, profiles["sender"][2]["ANTHROPIC_API_KEY"])
        assert sender["exit"] == 0
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            row = receiver.pending.get(timeout=max(.1, deadline-time.monotonic()))
            if row.get("type") == "result":
                assert not row.get("is_error")
                report["receiver_message_result"] = row
                break
        assert "receiver_message_result" in report
    finally:
        if receiver is not None:
            report["receiver"] = runner.scrub_mock_key(receiver.close(), profiles["receiver"][2]["ANTHROPIC_API_KEY"])
        for model in models.values():
            model.server.shutdown(); model.server.server_close()
        report["host_proxy"] = proxy.finish()
        for name, (home, _, _) in profiles.items():
            retain_store_evidence(home, output / name)
        runner.REPO, runner.MEMORY = old_repository, old_memory
        (output / "result.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    try:
        assert report["receiver"]["exit"] == 0
        prompts = [json.loads(p.read_bytes()) for p in (output / "receiver/inputs").glob("*.json")]
        requests = [json.loads(json.loads(line)["body"]) for line in (output / "sender/requests.jsonl").read_text(encoding="utf-8").splitlines()]
        report["delivery"] = qualify_delivery(prompts, requests, report["receiver_session"], names, MARKER)
        for name, (home, _, _) in profiles.items():
            root = home / ".corthex/corthex-memory"
            rows = [json.loads(line) for p in root.glob("projects/*/raw/*.jsonl") for line in p.read_bytes().splitlines()]
            assert [v["kind"] for v in rows] == (["start","prompt","answer","end"] if name == "sender" else ["start","prompt","answer","answer","end"])
            session = rows[0]["session"]
            assert rows[0]["event"] == "start" and "text" not in rows[0] and "text" not in rows[-1]
            assert all(v["session"] == session for v in rows)
            assert rows[1]["text"] == runner.PROMPT and rows[2]["text"] == runner.REPLY and rows[1]["turn"] == rows[2]["turn"]
            if name == "receiver":
                assert session == report["receiver_session"] and rows[3]["text"] == runner.REPLY and rows[3]["turn"] != rows[2]["turn"]
            assert not any(any(mark in p.read_bytes() for mark in (MARKER.encode(), b"<cross-session-message")) for p in root.rglob("*") if p.is_file())
            capture = runner.capture(home)
            assert capture["failures_ok"] and capture["timings_ok"]
            assert sorted(capture["hook_outcomes"]["prompt"]) == (["ok"] if name == "sender" else ["left-out","ok"])
            report[name + "_capture"] = {"entries":rows,"hook_outcomes":capture["hook_outcomes"],"memory_marker_occurrences":0}
        assert all(hashlib.sha256((memory/name).read_bytes()).hexdigest() == value for name,value in originals.items() if name != "hooks/hooks.json")
        report["installed_copy"] = installed_copy(config, memory, originals)
        assert report["controller_sha256s"] == controller_hashes(), "QA controller source changed during execution"
        report.update(verified=True, native_send_succeeded=True, observed_prompt_prefixes=["<cross-session-message"],
                      prefix_filter_version="host-prompts-2", scope="Explicit inbound settings between two owned fixtures; no default-inbound or legacy-team claim")
    finally:
        (output / "result.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print("CORTHEX_CROSS_SESSION=" + json.dumps({"verified":True,"os":report["os"],"own_sessions":2,"observed":report["observed_prompt_prefixes"]}))


if __name__ == "__main__":
    main()
