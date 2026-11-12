"""TASK-100: the staged memory worker with its requests and answers written down, for c2_real.py.

Usage: python c2_real_worker.py TAP CUT CHECK PLUGIN --reason REASON --project NAME

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

CHECK is the process ID of the check that started this worker, or 0 for none.
A thread watches that process and ends this one within about a second once
it is gone. The check ends its worker itself when it is interrupted or ends
one at a timeout; the watch is for every other end of the check, such as a
kill that no process can catch. The worker has the memory keys and a session
of its own, and without the check nothing reads what it sends. On POSIX the
processes of this worker's group end with it, among them the one that holds
the request under way; on Windows that one request runs to its end. Where the
check's process cannot be watched, a line on the error output says so and the
worker runs on.

Nothing else of the worker changes: it reads the store, the configuration and
the keys as the installed worker does, and it ends quietly as that one does.
A line that cannot be written to TAP is left out and the answer goes on to the
worker as it came; c2_real.py then finds a request without its line.
"""
import json
import os
from pathlib import Path
import runpy
import signal
import sys
import threading
import time

WATCH_SECONDS = 0.5  # How often the watch looks, where it cannot wait for the check's end itself.


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


def gone(check):
    """Wait until the process with the ID `check` is gone. An OSError says that it cannot be watched.

    On POSIX the check is this process's parent: when it ends, also before anything has collected it, another
    process becomes the parent. Where something stands between the two, the check's ID is looked up as well. A
    check that ended before this function's first look is found only by its ID, so once something has collected
    it. On Windows a parent's ID stays the same after its end, so the process itself is opened and waited for.
    """
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        handle = kernel.OpenProcess(0x00100000, False, check)  # SYNCHRONIZE, which is enough to wait for its end.
        if not handle:
            if ctypes.get_last_error() == 87:  # ERROR_INVALID_PARAMETER: no process has that ID any more.
                return
            raise ctypes.WinError(ctypes.get_last_error())
        if kernel.WaitForSingleObject(handle, 0xFFFFFFFF) != 0:  # Without a time limit; 0 says that it ended.
            raise ctypes.WinError(ctypes.get_last_error())
        return
    parent = os.getppid()
    while os.getppid() == parent:
        try:
            os.kill(check, 0)  # Signal 0 sends nothing: it only asks whether the process is there.
        except ProcessLookupError:
            return
        except OSError:
            pass  # It is there and not this user's to signal.
        time.sleep(WATCH_SECONDS)


def end():
    """End this process at once, on POSIX with the processes of the group that it leads."""
    if os.name != "nt" and os.getpgrp() == os.getpid():
        os.killpg(os.getpid(), signal.SIGKILL)
    os._exit(1)


def watch(check):
    """Start the thread that ends this process once the check's process is gone."""
    def watching():
        try:
            gone(check)
        except Exception as error:
            try:
                sys.stderr.write("c2_real_worker: the check's process %d cannot be watched (%s), so this worker "
                                 "runs to its own end\n" % (check, error))
            except Exception:
                pass
            return
        end()

    threading.Thread(target=watching, name="check-watch", daemon=True).start()


def main():
    tap, cut, check, plugin = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4])
    # As the worker's own first line does, before the library is loaded here: the staged package, which is what
    # was checked, gets no bytecode files beside its modules.
    sys.dont_write_bytecode = True
    if check > 0:
        watch(check)
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
    sys.argv = [str(worker)] + sys.argv[5:]
    runpy.run_path(str(worker), run_name="__main__")


if __name__ == "__main__":
    main()
