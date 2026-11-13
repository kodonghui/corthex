"""TASK-100: the readings, refusals and scripted server of the real-provider check, and its self-test.

No provider is called here: the readings get made-up layers and answers, and the one run of the script answers
every request from its local server.
"""
import contextlib
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from _common import ROOT

FOLDER = ROOT / ".github/hook-check"
sys.path.insert(0, str(FOLDER))
sys.path.insert(0, str(ROOT / "plugins/corthex-memory/skills/corthex-memory/scripts"))
from memory_lib import curator_answers  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(name + "_checked", FOLDER / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


real = load("c2_real")
worker = load("c2_real_worker")

ANTHROPIC, OPENAI = real.ANTHROPIC, real.OPENAI
# A process that writes its ID to the file that it is given and then stays, for the tests that end one.
SLEEPER = 'import os, sys, time; open(sys.argv[1], "w").write(str(os.getpid())); time.sleep(300)'
# A process that starts a second one, which holds the first one's output open, and then stays as the second does:
# whoever reads that output to its end waits for both.
TREE = ("import subprocess, sys, time\n"
        "second = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'], stdout=sys.stdout,\n"
        "                          stderr=sys.stderr)\n"
        "open(sys.argv[1], 'w').write(str(second.pid))\n"
        "time.sleep(120)\n")
YES, KOREAN, CHAT = ("the short yes gave a user decision with the user's answer first",
                     "the Korean decision gave a Korean item", "the small talk gave no item")


def ident(prefix, number):
    return "%s_%012d" % (prefix, number)


def quote(entry, speaker="user", words="words", start=0, end=None):
    return {"entry": entry, "speaker": speaker, "words": words, "start": start,
            "end": start + len(words) if end is None else end}


def item(number, quotes, kind="decision", status="current", title="제목", text="본문", **more):
    return dict(id=ident("i", number), kind=kind, status=status, title=title, text=text, quotes=list(quotes), **more)


def line(number, cites=(), part="decisions", text="한 줄"):
    return {"id": ident("s", number), "part": part, "pos": number, "text": text, "cites": list(cites)}


def layer(items=(), lines=(), candidates=(), waiting=0):
    return {"items": {value["id"]: value for value in items}, "lines": list(lines),
            "candidates": list(candidates), "waiting": waiting}


def candidate(first, second, status="open"):
    return {"id": "c_000000000001", "items": [first, second], "status": status}


def turns(count):
    """The entries of `count` turns, as `Home.turn` returns them."""
    return [{"prompt": ident("e", 2 * number + 1), "answer": ident("e", 2 * number + 2)} for number in range(count)]


def usage(call, result="ok", instructions=None, **more):
    return dict(call=call, result=result, instructions=instructions, **more)


def written(instructions, answer, failure=None):
    return {"instructions": instructions, "document": "<request/>", "failure": failure, "attempts": 1,
            "answer": answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)}


def started(mark, seconds=60):
    """The process ID that a test's process wrote to `mark`, once it is there."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if mark.exists() and mark.read_text(encoding="utf-8"):
            return int(mark.read_text(encoding="utf-8"))
        time.sleep(0.05)
    raise AssertionError("the process did not start within %d s" % seconds)


def over(pid):
    """End a process that a test started and that may still run, as when the test failed before its own check."""
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def ended(pid, seconds=20):
    """Whether a process that is not this one's child ends within `seconds`, collected or not (POSIX)."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except OSError:
            pass
        try:  # Linux keeps an ended process that nothing has collected yet, with the state Z.
            if Path("/proc/%d/stat" % pid).read_text(encoding="utf-8").rpartition(")")[2].split()[0] == "Z":
                return True
        except (OSError, IndexError):
            pass
        time.sleep(0.1)
    return False


def passing(*_):
    return {"outcome": "pass"}


INTERRUPTING = ("SIGINT",) + real.ENDING  # The signals of which the first interrupts the check.


EMPTY = {"changes": [], "state": {"change": [], "add": [], "remove": []}}
KEPT = {"state": {"goal": [], "decisions": [], "progress": [], "blockers": [], "next": []}}


def request(entries, items=(), lines=(), kind="curate", instructions="curate-3", **body):
    """A request's body with a document that holds what the scripted server reads: lines, items and entries."""
    def escaped(text):
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    parts = ['<request kind="%s" instructions="%s">' % (kind, instructions), "<state>"]
    parts += ['<line id="%s" part="decisions" cites="%s">%s</line>' % (name, " ".join(cites), escaped(text))
              for name, cites, text in lines]
    parts += ["</state>", '<items form="full">']
    parts += ['<item id="%s" kind="decision" speaker="user" date="2026-11-12"><title>%s</title></item>' % (
        name, escaped(title)) for name, title in items]
    parts += ["</items>", "<turns>"]
    parts += ['<entry id="%s" speaker="%s" at="2026-11-12T00:00:00.000Z">%s</entry>' % (name, speaker, escaped(text))
              for name, speaker, text in entries]
    parts += ["</turns>", "</request>"]
    return dict(body, messages=[{"role": "user", "content": "\n".join(parts)}])


class RefusalTests(unittest.TestCase):
    def run_main(self, arguments, prepare=None, **environment):
        """`main` with a new OUTDIR, which `prepare` may fill first, and without the keys of this environment.

        The staged copy that a check points the runner at is put back, so that a test may let a check begin.
        """
        base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, base, True)
        if prepare:
            prepare(Path(base) / "c2-real")
        kept = {name: value for name, value in os.environ.items()
                if name not in ("CI", "GITHUB_ACTIONS", ANTHROPIC, OPENAI)}
        kept.update(environment)
        output = io.StringIO()
        with mock.patch.dict(os.environ, kept, clear=True), contextlib.redirect_stdout(output), \
                mock.patch.object(real.hookcheck, "REPO", real.hookcheck.REPO), \
                mock.patch.object(real.hookcheck, "MEMORY", real.hookcheck.MEMORY):
            code = real.main([base] + arguments)
        return code, output.getvalue(), Path(base)

    @staticmethod
    def report(base):
        return json.loads((base / "c2-real/report.json").read_text(encoding="utf-8"))

    @staticmethod
    def files(folder):
        return {path.relative_to(folder).as_posix(): path.read_text(encoding="utf-8")
                for path in sorted(folder.rglob("*")) if path.is_file()}

    def test_it_never_calls_the_providers_in_ci(self):
        for name in ("CI", "GITHUB_ACTIONS"):
            with self.subTest(name):
                code, text, base = self.run_main([], **{name: "true", ANTHROPIC: "made-up"})
                self.assertEqual(code, 2)
                self.assertIn("never run in CI", text)
                self.assertEqual(list(base.iterdir()), [])

    def test_it_names_the_key_that_is_not_set_and_writes_nothing(self):
        code, text, base = self.run_main([])
        self.assertEqual(code, 2)
        self.assertIn(ANTHROPIC + " is not set", text)
        self.assertEqual(list(base.iterdir()), [])

    def test_a_repeat_below_one_and_a_limit_that_is_no_number_above_zero_are_refused(self):
        for arguments in (["--repeat", "0"], ["--limit", "0"], ["--limit", "-1"], ["--limit", "nan"],
                          ["--limit", "inf"]):
            with self.subTest(arguments):
                code, _, base = self.run_main(["--self-test"] + arguments)
                self.assertEqual(code, 2)
                self.assertEqual(list(base.iterdir()), [])

    def test_a_workflow_runs_it_as_a_self_test_only(self):
        lines = [(path.name, text) for path in sorted((ROOT / ".github/workflows").glob("*.yml"))
                 for text in path.read_text(encoding="utf-8").splitlines() if "c2_real" in text and "run:" in text]
        self.assertTrue(lines)
        for name, text in lines:
            self.assertIn("c2_real.py", text, name)
            self.assertIn("--self-test", text, name)

    def test_a_case_named_twice_is_run_once_and_no_name_means_every_case(self):
        self.assertEqual(real.options(["out", "--case", "TC-261", "--case", "TC-258", "--case", "TC-261"]).case,
                         ["TC-261", "TC-258"])
        self.assertEqual(real.options(["out"]).case, list(real.CASES))

    def test_no_run_starts_once_the_cost_has_reached_the_limit(self):
        check = real.Check.__new__(real.Check)
        check.real, check.spent, check.options = True, 0.25, SimpleNamespace(limit=0.25)
        with self.assertRaises(real.Stopped) as stopped:
            check.afford()
        self.assertIn("0.2500 USD", str(stopped.exception))
        check.spent = 0.24
        check.afford()
        check.real, check.spent = False, 9.0  # A self-test's lines are the local server's made-up usage.
        check.afford()

    def test_a_run_that_began_is_finished_and_the_next_one_does_not_start_at_the_limit(self):
        check = real.Check.__new__(real.Check)
        check.report, check.keys = {"cases": {}}, {}
        check.real, check.spent, check.options = True, 0.0, SimpleNamespace(repeat=3, limit=0.5)
        labels = []

        def runner(_, label):
            labels.append(label)
            check.spent += 0.5  # This run's cost reaches the limit; what it found is kept.
            return {"outcome": "pass", "label": label}

        with mock.patch.dict(real.RUNNERS, {"TC-261": runner, "TC-262": runner}):
            check.case("TC-261")
            check.case("TC-262")
        entry = check.report["cases"]["TC-261"]
        self.assertEqual(labels, ["tc-261-1"])
        self.assertEqual([run["outcome"] for run in entry["runs"]], ["pass", "not run"])
        self.assertIn("0.5000 USD", entry["runs"][1]["why"])
        self.assertEqual((entry["outcome"], entry["runs"][0]["label"]), ("not run", "tc-261-1"))
        # A case that would begin at the limit builds no home: its runner is not called at all.
        self.assertEqual(check.report["cases"]["TC-262"]["outcome"], "not run")
        self.assertEqual([run["outcome"] for run in check.report["cases"]["TC-262"]["runs"]], ["not run"])

    def test_an_interrupt_is_noted_on_its_run_and_raised_again(self):
        check = real.Check.__new__(real.Check)
        check.report, check.keys, check.real = {"cases": {}}, {}, False
        check.options = SimpleNamespace(repeat=3)
        outcomes = iter(["pass", KeyboardInterrupt()])

        def runner(*_):
            value = next(outcomes)
            if isinstance(value, BaseException):
                raise value
            return {"outcome": value}

        with mock.patch.dict(real.RUNNERS, {"TC-345": runner, "TC-356": runner}):
            with self.assertRaises(KeyboardInterrupt):
                check.case("TC-345")
        entry = check.report["cases"]["TC-345"]
        self.assertEqual([run["outcome"] for run in entry["runs"]], ["pass", "not run"])
        self.assertIn("interrupted", entry["runs"][1]["why"])
        self.assertEqual(entry["outcome"], "not run")

    def test_an_interrupt_keeps_the_report_of_the_cases_before_it(self):
        def passed(*_):
            return {"outcome": "pass", "observed": {"read": True}}

        def interrupted(*_):
            raise KeyboardInterrupt()

        handlers = [signal.getsignal(getattr(signal, name)) for name in INTERRUPTING if hasattr(signal, name)]
        with mock.patch.dict(real.RUNNERS, {"TC-258": passed, "TC-259": interrupted}):
            code, text, base = self.run_main(["--self-test", "--case", "TC-258", "--case", "TC-259",
                                              "--case", "TC-261"])
        self.assertEqual(code, 1)
        # The handlers of the signals that interrupt the check are this process's own again.
        self.assertEqual([signal.getsignal(getattr(signal, name)) for name in INTERRUPTING if hasattr(signal, name)],
                         handlers)
        report = self.report(base)
        self.assertEqual({name: entry["outcome"] for name, entry in report["cases"].items()},
                         {"TC-258": "pass", "TC-259": "not run"})
        self.assertIn("interrupted", report["crash"])
        self.assertEqual((report["cost"]["requests"], report["files_with_key"], report["files_not_read"]),
                         (0, [], []))
        self.assertIn("TC-258: pass", text)
        self.assertIn("TC-259: not run", text)
        self.assertIn("interrupted", text.splitlines()[-1])

    def test_the_folder_of_an_earlier_run_is_kept_unless_its_report_shows_a_self_test(self):
        ran = []

        def runner(_, label):
            ran.append(label)
            return {"outcome": "pass"}

        kinds = [("a provider's run", {"report.json": json.dumps({"self_test": False, "cases": {}}),
                                       "tc-258-1/requests.jsonl": "{}\n"}),
                 ("files without a report", {"tc-258-1/requests.jsonl": "{}\n"}),
                 ("a report that is no JSON", {"report.json": '{"self_test": true'}),
                 ("a report that is no object", {"report.json": "[true]"}),
                 ("a report that says something else", {"report.json": json.dumps({"self_test": "true"})})]
        for name, files in kinds:
            with self.subTest(name):
                def prepare(folder):
                    for path, text in files.items():
                        (folder / path).parent.mkdir(parents=True, exist_ok=True)
                        (folder / path).write_text(text, encoding="utf-8")

                with mock.patch.dict(real.RUNNERS, {case: runner for case in real.CASES}):
                    code, text, base = self.run_main(["--self-test"], prepare=prepare)
                self.assertEqual((code, ran), (2, []))
                self.assertIn("is there already", text)
                self.assertIn("another OUTDIR", text)
                self.assertEqual(self.files(base / "c2-real"), files)

    def test_a_file_or_a_link_named_as_the_check_s_folder_is_left_alone(self):
        with mock.patch.dict(real.RUNNERS, {case: passing for case in real.CASES}):
            code, text, base = self.run_main(["--self-test"], prepare=lambda folder: folder.write_text("mine"))
            self.assertEqual((code, (base / "c2-real").read_text()), (2, "mine"))
            self.assertIn("is there already", text)
            if os.name == "nt":
                return  # A link needs a right there that a test may not have.
            # Through the link the folder would read as a self-test's: it is a self-test's somewhere else.
            other = Path(tempfile.mkdtemp())
            self.addCleanup(shutil.rmtree, str(other), True)
            (other / "report.json").write_text(json.dumps({"self_test": True}), encoding="utf-8")
            code, text, base = self.run_main(["--self-test"], prepare=lambda folder: folder.symlink_to(
                other, target_is_directory=True))
        self.assertEqual((code, (base / "c2-real").is_symlink()), (2, True))
        self.assertEqual(self.files(other), {"report.json": json.dumps({"self_test": True})})

    def test_a_self_test_s_folder_and_an_empty_one_are_replaced(self):
        def left(folder):
            (folder / "tc-258-1").mkdir(parents=True)
            (folder / "tc-258-1/requests.jsonl").write_text("{}\n", encoding="utf-8")
            (folder / "report.json").write_text(json.dumps({"self_test": True, "cases": {}}), encoding="utf-8")

        for name, prepare in (("a self-test's", left), ("an empty folder", lambda folder: folder.mkdir())):
            with self.subTest(name):
                with mock.patch.dict(real.RUNNERS, {"TC-261": passing}):
                    code, _, base = self.run_main(["--self-test", "--case", "TC-261"], prepare=prepare)
                self.assertEqual(code, 0)
                self.assertFalse((base / "c2-real/tc-258-1").exists())
                self.assertEqual({case: entry["outcome"] for case, entry in self.report(base)["cases"].items()},
                                 {"TC-261": "pass"})

    def test_the_report_is_on_disk_before_each_case_begins(self):
        seen = []

        def looking(check, _):
            seen.append(json.loads((check.out / "report.json").read_text(encoding="utf-8")))
            return {"outcome": "pass"}

        with mock.patch.dict(real.RUNNERS, {"TC-258": looking, "TC-259": looking}):
            code, _, base = self.run_main(["--self-test", "--case", "TC-258", "--case", "TC-259"])
        self.assertEqual(code, 0)
        self.assertEqual([(report["self_test"], {case: entry["outcome"] for case, entry in report["cases"].items()})
                          for report in seen], [(True, {}), (True, {"TC-258": "pass"})])
        self.assertIn("checkout", seen[0])
        # Each report took the place of the one before it: no file of a write that is under way stays.
        self.assertEqual(sorted(path.name for path in (base / "c2-real").iterdir() if path.is_file()),
                         ["report.json"])

    def test_a_check_that_breaks_as_it_begins_has_said_that_it_is_a_self_test_s(self):
        seen = []

        def broken(out, _):
            seen.append(json.loads((out / "report.json").read_text(encoding="utf-8")))
            raise RuntimeError("the package could not be staged")

        with mock.patch.object(real, "Check", broken):
            code, text, base = self.run_main(["--self-test"])
        self.assertEqual((code, seen), (1, [{"release": real.c2_hosts.RELEASE, "provider": real.SELF_TEST,
                                              "self_test": True}]))
        self.assertIn("could not be staged", self.report(base)["crash"])
        self.assertIn("could not be staged", text)
        self.assertIsNone(real.earlier(base / "c2-real"))  # The next self-test may take the folder.

    def test_a_check_that_refuses_to_begin_says_why_in_one_line_and_runs_no_case(self):
        ran = []

        class Refusing(real.Check):
            def steps(self):
                raise real.Stopped("Nothing was run. What it was given cannot be recorded.")

            def step(self, name):
                ran.append(name)

        with mock.patch.object(real, "Check", Refusing):
            code, text, base = self.run_main(["--self-test"])
        report = self.report(base)
        # The reason alone: no traceback of a refusal that the check made itself.
        self.assertEqual((code, ran, report["crash"], report["cases"]),
                         (1, [], "Nothing was run. What it was given cannot be recorded.", {}))
        self.assertEqual(text.splitlines()[-1], report["crash"])
        self.assertEqual((report["cost"]["requests"], report["files_with_key"], report["files_not_read"]),
                         (0, [], []))

    def test_what_sends_nothing_to_a_provider_is_refused_neither_in_ci_nor_without_a_key(self):
        launch = real.launch
        for environment in ({"CI": "true"}, {"GITHUB_ACTIONS": "true"}, {}):
            with self.subTest(environment):
                with mock.patch.dict(real.RUNNERS, {"TC-258": passing}), \
                        mock.patch.object(real, "launch", lambda chosen, folder: launch(chosen, folder, free=True)):
                    code, _, base = self.run_main(["--case", "TC-258"], **environment)
                report = self.report(base)
                self.assertEqual((code, report["self_test"], report["cases"]["TC-258"]["outcome"]),
                                 (0, False, "pass"))
                self.assertEqual(report["keys"], {ANTHROPIC: "missing", OPENAI: "missing"})
        # Its other refusals hold: a folder that may be an earlier run's record is not replaced.
        with mock.patch.dict(real.RUNNERS, {"TC-258": passing}), \
                mock.patch.object(real, "launch", lambda chosen, folder: launch(chosen, folder, free=True)):
            code, text, base = self.run_main(["--case", "TC-258"], prepare=lambda out: (
                out.mkdir(), (out / "report.json").write_text(json.dumps({"self_test": False}), encoding="utf-8")))
        self.assertEqual((code, self.report(base)), (2, {"self_test": False}))

    def test_a_report_that_cannot_be_written_stops_the_cases_after_it_and_is_written_at_the_end(self):
        ran, writes, write = [], [], real.write

        def runner(_, label):
            ran.append(label)
            return {"outcome": "pass"}

        def failing(out, report, check):
            writes.append(sorted(report.get("cases", {})))
            if len(writes) == 3:  # The write before the second case: the first is the check's beginning.
                raise OSError("No space left on device")
            return write(out, report, check)

        with mock.patch.dict(real.RUNNERS, {case: runner for case in real.CASES}), \
                mock.patch.object(real, "write", failing):
            code, text, base = self.run_main(["--self-test", "--case", "TC-258", "--case", "TC-259",
                                              "--case", "TC-261"])
        # What the runs gave could not be kept, so no further run was made; the end's writes still were.
        self.assertEqual((code, ran, writes), (1, ["tc-258-1"], [[], [], ["TC-258"], ["TC-258"], ["TC-258"]]))
        report = self.report(base)
        self.assertEqual({case: entry["outcome"] for case, entry in report["cases"].items()}, {"TC-258": "pass"})
        self.assertIn("No space left on device", report["crash"])
        self.assertEqual((report["cost"]["requests"], report["files_with_key"]), (0, []))
        self.assertIn("No space left on device", text)

    def test_a_report_that_can_no_longer_be_written_still_ends_with_the_summary(self):
        writes, write = [], real.write

        def failing(out, report, check):
            writes.append(sorted(report.get("cases", {})))
            if len(writes) >= 3:  # From the write before the second case on, as when the disk is full.
                raise OSError("No space left on device")
            return write(out, report, check)

        with mock.patch.dict(real.RUNNERS, {case: passing for case in real.CASES}), \
                mock.patch.object(real, "write", failing):
            code, text, base = self.run_main(["--self-test", "--case", "TC-258", "--case", "TC-259"])
        self.assertEqual((code, writes), (1, [[], [], ["TC-258"], ["TC-258"], ["TC-258"]]))
        # The file is the one of before the first case; what the run gave is on the terminal all the same.
        self.assertEqual(self.report(base)["cases"], {})
        self.assertIn("TC-258: pass", text)
        self.assertIn('by the usage log: {"calls": {}, "usd": 0.0, "requests": 0}', text)
        self.assertIn("No space left on device", text)

    def test_an_interrupt_in_the_check_s_ending_is_noted_and_the_report_is_still_written(self):
        def interrupted(*_):
            raise KeyboardInterrupt()

        with mock.patch.dict(real.RUNNERS, {"TC-258": passing}), mock.patch.object(real, "close", interrupted):
            code, text, base = self.run_main(["--self-test", "--case", "TC-258"])
        report = self.report(base)
        self.assertEqual((code, report["cases"]["TC-258"]["outcome"]), (1, "pass"))
        self.assertIn("KeyboardInterrupt", report["crash"])
        self.assertIn("TC-258: pass", text)

    def test_an_error_and_an_interrupt_are_both_in_the_report(self):
        def broken(*_):
            raise RuntimeError("the package could not be staged")

        def interrupted(report, check, text=None, noted=real.noted):
            noted(report, check, text)
            if text is None:  # While the error is noted, before the check's ending has begun.
                raise KeyboardInterrupt()

        with mock.patch.object(real, "Check", broken), mock.patch.object(real, "noted", interrupted):
            code, text, base = self.run_main(["--self-test"])
        crash = self.report(base)["crash"]
        self.assertEqual(code, 1)
        self.assertIn("could not be staged", crash)
        self.assertTrue(crash.endswith(real.INTERRUPTED), crash)
        self.assertIn(real.INTERRUPTED, text)

    def test_only_the_first_signal_interrupts_and_an_ignored_one_stays_ignored(self):
        numbers = [getattr(signal, name) for name in INTERRUPTING if hasattr(signal, name)]
        self.assertGreater(len(numbers), 2)
        usual = [signal.default_int_handler] + [signal.SIG_DFL] * (len(numbers) - 2)
        for number in numbers:
            if signal.getsignal(number) is None:
                self.skipTest("a handler of this process is not Python's to put back")
            self.addCleanup(signal.signal, number, signal.getsignal(number))
        for number, handler in zip(numbers, usual + [signal.SIG_IGN]):  # The last one as under `nohup`.
            signal.signal(number, handler)
        signals = real.Interrupts()
        self.assertEqual(signals.before, dict(zip(numbers, usual)))
        self.assertIs(signal.getsignal(numbers[-1]), signal.SIG_IGN)
        with self.assertRaises(KeyboardInterrupt):
            signal.getsignal(numbers[1])(numbers[1], None)
        # One that follows, Ctrl+C among them, does not break off the ending of the worker and of the check.
        for number in numbers[:-1]:
            self.assertIsNone(signal.getsignal(number)(number, None))
        signals.restore()
        self.assertEqual([signal.getsignal(number) for number in numbers], usual + [signal.SIG_IGN])
        held = real.Interrupts()
        held.hold()  # A check that ends by itself: none interrupts it from there on.
        for number in numbers[:-1]:
            self.assertIsNone(signal.getsignal(number)(number, None))
        held.restore()
        self.assertEqual([signal.getsignal(number) for number in numbers], usual + [signal.SIG_IGN])

    def test_the_check_holds_only_when_every_case_ended_well_and_every_file_was_searched(self):
        good = {"cases": {"TC-258": {"outcome": "pass"}, "TC-345": {"outcome": "recorded"}},
                "files_with_key": [], "files_not_read": [], "local_requests_with_key": 0}
        self.assertTrue(real.passed(good))
        for name, change in (("a case that failed", {"cases": {"TC-258": {"outcome": "fail"}}}),
                             ("a case that was not run", {"cases": {"TC-258": {"outcome": "not run"}}}),
                             ("no case", {"cases": {}}),
                             ("an interrupt", {"crash": "interrupted"}),
                             ("a key in a file", {"files_with_key": ["a"]}),
                             ("a file that could not be read", {"files_not_read": ["a"]})):
            with self.subTest(name):
                self.assertFalse(real.passed(dict(good, **change)))

    def test_a_run_that_breaks_is_kept_with_a_key_masked_and_the_next_run_still_goes(self):
        check = real.Check.__new__(real.Check)
        check.report, check.options, check.real = {"cases": {}}, SimpleNamespace(repeat=2), False
        check.keys = {ANTHROPIC: "REAL-KEY-VALUE"}
        outcomes = iter([RuntimeError("it broke with REAL-KEY-VALUE"), "recorded"])

        def runner(*_):
            value = next(outcomes)
            if isinstance(value, Exception):
                raise value
            return {"outcome": value}

        with mock.patch.dict(real.RUNNERS, {"TC-345": runner}):
            check.case("TC-345")
        entry = check.report["cases"]["TC-345"]
        self.assertEqual([run["outcome"] for run in entry["runs"]], ["crash", "recorded"])
        self.assertEqual(entry["outcome"], "crash")
        self.assertIn("<memory key>", entry["runs"][0]["crash"])
        self.assertNotIn("REAL-KEY-VALUE", entry["runs"][0]["crash"])

    def test_a_key_is_masked_before_a_long_output_is_cut(self):
        check = real.Check.__new__(real.Check)
        check.keys = {ANTHROPIC: "REAL-KEY-VALUE-0123456789"}
        # Cut first, the text would end with the key's first characters and no whole key would be left to mask.
        shown = check.shown("x" * 590 + " REAL-KEY-VALUE-0123456789 and more", 600)
        self.assertNotIn("REAL", shown)
        self.assertTrue(shown.endswith("..."))
        self.assertEqual(check.shown("error: REAL-KEY-VALUE-0123456789"), "error: <memory key>")


class EnvironmentTests(unittest.TestCase):
    def check(self, is_real):
        check = real.Check.__new__(real.Check)
        check.real, check.plugin = is_real, Path("plugin")
        check.keys = {ANTHROPIC: "REAL-ANTHROPIC", OPENAI: "REAL-OPENAI"}
        check.markers = {ANTHROPIC: "MARKER-ANTHROPIC", OPENAI: "MARKER-OPENAI"}
        check.server = SimpleNamespace(url="http://127.0.0.1:9")
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(home), True)
        return check, home

    def test_a_provider_s_run_gets_the_keys_and_the_network_variables_and_no_base_url(self):
        check, home = self.check(True)
        outer = {"HTTPS_PROXY": "http://127.0.0.1:1", "NO_PROXY": "api.example", "SSL_CERT_FILE": "/ca.pem",
                 "CORTHEX_MEMORY_ANTHROPIC_BASE_URL": "http://127.0.0.1:2", "UNRELATED_TOKEN": "x"}
        with mock.patch.dict(os.environ, outer):
            env = check.worker_environment(home, True)
        self.assertEqual((env[ANTHROPIC], env[OPENAI]), ("REAL-ANTHROPIC", "REAL-OPENAI"))
        self.assertEqual((env["HTTPS_PROXY"], env["NO_PROXY"], env["SSL_CERT_FILE"]),
                         ("http://127.0.0.1:1", "api.example", "/ca.pem"))
        self.assertNotIn("CORTHEX_MEMORY_ANTHROPIC_BASE_URL", env)
        self.assertNotIn("CORTHEX_MEMORY_OPENAI_BASE_URL", env)
        self.assertNotIn("UNRELATED_TOKEN", env)
        self.assertEqual(env["HOME"], str(home))

    def test_a_seed_s_run_and_a_self_test_get_made_up_keys_and_the_local_server(self):
        for is_real, provider in ((True, False), (False, True), (False, False)):
            with self.subTest(real=is_real, provider=provider):
                check, home = self.check(is_real)
                with mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://127.0.0.1:1"}):
                    env = check.worker_environment(home, provider)
                self.assertEqual((env[ANTHROPIC], env[OPENAI]), ("MARKER-ANTHROPIC", "MARKER-OPENAI"))
                self.assertEqual(env["CORTHEX_MEMORY_ANTHROPIC_BASE_URL"], "http://127.0.0.1:9")
                self.assertEqual(env["CORTHEX_MEMORY_OPENAI_BASE_URL"], "http://127.0.0.1:9")
                self.assertNotIn("HTTPS_PROXY", env)
                self.assertNotIn("REAL-ANTHROPIC", json.dumps(env))

    def test_a_hook_gets_its_host_s_variable_and_no_key(self):
        check, home = self.check(True)
        with mock.patch.dict(os.environ, {ANTHROPIC: "REAL-ANTHROPIC", OPENAI: "REAL-OPENAI"}):
            claude, codex = check.host_environment(home, "claude"), check.host_environment(home, "codex")
        self.assertEqual((claude["CLAUDECODE"], claude["CLAUDE_PLUGIN_ROOT"]), ("1", "plugin"))
        self.assertEqual(codex["PLUGIN_ROOT"], "plugin")
        self.assertNotIn("CLAUDECODE", codex)
        for env in (claude, codex):
            self.assertNotIn(ANTHROPIC, env)
            self.assertNotIn(OPENAI, env)

    def test_a_hook_s_input_has_the_fields_that_its_host_sends(self):
        contract = json.loads((FOLDER / "host-inputs.json").read_text(encoding="utf-8"))["hosts"]
        for host in ("claude", "codex"):
            for event, values in (("UserPromptSubmit", {"prompt": "질문"}), ("Stop", {"last_assistant_message": "답"})):
                with self.subTest(host=host, event=event):
                    value = real.host_input(host, event, Path("demo"), "session", "turn", **values)
                    self.assertEqual(set(value), set(contract[host]["events"][event]))
                    self.assertEqual(value["hook_event_name"], event)
                    for name, text in values.items():
                        self.assertEqual(value[name], text)
        self.assertEqual(real.host_input("claude", "Stop", Path("demo"), "s", "t", last_assistant_message="")["prompt_id"],
                         "t")
        self.assertIsNone(real.host_input("codex", "Stop", Path("demo"), "s", "t", last_assistant_message="")
                          ["transcript_path"])

    def test_the_files_that_hold_a_key_are_named(self):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(base), True)
        (base / "store/logs").mkdir(parents=True)
        (base / "store/logs/a.jsonl").write_text('{"text": "before KEY-ONE after"}', encoding="utf-8")
        (base / "store/b.json").write_text("nothing", encoding="utf-8")
        (base / "c.bin").write_bytes(b"\xff\xfeKEY-TWO")
        self.assertEqual(real.holding(base, ["KEY-ONE", "KEY-TWO"]), ["c.bin", "store/logs/a.jsonl"])
        self.assertEqual(real.holding(base, ["KEY-THREE"]), [])
        self.assertEqual(real.holding(base, []), [])

    def test_a_file_that_cannot_be_read_is_named_apart_and_the_others_are_still_searched(self):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(base), True)
        (base / "a.txt").write_text("KEY-ONE", encoding="utf-8")
        (base / "b.txt").write_text("held by another process", encoding="utf-8")
        read = Path.read_bytes

        def locked(path):
            if path.name == "b.txt":
                raise PermissionError("in use")
            return read(path)

        unread = []
        with mock.patch.object(Path, "read_bytes", locked):
            self.assertEqual(real.holding(base, ["KEY-ONE"], unread), ["a.txt"])
            self.assertEqual(real.holding(base, ["KEY-ONE"]), ["a.txt"])
        self.assertEqual(unread, ["b.txt"])


class ReadingTests(unittest.TestCase):
    def test_tc258_needs_each_kind_of_request_logged_ok_with_an_answer_that_fits(self):
        merged = {"merges": [], "conflicts": []}
        run = {"usage": [usage("curate", instructions="curate-3"), usage("consolidate", instructions="merge-2"),
                         usage("consolidate", instructions="state-2"), usage("embed-items", "failed")],
               "requests": [written("curate-3", EMPTY), written("merge-2", merged), written("state-2", KEPT)]}
        found = real.schemas(run)
        self.assertEqual(found["merge"], {"usage results": {"ok": 1}, "answers": 1, "answers that fit the schema": 1})
        self.assertTrue(real.accepted(found))
        # An attempt that failed and was tried again leaves a `failed` line beside the request's `ok` line.
        retried = {"usage": run["usage"] + [usage("consolidate", "failed", "merge-2", error="overloaded")],
                   "requests": run["requests"]}
        self.assertEqual(real.schemas(retried)["merge"]["usage results"], {"ok": 1, "failed": 1})
        self.assertTrue(real.accepted(real.schemas(retried)))
        for name, change in (("no state request", lambda value: (value["usage"].pop(2), value["requests"].pop(2))),
                             ("a merge that failed in the end", lambda value: (
                                 value["usage"].append(usage("consolidate", "failed", "merge-2", error="overloaded")),
                                 value["requests"].append(written("merge-2", "", "overloaded")))),
                             ("a request whose line was not written", lambda value: value["usage"].append(
                                 usage("consolidate", "ok", "merge-2"))),
                             ("an answer that does not fit", lambda value: value["requests"].__setitem__(
                                 0, written("curate-3", {"changes": []}))),
                             ("an answer that is no JSON", lambda value: value["requests"].__setitem__(
                                 1, written("merge-2", "not JSON"))),
                             ("a request without a usage line", lambda value: value["usage"].pop(0))):
            with self.subTest(name):
                other = {"usage": list(run["usage"]), "requests": list(run["requests"])}
                change(other)
                self.assertFalse(real.accepted(real.schemas(other)))

    def test_an_answer_fits_by_its_own_kind_s_schema(self):
        self.assertTrue(real.fits(written("state-2", KEPT)))
        self.assertFalse(real.fits(written("curate-3", KEPT)))
        self.assertFalse(real.fits(written("merge-2", EMPTY)))

    def test_the_answers_of_a_kind_leave_out_failed_requests_and_what_is_no_json(self):
        rows = [written("curate-3", EMPTY), written("curate-3", "", "max-tokens"), written("curate-3", "{"),
                written("state-2", KEPT)]
        self.assertEqual(real.answers(rows), [EMPTY])
        self.assertEqual(real.answers(rows, "state"), [KEPT])
        self.assertEqual(real.answers(rows, "merge"), [])

    def test_tc259_needs_the_result_limit_and_the_code_max_tokens_and_no_answer_that_was_not_cut(self):
        before, after = layer(waiting=2), layer(waiting=2)
        record = {"recent": [{"kind": "curate", "result": "failed", "error": "max-tokens", "at": "now"}],
                  "failures": {"count": 1}}
        run = {"usage": [usage("curate", "limit", "curate-3", error="max-tokens", input=900, output=64, cost=0.1)]}
        found = real.cut(run, before, after, record)
        self.assertTrue(found["logged with the result limit and the code max-tokens"])
        self.assertEqual(found["the curation record's latest attempt"],
                         {"kind": "curate", "result": "failed", "error": "max-tokens"})
        self.assertEqual((found["failed attempts counted"], found["turns left to curate"]), (1, [2, 2]))
        again = {"usage": [usage("curate", "failed", "curate-3", error="overloaded")] + run["usage"]}
        self.assertTrue(real.cut(again, before, after, record)["logged with the result limit and the code max-tokens"])
        for name, rows in (("an answer that was not cut", [usage("curate", "ok", "curate-3")]),
                           ("a cut answer and one that was not cut", run["usage"] + [usage("curate", "ok", "curate-3")]),
                           ("another failure", [usage("curate", "failed", "curate-3", error="api_error")]),
                           ("a limit without its code", [usage("curate", "limit", "curate-3")]),
                           ("no request", [])):
            with self.subTest(name):
                self.assertFalse(real.cut({"usage": rows}, before, after, {})[
                    "logged with the result limit and the code max-tokens"])

    def test_tc261_reads_the_yes_the_korean_item_and_the_small_talk(self):
        proposal, yes, korean, small = ids = turns(4)
        agreed = item(1, [quote(yes["prompt"], words="응"), quote(proposal["answer"], "agent", "제안")])
        decided = item(2, [quote(korean["prompt"])], title="릴리스 노트", text="두 언어로 쓴다.")
        found = real.inside(layer([agreed, decided])["items"], ids)
        self.assertEqual([found[name] for name in (YES, KOREAN, CHAT)], [True, True, True])
        self.assertTrue(found["the proposal's words follow as its next quote"])
        cases = (
            ("the proposal first", [item(1, [quote(proposal["answer"], "agent"), quote(yes["prompt"])]), decided],
             [False, True, True]),
            ("a fact for the yes", [item(1, [quote(yes["prompt"])], kind="fact"), decided], [False, True, True]),
            ("a withdrawn decision", [item(1, [quote(yes["prompt"])], status="withdrawn"), decided],
             [False, True, True]),
            ("an English item", [agreed, item(2, [quote(korean["prompt"])], title="Release notes", text="Two.")],
             [True, False, True]),
            ("an English text", [agreed, item(2, [quote(korean["prompt"])], title="릴리스 노트", text="Two.")],
             [True, False, True]),
            ("an item of the small talk", [agreed, decided, item(3, [quote(small["answer"], "agent")], kind="fact")],
             [True, True, False]),
            ("nothing saved", [], [False, False, True]))
        for name, items, expected in cases:
            with self.subTest(name):
                found = real.inside(layer(items)["items"], ids)
                self.assertEqual([found[key] for key in (YES, KOREAN, CHAT)], expected)
        alone = real.inside(layer([item(1, [quote(yes["prompt"])]), decided])["items"], ids)
        self.assertEqual((alone[YES], alone["the proposal's words follow as its next quote"]), (True, False))

    def outside(self, extra=(), lines=None, documents=None, stored=None, holding=(), seeded="current"):
        ids = turns(5)
        pasted = "요약해 주세요.\n<pasted_content id=\"p1\">\n결정: 평문으로 둔다.\n</pasted_content id=\"p1\">"
        seed = item(1, [quote(ident("e", 90))], title="점프 호스트")
        before = layer([seed], [line(1, [seed["id"]], text="점프 호스트를 거친다.")])
        after = layer([dict(seed, status=seeded)] + list(extra),
                      before["lines"] if lines is None else lines)
        entries = {ids[2]["prompt"]: {"text": pasted},
                   ids[4]["prompt"]: {"text": "값을 붙입니다. [redacted:anthropic-key] 보내 주세요."
                                      if stored is None else stored}}
        documents = ["<request>[redacted:anthropic-key]</request>"] if documents is None else documents
        return ids, pasted, real.outside(before, after, ids, entries, "sk-made-up", documents, list(holding))

    def test_tc262_holds_when_nothing_was_followed_quoted_or_sent(self):
        _, _, found = self.outside()
        self.assertEqual([found[name] for name in real.OUTSIDE_NEEDS], [True] * len(real.OUTSIDE_NEEDS))
        self.assertEqual(found["files of the home that hold the key"], [])
        # The seeded line written anew with the same part, text and citation is as it was.
        _, _, found = self.outside(lines=[line(1, [ident("i", 1)], text="점프 호스트를 거친다.")])
        self.assertEqual([found[name] for name in real.OUTSIDE_NEEDS], [True] * len(real.OUTSIDE_NEEDS))

    def test_tc262_reads_each_thing_that_must_not_happen(self):
        ids, pasted, _ = self.outside()
        inside = pasted.index("결정")
        cases = (
            ("a decision with an instruction's title", dict(extra=[item(2, [quote(ids[0]["prompt"])],
                                                                         title=real.OBEY[0])]), 0),
            ("the English instruction's title", dict(extra=[item(2, [quote(ids[1]["prompt"])],
                                                                 title="Saved: " + real.OBEY[1])]), 0),
            ("the seeded decision withdrawn", dict(seeded="withdrawn"), 1),
            ("the seeded line gone", dict(lines=[]), 2),
            ("the seeded line reworded", dict(lines=[line(1, [ident("i", 1)], text="다른 말")]), 2),
            ("the seeded line in another part", dict(lines=[line(1, [ident("i", 1)], part="progress",
                                                                 text="점프 호스트를 거친다.")]), 2),
            ("the seeded line citing another item", dict(lines=[line(1, [ident("i", 1), ident("i", 2)],
                                                                     text="점프 호스트를 거친다.")]), 2),
            ("the seeded line citing nothing", dict(lines=[line(1, text="점프 호스트를 거친다.")]), 2),
            ("a decision quoting the pasted lines", dict(extra=[item(2, [quote(ids[2]["prompt"], start=inside)])]), 3),
            ("a decision whose second quote is pasted", dict(extra=[item(2, [
                quote(ids[2]["answer"], "agent"), quote(ids[2]["prompt"], start=inside)])]), 3),
            ("the key in a request", dict(documents=["<request>sk-made-up</request>"]), 4),
            ("no redaction mark in any request", dict(documents=["<request>값</request>"]), 4),
            ("no request at all", dict(documents=[]), 4),
            ("the key in the raw log", dict(stored="값을 붙입니다. sk-made-up 보내 주세요."), 5),
            ("no mark in the raw log", dict(stored="값을 붙입니다. 보내 주세요."), 5))
        for name, options, failed in cases:
            with self.subTest(name):
                _, _, found = self.outside(**options)
                self.assertEqual([found[key] for key in real.OUTSIDE_NEEDS],
                                 [number != failed for number in range(len(real.OUTSIDE_NEEDS))])

    def test_tc262_lets_a_fact_name_an_instruction_and_a_decision_quote_the_words_before_the_paste(self):
        ids, _, _ = self.outside()
        noted = item(2, [quote(ids[0]["prompt"])], kind="fact", title="지시문: " + real.OBEY[0])
        asked = item(3, [quote(ids[2]["prompt"], words="요약해 주세요.")])
        _, _, found = self.outside(extra=[noted, asked], holding=["home/x.json"])
        self.assertEqual([found[name] for name in real.OUTSIDE_NEEDS], [True] * len(real.OUTSIDE_NEEDS))
        self.assertEqual([value["id"] for value in found["items that quote an instruction"]], [noted["id"]])
        self.assertEqual([value["id"] for value in found["items that quote Claude Code's pasted prompt"]],
                         [asked["id"]])
        self.assertEqual(found["files of the home that hold the key"], ["home/x.json"])

    def test_tc345_says_which_lines_the_answer_names_and_which_stay(self):
        old = item(3, [quote(ident("e", 5))], title="포트 8443")
        others = [item(number, [quote(ident("e", number))]) for number in (1, 2, 4, 5)]
        lines = [line(number, [ident("i", number)], text="줄 %d" % number) for number in range(1, 6)]
        before = layer([old] + others, lines)
        new = item(6, [quote(ident("e", 11))], title="포트 9443")
        changed = [dict(value) for value in lines]
        changed[2] = dict(changed[2], text="포트는 9443", cites=[new["id"]])
        after = layer([dict(old, status="superseded", superseded_by=new["id"]), new] + others, changed)
        answer = {"changes": [{"action": "replace", "kind": "decision", "targets": [old["id"]], "conflicts": [],
                               "title": "포트 9443"}],
                  "state": {"change": [{"line": lines[2]["id"]}], "add": [], "remove": []}}
        found = real.one_fact(before, after, answer, old["id"])
        self.assertEqual(found["the affected line"], [lines[2]["id"]])
        self.assertTrue(found["the answer names the affected line"])
        self.assertEqual(found["unaffected lines that the answer names"], [])
        self.assertEqual(found["unaffected lines that stay as they were"], "4 of 4")
        self.assertEqual((found["lines before"], found["lines after"], found["the old fact's item"]),
                         (5, 5, "superseded"))
        self.assertEqual(found["changes of the answer"][0]["targets"], [old["id"]])
        self.assertEqual((found["the affected line after"], found["line edits that the package dropped, by reason"],
                          found["IDs that the line edits cite and the request does not carry"]),
                         ("changed", "none", []))

        # An edit that cites an ID of the answer's own making is dropped, and the decision line goes with its item.
        answer["state"]["change"] = [{"line": lines[2]["id"], "cites": [ident("i", 99), ident("e", 11)]}]
        gone = layer([dict(old, status="superseded", superseded_by=new["id"]), new] + others,
                     [value for value in lines if value is not lines[2]])
        record = {"recent": [{"kind": "curate", "result": "ok", "edit_reasons": {"cites": 1, "text": 2}},
                             {"kind": "curate", "result": "ok", "edit_reasons": {"line": 4}}]}
        found = real.one_fact(before, gone, answer, old["id"], record, '<entry id="%s">' % ident("e", 11))
        self.assertTrue(found["the answer names the affected line"])
        self.assertEqual((found["lines after"], found["the affected line after"]), (4, "gone"))
        self.assertEqual(found["line edits that the package dropped, by reason"], "cites: 1, text: 2")
        self.assertEqual(found["IDs that the line edits cite and the request does not carry"], [ident("i", 99)])
        self.assertEqual(found["unaffected lines that stay as they were"], "4 of 4")

        answer["state"] = {"change": [{"line": lines[0]["id"]}], "add": [{"text": "새 줄"}],
                           "remove": [{"line": lines[4]["id"]}]}
        reworded = [dict(lines[0], text="다시 쓴 줄"), lines[1], lines[2], lines[3]]
        found = real.one_fact(before, layer([old] + others, reworded), answer, old["id"])
        self.assertFalse(found["the answer names the affected line"])
        self.assertEqual(found["unaffected lines that the answer names"], [lines[0]["id"], lines[4]["id"]])
        self.assertEqual(found["unaffected lines that stay as they were"], "2 of 4")
        self.assertEqual(found["lines that the answer adds"], ["새 줄"])
        self.assertEqual(found["the old fact's item"], "current")

        found = real.one_fact(before, before, None, old["id"])
        self.assertFalse(found["the answer names the affected line"])
        self.assertEqual(found["unaffected lines that stay as they were"], "4 of 4")
        self.assertEqual(found["the affected line after"], "as it was")
        self.assertEqual(real.one_fact(before, before, None, others[0]["id"], {"recent": []})["the affected line after"],
                         "as it was")
        self.assertEqual(real.became({}, {}, []), "no line cited the item")

    def test_a_line_whose_citations_changed_is_not_as_it_was(self):
        old = item(1, [quote(ident("e", 1))])
        other = item(2, [quote(ident("e", 2))])
        lines = [line(1, [old["id"]]), line(2, [other["id"]])]
        moved = [lines[0], dict(lines[1], cites=[old["id"]])]
        found = real.one_fact(layer([old, other], lines), layer([old, other], moved), EMPTY, old["id"])
        self.assertEqual(found["unaffected lines that stay as they were"], "0 of 1")

    def test_tc356_says_what_became_of_each_rule(self):
        later = turns(2)
        first, second = item(1, [quote(ident("e", 91))]), item(2, [quote(ident("e", 92))])
        before = layer([first, second])
        newer = item(3, [quote(later[0]["prompt"])])
        told = item(4, [quote(later[1]["answer"], "agent")], kind="fact")
        cases = (
            ("replaced on the user's words",
             layer([dict(first, status="superseded", superseded_by=newer["id"]), second, newer]),
             "the later statement replaced the rule", "nothing was saved for the later statement", True),
            ("a candidate for each",
             layer([first, second, newer, told],
                   candidates=[candidate(first["id"], newer["id"]), candidate(told["id"], second["id"])]),
             "a conflict candidate, and both stay current", "a conflict candidate, and both stay current", True),
            ("both without a candidate", layer([first, second, newer, told]),
             "both stay current, without a candidate", "both stay current, without a candidate", True),
            ("a dismissed candidate is not open",
             layer([first, second, newer], candidates=[candidate(first["id"], newer["id"], "dismissed")]),
             "both stay current, without a candidate", "nothing was saved for the later statement", True),
            ("nothing saved", layer([first, second]), "nothing was saved for the later statement",
             "nothing was saved for the later statement", True),
            ("the agent's words replaced the user's rule",
             layer([first, dict(second, status="superseded", superseded_by=told["id"]), told]),
             "nothing was saved for the later statement", "the later statement replaced the rule", False))
        for name, after, user, agent, rests in cases:
            with self.subTest(name):
                found = real.disagreement(before, after, EMPTY, [first["id"], second["id"]], later)
                self.assertEqual((found["the user's later rule"], found["the agent's statement"],
                                  found["each replacement rests on the user's words"]), (user, agent, rests))
        found = real.disagreement(before, cases[0][1], {"changes": [{"action": "replace", "kind": "decision",
                                                                    "targets": [first["id"]], "conflicts": [],
                                                                    "title": "새 규칙", "text": "..."}]},
                                  [first["id"], second["id"]], later)
        self.assertEqual(found["replacements of the user's rules"],
                         [{"item": first["id"], "by": newer["id"], "speaker of the deciding quote": "user"}])
        self.assertEqual(found["changes of the answer"], [{"action": "replace", "kind": "decision",
                                                           "targets": [first["id"]], "conflicts": [],
                                                           "title": "새 규칙"}])

    def test_a_run_is_kept_without_its_documents_and_answers(self):
        run = {"exit": 0, "usage": [usage("curate")], "failures": [],
               "requests": [written("curate-3", "답 text"), written("state-2", "", "max-tokens")]}
        run["requests"][0]["document"] = "<request>문서</request>"
        kept = real.trimmed(run)
        self.assertEqual(kept["requests"][0], {"instructions": "curate-3", "failure": None, "attempts": 1,
                                               "document_bytes": len("<request>문서</request>".encode("utf-8")),
                                               "answer_bytes": len("답 text".encode("utf-8"))})
        self.assertEqual(kept["requests"][1]["failure"], "max-tokens")
        self.assertNotIn("문서", json.dumps(kept, ensure_ascii=False))
        self.assertIn("document", run["requests"][0])

    def test_half_a_surrogate_pair_in_an_answer_is_counted_and_written(self):
        half = "답 \ud83d 끝"
        run = {"exit": 0, "usage": [], "failures": [], "requests": [written("curate-3", half)]}
        kept = real.trimmed(run)
        self.assertEqual(kept["requests"][0]["answer_bytes"], len("답  끝".encode("utf-8")) + 3)
        out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(out), True)
        self.assertFalse(real.write(out, {"cases": {"TC-345": {"why": half, "한글": "그대로"}}}, None))
        data = (out / "report.json").read_bytes()
        self.assertIn("그대로".encode("utf-8"), data)  # Only what UTF-8 cannot hold is escaped.
        self.assertEqual(json.loads(data.decode("utf-8")), {"cases": {"TC-345": {"why": half, "한글": "그대로"}}})

    def test_a_write_that_breaks_leaves_the_report_that_was_there(self):
        out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(out), True)
        first = {"cases": {"TC-258": {"outcome": "pass"}}}
        real.write(out, first, None)

        def broken(path, *_, **__):
            open(str(path), "wb").close()  # As a write that is cut short leaves its file: without its text.
            raise OSError("No space left on device")

        with mock.patch.object(Path, "write_bytes", broken), mock.patch.object(Path, "write_text", broken):
            with self.assertRaises(OSError):
                real.write(out, {"cases": {"TC-258": {"outcome": "pass"}, "TC-259": {"outcome": "pass"}}}, None)
        self.assertEqual(json.loads((out / "report.json").read_text(encoding="utf-8")), first)

    def test_any_file_of_a_check_is_written_beside_itself_and_then_takes_its_place(self):
        out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(out), True)
        path = out / "recall-texts.json"
        half = {"text": "잘린 \ud83d 글자", "한글": "그대로"}
        real.put(path, json.dumps(half, ensure_ascii=False))
        data = path.read_bytes()
        self.assertIn("그대로".encode("utf-8"), data)  # Only what UTF-8 cannot hold is written as its escape.
        self.assertEqual((json.loads(data.decode("utf-8")), sorted(entry.name for entry in out.iterdir())),
                         (half, ["recall-texts.json"]))

        def broken(target, *_, **__):
            open(str(target), "wb").close()  # As a write that is cut short leaves its file: without its text.
            raise OSError("No space left on device")

        with mock.patch.object(Path, "write_bytes", broken), mock.patch.object(Path, "write_text", broken):
            with self.assertRaises(OSError):
                real.put(path, "{}")
        # The file that was there is whole; what could not be written is beside it, under the name with `.new`.
        self.assertEqual((json.loads(path.read_text(encoding="utf-8")), sorted(entry.name for entry in out.iterdir())),
                         (half, ["recall-texts.json", "recall-texts.json.new"]))

    def test_on_windows_the_report_waits_for_its_place_and_elsewhere_a_refusal_is_raised_at_once(self):
        out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(out), True)
        replace, calls = os.replace, []

        def busy(times):
            def replacing(source, target):
                calls.append(target)
                if len(calls) <= times:
                    raise PermissionError(13, "The process cannot access the file")
                return replace(source, target)
            return replacing

        with mock.patch.object(real, "WINDOWS", True), mock.patch.object(real.os, "replace", busy(2)):
            real.write(out, {"cases": {}}, None)
        self.assertEqual((len(calls), json.loads((out / "report.json").read_text(encoding="utf-8"))),
                         (3, {"cases": {}}))
        del calls[:]
        with mock.patch.object(real, "WINDOWS", True), mock.patch.object(real.os, "replace", busy(10 ** 9)), \
                mock.patch.object(real, "REPLACE_SECONDS", 0.2):
            with self.assertRaises(PermissionError):
                real.write(out, {"cases": {"TC-258": {}}}, None)
        self.assertGreater(len(calls), 1)
        del calls[:]
        with mock.patch.object(real, "WINDOWS", False), mock.patch.object(real.os, "replace", busy(1)):
            with self.assertRaises(PermissionError):
                real.write(out, {"cases": {"TC-258": {}}}, None)
        self.assertEqual((len(calls), json.loads((out / "report.json").read_text(encoding="utf-8"))),
                         (1, {"cases": {}}))

    def test_the_checkout_s_changed_files_are_counted_one_by_one_without_the_check_s_own_folder(self):
        try:
            git = real.c2_hosts.program("git")
        except OSError:
            self.skipTest("Git is not installed here")
        base = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, str(base), True)
        repo = base / "checkout"
        repo.mkdir()
        (repo / "kept.txt").write_text("first\n", encoding="utf-8")
        for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "start"]):
            subprocess.run([git, "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                            "-c", "commit.gpgsign=false"] + args, check=True, capture_output=True)
        (repo / "kept.txt").write_text("changed\n", encoding="utf-8")
        for name in ("new/one.txt", "new/two.txt", "out/c2-real/report.json", "out/c2-real/source/plugin.json"):
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text("{}", encoding="utf-8")
        with mock.patch.object(real, "REPO", repo):
            inside = real.checkout(repo / "out/c2-real")
            outside = real.checkout(base / "elsewhere/c2-real")
        # The changed file and the two new ones, each by itself; another OUTDIR leaves that folder's two files in.
        self.assertEqual((inside["changed files"], outside["changed files"]), (3, 5))
        self.assertRegex(inside["commit"], "^[0-9a-f]{40}$")
        self.assertEqual(inside["commit"], outside["commit"])
        # Git read the checkout and wrote nothing into it. A status would write the index that it refreshed: the
        # file below has its text of the commit again and another time, which is what Git then refreshes.
        (repo / "kept.txt").write_text("first\n", encoding="utf-8")
        os.utime(str(repo / "kept.txt"), (1000000000, 1000000000))
        index = (repo / ".git/index").read_bytes()
        with mock.patch.object(real, "REPO", repo):
            self.assertEqual(real.checkout(repo / "out/c2-real")["changed files"], 2)
        self.assertEqual((repo / ".git/index").read_bytes(), index)

    def test_git_is_started_without_the_memory_keys(self):
        calls = []

        def run(command, env, **more):
            calls.append((command, env))
            return {"exit": 0, "stdout": "", "stderr": ""}
        keys = {real.ANTHROPIC: "sk-ant-" + "k" * 24, real.OPENAI: "sk-" + "o" * 24}
        with mock.patch.dict(os.environ, dict(keys, C2_REAL_KEPT="kept")), \
                mock.patch.object(real.hookcheck, "run", run), \
                mock.patch.object(real.c2_hosts, "program", lambda name: "git-of-the-test"):
            found = real.checkout(real.REPO.parent / "elsewhere/c2-real")
        self.assertEqual(found, {"commit": "", "changed files": 0})
        self.assertEqual([command[0] for command, _ in calls], ["git-of-the-test"] * 2)
        for _, env in calls:
            # What Git's configuration makes it start, such as a file system monitor, gets Git's environment:
            # the rest of this process's, and neither key under its name or any other.
            self.assertEqual((set(keys) & set(env), set(keys.values()) & set(env.values())), (set(), set()))
            self.assertEqual((env["C2_REAL_KEPT"], env["GIT_OPTIONAL_LOCKS"]), ("kept", "0"))

    def test_the_cost_is_the_sum_of_the_provider_s_usage_lines_by_call(self):
        check = real.Check.__new__(real.Check)
        check.usage, check.spent = [], 0.0
        check.account({"usage": [usage("curate", input=100, output=10, cost=0.5),
                                 usage("curate", "limit", input=50, output=5, cost=0.25, error="max-tokens")]}, True)
        check.account({"usage": [usage("curate", input=7, output=7, cost=9.0)]}, False)  # A seed's lines.
        check.account({"usage": [usage("embed-items", "failed", error="insufficient_quota", cost=0.0)]}, True)
        found = check.cost()
        self.assertEqual(found["calls"]["curate"], {"requests": 2, "results": {"ok": 1, "limit": 1}, "input": 150,
                                                    "output": 15, "usd": 0.75})
        self.assertEqual(found["calls"]["embed-items"]["results"], {"failed: insufficient_quota": 1})
        self.assertEqual((found["usd"], found["requests"]), (0.75, 3))

    def test_a_leak_is_a_key_in_a_file_in_the_report_or_in_a_local_request(self):
        self.assertFalse(real.leaked({"files_with_key": [], "local_requests_with_key": 0}))
        for report in ({"files_with_key": ["a"]}, {"key_in_report": True}, {"local_requests_with_key": 1}):
            self.assertTrue(real.leaked(report))


class WorkTests(unittest.TestCase):
    """`Home.work` around a worker that is not started: the runner is replaced."""

    def home(self, is_real):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(base), True)
        check = real.Check.__new__(real.Check)
        check.real, check.plugin, check.provider = is_real, Path("plugin"), "a provider"
        check.keys, check.markers = {ANTHROPIC: "REAL-KEY-VALUE-0123456789"}, {ANTHROPIC: "MARKER"}
        check.server = SimpleNamespace(url="http://127.0.0.1:9")
        check.usage, check.spent = [], 0.0
        home = real.Home.__new__(real.Home)
        home.check, home.home, home.demo, home.base = check, base, base, base
        home.store, home.tap = base / "store", base / "requests.jsonl"
        (home.store / "logs").mkdir(parents=True)
        home.read, home.broken = {"usage": 0, "failures": 0, "requests": 0}, {}
        return check, home

    def test_a_provider_s_run_may_take_the_package_s_own_hour_and_a_local_run_much_less(self):
        seen = []

        def run(args, env, cwd=None, stdin="", timeout=180, line=None):
            seen.append(timeout)
            return {"exit": 0, "seconds": 0.1, "stdout": "", "stderr": ""}

        for is_real, expected in ((True, [real.WORK_SECONDS, real.LOCAL_SECONDS]),
                                  (False, [real.LOCAL_SECONDS, real.LOCAL_SECONDS])):
            with self.subTest(real=is_real):
                check, home = self.home(is_real)
                del seen[:]
                with mock.patch.object(real.hookcheck, "run", run):
                    self.assertEqual(home.work()["exit"], 0)
                    home.work(provider=False)
                self.assertEqual(seen, expected)
        from memory_lib import worker_runtime
        self.assertGreater(real.WORK_SECONDS, worker_runtime.RUN_SECONDS)
        self.assertLess(real.LOCAL_SECONDS, real.WORK_SECONDS)

    def test_what_an_interrupted_run_logged_is_still_counted(self):
        check, home = self.home(True)

        def run(*_, **__):
            # The worker had logged one request and was writing its next lines when it was stopped.
            (home.store / "logs/usage-2026-11.jsonl").write_text(
                json.dumps(usage("curate", cost=0.25)) + "\n" + '{"call": "cur', encoding="utf-8")
            (home.store / "logs/failures-2026-11.jsonl").write_text('{"step": "cur', encoding="utf-8")
            raise KeyboardInterrupt()

        with mock.patch.object(real.hookcheck, "run", run):
            with self.assertRaises(KeyboardInterrupt):
                home.work()
        self.assertEqual((check.spent, [row["call"] for row in check.usage]), (0.25, ["curate"]))
        self.assertEqual(home.read["usage"], 1)

    def test_a_run_names_the_lines_that_were_no_json_and_a_worker_that_failed_shows_no_part_of_a_key(self):
        check, home = self.home(True)
        home.tap.write_text(json.dumps(written("curate-3", EMPTY)) + "\nnot JSON\n", encoding="utf-8")
        (home.store / "logs/usage-2026-11.jsonl").write_text(json.dumps(usage("curate", cost=0.5)) + "\n",
                                                            encoding="utf-8")
        done = {"exit": 0, "seconds": 0.1, "stdout": "", "stderr": ""}
        with mock.patch.object(real.hookcheck, "run", return_value=done):
            run = home.work()
        self.assertEqual(run["lines left out because they are no JSON"], {"usage": 0, "failures": 0, "requests": 1})
        self.assertEqual((len(run["requests"]), len(run["usage"]), check.spent), (1, 1, 0.5))
        failed = {"exit": 1, "seconds": 0.1, "stdout": "",
                  "stderr": "x" * 590 + " REAL-KEY-VALUE-0123456789 and more"}
        with mock.patch.object(real.hookcheck, "run", return_value=failed):
            with self.assertRaises(RuntimeError) as error:
                home.work()
        self.assertNotIn("REAL", str(error.exception))
        self.assertIn("the worker ended with 1", str(error.exception))

    def test_a_recorded_turn_keeps_each_hook_s_time_from_outside_its_process(self):
        _, home = self.home(False)
        home.root, home.sessions, home.took = home.base, {}, {"prompt": 1.0, "end-of-turn": 1.0, "other": 1.0}
        (home.root / "raw").mkdir()
        times = iter([(5000000000, 5250400000), (7000000000, 7031260000)])
        started = []

        def run(args, env, cwd=None, stdin="", timeout=180, line=None):
            data = json.loads(stdin)
            started.append((args[-1], data["hook_event_name"], data["session_id"]))
            kind = "prompt" if args[-1] == "prompt" else "answer"
            with open(str(home.root / "raw/2026-11.jsonl"), "a", encoding="utf-8") as log:
                log.write(json.dumps({"id": "e_" + kind, "kind": kind}) + "\n")
            begun, ended = next(times)
            return {"exit": 0, "stdout": "", "stderr": "", "started_monotonic_ns": begun,
                    "ended_monotonic_ns": ended}

        with mock.patch.object(real.hookcheck, "run", run):
            found = home.turn(real.SEED_262[0])
        self.assertEqual(found, {"prompt": "e_prompt", "answer": "e_answer"})
        # Of this turn alone: nothing of a turn before it stays.
        self.assertEqual(home.took, {"prompt": 250.4, "end-of-turn": 31.3})
        session = home.sessions[real.SEED_262[0].host]
        self.assertEqual(started, [("prompt", "UserPromptSubmit", session), ("end-of-turn", "Stop", session)])

    def test_a_reading_names_the_logs_that_it_reads_and_leaves_the_others_for_the_next(self):
        check, home = self.home(True)
        logs = home.store / "logs"
        (logs / "usage-2026-11.jsonl").write_text(json.dumps(usage("embed-prompt", cost=0.25)) + "\n",
                                                  encoding="utf-8")
        (logs / "failures-2026-11.jsonl").write_text(json.dumps({"hook": "prompt", "step": "recall"}) + "\n",
                                                     encoding="utf-8")
        home.tap.write_text(json.dumps(written("curate-3", EMPTY)) + "\n", encoding="utf-8")
        rows, read = home.rows, []

        def noting(name):
            read.append(name)
            return rows(name)

        home.rows = noting
        hook = {}
        home.logged(hook, True, ("usage",))
        # A hook's lines: the usage log alone was opened, its line is counted, and its prices are left out.
        self.assertEqual((read, sorted(hook), [row["call"] for row in hook["usage"]], check.spent),
                         (["usage"], ["usage"], ["embed-prompt"], 0.25))
        self.assertNotIn("prices", hook["usage"][0])
        with open(str(logs / "usage-2026-11.jsonl"), "a", encoding="utf-8") as log:
            log.write(json.dumps(usage("curate", cost=0.5)) + "\n")
        run = {}
        home.logged(run, True)
        # The run after it reads every log: the usage line that the hook's reading took is not its own, and the
        # failure line and the request that nothing read yet are.
        self.assertEqual(([row["call"] for row in run["usage"]], run["failures"], len(run["requests"]), check.spent),
                         (["curate"], [{"hook": "prompt", "step": "recall"}], 1, 0.75))
        self.assertEqual(home.read, {"usage": 2, "failures": 1, "requests": 1})

    def test_a_file_s_whole_lines_are_read_and_the_others_counted(self):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(base), True)
        path = base / "lines.jsonl"
        path.write_bytes('{"a": "한글"}\n{"b": 2}\n{"c": \n'.encode("utf-8") + b"\xff\xfe\n")
        self.assertEqual(real.whole_lines(path), ([{"a": "한글"}, {"b": 2}], 2))
        path.write_bytes(b'{"a": 1}\n{"b": ')  # A worker that was stopped while it wrote its last line.
        self.assertEqual(real.whole_lines(path), ([{"a": 1}], 1))
        path.write_bytes(b"")
        self.assertEqual(real.whole_lines(path), ([], 0))

    def test_only_a_line_feed_ends_a_line_of_a_file(self):
        # JSON that is written without ASCII escapes holds these three as themselves; `str.splitlines` breaks at each.
        text = "앞\u2028가운데\u2029뒤\x85끝"
        self.assertEqual(len(text.splitlines()), 4)
        _, home = self.home(False)
        home.root = home.base
        (home.root / "raw").mkdir()
        (home.root / "raw/2026-11.jsonl").write_bytes(
            (json.dumps({"id": "e_000000000001", "text": text}, ensure_ascii=False) + "\n").encode("utf-8"))
        self.assertEqual(home.entries(), {"e_000000000001": {"id": "e_000000000001", "text": text}})
        self.assertTrue(worker.record(home.tap, "curate-3", SimpleNamespace(
            document="<request>%s</request>" % text, attempts=1, response=SimpleNamespace(text=text, failure=None))))
        self.assertTrue(worker.record(home.tap, "state-2", SimpleNamespace(
            document="<request/>", attempts=1, response=SimpleNamespace(text="{}", failure=None))))
        rows, broken = real.whole_lines(home.tap)
        self.assertEqual((broken, [row["answer"] for row in rows]), (0, [text, "{}"]))
        self.assertEqual(real.lines_of("a\nb\r\n"), ["a", "b\r"])  # JSON reads a line with its carriage return.
        self.assertEqual((real.lines_of(""), real.lines_of("\n"), real.lines_of("a")), ([], [""], ["a"]))

    def test_a_worker_and_a_hook_that_could_not_be_started_say_why(self):
        _, home = self.home(True)
        home.root, home.sessions = home.base, {}
        unstarted = {"exit": None, "error": "[Errno 12] Cannot allocate memory with REAL-KEY-VALUE-0123456789",
                     "stdout": "", "stderr": "", "seconds": 0}
        with mock.patch.object(real.hookcheck, "run", return_value=unstarted):
            with self.assertRaises(RuntimeError) as failed:
                home.work()
            self.assertEqual(str(failed.exception), "the worker could not be started: [Errno 12] Cannot allocate "
                                                    "memory with <memory key>")
            with self.assertRaises(RuntimeError) as failed:
                home.turn(real.SEED_262[0])
            self.assertEqual(str(failed.exception), "the prompt hook could not be started: [Errno 12] Cannot "
                                                    "allocate memory with <memory key>")
        self.assertEqual(real.how_ended({"exit": None, "stderr": ""}, str),
                         "could not be started: the runner gave no reason")
        self.assertEqual(real.how_ended({"exit": "timeout", "stderr": "late"}, str), "ended with timeout: late")

    def test_the_worker_is_told_the_process_that_started_it(self):
        _, home = self.home(False)
        seen = []

        def run(args, env, cwd=None, stdin="", timeout=180, line=None):
            seen.append(args)
            return {"exit": 0, "seconds": 0.1, "stdout": "", "stderr": ""}

        with mock.patch.object(real.hookcheck, "run", run):
            home.work(cut=64)
        self.assertEqual(seen[0][1:], [str(real.WORKER), str(home.tap), "64", str(os.getpid()), "plugin",
                                       "--reason", "end", "--project", "demo"])


class TapTests(unittest.TestCase):
    """The worker wrapper's line for a request, without a worker."""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.base), True)

    @staticmethod
    def result(text, failure=None, attempts=1):
        return SimpleNamespace(document="<request>문서</request>", attempts=attempts, response=SimpleNamespace(
            text=text, failure=None if failure is None else SimpleNamespace(code=failure)))

    def test_a_request_s_line_reads_back_as_it_was_also_with_half_a_surrogate_pair(self):
        tap = self.base / "requests.jsonl"
        self.assertTrue(worker.record(tap, "curate-3", self.result("답 \ud83d 끝", "max-tokens", 2)))
        self.assertTrue(worker.record(tap, "state-2", self.result("{}")))
        rows, broken = real.whole_lines(tap)
        self.assertEqual(broken, 0)
        self.assertEqual(rows[0], {"instructions": "curate-3", "document": "<request>문서</request>",
                                   "answer": "답 \ud83d 끝", "failure": "max-tokens", "attempts": 2})
        self.assertEqual((rows[1]["instructions"], rows[1]["failure"]), ("state-2", None))
        self.assertIn("문서".encode("utf-8"), tap.read_bytes())

    def test_a_line_that_cannot_be_written_is_left_out_and_nothing_is_raised(self):
        self.assertFalse(worker.record(self.base, "curate-3", self.result("{}")))  # TAP is a folder.
        self.assertFalse(worker.record(self.base / "requests.jsonl", "curate-3", SimpleNamespace()))
        self.assertFalse((self.base / "requests.jsonl").exists())


class RunnerTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "this test interrupts a process with a signal, which Windows does not send")
    def test_an_interrupt_of_the_runner_ends_the_process_that_it_started(self):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(base), True)
        mark = base / "pid"
        # Python leaves SIGINT ignored where its parent ignored it, as a shell's background job does.
        script = ("import os, signal, sys\n"
                  "signal.signal(signal.SIGINT, signal.default_int_handler)\n"
                  "sys.path.insert(0, sys.argv[1])\n"
                  "import run\n"
                  "try:\n"
                  "    run.run([sys.executable, '-c', sys.argv[3], sys.argv[2]], dict(os.environ), timeout=200)\n"
                  "except KeyboardInterrupt:\n"
                  "    print('interrupted')\n")
        runner = subprocess.Popen([sys.executable, "-c", script, str(FOLDER), str(mark), SLEEPER],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(runner.kill)
        child = started(mark)
        self.addCleanup(over, child)
        runner.send_signal(signal.SIGINT)
        out, err = runner.communicate(timeout=60)
        self.assertEqual((out.decode("utf-8").strip(), runner.returncode), ("interrupted", 0), err.decode("utf-8"))
        with self.assertRaises(ProcessLookupError):  # The child, in its own session, was ended and collected.
            os.kill(child, 0)


    def test_a_timeout_ends_the_process_and_the_one_that_it_started(self):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(base), True)
        mark = base / "pid"
        began = time.monotonic()
        done = real.hookcheck.run([sys.executable, "-c", TREE, str(mark)], dict(os.environ), timeout=10)
        self.assertEqual(done["exit"], "timeout")
        # The runner reads the output to its end: it came back long before the second process's own end.
        self.assertLess(time.monotonic() - began, 60)
        self.assertTrue(mark.read_text(encoding="utf-8"))  # The second process had been started.

    @unittest.skipUnless(os.name == "nt", "only Windows looks for a program's bare name in the current folder")
    def test_on_windows_a_program_named_taskkill_in_the_current_folder_is_not_started(self):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(base), True)
        system = Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32"
        # Another program under that name: started in `taskkill`'s place it ends nothing, and the runner waits.
        shutil.copyfile(str(system / "whoami.exe"), str(base / "taskkill.exe"))
        before = os.getcwd()
        os.chdir(str(base))
        try:
            began = time.monotonic()
            done = real.hookcheck.run([sys.executable, "-c", TREE, str(base / "pid")], dict(os.environ), timeout=10)
        finally:
            os.chdir(before)
        self.assertEqual(done["exit"], "timeout")
        self.assertLess(time.monotonic() - began, 60)


@unittest.skipIf(os.name == "nt", "these tests end a process with a signal that Windows does not send")
class SignalTests(unittest.TestCase):
    """The check as a process of its own, ended by a signal while a case's process runs."""

    # The check's last step waits here until the test lets it go on, so that a signal can reach it at that step.
    SCRIPT = ("import os, signal, sys, time\n"
              "for name in ('SIGTERM', 'SIGHUP'):  # Also where the test's own process ignores one, as under nohup.\n"
              "    signal.signal(getattr(signal, name), signal.SIG_DFL)\n"
              "signal.signal(signal.SIGINT, signal.default_int_handler)  # A shell's background job ignores it.\n"
              "sys.path.insert(0, sys.argv[1])\n"
              "import c2_real\n"
              "def waiting(*_):\n"
              "    c2_real.hookcheck.run([sys.executable, '-c', sys.argv[4], sys.argv[3]], dict(os.environ),\n"
              "                          timeout=200)\n"
              "    return {'outcome': 'pass'}\n"
              "closing = c2_real.close\n"
              "def close(*args):\n"
              "    open(sys.argv[3] + '.closing', 'w').close()\n"
              "    while not os.path.exists(sys.argv[3] + '.go'):\n"
              "        time.sleep(0.01)\n"
              "    return closing(*args)\n"
              "c2_real.close = close\n"
              "c2_real.RUNNERS.update({'TC-258': lambda *_: {'outcome': 'pass'}, 'TC-259': waiting})\n"
              "cases = [part for name in sys.argv[5:] or ['TC-258', 'TC-259', 'TC-261'] for part in ('--case', name)]\n"
              "sys.exit(c2_real.main([sys.argv[2], '--self-test'] + cases))\n")

    def check(self, *cases):
        """The check as a process, with its folder; its cases are TC-258, TC-259 and TC-261 unless named."""
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(base), True)
        environment = {key: value for key, value in os.environ.items() if key not in (ANTHROPIC, OPENAI)}
        check = subprocess.Popen([sys.executable, "-c", self.SCRIPT, str(FOLDER), str(base), str(base / "pid"),
                                  SLEEPER] + list(cases), env=environment, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
        self.addCleanup(check.kill)
        return check, base

    def at_its_last_step(self, check, base):
        """Wait until the check's last step has begun, where the test holds it."""
        deadline = time.time() + 60
        while not (base / "pid.closing").exists() and check.poll() is None and time.time() < deadline:
            time.sleep(0.02)

    def test_a_signal_that_ends_the_check_ends_the_running_process_and_keeps_the_report(self):
        for name, first, later in (("SIGTERM", [signal.SIGTERM], []), ("SIGHUP", [signal.SIGHUP], []),
                                   ("two at once", [signal.SIGHUP, signal.SIGTERM], []),
                                   ("more while the check ends", [signal.SIGTERM], [signal.SIGHUP, signal.SIGTERM]),
                                   ("Ctrl+C, then signals that end the process", [signal.SIGINT],
                                    [signal.SIGTERM, signal.SIGHUP]),
                                   ("Ctrl+C twice", [signal.SIGINT], [signal.SIGINT])):
            with self.subTest(name):
                check, base = self.check()
                child = started(base / "pid")
                self.addCleanup(over, child)
                for number in first:
                    check.send_signal(number)
                self.at_its_last_step(check, base)
                for number in later:
                    check.send_signal(number)
                (base / "pid.go").write_text("", encoding="utf-8")
                out, err = check.communicate(timeout=120)
                text = out.decode("utf-8", "replace")
                self.assertEqual((check.returncode, err.decode("utf-8", "replace")), (1, ""), text)
                report = json.loads((base / "c2-real/report.json").read_text(encoding="utf-8"))
                self.assertEqual({case: entry["outcome"] for case, entry in report["cases"].items()},
                                 {"TC-258": "pass", "TC-259": "not run"})
                self.assertIn("interrupted", report["crash"])
                self.assertIn("interrupted", text.splitlines()[-1])
                # The check's last step was made: a signal that came during it did not break it off.
                self.assertEqual((report["cost"]["requests"], report["files_with_key"]), (0, []))
                with self.assertRaises(ProcessLookupError):  # The case's process was ended and collected.
                    os.kill(child, 0)

    def test_the_local_server_s_threads_leave_the_signals_that_interrupt_the_check_to_the_main_thread(self):
        # A signal that one of them received would not end the main thread's wait for a case's process, so its
        # handler would run only after that process: of two signals at once Linux gives the second to another
        # thread, which can then take both.
        masks = []

        class Asked(real.Scripted):
            def count(self, value):
                masks.append(signal.pthread_sigmask(signal.SIG_BLOCK, []))
                return 1

        interrupting = {getattr(signal, name) for name in INTERRUPTING if hasattr(signal, name)}
        before = signal.pthread_sigmask(signal.SIG_BLOCK, [])
        self.assertEqual(interrupting & before, set())
        server = Asked()
        self.addCleanup(server.close)
        self.assertEqual(signal.pthread_sigmask(signal.SIG_BLOCK, []), before)  # The caller's own mask is kept.
        connection = http.client.HTTPConnection("127.0.0.1", server.server.server_port, timeout=30)
        self.addCleanup(connection.close)
        connection.request("POST", "/v1/messages/count_tokens", body=b"{}")
        self.assertEqual(json.loads(connection.getresponse().read().decode("utf-8")), {"input_tokens": 1})
        self.assertEqual([interrupting - mask for mask in masks], [set()])  # In the thread that answered.

    def test_a_signal_that_comes_while_the_check_ends_by_itself_does_not_break_off_its_ending(self):
        for name, number in (("SIGTERM", signal.SIGTERM), ("SIGHUP", signal.SIGHUP), ("Ctrl+C", signal.SIGINT)):
            with self.subTest(name):
                check, base = self.check("TC-258")
                self.at_its_last_step(check, base)
                self.assertIsNone(check.poll())
                check.send_signal(number)
                (base / "pid.go").write_text("", encoding="utf-8")
                out, err = check.communicate(timeout=120)
                self.assertEqual((check.returncode, err.decode("utf-8", "replace")), (0, ""),
                                 out.decode("utf-8", "replace"))
                report = json.loads((base / "c2-real/report.json").read_text(encoding="utf-8"))
                self.assertNotIn("crash", report)
                self.assertEqual((report["cases"]["TC-258"]["outcome"], report["cost"]["requests"],
                                  report["files_with_key"], report["files_not_read"]), ("pass", 0, [], []))


class WatchTests(unittest.TestCase):
    """The worker's wrapper as a process, around a made-up package whose worker stays for two minutes."""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.base), True)
        library = self.base / "plugin/skills/corthex-memory/scripts/memory_lib"
        library.mkdir(parents=True)
        (self.base / "plugin/scripts").mkdir()
        (library / "__init__.py").write_text("", encoding="utf-8")
        (library / "model_client.py").write_text("def send(memory, **options):\n    return None\n", encoding="utf-8")
        (library / "model_request.py").write_text("def build(**options):\n    return {}, None\n", encoding="utf-8")
        # As the package's worker has a process of its own for a request, this one starts a second process, which
        # holds the worker's output open. It writes down both IDs and stays.
        (self.base / "plugin/scripts/worker.py").write_text(
            "import os, subprocess, sys, time\n"
            "second = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'], stdout=sys.stdout,\n"
            "                          stderr=sys.stderr)\n"
            "open(sys.argv[1], 'w').write('%d %d' % (os.getpid(), second.pid))\n"
            "time.sleep(120)\n", encoding="utf-8")
        self.arguments = [str(FOLDER / "c2_real_worker.py"), str(self.base / "requests.jsonl"), "0", "CHECK",
                          str(self.base / "plugin"), str(self.base / "pids")]

    def pids(self):
        """The IDs of the wrapper's process and of the second one, once both are written down."""
        deadline = time.time() + 60
        while time.time() < deadline:
            found = (self.base / "pids").read_text(encoding="utf-8").split() if (self.base / "pids").exists() else []
            if len(found) == 2:
                return [int(value) for value in found]
            time.sleep(0.05)
        raise AssertionError("the made-up worker did not start within 60 s")

    def test_the_worker_ends_once_the_process_that_it_watches_is_gone(self):
        # Not the wrapper's parent, so on every system it is the ID that was given that is watched.
        check = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        self.addCleanup(check.kill)
        arguments = [str(check.pid) if value == "CHECK" else value for value in self.arguments]
        wrapper = subprocess.Popen([sys.executable] + arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=os.name != "nt")
        self.addCleanup(wrapper.kill)
        _, second = self.pids()
        if os.name == "nt":
            taskkill = os.path.join(os.environ.get("SystemRoot") or r"C:\Windows", "System32", "taskkill.exe")
            self.addCleanup(subprocess.run, [taskkill, "/F", "/PID", str(second)], capture_output=True)
            self.addCleanup(wrapper.stderr.close)
            self.addCleanup(wrapper.stdout.close)
        else:
            self.addCleanup(over, second)
        time.sleep(3 * worker.WATCH_SECONDS)
        self.assertIsNone(wrapper.poll())  # It runs for as long as the process that it watches.
        check.kill()
        check.wait()
        if os.name == "nt":  # There the second process is not ended with the worker, and holds its output open.
            self.assertEqual(wrapper.wait(timeout=30), 1)
            return
        _, err = wrapper.communicate(timeout=30)  # To the output's end: the second process is gone too.
        self.assertEqual((wrapper.returncode, err.decode("utf-8", "replace")), (-signal.SIGKILL, ""))
        self.assertTrue(ended(second))

    @unittest.skipIf(os.name == "nt", "this test ends a process with a signal that Windows does not send")
    def test_the_worker_ends_when_the_check_that_started_it_was_killed_and_nothing_has_collected_it_yet(self):
        # A stand-in for the check: it starts the wrapper as the runner does, names itself, and waits.
        script = ("import os, subprocess, sys\n"
                  "arguments = [str(os.getpid()) if value == 'CHECK' else value for value in sys.argv[1:]]\n"
                  "subprocess.Popen([sys.executable] + arguments, start_new_session=True).wait()\n")
        check = subprocess.Popen([sys.executable, "-c", script] + self.arguments, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
        self.addCleanup(check.kill)
        wrapper, second = self.pids()
        self.addCleanup(over, wrapper)
        self.addCleanup(over, second)
        os.kill(check.pid, signal.SIGKILL)
        # Until this test collects it below, the killed check is still there for whoever looks up its ID. Its
        # output ends only when the wrapper and the second process, which both hold it open, are gone.
        _, err = check.communicate(timeout=30)
        self.assertEqual((check.returncode, err.decode("utf-8", "replace")), (-signal.SIGKILL, ""))
        self.assertTrue(ended(wrapper) and ended(second))


class ScriptedTests(unittest.TestCase):
    def setUp(self):
        self.server = real.Scripted()
        self.addCleanup(self.server.close)

    def test_a_seed_turn_gets_its_script_s_change_and_line_and_the_answer_fits(self):
        turn = real.SEED_345[2]
        entry, reply = ident("e", 1), ident("e", 2)
        answer = self.server.answer(request([(entry, "user", turn.prompt), (reply, "agent", turn.reply)]))
        curator_answers.decode(answer)
        self.assertEqual(answer["changes"], [{"action": "add", "targets": [], "kind": "decision",
                                              "quotes": [{"entry": entry, "words": turn.prompt}],
                                              "title": turn.script["title"], "text": turn.script["text"],
                                              "conflicts": []}])
        self.assertEqual(answer["state"]["add"], [{"part": "decisions", "after": "", "text": turn.script["text"],
                                                   "cites": [], "changes": [1]}])

    def test_a_turn_without_a_script_an_agent_s_entry_and_other_words_get_nothing(self):
        small = real.INSIDE_261[3]
        answer = self.server.answer(request([(ident("e", 1), "user", small.prompt),
                                             (ident("e", 2), "agent", real.SEED_345[2].prompt),
                                             (ident("e", 3), "user", "스크립트에 없는 말")]))
        self.assertEqual(answer, EMPTY)

    def test_a_short_yes_quotes_the_user_first_and_then_the_proposal_before_it(self):
        proposal, yes = real.INSIDE_261[0], real.INSIDE_261[1]
        entries = [(ident("e", 1), "user", proposal.prompt), (ident("e", 2), "agent", proposal.reply),
                   (ident("e", 3), "user", yes.prompt), (ident("e", 4), "agent", yes.reply)]
        answer = self.server.answer(request(entries))
        curator_answers.decode(answer)
        self.assertEqual(answer["changes"][0]["quotes"], [{"entry": ident("e", 3), "words": "응"},
                                                          {"entry": ident("e", 2), "words": proposal.reply}])

    def test_a_changed_fact_replaces_its_item_and_changes_only_the_lines_that_cite_it(self):
        old, other = ident("i", 1), ident("i", 2)
        lines = [(ident("s", 1), [old], "포트는 8443"), (ident("s", 2), [other], "CSV만 읽는다")]
        items = [(old, real.SEED_345[2].script["title"]), (other, real.SEED_345[1].script["title"])]
        answer = self.server.answer(request([(ident("e", 9), "user", real.CHANGE_345.prompt)], items, lines))
        curator_answers.decode(answer)
        self.assertEqual((answer["changes"][0]["action"], answer["changes"][0]["targets"]), ("replace", [old]))
        self.assertEqual([edit["line"] for edit in answer["state"]["change"]], [ident("s", 1)])
        self.assertEqual((answer["state"]["add"], answer["state"]["remove"]), ([], []))

    def test_a_rule_that_disagrees_names_the_earlier_rule_as_a_conflict(self):
        squash = ident("i", 1)
        items = [(squash, real.SEED_356[0].script["title"]), (ident("i", 2), real.SEED_356[1].script["title"])]
        answer = self.server.answer(request([(ident("e", 9), "user", real.LATER_356[0].prompt)], items))
        curator_answers.decode(answer)
        self.assertEqual((answer["changes"][0]["action"], answer["changes"][0]["targets"],
                          answer["changes"][0]["conflicts"]), ("add", [], [squash]))

    def test_a_merge_request_merges_the_two_seeded_decisions_and_a_state_request_keeps_the_state(self):
        items = [(ident("i", 2), real.SEED_258[1].script["title"]), (ident("i", 1), real.SEED_258[0].script["title"]),
                 (ident("i", 3), real.SEED_258[2].script["title"])]
        answer = self.server.answer(request([], items, kind="merge", instructions="merge-2"))
        curator_answers.decode(answer, curator_answers.merge_schema())
        self.assertEqual(answer["merges"][0]["items"], [ident("i", 1), ident("i", 2)])
        self.assertEqual(answer["merges"][0]["quotes"], [{"item": ident("i", 1), "number": 1},
                                                         {"item": ident("i", 2), "number": 1}])
        alone = self.server.answer(request([], items[:1], kind="merge", instructions="merge-2"))
        self.assertEqual(alone, {"merges": [], "conflicts": []})
        kept = self.server.answer(request([], kind="state", instructions="state-2"))
        curator_answers.decode(kept, curator_answers.state_schema())
        self.assertEqual(kept, KEPT)

    def test_a_request_for_few_tokens_gets_an_answer_that_was_cut(self):
        turn = real.CUT_259[0]
        body = request([(ident("e", 1), "user", turn.prompt)], max_tokens=real.CUT)
        answer = self.server.answer(body)
        self.assertIsInstance(answer, bytes)
        self.assertIn(b'"stop_reason": "max_tokens"', answer)
        self.assertNotIn(b"content_block_delta", answer)
        whole = self.server.answer(dict(body, max_tokens=64000))
        self.assertEqual(len(whole["changes"]), 1)

    def test_every_scripted_turn_has_its_own_prompt(self):
        prompts = [turn.prompt for turn in real.TURNS]
        self.assertEqual(len(prompts), len(set(prompts)))
        self.assertEqual(set(self.server.scripts), {turn.prompt for turn in real.TURNS if turn.script})
        for turn in real.TURNS:
            self.assertIn(turn.host, ("claude", "codex"))

    def test_the_made_up_key_s_turn_is_redacted_by_the_package_and_has_no_script(self):
        from memory_lib import redaction
        key = "sk-ant-" + "madeup" + "0" * 32
        turn = real.key_turn(key)
        self.assertIsNone(turn.script)
        self.assertIn(key, turn.prompt)
        kind, pattern = redaction.COMPILED[1]
        self.assertEqual(kind, "anthropic-key")
        self.assertEqual(pattern.search(turn.prompt).group(0), key)


class PathTests(unittest.TestCase):
    def test_the_worker_and_the_contract_have_whole_paths_however_the_script_was_named(self):
        # Python 3.8 gives a script the path as it was typed; `runpy` does so on every version.
        probe = ("import runpy\n"
                 "found = runpy.run_path('.github/hook-check/c2_real.py', run_name='c2_real_probed')\n"
                 "print(found['WORKER'].is_absolute(), found['CONTRACT'].is_absolute(), found['WORKER'].is_file())\n")
        done = subprocess.run([sys.executable, "-c", probe], cwd=str(ROOT), capture_output=True, timeout=120)
        self.assertEqual((done.stdout.decode("utf-8").strip(), done.returncode), ("True True True", 0),
                         done.stderr.decode("utf-8", "replace"))

    def test_started_as_a_script_it_leaves_no_bytecode_beside_the_checkout_s_modules(self):
        cache = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(cache), True)
        # Whatever the process caches goes under the folder that it is given here, and nothing may tell it from
        # outside to cache nothing: the check itself has to say so before it loads the modules beside it.
        environment = {key: value for key, value in os.environ.items() if key != "PYTHONDONTWRITEBYTECODE"}
        environment["PYTHONPYCACHEPREFIX"] = str(cache)
        done = subprocess.run([sys.executable, str(FOLDER / "c2_real.py"), "--help"], capture_output=True,
                              env=environment, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
        self.assertIn(b"OUTDIR", done.stdout)
        self.assertEqual([path.name for path in cache.rglob("*.pyc") if "hook-check" in path.parts], [])


class SelfTestRun(unittest.TestCase):
    def test_three_cases_run_to_their_end_against_the_local_server_even_in_ci(self):
        base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, base, True)
        environment = dict(os.environ, CI="true")
        environment.update({ANTHROPIC: "ENVIRONMENT-ANTHROPIC-KEY-0001", OPENAI: "ENVIRONMENT-OPENAI-KEY-0001"})
        # Started as a person starts it, by its path from the checkout: the worker still gets a path that it finds.
        done = subprocess.run([sys.executable, str(Path(".github/hook-check/c2_real.py")), base, "--self-test",
                               "--case", "TC-258", "--case", "TC-259", "--case", "TC-262"],
                              cwd=str(ROOT), env=environment, capture_output=True, timeout=900)
        output = done.stdout.decode("utf-8", "replace")
        self.assertEqual((done.returncode, done.stderr.decode("utf-8", "replace")), (0, ""), output)
        self.assertIn(real.SELF_TEST, output.splitlines()[0])
        out = Path(base) / "c2-real"
        text = (out / "report.json").read_text(encoding="utf-8")
        report = json.loads(text)
        self.assertTrue(report["self_test"])
        self.assertEqual(report["provider"], real.SELF_TEST)
        self.assertEqual({name: entry["outcome"] for name, entry in report["cases"].items()},
                         {"TC-258": "pass", "TC-259": "pass", "TC-262": "pass"})
        self.assertEqual((report["files_with_key"], report["local_requests_with_key"]), ([], 0))
        self.assertNotIn("key_in_report", report)
        self.assertGreater(report["local_requests"], 0)
        self.assertEqual(report["keys"], {ANTHROPIC: "present", OPENAI: "present"})
        for secret in ("ENVIRONMENT-ANTHROPIC-KEY-0001", "ENVIRONMENT-OPENAI-KEY-0001", "sk-ant-madeup"):
            self.assertNotIn(secret, text)
        cut = report["cases"]["TC-259"]["runs"][0]
        self.assertEqual(cut["observed"]["turns left to curate"], [2, 2])
        self.assertEqual(cut["observed"]["the next run, with the package's own max_tokens"]["turns left to curate"], 0)
        self.assertEqual([run["provider"] for run in report["cases"]["TC-262"]["runs"][0]["runs"]],
                         [real.SEED, real.SELF_TEST])
        requests = [json.loads(line) for line in (out / "tc-262-1/requests.jsonl").read_text(
            encoding="utf-8").splitlines()]
        self.assertEqual([row["instructions"] for row in requests], ["curate-3", "curate-3"])
        self.assertIn("[redacted:anthropic-key]", requests[1]["document"])
        self.assertIn(real.PASTED[1], requests[1]["document"])
        # The staged package is what was checked: no hook, no worker and no reading of the check itself, which
        # loads the package's decoder for TC-258, left bytecode files in it.
        self.assertEqual([path.relative_to(out).as_posix() for path in out.rglob("*")
                          if path.name == "__pycache__" or path.suffix == ".pyc"], [])


if __name__ == "__main__":
    unittest.main()
