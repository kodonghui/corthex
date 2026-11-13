"""TASK-047: the staged memory worker with every request counted and sized in writing, for c2_measure.py.

Usage: python c2_measure_worker.py TAP CHECK PLUGIN --reason REASON --project NAME

It runs PLUGIN/scripts/worker.py in this process as c2_real_worker.py does,
with that wrapper's watch of the check's process CHECK and its line of each
request in TAP. These things differ:

- `request_budget.UNCOUNTED` is -1, so the package asks the provider for the
  token count of every request that it sizes, before it sends it. By itself it
  counts only a request whose safe estimate passes 60,000. A count costs
  nothing and has its own usage line. Nothing else of the sizing changes: a
  count above 99,000 still takes turns out of the request.
- `model_count.count` is wrapped: after each call a line of the kind `count`
  is added to TAP with the SHA-256 of the document that was counted, the count
  and the failure's code.
- `request_budget.plan` and `request_budget.merge_part`, which size a curate
  and a merge request, are wrapped only to read what they made: for each
  request a line of the kind `sized` says, by the SHA-256 of its document,
  which count let it go and how many counts its sizing took, and for one part
  of a turn which part of how many it is. A part is counted while the parts
  have a provisional number, so that count's document is a few characters
  longer than the part that goes, and only this line says which count was the
  part's.
- A request's line has the kind `request` and also says how the package sizes
  the request: the SHA-256 of its document as the count got it, the working
  and the safe estimate of the instructions, the schema and that document, the
  numbers of ASCII and of other characters that both estimates are made of,
  the estimate as the worker gives it to the usage line, and the size that the
  worker gives with it. It also has the model, the effort and the `max_tokens`
  of the request's body as `model_request.build` made it, which is wrapped
  only to read them; the times, as the package writes a time, right before and
  right after the call of `send`, between which each attempt of the request
  began; and how many usage lines the call says that it wrote. A call that
  raised an error has a line too, with the error's name in `raised` and
  neither a document nor an answer: it may have logged an attempt before.
- `index_worker.keep`, the worker's index step, is wrapped only to read how it
  ended: a line of the kind `index` has its reason, why the index was built
  again if it was, how many rows it wrote and removed, how many items got a
  vector, how many embedding requests it sent and the failed ones' codes.

The document that is counted and sized is the one before the package's
redaction, as the package's own estimates read it; the document that the
line keeps is the one that was sent. Nothing else of the worker changes, and
no line that cannot be written changes it either.
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


def sized(library, instructions, schema, source):
    """How the package sizes a request: its estimates of the instructions, the schema and the document."""
    whole = library.model_prompts.PROMPTS[instructions] + json.dumps(schema, ensure_ascii=False) + source
    plain = sum(1 for byte in whole.encode("utf-8", "surrogatepass") if byte < 128)
    return {"working": library.request_budget.working(whole), "safe": library.request_budget.safe(whole),
            "estimate": library.request_budget.estimate(instructions, schema, source),
            "ascii": plain, "other": len(whole) - plain}


def wrap(library, tap):
    """Wrap the functions of the staged library through which the worker counts, sizes and sends its requests and
    keeps its index, so that each adds its line to TAP, and make the package count every request that it sizes.

    A wrapper gives back what the function gave, or raises what it raised. Nothing that goes wrong while a line is
    made or written changes that.
    """
    budget, write = library.request_budget, c2_real_worker.write
    count, send, build = library.model_count.count, library.model_client.send, library.model_request.build
    plan, merge_part, keep = budget.plan, budget.merge_part, library.index_worker.keep
    body = {}  # Of the request built last in the call of `send` under way: its attempts are built one after another.

    def moment():
        try:
            return library.base.utc_time()
        except Exception:
            return None

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
            write(tap, {"kind": "count", "instructions": options.get("instructions"),
                        "source_sha256": digest(options["source"]), "tokens": result.tokens,
                        "failure": None if failure is None else failure.code})
        except Exception:
            pass
        return result

    def sizing(instructions, made):
        try:
            part = getattr(made, "part", None)
            write(tap, {"kind": "sized", "instructions": instructions, "source_sha256": digest(made.source),
                        "counted": made.counted, "counts": made.counts, "part": None if part is None else list(part)})
        except Exception:
            pass

    def planned(*arguments, **options):
        made = plan(*arguments, **options)
        try:
            for request in made.requests:
                sizing(options.get("instructions", library.model_prompts.CURATE), request)
        except Exception:
            pass
        return made

    def merged(*arguments, **options):
        made = merge_part(*arguments, **options)
        sizing(library.model_prompts.MERGE, made)
        return made

    def written(memory, **options):
        body.clear()
        more = {"kind": "request", "began": moment()}

        def ended():
            try:
                more.update(body, ended=moment())
                more.update(sized(library, options["instructions"], options["schema"], options["source"]),
                            source_sha256=digest(options["source"]), size=options.get("size"))
            except Exception:
                pass

        try:
            result = send(memory, **options)
        except BaseException as error:
            ended()
            write(tap, dict(more, instructions=options.get("instructions"), raised=type(error).__name__))
            raise
        ended()
        c2_real_worker.record(tap, options.get("instructions"), result, logged=getattr(result, "logged", None),
                              **more)
        return result

    def kept(*arguments, **options):
        try:
            outcome = keep(*arguments, **options)
        except BaseException as error:
            write(tap, {"kind": "index", "raised": type(error).__name__})
            raise
        try:
            write(tap, {"kind": "index", "reason": outcome.reason, "rebuilt": outcome.rebuilt,
                        "written": len(outcome.written), "removed": len(outcome.removed),
                        "embedded": len(outcome.embedded), "requests": outcome.requests,
                        "failed": list(outcome.failed)})
        except Exception:
            pass
        return outcome

    budget.UNCOUNTED = -1
    library.model_count.count, library.model_client.send, library.model_request.build = counted, written, built
    budget.plan, budget.merge_part, library.index_worker.keep = planned, merged, kept


def main():
    tap, check, plugin = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
    sys.dont_write_bytecode = True  # As the worker's own first line does: the staged package gets no bytecode files.
    if check > 0:
        c2_real_worker.watch(check)
    sys.path.insert(0, str(plugin / "skills/corthex-memory/scripts"))
    import memory_lib
    from memory_lib import (base, index_worker, model_client, model_count, model_prompts,  # noqa: F401
                            model_request, request_budget)
    wrap(memory_lib, tap)
    worker = plugin / "scripts/worker.py"
    sys.argv = [str(worker)] + sys.argv[4:]
    runpy.run_path(str(worker), run_name="__main__")


if __name__ == "__main__":
    main()
