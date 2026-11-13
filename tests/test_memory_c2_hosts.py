"""TASK-099 and TASK-101: the verdicts and helpers of the installed-host C2 checks, on made-up reports and files.

No host runs here.
"""
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
import ntpath
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from _common import ROOT

FOLDER = ROOT / ".github/hook-check"
sys.path.insert(0, str(FOLDER))
sys.path.insert(0, str(ROOT / "plugins/corthex-memory/skills/corthex-memory/scripts"))
from memory_lib import hooks as memory_hooks  # noqa: E402


def load(name):
    spec = importlib.util.spec_from_file_location(name + "_checked", FOLDER / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hosts, walk, timing = load("c2_hosts"), load("c2_walk_replay"), load("c2_recall_timing")

START = 1794000000.0
HOOKS = ("start", "prompt", "end-of-turn", "end")
KEYS = {"files_with_marker": [], "command_lines_with_marker": 0, "requests_with_key": 4}
ANTHROPIC, OPENAI = "CORTHEX_MEMORY_ANTHROPIC_API_KEY", "CORTHEX_MEMORY_OPENAI_API_KEY"
NOT_COUNTED = "the requests were not counted between two moments without a worker"


class Clock:
    """A clock that only its own sleep moves, in place of the `time` module of a wait."""

    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def stamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def session(number, outcomes=None):
    """One session's report as `Hosts.decide` writes it, with every check met; sessions start 100 seconds apart."""
    host, turns = hosts.DECISIONS[number][:2]
    started = START + 100 * number
    reason = "end-of-turn" if turns == 1 else "end"
    return {"label": "decision %d" % (number + 1), "host": host, "exit": 0, "started": started,
            "ended": started + 10, "expected_reason": reason, "reasons": [reason, "start"],
            "hooks": {name: {"outcome": (outcomes or {}).get(name, "ok"), "ms": 100} for name in HOOKS},
            "held_after_exit": True, "settled": {"applied": True}, "decision": True,
            "run_logged": {"items": 2, "unlisted": [], "runs": ["r_1"]},
            "command_reads": {"reads": 4, "lines": 40, "errors": []}, "workers": ["worker.py --reason " + reason],
            "shows_earlier": {"earlier": True} if number else {}}


def failure(number, host, hook, step, error, after=2.0):
    """A failure log line written `after` seconds into a session."""
    return {"at": stamp(START + 100 * number + after), "hook": hook, "step": step, "error": error, "host": host}


def report(sessions=None, failures=(), recalls=None):
    return {"sessions": [session(number) for number in range(4)] if sessions is None else sessions,
            "failures": list(failures), "command_lines": 160,
            "keys": {ANTHROPIC: dict(KEYS), OPENAI: dict(KEYS)},
            "recalls": {"claude": {"injected": 1}, "codex": {"injected": 2}} if recalls is None else recalls,
            "scrub": {"exit": 0, "keys_reached_hooks": {ANTHROPIC: False, OPENAI: False}, "notice": True,
                      "memory_requests": [], "workers_gone": {"before": True, "after": True}}}


class C2HostVerdictsTest(unittest.TestCase):
    def verdicts(self, *args, **kwargs):
        return hosts.verdicts(report(*args, **kwargs))

    def test_tc253_to_tc257_pass_when_every_check_is_met(self):
        found = self.verdicts()
        self.assertEqual([found[case] for case in ("TC-253", "TC-254", "TC-255", "TC-257")], [True] * 4)
        self.assertEqual((found["late recalls"], found["blocking_failures"], found["hooks_ok"]), (0, [], True))

    def test_tc253_counts_a_recall_that_gave_up_at_its_window_and_does_not_fail_on_it(self):
        # The first prompt on a slow machine: the recall's embedding missed its window, the hook returned with
        # the outcome `deadline` and noted one line (API-010), whose code is `timeout` when the request was out.
        for code in ("deadline", "timeout"):
            with self.subTest(code):
                sessions = [session(0, {"prompt": "deadline"})] + [session(number) for number in (1, 2, 3)]
                line = failure(0, "claude-code", "prompt", "recall", code)
                found = self.verdicts(sessions, [line])
                self.assertTrue(found["TC-253"])
                self.assertEqual((found["late recalls"], found["blocking_failures"]), (1, []))
                self.assertTrue(found["sessions"]["decision 1"]["four hooks ok or late in recall"])
                self.assertFalse(found["hooks_ok"])  # the report still says that not every outcome was `ok`

    def test_tc253_fails_for_a_recall_that_failed(self):
        # Any other code of the recall step is a recall that failed, which the hook's outcome `error` says too.
        sessions = [session(0, {"prompt": "error"})] + [session(number) for number in (1, 2, 3)]
        line = failure(0, "claude-code", "prompt", "recall", "http-500")
        found = self.verdicts(sessions, [line])
        self.assertFalse(found["TC-253"])
        self.assertEqual((found["late recalls"], found["blocking_failures"]), (0, [line]))

    def test_tc253_fails_when_a_deadline_cut_any_other_step(self):
        for hook, step in (("prompt", "record"), ("prompt", "compaction"), ("end-of-turn", "trigger")):
            with self.subTest(hook=hook, step=step):
                sessions = [session(0, {hook: "deadline"})] + [session(number) for number in (1, 2, 3)]
                line = failure(0, "claude-code", hook, step, "deadline")
                found = self.verdicts(sessions, [line])
                self.assertFalse(found["TC-253"])
                self.assertEqual(found["blocking_failures"], [line])
                self.assertFalse(found["sessions"]["decision 1"]["four hooks ok or late in recall"])

    def test_tc253_fails_for_a_deadline_outcome_without_that_session_s_own_late_recall_line(self):
        sessions = [session(number) for number in (0, 1)] + [session(2, {"prompt": "deadline"}), session(3)]
        for name, line in (("no line", None),
                           ("another session's line", failure(0, "claude-code", "prompt", "recall", "deadline")),
                           ("the other host's line", failure(2, "codex", "prompt", "recall", "deadline"))):
            with self.subTest(name):
                found = self.verdicts(sessions, [line] if line else [])
                self.assertFalse(found["TC-253"])
                self.assertFalse(found["sessions"]["decision 3"]["four hooks ok or late in recall"])
                self.assertEqual(found["blocking_failures"], [])

    def test_tc253_fails_for_a_late_recall_s_outcome_on_another_hook(self):
        sessions = [session(0, {"end": "deadline"})] + [session(number) for number in (1, 2, 3)]
        found = self.verdicts(sessions, [failure(0, "claude-code", "prompt", "recall", "deadline")])
        self.assertFalse(found["TC-253"])

    def test_tc253_fails_when_a_hook_that_can_start_the_worker_ran_past_its_own_deadline(self):
        name = "worker-starting hooks within their deadlines"
        for hook, limit in sorted(hosts.DEADLINE_MS.items()):
            for ms, expected in ((limit, True), (limit + 1, False), (None, False)):
                with self.subTest(hook=hook, ms=ms):
                    sessions = [session(number) for number in range(4)]
                    sessions[1]["hooks"][hook]["ms"] = ms
                    found = self.verdicts(sessions)
                    self.assertEqual((found["TC-253"], found["sessions"]["decision 2"][name]), (expected, expected))
                    self.assertTrue(found["sessions"]["decision 1"][name])

    def test_tc253_leaves_the_prompt_hook_s_time_to_tc256(self):
        sessions = [session(number) for number in range(4)]
        sessions[0]["hooks"]["prompt"]["ms"] = 5000
        self.assertTrue(self.verdicts(sessions)["TC-253"])

    def test_the_deadlines_judged_are_the_hooks_own(self):
        own = {hook: int(round(seconds * 1000)) for hook, seconds in memory_hooks.SECONDS.items()}
        self.assertEqual(hosts.DEADLINE_MS, {hook: ms for hook, ms in own.items() if hook != "prompt"})

    def test_tc253_lists_a_lock_that_stayed_busy_and_passes(self):
        line = failure(1, None, None, "curate", "lock-busy")
        found = self.verdicts(failures=[line])
        self.assertTrue(found["TC-253"])
        self.assertEqual(found["blocking_failures"], [])

    def test_tc253_fails_for_any_other_failure_line(self):
        line = failure(1, None, None, "curate", "OSError")
        found = self.verdicts(failures=[line])
        self.assertFalse(found["TC-253"])
        self.assertEqual(found["blocking_failures"], [line])

    def test_tc254_still_needs_a_ranked_recall_in_each_host(self):
        # A host whose only recall with items was late has shown no ranking with its key: no evidence, no pass.
        sessions = [session(number) for number in (0, 1)] + [session(2, {"prompt": "deadline"}), session(3)]
        line = failure(2, "claude-code", "prompt", "recall", "deadline")
        found = self.verdicts(sessions, [line], {"claude": {"no-index": 1, "late": 1}, "codex": {"injected": 2}})
        self.assertTrue(found["TC-253"])
        self.assertFalse(found["TC-254"])
        self.assertEqual(found["ranked recalls"], {"claude": 0, "codex": 2})

    def test_tc254_fails_for_a_store_file_that_could_not_be_read(self):
        value = report()
        value["unread_files"] = [".corthex/corthex-memory/projects/demo/curation.json.0a1b2c3d.tmp"]
        found = hosts.verdicts(value)
        self.assertEqual((found["TC-253"], found["TC-254"]), (True, False))

    def test_tc257_needs_each_key_in_a_request_or_the_notice_and_no_request(self):
        reached, kept, one = "keys reached the hooks", "keys kept from the hooks", "only one key reached the hooks"
        cases = (
            # (a request carried the Anthropic key, one carried the OpenAI key, the notice was shown, the kinds
            # of the requests that came, the verdict, what the summary says)
            (True, True, False, ["embeddings", "curate"], True, reached),
            (False, False, True, [], True, kept),
            (False, False, False, [], False, kept),
            # Where the keys are kept from the hooks nothing is sent, so a request without a key fails the case.
            (False, False, True, ["embeddings"], False, kept),
            (False, False, False, ["embeddings"], False, kept),
            # A host that passes one key and keeps the other fails it, with the notice or without.
            (False, True, False, ["embeddings"], False, one),
            (True, False, True, ["curate"], False, one),
        )
        for anthropic, openai, notice, sent, expected, observed in cases:
            with self.subTest(anthropic=anthropic, openai=openai, notice=notice, sent=sent):
                value = report()
                value["scrub"].update(keys_reached_hooks={ANTHROPIC: anthropic, OPENAI: openai}, notice=notice,
                                      memory_requests=sent)
                found = hosts.verdicts(value)
                self.assertEqual((found["TC-257"], found["TC-257 observed"]), (expected, observed))

    def test_tc257_fails_when_its_requests_were_not_counted_between_two_moments_without_a_worker(self):
        # A worker that was left then sent requests that are another session's, or that were still to come. A
        # reading that failed counts as a worker, and a report of an earlier check has no such moments at all:
        # neither shows that no worker was left, so the verdict says what was not observed.
        absent = object()
        for gone in ({"before": False, "after": True}, {"before": True, "after": False}, {}, None, absent):
            with self.subTest(gone=gone):
                value = report()
                value["scrub"]["workers_gone"] = gone
                if gone is absent:
                    del value["scrub"]["workers_gone"]
                found = hosts.verdicts(value)
                self.assertEqual((found["TC-257"], found["TC-257 observed"]), (False, NOT_COUNTED))
                self.assertEqual([found[case] for case in ("TC-253", "TC-254", "TC-255")], [True] * 3)

    def test_a_request_carries_a_key_in_any_of_its_headers(self):
        row = {"headers": {"x-api-key": "sk-made-up-1", "content-type": "application/json"}}
        self.assertTrue(hosts.carries(row, "sk-made-up-1"))
        self.assertFalse(hosts.carries(row, "sk-made-up-2"))
        self.assertTrue(hosts.carries({"headers": {"authorization": "Bearer sk-made-up-2"}}, "sk-made-up-2"))

    def test_only_a_held_request_that_is_not_answered_yet_counts_as_held(self):
        # After HOLD_SECONDS the server answers by itself; such a request was not held past the host's exit.
        rows = [{"holding": True, "at": 1.0}, {"holding": True, "at": 2.0, "answered": 5.0}, {"holding": False}, {}]
        self.assertEqual(hosts.unanswered(rows), [{"holding": True, "at": 1.0}])


class C2HostRequestsTest(unittest.TestCase):
    """What the local memory server reads of a request, and where the checks take programs from."""

    @staticmethod
    def request(content):
        return {"messages": [{"content": content}]}

    def test_a_request_s_kind_entries_and_items_are_read(self):
        value = self.request(
            '<request kind="curate" instructions="made up"><entries>'
            '<entry id="e_1" speaker="user">결정: A &lt;B&gt; &amp; C</entry><entry id="e_2" speaker="agent"/>'
            '</entries><items><item id="i_1"><title>Decision &quot;X&quot;</title><text>T</text></item></items>'
            '</request>')
        self.assertEqual(hosts.request_kind(value), "curate")
        self.assertEqual(hosts.MemoryServer.entries(value),
                         [("e_1", "user", "결정: A <B> & C"), ("e_2", "agent", "")])
        self.assertEqual(hosts.MemoryServer.items(value), {"i_1": 'Decision "X"'})

    def test_a_request_with_a_document_type_is_refused(self):
        # Without a document type a request declares no entity, so none expands.
        expanding = ('<!DOCTYPE request [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
                     '<request kind="curate">&b;</request>')
        for content in (expanding, '<!DOCTYPE request><request kind="curate"/>'):
            with self.subTest(content=content[:28]):
                for read in (hosts.request_kind, hosts.MemoryServer.entries, hosts.MemoryServer.items):
                    with self.assertRaises(ValueError):
                        read(self.request(content))

    def test_a_request_that_is_not_xml_is_a_value_error(self):
        # The server's handler notes a ValueError on the request's row and answers nothing.
        for content in ("", "not XML", '<request kind="curate">', "<a/><b/>", "<request>&undeclared;</request>"):
            with self.subTest(content=content):
                with self.assertRaises(ValueError):
                    hosts.document(self.request(content))

    def test_a_program_comes_from_an_absolute_folder_of_path_only(self):
        folder = Path(tempfile.mkdtemp(prefix="c2-program-")).resolve()
        self.addCleanup(shutil.rmtree, str(folder), True)
        tool = folder / ("made-up-tool" + (".exe" if os.name == "nt" else ""))
        tool.write_bytes(b"")
        tool.chmod(0o755)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(str(folder))
        # The current folder holds the program, and PATH names that folder only as itself and as a relative one.
        with mock.patch.dict(os.environ, {"PATH": os.pathsep.join((".", "", os.curdir + os.sep))}):
            with self.assertRaises(OSError):
                hosts.program("made-up-tool")
        with mock.patch.dict(os.environ, {"PATH": os.pathsep.join((".", '"%s"' % folder))}):
            self.assertEqual(os.path.normcase(hosts.program("made-up-tool")), os.path.normcase(str(tool)))

    def test_a_host_s_shim_is_found_by_its_extension_in_an_absolute_folder(self):
        # On Windows the hosts are npm `.cmd` shims: each folder of the given path is tried with each extension.
        first, second = (Path(tempfile.mkdtemp(prefix="c2-shim-")).resolve() for _ in range(2))
        for folder in (first, second):
            self.addCleanup(shutil.rmtree, str(folder), True)
        shim, other = first / "made-up-host.cmd", second / "made-up-host.exe"
        for path in (shim, other):
            path.write_bytes(b"")
            path.chmod(0o755)
        both = os.pathsep.join((str(first), str(second)))
        self.assertEqual(hosts.program("made-up-host", both, (".exe", ".cmd")), str(shim))
        self.assertEqual(hosts.program("made-up-host", os.pathsep.join((str(second), str(first))), (".exe", ".cmd")),
                         str(other))
        with self.assertRaises(OSError):
            hosts.program("made-up-host", str(first), (".exe",))
        # Only a host is looked for as a shim. Any other program is an `.exe` on Windows, whatever PATHEXT says:
        # a batch file of its name in an earlier folder is passed by.
        self.assertEqual(hosts.HOST_EXTENSIONS, (".exe", ".cmd", ".bat") if os.name == "nt" else ("",))
        with mock.patch.object(hosts.os, "name", "nt"), mock.patch.dict(os.environ, {"PATHEXT": ".CMD;.EXE"}):
            self.assertEqual(hosts.program("made-up-host", both), str(other))
        # The given path is the one searched, and a folder that is not absolute is never tried.
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(str(first))
        with mock.patch.dict(os.environ, {"PATH": both}):
            with self.assertRaises(OSError):
                hosts.program("made-up-host", os.pathsep.join((".", "")), (".cmd",))


class C2HostFilesTest(unittest.TestCase):
    """The checks' readers of the memory store, on a made-up store that a worker may be writing."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="c2-hosts-"))
        self.addCleanup(shutil.rmtree, str(self.home), True)
        self.store = self.home / ".corthex/corthex-memory"
        self.root = self.store / "projects/demo"
        (self.root / "layer/items").mkdir(parents=True)

    def item(self, ident, title):
        (self.root / "layer/items" / (ident + ".json")).write_text(json.dumps({"id": ident, "title": title}),
                                                                   encoding="utf-8")

    def injections(self, name, outcomes):
        folder = self.root / "injections"
        folder.mkdir(exist_ok=True)
        (folder / name).write_text("".join(json.dumps({"where": "prompt", "outcome": outcome}) + "\n"
                                           for outcome in outcomes), encoding="utf-8")

    def failures(self, rows):
        (self.store / "logs").mkdir(exist_ok=True)
        (self.store / "logs/failures-2026-11-12.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def hosts_object(self, **values):
        """A `Hosts` that staged and started nothing: only what the method under test reads."""
        checked = hosts.Hosts.__new__(hosts.Hosts)
        checked.home, checked.report, checked.lines, checked.label = self.home, {}, [], None
        # Without a run's folder every memory worker counts as this run's.
        checked.run_folder = None
        for name, value in values.items():
            setattr(checked, name, value)
        return checked

    def test_only_a_host_whose_recalls_gave_up_and_ranked_nothing_is_asked_once_more(self):
        checked = self.hosts_object()
        self.assertEqual(checked.late_only(), [])
        self.injections("claude-code-1.jsonl", ["no-index", "late"])
        self.injections("codex-1.jsonl", ["late", "injected"])
        self.assertEqual(checked.late_only(), ["claude"])
        self.injections("claude-code-2.jsonl", ["below"])
        self.assertEqual(checked.late_only(), [])
        # A recall that failed in another way is not a slow runner's: the host is not asked again.
        self.injections("codex-1.jsonl", ["error"])
        self.assertEqual(checked.late_only(), [])

    def test_a_late_recall_that_left_only_its_failure_line_is_asked_once_more(self):
        # The injection log's line is skipped when its lock stays busy; the prompt hook's note is still there.
        checked = self.hosts_object()
        self.failures([failure(0, "codex", "prompt", "recall", "lock-busy"),
                       failure(0, "claude-code", "end", "curate", "deadline")])
        self.assertEqual(checked.late_only(), [])
        self.failures([failure(0, "claude-code", "prompt", "recall", "timeout")])
        self.assertEqual(checked.late_only(), ["claude"])
        self.injections("claude-code-1.jsonl", ["no-index"])
        self.assertEqual(checked.late_only(), ["claude"])
        self.injections("claude-code-2.jsonl", ["injected"])
        self.assertEqual(checked.late_only(), [])

    def test_a_failure_log_that_is_being_written_is_read_again_and_then_left_to_the_injection_log(self):
        checked = self.hosts_object()
        self.injections("codex-1.jsonl", ["late"])
        note = failure(0, "claude-code", "prompt", "recall", "timeout")
        self.failures([note])
        self.assertEqual((checked.late_only(), checked.report), (["claude", "codex"], {}))
        # A line that a worker is writing just now is whole a moment later: the second read finds the note.
        with mock.patch.object(hosts, "failure_rows", side_effect=[ValueError("half a line"), [note]]) as read, \
                mock.patch.object(hosts.time, "sleep") as sleep:
            self.assertEqual((checked.late_only(), checked.report), (["claude", "codex"], {}))
        self.assertEqual((read.call_count, sleep.call_args_list), (2, [mock.call(hosts.STORE_READ_PAUSE)]))
        # A log that stays unread after every read leaves the injection log to decide. The report names the
        # kind of the error and nothing of the log, and the run's end, which reads the log strictly, still
        # fails on such a line.
        path = self.store / "logs/failures-2026-11-12.jsonl"
        path.write_text(path.read_text(encoding="utf-8") + '{"at": "2026-11-', encoding="utf-8")
        with mock.patch.object(hosts, "failure_rows", wraps=hosts.failure_rows) as read, \
                mock.patch.object(hosts.time, "sleep") as sleep:
            self.assertEqual(checked.late_only(), ["codex"])
        # A pause comes between two reads, and none after the last.
        self.assertEqual((read.call_count, sleep.call_args_list),
                         (hosts.FAILURE_LOG_READS, [mock.call(hosts.STORE_READ_PAUSE)] * (hosts.FAILURE_LOG_READS - 1)))
        self.assertEqual(checked.report, {"late_notes_unread": "JSONDecodeError"})
        with self.assertRaises(ValueError):
            hosts.failure_rows(self.home)

    def test_one_more_session_answers_at_once_waits_for_its_worker_and_is_reported(self):
        sampler, memory = mock.Mock(lines=["a line"]), mock.Mock()
        session = {"label": "recall again (claude)", "exit": 0, "started": START, "ended": START + 5,
                   "sampler": sampler, "bodies": ["a body"]}
        checked = self.hosts_object(memory=memory, session=mock.Mock(return_value=session),
                                    rested=mock.Mock(return_value=True))
        with mock.patch.object(hosts, "configure") as configure:
            result = checked.recall_again("claude", "/made-up/claude")
        configure.assert_called_once_with(self.home, 10)
        # The gate is open, so the session's curate request is answered at once.
        self.assertEqual([call[0] for call in memory.method_calls], ["rearm", "release"])
        checked.session.assert_called_once_with("claude", "/made-up/claude", hosts.AGAIN,
                                                label="recall again (claude)")
        sampler.stop.assert_called_once_with()
        # Its worker is waited for, and the result says whether it went.
        checked.rested.assert_called_once_with()
        self.assertEqual((checked.lines, checked.report["recall_again"]), (["a line"], [result]))
        self.assertEqual((result["rested"], result["hooks"], "sampler" in result, "bodies" in result),
                         (True, {}, False, False))

    def test_a_wait_for_the_workers_counts_its_readings_and_one_that_runs_out_is_reported(self):
        name, key = "scrub (claude/output-5.txt)", "MARKER-A-0123456789"
        # A key that lies across the place where a long line is cut.
        worker = "python /made-up/" + "x" * 347 + "/scripts/worker.py --reason end "
        whole = worker + key + " --project demo"
        self.assertEqual(len(worker), 395)
        checked = self.hosts_object(label=name, keys={ANTHROPIC: key}, run_folder="/made-up")
        # What `quiet` gives of each wait, and whether the wait ended as calm.
        waits = [(True, {"busy": False, "workers": [], "lines": ["python other.py", whole]}),
                 (False, {"busy": True, "calm": 0.0, "workers": [whole], "lines": [whole, whole]}),
                 (False, {"busy": "unread: PermissionError", "calm": 0.0, "unread": "OSError('no ps %s')" % key,
                          "lines": []}),
                 (False, {"busy": False, "calm": 1.4, "workers": [], "lines": []})]

        def wait(root, turns, worker, seen, run_folder):
            # No turn is waited for, and the command lines are read for this run's workers of any kind.
            self.assertEqual((root, turns, worker, seen, run_folder), (self.root, False, "", {}, "/made-up"))
            calm, found = waits.pop(0)
            seen.update(found)
            return calm
        with mock.patch.object(hosts, "quiet", side_effect=wait), mock.patch.object(hosts, "command_lines") as read:
            self.assertTrue(checked.rested())
            # A wait that ended as calm leaves nothing in the report, and every line of its readings counts
            # for TC-254.
            self.assertEqual((checked.report, checked.lines), ({}, ["python other.py", whole]))
            self.assertEqual([checked.rested() for _ in range(3)], [False] * 3)
        # What the wait saw is kept as it was: nothing is read again once the wait is over.
        read.assert_not_called()
        # The lease at the last look, or that the look could not tell; for how long no lease had been seen;
        # and the workers' lines or the error of the last reading since the lease was last seen.
        self.assertEqual(checked.report["workers_left"], [
            {"after": name, "lease": True, "calm_seconds": 0.0, "workers": [worker + "<mark..."]},
            {"after": name, "lease": "unread: PermissionError", "calm_seconds": 0.0,
             "unread": "OSError('no ps <marker>')"},
            {"after": name, "lease": False, "calm_seconds": 1.4, "workers": []}])
        self.assertNotIn("MARK", json.dumps(checked.report))
        self.assertEqual(checked.lines, ["python other.py"] + [whole] * 3)

    def test_a_session_s_report_masks_a_key_in_a_worker_s_line_before_it_cuts_the_line(self):
        key = "MARKER-A-0123456789"
        worker = "python /made-up/" + "x" * 347 + "/scripts/worker.py --reason end "
        whole = worker + key + " --project demo"
        sampler = hosts.Sampler()
        with mock.patch.object(hosts, "command_lines", return_value=["python other.py", whole]):
            self.assertTrue(sampler.read())
        # The readings keep a worker's line whole: cut first, it would keep a part of the key that no mask finds.
        self.assertEqual(sampler.workers, [whole])
        self.item("i_0000000000aa", "Decision DEC-ALPHA-ship.py")
        session = {"host": "claude", "label": "decision 1", "exit": 0, "started": START, "ended": START + 5,
                   "sampler": sampler, "bodies": []}
        checked = self.hosts_object(memory=mock.Mock(requests=[]), session=mock.Mock(return_value=session),
                                    timings=mock.Mock(return_value={}), report={"sessions": []},
                                    keys={ANTHROPIC: key})
        with mock.patch.object(hosts, "configure"), mock.patch.object(sampler, "stop") as stop:
            result = checked.decide(0, {"claude": "/made-up/claude"})
        stop.assert_called_once_with(last=True)
        self.assertEqual((result["workers"], result["reasons"], result["decision"]),
                         ([worker + "<mark..."], ["end"], True))
        self.assertEqual(checked.report["sessions"], [result])
        self.assertNotIn("MARK", json.dumps(checked.report))
        # The whole line counts for TC-254.
        self.assertEqual(checked.lines, ["python other.py", whole])

    def test_a_session_is_named_by_the_output_file_that_it_writes(self):
        out = self.home / "out"
        (out / "codex").mkdir(parents=True)
        done = {"exit": 0, "seconds": 1.0, "stdout": "an answer with fixture-key", "stderr": ""}
        checked = self.hosts_object(out=out, demo=self.home, count=3, mock=mock.Mock(),
                                    environment=mock.Mock(return_value={"MOCK_KEY": "fixture-key"}))
        with mock.patch.object(hosts.hookcheck, "run", return_value=done) as run:
            result = checked.session("codex", "/made-up/codex", "a prompt", label="decision 2", sample=False)
        self.assertEqual(run.call_args[0][0][:2], ["/made-up/codex", "exec"])
        # The name in the report's lists is the label and the place of the file that the session wrote, which
        # the artifact of every check that runs sessions holds. The result keeps the bare label.
        self.assertEqual((checked.label, checked.count, result["label"]),
                         ("decision 2 (codex/output-3.txt)", 4, "decision 2"))
        self.assertEqual((out / "codex/output-3.txt").read_text(encoding="utf-8"),
                         "an answer with [mock-key]\n--- stderr ---\n")
        self.assertEqual((hosts.named("codex/output-1.txt", "decision 2"), hosts.named("claude/output-0.txt")),
                         ("decision 2 (codex/output-1.txt)", "claude/output-0.txt"))

    def test_the_scrub_session_counts_its_requests_between_two_moments_without_a_worker(self):
        earlier = {"kind": "curate", "headers": {"x-api-key": "MARKER-A"}}
        memory, sampler = mock.Mock(requests=[earlier]), mock.Mock(lines=["a line"])
        session = {"label": "scrub", "exit": 0, "started": START, "ended": START + 5, "sampler": sampler,
                   "bodies": ["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB is set. " + hosts.line("DEC-DELTA-tag")]}
        waited = []

        def run(*args, **options):
            waited.append(checked.rested.call_count)
            memory.requests.append({"kind": "embeddings", "headers": {"authorization": "Bearer MARKER-O"}})
            return session
        checked = self.hosts_object(memory=memory, session=mock.Mock(side_effect=run),
                                    rested=mock.Mock(side_effect=[True, False]),
                                    keys={ANTHROPIC: "MARKER-A", OPENAI: "MARKER-O"})
        with mock.patch.object(hosts, "configure"):
            result = checked.scrub("/made-up/claude")
        # One wait for the workers comes before the session, and one after it.
        self.assertEqual((waited, checked.rested.call_count), ([1], 2))
        self.assertEqual(checked.session.call_args[1]["extra"], {"CLAUDE_CODE_SUBPROCESS_ENV_SCRUB": "1"})
        # The request of an earlier session is not this session's, and each key is looked for by itself.
        self.assertEqual((result["memory_requests"], result["keys_reached_hooks"]),
                         (["embeddings"], {ANTHROPIC: False, OPENAI: True}))
        self.assertEqual((result["notice"], result["recalled"], result["workers_gone"]),
                         (True, True, {"before": True, "after": False}))
        self.assertEqual((checked.lines, checked.report["scrub"]), (["a line"], result))
        found = hosts.verdicts(dict(report(), scrub=result))
        self.assertEqual((found["TC-257"], found["TC-257 observed"]), (False, NOT_COUNTED))

    def test_a_project_is_busy_while_a_worker_holds_it_or_a_turn_waits(self):
        self.assertFalse(hosts.busy(self.root))
        (self.root / "unprocessed").mkdir()
        self.assertFalse(hosts.busy(self.root))
        (self.root / "unprocessed/turn").write_text("", encoding="utf-8")
        self.assertEqual((hosts.busy(self.root), hosts.busy(self.root, turns=False)), (True, False))
        # While curation is stopped the turns wait for nothing.
        (self.root / "curation.json").write_text(json.dumps({"stopped": {"at": "2026-11-12T00:00:00.000Z"}}),
                                                 encoding="utf-8")
        self.assertFalse(hosts.busy(self.root))
        (self.root / "curation.lock").write_text("", encoding="utf-8")
        self.assertEqual((hosts.busy(self.root), hosts.busy(self.root, turns=False)), (True, True))

    def test_quiet_waits_for_the_calm_and_gives_up_at_its_time(self):
        with mock.patch.object(hosts, "QUIET", 0.4):
            started = time.time()
            self.assertTrue(hosts.quiet(self.root, timeout=10))
            self.assertTrue(0.4 <= time.time() - started < 5)
            (self.root / "curation.lock").write_text("", encoding="utf-8")
            self.assertFalse(hosts.quiet(self.root, timeout=0.8))
            # A folder that cannot be listed just now is looked at again.
            (self.root / "curation.lock").unlink()
            with mock.patch.object(hosts, "busy", side_effect=[PermissionError(13, "being replaced")] + [False] * 50):
                self.assertTrue(hosts.quiet(self.root, timeout=10))
            # With `worker`, a memory worker whose command line holds that text keeps the wait going: one that
            # a hook has just launched does not hold the lease yet.
            start, end = ("python /made-up/scripts/worker.py --reason " + reason for reason in ("start", "end"))
            with mock.patch.object(hosts, "command_lines", side_effect=[[start], [start, end], [end]]) as read:
                self.assertTrue(hosts.quiet(self.root, timeout=10, worker="--reason start"))
            self.assertEqual(read.call_count, 3)
            with mock.patch.object(hosts, "command_lines", return_value=["python other.py", end]):
                self.assertFalse(hosts.quiet(self.root, timeout=0.7, worker=""))
                self.assertTrue(hosts.quiet(self.root, timeout=10, worker="--reason start"))
            # No reading is made without `worker`. A reading that fails counts as a worker, since it does not
            # show that none runs, so the wait never ends as calm on one.
            with mock.patch.object(hosts, "command_lines", side_effect=OSError("no ps")) as read:
                self.assertTrue(hosts.quiet(self.root, timeout=10))
                read.assert_not_called()
                self.assertTrue(hosts.running(""))
                self.assertFalse(hosts.quiet(self.root, timeout=0.7, worker=""))
            with mock.patch.object(hosts, "command_lines", return_value=["python other.py"]):
                self.assertFalse(hosts.running(""))

    def test_a_reading_says_what_it_showed_and_keeps_every_line_of_it_and_of_those_before_it(self):
        start, end = ("python /made-up/scripts/worker.py --reason " + reason for reason in ("start", "end"))
        reading = ["python other.py", start, end]
        seen = {"unread": "an earlier reading"}
        with mock.patch.object(hosts, "command_lines", return_value=reading):
            self.assertEqual((hosts.running("--reason end", seen), seen), (True, {"workers": [end], "lines": reading}))
            self.assertEqual((hosts.running("--reason skill", seen), seen),
                             (False, {"workers": [], "lines": reading * 2}))
            self.assertEqual((hosts.running("", seen), seen), (True, {"workers": [start, end], "lines": reading * 3}))
            # Only the workers of the run's folder count, and every line of the reading still does.
            self.assertEqual((hosts.running("", seen, "/elsewhere"), seen),
                             (False, {"workers": [], "lines": reading * 4}))
        with mock.patch.object(hosts, "command_lines", side_effect=OSError("no ps")):
            self.assertEqual((hosts.running("", seen), seen),
                             (True, {"unread": "OSError('no ps')", "lines": reading * 4}))

    def test_only_the_workers_under_the_run_s_folder_are_this_run_s(self):
        own = "python -I %s --reason end --project demo" % (self.home / "run/c2-hosts/shared/plugin/scripts/worker.py")
        # A worker of the user's own sessions, and one of an earlier run whose folder starts with the same name.
        other = "python -I /made-up/other-home/.claude/plugins/corthex/scripts/worker.py --reason end --project demo"
        sibling = "python -I %s --reason end --project demo" % (self.home / "run-old/c2-hosts/plugin/scripts/worker.py")
        lines = ["python other.py", own, other, sibling]
        folder = hosts.comparable(str(self.home / "run"))
        self.assertEqual(hosts.workers(lines), [own, other, sibling])
        self.assertEqual((hosts.workers(lines, folder), hosts.workers(lines, folder + "/")), ([own], [own]))
        # On Windows a command line may write the folder with either slash and in another case.
        line = ('"C:\\Program Files\\Python\\python.exe" -I '
                '"D:\\Made-Up\\Temp\\RUN\\c2-hosts\\plugin\\scripts\\worker.py" --reason end')
        with mock.patch.object(hosts.os.path, "normcase", ntpath.normcase):
            folder = hosts.comparable("D:/Made-Up/Temp/run")
            self.assertEqual((folder, hosts.workers([line, other], folder)), ("d:/made-up/temp/run", [line]))

    def test_a_worker_of_another_home_does_not_keep_the_wait_going(self):
        folder = hosts.comparable(str(self.home / "run"))
        own = "python %s --reason start" % (self.home / "run/plugin/scripts/worker.py")
        other = "python /made-up/other-home/plugin/scripts/worker.py --reason start"
        with mock.patch.object(hosts, "time", Clock()), mock.patch.object(hosts, "command_lines", return_value=[other]):
            self.assertTrue(hosts.quiet(self.root, timeout=9.9, worker="", run_folder=folder))
            # Without the run's folder it counts, as before.
            self.assertFalse(hosts.quiet(self.root, timeout=9.9, worker=""))
        with mock.patch.object(hosts, "time", Clock()), \
                mock.patch.object(hosts, "command_lines", return_value=[other, own]):
            self.assertFalse(hosts.quiet(self.root, timeout=9.9, worker="--reason start", run_folder=folder))

    def test_a_wait_says_what_it_saw_as_it_ended(self):
        start, end = ("python /made-up/scripts/worker.py --reason " + reason for reason in ("start", "end"))
        lock = self.root / "curation.lock"

        def wait(lines=None, clock=None, **options):
            # The looks come every 0.2 seconds of a clock that only their own pauses move, until 9.9 seconds.
            seen = {}
            with mock.patch.object(hosts, "time", clock or Clock()), \
                    mock.patch.object(hosts, "command_lines", side_effect=lines) as read:
                calm = hosts.quiet(self.root, timeout=9.9, turns=False, seen=seen, **options)
            return calm, read.call_count, seen
        # A wait that ends as calm gives its last look and that look's reading, and no time without a lease.
        # Every line of its readings counts.
        self.assertEqual(wait([[start], ["python other.py"]], worker="--reason start"),
                         (True, 2, {"busy": False, "workers": [], "lines": [start, "python other.py"]}))
        # A lease that is held to the end lets no look read the command lines: they are read as the wait ends,
        # and the lease is looked at once more after that reading, so no time without a lease has passed.
        lock.write_text("", encoding="utf-8")
        self.assertEqual(wait([["python other.py", end]], worker=""),
                         (False, 1, {"busy": True, "calm": 0.0, "workers": [end], "lines": ["python other.py", end]}))
        # Without `worker` no reading is made, and without `seen` none is made for it.
        self.assertEqual(wait([]), (False, 0, {"busy": True, "calm": 0.2}))
        with mock.patch.object(hosts, "time", Clock()), mock.patch.object(hosts, "command_lines") as read:
            self.assertFalse(hosts.quiet(self.root, timeout=9.9, turns=False, worker=""))
        read.assert_not_called()

        # A lease that goes while the reading at the end is made: the look after it shows none, and the seconds
        # without one count from the last look that met it.
        def gone():
            lock.unlink()
            return ["python other.py"]
        self.assertEqual(wait(gone, worker=""),
                         (False, 1, {"busy": False, "calm": 0.2, "workers": [], "lines": ["python other.py"]}))
        # A worker that an early reading showed ends, and another then holds the lease to the end. The reading
        # that goes with the last look is the one made as the wait ended, not the early one, whose line still
        # counts.
        readings = [[start], [end]]

        def read():
            lock.write_text("", encoding="utf-8")
            return readings.pop(0)
        self.assertEqual(wait(read, worker=""),
                         (False, 2, {"busy": True, "calm": 0.0, "workers": [end], "lines": [start, end]}))
        lock.unlink()
        # A worker that keeps running without the lease to the end: the looks that meet no lease keep the last
        # reading, and no lease has been seen since the wait began. Once QUIET seconds have passed, every third
        # look, 0.6 seconds after the one before, reads the command lines, from 3.2 to 9.8 seconds; the end
        # reads nothing more.
        calm, count, seen = wait([[end]] * 99, worker="")
        self.assertEqual((calm, count, seen), (False, 12, {"busy": False, "calm": 10.0, "workers": [end],
                                                           "lines": [end] * 12}))
        # A look that cannot tell whether the lease is there says so, and counts as busy.
        with mock.patch.object(hosts, "busy", side_effect=PermissionError(13, "being replaced")):
            self.assertEqual(wait([["python other.py"]], worker=""),
                             (False, 1, {"busy": "unread: PermissionError", "calm": 0.0, "workers": [],
                                         "lines": ["python other.py"]}))
        # A lease that goes shortly before the end leaves no lease and no worker as the wait runs out: the
        # seconds without a lease, fewer than QUIET, say why the wait was not over.
        clock = Clock()
        with mock.patch.object(hosts, "busy", side_effect=lambda root, turns: clock.now < 7.9):
            self.assertEqual(wait([["python other.py"]], clock, worker=""),
                             (False, 1, {"busy": False, "calm": 2.2, "workers": [], "lines": ["python other.py"]}))
        self.assertLess(2.2, hosts.QUIET)

    def test_a_wait_for_the_start_s_worker_that_gives_up_is_reported(self):
        checked = self.hosts_object(label=hosts.named("codex/output-1.txt", "decision 2"), memory=mock.Mock())
        (self.root / "curation.lock").write_text("", encoding="utf-8")
        with mock.patch.object(hosts, "START_WORKER_SECONDS", 0.3), \
                mock.patch.object(hosts.hookcheck.Mock, "stream", return_value=b"") as stream:
            # A session's second model request waits again, and the session is named once.
            for _ in range(2):
                checked.after_start_worker("/v1/messages?beta=true", "a model")
            # A request that is not the model's does not wait.
            checked.after_start_worker("/v1/models", "a model")
        self.assertEqual(checked.report, {"start_worker_waits_given_up": ["decision 2 (codex/output-1.txt)"]})
        self.assertEqual(checked.memory.hold.call_count, 2)
        self.assertEqual(stream.call_args_list, [mock.call("/v1/messages?beta=true", "a model")] * 2 +
                         [mock.call("/v1/models", "a model")])
        self.assertEqual(hosts.waits_line(["decision 2", "결정 하나"]),
                         "sessions whose model answered after 60 s of waiting for the start's worker: "
                         '["decision 2", "결정 하나"]')
        # A wait that ends because the lease and the worker are gone reports nothing. A start's worker of
        # another home, such as one of the user's own sessions, is not waited for.
        (self.root / "curation.lock").unlink()
        checked.report, checked.run_folder = {}, hosts.comparable(str(self.home / "run"))
        lines = ["python other.py --reason start", "python /made-up/other-home/plugin/scripts/worker.py --reason start"]
        with mock.patch.object(hosts, "QUIET", 0.2), mock.patch.object(hosts, "command_lines", return_value=lines), \
                mock.patch.object(hosts.hookcheck.Mock, "stream", return_value=b""):
            checked.after_start_worker("/v1/responses", "a model")
        self.assertEqual(checked.report, {})

    def test_settled_does_not_wait_when_no_answer_was_held(self):
        started = time.time()
        found = hosts.settled(self.home, [], timeout=30)
        self.assertEqual((found["applied"], found["missing"]), (False, []))
        self.assertLess(time.time() - started, 5)

    def test_settled_needs_the_titles_no_lease_and_no_waiting_turn(self):
        self.item("i_0000000000aa", "Decision A")
        # A project whose folder of waiting turns was never made has none.
        self.assertTrue(hosts.settled(self.home, ["Decision A"], timeout=5)["applied"])
        self.assertEqual(hosts.settled(self.home, ["Decision A", "Decision B"], timeout=0.5)["missing"], ["Decision B"])
        (self.root / "unprocessed").mkdir()
        self.assertTrue(hosts.settled(self.home, ["Decision A"], timeout=5)["applied"])
        (self.root / "unprocessed/turn").write_text("", encoding="utf-8")
        self.assertFalse(hosts.settled(self.home, ["Decision A"], timeout=0.5)["applied"])
        (self.root / "unprocessed/turn").unlink()
        (self.root / "curation.lock").write_text("", encoding="utf-8")
        self.assertFalse(hosts.settled(self.home, ["Decision A"], timeout=0.5)["applied"])

    def test_settled_looks_again_past_an_item_file_that_is_being_replaced(self):
        self.item("i_0000000000aa", "Decision A")
        read, calls = Path.read_text, []

        def replacing(path, *args, **options):
            calls.append(path.name)
            if len(calls) == 1:
                raise PermissionError(13, "being replaced")
            return read(path, *args, **options)
        with mock.patch.object(Path, "read_text", replacing):
            found = hosts.settled(self.home, ["Decision A"], timeout=5)
        self.assertTrue(found["applied"])
        self.assertEqual(calls, ["i_0000000000aa.json"] * 2)

    def test_marked_files_reads_again_and_names_what_it_could_not_read(self):
        keys = {"KEY": "MARKER123"}
        (self.store / "logs").mkdir()
        (self.store / "logs/usage.jsonl").write_text("x MARKER123 y", encoding="utf-8")
        (self.store / "store.json").write_text("{}", encoding="utf-8")
        marked = ".corthex/corthex-memory/logs/usage.jsonl"
        self.assertEqual(hosts.marked_files(self.home, keys), ({"KEY": [marked]}, []))
        read, refused, limit = Path.read_bytes, [], [2]

        def locked(path):
            if path.name == "store.json" and len(refused) < limit[0]:
                refused.append(path.name)
                raise PermissionError(13, "locked")
            return read(path)
        with mock.patch.object(Path, "read_bytes", locked), mock.patch.object(hosts.time, "sleep"):
            # A file that a worker was replacing is read on a later pass.
            self.assertEqual(hosts.marked_files(self.home, keys), ({"KEY": [marked]}, []))
            # One that stays unread is named, after five passes.
            del refused[:]
            limit[0] = 99
            found, unread = hosts.marked_files(self.home, keys)
        self.assertEqual((found, unread, len(refused)),
                         ({"KEY": [marked]}, [".corthex/corthex-memory/store.json"], 5))

    def test_stage_takes_the_release_s_hooks_file_before_and_after_the_release_renames_it(self):
        for waiting in (True, False):
            with self.subTest(waiting=waiting):
                repository = Path(tempfile.mkdtemp(prefix="c2-stage-"))
                self.addCleanup(shutil.rmtree, str(repository), True)
                memory = repository / "plugins/corthex-memory"
                for folder in (repository / ".claude-plugin", repository / ".agents/plugins",
                               memory / ".claude-plugin", memory / ".codex-plugin", memory / "hooks"):
                    folder.mkdir(parents=True)
                for name in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
                    (memory / name).write_text(json.dumps({"name": "corthex-memory", "version": "0.2.1"}),
                                               encoding="utf-8")
                # Before the release its hooks file waits beside the current one; the release renames it.
                (memory / "hooks/hooks.json").write_text('"current"' if waiting else '"release"', encoding="utf-8")
                if waiting:
                    (memory / "hooks/hooks-0.3.0.json").write_text('"release"', encoding="utf-8")
                target, plugin = hosts.stage(repository, repository / "out")
                self.assertEqual(plugin, target / "plugins/corthex-memory")
                self.assertEqual(sorted(path.name for path in (plugin / "hooks").iterdir()), ["hooks.json"])
                self.assertEqual((plugin / "hooks/hooks.json").read_text(encoding="utf-8"), '"release"')
                for name in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
                    self.assertEqual(json.loads((plugin / name).read_text(encoding="utf-8"))["version"], hosts.RELEASE)


class C2SamplerTest(unittest.TestCase):
    def test_a_reading_keeps_every_line_and_only_this_run_s_workers(self):
        own = "python /made-up/run/c2-hosts/plugin/scripts/worker.py --reason end"
        other = "python /made-up/run-old/c2-hosts/plugin/scripts/worker.py --reason end"
        sampler = hosts.Sampler(hosts.comparable("/made-up/run"))
        with mock.patch.object(hosts, "command_lines", return_value=["python other.py", other, own]):
            self.assertTrue(sampler.read())
        self.assertEqual((sampler.lines, sampler.workers, sampler.reads), (["python other.py", other, own], [own], 1))

    def test_the_last_reading_follows_the_readings_in_the_caller_s_thread(self):
        caller, seen = threading.current_thread(), []
        worker = "python /made-up/scripts/worker.py --reason end"

        def lines():
            # The worker shows only once the readings' own thread has ended.
            seen.append(threading.current_thread() is caller)
            return [worker] if seen[-1] else ["python other.py"]
        with mock.patch.object(hosts, "command_lines", lines), mock.patch.object(hosts, "SAMPLE_SECONDS", 0.01):
            sampler = hosts.Sampler()
            sampler.start()
            while not seen:
                time.sleep(0.01)
            sampler.stop(last=True)
            self.assertFalse(sampler.is_alive())
            self.assertEqual((seen[-1], any(seen[:-1]), sampler.reads), (True, False, len(seen)))
            self.assertEqual(sampler.workers, [worker])
            # Without `last` the readings end where they are.
            del seen[:]
            sampler = hosts.Sampler()
            sampler.start()
            while not seen:
                time.sleep(0.01)
            sampler.stop()
            self.assertEqual((any(seen), sampler.workers), (False, []))

    def test_a_reading_that_fails_is_noted_and_counts_as_none(self):
        with mock.patch.object(hosts, "command_lines", side_effect=OSError("no ps")):
            sampler = hosts.Sampler()
            self.assertFalse(sampler.read())
        self.assertEqual((sampler.reads, sampler.lines, len(sampler.errors)), (0, [], 1))
        with mock.patch.object(hosts, "command_lines", return_value=["python other.py"]):
            self.assertTrue(sampler.read())
        self.assertEqual((sampler.reads, sampler.lines, len(sampler.errors)), (1, ["python other.py"], 1))

    def test_the_last_reading_is_tried_again_until_one_works(self):
        caller = threading.current_thread()
        worker = "python /made-up/scripts/worker.py --reason end"
        for failed, expected in ((hosts.LAST_READINGS - 1, [worker]), (hosts.LAST_READINGS, [])):
            with self.subTest(failed=failed):
                began, results = threading.Event(), [OSError("no ps")] * failed + [[worker]]

                def lines(began=began, results=results):
                    if threading.current_thread() is not caller:
                        began.set()
                        return ["python other.py"]
                    found = results.pop(0)
                    if isinstance(found, Exception):
                        raise found
                    return found
                # The readings' own thread reads once and then waits for its end.
                with mock.patch.object(hosts, "command_lines", lines), \
                        mock.patch.object(hosts, "SAMPLE_SECONDS", 60), \
                        mock.patch.object(hosts.time, "sleep") as sleep:
                    sampler = hosts.Sampler()
                    sampler.start()
                    self.assertTrue(began.wait(10))
                    sampler.stop(last=True)
                self.assertFalse(sampler.is_alive())
                # A pause comes between two tries, and none after the last.
                self.assertEqual(sleep.call_args_list,
                                 [mock.call(hosts.LAST_READING_PAUSE)] * min(failed, hosts.LAST_READINGS - 1))
                self.assertEqual((sampler.workers, len(sampler.errors), sampler.reads),
                                 (expected, failed, 1 + len(expected)))


class C2WalkReplayTest(unittest.TestCase):
    def test_only_the_four_hooks_of_a_turn_go_through_the_measuring_script(self):
        # measure_hook.py exits 2 for any other hook, which would stop a compaction in Claude Code.
        folder = Path(tempfile.mkdtemp(prefix="c2-walk-"))
        self.addCleanup(shutil.rmtree, str(folder), True)
        source = ROOT / "plugins/corthex-memory/hooks"
        original = source / ("hooks-0.3.0.json" if (source / "hooks-0.3.0.json").exists() else "hooks.json")
        path = folder / "hooks.json"
        shutil.copyfile(str(original), str(path))
        before = json.loads(path.read_text(encoding="utf-8"))["hooks"]
        walk.measure_hooks(path)
        after = json.loads(path.read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(set(after), set(before))
        self.assertTrue(set(walk.MEASURED) < set(after))  # the release adds the compaction hooks
        taken = ("start", "prompt", "end-of-turn", "end")
        for name, groups in after.items():
            commands = [hook[key] for group in groups for hook in group["hooks"]
                        for key in ("command", "commandWindows")]
            if name not in walk.MEASURED:
                self.assertEqual(groups, before[name])
                continue
            for command in commands:
                self.assertNotIn("/scripts/hook.py", command)
                self.assertTrue(any(('/scripts/measure_hook.py" ' + hook) in command for hook in taken), command)


class Asked:
    """What `Walk.ranked` uses of a walk: sessions whose prompt recalls end as told, in turn, and the steps."""

    def __init__(self, *outcomes):
        self.outcomes, self.steps = outcomes, []
        self.asked = 0

    def session(self, host, prompt):
        self.asked += 1
        return {"session": "session-%d" % self.asked}

    def injections(self, sessions):
        number = int(sessions[0].rsplit("-", 1)[1])
        return [{"session": sessions[0], "where": "start", "outcome": "shown"},
                {"session": sessions[0], "where": "prompt", "outcome": self.outcomes[number - 1]}]

    def step(self, case, label, value):
        self.steps.append((case, value))


class C2WalkRecallTest(unittest.TestCase):
    def ranked(self, *outcomes):
        asked = Asked(*outcomes)
        result, lines = walk.Walk.ranked(asked, "TC-263", "codex", "a prompt")
        return asked, result["session"], [line["outcome"] for line in lines]

    def test_a_ranked_recall_is_asked_once(self):
        for outcome in ("injected", "below", "no-index"):
            with self.subTest(outcome=outcome):
                asked, session, outcomes = self.ranked(outcome)
                self.assertEqual((asked.asked, session, outcomes, asked.steps), (1, "session-1", [outcome], []))

    def test_a_recall_that_gave_up_at_its_window_is_recorded_and_asked_once_more(self):
        asked, session, outcomes = self.ranked("late", "injected")
        self.assertEqual((asked.asked, session, outcomes), (2, "session-2", ["injected"]))
        self.assertEqual([(case, [line["outcome"] for line in lines]) for case, lines in asked.steps],
                         [("TC-263", ["late"])])

    def test_a_second_late_recall_is_returned_as_it_is(self):
        asked, session, outcomes = self.ranked("late", "late")
        self.assertEqual((asked.asked, session, outcomes, len(asked.steps)), (2, "session-2", ["late"], 1))


class C2RecallTimingTest(unittest.TestCase):
    def test_a_host_and_size_passes_only_with_known_outcomes_and_a_run_that_ranked(self):
        cases = (({"injected": 58, "late": 42}, True), ({"below": 100}, True), ({"injected": 100}, True),
                 # A recall that never completes is not a time: the step fails.
                 ({"late": 100}, False), ({"injected": 99, "no-line": 1}, False), ({}, False))
        for found, expected in cases:
            with self.subTest(found=found):
                self.assertEqual(timing.ranked(Counter(found)), expected)


class HostVersionsTest(unittest.TestCase):
    def test_every_job_installs_the_hosts_that_the_input_contract_names(self):
        # The hook checks' jobs each install the hosts; they must be the versions whose inputs are recorded.
        contract = json.loads((FOLDER / "host-inputs.json").read_text(encoding="utf-8"))["hosts"]
        expected = "npm install -g @anthropic-ai/claude-code@%s @openai/codex@%s" % (
            contract["claude"]["version"], contract["codex"]["version"])
        for name in ("memory-hook-check.yml", "windows-hook-check.yml"):
            workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
            lines = [line.strip() for line in workflow.splitlines() if "npm install" in line]
            self.assertGreaterEqual(len(lines), 2, name)
            for line in lines:
                self.assertTrue(line.endswith(expected), (name, line))


if __name__ == "__main__":
    unittest.main()
