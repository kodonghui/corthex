"""Observe real host hooks; pace prompts using the declared lifecycle helper."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


def main():
    hook = sys.argv[1]
    assert hook in ("start", "prompt", "end-of-turn", "end")
    incoming = sys.stdin.buffer.read()
    event = json.loads(incoming)
    started = time.monotonic_ns()
    target = "lifecycle_prompt.py" if hook in ("start", "prompt") else "hook.py"
    child = subprocess.Popen([sys.executable, "-I", str(Path(__file__).with_name(target)), hook],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = child.communicate(incoming)
    value = {"hook": hook, "input": event, "stdout": stdout.decode("utf-8", "replace"),
             "stderr": stderr.decode("utf-8", "replace"), "exit": child.returncode,
             "child_pid": child.pid, "started_ns": started, "ended_ns": time.monotonic_ns()}
    output = Path(os.environ["HOOKCHECK_WALK_OBSERVATIONS"])
    output.mkdir(parents=True, exist_ok=True)
    temporary = output / (uuid.uuid4().hex + ".tmp")
    temporary.write_bytes((json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8"))
    temporary.replace(temporary.with_suffix(".json"))
    sys.stdout.buffer.write(stdout)
    sys.stderr.buffer.write(stderr)
    raise SystemExit(child.returncode)


if __name__ == "__main__":
    main()
