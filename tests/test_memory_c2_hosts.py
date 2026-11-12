"""TASK-099 and TASK-101: the verdicts and helpers of the installed-host C2 checks, on made-up reports and files.

No host runs here.
"""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
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


hosts, walk = load("c2_hosts"), load("c2_walk_replay")

START = 1794000000.0
HOOKS = ("start", "prompt", "end-of-turn", "end")
KEYS = {"files_with_marker": [], "command_lines_with_marker": 0, "requests_with_key": 4}


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
            "keys": {"CORTHEX_MEMORY_ANTHROPIC_API_KEY": dict(KEYS), "CORTHEX_MEMORY_OPENAI_API_KEY": dict(KEYS)},
            "recalls": {"claude": {"injected": 1}, "codex": {"injected": 2}} if recalls is None else recalls,
            "scrub": {"exit": 0, "keys_reached_hooks": False, "notice": True, "memory_requests": []}}


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

    def test_tc257_needs_the_keys_at_the_hooks_or_the_notice_that_they_were_kept(self):
        for reached, notice, expected in ((True, False, True), (False, True, True), (False, False, False)):
            with self.subTest(reached=reached, notice=notice):
                value = report()
                value["scrub"].update(keys_reached_hooks=reached, notice=notice,
                                      memory_requests=["embeddings"] if reached else [])
                self.assertEqual(hosts.verdicts(value)["TC-257"], expected)


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
