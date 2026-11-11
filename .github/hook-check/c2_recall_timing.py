"""TASK-099: TC-256, the prompt hook's time with many items at release 0.3.0, timed from outside.

Usage: python c2_recall_timing.py OUTDIR [--samples N]

The package is staged at 0.3.0 as `c2_hosts.py` stages it, in a made-up home
whose demo project is a format-2 store. The project gets 1,000, then 5,000,
then 20,000 current items, written as the curator writes them, and the memory
worker's step 6 (`index_worker.keep`) builds the search index and embeds them
against a local server that answers each embedding at once; no provider is
called and the keys are made up for the run.

For each number of items and each host, the staged package's prompt hook
(`plugins/corthex-memory/scripts/hook.py`, the file that both hosts install)
runs N times (100 by default), each as the first prompt of its own session,
with the host's own input fields (`host-inputs.json`) and the environment
variable by which the hook knows that host. It runs as each host would run
it, but without the host: the hosts are not started, and the hook is not
their installed copy. Each run is timed from outside, from just before the
process is created until it has exited, so the interpreter's start is
included; the host's own launch of the command is not. TC-256 says "in each
host", so this is a partial reading of it, which the report says. The injection log
gives recall's outcome for each run: `injected` and `below` mean that recall
ranked every item; any other outcome is counted and listed.

It writes report.json and prints the median and 95th percentile by system,
host and number of items. REQ-034 holds where each 95th percentile is under
one second. It exits 1 when a run fails or recall did not rank, not when a
percentile is over the target, which the summary reports.
"""
from collections import Counter
import json
import math
import os
from pathlib import Path
import platform
import random
import secrets
import shutil
import statistics
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import c2_hosts  # noqa: E402
import run as hookcheck  # noqa: E402

SIZES = (1000, 5000, 20000)
SAMPLES = 100
TARGET_MS = 1000.0
RANKED = ("injected", "below")
READING = "partial: the staged prompt hook run directly with each host's input, not through the hosts"
VOCABULARY = ["word%04d" % number for number in range(3000)]
PROMPT = ("지난 결정을 다시 확인하고 싶습니다. Which of word0007, word0042 and word1234 did we choose "
          "for the release checks, and why?")


def percentile(values, share):
    """The nearest-rank percentile of the values."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


class Store:
    """The staged package's own library, on the made-up home's memory store."""

    def __init__(self, plugin, home):
        sys.path.insert(0, str(plugin / "skills/corthex-memory/scripts"))
        from memory_lib import base, c2_store, clock, index_worker, item_types
        self.base, self.clock, self.index_worker, self.item_types = base, clock, index_worker, item_types
        self.folder = home / ".corthex/corthex-memory"
        self.root = self.folder / "projects/demo"
        self.memory = c2_store.C2Store(self.folder)
        self.device = json.loads((self.folder / "store.json").read_text(encoding="utf-8"))["device"]
        self.items = []

    def fill(self, count, rng):
        """Add current items until the project has `count`, each quoting one made-up user entry."""
        said = self.base.utc_time()
        log = "claude-code-" + secrets.token_hex(8)
        folder = self.root / "layer/items"
        while len(self.items) < count:
            words = rng.sample(VOCABULARY, 4)
            text = "The team chose %s with %s for %s, after %s." % tuple(words)
            quote = {"entry": self.base.new_id("e"), "log": log, "device": self.device, "start": 0,
                     "end": len(text), "speaker": "user", "said": said, "words": text}
            value = {"id": self.base.new_id("i"), "kind": rng.choice(("decision", "fact", "preference")),
                     "title": "Choice of " + words[0], "text": text, "quotes": [quote], "status": "current",
                     "saved": said, "device": self.device}
            (folder / (value["id"] + ".json")).write_bytes(self.item_types.item_bytes(value))
            self.items.append(value)
        (self.root / "layer/item-list.txt").write_bytes(self.item_types.item_list_bytes(self.items))

    def embed(self):
        """Run step 6 until every item has its vector: the outcomes, in order."""
        outcomes = []
        for _ in range(20):
            deadline = self.clock.now() + 900
            with self.memory.lease(self.root / "curation.lock", "curation", deadline) as owner:
                outcome = self.index_worker.keep(self.memory, "demo", owner, deadline)
            outcomes.append({"reason": outcome.reason, "embedded": len(outcome.embedded),
                             "requests": outcome.requests, "failed": list(outcome.failed)})
            if outcome.reason == "done" and not outcome.embedded:
                return outcomes
        raise RuntimeError("the index did not settle: " + json.dumps(outcomes))


def host_input(host, demo, session):
    contract = json.loads((Path(__file__).resolve().parent / "host-inputs.json").read_text(encoding="utf-8"))
    fields = contract["hosts"][host]["events"]["UserPromptSubmit"]
    values = {"cwd": str(demo), "hook_event_name": "UserPromptSubmit", "permission_mode": "default",
              "prompt": PROMPT, "session_id": session, "transcript_path": None, "model": "gpt-fixture",
              "prompt_id": str(uuid.uuid4()), "turn_id": str(uuid.uuid4())}
    if host == "claude":
        values["transcript_path"] = str(demo / ".fixture-transcript.jsonl")
    value = {name: values[name] for name in fields}
    assert set(value) == set(fields)
    return value


def interpreter():
    """The interpreter that the hooks file names first on this system."""
    for name in (("python",) if os.name == "nt" else ("python3", "python")):
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError("python not found on PATH")


def outcomes(root, sessions):
    found = {}
    for path in (root / "injections").glob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            value = json.loads(line)
            if value.get("where") == "prompt" and value.get("session") in sessions:
                found[value["session"]] = value.get("outcome")
    return [found.get(session, "no-line") for session in sessions]


def measure(plugin, home, demo, keys, url, host, samples):
    env = hookcheck.base_env(home)
    env.update(keys)
    env.update(CORTHEX_MEMORY_ANTHROPIC_BASE_URL=url, CORTHEX_MEMORY_OPENAI_BASE_URL=url)
    if host == "claude":
        env.update(CLAUDECODE="1", CLAUDE_PLUGIN_ROOT=str(plugin))
    else:
        env.update(PLUGIN_ROOT=str(plugin))
    command = [interpreter(), str(plugin / "scripts/hook.py"), "prompt"]
    times, exits, sessions, injected = [], Counter(), [], 0
    for _ in range(samples):
        session = str(uuid.uuid4())
        data = json.dumps(host_input(host, demo, session)).encode("utf-8")
        started = time.perf_counter_ns()
        done = subprocess.run(command, input=data, env=env, cwd=str(demo), capture_output=True, timeout=60)
        times.append((time.perf_counter_ns() - started) / 1e6)
        exits[done.returncode] += 1
        sessions.append(session)
        try:
            context = json.loads(done.stdout)["hookSpecificOutput"]["additionalContext"]
        except (ValueError, KeyError, TypeError):
            context = ""
        injected += bool(context)
    found = Counter(outcomes(home / ".corthex/corthex-memory/projects/demo", sessions))
    return {"samples": samples, "median_ms": round(statistics.median(times), 1),
            "p95_ms": round(percentile(times, 0.95), 1), "max_ms": round(max(times), 1),
            "under_target": percentile(times, 0.95) < TARGET_MS, "exits": dict(exits),
            "outcomes": dict(found), "ranked": all(name in RANKED for name in found.elements()),
            "outputs_with_context": injected}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    arguments = sys.argv[1:]
    samples = SAMPLES
    if "--samples" in arguments:
        index = arguments.index("--samples")
        samples = int(arguments[index + 1])
        del arguments[index:index + 2]
    out = Path(arguments[0]).resolve() / "c2-recall-timing"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    source, plugin = c2_hosts.stage(hookcheck.REPO, out)
    hookcheck.REPO, hookcheck.MEMORY = source, plugin
    home, demo = hookcheck.prepare(out / "shared")
    c2_hosts.configure(home, 10)
    server = c2_hosts.MemoryServer()
    keys = {"CORTHEX_MEMORY_ANTHROPIC_API_KEY": "MARKERANTHROPIC" + secrets.token_hex(16),
            "CORTHEX_MEMORY_OPENAI_API_KEY": "MARKEROPENAI" + secrets.token_hex(16)}
    os.environ.update(keys, CORTHEX_MEMORY_ANTHROPIC_BASE_URL=server.url, CORTHEX_MEMORY_OPENAI_BASE_URL=server.url)
    report = {"system": platform.system(), "machine": platform.machine(), "python": platform.python_version(),
              "release": c2_hosts.RELEASE, "samples": samples, "target_ms": TARGET_MS, "reading": READING,
              "sizes": {}}
    try:
        store = Store(plugin, home)
        rng = random.Random(256)
        for size in SIZES:
            started = time.time()
            store.fill(size, rng)
            embedding = store.embed()
            row = {"fill_and_embed_seconds": round(time.time() - started, 1), "embedding": embedding}
            for host in ("claude", "codex"):
                row[host] = measure(plugin, home, demo, keys, server.url, host, samples)
            report["sizes"][str(size)] = row
    except Exception:
        import traceback
        report["crash"] = traceback.format_exc()
    finally:
        server.close()
    (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    text = ["== TC-256: the prompt hook with recall at %s, %d runs per host and size, on %s %s, Python %s ==" % (
        c2_hosts.RELEASE, samples, report["system"], report["machine"], report["python"])]
    failed = "crash" in report
    if failed:
        text.append(report["crash"])
    for size, row in report["sizes"].items():
        for host in ("claude", "codex"):
            value = row.get(host)
            if not value:
                continue
            good = value["ranked"] and set(value["exits"]) == {0}
            failed = failed or not good
            text.append("%6s items, %-6s median %7.1f ms, p95 %7.1f ms, max %7.1f ms; REQ-034 %s; outcomes %s%s" % (
                size, host, value["median_ms"], value["p95_ms"], value["max_ms"],
                "holds" if value["under_target"] else "does NOT hold", json.dumps(value["outcomes"]),
                "" if good else "; exits " + json.dumps(value["exits"])))
    text.append("TC-256: %s (%s)" % ("FAIL" if failed else "measured", READING))
    print("\n".join(text))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write("```\n%s\n```\n" % "\n".join(text))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
