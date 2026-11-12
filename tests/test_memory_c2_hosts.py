"""TASK-099: the verdicts of the installed-host C2 check, on made-up reports. No host runs here."""
from datetime import datetime, timezone
import importlib.util
import sys
import unittest

from _common import ROOT

FOLDER = ROOT / ".github/hook-check"
sys.path.insert(0, str(FOLDER))
spec = importlib.util.spec_from_file_location("c2_hosts_verdicts", FOLDER / "c2_hosts.py")
hosts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hosts)

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
        # the outcome `deadline` and noted one line (API-010).
        sessions = [session(0, {"prompt": "deadline"})] + [session(number) for number in (1, 2, 3)]
        line = failure(0, "claude-code", "prompt", "recall", "deadline")
        found = self.verdicts(sessions, [line])
        self.assertTrue(found["TC-253"])
        self.assertEqual((found["late recalls"], found["blocking_failures"]), (1, []))
        self.assertTrue(found["sessions"]["decision 1"]["four hooks ok or late in recall"])
        self.assertFalse(found["hooks_ok"])  # the report still says that not every outcome was `ok`

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


if __name__ == "__main__":
    unittest.main()
