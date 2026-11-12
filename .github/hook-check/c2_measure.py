"""TASK-047: measurements of MEMORY on redacted real conversations, with the maintainer's memory keys.

Usage: python c2_measure.py OUTDIR [--samples DIR] [--sample ID]... [--prompts FILE]
                             [--part efforts|skip|recall]... [--effort LEVEL]... [--dims N]...
                             [--repeat N] [--limit USD] [--self-test]

The numbers for stage 12's TC-250 and TC-251, the share of prompts that
`recall.skip` skips, and the scores that TASK-048 judges. The runs cost money
and their answers vary, so this check runs by hand and never in CI, as
`c2_real.py` does, whose parts it is made of: the package is staged at 0.3.0,
each run gets a made-up home with a demo project whose memory is on, the turns
are recorded by the staged hooks with each host's own input fields, and the
staged worker runs in the foreground with the memory keys of this process's
environment. Without CORTHEX_MEMORY_ANTHROPIC_API_KEY the check says so and
ends, and it refuses when CI or GITHUB_ACTIONS is set.

The samples are real conversations that were picked and redacted before this
script gets them; it redacts nothing and changes no sample. DIR holds one
file <id>.json for each: `{"id", "kind", "source", "turns": [{"host", "prompt",
"reply"}]}`, where `host` is `claude` or `codex` and each turn is a prompt as
it was submitted with the last answer of its turn. `--sample` names the
samples to take, in that order; without it every sample of DIR is taken, by
file name. FILE is a JSON list of prompts that a person typed, each
`{"text"[, "source"]}`. Neither the samples nor the prompts belong in a public
repository, and neither does OUTDIR.

The parts, of which `efforts`, and `skip` when FILE is given, run unless
`--part` names others:

- efforts: each sample is recorded in a home of its own and curated at each
  `--effort` (medium, high and xhigh unless given; `models.effort`), `--repeat`
  times. The worker runs through `c2_measure_worker.py`, which makes the
  package ask the provider for the token count of every request that it
  sizes, at no cost, and writes down how the package's two estimates read the
  request. For each request the report gives the working and the safe
  estimate, the numbers of ASCII and other characters that they are made of,
  the count, the input and output tokens that the provider billed, its times,
  its cost by the usage log, and what the answer asks for by action and kind;
  for each run, the items and state lines that it left. This part's worker
  gets no embedding key, so it sends no embedding.
- skip: for each prompt of FILE, whether the staged package's own
  `recall.skipped` skips it at the default of `recall.skip`, by the prompt's
  language (ko with a Hangul letter, en with Latin letters and none, else
  none) and source; how many each other value of `recall.skip` would skip,
  and how many a count would in which a Hangul syllable is 2.
- recall: the samples are replayed in their order in one home. Before a
  sample is recorded, each of its prompts is given to the staged prompt hook
  as the first prompt of a new session, with the embedding key, at each
  `--dims` (512 and 1536 unless given; `models.dims`), so a prompt is only
  ever ranked against items that earlier samples left. `recall.threshold` is
  2, the highest that the configuration takes: nothing is injected, and the
  injection log's line of each ranked prompt names its five best items with
  their scores. The prompt is left out of recording for these runs
  (`left_out.kinds`), and recorded with its answer afterwards. Then the
  sample is curated at the default effort and its items are embedded. The
  hook's time is taken from outside, from before its process is created until
  it has ended. A prompt whose recall ended late or failed is given once more
  to `c2_measure_hook.py`, the same hook with 30 seconds: its scores are
  recorded as such and its time is not. Between two lengths every item is
  embedded again, which the report counts. It needs
  CORTHEX_MEMORY_OPENAI_API_KEY, and stops where an embedding of the items
  fails.

report.json holds numbers, the names of settings and the IDs that the package
made: no text of a sample, of a prompt, of an item or of an answer. Those stay
under OUTDIR/c2-measure, in each home's store and `requests.jsonl` and, for
the recall part, in recall-texts.json, which lists each prompt that was asked
and each candidate item's kind, title and text for the judging. A judgement of
what a run made is an agent's reading of those files and is no part of this
script.

Before each run the cost so far, by the usage log's lines, is compared with
`--limit` (1 USD unless given); once it is reached no run starts. A run that
has begun is finished. The report is written when the check begins, before
each run and at its end, and an interrupt ends the worker that is running, as
in `c2_real.py`. A folder OUTDIR/c2-measure that is there already is replaced
only when it is empty or its report says that it was a self-test's.

`--self-test` is for the tests: the samples and prompts are made up in this
file unless DIR or FILE is given, a local server stands in for both providers
with made-up keys, its answers are scripted and its count is a number made
from the request's size. It shows that this script and the package run on a
system, and nothing about a provider, a model or an estimate.

It prints a summary and exits 1 when a run broke, was not made or left a
request without its count or its usage line, when a memory key of this
process's environment is in a file under the folder, in the report or in a
request to the local server, or when a file there could not be read for that
search. Whether the safe estimate is at or above each count is a reading that
the report gives; it does not change the exit.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import traceback
import unicodedata
import uuid

if __name__ == "__main__":
    # Before the modules below are loaded: started as a script, this check leaves no bytecode files beside the
    # checkout's modules, nor beside those of the staged package, whose library its readings load.
    sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import c2_hosts  # noqa: E402
import c2_real  # noqa: E402
import run as hookcheck  # noqa: E402

# Whole paths: before Python 3.9 a script's `__file__` is the path as it was typed, and both run elsewhere.
WORKER = Path(__file__).resolve().with_name("c2_measure_worker.py")
HOOK = Path(__file__).resolve().with_name("c2_measure_hook.py")
PARTS = ("efforts", "skip", "recall")
EFFORTS = ("low", "medium", "high", "xhigh", "max")  # What `models.effort` takes.
MEASURED = ("medium", "high", "xhigh")               # TC-251's efforts.
LENGTHS = (512, 1536)                                # TC-251's vector lengths.
SHORTEST, LONGEST = 64, 3072                         # What `models.dims` takes.
THRESHOLD = 2       # The highest `recall.threshold`: above any score, so every ranked prompt's line has candidates.
MORE_SECONDS = 30   # The time of the hook that is asked again for a prompt whose recall ended late or failed.
AGAIN = ("late", "failed", "no-line")
RUNS = 3            # Runs of the worker for the turns that one sample leaves waiting.
REBUILDS = 5        # Runs of the worker until the index has every item at a new length.
SKIPS = (2, 4, 6, 8, 10, 12, 16)
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}\Z")
KOREAN = re.compile("[가-힣ᄀ-ᇿㄱ-ㆎ]")
LATIN = re.compile("[A-Za-z]")

# The samples and the prompts of a self-test, made up here, with what the scripted curator makes of each prompt.
MADE_UP = (
    {"id": "made-up-ko", "kind": "made-up", "source": "this file", "turns": [
        {"host": "claude", "prompt": "결정: 측정 보고서에는 숫자와 ID만 둡니다.",
         "reply": "네, 측정 보고서에는 숫자와 ID만 두겠습니다."},
        {"host": "codex", "prompt": "결정: 샘플 원문은 비공개 폴더에만 둡니다.",
         "reply": "네, 샘플 원문은 비공개 폴더에만 두겠습니다."}]},
    {"id": "made-up-en", "kind": "made-up", "source": "this file", "turns": [
        {"host": "claude", "prompt": "Decision: a measurement run keeps its numbers in report.json only.",
         "reply": "Understood. A measurement run keeps its numbers in report.json only."}]},
)
SCRIPTS = {
    MADE_UP[0]["turns"][0]["prompt"]: c2_real.script("decision", "측정 보고서에는 숫자와 ID만",
                                                     "측정 보고서에는 숫자와 ID만 둔다.", part="decisions"),
    MADE_UP[0]["turns"][1]["prompt"]: c2_real.script("decision", "샘플 원문은 비공개 폴더에만",
                                                     "샘플 원문은 비공개 폴더에만 둔다.", part="decisions"),
    MADE_UP[1]["turns"][0]["prompt"]: c2_real.script("decision", "A run's numbers stay in report.json",
                                                     "A measurement run keeps its numbers in report.json only."),
}
MADE_UP_PROMPTS = tuple({"source": "made up", "text": text} for text in (
    "응", "ㅇㅋ 진행", "그건 왜 그런지 설명해 줘", "측정 결과를 표로 정리해 줘", "ok", "go on",
    "Which file holds the numbers of a run?", "/status", "1234"))


def language(text):
    """ko for a text with a Hangul letter, en for one with Latin letters and no Hangul, else none."""
    if KOREAN.search(text):
        return "ko"
    return "en" if LATIN.search(text) else "none"


def counted(text):
    """A prompt's characters as recall counts them: trimmed, in NFC."""
    return unicodedata.normalize("NFC", text).strip()


def spread(values, digits=3):
    """The least, the median and the greatest of some numbers, or None without any."""
    values = [value for value in values if value is not None]
    if not values:
        return None
    return {"min": round(min(values), digits), "median": round(statistics.median(values), digits),
            "max": round(max(values), digits), "values": len(values)}


def percentile(values, share):
    """The nearest-rank percentile of the values."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def valid(value, name):
    """A sample as its file gives it, or a ValueError that names the file and never a text of it."""
    def wrong(why):
        return ValueError("%s is no sample: %s" % (name, why))

    if not isinstance(value, dict) or not isinstance(value.get("turns"), list) or not value["turns"]:
        raise wrong("it has no list of turns")
    if not isinstance(value.get("id"), str) or not NAME.match(value["id"]):
        raise wrong("its id is not lower-case letters, digits and hyphens, 40 at most")
    for key in ("kind", "source"):
        if not isinstance(value.get(key), str) or not value[key] or len(value[key]) > 40:
            raise wrong("its %s is not a text of 40 characters at most" % key)
    for number, turn in enumerate(value["turns"], 1):
        if not isinstance(turn, dict) or turn.get("host") not in c2_hosts.HOST_NAMES:
            raise wrong("turn %d names no host that is claude or codex" % number)
        for key in ("prompt", "reply"):
            if not isinstance(turn.get(key), str) or not turn[key].strip():
                raise wrong("turn %d has no %s" % (number, key))
    return {"id": value["id"], "kind": value["kind"], "source": value["source"],
            "turns": [{key: turn[key] for key in ("host", "prompt", "reply")} for turn in value["turns"]]}


def samples_of(folder, names):
    """The samples of a folder: those named, in that order, or all by file name."""
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError("--samples: %s is no folder" % folder)
    paths = [folder / (name + ".json") for name in names] if names else sorted(folder.glob("*.json"))
    found = []
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError("%s cannot be read as JSON: %s" % (path.name, type(error).__name__))
        sample = valid(value, path.name)
        if sample["id"] != path.stem:
            raise ValueError("%s is no sample: its id is not its file's name" % path.name)
        found.append(sample)
    if not found:
        raise ValueError("--samples: %s holds no sample" % folder)
    return found


def prompts_of(path):
    """The prompts of a file: a JSON list of `{"text"[, "source"]}`."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("--prompts: the file cannot be read as JSON: %s" % type(error).__name__)
    if not isinstance(value, list) or not value or not all(
            isinstance(row, dict) and isinstance(row.get("text"), str) and
            isinstance(row.get("source", ""), str) and len(row.get("source", "")) <= 40 for row in value):
        raise ValueError("--prompts: the file is no list of prompts, each with a text")
    return [{"source": row.get("source") or "not given", "text": row["text"]} for row in value]


def sizes(sample):
    """A sample in numbers."""
    prompts = "".join(turn["prompt"] for turn in sample["turns"])
    replies = "".join(turn["reply"] for turn in sample["turns"])
    letters = [character for character in prompts + replies if character.isalpha()]
    return {"kind": sample["kind"], "source": sample["source"], "turns": len(sample["turns"]),
            "hosts": dict(Counter(turn["host"] for turn in sample["turns"])),
            "prompt_characters": len(prompts), "reply_characters": len(replies),
            "hangul_share_of_letters": round(sum(1 for character in letters if KOREAN.match(character)) /
                                             max(1, len(letters)), 2)}


class Counting(c2_real.Scripted):
    """The local server of a self-test: the made-up samples' scripted answers, and a count for each count request.

    The count is made from the request's size and says nothing about a text. The server also notes the effort
    that each model request asked for.
    """

    def __init__(self):
        super().__init__([c2_real.Turn(turn["host"], turn["prompt"], turn["reply"], SCRIPTS.get(turn["prompt"]))
                          for sample in MADE_UP for turn in sample["turns"]])
        self.efforts = []

    def count(self, value):
        return 500 + len(json.dumps(value, ensure_ascii=False).encode("utf-8")) // 3

    def answer(self, value):
        self.efforts.append((value.get("output_config") or {}).get("effort"))
        return super().answer(value)


class Home(c2_real.Home):
    """A made-up home whose worker runs through c2_measure_worker.py; every run of it is kept in `made`."""

    def __init__(self, check, label):
        super().__init__(check, label)
        self.made = []

    def wrapper(self, cut):
        # This check cuts no answer short, so its wrapper takes no `cut`.
        return [sys.executable, str(WORKER), str(self.tap), str(os.getpid()), str(self.check.plugin)]

    def work(self, provider=True, cut=0):
        run = super().work(provider, cut)
        self.made.append(run)
        return run

    def setting(self, section, name, value):
        document = self.configuration()
        document.setdefault(section, {})[name] = value
        self.configure(document)

    def leave_out(self, kinds):
        """Leave these kinds of entries out of recording for the demo project; none records all again."""
        document = self.configuration()
        if kinds:
            document["projects"]["demo"]["left_out"] = {"kinds": list(kinds)}
        else:
            document["projects"]["demo"].pop("left_out", None)
        self.configure(document)

    def take(self, sample):
        """Record a sample's turns through the staged hooks, in sessions of their own."""
        self.sessions = {}
        for turn in sample["turns"]:
            self.turn(c2_real.Turn(turn["host"], turn["prompt"], turn["reply"], None))

    def curate(self):
        """Run the worker until no turn waits, RUNS times at most; those runs."""
        start = len(self.made)
        while len(self.made) - start < RUNS:
            self.work()
            if not self.layer()["waiting"]:
                break
        return self.made[start:]

    def current(self):
        """The layer's current items, by ID."""
        return {ident: value for ident, value in c2_hosts.items(self.home).items() if value["status"] == "current"}

    def vectors(self, dims):
        """Give the index vectors of `dims` numbers: None when it has them, else what the rebuilding runs logged."""
        models = self.configuration().get("models", {})
        if models.get("dims", self.check.defaults["dims"]) == dims:
            return None
        self.setting("models", "dims", dims)
        lines, runs = [], 0
        while runs < REBUILDS:
            run = self.work()
            runs += 1
            made = [row for row in run["usage"] if row.get("call") == "embed-items"]
            lines += made
            if not made:  # A run that embedded nothing: the index has every item.
                break
        return embedded(lines, dims=dims, worker_runs=runs)

    def ask(self, host, prompt, seconds=None):
        """Give a prompt to the staged prompt hook as the first of a new session; its time, outcome and candidates.

        With `seconds` the hook runs through c2_measure_hook.py, with that much time.
        """
        check = self.check
        session = str(uuid.uuid4())
        data = json.dumps(c2_real.host_input(host, "UserPromptSubmit", self.demo, session, str(uuid.uuid4()),
                                             prompt=prompt), ensure_ascii=False)
        command = [sys.executable, str(check.plugin / "scripts/hook.py"), "prompt"]
        if seconds is not None:
            command = [sys.executable, str(HOOK), str(check.plugin), str(seconds)]
        done = hookcheck.run(command, check.recall_environment(self.home, host), str(self.demo), stdin=data,
                             timeout=120)
        logged = {}
        self.logged(logged, True)
        if done["exit"] != 0:
            raise RuntimeError("the prompt hook %s" % c2_real.how_ended(done, check.shown))
        lines = [value for _, value in c2_hosts.injection_lines(self.root)
                 if value.get("session") == session and value.get("where") == "prompt"]
        line = lines[-1] if lines else {}
        sent = [row for row in logged["usage"] if row.get("call") == "embed-prompt"]
        return {"ms": round((done["ended_monotonic_ns"] - done["started_monotonic_ns"]) / 1e6, 1),
                "outcome": line.get("outcome", "no-line"), "items": len(line.get("items") or []),
                "candidates": [{"item": value["item"], "score": value["score"]}
                               for value in line.get("candidates") or []],
                "embed_ms": sent[-1].get("total_ms") if sent else None,
                "embed_result": sent[-1].get("result") if sent else None,
                "embed_error": sent[-1].get("error") if sent else None}

    def recalled(self, host, prompt):
        """A prompt's recall in the hook as it is and, when that ended late or failed, once more with more time."""
        first = self.ask(host, prompt)
        found = {"outcome": first["outcome"], "ms": first["ms"], "embed_ms": first["embed_ms"],
                 "scored": "in the hook's time", "candidates": first["candidates"]}
        if first["embed_error"]:
            found["embed_error"] = first["embed_error"]
        if first["outcome"] in AGAIN:
            again = self.ask(host, prompt, MORE_SECONDS)
            found.update(scored="with %d seconds" % MORE_SECONDS, outcome_with_more_time=again["outcome"],
                         candidates=again["candidates"])
        return found


def embedded(lines, **more):
    """Item embedding requests by their usage lines. A failed one stops the part: recall then has no index."""
    failed = sorted({str(row.get("error")) for row in lines if row.get("result") != "ok"})
    if failed:
        raise c2_real.Stopped("an embedding of the items failed (%s), so recall has no index to rank" %
                              ", ".join(failed))
    found = dict(more)
    found.update(requests=len(lines), input=sum(row.get("input") or 0 for row in lines),
                 usd=round(sum(row.get("cost") or 0 for row in lines), 6),
                 ms=sum(row.get("total_ms") or 0 for row in lines))
    return found


def answered(row):
    """What a request's answer asks for, in numbers: its changes by action and kind, its line edits, its merges."""
    try:
        answer = json.loads(row.get("answer") or "")
    except ValueError:
        return {"answer": "no JSON"}
    if not isinstance(answer, dict):
        return {"answer": "no object"}
    found = {}
    if isinstance(answer.get("changes"), list):
        found["changes"] = dict(Counter("%s %s" % (change.get("action"), change.get("kind"))
                                        for change in answer["changes"] if isinstance(change, dict)))
    if isinstance(answer.get("state"), dict):
        found["state"] = {name: len(value) for name, value in answer["state"].items() if isinstance(value, list)}
    for name in ("merges", "conflicts"):
        if isinstance(answer.get(name), list):
            found[name] = len(answer[name])
    return found


def joined(rows, usage):
    """A home's written requests, each with the count of its document and its usage lines, in numbers and names.

    `rows` are the lines of requests.jsonl and `usage` those of the usage log, both in the order in which they
    were written. The package logs each attempt of a request as a line of its own, so a request takes as many
    lines of its instructions as it had attempts, and its last line is the one of its answer.
    """
    counts, lines = {}, {}
    for row in rows:
        if row.get("kind") == "count":
            counts.setdefault(row.get("source_sha256"), []).append(row)
    for row in usage:
        if row.get("call") in ("curate", "consolidate"):
            lines.setdefault(row.get("instructions"), []).append(row)
    found = []
    for row in rows:
        if row.get("kind") != "request":
            continue
        made = counts.get(row.get("source_sha256"), [])
        tokens = next((value["tokens"] for value in reversed(made) if value.get("tokens") is not None), None)
        waiting = lines.get(row.get("instructions"), [])
        attempts = [waiting.pop(0) for _ in range(min(row.get("attempts") or 0, len(waiting)))]
        last = attempts[-1] if attempts else {}
        entry = {"instructions": row.get("instructions"), "model": row.get("model"), "effort": row.get("effort"),
                 "attempts": row.get("attempts"), "failure": row.get("failure"),
                 "document_bytes": c2_real.size(row.get("document") or ""),
                 "answer_bytes": c2_real.size(row.get("answer") or ""),
                 "source_sha256": row.get("source_sha256"), "ascii": row.get("ascii"), "other": row.get("other"),
                 "working": row.get("working"), "safe": row.get("safe"),
                 "count": tokens, "count_calls": len(made),
                 "count_failures": [value["failure"] for value in made if value.get("failure")],
                 "usage_lines": len(attempts), "result": last.get("result"), "error": last.get("error"),
                 "input": sum(last.get(name) or 0 for name in ("input", "cache_write", "cache_read"))
                 if attempts else None,
                 "output": last.get("output"), "first_ms": last.get("first_ms"), "total_ms": last.get("total_ms"),
                 "usd": round(sum(value.get("cost") or 0 for value in attempts), 6),
                 "list": last.get("list"), "turns": last.get("turns"),
                 # The usage line's estimate is the working estimate that the wrapper computed again.
                 "estimate_agrees": bool(attempts) and last.get("estimate") == row.get("estimate") == row.get("working")}
        if tokens and row.get("safe") is not None:
            entry.update(safe_at_or_above_count=row["safe"] >= tokens,
                         safe_over_count=round(row["safe"] / tokens, 3),
                         working_over_count=round(row["working"] / tokens, 3))
        entry.update(answered(row))
        found.append(entry)
    return found


def made(layer):
    """What a layer holds, in numbers."""
    items, lines = list(layer["items"].values()), layer["lines"]
    current = [value for value in items if value["status"] == "current"]
    return {"items": len(items), "items_by_status": dict(Counter(value["status"] for value in items)),
            "current_items_by_kind": dict(Counter(value["kind"] for value in current)),
            "current_items_with_korean_text": sum(1 for value in current
                                                  if KOREAN.search(value["title"] + value["text"])),
            "current_item_bytes": sum(c2_real.size(value["title"]) + c2_real.size(value["text"])
                                      for value in current),
            "quotes": sum(len(value["quotes"]) for value in current),
            "state_lines": len(lines), "state_lines_by_part": dict(Counter(line["part"] for line in lines)),
            "state_lines_with_korean_text": sum(1 for line in lines if KOREAN.search(line["text"])),
            "state_line_bytes": sum(c2_real.size(line["text"]) for line in lines),
            "open_conflict_candidates": sum(1 for value in layer["candidates"] if value.get("status") == "open"),
            "turns_left_to_curate": layer["waiting"]}


def results(usage):
    """The usage lines by call and how each ended."""
    found = {}
    for row in usage:
        ended = row.get("result") if row.get("result") != "failed" else "failed: %s" % row.get("error")
        found.setdefault(row.get("call"), Counter())[ended] += 1
    return {call: dict(value) for call, value in found.items()}


def moment():
    """The time now as the package writes a time."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def attempts(record, since=None):
    """The curation record's latest attempts, the newest first, in the package's own names and numbers: how each
    ended, how many changes it applied and dropped, and why it dropped changes and line edits. `since` leaves
    out those before a time."""
    return [{key: value[key] for key in ("kind", "result", "error", "applied", "dropped", "reasons",
                                         "edit_reasons", "state") if key in value}
            for value in record.get("recent") or [] if since is None or value.get("at", "") >= since]


def reading(home, runs, since=None):
    """Some runs of a home's worker in numbers: each request with its estimates, its count and its usage line,
    what the usage and failure logs and the curation record say of the runs, and the layer as it is now."""
    usage = [row for run in runs for row in run["usage"]]
    found = {"worker_runs": len(runs), "seconds": round(sum(run.get("seconds") or 0 for run in runs), 1),
             "requests": joined([row for run in runs for row in run["requests"]], usage),
             "usage": results(usage), "usd": round(sum(row.get("cost") or 0 for row in usage), 6),
             "failures": [{key: row.get(key) for key in ("hook", "step", "error") if row.get(key) is not None}
                          for run in runs for row in run["failures"]],
             "attempts": attempts(home.record(), since), "layer": made(home.layer())}
    broken = Counter()
    for run in runs:
        broken.update(run.get("lines left out because they are no JSON") or {})
    if any(broken.values()):
        found["lines_left_out_because_they_are_no_json"] = dict(broken)
    return found


def lacking(found):
    """Why a reading is not whole, as a list; empty when every request has its count and an `ok` usage line."""
    why = []
    if not found["requests"]:
        why.append("no request was written")
    for number, row in enumerate(found["requests"], 1):
        if row["count"] is None:
            why.append("request %d has no count" % number)
        if row["result"] != "ok":
            why.append("request %d ended with %s" % (number, row["result"] or "no usage line"))
        if not row["estimate_agrees"]:
            why.append("request %d: the usage line's estimate is not the one that was computed again" % number)
    if found["layer"]["turns_left_to_curate"]:
        why.append("%d turns are left to curate" % found["layer"]["turns_left_to_curate"])
    if found.get("lines_left_out_because_they_are_no_json"):
        why.append("a log has lines that are no JSON")
    return why


def measured(check, entry, sample, level, label):
    """One sample curated at one effort, in a home of its own."""
    home = check.home(label)
    home.setting("models", "effort", level)
    home.take(sample)
    entry.update(reading(home, home.curate()))
    why = lacking(entry)
    entry["outcome"] = "partial" if why else "measured"
    if why:
        entry["why"] = why


def skip_share(prompts, skip, skipped):
    """Which prompts recall skips, by language and by source, and what other ways of counting would skip.

    `skipped` is the staged package's `recall.skipped`. No text is kept: a skipped prompt is named by its
    number in the file, from 1.
    """
    def share(rows):
        found = Counter(row["why"] or "kept" for row in rows)
        left = found["short"] + found["command"]
        return {"prompts": len(rows), "short": found["short"], "command": found["command"], "skipped": left,
                "share": round(left / len(rows), 3) if rows else None}

    def weight(text):  # A count in which a Hangul syllable is 2.
        return sum(2 if "가" <= character <= "힣" else 1 for character in text)

    rows = [{"number": number, "language": language(prompt["text"]), "source": prompt["source"],
             "text": counted(prompt["text"]), "why": skipped(prompt["text"], skip)}
            for number, prompt in enumerate(prompts, 1)]
    plain = [row for row in rows if row["why"] != "command"]
    groups = [("all", plain)] + [(name, [row for row in plain if row["language"] == name])
                                 for name in ("ko", "en", "none")]
    return {"recall_skip": skip, "all": share(rows),
            "by_language": {name: share([row for row in rows if row["language"] == name])
                            for name in ("ko", "en", "none")},
            "by_source": {name: share([row for row in rows if row["source"] == name])
                          for name in sorted({row["source"] for row in rows})},
            "characters": spread([len(row["text"]) for row in rows], 0),
            "short_at_other_values": {str(value): {name: sum(1 for row in group if len(row["text"]) < value)
                                                   for name, group in groups} for value in SKIPS},
            "short_when_a_hangul_syllable_counts_2": {
                str(value): {name: sum(1 for row in group if weight(row["text"]) < value)
                             for name, group in groups} for value in SKIPS},
            "skipped_prompts": [{"number": row["number"], "language": row["language"], "why": row["why"],
                                 "characters": len(row["text"])} for row in rows if row["why"]]}


def replay(check, entry):
    """The recall part: the samples in their order in one home, each prompt ranked before its sample is recorded."""
    home = check.home("recall")
    home.setting("recall", "threshold", THRESHOLD)
    entry.update(threshold=THRESHOLD, dims=list(check.dims), recall_skip=check.defaults["skip"], stages=[],
                 rebuilds=[])
    texts, order = {"prompts": [], "items": {}}, list(check.dims)
    try:
        for sample in check.samples:
            check.afford()
            start, since, items = len(home.made), moment(), home.current()
            stage = {"sample": sample["id"], "current_items_before": len(items), "prompts": []}
            entry["stages"].append(stage)
            if items:
                home.leave_out(["prompt"])
                for number, turn in enumerate(sample["turns"], 1):
                    stage["prompts"].append({"turn": number, "host": turn["host"],
                                             "characters": len(counted(turn["prompt"])),
                                             "language": language(turn["prompt"])})
                    texts["prompts"].append({"sample": sample["id"], "turn": number, "text": turn["prompt"]})
                for dims in order:
                    rebuilt = home.vectors(dims)
                    if rebuilt:
                        entry["rebuilds"].append(dict(rebuilt, before=sample["id"], items=len(home.current())))
                    for row, turn in zip(stage["prompts"], sample["turns"]):
                        row[str(dims)] = home.recalled(turn["host"], turn["prompt"])
                        for value in row[str(dims)]["candidates"]:
                            item = items.get(value["item"]) or c2_hosts.items(home.home).get(value["item"]) or {}
                            texts["items"][value["item"]] = {key: item.get(key) for key in ("kind", "title", "text")}
                order.reverse()  # The next sample begins at the length that the index has now.
                home.leave_out([])
            home.take(sample)
            home.curate()
            stage["curation"] = reading(home, home.made[start:], since)
            embedded([row for run in home.made[start:] for row in run["usage"] if row.get("call") == "embed-items"])
    finally:
        try:
            (check.out / "recall-texts.json").write_text(json.dumps(texts, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
        finally:
            entry["by_dims"] = {str(dims): by_length(entry, dims) for dims in check.dims}
            entry["between_the_lengths"] = [between(entry, check.dims[0], dims) for dims in check.dims[1:]]
    why = [text for stage in entry["stages"] for text in lacking(stage["curation"])]
    for dims, value in entry["by_dims"].items():
        other = sorted(name for name in value["outcomes"] if name not in c2_hosts.RANKED + ("late", "short", "command"))
        if other:
            why.append("at %s numbers a prompt's recall ended with %s" % (dims, ", ".join(other)))
        if check.real and not value["ranked"]:
            why.append("at %s numbers no prompt was ranked" % dims)
    entry["outcome"] = "partial" if why else "measured"
    if why:
        entry["why"] = why


def asked(entry, dims):
    """The recall part's readings at one length, each prompt's in turn."""
    return [row[str(dims)] for stage in entry["stages"] for row in stage["prompts"] if str(dims) in row]


def by_length(entry, dims):
    """The recall part's readings at one length of the vectors."""
    rows = asked(entry, dims)
    ranked = [row for row in rows if row["candidates"]]
    times = [row["ms"] for row in rows]
    rebuilds = [value for value in entry["rebuilds"] if value["dims"] == dims]
    return {"prompts": len(rows), "outcomes": dict(Counter(row["outcome"] for row in rows)),
            "scored_with_more_time": sum(1 for row in rows if row["scored"] != "in the hook's time"),
            "ranked": len(ranked),
            "hook_ms": dict(spread(times, 1), p95=round(percentile(times, 0.95), 1)) if times else None,
            "hook_ms_of_ranked_in_time": spread([row["ms"] for row in rows if row["outcome"] in c2_hosts.RANKED], 1),
            "embed_ms": spread([row["embed_ms"] for row in rows], 1),
            "best_score": spread([row["candidates"][0]["score"] for row in ranked]),
            "fifth_score": spread([row["candidates"][4]["score"] for row in ranked if len(row["candidates"]) > 4]),
            "rebuilds": {"times": len(rebuilds), "requests": sum(value["requests"] for value in rebuilds),
                         "input": sum(value["input"] for value in rebuilds),
                         "usd": round(sum(value["usd"] for value in rebuilds), 6),
                         "ms": sum(value["ms"] for value in rebuilds)}}


def between(entry, first, other):
    """How the candidates of two lengths differ, over the prompts that both ranked."""
    pairs = [(row[str(first)]["candidates"], row[str(other)]["candidates"])
             for stage in entry["stages"] for row in stage["prompts"]
             if row.get(str(first), {}).get("candidates") and row.get(str(other), {}).get("candidates")]
    found = {"dims": [first, other], "prompts_ranked_at_both": len(pairs)}
    if pairs:
        shared = [len({value["item"] for value in one} & {value["item"] for value in two}) for one, two in pairs]
        found.update(same_best_item=sum(1 for one, two in pairs if one[0]["item"] == two[0]["item"]),
                     shared_candidates=spread(shared, 1),
                     best_score_difference=spread([two[0]["score"] - one[0]["score"] for one, two in pairs]))
    return found


def line(points):
    """The least-squares line count = a * ASCII + b * other + c over some documents, or None where they give none.

    Each point is (ASCII characters, other characters, count). Documents whose two numbers of characters are in
    step with each other, or that have no character of one of the two kinds, give no line.
    """
    most = [max(point[index] for point in points) for index in (0, 1)] if points else [0, 0]
    if len(points) < 3 or not all(most):
        return None
    table = [[0.0] * 4 for _ in range(3)]  # The normal equations of the three unknowns, each number of
    for ascii_count, other, count in points:  # characters as a share of the greatest, so that all are near 1.
        values = (ascii_count / most[0], other / most[1], 1.0)
        for i in range(3):
            for j in range(3):
                table[i][j] += values[i] * values[j]
            table[i][3] += values[i] * count
    for i in range(3):  # Gaussian elimination with the greatest pivot.
        pivot = max(range(i, 3), key=lambda row: abs(table[row][i]))
        if abs(table[pivot][i]) <= 1e-9 * len(points):
            return None
        table[i], table[pivot] = table[pivot], table[i]
        for row in range(3):
            if row != i:
                factor = table[row][i] / table[i][i]
                table[row] = [value - factor * base for value, base in zip(table[row], table[i])]
    a, b, c = table[0][3] / table[0][0] / most[0], table[1][3] / table[1][1] / most[1], table[2][3] / table[2][2]
    errors = [abs(a * x + b * y + c - count) for x, y, count in points]
    return {"documents": len(points), "tokens_per_ascii_character": round(a, 4),
            "tokens_per_other_character": round(b, 4), "constant": round(c, 1),
            "largest_error_tokens": round(max(errors), 1)}


def estimates(requests):
    """The estimates of every counted request against its count, each document once."""
    seen, rows = set(), []
    for row in requests:
        key = (row.get("instructions"), row.get("source_sha256"))
        if row.get("count") and row.get("safe") is not None and key not in seen:
            seen.add(key)
            rows.append(row)
    found = {"requests": len(requests), "requests_with_a_count": sum(1 for row in requests if row.get("count")),
             "documents_counted": len(rows)}
    if rows:
        curate = [(row["ascii"], row["other"], row["count"]) for row in rows
                  if c2_real.kind_of(row) == "curate" and row.get("ascii") is not None]
        found.update(
            documents_with_the_safe_estimate_below_the_count=sum(1 for row in rows if row["safe"] < row["count"]),
            safe_over_count=spread([row["safe"] / row["count"] for row in rows]),
            working_over_count=spread([row["working"] / row["count"] for row in rows]),
            count_over_billed_input=spread([row["count"] / row["input"] for row in rows if row.get("input")]),
            line_of_curate_requests=line(curate))
    return found


def by_effort(runs):
    """The measured runs' sums at each effort."""
    found = {}
    for entry in runs.values():
        if entry.get("outcome") != "measured":
            continue
        value = found.setdefault(entry["effort"], {
            "runs": 0, "requests": 0, "input": 0, "output": 0, "usd": 0.0, "request_ms": 0, "items": 0,
            "state_lines": 0, "current_item_bytes": 0, "changes": Counter(), "current_items_by_kind": Counter(),
            "applied": 0, "dropped": 0, "dropped_by_reason": Counter(), "line_edits_dropped_by_reason": Counter(),
            "first_ms": []})
        value["runs"] += 1
        for attempt in entry.get("attempts", []):
            value["applied"] += attempt.get("applied") or 0
            value["dropped"] += attempt.get("dropped") or 0
            value["dropped_by_reason"].update(attempt.get("reasons") or {})
            value["line_edits_dropped_by_reason"].update(attempt.get("edit_reasons") or {})
        for row in entry["requests"]:
            value["requests"] += 1
            for name, key in (("input", "input"), ("output", "output"), ("request_ms", "total_ms")):
                value[name] += row.get(key) or 0
            value["changes"].update(row.get("changes") or {})
            value["first_ms"].append(row.get("first_ms"))
        value["usd"] += entry["usd"]
        layer = entry["layer"]
        value["items"] += layer["items"]
        value["state_lines"] += layer["state_lines"]
        value["current_item_bytes"] += layer["current_item_bytes"]
        value["current_items_by_kind"].update(layer["current_items_by_kind"])
    for value in found.values():
        value.update(usd=round(value["usd"], 6), changes=dict(value["changes"]),
                     current_items_by_kind=dict(value["current_items_by_kind"]),
                     dropped_by_reason=dict(value["dropped_by_reason"]),
                     line_edits_dropped_by_reason=dict(value["line_edits_dropped_by_reason"]),
                     first_ms=spread(value["first_ms"], 0))
    return found


class Measure(c2_real.Check):
    Server = Counting

    def __init__(self, out, options):
        super().__init__(out, options)
        scripts = self.plugin / "skills/corthex-memory/scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        schema = json.loads((scripts / "memory_lib/configuration.schema.json").read_text(encoding="utf-8"))
        properties = schema["properties"]
        self.defaults = {"effort": properties["models"]["properties"]["effort"]["default"],
                         "dims": properties["models"]["properties"]["dims"]["default"],
                         "skip": properties["recall"]["properties"]["skip"]["default"]}
        self.samples, self.pool, self.dims = options.loaded, options.pool, options.dims
        self.embedding = False  # Whether the worker gets the embedding key: only in the recall part.
        del self.report["cases"]
        self.report.update(parts=options.part, efforts=options.effort, dims=options.dims, defaults=self.defaults,
                           samples={sample["id"]: sizes(sample) for sample in self.samples}, runs={})

    def home(self, label):
        return Home(self, label)

    def worker_environment(self, home, provider):
        env = super().worker_environment(home, provider)
        if not self.embedding:
            env.pop(c2_real.OPENAI, None)
        return env

    def recall_environment(self, home, host):
        """The prompt hook's environment for a recall: the host's, with the embedding key and nothing else of the
        memory keys."""
        env = self.host_environment(home, host)
        if self.real:
            env.update({name: os.environ[name] for name in c2_real.NETWORK if name in os.environ})
            env[c2_real.OPENAI] = self.keys[c2_real.OPENAI]
        else:
            env[c2_real.OPENAI] = self.markers[c2_real.OPENAI]
            env.update(c2_hosts.memory_urls(self.server.url))
        return env

    def steps(self):
        """What is run one by one, with the report written before each."""
        found = []
        if "efforts" in self.options.part:
            found += [("efforts", sample, level, number) for sample in self.samples
                      for level in self.options.effort for number in range(1, self.options.repeat + 1)]
        return found + [(name,) for name in ("skip", "recall") if name in self.options.part]

    def step(self, name):
        if name[0] == "skip":
            from memory_lib import recall
            entry = self.report["skip"] = {"outcome": "not run"}
            self.guard(entry, lambda: entry.update(skip_share(self.pool, self.defaults["skip"], recall.skipped),
                                                   outcome="measured"), free=True)
        elif name[0] == "recall":
            entry = self.report["recall"] = {"outcome": "not run"}
            self.embedding = True
            try:
                self.guard(entry, lambda: replay(self, entry))
            finally:
                self.embedding = False
        else:
            _, sample, level, number = name
            label = "%s-%s-%d" % (sample["id"], level, number)
            entry = self.report["runs"][label] = {"sample": sample["id"], "effort": level, "outcome": "not run"}
            self.guard(entry, lambda: measured(self, entry, sample, level, label))
        self.totals()

    def guard(self, entry, action, free=False):
        """Run a step that fills `entry`; no step that costs starts once the limit is reached, and an interrupt
        is noted."""
        try:
            if not free:
                self.afford()
            action()
        except c2_real.Stopped as stopped:
            entry.update(outcome="not run", why=str(stopped))
        except KeyboardInterrupt:
            entry.update(outcome="not run", why="interrupted during this run")
            raise
        except Exception:
            entry.update(outcome="crash", crash=self.mask(traceback.format_exc()))

    def totals(self):
        """The readings across what has run so far."""
        report = self.report
        requests = [row for entry in report["runs"].values() for row in entry.get("requests", [])]
        requests += [row for stage in (report.get("recall") or {}).get("stages", [])
                     for row in (stage.get("curation") or {}).get("requests", [])]
        report["estimates"] = estimates(requests)
        report["by_effort"] = by_effort(report["runs"])
        if not self.real:
            report["efforts_that_the_local_server_got"] = dict(Counter(str(value) for value in self.server.efforts))


def ended(report):
    """Every step's outcome, by its name in the report."""
    found = {name: entry["outcome"] for name, entry in report.get("runs", {}).items()}
    found.update({name: report[name]["outcome"] for name in ("skip", "recall") if name in report})
    return found


def summary(report):
    text = ["== MEMORY measured at %s against %s ==" % (report["release"], report["provider"])]
    if "runs" not in report:
        return text + [report.get("crash", "the check did not begin")]
    text.append("system: %s, Python %s; checkout: %s; keys: %s" % (
        report["system"]["platform"], report["system"]["python"], json.dumps(report["checkout"]),
        json.dumps(report["keys"])))
    for name, entry in report["runs"].items():
        if entry["outcome"] != "measured":
            text.append("%s: %s %s" % (name, entry["outcome"], json.dumps(entry.get("why") or entry.get("crash"))))
            continue
        layer = entry["layer"]
        for row in entry["requests"]:
            text.append("%s: working %s, safe %s, count %s (safe/count %s), billed input %s, output %s, %s ms, "
                        "%s USD; %d items, %d state lines; changes dropped: %s" % (
                            name, row["working"], row["safe"], row["count"], row.get("safe_over_count"),
                            row["input"], row["output"], row["total_ms"], row["usd"], layer["items"],
                            layer["state_lines"],
                            sum(attempt.get("dropped") or 0 for attempt in entry.get("attempts", []))))
    text.append("estimates against counts: %s" % json.dumps(report.get("estimates")))
    for level, value in report.get("by_effort", {}).items():
        text.append("effort %s: %s" % (level, json.dumps(value)))
    if "skip" in report:
        shown = {key: value for key, value in report["skip"].items() if key != "skipped_prompts"}
        text.append("recall.skip: %s" % json.dumps(shown))
    if "recall" in report:
        value = report["recall"]
        text.append("recall: %s %s" % (value["outcome"], json.dumps(value.get("why") or value.get("crash") or "")))
        for dims, found in (value.get("by_dims") or {}).items():
            text.append("  %s numbers: %s" % (dims, json.dumps(found)))
        for found in value.get("between_the_lengths") or []:
            text.append("  between the lengths: %s" % json.dumps(found))
    text.append("requests to %s, by the usage log: %s" % (report["provider"], json.dumps(report.get("cost"))))
    text.append("requests to the local server: %s" % report.get("local_requests"))
    if c2_real.leaked(report):
        text.append("A MEMORY KEY OF THIS ENVIRONMENT WAS FOUND: in files %s; in the report: %s; in requests to the "
                    "local server: %s" % (json.dumps(report.get("files_with_key")), bool(report.get("key_in_report")),
                                          report.get("local_requests_with_key")))
    if report.get("files_not_read"):
        text.append("files that could not be read, so the search for a key is not complete: %s" % json.dumps(
            report["files_not_read"]))
    if "crash" in report:
        text.append(report["crash"])
    return text


def passed(report):
    """Whether everything that was asked for was measured, no memory key of this environment was found, and
    every file under the folder could be searched for one."""
    outcomes = ended(report)
    done = "crash" not in report and bool(outcomes) and all(value == "measured" for value in outcomes.values())
    return done and not c2_real.leaked(report) and not report.get("files_not_read")


def options(arguments):
    parser = argparse.ArgumentParser(description="Measurements of MEMORY on redacted real conversations (TASK-047).")
    parser.add_argument("out", metavar="OUTDIR")
    parser.add_argument("--samples", metavar="DIR", help="the folder of the redacted samples, one <id>.json each")
    parser.add_argument("--sample", action="append", metavar="ID", help="a sample to take; every one when left out")
    parser.add_argument("--prompts", metavar="FILE", help="a JSON list of typed prompts, for the share skipped")
    parser.add_argument("--part", action="append", choices=PARTS, help="a part to run; efforts, and skip with FILE")
    parser.add_argument("--effort", action="append", choices=EFFORTS, help="an effort; medium, high and xhigh")
    parser.add_argument("--dims", action="append", type=int, help="a length of the vectors; 512 and 1536")
    parser.add_argument("--repeat", type=int, default=1, help="runs of each sample at each effort")
    parser.add_argument("--limit", type=float, default=c2_real.LIMIT, help="USD by the usage log after which no run starts")
    parser.add_argument("--self-test", action="store_true", help="answer every request from a local server")
    chosen = parser.parse_args(arguments)
    usual = ["efforts"] + (["skip"] if chosen.prompts or (chosen.self_test and not chosen.samples) else [])
    chosen.part = [name for name in PARTS if name in (chosen.part or usual)]
    chosen.effort = [name for name in EFFORTS if name in (chosen.effort or MEASURED)]
    chosen.dims = list(dict.fromkeys(chosen.dims or LENGTHS))
    return chosen


def given(chosen):
    """The samples and the prompts that the options name, or a ValueError that says what is missing."""
    if any(not SHORTEST <= dims <= LONGEST for dims in chosen.dims):
        raise ValueError("--dims is a number from %d to %d" % (SHORTEST, LONGEST))
    names = list(dict.fromkeys(chosen.sample or []))
    if chosen.samples:
        samples = samples_of(chosen.samples, names)
    elif chosen.self_test:
        samples = [sample for sample in MADE_UP if not names or sample["id"] in names]
        if not samples:
            raise ValueError("--sample names none of the made-up samples")
    elif set(chosen.part) - {"skip"}:
        raise ValueError("--samples DIR is needed: the folder of the redacted samples")
    else:
        samples = []
    if "skip" not in chosen.part:
        pool = []
    elif chosen.prompts:
        pool = prompts_of(chosen.prompts)
    elif chosen.self_test:
        pool = list(MADE_UP_PROMPTS)
    else:
        raise ValueError("--prompts FILE is needed for the part skip")
    if "recall" in chosen.part and not chosen.self_test and not os.environ.get(c2_real.OPENAI):
        raise ValueError("%s is not set in this environment, and the part recall embeds with it." % c2_real.OPENAI)
    return samples, pool


def main(arguments=None):
    chosen = options(arguments)
    try:
        chosen.loaded, chosen.pool = given(chosen)
    except ValueError as error:
        print(error)
        return 2
    return c2_real.launch(chosen, "c2-measure", Measure, summary, passed)


if __name__ == "__main__":
    sys.exit(main())
