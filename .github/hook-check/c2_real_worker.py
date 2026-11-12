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
"""
import json
from pathlib import Path
import runpy
import sys


def main():
    tap, cut, plugin = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
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
        failure = result.response.failure
        row = {"instructions": options.get("instructions"), "document": result.document,
               "answer": result.response.text, "failure": None if failure is None else failure.code,
               "attempts": result.attempts}
        with open(str(tap), "a", encoding="utf-8") as target:
            target.write(json.dumps(row, ensure_ascii=False) + "\n")
        return result

    model_client.send = written
    worker = plugin / "scripts/worker.py"
    sys.argv = [str(worker)] + sys.argv[4:]
    runpy.run_path(str(worker), run_name="__main__")


if __name__ == "__main__":
    main()
