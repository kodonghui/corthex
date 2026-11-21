"""TASK-047: the staged prompt hook with more time for recall, for c2_measure.py.

Usage: python c2_measure_hook.py PLUGIN SECONDS    (the hook's input on the standard input)

It runs the prompt hook of PLUGIN in this process, as PLUGIN/scripts/hook.py
runs it, with two of the package's time limits raised to SECONDS: the prompt
hook's own (0.9 s after its start) and that of the prompt's embedding request
(0.8 s after the hook's start). Nothing else of the hook changes: it reads its
input, the store, the configuration and the embedding key as the installed
hook does, writes the same injection log line and ends quietly.

c2_measure.py starts it only for a prompt whose recall ended late or failed in
the hook as it is, to get the scores that the hook would have had with a
faster network. Its time is no reading of the hook's time.
"""
import time

STARTED = time.perf_counter()  # Before the imports below, as the hook's own entry samples it.

import sys  # noqa: E402

sys.dont_write_bytecode = True  # As the hook's entry does: the staged package gets no bytecode files.
from pathlib import Path  # noqa: E402


def main():
    plugin, seconds = Path(sys.argv[1]), float(sys.argv[2])
    sys.path.insert(0, str(plugin / "skills/corthex-memory/scripts"))
    try:
        from memory_lib import hooks, prompt_recall
        hooks.SECONDS["prompt"] = seconds
        prompt_recall.EMBED_SECONDS = seconds
        hooks.run("prompt", STARTED, sys.stdin.buffer, sys.stdout.buffer)
    except Exception as error:
        sys.stderr.write("corthex-memory: " + type(error).__name__ + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
