"""TASK-047: the readings, refusals and wrappers of the measurement check, and its self-test.

No provider is called here: the readings get made-up request lines, usage lines and layers, and the one run of the
script and the worker's flows at the end answer every request from a local server.
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


def moment(second, part=0):
    """A time as the package writes one: `second` seconds and `part` thousandths into a made-up minute."""
    return "2026-11-13T00:00:%02d.%03dZ" % (second, part)


def digest(document):
    return hashlib.sha256(document.encode("utf-8")).hexdigest()


def request(document="a", instructions="curate-3", attempts=1, failure=None, answer=None, second=1, **more):
    """A request's line of requests.jsonl, as c2_measure_worker.py writes it: sent in the second `second`."""
    row = {"kind": "request", "instructions": instructions, "document": "<request>%s</request>" % document,
           "answer": json.dumps(answer if answer is not None else {"changes": [], "state": {
               "change": [], "add": [], "remove": []}}),
           "failure": failure, "attempts": attempts, "model": "model-x", "effort": "high", "max_tokens": 64000,
           "source_sha256": digest(document), "ascii": 4000, "other": 1000, "working": 2000, "safe": 4000,
           "estimate": 2000, "size": {"turns": 1, "list": "full", "estimate": 2000},
           "began": moment(second), "ended": moment(second, 900), "logged": attempts}
    row.update(more)
    return row


def raised(document="a", instructions="curate-3", second=1, error="LostLock"):
    """The line of a call of `send` that raised an error."""
    row = request(document, instructions, second=second, raised=error)
    return {key: value for key, value in row.items() if key not in ("document", "answer", "failure", "attempts",
                                                                     "logged")}


def count(document="a", tokens=3000, failure=None, instructions="curate-3"):
    return {"kind": "count", "instructions": instructions, "tokens": tokens, "failure": failure,
            "source_sha256": digest(document)}


def sized(document="a", counted=3000, counts=1, instructions="curate-3", part=None):
    """The line of a request that the package sized, with the count that let it go."""
    return {"kind": "sized", "instructions": instructions, "source_sha256": digest(document), "counted": counted,
            "counts": counts, "part": part}


def index(reason="done", failed=(), embedded=0, **more):
    """The line of a run's index step."""
    row = {"kind": "index", "reason": reason, "rebuilt": None, "written": 0, "removed": 0, "embedded": embedded,
           "requests": 1 if embedded or failed else 0, "failed": list(failed)}
    row.update(more)
    return row


def usage(call="curate", result="ok", instructions="curate-3", second=1, **more):
    """A usage line of an attempt that began in the second `second`."""
    row = {"at": moment(second, 500), "call": call, "result": result, "instructions": instructions, "input": 3000,
           "output": 400, "cache_write": 0, "cache_read": 0, "first_ms": 900, "total_ms": 1000, "cost": 0.001,
           "estimate": 2000, "list": "full", "turns": 1}
    row.update(more)
    return row


def run(rows=(), lines=()):
    """A run of the worker as a home gives it: its lines of requests.jsonl and of the usage log."""
    return {"requests": list(rows), "usage": list(lines), "failures": [], "seconds": 1.5}


def layer(items=(), lines=(), candidates=(), waiting=0):
    return {"items": {value["id"]: value for value in items}, "lines": list(lines),
            "candidates": list(candidates), "waiting": waiting}


def item(number, kind="decision", status="current", title="제목", text="본문"):
    return {"id": "i_%012d" % number, "kind": kind, "status": status, "title": title, "text": text,
            "quotes": [{"entry": "e_%012d" % number}]}


def measured_run(effort="high", **more):
    row = measure.joined([count(), sized(), request()], [usage()])[0]
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

    def prompts(self, *texts):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(folder), True)
        path = folder / "prompts.json"
        path.write_text(json.dumps([{"text": text, "source": "a test"} for text in texts], ensure_ascii=False),
                        encoding="utf-8")
        return path

    @staticmethod
    def report(base):
        return json.loads((base / "c2-measure/report.json").read_text(encoding="utf-8"))

    def test_the_part_skip_alone_sends_nothing_so_neither_ci_nor_a_missing_key_refuses_it(self):
        path = str(self.prompts("응", "이 결정을 다시 알려 줘", "/status"))
        for environment in ({}, {"CI": "true"}, {"GITHUB_ACTIONS": "true"}):
            with self.subTest(environment):
                code, text, base = self.run_main(["--part", "skip", "--prompts", path], **environment)
                report = self.report(base)
                self.assertEqual((code, report["self_test"], measure.ended(report)), (0, False, {"skip": "measured"}))
                self.assertEqual(report["skip"]["all"], {"prompts": 3, "short": 1, "command": 1, "skipped": 2,
                                                         "share": 0.667})
                self.assertEqual(report["keys"], {ANTHROPIC: "missing", OPENAI: "missing"})
                self.assertEqual((report["cost"]["requests"], report["local_requests"]), (0, 0))
                # No home was made: the staged package and the report are all that the folder has.
                self.assertEqual(sorted(path.name for path in (base / "c2-measure").iterdir()),
                                 ["report.json", "source"])
        # Beside a part that sends, both refusals hold.
        arguments = ["--samples", str(self.samples()), "--part", "skip", "--part", "efforts", "--prompts", path]
        code, text, base = self.run_main(arguments, CI="true", **{ANTHROPIC: "made-up"})
        self.assertEqual((code, list(base.iterdir())), (2, []))
        self.assertIn("never run in CI", text)
        code, text, base = self.run_main(arguments)
        self.assertEqual((code, list(base.iterdir())), (2, []))
        self.assertIn(ANTHROPIC + " is not set", text)

    def test_nothing_is_run_when_a_sample_s_prompt_begins_as_one_that_a_host_makes(self):
        turn = SAMPLE["turns"][0]
        made = dict(SAMPLE, id="two",
                    turns=[turn, dict(turn, prompt="\n <task-notification>\nPROMPT-TEXT-OF-A-SAMPLE")])
        code, text, base = self.run_main(["--self-test", "--samples", str(self.samples(SAMPLE, made)), "--part",
                                          "efforts", "--part", "recall"])
        report = self.report(base)
        self.assertEqual((code, report["runs"], "recall" in report, report["local_requests"]), (1, {}, False, 0))
        self.assertTrue(report["crash"].startswith("Nothing was run. The prompt of turn 2 of the sample two begins "
                                                   "as one that a host makes (<task-notification>, "), report["crash"])
        self.assertNotIn("Traceback", report["crash"])
        self.assertEqual(text.splitlines()[-1], report["crash"])
        self.assertNotIn("PROMPT-TEXT", text + json.dumps(report))
        # Neither a hook nor a worker ran: no home was made.
        self.assertEqual(sorted(path.name for path in (base / "c2-measure").iterdir()), ["report.json", "source"])

    def test_a_sample_with_half_of_a_surrogate_pair_is_refused_before_anything_is_written(self):
        # As a text that was cut inside a character has one; JSON's escape of it reads as that half.
        folder = self.samples()
        (folder / "one.json").write_text(json.dumps(SAMPLE).replace("REPLY-TEXT", "REPLY\\ud83d-TEXT"),
                                         encoding="utf-8")
        code, text, base = self.run_main(["--self-test", "--samples", str(folder)])
        self.assertEqual((code, list(base.iterdir())), (2, []))
        self.assertIn("one.json is no sample: the reply of turn 1 has half of a surrogate pair", text)
        self.assertNotIn("TEXT-OF-A-SAMPLE", text)

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

    def test_a_sample_s_name_that_is_no_id_is_refused_before_it_is_part_of_a_path(self):
        # A file beside the folder of the samples, which a name with `..` would reach.
        folder = self.samples(dict(SAMPLE, id="outside")) / "samples"
        folder.mkdir()
        (folder / "one.json").write_text(json.dumps(SAMPLE), encoding="utf-8")
        for name in ("../outside", "One", "a/b", "", "a" * 41, "one.json"):
            with self.subTest(name):
                code, text, base = self.run_main(["--self-test", "--samples", str(folder), "--sample", name])
                self.assertEqual((code, list(base.iterdir())), (2, []))
                self.assertIn("--sample is a sample's id", text)
        with self.assertRaises(ValueError):
            measure.given(measure.options(["out", "--self-test", "--sample", "../made-up-en"]))

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
        # A character outside the basic plane is a whole pair in UTF-16 and one character here.
        whole = dict(SAMPLE, turns=[dict(SAMPLE["turns"][0], prompt="\U0001f600 as JSON's \\ud83d\\ude00 reads")])
        self.assertEqual(measure.valid(json.loads(json.dumps(whole)), "one.json"), whole)

    def test_what_is_no_sample_is_refused_with_the_file_s_name_and_none_of_its_text(self):
        turn = SAMPLE["turns"][0]
        for change, why in (({"turns": []}, "no list of turns"), ({"turns": "x"}, "no list of turns"),
                            ({"id": "One"}, "its id"), ({"id": "../one"}, "its id"), ({"id": "a" * 41}, "its id"),
                            ({"id": 7}, "its id"), ({"kind": ""}, "its kind"), ({"source": "s" * 41}, "its source"),
                            ({"turns": [dict(turn, host="gemini")]}, "turn 1 names no host"),
                            ({"turns": [turn, dict(turn, prompt="  ")]}, "turn 2 has no prompt"),
                            ({"turns": [dict(turn, reply=None)]}, "turn 1 has no reply"),
                            ({"turns": ["x"]}, "turn 1 names no host"),
                            # Half of a surrogate pair, which no hook can be given as UTF-8.
                            ({"turns": [dict(turn, prompt="cut \ud83d")]},
                             "the prompt of turn 1 has half of a surrogate pair"),
                            ({"turns": [turn, dict(turn, reply="\ude00 cut")]},
                             "the reply of turn 2 has half of a surrogate pair")):
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

    def test_a_file_that_begins_with_a_byte_order_mark_is_read_as_one_without(self):
        # As an editor on Windows may save it.
        folder = self.folder()
        (folder / "one.json").write_bytes(b"\xef\xbb\xbf" + json.dumps(SAMPLE).encode("utf-8"))
        (folder / "p.txt").write_bytes(b"\xef\xbb\xbf" + json.dumps([{"text": "가", "source": "chat"}],
                                                                    ensure_ascii=False).encode("utf-8"))
        self.assertEqual(measure.samples_of(folder, []), [SAMPLE])
        self.assertEqual(measure.prompts_of(folder / "p.txt"), [{"source": "chat", "text": "가"}])
        (folder / "one.json").write_bytes(json.dumps(SAMPLE).encode("utf-8"))
        self.assertEqual(measure.samples_of(folder, ["one"]), [SAMPLE])

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
    def test_a_request_gets_the_count_that_let_it_go_and_the_usage_line_of_its_time(self):
        rows = [count("a", 3000), sized("a", 3000), request("a"), count("b", 500), sized("b", 500),
                request("b", second=2, safe=400, working=200, estimate=200)]
        lines = [usage(call="count-tokens", instructions=None), usage(cache_read=200, cache_write=100),
                 usage(call="count-tokens", instructions=None, second=2),
                 usage(second=2, estimate=200, input=480, output=10, cost=0.0002)]
        first, second = measure.joined(rows, lines)
        self.assertEqual({key: first[key] for key in (
            "count", "count_calls", "count_is_of_this_document", "input", "output", "usd", "result", "usage_lines",
            "logged", "estimate_agrees", "safe_at_or_above_count", "safe_over_count", "working_over_count", "effort",
            "model", "list", "turns")},
            {"count": 3000, "count_calls": 1, "count_is_of_this_document": True, "input": 3300, "output": 400,
             "usd": 0.001, "result": "ok", "usage_lines": 1, "logged": 1, "estimate_agrees": True,
             "safe_at_or_above_count": True, "safe_over_count": 1.333, "working_over_count": 0.667, "effort": "high",
             "model": "model-x", "list": "full", "turns": 1})
        self.assertEqual((second["count"], second["input"], second["safe_at_or_above_count"],
                          second["safe_over_count"]), (500, 480, False, 0.8))
        # Neither the document nor the answer is kept: their sizes are.
        self.assertEqual((first["document_bytes"], first["answer_bytes"]),
                         (len("<request>a</request>"), len(request("a")["answer"])))
        self.assertFalse({"document", "answer", "size", "began", "ended", "part", "raised"} & set(first))

    def test_a_request_that_was_tried_again_takes_a_line_for_each_attempt_and_reads_the_last(self):
        rows = [sized("a"), request("a", attempts=2), sized("b"), request("b", second=2)]
        lines = [usage(result="failed", error="overloaded", cost=0.0, output=0, input=0), usage(output=700, cost=0.002),
                 usage(second=2, output=5, cost=0.0001)]
        first, second = measure.joined(rows, lines)
        self.assertEqual((first["usage_lines"], first["result"], first["output"], first["usd"]), (2, "ok", 700, 0.002))
        self.assertEqual((second["usage_lines"], second["output"]), (1, 5))

    def test_requests_of_other_instructions_take_their_own_usage_lines(self):
        # Both in the same second: a line is its request's only with that request's instructions.
        rows = [request("a"), request("m", instructions="merge-2", answer={"merges": [{}], "conflicts": []})]
        lines = [usage(call="consolidate", instructions="merge-2", output=9), usage(output=8)]
        first, second = measure.joined(rows, lines)
        self.assertEqual((first["output"], second["output"], second["merges"], second["conflicts"]), (8, 9, 1, 0))

    def test_a_line_that_a_call_wrote_before_it_raised_is_that_call_s_and_no_later_request_s(self):
        # The first call logged an attempt and then raised: the package's check failed after the answer.
        rows = [sized("a"), raised("a"), sized("a"), request("a", second=3)]
        lines = [usage(output=11, cost=0.004), usage(second=3, output=22)]
        first, second = measure.joined(rows, lines)
        self.assertEqual((first["raised"], first["usage_lines"], first["logged"], first["output"], first["usd"],
                          first["attempts"], first["document_bytes"]), ("LostLock", 1, None, 11, 0.004, None, 0))
        self.assertEqual((second["usage_lines"], second["output"], second.get("raised")), (1, 22, None))
        found = {"requests": [first, second], "layer": {"turns_left_to_curate": 0}}
        self.assertEqual(measure.lacking(found), ["request 1 ended with the error LostLock"])
        # Paired by their order alone, the second request would have read the first call's line.
        self.assertEqual(measure.lacking({"requests": [second], "layer": {"turns_left_to_curate": 0}}), [])

    def test_a_request_takes_no_more_lines_than_its_call_wrote_and_none_outside_its_time(self):
        # Two requests whose times meet in one thousandth of a second, each with a line that began then.
        edge = moment(1, 900)
        rows = [request("a"), request("b", began=edge, ended=moment(2, 900))]
        lines = [usage(at=edge, output=1), usage(at=edge, output=2)]
        first, second = measure.joined(rows, lines)
        self.assertEqual((first["usage_lines"], first["output"], second["usage_lines"], second["output"]),
                         (1, 1, 1, 2))
        # A line from before a request began or from after it ended is not its line, nor is one without a time.
        late = dict(usage(second=5), output=3)
        row = measure.joined([request("a")], [late, {key: value for key, value in usage().items() if key != "at"}])[0]
        self.assertEqual((row["usage_lines"], row["result"]), (0, None))
        self.assertEqual(measure.joined([request("a", began=None)], [usage()])[0]["usage_lines"], 0)
        self.assertTrue(measure.within(request(), usage()))
        self.assertFalse(measure.within(request(), usage(second=2)))

    def test_a_count_is_the_one_of_the_latest_sizing_of_the_document_before_the_request(self):
        rows = [count("a", None, "timeout"), count("a", 2900), sized("a", 2900, 2), request("a"),
                count("a", 2950), sized("a", 2950, 1), request("a", second=2)]
        first, second = measure.joined(rows, [usage(), usage(second=2)])
        self.assertEqual((first["count"], first["count_calls"], second["count"], second["count_calls"]),
                         (2900, 2, 2950, 1))
        # A sizing of other instructions' request with the same document is not this request's.
        row = measure.joined([sized("a", 7, instructions="merge-2"), request("a")], [usage()])[0]
        self.assertEqual((row["count"], row["count_calls"]), (None, 0))

    def test_a_part_of_a_turn_has_the_count_of_its_provisional_document_and_says_so(self):
        # The count was made of the document with a provisional number of parts, which has another digest.
        rows = [count("part 1 of 999999", 60000), count("part 2 of 999999", 61000),
                sized("part 1 of 2", 60000, 1, part=[1, 2]), sized("part 2 of 2", 61000, 1, part=[2, 2]),
                request("part 1 of 2"), request("part 2 of 2", second=2)]
        first, second = measure.joined(rows, [usage(), usage(second=2)])
        self.assertEqual([(row["count"], row["count_calls"], row["part"], row["count_is_of_this_document"])
                          for row in (first, second)], [(60000, 1, [1, 2], False), (61000, 1, [2, 2], False)])
        self.assertEqual(measure.lacking({"requests": [first, second], "layer": {"turns_left_to_curate": 0}}), [])

    def test_a_request_without_a_count_or_a_usage_line_says_so_and_has_no_ratio(self):
        row = measure.joined([request("a")], [])[0]
        self.assertEqual((row["count"], row["result"], row["input"], row["usage_lines"], row["estimate_agrees"]),
                         (None, None, None, 0, False))
        self.assertNotIn("safe_over_count", row)
        self.assertNotIn("count_is_of_this_document", row)
        self.assertEqual(measure.lacking({"requests": [row], "layer": {"turns_left_to_curate": 0}}),
                         ["request 1 has no count", "request 1 ended with no usage line",
                          "request 1: the usage line's estimate is not the one that was computed again"])

    def test_an_estimate_of_the_usage_line_that_is_not_the_wrapper_s_is_told(self):
        row = measure.joined([sized(), request()], [usage(estimate=1999)])[0]
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
        whole = {"requests": measure.joined([sized(), request()], [usage()]), "layer": {"turns_left_to_curate": 0}}
        self.assertEqual(measure.lacking(whole), [])
        self.assertEqual(measure.lacking({"requests": [], "layer": {"turns_left_to_curate": 2}}),
                         ["no request was written", "2 turns are left to curate"])
        failed = measure.joined([sized(), request(failure="limit")], [usage(result="limit", error="max-tokens")])
        self.assertEqual(measure.lacking({"requests": failed, "layer": {"turns_left_to_curate": 0}}),
                         ["request 1 ended with limit"])
        self.assertEqual(measure.lacking(dict(whole, lines_left_out_because_they_are_no_json={"usage": 1})),
                         ["a log has lines that are no JSON"])
        self.assertEqual(measure.lacking(dict(whole, usage_lines_of_no_request=2)),
                         ["2 usage lines are of no request that was written"])
        # A call that says it wrote two lines and has one in its time.
        fewer = measure.joined([sized(), request(attempts=2)], [usage()])
        self.assertEqual(measure.lacking({"requests": fewer, "layer": {"turns_left_to_curate": 0}}),
                         ["request 1 has 1 usage lines in its time and wrote 2"])

    def test_a_run_that_also_consolidates_lacks_nothing_that_the_package_does_not_give_those_requests(self):
        # The package counts a merge request and no state request, and gives a consolidation's usage lines no
        # estimate.
        rows = [sized("a"), request("a"), sized("m", 1500, instructions="merge-2"),
                request("m", instructions="merge-2", second=2, answer={"merges": [], "conflicts": []}),
                request("s", instructions="state-2", second=3, answer={"state": {}})]
        lines = [usage(), usage(call="consolidate", instructions="merge-2", second=2, estimate=None),
                 usage(call="consolidate", instructions="state-2", second=3, estimate=None)]
        found = measure.joined(rows, lines)
        self.assertEqual([(row["instructions"], row["count"], row["result"], row["estimate_agrees"]) for row in found],
                         [("curate-3", 3000, "ok", True), ("merge-2", 1500, "ok", False),
                          ("state-2", None, "ok", False)])
        self.assertEqual(measure.lacking({"requests": found, "layer": {"turns_left_to_curate": 0}}), [])
        # A merge request without the count that the package makes for it is told.
        found = measure.joined([row for row in rows if row != rows[2]], lines)
        self.assertEqual(measure.lacking({"requests": found, "layer": {"turns_left_to_curate": 0}}),
                         ["request 2 has no count"])

    def test_a_reading_counts_the_usage_lines_that_no_written_request_took_and_tells_each_index_step(self):
        home = SimpleNamespace(record=lambda: {}, layer=lambda: layer())
        # The second run's worker was ended while its request was under way: a usage line and no request's line.
        runs = [run([sized(), request(), index("key")], [usage(), usage(call="count-tokens", instructions=None)]),
                run([index(embedded=2)], [usage(second=7), usage(call="embed-items", instructions=None, second=8)])]
        found = measure.reading(home, runs)
        self.assertEqual((found["worker_runs"], found["seconds"], len(found["requests"]),
                          found["usage_lines_of_no_request"]), (2, 3.0, 1, 1))
        self.assertEqual([(step["reason"], step["embedded"]) for step in found["index"]], [("key", 0), ("done", 2)])
        self.assertEqual(measure.lacking(found), ["1 usage lines are of no request that was written"])
        self.assertNotIn("usage_lines_of_no_request", measure.reading(home, runs[:1]))

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
        self.assertEqual([real.result_of(row) for row in lines[:2] + [{}]], ["ok", "failed: overloaded", None])

    def test_the_estimates_are_read_once_for_each_document(self):
        rows = measure.joined(
            [count("a", 3000), sized("a", 3000), request("a"), request("a", second=2), sized("b", 5000, part=[1, 2]),
             request("b", second=3), request("c", second=4), sized("m", 4000, instructions="merge-2"),
             count("m", 4000, instructions="merge-2"), request("m", instructions="merge-2", second=5)],
            [usage(), usage(second=2), usage(second=3, input=5000), usage(second=4),
             usage(call="consolidate", instructions="merge-2", second=5, input=4000)])
        found = measure.estimates(rows)
        self.assertEqual({key: found[key] for key in (
            "requests", "requests_with_a_count", "documents_counted", "documents_counted_by_kind",
            "documents_counted_with_a_provisional_number_of_parts",
            "documents_with_the_safe_estimate_below_the_count")},
            {"requests": 5, "requests_with_a_count": 4, "documents_counted": 3,
             "documents_counted_by_kind": {"curate": 2, "merge": 1},
             "documents_counted_with_a_provisional_number_of_parts": 1,
             "documents_with_the_safe_estimate_below_the_count": 1})
        found = measure.estimates(rows[:4])
        self.assertEqual(found["safe_over_count"], {"min": 0.8, "median": 1.067, "max": 1.333, "values": 2})
        self.assertEqual(found["working_over_count"], {"min": 0.4, "median": 0.533, "max": 0.667, "values": 2})
        self.assertEqual(found["count_over_billed_input"], {"min": 1.0, "median": 1.0, "max": 1.0, "values": 2})
        self.assertIsNone(found["line_of_curate_requests"])
        self.assertEqual(measure.estimates([]), {
            "requests": 0, "requests_with_a_count": 0, "documents_counted": 0, "documents_counted_by_kind": {},
            "documents_counted_with_a_provisional_number_of_parts": 0})

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
            "runs", "requests", "requests_by_kind", "input", "output", "usd", "request_ms", "items", "state_lines",
            "changes", "current_items_by_kind")},
            {"runs": 2, "requests": 2, "requests_by_kind": {"curate": 2}, "input": 6000, "output": 800, "usd": 0.002,
             "request_ms": 2000, "items": 4, "state_lines": 2, "changes": {},
             "current_items_by_kind": {"decision": 2, "fact": 2}})
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

    def test_what_each_other_value_would_skip_is_asked_of_the_package_s_rule_too(self):
        asked = []

        def skipped(text, skip):  # A rule that no count of characters gives: at 6 it skips a prompt with a digit.
            asked.append(skip)
            if text.startswith("/"):
                return "command"
            return "short" if skip == 6 and any(character.isdigit() for character in text) else None

        prompts = [{"source": "chat", "text": text} for text in ("가나다 1", "a long prompt without one", "/7", "22")]
        found = measure.skip_share(prompts, 8, skipped)
        self.assertEqual(found["all"], {"prompts": 4, "short": 0, "command": 1, "skipped": 1, "share": 0.25})
        self.assertEqual({value: row["all"] for value, row in found["short_at_other_values"].items()},
                         {"2": 0, "4": 0, "6": 2, "8": 0, "10": 0, "12": 0, "16": 0})
        self.assertEqual(found["short_at_other_values"]["6"], {"all": 2, "ko": 1, "en": 0, "none": 1})
        self.assertEqual(set(asked), set(measure.SKIPS))
        self.assertNotIn("가나다", json.dumps(found, ensure_ascii=False))

    def test_the_spread_and_the_percentile_of_some_numbers(self):
        self.assertEqual(measure.spread([3, None, 1, 2]), {"min": 1, "median": 2, "max": 3, "values": 3})
        self.assertIsNone(measure.spread([None]))
        self.assertEqual([measure.percentile(list(range(1, 21)), share) for share in (0.5, 0.95, 1.0)], [10, 19, 20])
        self.assertEqual(measure.percentile([7], 0.95), 7)
        # The percentile is the timing check's own, and a list of times has it beside its spread.
        self.assertEqual(measure.percentile.__module__, "c2_recall_timing")
        self.assertEqual(measure.timed([float(value) for value in range(1, 21)]),
                         {"min": 1.0, "median": 10.5, "max": 20.0, "values": 20, "p95": 19.0})
        self.assertIsNone(measure.timed([]))

    def test_the_attempts_of_item_embeddings_are_read_in_numbers_and_a_failed_one_stops_nothing(self):
        lines = [usage(call="embed-items", input=30, cost=0.000001, total_ms=40),
                 usage(call="embed-items", input=10, cost=0.0, total_ms=20),
                 usage(call="embed-items", result="failed", error="overloaded", input=0, cost=0.0, total_ms=5)]
        self.assertEqual(measure.embedded(lines), {"attempts": 3, "failed_attempts": {"overloaded": 1}, "input": 40,
                                                   "usd": 1e-06, "ms": 65})
        self.assertEqual(measure.embedded([]), {"attempts": 0, "failed_attempts": {}, "input": 0, "usd": 0.0, "ms": 0})

    def test_the_index_is_whole_after_a_run_whose_last_index_step_was_done_without_a_failed_request(self):
        for rows, whole in (([index()], True), ([index(embedded=3)], True),
                            # A request that failed leaves its items without a vector until a later run.
                            ([index(failed=["overloaded"], embedded=2)], False), ([index("failed")], False),
                            ([index("key")], False), ([index("busy")], False), ([], False),
                            ([{"kind": "index", "raised": "OperationalError"}], False),
                            # The step that counts is the run's last one.
                            ([index("failed", ["authentication_error"]), request(), index(embedded=2)], True),
                            # A request to the model after the last index step may have changed the items.
                            ([index(), request()], False), ([index(), raised()], False),
                            ([request(), sized(), count(), index()], True)):
            with self.subTest(rows=[row.get("reason", row["kind"]) for row in rows]):
                self.assertEqual(measure.whole(run(rows)), whole)
        self.assertEqual(measure.kept(run([request(), index("failed", ["overloaded"]), index(embedded=1)])), [
            {"reason": "failed", "rebuilt": None, "written": 0, "removed": 0, "embedded": 0, "requests": 1,
             "failed": ["overloaded"]},
            {"reason": "done", "rebuilt": None, "written": 0, "removed": 0, "embedded": 1, "requests": 1,
             "failed": []}])

    def home(self, *runs):
        """A home whose worker gives these runs, one for each time that it is run."""
        home, waiting = measure.Home.__new__(measure.Home), list(runs)
        home.work = lambda: waiting.pop(0)
        home.left = waiting
        return home

    def test_the_worker_is_run_again_until_the_index_is_whole_and_no_more_than_five_times(self):
        refused, done = run([index("failed", ["authentication_error"])]), run([index(embedded=2)])
        home, runs = self.home(done), [refused]
        home.settle(runs)
        self.assertEqual((runs, home.left), ([refused, done], []))
        # A last run that left the index whole is followed by none.
        home, runs = self.home(done), [refused, done]
        home.settle(runs)
        self.assertEqual((len(runs), len(home.left)), (2, 1))
        # Without a run before, one is made.
        home, runs = self.home(done), []
        home.settle(runs)
        self.assertEqual(runs, [done])
        home, runs = self.home(*[refused] * (measure.REBUILDS + 1)), [refused]
        with self.assertRaises(real.Stopped) as stopped:
            home.settle(runs)
        self.assertEqual((len(runs), len(home.left)), (1 + measure.REBUILDS, 1))
        self.assertIn("is not whole after 5 more runs", str(stopped.exception))
        self.assertIn("authentication_error", str(stopped.exception))

    def test_the_index_gets_another_length_only_when_it_does_not_have_it(self):
        done = run([index(embedded=2, rebuilt="embedding")])
        home, settings, runs = self.home(done), [], []
        home.check = SimpleNamespace(defaults={"dims": 512})
        home.configuration = lambda: {"models": dict(settings)}
        home.setting = lambda section, name, value: settings.append((name, value))
        home.vectors(512, runs)
        self.assertEqual((runs, settings), ([], []))
        home.vectors(1536, runs)
        self.assertEqual((runs, settings), ([done], [("dims", 1536)]))
        home.vectors(1536, runs)
        self.assertEqual(len(runs), 1)

    def test_the_runs_that_gave_the_index_another_length_are_read_with_any_request_to_the_model(self):
        lines = [usage(call="embed-items", instructions=None, input=30, cost=0.000001, total_ms=40)]
        found = measure.rebuilt([run([index(embedded=2, rebuilt="embedding")], lines)], dims=1536, before="b", items=2)
        self.assertEqual(found, {"dims": 1536, "before": "b", "items": 2, "worker_runs": 1, "attempts": 1,
                                 "failed_attempts": {}, "input": 30, "usd": 1e-06, "ms": 40,
                                 "index": [{"reason": "done", "rebuilt": "embedding", "written": 0, "removed": 0,
                                            "embedded": 2, "requests": 1, "failed": []}]})
        # A consolidation that failed before is made again in such a run: its requests are read there.
        merge = [sized("m", 900, instructions="merge-2"), request("m", instructions="merge-2"), index(embedded=2)]
        found = measure.rebuilt([run(merge, lines + [usage(call="consolidate", instructions="merge-2")])], dims=1536)
        self.assertEqual([(row["instructions"], row["count"], row["usage_lines"]) for row in found["model_requests"]],
                         [("merge-2", 900, 1)])

    def recall_entry(self):
        def asked(outcome, ms, scores, scored="in the hook's time", embed=100):
            return {"outcome": outcome, "ms": ms, "embed_ms": embed, "scored": scored,
                    "candidates": [{"item": "i_%d" % number, "score": score} for number, score in scores]}

        def taken(turn, ms, outcome, embed=None):
            return {"turn": turn, "host": "claude", "ms": ms, "outcome": outcome, "embed_ms": embed}

        return {"rebuilds": [{"dims": 1536, "attempts": 3, "failed_attempts": {"overloaded": 1}, "input": 90,
                              "usd": 0.000002, "ms": 300}],
                "stages": [{"prompts": [], "recorded": {"dims": 512, "prompts": [
                    taken(1, 300.0, "no-index"), taken(2, 280.0, "no-index")]}}, {"prompts": [
                        {"512": asked("below", 400.0, [(1, 0.5), (2, 0.4), (3, 0.3), (4, 0.2), (5, 0.1)]),
                         "1536": asked("below", 500.0, [(1, 0.45), (3, 0.35)])},
                        {"512": asked("late", 950.0, [(2, 0.6)], "with 30 seconds", None),
                         "1536": asked("below", 450.0, [(4, 0.7), (2, 0.2)])},
                        {"512": asked("short", 200.0, [], "no", None), "1536": asked("short", 210.0, [], "no", None)}],
                    "recorded": {"dims": 1536, "prompts": [
                        taken(1, 700.0, "below", 110), taken(2, 990.0, "late", 800), taken(3, 250.0, "short")]}},
                    # A stage that ended before its turns were recorded.
                    {"prompts": [{"512": asked("late", 900.0, [], "no", None)}]}]}

    def test_the_recall_part_is_read_at_each_length(self):
        entry = self.recall_entry()
        found = measure.by_length(entry, 512)
        # A prompt that was asked again and still not ranked is not one that more time scored.
        self.assertEqual({key: found[key] for key in ("prompts", "outcomes", "scored_with_more_time", "ranked")},
                         {"prompts": 4, "outcomes": {"below": 1, "late": 2, "short": 1}, "scored_with_more_time": 1,
                          "ranked": 2})
        self.assertEqual(found["hook_ms"], {"min": 200.0, "median": 650.0, "max": 950.0, "values": 4, "p95": 950.0})
        self.assertEqual(found["hook_ms_of_ranked_in_time"]["values"], 1)
        # The turns that were recorded while the index had this length: the hook as an installed one runs.
        self.assertEqual(found["recorded"], {
            "prompts": 2, "outcomes": {"no-index": 2},
            "hook_ms": {"min": 280.0, "median": 290.0, "max": 300.0, "values": 2, "p95": 300.0},
            "hook_ms_of_ranked_in_time": None, "embed_ms": None})
        self.assertEqual(measure.by_length(entry, 1536)["recorded"], {
            "prompts": 3, "outcomes": {"below": 1, "late": 1, "short": 1},
            "hook_ms": {"min": 250.0, "median": 700.0, "max": 990.0, "values": 3, "p95": 990.0},
            "hook_ms_of_ranked_in_time": {"min": 700.0, "median": 700.0, "max": 700.0, "values": 1},
            "embed_ms": {"min": 110, "median": 455.0, "max": 800, "values": 2}})
        self.assertEqual(found["embed_ms"], {"min": 100, "median": 100, "max": 100, "values": 1})
        self.assertEqual(found["best_score"], {"min": 0.5, "median": 0.55, "max": 0.6, "values": 2})
        self.assertEqual(found["fifth_score"], {"min": 0.1, "median": 0.1, "max": 0.1, "values": 1})
        self.assertEqual(found["rebuilds"]["times"], 0)
        self.assertEqual(measure.by_length(entry, 1536)["rebuilds"], {
            "times": 1, "attempts": 3, "failed_attempts": 1, "input": 90, "usd": 2e-06, "ms": 300})
        empty = measure.by_length({"stages": [], "rebuilds": []}, 512)
        self.assertEqual((empty["hook_ms"], empty["recorded"]["prompts"], empty["recorded"]["hook_ms"]),
                         (None, 0, None))

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
        for part in ("== MEMORY measured at 0.3.0 against p ==", "system: x, Python 3",
                     "one-high-1, curate-3: working 2000, safe 4000, count 3000 (safe/count 1.333)",
                     "changes dropped: 1", "requests to the local server: None",
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

    def test_a_hook_gets_the_embedding_key_alone_in_the_recall_part_and_no_key_in_the_others(self):
        # Every hook of the recall part: the one that is asked a prompt and those that record a sample's turns.
        check, home = self.check()
        with mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://proxy.invalid:1"}):
            env = check.host_environment(home, "codex")
            self.assertEqual((env.get(OPENAI), env.get(ANTHROPIC), env.get("HTTPS_PROXY"), env.get("PLUGIN_ROOT")),
                             (None, None, None, "plugin"))
            check.embedding = True
            env = check.host_environment(home, "codex")
        self.assertEqual((env.get(OPENAI), env.get(ANTHROPIC), env.get("HTTPS_PROXY"), env.get("PLUGIN_ROOT")),
                         ("REAL-OPENAI", None, "http://proxy.invalid:1", "plugin"))
        self.assertFalse([name for name in env if name.endswith("_BASE_URL")])
        check, home = self.check(real=False, embedding=True)
        env = check.host_environment(home, "claude")
        self.assertEqual((env.get(OPENAI), env.get(ANTHROPIC), env.get("CORTHEX_MEMORY_OPENAI_BASE_URL"),
                          env.get("CLAUDECODE")), ("MARKER-OPENAI", None, "http://127.0.0.1:9", "1"))
        check.embedding = False
        env = check.host_environment(home, "claude")
        self.assertEqual((env.get(OPENAI), [name for name in env if name.endswith("_BASE_URL")]), (None, []))

    def test_the_steps_are_each_sample_at_each_effort_and_then_the_other_parts(self):
        check, _ = self.check(samples=[dict(SAMPLE, id="a"), dict(SAMPLE, id="b")],
                              options=SimpleNamespace(part=["efforts", "skip", "recall"], effort=["low", "max"],
                                                      repeat=2))
        steps = check.steps()
        self.assertEqual([(step[0],) + ((step[1]["id"],) + step[2:] if len(step) > 1 else ()) for step in steps],
                         [("efforts", "a", "low", 1), ("efforts", "a", "low", 2), ("efforts", "a", "max", 1),
                          ("efforts", "a", "max", 2), ("efforts", "b", "low", 1), ("efforts", "b", "low", 2),
                          ("efforts", "b", "max", 1), ("efforts", "b", "max", 2), ("skip",), ("recall",)])
        check.options.part = ["skip"]
        self.assertEqual(check.steps(), [("skip",)])

    def test_there_is_no_step_where_the_hooks_would_leave_a_sample_s_prompt_out_as_host_made(self):
        from memory_lib import hooks
        turn = SAMPLE["turns"][0]
        options = SimpleNamespace(part=["recall"], effort=["low"], repeat=1)
        for prompt in ["%s> PROMPT-TEXT" % hooks.HOST_PROMPTS[0].rstrip(">"), "  \n\t" + hooks.HOST_PROMPTS[0],
                       "\u3000" + hooks.HOST_PROMPTS[-1] + " from=\"x\">"] + list(hooks.HOST_PROMPTS):
            with self.subTest(prompt):
                made = dict(SAMPLE, id="b", turns=[turn, turn, dict(turn, prompt=prompt)])
                check, _ = self.check(samples=[SAMPLE, made], options=options)
                with self.assertRaises(real.Stopped) as stopped:
                    check.steps()
                self.assertIn("Nothing was run. The prompt of turn 3 of the sample b begins", str(stopped.exception))
                self.assertNotIn("PROMPT-TEXT", str(stopped.exception))
                # The part skip records no sample, so it has its step.
                check.options = SimpleNamespace(part=["skip"])
                self.assertEqual(check.steps(), [("skip",)])
        # The hooks' rule and no wider one: such a tag later in a prompt, or in an answer, leaves nothing out.
        kept = dict(SAMPLE, turns=[dict(turn, prompt="What is a %s?" % hooks.HOST_PROMPTS[0],
                                        reply=hooks.HOST_PROMPTS[0])])
        check, _ = self.check(samples=[kept], options=options)
        self.assertEqual(check.steps(), [("recall",)])

    def test_the_sums_are_made_after_a_step_that_was_interrupted_too(self):
        check, _ = self.check(report={"runs": {}}, spent=0.0, real=False, options=SimpleNamespace(limit=1.0),
                              server=SimpleNamespace(efforts=["high"]))

        def interrupted(check, entry, sample, level, label):
            entry.update(requests=measured_run()["requests"])  # What the run had made when it was interrupted.
            raise KeyboardInterrupt()

        with mock.patch.object(measure, "measured", interrupted):
            with self.assertRaises(KeyboardInterrupt):
                check.step(("efforts", SAMPLE, "high", 1))
        entry = check.report["runs"]["one-high-1"]
        self.assertEqual((entry["outcome"], entry["why"]), ("not run", "interrupted during this run"))
        self.assertEqual((check.report["estimates"]["requests"], check.report["efforts_that_the_local_server_got"]),
                         (1, {"high": 1}))
        self.assertIn("by_effort", check.report)

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
        # Where the hook with more time ranks nothing either, nothing was scored with more time.
        del asked[:]
        late = {"ms": 950.0, "outcome": "late", "candidates": [], "embed_ms": None, "embed_error": None}
        home.ask = lambda host, prompt, seconds=None: asked.append(seconds) or dict(
            late, outcome="late" if seconds is None else "no-index")
        self.assertEqual(home.recalled("claude", "prompt"), {
            "outcome": "late", "ms": 950.0, "embed_ms": None, "scored": "no", "outcome_with_more_time": "no-index",
            "candidates": []})
        self.assertEqual(asked, [None, measure.MORE_SECONDS])
        # A prompt that was ranked in the hook's time is asked once, and one that recall skips is scored nowhere.
        del asked[:]
        ranked = {"ms": 400.0, "outcome": "below", "candidates": [{"item": "i_2", "score": 0.3}], "embed_ms": 90,
                  "embed_error": None}
        home.ask = lambda host, prompt, seconds=None: asked.append(seconds) or ranked
        self.assertEqual(home.recalled("claude", "prompt"), {
            "outcome": "below", "ms": 400.0, "embed_ms": 90, "scored": "in the hook's time",
            "candidates": [{"item": "i_2", "score": 0.3}]})
        self.assertEqual(asked, [None])
        home.ask = lambda host, prompt, seconds=None: {"ms": 300.0, "outcome": "short", "candidates": [],
                                                       "embed_ms": None, "embed_error": None}
        self.assertEqual(home.recalled("claude", "응"), {"outcome": "short", "ms": 300.0, "embed_ms": None,
                                                        "scored": "no", "candidates": []})

    def test_a_session_s_prompt_lines_are_read_from_its_own_file_of_the_injection_log(self):
        from memory_lib import raw_log
        home = measure.Home.__new__(measure.Home)
        home.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(home.root), True)
        folder = home.root / "injections"
        self.assertEqual(home.injected("claude", "s-1"), [])  # Before any line was written.
        folder.mkdir()
        line = {"at": moment(1), "session": "s-1", "where": "prompt", "items": [], "outcome": "below", "한글": "줄"}
        (folder / (raw_log.log_name("claude-code", "s-1") + ".jsonl")).write_bytes("".join(
            json.dumps(value, ensure_ascii=False) + "\n"
            for value in ({"session": "s-1", "where": "start", "items": []}, line)).encode("utf-8"))
        # The other host's session of that name has a file of its own, which here could not even be read.
        (folder / (raw_log.log_name("codex", "s-1") + ".jsonl")).write_bytes(b"no JSON\n")
        self.assertEqual(home.injected("claude", "s-1"), [line])
        self.assertEqual(home.injected("claude", "s-2"), [])
        with self.assertRaises(ValueError):
            home.injected("codex", "s-1")

    def asking(self, check, base):
        """A home whose prompt hook is not run: what it was started with, and what was then read."""
        home = measure.Home.__new__(measure.Home)
        home.check, home.home, home.demo = check, base, base
        seen = SimpleNamespace(started=[], read=[], sessions=[])

        def run(args, env, cwd=None, stdin="", timeout=180, line=None):
            seen.started.append((args, env, json.loads(stdin)))
            return {"exit": 0, "stdout": "", "stderr": "", "started_monotonic_ns": 1000000,
                    "ended_monotonic_ns": 251500000}

        def logged(found, provider, names):
            seen.read.append((provider, names))
            found.update(usage=[usage(call="embed-items"), usage(call="embed-prompt", total_ms=140)], failures=[])

        def injected(host, session):
            seen.sessions.append((host, session))
            return [{"where": "prompt", "outcome": "below", "items": [],
                     "candidates": [{"item": "i_1", "score": 0.4, "more": "x"}]}]

        home.logged, home.injected = logged, injected
        return home, seen, mock.patch.object(real.hookcheck, "run", run)

    def test_an_asked_prompt_s_hook_has_the_embedding_key_and_only_what_it_wrote_is_read(self):
        check, base = self.check(embedding=True, plugin=Path("/staged"))
        home, seen, patched = self.asking(check, base)
        with patched:
            found = home.ask("codex", "PROMPT-TEXT")
            more = home.ask("claude", "PROMPT-TEXT", 30)
        self.assertEqual(found, {"ms": 250.5, "outcome": "below", "items": 0,
                                 "candidates": [{"item": "i_1", "score": 0.4}], "embed_ms": 140,
                                 "embed_result": "ok", "embed_error": None})
        self.assertEqual(more, found)
        (args, env, data), (again, more_env, _) = seen.started
        self.assertEqual(args[1:], [str(Path("/staged") / "scripts/hook.py"), "prompt"])
        self.assertEqual(again[1:], [str(measure.HOOK), str(Path("/staged")), "30"])
        self.assertEqual((env.get(OPENAI), env.get(ANTHROPIC), more_env.get(OPENAI), data["prompt"]),
                         ("REAL-OPENAI", None, "REAL-OPENAI", "PROMPT-TEXT"))
        # A hook writes no request, so that file is not read again for each prompt; and of the injection log
        # the one file of the prompt's own session is.
        self.assertEqual(seen.read, [(True, ("usage", "failures"))] * 2)
        self.assertEqual(seen.sessions[0], ("codex", data["session_id"]))
        self.assertEqual(len({session for _, session in seen.sessions}), 2)

    def test_a_recorded_turn_has_its_hook_s_time_its_own_line_s_outcome_and_its_usage_lines(self):
        home = measure.Home.__new__(measure.Home)
        home.sessions = {"claude": "the session of the sample before"}
        seen, read, waiting = [], [], []
        lines = {"claude": [{"where": "prompt", "prompt": "e_0", "outcome": "injected"}], "codex": []}
        outcomes = ("below", None, "no-index")  # The second turn's line could not be written.

        def turn(value):
            number = len(seen) + 1
            seen.append((value.host, value.prompt, value.reply, value.script, home.sessions.get(value.host)))
            home.sessions.setdefault(value.host, "a new session of " + value.host)
            home.took = {"prompt": 100.0 * number, "end-of-turn": 5.0}
            if outcomes[number - 1]:
                lines[value.host].append({"where": "prompt", "prompt": "e_%d" % number,
                                          "outcome": outcomes[number - 1]})
            if number == 1:
                waiting.extend([usage(call="embed-prompt", total_ms=120)])
            return {"prompt": "e_%d" % number, "answer": "a_%d" % number}

        def logged(found, provider, names):
            read.append((provider, names))
            found["usage"] = list(waiting)
            del waiting[:]

        home.turn, home.logged = turn, logged
        home.injected = lambda host, session: list(lines[host])
        sample = {"turns": [{"host": "claude", "prompt": "P1", "reply": "R1"},
                            {"host": "claude", "prompt": "P2", "reply": "R2"},
                            {"host": "codex", "prompt": "P3", "reply": "R3"}]}
        self.assertEqual(home.take(sample), [
            {"turn": 1, "host": "claude", "ms": 100.0, "outcome": "below", "embed_ms": 120},
            # Not the line of the turn before it, which is the last of its session's file.
            {"turn": 2, "host": "claude", "ms": 200.0, "outcome": "no-line", "embed_ms": None},
            {"turn": 3, "host": "codex", "ms": 300.0, "outcome": "no-index", "embed_ms": None}])
        # The sample's turns went into sessions of their own, each with its answer and no script.
        self.assertEqual(seen, [("claude", "P1", "R1", None, None),
                                ("claude", "P2", "R2", None, "a new session of claude"),
                                ("codex", "P3", "R3", None, None)])
        # After each turn the hooks' usage lines were read and counted, so that no run of the worker takes them.
        self.assertEqual(read, [(True, ("usage",))] * 3)

    def replayed(self, samples, **changes):
        """The recall part over a home whose hooks and worker are not run, and what the files held each time
        the part came to a sample and to a curation."""
        check, out = self.check(real=False, dims=[512, 1536], defaults={"skip": 8, "dims": 512}, spent=0.0,
                                keys={}, options=SimpleNamespace(limit=1.0), server=SimpleNamespace(efforts=[]),
                                samples=samples)
        entry, seen = {"outcome": "not run"}, []
        check.out, check.report = out, {"runs": {}, "recall": entry}

        def on_disk(where):
            report = json.loads((out / "report.json").read_text(encoding="utf-8"))["recall"]
            texts = json.loads((out / "recall-texts.json").read_text(encoding="utf-8"))
            seen.append((where, [stage["sample"] for stage in report["stages"]],
                         sum(1 for stage in report["stages"] if "curation" in stage), len(texts["prompts"]),
                         report["by_dims"]["512"]["prompts"], report["by_dims"]["512"]["recorded"]["prompts"]))

        class Replayed:
            home, dims, items = out, 512, {}

            def setting(self, section, name, value):
                pass

            def leave_out(self, kinds):
                pass

            def settle(self, runs):
                pass

            def current(self):
                on_disk("sample")
                return dict(self.items)

            def vectors(self, dims, runs):
                self.dims = dims

            def configuration(self):
                return {"models": {"dims": self.dims}}

            def recalled(self, host, prompt):
                return {"outcome": "below", "ms": 300.0, "embed_ms": 100, "scored": "in the hook's time",
                        "candidates": [{"item": "i_000000000001", "score": 0.5}]}

            def take(self, sample):
                return [{"turn": 1, "host": "claude", "ms": 400.0, "outcome": "below", "embed_ms": 100}]

            def curate(self):
                on_disk("curation")
                self.items = {"i_000000000001": item(1)}
                return [run([count(), sized(), request(), index(embedded=1)], [usage()])]

            def record(self):
                return {}

            def layer(self):
                return layer([item(1)])

        home = Replayed()
        for name, value in changes.items():
            setattr(home, name, value)
        check.home = lambda label: home
        return check, entry, seen, out

    def test_the_recall_part_writes_what_it_has_before_each_sample_and_before_each_curation(self):
        check, entry, seen, out = self.replayed([dict(SAMPLE, id=name) for name in ("a", "b", "c")])
        measure.replay(check, entry)
        # Where it stood; the stages that the report had, how many of them with their curation, the prompts of
        # recall-texts.json, and the prompts asked and recorded at 512 numbers by the report's sums.
        self.assertEqual(seen, [("sample", [], 0, 0, 0, 0), ("curation", ["a"], 0, 0, 0, 1),
                                ("sample", ["a"], 1, 0, 0, 1), ("curation", ["a", "b"], 1, 1, 1, 1),
                                ("sample", ["a", "b"], 2, 1, 1, 1), ("curation", ["a", "b", "c"], 2, 2, 2, 2)])
        self.assertEqual((entry["outcome"], [stage["recorded"]["dims"] for stage in entry["stages"]]),
                         ("measured", [512, 1536, 512]))
        self.assertIn("estimates", check.report)
        texts = json.loads((out / "recall-texts.json").read_text(encoding="utf-8"))
        self.assertEqual(([row["sample"] for row in texts["prompts"]], list(texts["items"])),
                         (["b", "c"], ["i_000000000001"]))
        self.assertEqual(sorted(path.name for path in out.iterdir() if path.is_file()),
                         ["recall-texts.json", "report.json"])

    def test_an_interrupt_in_the_recall_part_leaves_the_stages_before_it_and_its_own_in_the_files(self):
        curations = []

        def curate():
            curations.append(1)
            if len(curations) == 2:
                raise KeyboardInterrupt()
            home.items = {"i_000000000001": item(1)}
            return [run([count(), sized(), request(), index(embedded=1)], [usage()])]

        check, entry, seen, out = self.replayed([dict(SAMPLE, id=name) for name in ("a", "b", "c")], curate=curate)
        home = check.home("recall")
        with self.assertRaises(KeyboardInterrupt):
            measure.replay(check, entry)
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))["recall"]
        first, second = report["stages"]
        # The hooks' times, which are in no file of the home, were written before the curation began.
        self.assertEqual((first["sample"], "curation" in first, second["sample"], "curation" in second),
                         ("a", True, "b", False))
        self.assertEqual((second["prompts"][0]["512"]["ms"], second["prompts"][0]["1536"]["ms"],
                          second["recorded"]["prompts"][0]["ms"]), (300.0, 300.0, 400.0))
        self.assertEqual(report["by_dims"]["512"]["prompts"], 1)
        texts = json.loads((out / "recall-texts.json").read_text(encoding="utf-8"))
        self.assertEqual([row["sample"] for row in texts["prompts"]], ["b"])

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

    def library(self, **changes):
        """A stand-in for the staged library with the functions that the wrapper wraps, and what they were given."""
        calls = []
        times = iter(range(1, 100))

        def said(name, value):
            def function(*arguments, **options):
                calls.append((name, arguments, options))
                if isinstance(value, BaseException):
                    raise value
                return value
            return function

        failure = SimpleNamespace(code="overloaded")
        sent = SimpleNamespace(response=SimpleNamespace(failure=None, text="ANSWER"), document="SENT", attempts=2,
                               logged=2)
        values = {"count": SimpleNamespace(tokens=None, failure=failure), "send": sent,
                  "build": ({"body": {"model": "model-x", "max_tokens": 64000, "output_config": {"effort": "max"}}},
                            "SENT"),
                  "plan": SimpleNamespace(requests=(SimpleNamespace(source="one", counted=70, counts=2, part=(1, 2)),
                                                    SimpleNamespace(source="two", counted=None, counts=3, part=None))),
                  "merge_part": SimpleNamespace(source="merge", counted=40, counts=1),
                  "keep": SimpleNamespace(reason="failed", rebuilt="embedding", written=("i_1",), removed=(),
                                          embedded=("i_1", "i_2"), requests=2, failed=("overloaded",))}
        values.update(changes)

        def send(*arguments, **options):
            calls.append(("send", arguments, options))
            if isinstance(values["send"], BaseException):
                raise values["send"]  # As when the package's check fails before a request is built.
            library.model_request.build(config={})
            return values["send"]

        library = SimpleNamespace(
            base=SimpleNamespace(utc_time=lambda: moment(next(times))),
            model_prompts=model_prompts,
            model_count=SimpleNamespace(count=said("count", values["count"])),
            model_client=SimpleNamespace(send=send),
            model_request=SimpleNamespace(build=said("build", values["build"])),
            index_worker=SimpleNamespace(keep=said("keep", values["keep"])),
            request_budget=SimpleNamespace(
                UNCOUNTED=60000, plan=said("plan", values["plan"]), merge_part=said("merge_part", values["merge_part"]),
                working=request_budget.working, safe=request_budget.safe, estimate=request_budget.estimate))
        return library, calls, values

    def tap(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(folder), True)
        return folder / "requests.jsonl"

    def rows(self, tap):
        if not tap.exists():
            return []
        return [json.loads(text) for text in tap.read_text(encoding="utf-8").split("\n") if text]

    def test_each_wrapped_function_gives_what_the_package_s_gave_and_adds_its_line(self):
        library, calls, values = self.library()
        tap = self.tap()
        worker.wrap(library, tap)
        self.assertEqual(library.request_budget.UNCOUNTED, -1)  # The package counts every request that it sizes.
        schema = {"type": "object"}
        options = dict(project="demo", instructions=model_prompts.CURATE, source="문서 one", schema=schema)
        self.assertIs(library.model_count.count("memory", **options), values["count"])
        self.assertIs(library.request_budget.plan("layer", "sessions", schema=schema), values["plan"])
        self.assertIs(library.request_budget.merge_part(["i_1"], [], group="fact", schema=schema), values["merge_part"])
        self.assertIs(library.model_client.send("memory", size={"turns": 1}, **options), values["send"])
        self.assertEqual(library.model_request.build(config={"a": 1}), values["build"])
        self.assertIs(library.index_worker.keep("memory", "demo", "owner", 9.5), values["keep"])
        self.assertEqual([(name, arguments) for name, arguments, _ in calls], [
            ("count", ("memory",)), ("plan", ("layer", "sessions")), ("merge_part", (["i_1"], [])),
            ("send", ("memory",)), ("build", ()), ("build", ()), ("keep", ("memory", "demo", "owner", 9.5))])
        self.assertEqual((calls[3][2], calls[5][2]), (dict(options, size={"turns": 1}), {"config": {"a": 1}}))
        counted, first, second, merged, sent, kept = self.rows(tap)
        self.assertEqual(counted, {"kind": "count", "instructions": model_prompts.CURATE, "tokens": None,
                                   "source_sha256": worker.digest("문서 one"), "failure": "overloaded"})
        self.assertEqual([first, second, merged], [
            {"kind": "sized", "instructions": model_prompts.CURATE, "source_sha256": worker.digest("one"),
             "counted": 70, "counts": 2, "part": [1, 2]},
            {"kind": "sized", "instructions": model_prompts.CURATE, "source_sha256": worker.digest("two"),
             "counted": None, "counts": 3, "part": None},
            {"kind": "sized", "instructions": model_prompts.MERGE, "source_sha256": worker.digest("merge"),
             "counted": 40, "counts": 1, "part": None}])
        sizes = worker.sized(library, model_prompts.CURATE, schema, "문서 one")
        self.assertEqual(sent, dict(
            sizes, kind="request", instructions=model_prompts.CURATE, document="SENT", answer="ANSWER", failure=None,
            attempts=2, logged=2, began=moment(1), ended=moment(2), model="model-x", effort="max", max_tokens=64000,
            source_sha256=worker.digest("문서 one"), size={"turns": 1}))
        self.assertEqual(kept, {"kind": "index", "reason": "failed", "rebuilt": "embedding", "written": 1,
                                "removed": 0, "embedded": 2, "requests": 2, "failed": ["overloaded"]})

    def test_a_call_of_send_that_raises_has_its_line_and_raises_the_same_error(self):
        error = RuntimeError("the lease is gone")
        library, _, _ = self.library(send=error, keep=error)
        tap = self.tap()
        worker.wrap(library, tap)
        options = dict(instructions=model_prompts.CURATE, source="문서", schema={})
        # No request was built in this call: the body of an earlier call's request is not this one's.
        library.model_request.build(config={})
        with self.assertRaises(RuntimeError) as raised_error:
            library.model_client.send("memory", **options)
        self.assertIs(raised_error.exception, error)
        with self.assertRaises(RuntimeError) as raised_error:
            library.index_worker.keep("memory", "demo", "owner", 9.5)
        self.assertIs(raised_error.exception, error)
        sent, kept = self.rows(tap)
        self.assertEqual(sent, dict(worker.sized(library, model_prompts.CURATE, {}, "문서"), kind="request",
                                    instructions=model_prompts.CURATE, raised="RuntimeError", began=moment(1),
                                    ended=moment(2), source_sha256=worker.digest("문서"), size=None))
        self.assertEqual(kept, {"kind": "index", "raised": "RuntimeError"})

    def test_a_line_that_cannot_be_made_or_written_changes_nothing_of_what_the_worker_gets(self):
        # Results without the fields that a line reads, a time that cannot be read, and a folder that is not there.
        odd = object()
        library, _, values = self.library(count=odd, plan=odd, merge_part=odd, keep=odd, build=({}, "SENT"))
        library.base.utc_time = lambda: 1 / 0
        tap = self.tap().parent / "none/requests.jsonl"
        worker.wrap(library, tap)
        options = dict(instructions=model_prompts.CURATE, source="문서", schema={})
        self.assertIs(library.model_count.count("memory", **options), odd)
        self.assertIs(library.request_budget.plan("layer", "sessions", schema={}), odd)
        self.assertIs(library.request_budget.merge_part([], [], group="fact", schema={}), odd)
        self.assertIs(library.index_worker.keep("memory", "demo", "owner", 9.5), odd)
        self.assertIs(library.model_client.send("memory", **options), values["send"])
        self.assertEqual(library.model_request.build(config={}), ({}, "SENT"))
        self.assertFalse(tap.exists())
        # With a folder, a line is written for what could be read, and a time that cannot be read is left out.
        tap = self.tap()
        worker.wrap(library, tap)
        self.assertIs(library.model_client.send("memory", instructions=model_prompts.CURATE), values["send"])
        (row,) = self.rows(tap)
        self.assertEqual((row["kind"], row["began"], row["ended"], row["logged"], row["answer"]),
                         ("request", None, None, 2, "ANSWER"))
        self.assertNotIn("safe", row)

    def test_a_line_is_added_and_one_that_cannot_be_written_is_left_out(self):
        tap = self.tap()
        write = worker.c2_real_worker.write
        self.assertTrue(write(tap, {"kind": "count", "tokens": 7, "text": "반\ud83d"}))
        self.assertTrue(write(tap, {"kind": "count", "tokens": 8}))
        rows = self.rows(tap)
        self.assertEqual([row["tokens"] for row in rows], [7, 8])
        self.assertEqual(rows[0]["text"], "반\ud83d")
        self.assertFalse(write(tap.parent / "none/requests.jsonl", {"kind": "count"}))
        self.assertFalse(write(tap, {"kind": object()}))

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
                self.assertIs(row["count_is_of_this_document"], True)
                self.assertEqual((row["working"], row["safe"]),
                                 (-(-row["ascii"] // 4) + row["other"], -(-row["ascii"] // 2) + 2 * row["other"]))
                self.assertEqual(row["safe_at_or_above_count"], row["safe"] >= row["count"])
                # The efforts part sends no embedding: its worker has no embedding key, and its index step says so.
                self.assertEqual(sorted(entry["usage"]), ["count-tokens", "curate"])
                self.assertEqual([step["reason"] for step in entry["index"]], ["key"])
                self.assertNotIn("usage_lines_of_no_request", entry)
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
        # The index got its other length once, in one run of the worker that sent embeddings only.
        self.assertEqual([(value["dims"], value["items"], value["before"], value["worker_runs"])
                          for value in recall_part["rebuilds"]], [(1536, 2, "made-up-en", 1)])
        rebuild = recall_part["rebuilds"][0]
        self.assertEqual([(step["reason"], step["rebuilt"], step["embedded"], step["failed"])
                          for step in rebuild["index"]], [("done", "embedding", 2, [])])
        self.assertEqual((rebuild["attempts"], rebuild["failed_attempts"]), (1, {}))
        self.assertNotIn("model_requests", rebuild)
        self.assertEqual([recall_part["by_dims"][dims]["rebuilds"]["times"] for dims in ("512", "1536")], [0, 1])
        # A stage's curation is its own run and nothing of that rebuild or of the stage before it: one request,
        # one embedding request for what it added, and the one attempt of the curation record.
        for stage, applied in ((first, 2), (second, 1)):
            with self.subTest(stage["sample"]):
                curation = stage["curation"]
                self.assertEqual((curation["worker_runs"], len(curation["requests"]), curation["usage"]),
                                 (1, 1, {"count-tokens": {"ok": 1}, "curate": {"ok": 1}, "embed-items": {"ok": 1}}))
                self.assertEqual([(step["reason"], step["embedded"], step["failed"]) for step in curation["index"]],
                                 [("done", applied, [])])
                self.assertEqual([(attempt["kind"], attempt["applied"]) for attempt in curation["attempts"]],
                                 [("curate", applied)])
                self.assertEqual(measure.lacking(curation), [])
        # The turns were then recorded by the hook as an installed one runs, with the embedding key: the first
        # sample's while there was no index yet, the second's at the length that the index had by then. Their
        # embedding is in no curation's usage above.
        self.assertEqual((first["recorded"]["dims"], [(row["turn"], row["host"], row["outcome"], row["embed_ms"])
                                                      for row in first["recorded"]["prompts"]]),
                         (512, [(1, "claude", "no-index", None), (2, "codex", "no-index", None)]))
        taken = second["recorded"]["prompts"]
        self.assertEqual((second["recorded"]["dims"], len(taken), taken[0]["turn"]), (1536, 1, 1))
        self.assertIn(taken[0]["outcome"], ("below", "late"))
        self.assertGreater(taken[0]["ms"], 0)
        self.assertEqual([recall_part["by_dims"][dims]["recorded"]["prompts"] for dims in ("512", "1536")], [2, 1])
        if taken[0]["outcome"] == "below":  # Its embedding's usage line was read with the turn, and counted.
            self.assertIsNotNone(taken[0]["embed_ms"])
            self.assertGreaterEqual(self.report["cost"]["calls"]["embed-prompt"]["requests"], 3)
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


# A turn that no one request can carry: the package sends it in parts.
LONG = {"id": "long", "kind": "made-up", "source": "a test", "turns": [
    {"host": "claude", "prompt": "결정: 긴 입력도 나눠서 보냅니다. " + "word " * 112000, "reply": "네."}]}


class Once(measure.Counting):
    """The local server of the flows below: it refuses the first embedding request, as a provider refuses a key."""

    def __init__(self):
        super().__init__()
        self.refusals = 0

    def embeddings(self, value):
        if not self.refusals:
            self.refusals += 1
            return None
        return super().embeddings(value)


class Flows(measure.Measure):
    """The measurement check with three flows of the worker as its steps, each in a home of its own."""
    Server = Once
    FLOWS = ("consolidation", "parts", "refused")

    def steps(self):
        return list(self.FLOWS)

    def step(self, name):
        entry = self.report["runs"][name] = {"outcome": "not run"}
        self.guard(entry, lambda: entry.update(getattr(self, name)(), outcome="read"))

    def consolidation(self):
        """A run that curates a sample and then consolidates: a curate, a merge and a state request."""
        home = self.home("consolidation")
        home.take(measure.MADE_UP[0])
        home.due()
        return measure.reading(home, home.curate())

    def parts(self):
        home = self.home("parts")
        home.take(LONG)
        return measure.reading(home, home.curate())

    def refused(self):
        """A curation whose items' embedding is refused, and the run of the worker that makes it good."""
        home = self.home("refused")
        self.embedding = True
        try:
            home.take(measure.MADE_UP[0])
            runs = home.curate()
            first = measure.whole(runs[-1])
            home.settle(runs)
        finally:
            self.embedding = False
        return dict(measure.reading(home, runs), whole_after_the_curation=first,
                    whole_at_the_end=measure.whole(runs[-1]))


class WorkerFlows(unittest.TestCase):
    """The readings over runs of the staged worker against the local server.

    The tests of the readings above give them made-up lines, which can agree with a reading and not with the
    package. Here the lines are the ones that the package and the wrapper write.
    """

    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.mkdtemp()
        cls.addClassCleanup(shutil.rmtree, cls.base, True)
        out = Path(cls.base) / "c2-measure"
        out.mkdir()
        chosen = measure.options([cls.base, "--self-test"])
        chosen.loaded, chosen.pool = measure.given(chosen)
        # The staged copy that a check points the runner at, and the path that it adds, are put back.
        with mock.patch.dict(os.environ, {ANTHROPIC: SECRETS[0], OPENAI: SECRETS[1]}), \
                mock.patch.object(real.hookcheck, "REPO", real.hookcheck.REPO), \
                mock.patch.object(real.hookcheck, "MEMORY", real.hookcheck.MEMORY), \
                mock.patch.object(sys, "path", list(sys.path)):
            cls.report = real.carry_out(out, chosen, kind=Flows)

    def flow(self, name):
        entry = self.report.get("runs", {}).get(name, {})
        self.assertEqual(entry.get("outcome"), "read",
                         entry.get("crash") or entry.get("why") or self.report.get("crash"))
        return entry

    def test_the_check_ran_each_flow_to_its_end_and_found_no_key(self):
        report = self.report
        self.assertNotIn("crash", report)
        self.assertEqual(measure.ended(report), {name: "read" for name in Flows.FLOWS})
        self.assertEqual((report["files_with_key"], report["local_requests_with_key"], report["files_not_read"]),
                         ([], 0, []))
        self.assertNotIn("key_in_report", report)

    def test_a_run_that_also_consolidates_has_for_each_request_what_the_package_gives_its_kind(self):
        entry = self.flow("consolidation")
        rows = entry["requests"]
        self.assertEqual([real.kind_of(row) for row in rows], ["curate", "merge", "state"])
        # The package counts a curate and a merge request before it sends one, and a state request never.
        self.assertEqual([(row["count"] is not None, row["count_calls"], row.get("count_is_of_this_document"))
                          for row in rows], [(True, 1, True), (True, 1, True), (False, 0, None)])
        self.assertEqual([(row["usage_lines"], row["logged"], row["result"]) for row in rows], [(1, 1, "ok")] * 3)
        # Only a curate request's usage line has an estimate.
        self.assertEqual([row["estimate_agrees"] for row in rows], [True, False, False])
        self.assertEqual(entry["usage"], {"count-tokens": {"ok": 2}, "curate": {"ok": 1}, "consolidate": {"ok": 2}})
        self.assertEqual([attempt["kind"] for attempt in entry["attempts"]], ["consolidate", "curate"])
        self.assertEqual((entry["worker_runs"], measure.lacking(entry)), (1, []))
        self.assertNotIn("usage_lines_of_no_request", entry)
        found = measure.estimates(rows)
        self.assertEqual((found["requests"], found["requests_with_a_count"], found["documents_counted_by_kind"],
                          found["documents_counted_with_a_provisional_number_of_parts"]),
                         (3, 2, {"curate": 1, "merge": 1}, 0))

    def test_each_part_of_a_turn_has_the_count_that_let_it_go_which_is_of_its_provisional_document(self):
        entry = self.flow("parts")
        rows = entry["requests"]
        total = len(rows)
        self.assertGreater(total, 1)
        self.assertEqual([row["part"] for row in rows], [[number, total] for number in range(1, total + 1)])
        for row in rows:
            with self.subTest(part=row["part"]):
                self.assertEqual((row["instructions"], row["turns"], row["usage_lines"], row["logged"],
                                  row["result"]), ("curate-3", 1, 1, 1, "ok"))
                self.assertGreater(row["count"], 0)
                self.assertGreaterEqual(row["count_calls"], 1)
                self.assertIs(row["count_is_of_this_document"], False)
                self.assertTrue(row["estimate_agrees"])
                self.assertEqual(row["safe_at_or_above_count"], row["safe"] >= row["count"])
        self.assertEqual(list(entry["usage"]["count-tokens"]), ["ok"])
        self.assertGreaterEqual(entry["usage"]["count-tokens"]["ok"], total)
        self.assertEqual((entry["usage"]["curate"], measure.lacking(entry)), ({"ok": total}, []))
        found = measure.estimates(rows)
        self.assertEqual((found["documents_counted"], found["documents_counted_with_a_provisional_number_of_parts"]),
                         (total, total))

    def test_a_refused_embedding_leaves_the_index_not_whole_and_a_later_run_makes_it_good(self):
        entry = self.flow("refused")
        self.assertEqual((entry["whole_after_the_curation"], entry["whole_at_the_end"], entry["worker_runs"]),
                         (False, True, 2))
        self.assertEqual([(step["reason"], step["embedded"], step["failed"]) for step in entry["index"]],
                         [("failed", 0, ["authentication_error"]), ("done", 2, [])])
        self.assertEqual(entry["usage"]["embed-items"], {"failed: authentication_error": 1, "ok": 1})
        self.assertEqual(entry["failures"], [{"step": "embed", "error": "authentication_error"}])
        # The curation itself lacks nothing: the refusal is the index step's.
        self.assertEqual((len(entry["requests"]), measure.lacking(entry)), (1, []))


if __name__ == "__main__":
    unittest.main()
