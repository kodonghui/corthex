"""TASK-047: the staged memory worker with every request counted and sized in writing, for c2_measure.py.

Usage: python c2_measure_worker.py TAP CHECK PLUGIN --reason REASON --project NAME

It runs PLUGIN/scripts/worker.py in this process as c2_real_worker.py does,
with that wrapper's watch of the check's process CHECK and its line of each
request in TAP. Three things differ:

- `request_budget.UNCOUNTED` is -1, so the package asks the provider for the
  token count of every request that it sizes, before it sends it. By itself it
  counts only a request whose safe estimate passes 60,000. A count costs
  nothing and has its own usage line. Nothing else of the sizing changes: a
  count above 99,000 still takes turns out of the request.
- `model_count.count` is wrapped: after each call a line of the kind `count`
  is added to TAP with the SHA-256 of the document that was counted, the count
  and the failure's code.
- A request's line has the kind `request` and also says how the package sizes
  the request: the SHA-256 of its document as the count got it, the working
  and the safe estimate of the instructions, the schema and that document, the
  numbers of ASCII and of other characters that both estimates are made of,
  the estimate as the worker gives it to the usage line, and the size that the
  worker gives with it. It also has the model, the effort and the `max_tokens`
  of the request's body as `model_request.build` made it, which is wrapped
  only to read them.

The document that is counted and sized is the one before the package's
redaction, as the package's own estimates read it; the document that the
line keeps is the one that was sent. Nothing else of the worker changes.
"""
import hashlib
import json
from pathlib import Path
import runpy
import sys

if __name__ == "__main__":
    # Before the wrapper beside this file is loaded: no bytecode files beside the checkout's modules.
    sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import c2_real_worker  # noqa: E402


def digest(text):
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def note(tap, row):
    """Add a line to TAP; whether it was written. It never raises, so the worker keeps what it was given."""
    try:
        with open(str(tap), "ab") as target:
            target.write(json.dumps(row, ensure_ascii=False).encode("utf-8", "backslashreplace") + b"\n")
    except Exception:
        return False
    return True


def sized(library, instructions, schema, source):
    """How the package sizes a request: its estimates of the instructions, the schema and the document."""
    whole = library.model_prompts.PROMPTS[instructions] + json.dumps(schema, ensure_ascii=False) + source
    plain = sum(1 for byte in whole.encode("utf-8", "surrogatepass") if byte < 128)
    return {"working": library.request_budget.working(whole), "safe": library.request_budget.safe(whole),
            "estimate": library.request_budget.estimate(instructions, schema, source),
            "ascii": plain, "other": len(whole) - plain}


def main():
    tap, check, plugin = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
    sys.dont_write_bytecode = True  # As the worker's own first line does: the staged package gets no bytecode files.
    if check > 0:
        c2_real_worker.watch(check)
    sys.path.insert(0, str(plugin / "skills/corthex-memory/scripts"))
    import memory_lib
    from memory_lib import model_client, model_count, model_prompts, model_request, request_budget  # noqa: F401
    request_budget.UNCOUNTED = -1
    count, send, build = model_count.count, model_client.send, model_request.build
    body = {}  # Of the request that was built last: a request's attempts are built one after another.

    def built(**options):
        payload, sent = build(**options)
        try:
            made = payload["body"]
            body.update(model=made.get("model"), effort=made.get("output_config", {}).get("effort"),
                        max_tokens=made.get("max_tokens"))
        except Exception:
            pass
        return payload, sent

    def counted(memory, **options):
        result = count(memory, **options)
        try:
            failure = result.failure
            note(tap, {"kind": "count", "instructions": options.get("instructions"),
                       "source_sha256": digest(options["source"]), "tokens": result.tokens,
                       "failure": None if failure is None else failure.code})
        except Exception:
            pass
        return result

    def written(memory, **options):
        result = send(memory, **options)
        more = dict(body, kind="request")
        try:
            more.update(sized(memory_lib, options["instructions"], options["schema"], options["source"]),
                        source_sha256=digest(options["source"]), size=options.get("size"))
        except Exception:
            pass
        c2_real_worker.record(tap, options.get("instructions"), result, **more)
        return result

    model_count.count, model_client.send, model_request.build = counted, written, built
    worker = plugin / "scripts/worker.py"
    sys.argv = [str(worker)] + sys.argv[4:]
    runpy.run_path(str(worker), run_name="__main__")


if __name__ == "__main__":
    main()
