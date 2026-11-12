"""TASK-100: the staged memory worker with its requests and answers written down, for c2_real.py.

Usage: python c2_real_worker.py TAP CUT PLUGIN --reason REASON --project NAME

It runs PLUGIN/scripts/worker.py in this process, with the arguments after
PLUGIN, once two functions of that package's library are wrapped:

- `model_client.send`, through which every curate, merge and state request
  goes: after each call one JSON line is added to TAP with the request's
  instructions, the document that was sent, the answer's text, its failure
  code and the number of attempts. No header and no key is written; the
  document is the one that the package redacted before it sent it.
- `model_request.build`, only when CUT is above zero: the request's
  `max_tokens` becomes CUT, so that the provider cuts the answer (TC-259). The
  package itself always asks for 64,000.

Nothing else of the worker changes: it reads the store, the configuration and
the keys as the installed worker does, and it ends quietly as that one does.
A line that cannot be written to TAP is left out and the answer goes on to the
worker as it came; c2_real.py then finds a request without its line.
"""
import json
from pathlib import Path
import runpy
import sys


def record(tap, instructions, result):
    """Add a request's line to TAP; whether it was written. It never raises, so the worker keeps its answer.

    A character that UTF-8 cannot hold, such as half of a surrogate pair in an answer, is written as its JSON
    escape, so the line reads back as the same value.
    """
    try:
        failure = result.response.failure
        row = {"instructions": instructions, "document": result.document, "answer": result.response.text,
               "failure": None if failure is None else failure.code, "attempts": result.attempts}
        with open(str(tap), "ab") as target:
            target.write(json.dumps(row, ensure_ascii=False).encode("utf-8", "backslashreplace") + b"\n")
    except Exception:
        return False
    return True


def main():
    tap, cut, plugin = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
    # As the worker's own first line does, before the library is loaded here: the staged package, which is what
    # was checked, gets no bytecode files beside its modules.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(plugin / "skills/corthex-memory/scripts"))
    from memory_lib import model_client, model_request
    if cut > 0:
        build = model_request.build

        def lowered(**options):
            payload, sent = build(**options)
            payload["body"]["max_tokens"] = cut
            return payload, sent

        model_request.build = lowered
    send = model_client.send

    def written(memory, **options):
        result = send(memory, **options)
        record(tap, options.get("instructions"), result)
        return result

    model_client.send = written
    worker = plugin / "scripts/worker.py"
    sys.argv = [str(worker)] + sys.argv[4:]
    runpy.run_path(str(worker), run_name="__main__")


if __name__ == "__main__":
    main()
