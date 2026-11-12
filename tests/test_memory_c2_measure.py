"""TASK-047: the readings, refusals and wrappers of the measurement check, and its self-test.

No provider is called here: the readings get made-up request lines, usage lines and layers, and the one run of the
script answers every request from its local server.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid

from _common import ROOT

FOLDER = ROOT / ".github/hook-check"
sys.path.insert(0, str(FOLDER))
sys.path.insert(0, str(ROOT / "plugins/corthex-memory/skills/corthex-memory/scripts"))
import memory_lib  # noqa: E402
from memory_lib import model_prompts, recall, request_budget  # noqa: E402,F401


def load(name):
    spec = importlib.util.spec_from_file_location(name + "_checked", FOLDER / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


measure = load("c2_measure")
worker = load("c2_measure_worker")
real, hosts = measure.c2_real, measure.c2_hosts

ANTHROPIC, OPENAI = real.ANTHROPIC, real.OPENAI
SECRETS = ("ENVIRONMENT-ANTHROPIC-KEY-0002", "ENVIRONMENT-OPENAI-KEY-0002")
SAMPLE = {"id": "one", "kind": "typed", "source": "a test", "turns": [
    {"host": "claude", "prompt": "PROMPT-TEXT-OF-A-SAMPLE", "reply": "REPLY-TEXT-OF-A-SAMPLE"}]}


def request(document="a", instructions="curate-3", attempts=1, failure=None, answer=None, **more):
    """A request's line of requests.jsonl, as c2_measure_worker.py writes it."""
    digest = hashlib.sha256(document.encode("utf-8")).hexdigest()
    row = {"kind": "request", "instructions": instructions, "document": "<request>%s</request>" % document,
           "answer": json.dumps(answer if answer is not None else {"changes": [], "state": {
               "change": [], "add": [], "remove": []}}),
           "failure": failure, "attempts": attempts, "model": "model-x", "effort": "high", "max_tokens": 64000,
           "source_sha256": digest, "ascii": 4000, "other": 1000, "working": 2000, "safe": 4000, "estimate": 2000,
           "size": {"turns": 1, "list": "full", "estimate": 2000}}
    row.update(more)
    return row


def count(document="a", tokens=3000, failure=None):
    return {"kind": "count", "instructions": "curate-3", "tokens": tokens, "failure": failure,
            "source_sha256": hashlib.sha256(document.encode("utf-8")).hexdigest()}


def usage(call="curate", result="ok", instructions="curate-3", **more):
    row = {"call": call, "result": result, "instructions": instructions, "input": 3000, "output": 400,
           "cache_write": 0, "cache_read": 0, "first_ms": 900, "total_ms": 1000, "cost": 0.001, "estimate": 2000,
           "list": "full", "turns": 1}
    row.update(more)
    return row


def layer(items=(), lines=(), candidates=(), waiting=0):
    return {"items": {value["id"]: value for value in items}, "lines": list(lines),
            "candidates": list(candidates), "waiting": waiting}


def item(number, kind="decision", status="current", title="제목", text="본문"):
    return {"id": "i_%012d" % number, "kind": kind, "status": status, "title": title, "text": text,
            "quotes": [{"entry": "e_%012d" % number}]}


def measured_run(effort="high", **more):
    row = measure.joined([request(), count()], [usage()])[0]
    entry = {"sample": "one", "effort": effort, "outcome": "measured", "requests": [row], "usd": 0.001,
             "attempts": [{"kind": "curate", "result": "ok", "applied": 2, "dropped": 1, "reasons": {"quote": 1},
                           "edit_reasons": {"cite": 2}}],
             "layer": measure.made(layer([item(1), item(2, kind="fact")], [{"part": "decisions", "text": "한 줄"}]))}
    entry.update(more)
    return entry


class OptionTests(unittest.TestCase):
    def run_main(self, arguments, **environment):
        """`main` with a new OUTDIR and without the keys of this environment; the staged copy is put back."""
        base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, base, True)
        kept = {name: value for name, value in os.environ.items()
                if name not in ("CI", "GITHUB_ACTIONS", ANTHROPIC, OPENAI)}
        kept.update(environment)
        output = io.StringIO()
        with mock.patch.dict(os.environ, kept, clear=True), contextlib.redirect_stdout(output), \
                mock.patch.object(real.hookcheck, "REPO", real.hookcheck.REPO), \
                mock.patch.object(real.hookcheck, "MEMORY", real.hookcheck.MEMORY):
            code = measure.main([base] + arguments)
        return code, output.getvalue(), Path(base)

    def samples(self, *values):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(folder), True)
        for value in values or (SAMPLE,):
            (folder / (value["id"] + ".json")).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return folder

    def test_it_never_calls_the_providers_in_ci(self):
        for name in ("CI", "GITHUB_ACTIONS"):
            with self.subTest(name):
                code, text, base = self.run_main(["--samples", str(self.samples())],
                                                 **{name: "true", ANTHROPIC: "made-up"})
                self.assertEqual(code, 2)
                self.assertIn("never run in CI", text)
                self.assertEqual(list(base.iterdir()), [])

    def test_it_names_the_key_that_is_not_set_and_writes_nothing(self):
        code, text, base = self.run_main(["--samples", str(self.samples())])
        self.assertEqual(code, 2)
        self.assertIn(ANTHROPIC + " is not set", text)
        self.assertEqual(list(base.iterdir()), [])

    def test_a_run_against_the_providers_needs_the_samples_folder(self):
        code, text, base = self.run_main([], **{ANTHROPIC: "made-up"})
        self.assertEqual(code, 2)
        self.assertIn("--samples DIR is needed", text)
        self.assertEqual(list(base.iterdir()), [])

    def test_the_part_skip_needs_the_prompts_and_the_part_recall_the_embedding_key(self):
        folder = str(self.samples())
        code, text, base = self.run_main(["--samples", folder, "--part", "skip"], **{ANTHROPIC: "made-up"})
        self.assertEqual((code, list(base.iterdir())), (2, []))
        self.assertIn("--prompts FILE is needed", text)
        code, text, base = self.run_main(["--samples", folder, "--part", "recall"], **{ANTHROPIC: "made-up"})
        self.assertEqual((code, list(base.iterdir())), (2, []))
        self.assertIn(OPENAI + " is not set", text)

    def test_a_length_that_the_configuration_does_not_take_is_refused(self):
        for value in ("63", "3073"):
            code, text, base = self.run_main(["--self-test", "--dims", value])
            self.assertEqual((code, list(base.iterdir())), (2, []), value)
            self.assertIn("--dims", text)

    def test_a_sample_that_cannot_be_read_is_named_without_its_text_and_nothing_is_written(self):
        broken = dict(SAMPLE, turns=[dict(SAMPLE["turns"][0], reply="")])
        code, text, base = self.run_main(["--self-test", "--samples", str(self.samples(broken))])
        self.assertEqual((code, list(base.iterdir())), (2, []))
        self.assertIn("one.json is no sample: turn 1 has no reply", text)
        self.assertNotIn("PROMPT-TEXT", text)

    def test_the_parts_efforts_and_lengths_that_no_option_names(self):
        chosen = measure.options(["out", "--samples", "dir"])
        self.assertEqual((chosen.part, chosen.effort, chosen.dims), (["efforts"], ["medium", "high", "xhigh"],
                                                                     [512, 1536]))
        self.assertEqual(measure.options(["out", "--samples", "dir", "--prompts", "file"]).part, ["efforts", "skip"])
        # A self-test without a folder has its made-up prompts too.
        self.assertEqual(measure.options(["out", "--self-test"]).part, ["efforts", "skip"])
        self.assertEqual(measure.options(["out", "--self-test", "--samples", "dir"]).part, ["efforts"])

    def test_a_part_an_effort_and_a_length_named_twice_count_once(self):
        chosen = measure.options(["out", "--part", "recall", "--part", "efforts", "--part", "recall", "--effort",
                                  "xhigh", "--effort", "low", "--effort", "xhigh", "--dims", "1536", "--dims", "256",
                                  "--dims", "1536"])
        self.assertEqual((chosen.part, chosen.effort, chosen.dims), (["efforts", "recall"], ["low", "xhigh"],
                                                                     [1536, 256]))

    def test_a_self_test_without_a_folder_takes_the_made_up_samples_and_prompts(self):
        chosen = measure.options(["out", "--self-test", "--sample", "made-up-en"])
        samples, pool = measure.given(chosen)
        self.assertEqual(([sample["id"] for sample in samples], len(pool)), (["made-up-en"], len(measure.MADE_UP_PROMPTS)))
        with self.assertRaises(ValueError):
            measure.given(measure.options(["out", "--self-test", "--sample", "no-such"]))

    def test_a_workflow_runs_it_as_a_self_test_only(self):
        lines = [(path.name, text) for path in sorted((ROOT / ".github/workflows").glob("*.yml"))
                 for text in path.read_text(encoding="utf-8").splitlines() if "c2_measure" in text and "run:" in text]
        self.assertTrue(lines)
        for name, text in lines:
            self.assertIn("c2_measure.py", text, name)
            self.assertIn("--self-test", text, name)

    def test_the_wrappers_have_whole_paths_however_the_script_was_named(self):
        # Python 3.8 gives a script the path as it was typed; `runpy` does so on every version.
        probe = ("import runpy\n"
                 "found = runpy.run_path('.github/hook-check/c2_measure.py', run_name='c2_measure_probed')\n"
                 "print(all(found[name].is_absolute() and found[name].is_file() for name in ('WORKER', 'HOOK')))\n")
        done = subprocess.run([sys.executable, "-c", probe], cwd=str(ROOT), capture_output=True, timeout=120)
        self.assertEqual((done.stdout.decode("utf-8").strip(), done.returncode), ("True", 0),
                         done.stderr.decode("utf-8", "replace"))

    def test_started_as_a_script_it_leaves_no_bytecode_beside_the_checkout_s_modules(self):
        cache = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(cache), True)
        environment = {key: value for key, value in os.environ.items() if key != "PYTHONDONTWRITEBYTECODE"}
        environment["PYTHONPYCACHEPREFIX"] = str(cache)
        done = subprocess.run([sys.executable, str(FOLDER / "c2_measure.py"), "--help"], capture_output=True,
                              env=environment, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
        self.assertIn(b"OUTDIR", done.stdout)
        self.assertEqual([path.name for path in cache.rglob("*.pyc") if "hook-check" in path.parts], [])


class SampleTests(unittest.TestCase):
    def folder(self, **files):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(folder), True)
        for name, value in files.items():
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            (folder / (name + ".json")).write_text(text, encoding="utf-8")
        return folder

    def test_a_sample_keeps_its_id_kind_source_and_turns_and_nothing_else(self):
        value = dict(SAMPLE, extra="x", turns=[dict(SAMPLE["turns"][0], more="y")])
        self.assertEqual(measure.valid(value, "one.json"), SAMPLE)

    def test_what_is_no_sample_is_refused_with_the_file_s_name_and_none_of_its_text(self):
        turn = SAMPLE["turns"][0]
        for change, why in (({"turns": []}, "no list of turns"), ({"turns": "x"}, "no list of turns"),
                            ({"id": "One"}, "its id"), ({"id": "../one"}, "its id"), ({"id": "a" * 41}, "its id"),
                            ({"id": 7}, "its id"), ({"kind": ""}, "its kind"), ({"source": "s" * 41}, "its source"),
                            ({"turns": [dict(turn, host="gemini")]}, "turn 1 names no host"),
                            ({"turns": [turn, dict(turn, prompt="  ")]}, "turn 2 has no prompt"),
                            ({"turns": [dict(turn, reply=None)]}, "turn 1 has no reply"),
                            ({"turns": ["x"]}, "turn 1 names no host")):
            with self.subTest(change):
                with self.assertRaises(ValueError) as refused:
                    measure.valid(dict(SAMPLE, **change), "one.json")
                self.assertIn("one.json is no sample", str(refused.exception))
                self.assertIn(why, str(refused.exception))
                self.assertNotIn("TEXT-OF-A-SAMPLE", str(refused.exception))
        with self.assertRaises(ValueError):
            measure.valid([SAMPLE], "one.json")

    def test_the_samples_are_those_named_in_that_order_or_all_by_file_name(self):
        folder = self.folder(b=dict(SAMPLE, id="b"), a=dict(SAMPLE, id="a"), c=dict(SAMPLE, id="c"))
        self.assertEqual([sample["id"] for sample in measure.samples_of(folder, [])], ["a", "b", "c"])
        self.assertEqual([sample["id"] for sample in measure.samples_of(folder, ["c", "a"])], ["c", "a"])

    def test_a_folder_a_file_and_an_id_that_do_not_fit_are_refused(self):
        with self.assertRaises(ValueError) as refused:
            measure.samples_of(self.folder() / "none", [])
        self.assertIn("is no folder", str(refused.exception))
        with self.assertRaises(ValueError) as refused:
            measure.samples_of(self.folder(), [])
        self.assertIn("holds no sample", str(refused.exception))
        for files, names, why in (({"a": "{not json"}, [], "a.json cannot be read as JSON"),
                                  ({"a": dict(SAMPLE, id="a")}, ["b"], "b.json cannot be read as JSON"),
                                  ({"a": dict(SAMPLE, id="b")}, [], "its id is not its file's name")):
            with self.subTest(why):
                with self.assertRaises(ValueError) as refused:
                    measure.samples_of(self.folder(**files), names)
                self.assertIn(why, str(refused.exception))

    def test_the_prompts_are_a_list_of_texts_each_with_its_source_when_it_has_one(self):
        folder = self.folder(p=[{"text": "가", "source": "chat", "language": "x"}, {"text": "b"}])
        self.assertEqual(measure.prompts_of(folder / "p.json"),
                         [{"source": "chat", "text": "가"}, {"source": "not given", "text": "b"}])
        for value in ("{}", "[]", '[{"text": 3}]', '["x"]', "[", json.dumps([{"text": "a", "source": "s" * 41}])):
            with self.subTest(value):
                with self.assertRaises(ValueError):
                    measure.prompts_of(self.folder(p=value) / "p.json")
        with self.assertRaises(ValueError):
            measure.prompts_of(folder / "none.json")

    def test_a_sample_in_numbers_has_none_of_its_text(self):
        value = {"id": "s", "kind": "chat", "source": "a test", "turns": [
            {"host": "claude", "prompt": "가나 ab", "reply": "다 cd"}, {"host": "codex", "prompt": "ef", "reply": "라"}]}
        self.assertEqual(measure.sizes(value), {
            "kind": "chat", "source": "a test", "turns": 2, "hosts": {"claude": 1, "codex": 1},
            "prompt_characters": 7, "reply_characters": 5, "hangul_share_of_letters": 0.4})

    def test_the_made_up_samples_are_samples_and_each_prompt_of_them_has_its_script(self):
        for sample in measure.MADE_UP:
            self.assertEqual(measure.valid(sample, sample["id"]), sample)
        prompts = [turn["prompt"] for sample in measure.MADE_UP for turn in sample["turns"]]
        self.assertEqual(sorted(measure.SCRIPTS), sorted(prompts))


class ReadingTests(unittest.TestCase):
    def test_a_request_gets_the_count_of_its_document_and_its_usage_line(self):
        rows = [count("a", 3000), request("a"), count("b", 500), request("b", safe=400, working=200, estimate=200)]
        lines = [usage(call="count-tokens", instructions=None), usage(cache_read=200, cache_write=100),
                 usage(estimate=200, input=480, output=10, cost=0.0002)]
        first, second = measure.joined(rows, lines)
        self.assertEqual({key: first[key] for key in (
            "count", "count_calls", "input", "output", "usd", "result", "usage_lines", "estimate_agrees",
            "safe_at_or_above_count", "safe_over_count", "working_over_count", "effort", "model", "list", "turns")},
            {"count": 3000, "count_calls": 1, "input": 3300, "output": 400, "usd": 0.001, "result": "ok",
             "usage_lines": 1, "estimate_agrees": True, "safe_at_or_above_count": True, "safe_over_count": 1.333,
             "working_over_count": 0.667, "effort": "high", "model": "model-x", "list": "full", "turns": 1})
        self.assertEqual((second["count"], second["input"], second["safe_at_or_above_count"],
                          second["safe_over_count"]), (500, 480, False, 0.8))
        # Neither the document nor the answer is kept: their sizes are.
        self.assertEqual((first["document_bytes"], first["answer_bytes"]),
                         (len("<request>a</request>"), len(request("a")["answer"])))
        self.assertFalse({"document", "answer", "size"} & set(first))

    def test_a_request_that_was_tried_again_takes_a_line_for_each_attempt_and_reads_the_last(self):
        rows = [count("a"), request("a", attempts=2), count("b"), request("b")]
        lines = [usage(result="failed", error="overloaded", cost=0.0, output=0, input=0), usage(output=700, cost=0.002),
                 usage(output=5, cost=0.0001)]
        first, second = measure.joined(rows, lines)
        self.assertEqual((first["usage_lines"], first["result"], first["output"], first["usd"]), (2, "ok", 700, 0.002))
        self.assertEqual((second["usage_lines"], second["output"]), (1, 5))

    def test_requests_of_other_instructions_take_their_own_usage_lines(self):
        rows = [request("a"), request("m", instructions="merge-2", answer={"merges": [{}], "conflicts": []})]
        lines = [usage(call="consolidate", instructions="merge-2", output=9), usage(output=8)]
        first, second = measure.joined(rows, lines)
        self.assertEqual((first["output"], second["output"], second["merges"], second["conflicts"]), (8, 9, 1, 0))

    def test_a_document_counted_twice_has_its_latest_count_and_a_failed_count_is_named(self):
        rows = [count("a", None, "timeout"), count("a", 2900), request("a")]
        row = measure.joined(rows, [usage()])[0]
        self.assertEqual((row["count"], row["count_calls"], row["count_failures"]), (2900, 2, ["timeout"]))

    def test_a_request_without_a_count_or_a_usage_line_says_so_and_has_no_ratio(self):
        row = measure.joined([request("a")], [])[0]
        self.assertEqual((row["count"], row["result"], row["input"], row["usage_lines"], row["estimate_agrees"]),
                         (None, None, None, 0, False))
        self.assertNotIn("safe_over_count", row)
        self.assertEqual(measure.lacking({"requests": [row], "layer": {"turns_left_to_curate": 0}}),
                         ["request 1 has no count", "request 1 ended with no usage line",
                          "request 1: the usage line's estimate is not the one that was computed again"])

    def test_an_estimate_of_the_usage_line_that_is_not_the_wrapper_s_is_told(self):
        row = measure.joined([count(), request()], [usage(estimate=1999)])[0]
        self.assertFalse(row["estimate_agrees"])

    def test_an_answer_is_read_in_numbers(self):
        answer = {"changes": [{"action": "add", "kind": "decision", "title": "T"}, {"action": "add", "kind": "fact"},
                              {"action": "replace", "kind": "decision"}, "x"],
                  "state": {"change": [{}], "add": [{}, {}], "remove": []}}
        self.assertEqual(measure.answered({"answer": json.dumps(answer)}),
                         {"changes": {"add decision": 1, "add fact": 1, "replace decision": 1},
                          "state": {"change": 1, "add": 2, "remove": 0}})
        self.assertEqual(measure.answered({"answer": "{cut"}), {"answer": "no JSON"})
        self.assertEqual(measure.answered({"answer": None}), {"answer": "no JSON"})
        self.assertEqual(measure.answered({"answer": "[1]"}), {"answer": "no object"})

    def test_a_reading_lacks_what_it_names(self):
        whole = {"requests": measure.joined([count(), request()], [usage()]), "layer": {"turns_left_to_curate": 0}}
        self.assertEqual(measure.lacking(whole), [])
        self.assertEqual(measure.lacking({"requests": [], "layer": {"turns_left_to_curate": 2}}),
                         ["no request was written", "2 turns are left to curate"])
        failed = measure.joined([count(), request(failure="limit")], [usage(result="limit", error="max-tokens")])
        self.assertEqual(measure.lacking({"requests": failed, "layer": {"turns_left_to_curate": 0}}),
                         ["request 1 ended with limit"])
        self.assertEqual(measure.lacking(dict(whole, lines_left_out_because_they_are_no_json={"usage": 1})),
                         ["a log has lines that are no JSON"])

    def test_a_layer_is_read_in_numbers(self):
        found = measure.made(layer(
            [item(1), item(2, kind="fact", title="Title", text="Text"), item(3, status="superseded")],
            [{"part": "decisions", "text": "한 줄"}, {"part": "next", "text": "a line"}],
            [{"status": "open"}, {"status": "closed"}], waiting=1))
        self.assertEqual(found, {
            "items": 3, "items_by_status": {"current": 2, "superseded": 1},
            "current_items_by_kind": {"decision": 1, "fact": 1}, "current_items_with_korean_text": 1,
            "current_item_bytes": 12 + 9, "quotes": 2, "state_lines": 2,
            "state_lines_by_part": {"decisions": 1, "next": 1}, "state_lines_with_korean_text": 1,
            "state_line_bytes": 7 + 6, "open_conflict_candidates": 1, "turns_left_to_curate": 1})

    def test_the_usage_lines_are_counted_by_call_and_how_they_ended(self):
        lines = [usage(), usage(result="failed", error="overloaded"), usage(call="embed-items"),
                 usage(call="embed-items", result="failed", error="insufficient_quota")]
        self.assertEqual(measure.results(lines), {"curate": {"ok": 1, "failed: overloaded": 1},
                                                 "embed-items": {"ok": 1, "failed: insufficient_quota": 1}})

    def test_the_estimates_are_read_once_for_each_document(self):
        rows = measure.joined([count("a", 3000), request("a"), request("a"), count("b", 5000), request("b"),
                               request("c")], [usage(), usage(), usage(input=5000), usage()])
        found = measure.estimates(rows)
        self.assertEqual({key: found[key] for key in ("requests", "requests_with_a_count", "documents_counted",
                                                      "documents_with_the_safe_estimate_below_the_count")},
                         {"requests": 4, "requests_with_a_count": 3, "documents_counted": 2,
                          "documents_with_the_safe_estimate_below_the_count": 1})
        self.assertEqual(found["safe_over_count"], {"min": 0.8, "median": 1.067, "max": 1.333, "values": 2})
        self.assertEqual(found["working_over_count"], {"min": 0.4, "median": 0.533, "max": 0.667, "values": 2})
        self.assertEqual(found["count_over_billed_input"], {"min": 1.0, "median": 1.0, "max": 1.0, "values": 2})
        self.assertIsNone(found["line_of_curate_requests"])
        self.assertEqual(measure.estimates([]), {"requests": 0, "requests_with_a_count": 0, "documents_counted": 0})

    def test_the_line_of_the_counts_is_found_where_the_documents_give_one(self):
        points = [(x, y, 0.3 * x + 1.5 * y + 400) for x, y in ((1000, 0), (0, 1000), (2000, 500), (700, 300))]
        found = measure.line(points)
        self.assertEqual((found["documents"], found["tokens_per_ascii_character"], found["tokens_per_other_character"],
                          found["constant"], found["largest_error_tokens"]), (4, 0.3, 1.5, 400.0, 0.0))
        self.assertIsNone(measure.line(points[:2]))
        # Documents whose other characters are in step with their ASCII characters give no line.
        self.assertIsNone(measure.line([(1000, 100, 500), (2000, 200, 900), (3000, 300, 1300)]))

    def test_each_effort_sums_its_measured_runs_only(self):
        runs = {"a": measured_run(), "b": measured_run(), "c": measured_run("xhigh"),
                "d": dict(measured_run(), outcome="partial"), "e": {"effort": "high", "outcome": "crash"}}
        found = measure.by_effort(runs)
        self.assertEqual(sorted(found), ["high", "xhigh"])
        self.assertEqual({key: found["high"][key] for key in (
            "runs", "requests", "input", "output", "usd", "request_ms", "items", "state_lines", "changes",
            "current_items_by_kind")},
            {"runs": 2, "requests": 2, "input": 6000, "output": 800, "usd": 0.002, "request_ms": 2000, "items": 4,
             "state_lines": 2, "changes": {}, "current_items_by_kind": {"decision": 2, "fact": 2}})
        self.assertEqual(found["high"]["first_ms"], {"min": 900, "median": 900, "max": 900, "values": 2})
        self.assertEqual({key: found["high"][key] for key in ("applied", "dropped", "dropped_by_reason",
                                                              "line_edits_dropped_by_reason")},
                         {"applied": 4, "dropped": 2, "dropped_by_reason": {"quote": 2},
                          "line_edits_dropped_by_reason": {"cite": 4}})

    def test_the_curation_record_s_attempts_are_kept_in_the_package_s_names_from_a_time_on(self):
        record = {"recent": [
            {"at": "2026-11-13T00:00:05.000Z", "kind": "curate", "result": "ok", "applied": 3, "dropped": 1,
             "reasons": {"quote": 1}, "edit_reasons": {"cite": 1}, "state": "new", "run": "r_1"},
            {"at": "2026-11-13T00:00:01.000Z", "kind": "curate", "result": "failed", "error": "limit"}]}
        self.assertEqual(measure.attempts(record), [
            {"kind": "curate", "result": "ok", "applied": 3, "dropped": 1, "reasons": {"quote": 1},
             "edit_reasons": {"cite": 1}, "state": "new"},
            {"kind": "curate", "result": "failed", "error": "limit"}])
        self.assertEqual(len(measure.attempts(record, "2026-11-13T00:00:02.000Z")), 1)
        self.assertEqual(measure.attempts({}), [])
        self.assertRegex(measure.moment(), r"\A\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z\Z")

    def test_a_language_is_korean_with_a_hangul_letter_english_with_latin_ones_only_else_none(self):
        self.assertEqual([measure.language(text) for text in ("응", "ㅇㅋ go", "go on", "1234 !!", "", "日本語")],
                         ["ko", "ko", "en", "none", "none", "none"])

    def test_the_share_that_recall_skips_is_counted_by_the_package_s_own_rule(self):
        prompts = [{"source": "chat", "text": text} for text in (
            "응", "  ㅇㅋ 진행  ", "이 결정을 다시 알려 줘", "go on", "Which file holds it?", "/status now", "1234",
            "가나다라")]  # The last is four syllables in NFD.
        prompts[4]["source"] = "session"
        found = measure.skip_share(prompts, 8, recall.skipped)
        self.assertEqual(found["all"], {"prompts": 8, "short": 5, "command": 1, "skipped": 6, "share": 0.75})
        self.assertEqual(found["by_language"]["ko"], {"prompts": 4, "short": 3, "command": 0, "skipped": 3,
                                                      "share": 0.75})
        self.assertEqual(found["by_language"]["en"], {"prompts": 3, "short": 1, "command": 1, "skipped": 2,
                                                      "share": 0.667})
        self.assertEqual(found["by_language"]["none"]["skipped"], 1)
        self.assertEqual(found["by_source"]["session"], {"prompts": 1, "short": 0, "command": 0, "skipped": 0,
                                                         "share": 0.0})
        # The command is no short prompt at any value; a Hangul syllable counted as 2 keeps the Korean of 4 to 7.
        self.assertEqual(found["short_at_other_values"]["8"], {"all": 5, "ko": 3, "en": 1, "none": 1})
        self.assertEqual(found["short_at_other_values"]["4"], {"all": 1, "ko": 1, "en": 0, "none": 0})
        self.assertEqual(found["short_when_a_hangul_syllable_counts_2"]["8"], {"all": 4, "ko": 2, "en": 1, "none": 1})
        self.assertEqual(found["skipped_prompts"][:2], [
            {"number": 1, "language": "ko", "why": "short", "characters": 1},
            {"number": 2, "language": "ko", "why": "short", "characters": 5}])
        self.assertEqual(found["skipped_prompts"][-1], {"number": 8, "language": "ko", "why": "short", "characters": 4})
        self.assertEqual(found["characters"]["min"], 1)
        text = json.dumps(found, ensure_ascii=False)
        for prompt in prompts:
            self.assertNotIn(prompt["text"].strip(), text)

    def test_the_spread_and_the_percentile_of_some_numbers(self):
        self.assertEqual(measure.spread([3, None, 1, 2]), {"min": 1, "median": 2, "max": 3, "values": 3})
        self.assertIsNone(measure.spread([None]))
        self.assertEqual([measure.percentile(list(range(1, 21)), share) for share in (0.5, 0.95, 1.0)], [10, 19, 20])
        self.assertEqual(measure.percentile([7], 0.95), 7)

    def test_a_failed_embedding_of_the_items_stops_the_recall_part(self):
        lines = [usage(call="embed-items", input=30, cost=0.000001, total_ms=40),
                 usage(call="embed-items", input=10, cost=0.0, total_ms=20)]
        self.assertEqual(measure.embedded(lines, dims=512), {"dims": 512, "requests": 2, "input": 40, "usd": 1e-06,
                                                             "ms": 60})
        with self.assertRaises(real.Stopped) as stopped:
            measure.embedded(lines + [usage(call="embed-items", result="failed", error="insufficient_quota")])
        self.assertIn("insufficient_quota", str(stopped.exception))

    def recall_entry(self):
        def asked(outcome, ms, scores, scored="in the hook's time", embed=100):
            return {"outcome": outcome, "ms": ms, "embed_ms": embed, "scored": scored,
                    "candidates": [{"item": "i_%d" % number, "score": score} for number, score in scores]}

        return {"rebuilds": [{"dims": 1536, "requests": 2, "input": 90, "usd": 0.000002, "ms": 300}],
                "stages": [{"prompts": []}, {"prompts": [
                    {"512": asked("below", 400.0, [(1, 0.5), (2, 0.4), (3, 0.3), (4, 0.2), (5, 0.1)]),
                     "1536": asked("below", 500.0, [(1, 0.45), (3, 0.35)])},
                    {"512": asked("late", 950.0, [(2, 0.6)], "with 30 seconds", None),
                     "1536": asked("below", 450.0, [(4, 0.7), (2, 0.2)])},
                    {"512": asked("short", 200.0, [], embed=None), "1536": asked("short", 210.0, [], embed=None)}]}]}

    def test_the_recall_part_is_read_at_each_length(self):
        entry = self.recall_entry()
        found = measure.by_length(entry, 512)
        self.assertEqual({key: found[key] for key in ("prompts", "outcomes", "scored_with_more_time", "ranked")},
                         {"prompts": 3, "outcomes": {"below": 1, "late": 1, "short": 1}, "scored_with_more_time": 1,
                          "ranked": 2})
        self.assertEqual(found["hook_ms"], {"min": 200.0, "median": 400.0, "max": 950.0, "values": 3, "p95": 950.0})
        self.assertEqual(found["hook_ms_of_ranked_in_time"]["values"], 1)
        self.assertEqual(found["embed_ms"], {"min": 100, "median": 100, "max": 100, "values": 1})
        self.assertEqual(found["best_score"], {"min": 0.5, "median": 0.55, "max": 0.6, "values": 2})
        self.assertEqual(found["fifth_score"], {"min": 0.1, "median": 0.1, "max": 0.1, "values": 1})
        self.assertEqual(found["rebuilds"]["times"], 0)
        self.assertEqual(measure.by_length(entry, 1536)["rebuilds"], {"times": 1, "requests": 2, "input": 90,
                                                                      "usd": 2e-06, "ms": 300})
        self.assertEqual(measure.by_length({"stages": [], "rebuilds": []}, 512)["hook_ms"], None)

    def test_two_lengths_are_compared_over_the_prompts_that_both_ranked(self):
        found = measure.between(self.recall_entry(), 512, 1536)
        self.assertEqual(found, {"dims": [512, 1536], "prompts_ranked_at_both": 2, "same_best_item": 1,
                                 "shared_candidates": {"min": 1, "median": 1.5, "max": 2, "values": 2},
                                 "best_score_difference": {"min": -0.05, "median": 0.025, "max": 0.1, "values": 2}})
        self.assertEqual(measure.between({"stages": []}, 512, 1536), {"dims": [512, 1536], "prompts_ranked_at_both": 0})

    def test_the_check_holds_only_when_every_step_was_measured_and_every_file_was_searched(self):
        whole = {"runs": {"a": {"outcome": "measured"}}, "skip": {"outcome": "measured"},
                 "recall": {"outcome": "measured"}}
        self.assertTrue(measure.passed(whole))
        self.assertEqual(measure.ended(whole), {"a": "measured", "skip": "measured", "recall": "measured"})
        for change in ({"runs": {"a": {"outcome": "partial"}}}, {"runs": {"a": {"outcome": "not run"}}},
                       {"recall": {"outcome": "crash"}}, {"skip": {"outcome": "not run"}}, {"crash": "x"},
                       {"files_with_key": ["a"]}, {"key_in_report": True}, {"local_requests_with_key": 1},
                       {"files_not_read": ["b"]}):
            with self.subTest(change):
                self.assertFalse(measure.passed(dict(whole, **change)))
        self.assertFalse(measure.passed({"runs": {}}))
        self.assertFalse(measure.passed({}))

    def test_the_summary_tells_a_report_that_did_not_begin_and_one_with_every_part(self):
        self.assertEqual(measure.summary({"release": "0.3.0", "provider": "p", "crash": "broke"})[1], "broke")
        report = {"release": "0.3.0", "provider": "p", "system": {"platform": "x", "python": "3"}, "checkout": {},
                  "keys": {}, "runs": {"one-high-1": measured_run(), "one-low-1": {"outcome": "crash", "crash": "C"}},
                  "estimates": {}, "by_effort": {"high": {}}, "skip": {"outcome": "measured", "skipped_prompts": [1]},
                  "recall": {"outcome": "partial", "why": ["w"], "by_dims": {"512": {}},
                             "between_the_lengths": [{}]}, "files_with_key": ["f"], "files_not_read": ["g"],
                  "crash": "ended"}
        text = "\n".join(measure.summary(report))
        for part in ("one-high-1: working 2000, safe 4000, count 3000 (safe/count 1.333)", "changes dropped: 1",
                     'one-low-1: crash "C"',
                     "effort high", "recall.skip", 'recall: partial ["w"]', "512 numbers", "between the lengths",
                     "A MEMORY KEY OF THIS ENVIRONMENT WAS FOUND", "could not be read", "ended"):
            self.assertIn(part, text)
        self.assertNotIn("skipped_prompts", text)


class CheckTests(unittest.TestCase):
    def check(self, **values):
        check = measure.Measure.__new__(measure.Measure)
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(home), True)
        check.real, check.embedding, check.plugin = True, False, Path("plugin")
        check.keys = {ANTHROPIC: "REAL-ANTHROPIC", OPENAI: "REAL-OPENAI"}
        check.markers = {ANTHROPIC: "MARKER-ANTHROPIC", OPENAI: "MARKER-OPENAI"}
        check.server = SimpleNamespace(url="http://127.0.0.1:9")
        for name, value in values.items():
            setattr(check, name, value)
        return check, home

    def test_the_worker_gets_the_embedding_key_in_the_recall_part_only(self):
        check, home = self.check()
        with mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://proxy.invalid:1"}):
            env = check.worker_environment(home, True)
            self.assertEqual((env.get(ANTHROPIC), env.get(OPENAI), env.get("HTTPS_PROXY")),
                             ("REAL-ANTHROPIC", None, "http://proxy.invalid:1"))
            check.embedding = True
            self.assertEqual(check.worker_environment(home, True).get(OPENAI), "REAL-OPENAI")
        check, home = self.check(real=False)
        env = check.worker_environment(home, True)
        self.assertEqual((env.get(ANTHROPIC), env.get(OPENAI)), ("MARKER-ANTHROPIC", None))
        self.assertEqual(env["CORTHEX_MEMORY_ANTHROPIC_BASE_URL"], "http://127.0.0.1:9")

    def test_a_recall_s_hook_gets_the_embedding_key_alone_and_a_self_test_s_goes_to_the_local_server(self):
        check, home = self.check()
        with mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://proxy.invalid:1"}):
            env = check.recall_environment(home, "codex")
        self.assertEqual((env.get(OPENAI), env.get(ANTHROPIC), env.get("HTTPS_PROXY"), env.get("PLUGIN_ROOT")),
                         ("REAL-OPENAI", None, "http://proxy.invalid:1", "plugin"))
        self.assertFalse([name for name in env if name.endswith("_BASE_URL")])
        check, home = self.check(real=False)
        env = check.recall_environment(home, "claude")
        self.assertEqual((env.get(OPENAI), env.get(ANTHROPIC), env.get("CORTHEX_MEMORY_OPENAI_BASE_URL"),
                          env.get("CLAUDECODE")), ("MARKER-OPENAI", None, "http://127.0.0.1:9", "1"))

    def test_the_steps_are_each_sample_at_each_effort_and_then_the_other_parts(self):
        check, _ = self.check(samples=[{"id": "a"}, {"id": "b"}],
                              options=SimpleNamespace(part=["efforts", "skip", "recall"], effort=["low", "max"],
                                                      repeat=2))
        steps = check.steps()
        self.assertEqual([(step[0],) + ((step[1]["id"],) + step[2:] if len(step) > 1 else ()) for step in steps],
                         [("efforts", "a", "low", 1), ("efforts", "a", "low", 2), ("efforts", "a", "max", 1),
                          ("efforts", "a", "max", 2), ("efforts", "b", "low", 1), ("efforts", "b", "low", 2),
                          ("efforts", "b", "max", 1), ("efforts", "b", "max", 2), ("skip",), ("recall",)])
        check.options.part = ["skip"]
        self.assertEqual(check.steps(), [("skip",)])

    def test_a_step_that_breaks_or_is_stopped_is_noted_and_an_interrupt_is_raised_again(self):
        check, _ = self.check(spent=0.0, options=SimpleNamespace(limit=1.0))

        def broke():
            raise RuntimeError("it broke with REAL-ANTHROPIC in its text")

        def stopped():
            raise real.Stopped("no index")

        def interrupted():
            raise KeyboardInterrupt()

        entry = {"outcome": "not run"}
        check.guard(entry, broke)
        self.assertEqual(entry["outcome"], "crash")
        self.assertIn("it broke with <memory key> in its text", entry["crash"])
        entry = {"outcome": "not run"}
        check.guard(entry, stopped)
        self.assertEqual(entry, {"outcome": "not run", "why": "no index"})
        entry = {"outcome": "not run"}
        with self.assertRaises(KeyboardInterrupt):
            check.guard(entry, interrupted)
        self.assertEqual(entry["why"], "interrupted during this run")

    def test_no_step_that_costs_starts_at_the_limit_and_the_skip_share_still_does(self):
        check, _ = self.check(spent=1.0, options=SimpleNamespace(limit=1.0))
        ran = []
        entry = {"outcome": "not run"}
        check.guard(entry, lambda: ran.append("cost"))
        self.assertEqual((ran, entry["outcome"]), ([], "not run"))
        self.assertIn("has reached the limit", entry["why"])
        check.guard({"outcome": "not run"}, lambda: ran.append("free"), free=True)
        self.assertEqual(ran, ["free"])

    def test_a_prompt_whose_recall_ended_late_is_asked_once_more_with_more_time(self):
        home = measure.Home.__new__(measure.Home)
        asked = []

        def ask(host, prompt, seconds=None):
            asked.append(seconds)
            late = {"ms": 950.0, "outcome": "late", "candidates": [], "embed_ms": 800, "embed_error": "timeout"}
            ranked = {"ms": 1500.0, "outcome": "below", "candidates": [{"item": "i_1", "score": 0.4}],
                      "embed_ms": 1200, "embed_error": None}
            return late if seconds is None else ranked

        home.ask = ask
        found = home.recalled("claude", "prompt")
        self.assertEqual(asked, [None, measure.MORE_SECONDS])
        self.assertEqual(found, {"outcome": "late", "ms": 950.0, "embed_ms": 800, "embed_error": "timeout",
                                 "scored": "with 30 seconds", "outcome_with_more_time": "below",
                                 "candidates": [{"item": "i_1", "score": 0.4}]})
        home.ask = lambda host, prompt, seconds=None: {"ms": 300.0, "outcome": "short", "candidates": [],
                                                       "embed_ms": None, "embed_error": None}
        self.assertEqual(home.recalled("claude", "응"), {"outcome": "short", "ms": 300.0, "embed_ms": None,
                                                        "scored": "in the hook's time", "candidates": []})

    def test_the_local_server_counts_by_the_request_s_size_and_notes_each_effort(self):
        server = measure.Counting()
        self.addCleanup(server.close)
        body = {"model": "m", "system": "s", "messages": [{"role": "user", "content": "x" * 300}]}
        self.assertEqual(server.count(body), 500 + len(json.dumps(body)) // 3)
        self.assertEqual(sorted(server.scripts), sorted(measure.SCRIPTS))


class WrapperTests(unittest.TestCase):
    def test_a_request_is_sized_as_the_package_sizes_it(self):
        schema = {"type": "object", "properties": {"가": {"type": "string"}}}
        source = "<request kind=\"curate\">결정: 한글과 ASCII가 섞인 문서입니다.</request>"
        found = worker.sized(memory_lib, model_prompts.CURATE, schema, source)
        whole = model_prompts.PROMPTS[model_prompts.CURATE] + json.dumps(schema, ensure_ascii=False) + source
        self.assertEqual(found["estimate"], request_budget.estimate(model_prompts.CURATE, schema, source))
        self.assertEqual(found["working"], found["estimate"])
        self.assertEqual(found["safe"], request_budget.safe(whole))
        self.assertEqual(found["ascii"] + found["other"], len(whole))
        self.assertEqual(found["other"], sum(1 for character in whole if ord(character) > 127))
        self.assertEqual((found["working"], found["safe"]),
                         (-(-found["ascii"] // 4) + found["other"], -(-found["ascii"] // 2) + 2 * found["other"]))

    def test_a_line_is_added_and_one_that_cannot_be_written_is_left_out(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(folder), True)
        tap = folder / "requests.jsonl"
        self.assertTrue(worker.note(tap, {"kind": "count", "tokens": 7, "text": "반\ud83d"}))
        self.assertTrue(worker.note(tap, {"kind": "count", "tokens": 8}))
        rows = [json.loads(text) for text in tap.read_text(encoding="utf-8").split("\n") if text]
        self.assertEqual([row["tokens"] for row in rows], [7, 8])
        self.assertEqual(rows[0]["text"], "반\ud83d")
        self.assertFalse(worker.note(folder / "none/requests.jsonl", {"kind": "count"}))
        self.assertFalse(worker.note(tap, {"kind": object()}))

    def test_a_document_s_digest_is_that_of_its_utf_8_bytes(self):
        self.assertEqual(worker.digest("문서"), hashlib.sha256("문서".encode("utf-8")).hexdigest())
        self.assertEqual(len(worker.digest("half \ud83d")), 64)


class SelfTestRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, cls.base, True)
        environment = dict(os.environ, CI="true")
        environment.update({ANTHROPIC: SECRETS[0], OPENAI: SECRETS[1]})
        # Started as a person starts it, by its path from the checkout.
        cls.done = subprocess.run(
            [sys.executable, str(Path(".github/hook-check/c2_measure.py")), cls.base, "--self-test", "--effort",
             "medium", "--effort", "xhigh", "--part", "efforts", "--part", "skip", "--part", "recall"],
            cwd=str(ROOT), env=environment, capture_output=True, timeout=1200)
        cls.output = cls.done.stdout.decode("utf-8", "replace")
        cls.out = Path(cls.base) / "c2-measure"
        try:
            cls.text = (cls.out / "report.json").read_text(encoding="utf-8")
            cls.report = json.loads(cls.text)
        except (OSError, ValueError):
            cls.text, cls.report = "", {}

    def test_it_runs_to_its_end_against_the_local_server_even_in_ci(self):
        self.assertEqual((self.done.returncode, self.done.stderr.decode("utf-8", "replace")), (0, ""), self.output)
        self.assertIn(real.SELF_TEST, self.output.splitlines()[0])
        report = self.report
        self.assertTrue(report["self_test"])
        self.assertEqual((report["parts"], report["efforts"], report["dims"]),
                         (["efforts", "skip", "recall"], ["medium", "xhigh"], [512, 1536]))
        self.assertEqual(measure.ended(report), dict(
            {"%s-%s-1" % (sample, effort): "measured" for sample in ("made-up-ko", "made-up-en")
             for effort in ("medium", "xhigh")}, skip="measured", recall="measured"))
        self.assertEqual((report["files_with_key"], report["local_requests_with_key"], report["files_not_read"]),
                         ([], 0, []))
        self.assertNotIn("key_in_report", report)
        self.assertEqual(report["keys"], {ANTHROPIC: "present", OPENAI: "present"})

    def test_each_request_has_its_count_its_estimates_and_its_run_s_effort(self):
        for name, entry in self.report["runs"].items():
            with self.subTest(name):
                self.assertEqual(len(entry["requests"]), 1)
                row = entry["requests"][0]
                self.assertEqual((row["effort"], row["result"], row["count_calls"], row["usage_lines"]),
                                 (entry["effort"], "ok", 1, 1))
                self.assertTrue(row["estimate_agrees"])
                self.assertGreater(row["count"], 500)
                self.assertEqual((row["working"], row["safe"]),
                                 (-(-row["ascii"] // 4) + row["other"], -(-row["ascii"] // 2) + 2 * row["other"]))
                self.assertEqual(row["safe_at_or_above_count"], row["safe"] >= row["count"])
                # The efforts part sends no embedding: its worker has no embedding key.
                self.assertEqual(sorted(entry["usage"]), ["count-tokens", "curate"])
                self.assertEqual(entry["layer"]["turns_left_to_curate"], 0)
                self.assertEqual([(attempt["kind"], attempt["result"], attempt["dropped"])
                                  for attempt in entry["attempts"]], [("curate", "ok", 0)])
        self.assertEqual(self.report["runs"]["made-up-ko-xhigh-1"]["layer"]["items"], 2)
        self.assertEqual(self.report["runs"]["made-up-ko-xhigh-1"]["layer"]["state_lines_with_korean_text"], 2)
        self.assertEqual(self.report["runs"]["made-up-en-medium-1"]["requests"][0]["changes"], {"add decision": 1})
        # The two samples at two efforts, and the recall part's two curations at the default.
        self.assertEqual(self.report["efforts_that_the_local_server_got"], {"medium": 2, "xhigh": 4})
        self.assertEqual(self.report["by_effort"]["medium"]["runs"], 2)
        self.assertEqual(self.report["estimates"]["documents_counted"], self.report["estimates"]["requests"])

    def test_the_share_that_recall_skips_is_that_of_the_made_up_prompts(self):
        skip = self.report["skip"]
        self.assertEqual(skip["recall_skip"], 8)
        self.assertEqual(skip["all"], {"prompts": 9, "short": 5, "command": 1, "skipped": 6, "share": 0.667})
        self.assertEqual({name: value["prompts"] for name, value in skip["by_language"].items()},
                         {"ko": 4, "en": 4, "none": 1})

    def test_each_prompt_is_ranked_against_the_items_of_the_samples_before_it_at_both_lengths(self):
        recall_part = self.report["recall"]
        first, second = recall_part["stages"]
        self.assertEqual((first["sample"], first["current_items_before"], first["prompts"]), ("made-up-ko", 0, []))
        self.assertEqual((second["sample"], second["current_items_before"], len(second["prompts"])),
                         ("made-up-en", 2, 1))
        texts = json.loads((self.out / "recall-texts.json").read_text(encoding="utf-8"))
        row = second["prompts"][0]
        self.assertEqual((row["turn"], row["host"], row["language"]), (1, "claude", "en"))
        for dims in ("512", "1536"):
            with self.subTest(dims):
                asked = row[dims]
                # A slow system may end the hook's recall late; the prompt is then scored with more time.
                self.assertIn(asked["outcome"], ("below", "late"))
                self.assertEqual(asked["scored"] == "in the hook's time", asked["outcome"] == "below")
                self.assertEqual(len(asked["candidates"]), 2)
                self.assertEqual(sorted(value["item"] for value in asked["candidates"]), sorted(texts["items"]))
                self.assertGreater(asked["ms"], 0)
                self.assertEqual(recall_part["by_dims"][dims]["ranked"], 1)
        self.assertEqual([(value["dims"], value["items"], value["before"]) for value in recall_part["rebuilds"]],
                         [(1536, 2, "made-up-en")])
        self.assertGreaterEqual(recall_part["rebuilds"][0]["requests"], 1)
        self.assertEqual(recall_part["between_the_lengths"][0]["prompts_ranked_at_both"], 1)
        # The texts for the judging are beside the report, and the prompt that was asked was recorded once.
        self.assertEqual(texts["prompts"], [{"sample": "made-up-en", "turn": 1,
                                             "text": measure.MADE_UP[1]["turns"][0]["prompt"]}])
        self.assertEqual(sorted(value["title"] for value in texts["items"].values()),
                         sorted(script["title"] for script in list(measure.SCRIPTS.values())[:2]))
        entries = [json.loads(text) for path in sorted(
            (self.out / "recall/home/.corthex/corthex-memory/projects/demo/raw").glob("*.jsonl"))
            for text in path.read_text(encoding="utf-8").split("\n") if text]
        self.assertEqual(dict(real.Counter(entry["kind"] for entry in entries)), {"prompt": 3, "answer": 3})

    def test_the_report_has_no_text_of_a_sample_and_no_key_and_nothing_left_bytecode(self):
        self.assertTrue(self.text)
        for sample in measure.MADE_UP:
            for turn in sample["turns"]:
                self.assertNotIn(turn["prompt"], self.text)
                self.assertNotIn(turn["reply"], self.text)
        for script in measure.SCRIPTS.values():
            self.assertNotIn(script["title"], self.text)
            self.assertNotIn(script["text"], self.text)
        for prompt in measure.MADE_UP_PROMPTS:
            if len(prompt["text"]) > 4:
                self.assertNotIn(prompt["text"], self.text)
        for secret in SECRETS:
            self.assertNotIn(secret, self.text)
            self.assertNotIn(secret, self.output)
        self.assertEqual([path.relative_to(self.out).as_posix() for path in self.out.rglob("*")
                          if path.name == "__pycache__" or path.suffix == ".pyc"], [])

    def test_the_hook_with_more_time_ranks_a_prompt_whose_embedding_comes_too_late_for_the_hook(self):
        self.assertEqual(self.done.returncode, 0, self.output)
        home, demo = self.out / "recall/home", self.out / "recall/work/demo"
        plugin = self.out / "source/plugins/corthex-memory"
        root = home / ".corthex/corthex-memory/projects/demo"
        vector = hosts.vector

        def slow(text, dims=hosts.DIMS):
            time.sleep(1.5)  # Past the 0.8 s that the hook gives the prompt's embedding.
            return vector(text, dims)

        # The prompt is left out of recording, as the check's own recall runs leave it out.
        path = home / ".corthex/corthex-memory/configuration.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["projects"]["demo"]["left_out"] = {"kinds": ["prompt"]}
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        server = hosts.MemoryServer()
        self.addCleanup(server.close)
        env = real.hookcheck.base_env(home)
        env.update({OPENAI: "MARKEROPENAI-OF-THIS-TEST", "CLAUDECODE": "1", "CLAUDE_PLUGIN_ROOT": str(plugin)})
        env.update(hosts.memory_urls(server.url))
        prompt = "Which file keeps the numbers of a measurement run?"

        def ask(command):
            session = str(uuid.uuid4())
            data = json.dumps(real.host_input("claude", "UserPromptSubmit", demo, session, str(uuid.uuid4()),
                                              prompt=prompt)).encode("utf-8")
            done = subprocess.run(command, input=data, env=env, cwd=str(demo), capture_output=True, timeout=120)
            self.assertEqual((done.returncode, done.stderr), (0, b""))
            lines = [value for _, value in hosts.injection_lines(root) if value.get("session") == session]
            self.assertEqual(len(lines), 1)
            return lines[0]

        with mock.patch.object(hosts, "vector", slow):
            late = ask([sys.executable, str(plugin / "scripts/hook.py"), "prompt"])
            more = ask([sys.executable, str(FOLDER / "c2_measure_hook.py"), str(plugin), "30"])
        self.assertEqual((late["outcome"], late.get("candidates")), ("late", None))
        self.assertEqual(more["outcome"], "below")
        self.assertEqual(len(more["candidates"]), 3)
        self.assertEqual([path.relative_to(self.out).as_posix() for path in self.out.rglob("*")
                          if path.name == "__pycache__" or path.suffix == ".pyc"], [])


if __name__ == "__main__":
    unittest.main()
