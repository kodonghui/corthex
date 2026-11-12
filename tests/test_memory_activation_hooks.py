"""TC-429–433: the 0.3.0 activation's second step (TASK-117), the hooks behind the version condition.

Each hook runs as a process, as a host runs it, with the release that the code
reads set to 0.2.1 or 0.3.0 before `hook.py` starts, since the plugin on `main`
keeps its 0.2.x version until the release (TASK-051). The memory worker's start
is recorded instead of made, and recall is replaced where a case needs its
block; the stores are made up, and keys are made up during the run.
"""
import json
import os
import shutil
import subprocess
import sys
import unittest

from _common import ROOT
PLUGIN = ROOT / "plugins/corthex-memory"
SCRIPTS = PLUGIN / "skills/corthex-memory/scripts"
sys.path.insert(0, str(SCRIPTS))
from memory_lib import base, compaction_brief, compaction_check, format2, injection_log, raw_log, store
import test_memory_curation_worker as worker_fixture
import test_memory_start_summary as summary_fixture

HOOK = PLUGIN / "scripts/hook.py"
DEVICE, AT = worker_fixture.DEVICE, worker_fixture.AT
line, pin = summary_fixture.line, summary_fixture.pin
SESSION = "fixture-activation-117"
LOG = raw_log.log_name("claude-code", SESSION)
NAMES = {"start": "SessionStart", "prompt": "UserPromptSubmit", "end-of-turn": "Stop", "end": "SessionEnd",
         "pre-compact": "PreCompact", "post-compact": "PostCompact"}
# The hook's clock 5 seconds on: every whole-hook deadline has passed before the hook reads anything.
LATE = "from memory_lib import clock\n_now = clock.now\nclock.now = lambda: _now() + 5"
SUMMARY = "## Objective\nShip the hooks.\n## Established facts\nThe tests pass.\n## Remaining plan\nTag it.\n"


class HookActivationTest(unittest.TestCase):
    """Hooks on the curation worker's format-2 store, whose project `sample` is registered for a checkout."""

    Fixture = worker_fixture.CurationWorkerTest
    configure, layer, saved, one_turn = Fixture.configure, Fixture.layer, Fixture.saved, Fixture.one_turn
    items, write, mark = Fixture.items, Fixture.write, Fixture.mark
    Summary = summary_fixture.StartSummaryTest
    item, pins, notice = Summary.item, Summary.pins, Summary.notice

    def setUp(self):
        self.Fixture.setUp(self)
        self.said, _ = self.one_turn()
        home = self.folder.parent / "home"
        self.checkout = self.folder.parent / "checkout"
        (home / ".corthex").mkdir(parents=True)
        (self.checkout / ".corthex").mkdir(parents=True)
        (self.checkout / ".corthex/project.json").write_text('{"name":"sample"}', encoding="utf-8")
        (home / ".corthex/projects.json").write_text(json.dumps(
            {"projects": [{"name": "sample", "path": str(self.checkout)}]}), encoding="utf-8")
        self.launches = self.folder.parent / "launches.jsonl"
        self.environment = {key: value for key, value in os.environ.items()
                            if not key.startswith(("CLAUDE", "CODEX", "PYTHON"))}
        self.environment.update(HOME=str(home), USERPROFILE=str(home), PLUGIN_ROOT="", CLAUDECODE="1",
                                CLAUDE_CODE_REMOTE="", PYTHONDONTWRITEBYTECODE="1")

    # Running a hook

    def event(self, hook, **changes):
        value = {"hook_event_name": NAMES[hook], "session_id": SESSION, "cwd": str(self.checkout),
                 "source": "startup", "prompt": "What did we decide about the hooks?",
                 "last_assistant_message": "One script serves them.", "trigger": "manual",
                 "compact_summary": SUMMARY}
        value.update(changes)
        return value

    def run_hook(self, hook, event=None, release="0.3.0", patch="", codex=False):
        """The hook's standard output, after checking that it exited with 0 and printed no error."""
        shim = self.folder.parent / "hook-shim.py"
        shim.write_text("\n".join((
            "import json, runpy, sys",
            "sys.path.insert(0, %r)" % str(SCRIPTS),
            "from memory_lib import activation, worker_launch",
            "activation._release[:] = [%r]" % release,
            "def launch(memory, project, reason, *args, **options):",
            "    with open(%r, 'a', encoding='utf-8') as target:" % str(self.launches),
            "        target.write(json.dumps([project, reason, options.get('expected_device')]) + '\\n')",
            "    return True",
            "worker_launch.launch = launch",
            patch,
            "sys.argv = [%r, %r]" % (str(HOOK), hook),
            "try:",
            "    runpy.run_path(%r, run_name='__main__')" % str(HOOK),
            "except SystemExit as error:",
            "    assert error.code == 0",
        )), encoding="utf-8")
        environment = dict(self.environment)
        if codex:
            environment.update(CLAUDECODE="", PLUGIN_ROOT=str(PLUGIN))
        payload = json.dumps(self.event(hook) if event is None else event).encode("utf-8")
        done = subprocess.run([sys.executable, str(shim)], input=payload, env=environment, cwd=str(self.checkout),
                              capture_output=True, timeout=60)
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        return done.stdout

    def context(self, output, name):
        value = json.loads(output)
        self.assertEqual(set(value), {"hookSpecificOutput"})
        self.assertEqual(value["hookSpecificOutput"]["hookEventName"], name)
        return value["hookSpecificOutput"]["additionalContext"]

    # What the hooks wrote

    def logs(self, name):
        return [json.loads(row) for path in sorted((self.folder / "logs").glob(name + "-*.jsonl"))
                for row in path.read_bytes().splitlines()]

    def timings(self):
        return [(row["hook"], row["outcome"]) for row in self.logs("hooks")]

    def failures(self):
        return [(row["step"], row["error"], row.get("hook")) for row in self.logs("failures")]

    def entries(self):
        path = self.root / "raw" / (LOG + ".jsonl")
        return [json.loads(row) for row in path.read_bytes().splitlines()] if path.exists() else []

    def injections(self):
        path = self.root / "injections" / (LOG + ".jsonl")
        return [injection_log.parse_line(row) for row in path.read_bytes().splitlines()] if path.exists() else []

    def started(self):
        if not self.launches.exists():
            return []
        return [json.loads(row) for row in self.launches.read_text(encoding="utf-8").splitlines()]

    def check_file(self):
        return self.root / "compaction" / (LOG + ".json")

    def files(self):
        return {path.relative_to(self.folder).as_posix(): path.read_bytes()
                for path in self.folder.rglob("*") if path.is_file()}

    def link(self, link, target, directory=False):
        try:
            os.symlink(str(target), str(link), target_is_directory=directory)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are not available")

    # TC-429

    def test_tc429_below_0_3_0_and_on_stores_that_c2_does_not_read_the_hooks_stay_c1(self):
        unreadable = "Memory could not be read: the store format is not supported. The memory status says more."
        # Below 0.3.0 a format-2 store is a newer one: nothing is recorded, and the compaction hooks do not run.
        before = self.files()
        text = self.context(self.run_hook("start", release="0.2.1"), "SessionStart")
        self.assertTrue(text.endswith("## Memory\n\n" + unreadable), text)
        for hook in ("prompt", "end-of-turn", "end", "pre-compact", "post-compact"):
            self.assertEqual(self.run_hook(hook, release="0.2.1"), b"", hook)
        self.assertEqual(self.files(), before)
        # From 0.3.0 a store that a migration holds, a newer one and a damaged one are refused in the same way.
        header = format2.parse_store((self.folder / "store.json").read_bytes())
        cases = (("migrating", dict(header, migrating={"from": 1, "to": 2, "started": AT}), unreadable),
                 ("newer", dict(header, format=3), unreadable),
                 ("mixed", None, "Memory could not be read: the store record is damaged. The memory status says more."))
        for label, value, expected in cases:
            with self.subTest(store=label):
                if value is None:
                    (self.folder / "store.json.bak").write_bytes(base.json_bytes(
                        dict(header, format=1, release="0.2.1"), "TBL-001"))
                else:
                    (self.folder / "store.json").write_text(json.dumps(value), encoding="utf-8")
                before = self.files()
                text = self.context(self.run_hook("start"), "SessionStart")
                self.assertTrue(text.endswith("## Memory\n\n" + expected), text)
                for hook in ("prompt", "end-of-turn", "end", "pre-compact", "post-compact"):
                    self.assertEqual(self.run_hook(hook), b"", hook)
                self.assertEqual(self.files(), before)
                (self.folder / "store.json").write_bytes(format2.store_bytes(header))
                if (self.folder / "store.json.bak").exists():
                    (self.folder / "store.json.bak").unlink()
        # A format-1 store at 0.3.0 starts and records as at 0.2.1, and the compaction hooks neither print nor write.
        record = store.new_record("0.2.1")
        (self.folder / "store.json").write_bytes(base.json_bytes(record, "TBL-001"))
        (self.root / "curation.json").write_bytes(base.json_bytes(
            {"logs": {}, "applies": 0, "recent": [], "consolidation": {"failures": 0}}, "TBL-009"))
        self.assertEqual(self.run_hook("start"), self.run_hook("start", release="0.2.1"))
        self.assertEqual(self.run_hook("prompt"), b"")
        for hook in ("pre-compact", "post-compact"):
            self.assertEqual(self.run_hook(hook), b"")
        self.assertEqual([entry["kind"] for entry in self.entries()], ["start", "start", "prompt"])
        self.assertEqual(self.timings(), [("start", "ok"), ("start", "ok"), ("prompt", "ok")])
        self.assertEqual(self.injections(), [])
        self.assertFalse(self.check_file().exists())
        self.assertEqual(self.started(), [["sample", "start", record["device"]]] * 2)

    def test_tc429_a_late_hook_still_records_and_a_format_1_store_keeps_c1_links(self):
        # A hook that reaches its gates after its whole deadline records on format 2, and only the C2 steps are cut.
        for hook, outcome in (("prompt", "ok"), ("end-of-turn", "deadline"), ("end", "deadline")):
            before = len(self.entries())
            self.assertEqual(self.run_hook(hook, patch=LATE), b"", hook)
            self.assertEqual((len(self.entries()) - before, self.timings()[-1]), (1, (hook, outcome)), hook)
        self.assertEqual(self.failures(), [("trigger", "deadline", "end-of-turn"), ("trigger", "deadline", "end")])
        # Recording also attempts the raw lock once its 50 ms window has passed.
        window = "from memory_lib import raw_log\nraw_log.RECORD_SECONDS = 0.0"
        self.assertEqual(self.run_hook("end", patch=window), b"")
        self.assertEqual((self.entries()[-1]["kind"], self.timings()[-1]), ("end", ("end", "ok")))
        # A format-1 store records a late hook at 0.3.0 as at 0.2.1, also through a link to its store record.
        record = store.new_record("0.2.1")
        real = self.folder.parent / "store-record.json"
        real.write_bytes(base.json_bytes(record, "TBL-001"))
        (self.folder / "store.json").unlink()
        self.link(self.folder / "store.json", real)
        (self.root / "curation.json").write_bytes(base.json_bytes(
            {"logs": {}, "applies": 0, "recent": [], "consolidation": {"failures": 0}}, "TBL-009"))
        found = {}
        for release in ("0.2.1", "0.3.0"):
            before, timed = len(self.entries()), len(self.timings())
            for hook in ("prompt", "end-of-turn", "end"):
                self.assertEqual(self.run_hook(hook, release=release, patch=LATE), b"")
            text = self.context(self.run_hook("start", release=release), "SessionStart")
            found[release] = (len(self.entries()) - before, self.timings()[timed:], text)
        self.assertEqual(found["0.3.0"], found["0.2.1"])
        self.assertEqual(found["0.3.0"][:2], (4, [("prompt", "ok"), ("end-of-turn", "ok"), ("end", "ok"),
                                                  ("start", "ok")]))

    def test_tc429_on_a_format_2_store_recording_refuses_a_link_inside_the_store(self):
        outside = self.folder.parent / "outside-raw"
        shutil.move(str(self.root / "raw"), str(outside))
        self.link(self.root / "raw", outside, directory=True)
        before = {path.name: path.read_bytes() for path in outside.iterdir()}
        for hook in ("prompt", "end"):
            self.assertEqual(self.run_hook(hook), b"")
        self.assertEqual({path.name: path.read_bytes() for path in outside.iterdir()}, before)
        self.assertEqual(self.timings(), [("prompt", "error"), ("end", "error")])
        self.assertEqual([failure[:2] for failure in self.failures()], [("record", "lost-lock")] * 2)

    # TC-430

    def test_tc430_the_start_hook_shows_the_start_summary_and_deletes_the_notices_it_showed(self):
        rule, goal = self.item("Keep one script"), self.item("Ship it", kind="fact")
        self.layer([rule, goal], [line("goal", 1, "Ship the start summary.", [goal["id"]]),
                                  line("next", 1, "Write the hook tests.", [rule["id"]])])
        self.pins(pin(rule, AT))
        shown = self.notice("rebuilt.json", kind="rebuilt")
        text = self.context(self.run_hook("start"), "SessionStart")
        memory = text[text.index("## Memory"):]
        self.assertIn("- The curation record was made again from the raw log", memory)
        self.assertIn("Pinned:\n- %s | decision |" % rule["id"], memory)
        # The pinned line ends with where to read its source again (TASK-112, SPEC-148).
        pinned = memory.split("Pinned:\n", 1)[1].split("\n", 1)[0]
        self.assertRegex(pinned, r" \| reread: e_[0-9a-z]{12}$")
        self.assertIn("Current state:\n- Goal: Ship the start summary. (%s)\n- Next action: Write the hook tests."
                      % goal["id"], memory)
        self.assertFalse(shown.exists())
        self.assertEqual([(row["where"], row["items"]) for row in self.injections()], [("start", [rule["id"]])])
        self.assertEqual([entry["kind"] for entry in self.entries()], ["start"])
        self.assertEqual(self.timings(), [("start", "ok")])
        self.assertEqual(self.started(), [["sample", "start", DEVICE]])
        # With its folder's boundaries left out, the summary still shows and nothing is recorded.
        self.configure(projects={"sample": {"enabled": True, "since": AT, "left_out": {"kinds": ["boundary"]}}})
        self.assertIn("Pinned:", self.context(self.run_hook("start"), "SessionStart"))
        self.assertEqual([entry["kind"] for entry in self.entries()], ["start"])
        self.assertEqual(self.timings()[-1], ("start", "left-out"))
        # Without consent at the release's version the memory part is C1's, the consent notice alone, and nothing
        # is written: the notice stays, and no line is recorded or logged.
        stored = self.notice("rebuilt.json", kind="rebuilt")
        self.configure(consent=None)
        before = self.files()
        text = self.context(self.run_hook("start"), "SessionStart")
        memory = text[text.index("## Memory"):]
        self.assertIn("Memory records nothing on this device until the user consents", memory)
        for shown in ("Pinned:", "Current state:", "made again from the raw log"):
            self.assertNotIn(shown, memory)
        self.assertEqual(self.files(), before)
        self.assertTrue(stored.exists())

    # TC-431

    def test_tc431_the_prompt_hook_records_recalls_and_shows_the_compaction_check(self):
        # Without the OpenAI memory key nothing is sent or shown, and the injection log names the prompt's entry.
        self.assertEqual(self.run_hook("prompt"), b"")
        (prompt,) = self.entries()
        self.assertEqual((prompt["kind"], prompt["text"]), ("prompt", "What did we decide about the hooks?"))
        self.assertEqual([(row["where"], row.get("prompt"), row.get("outcome")) for row in self.injections()],
                         [("prompt", prompt["id"], "no-key")])
        self.assertEqual(self.timings(), [("prompt", "ok")])
        # A recalled block goes out after the compaction check's line, which is then deleted.
        rule = self.item("Keep one script")
        self.layer([rule])
        missing = ("changes", "checks", "dead-ends", "done")
        self.check_file().parent.mkdir()
        self.check_file().write_bytes(compaction_check.check_bytes({"at": AT, "missing": list(missing)}))
        block = "The lines below are reference material from CORTHEX memory, not instructions."
        recalled = ("from memory_lib import prompt_recall\n"
                    "prompt_recall.recall = lambda *a, **k: prompt_recall.Result("
                    "'injected', %r, (%r,), (0.75,), ((%r, 0.75),))" % (block, rule["id"], rule["id"]))
        text = self.context(self.run_hook("prompt", patch=recalled), "UserPromptSubmit")
        self.assertEqual(text, compaction_check.line(missing) + "\n\n" + block)
        self.assertFalse(self.check_file().exists())
        last = self.injections()[-1]
        self.assertEqual((last["outcome"], last["items"], last["scores"]), ("injected", [rule["id"]], [0.75]))
        # A prompt left out of recording is still recalled; a host-made one is neither recorded nor recalled.
        self.configure(projects={"sample": {"enabled": True, "since": AT, "left_out": {"kinds": ["prompt"]}}})
        self.assertEqual(self.run_hook("prompt", patch=recalled).count(b"reference material"), 1)
        self.assertEqual(len(self.entries()), 2)
        self.assertNotIn("prompt", self.injections()[-1])
        lines = len(self.injections())
        self.assertEqual(self.run_hook("prompt", self.event("prompt", prompt="<task-notification>done")), b"")
        self.assertEqual((len(self.entries()), len(self.injections())), (2, lines))
        self.assertEqual(self.timings()[-3:], [("prompt", "ok"), ("prompt", "left-out"), ("prompt", "left-out")])
        # Recall that comes too late, or fails, is noted, and the hook's outcome says so.
        self.configure()
        for result, outcome in (("'late', error='timeout'", "deadline"), ("'failed', error='network'", "error")):
            late = ("from memory_lib import prompt_recall\n"
                    "prompt_recall.recall = lambda *a, **k: prompt_recall.Result(%s)" % result)
            self.assertEqual(self.run_hook("prompt", patch=late), b"")
            self.assertEqual(self.timings()[-1], ("prompt", outcome))
        self.assertEqual(self.failures(), [("recall", "timeout", "prompt"), ("recall", "network", "prompt")])
        # A check not read before the deadline stays for the next prompt, and its step's line says so.
        self.check_file().write_bytes(compaction_check.check_bytes({"at": AT, "missing": ["done"]}))
        slow = ("import time\nfrom memory_lib import prompt_recall\n"
                "def recall(*a, **k):\n    time.sleep(1)\n    return prompt_recall.Result('late', error='deadline')\n"
                "prompt_recall.recall = recall")
        self.assertEqual(self.run_hook("prompt", patch=slow), b"")
        self.assertTrue(self.check_file().exists())
        self.assertEqual(self.timings()[-1], ("prompt", "deadline"))
        self.assertEqual(self.failures()[-2:], [("recall", "deadline", "prompt"), ("compaction", "deadline", "prompt")])
        # With no check to read, a late prompt names only recall's code.
        self.check_file().unlink()
        self.assertEqual(self.run_hook("prompt", patch=slow), b"")
        self.assertEqual(self.failures()[-2:], [("compaction", "deadline", "prompt"), ("recall", "deadline", "prompt")])
        # While another process holds the session's raw lock the check stays, and the outcome is lock-busy.
        self.check_file().write_bytes(compaction_check.check_bytes({"at": AT, "missing": ["done"]}))
        held = ("from memory_lib import compaction_check, locks\n"
                "def pending(*a, **k):\n    raise locks.LockBusy()\n"
                "compaction_check.pending = pending")
        self.assertEqual(self.run_hook("prompt", patch=held), b"")
        self.assertTrue(self.check_file().exists())
        self.assertEqual(self.timings()[-1], ("prompt", "lock-busy"))
        # A deadline that passes once the check was read, before the print, still deletes the printed check.
        past = ("from memory_lib import clock, compaction_check\nline = compaction_check.line\n"
                "def late(parts):\n    _now = clock.now\n    clock.now = lambda: _now() + 1\n    return line(parts)\n"
                "compaction_check.line = late")
        text = self.context(self.run_hook("prompt", patch=past), "UserPromptSubmit")
        self.assertEqual(text, compaction_check.line(("done",)))
        self.assertFalse(self.check_file().exists())

    # TC-432

    def test_tc432_the_turn_and_session_end_hooks_start_the_worker_when_a_trigger_is_met(self):
        # One unprocessed turn meets no end-of-turn trigger, but the session end's.
        self.assertEqual(self.run_hook("end-of-turn"), b"")
        self.assertEqual(self.started(), [])
        self.assertEqual(self.run_hook("end"), b"")
        self.assertEqual(self.started(), [["sample", "end", DEVICE]])
        # Ten unprocessed turns meet the end-of-turn trigger.
        for number in range(10):
            said, _ = self.raw.turn("Turn %d" % number, "Answer %d" % number)
            self.write()
            self.mark(said)
        self.assertEqual(self.run_hook("end-of-turn"), b"")
        self.assertEqual(self.started()[-1], ["sample", "end-of-turn", DEVICE])
        # A trigger check that the deadline cut short names its step.
        late = "from memory_lib import curation_triggers\ncuration_triggers.start = lambda *a, **k: 'deadline'"
        self.assertEqual(self.run_hook("end-of-turn", patch=late), b"")
        self.assertEqual(self.timings()[-1], ("end-of-turn", "deadline"))
        self.assertEqual(self.failures(), [("trigger", "deadline", "end-of-turn")])
        # Without the Anthropic memory key nothing starts, and the answer is still recorded.
        self.environment["CORTHEX_MEMORY_ANTHROPIC_API_KEY"] = ""
        self.assertEqual(self.run_hook("end-of-turn"), b"")
        self.assertEqual(len(self.started()), 2)
        kinds = [entry["kind"] for entry in self.entries()]
        self.assertEqual(kinds, ["answer", "end", "answer", "answer", "answer"])
        self.assertEqual(self.timings(), [("end-of-turn", "ok"), ("end", "ok"), ("end-of-turn", "ok"),
                                          ("end-of-turn", "deadline"), ("end-of-turn", "ok")])

    # TC-433

    def test_tc433_the_compaction_hooks_brief_and_check_in_claude_code_only(self):
        goal = self.item("Ship it", kind="fact")
        self.layer([goal], [line("goal", 1, "Ship the hooks.", [goal["id"]]),
                            line("next", 1, "Done when: the check passes.", [goal["id"]])])
        brief = self.run_hook("pre-compact")
        self.assertEqual(brief.decode("utf-8"), compaction_brief.text(
            [dict(line("goal", 1, "Ship the hooks.", []), part="goal"),
             dict(line("next", 1, "Done when: the check passes.", []), part="next")]))
        self.assertFalse(brief.startswith(b"{"))
        self.assertEqual(self.run_hook("post-compact"), b"")
        missing = compaction_check.parse_check(self.check_file().read_bytes())["missing"]
        self.assertEqual(missing, ["changes", "checks", "dead-ends", "done"])
        self.assertNotIn(b"Ship the hooks", self.check_file().read_bytes())
        self.assertEqual(self.timings(), [("pre-compact", "ok"), ("post-compact", "ok")])
        # A summary with every part deletes the check; the next prompt then shows no line.
        whole = SUMMARY + "## Changes\nhooks.py\n## Checks\npass\n## Dead ends\nnone\nDone when: tagged.\n"
        self.assertEqual(self.run_hook("post-compact", self.event("post-compact", compact_summary=whole)), b"")
        self.assertFalse(self.check_file().exists())
        # In Codex both end before reading the store: nothing is printed or written, not even a timing line,
        # also for Codex's PostCompact input, which has no compact_summary.
        before = self.files()
        summaryless = self.event("post-compact", turn_id="turn-1")
        del summaryless["compact_summary"]
        for hook, event in (("pre-compact", None), ("post-compact", None), ("post-compact", summaryless)):
            self.assertEqual(self.run_hook(hook, event, codex=True), b"")
        self.assertEqual(self.files(), before)
        # A check hook without a summary is bad input, and writes no check.
        event = self.event("post-compact")
        del event["compact_summary"]
        self.assertEqual(self.run_hook("post-compact", event), b"")
        self.assertFalse(self.check_file().exists())
        self.assertEqual(self.failures()[-1], ("record", "bad-input", "post-compact"))


if __name__ == "__main__":
    unittest.main()
