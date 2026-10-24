"""Hook used by the Windows hook check: records which processes ran it and adds a marker to the context."""

import base64
import json
import os
import subprocess
import sys

KEYS = ("CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT", "CLAUDE_PROJECT_DIR", "MSYSTEM", "SHELL", "CLAUDE_CODE_GIT_BASH_PATH")

# Walks up from the process that started this one and prints id, name and command line of each.
PARENTS = (
    "$p = {pid}; for ($i = 0; $i -lt 4; $i++) {{ "
    "$x = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $p); if (-not $x) {{ break }}; "
    "'{{0}}|{{1}}|{{2}}' -f $x.ProcessId, $x.Name, $x.CommandLine; $p = $x.ParentProcessId }}"
)


def parents():
    script = PARENTS.format(pid=os.getppid())
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return [{"error": str(error)}]
    rows = []
    for line in result.stdout.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            rows.append({"pid": parts[0], "name": parts[1], "cmdline": parts[2][:1000]})
    return rows


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "none"
    try:
        event = json.load(sys.stdin)
    except ValueError:
        event = {}
    record = {
        "tag": tag,
        "script": sys.argv[0],
        "event": event.get("hook_event_name"),
        "source": event.get("source"),
        "env": {key: os.environ.get(key) for key in KEYS},
        "parents": parents(),
    }
    folder = os.environ.get("HOOKCHECK_LOG")
    if folder:
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "%s-%d.json" % (tag, os.getpid())), "w", encoding="utf-8") as handle:
            json.dump(record, handle)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "HOOKDIAG-" + tag}}))


main()
