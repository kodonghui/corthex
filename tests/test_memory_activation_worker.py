"""TC-434–437: the 0.3.0 activation's third step (TASK-117), the memory worker behind the version condition.

The worker runs in this process through `worker_runtime.run`, as `scripts/worker.py`
runs it, with the release that the code reads set to 0.2.1 or 0.3.0, since the plugin
on `main` keeps its 0.2.x version until the release (TASK-051). Every request goes to
the curation worker's local test server, with keys made up during the run; no provider
is called.
"""
import contextlib
from datetime import datetime, timedelta, timezone
import json
import os
import sys
import time
import unittest
from unittest import mock

from _common import ROOT
SCRIPTS = ROOT / "plugins/corthex-memory/skills/corthex-memory/scripts"
sys.path.insert(0, str(SCRIPTS))
from memory_lib import (activation, base, c2_store, commands, consolidation_worker, format2, history_retention,
                        index_worker, injection_log, item_types, locks, raw_log, retention, run_log, state_types,
                        store, worker_launch, worker_runtime, worker_support)
import test_memory_curation_worker as worker_fixture
from test_memory_curator_answers import answer, change, quote
from test_memory_run_log import logged
from test_memory_state_types import HISTORY

DEVICE, AT, HOOKS = worker_fixture.DEVICE, worker_fixture.AT, worker_fixture.HOOKS
UTC = timezone.utc


def ago(days):
    return base.utc_time(datetime.now(UTC) - timedelta(days=days))


class WorkerActivationTest(unittest.TestCase):
    """The worker on the curation worker's format-2 store, whose project `sample` is enabled."""

    Fixture = worker_fixture.CurationWorkerTest
    configure, layer, saved, one_turn = Fixture.configure, Fixture.layer, Fixture.saved, Fixture.one_turn
    items, write, mark, progress, markers = (Fixture.items, Fixture.write, Fixture.mark, Fixture.progress,
                                             Fixture.markers)

    def setUp(self):
        self.Fixture.setUp(self)
        # Consolidation is due 7 days after memory was turned on; turned on now, it is not.
        self.since = ago(0)
        self.configure(projects={"sample": {"enabled": True, "since": self.since}})

    def run_worker(self, reason="end-of-turn", release="0.3.0", expected=DEVICE):
        with mock.patch.object(activation, "_release", [release]):
            worker_runtime.run("sample", reason, expected, folder=self.folder)

    def files(self, index=True):
        return {path.relative_to(self.folder).as_posix(): path.read_bytes()
                for path in self.folder.rglob("*") if path.is_file() and path.suffix != ".lock"
                and (index or not path.name.startswith("index.db"))}

    def failures(self):
        return [(row["step"], row["error"]) for row in (
            json.loads(line) for path in sorted((self.folder / "logs").glob("failures-*.jsonl"))
            for line in path.read_bytes().splitlines())]

    # TC-434

    def test_tc434_below_0_3_0_and_on_stores_that_c2_does_not_read_the_worker_stays_c1(self):
        said, _ = self.one_turn()
        self.mark(said)
        self.server.answers = [answer(change(quote(said, HOOKS), kind="decision"))]
        # Below 0.3.0 the C1 gate refuses a format-2 store: nothing is sent or written.
        before = self.files()
        for reason in ("end-of-turn", "start"):
            self.run_worker(reason, release="0.2.1")
        self.assertEqual((self.server.requests, self.files()), ([], before))
        # From 0.3.0 a store that a migration holds, a newer one and a mixed pair end the worker the same way.
        header = format2.parse_store((self.folder / "store.json").read_bytes())
        for label, primary, backup in (
                ("migrating", dict(header, migrating={"from": 1, "to": 2, "started": AT}), None),
                ("newer", dict(header, format=3), None),
                ("mixed", None, dict(header, format=1, release="0.2.1")),
                ("damaged", b'{"format": 2, "device"', None)):
            with self.subTest(store=label):
                if isinstance(primary, bytes):
                    (self.folder / "store.json").write_bytes(primary)
                elif primary is not None:
                    (self.folder / "store.json").write_text(json.dumps(primary), encoding="utf-8")
                if backup is not None:
                    (self.folder / "store.json.bak").write_bytes(base.json_bytes(backup, "TBL-001"))
                before = self.files()
                for reason in ("end-of-turn", "start"):
                    self.run_worker(reason)
                self.assertEqual((self.server.requests, self.files()), ([], before))
                (self.folder / "store.json").write_bytes(format2.store_bytes(header))
                if backup is not None:
                    (self.folder / "store.json.bak").unlink()
        # A format-1 store at 0.3.0 gets C1's retention, as at 0.2.1, and no request.
        record = store.new_record("0.2.1")
        (self.folder / "store.json").write_bytes(base.json_bytes(record, "TBL-001"))
        log = raw_log.log_name("codex", "worker-activation-c1")
        entries = [{"id": "e_" + str(seq).zfill(12), "seq": seq, "turn": seq, "at": ago(days), "host": "codex",
                    "session": "worker-activation-c1", "kind": "prompt", "speaker": "user", "text": "turn %d" % seq}
                   for seq, days in ((1, 101), (2, 99))]
        (self.root / "raw" / (log + ".jsonl")).write_bytes(
            b"".join(base.json_bytes(entry, "TBL-007", compact=True) for entry in entries))
        (self.root / "curation.json").write_bytes(base.json_bytes(
            {"logs": {log: 2}, "applies": 0, "recent": [], "consolidation": {"failures": 0}}, "TBL-009"))
        self.run_worker("start", expected=record["device"])
        kept = [json.loads(line)["seq"] for line in (self.root / "raw" / (log + ".jsonl")).read_bytes().splitlines()]
        self.assertEqual((kept, self.server.requests), ([2], []))

    # TC-435

    def test_tc435_on_a_format_2_store_the_worker_curates_consolidates_and_keeps_the_index(self):
        said, _ = self.one_turn()
        self.mark(said)
        self.server.answers = [answer(change(quote(said, HOOKS), kind="decision"))]
        # Memory was turned on 8 days ago, so consolidation is due after curation.
        self.configure(projects={"sample": {"enabled": True, "since": ago(8)}})
        self.run_worker("end-of-turn")
        (headers, body), = self.server.requests
        self.assertEqual(headers["user-agent"], "corthex-memory/0.3.0")
        (item,) = self.items().values()
        self.assertEqual((item["kind"], item["status"]), ("decision", "current"))
        self.assertEqual(self.markers(), [])
        progress = self.progress()
        self.assertEqual(progress["logs"], {self.raw.name: said["seq"] + 1})
        # One decision item sends no merge and the state has no lines, so consolidation ends without a request.
        self.assertEqual([record["kind"] for record in progress["recent"]], ["consolidate", "curate"])  # newest first
        self.assertEqual((sorted(progress["consolidation"]), progress["consolidation"]["failures"]),
                         (["failures", "last"], 0))
        self.assertTrue((self.root / "index.db").exists())
        self.assertEqual(self.failures(), [])
        # Below 0.3.0 the user agent names that release.
        with mock.patch.object(activation, "_release", ["0.2.1"]):
            from memory_lib import model_request
            self.assertEqual(model_request.agent(), "corthex-memory/0.2.1")
        # Another process's fresh curation lease ends the worker before anything is sent.
        later, _ = self.one_turn("Name the script hook.py.", "The script is hook.py now.")
        self.mark(later)
        with self.holding(self.root / "curation.lock", "curation"):
            self.run_worker("end-of-turn")
        self.assertEqual(len(self.server.requests), 1)
        # A store of another device ends it too.
        self.run_worker("end-of-turn", expected="d_ffffffffffff")
        self.assertEqual(len(self.server.requests), 1)
        # Without the Anthropic memory key curation waits; the index is still kept.
        with mock.patch.dict(os.environ, {"CORTHEX_MEMORY_ANTHROPIC_API_KEY": ""}):
            (self.root / "index.db").unlink()
            self.run_worker("skill")
        self.assertEqual(len(self.server.requests), 1)
        self.assertTrue((self.root / "index.db").exists())
        self.assertEqual(len(self.markers()), 1)

    def test_tc435_a_turn_marked_while_the_run_goes_on_is_curated_before_it_ends(self):
        said, _ = self.one_turn()
        self.mark(said)
        later = []
        self.server.answers = [answer(change(quote(said, HOOKS), kind="decision"))]
        keep, kept = index_worker.keep, []

        def marking(memory, project, owner, deadline, **options):
            # A turn ends while step 6 runs; its trigger finds this run's lease fresh and starts no worker.
            if not later:
                turn, _ = self.one_turn("Name the script hook.py.", "The script is hook.py now.")
                self.mark(turn)
                later.append(turn)
                self.server.answers.append(answer(change(quote(turn, "hook.py"), kind="decision")))
                self.assertTrue(worker_launch._fresh(memory, project))
            kept.append(project)
            return keep(memory, project, owner, deadline, **options)
        with mock.patch.object(index_worker, "keep", side_effect=marking):
            self.run_worker("end-of-turn")
        # The run curates it after step 6, keeps the index again, and ends once curation finds nothing more.
        self.assertEqual((len(self.server.requests), self.markers(), len(kept)), (2, [], 2))
        self.assertEqual(sorted(value["quotes"][0]["entry"] for value in self.items().values()),
                         sorted([said["id"], later[0]["id"]]))
        self.assertEqual(self.progress()["logs"], {self.raw.name: later[0]["seq"] + 1})
        self.assertEqual(self.failures(), [])

    @contextlib.contextmanager
    def holding(self, path, kind):
        lease = locks.Lock(path, kind, DEVICE).acquire(time.monotonic() + 5)
        try:
            yield lease
        finally:
            lease.release()

    # TC-436

    def aged(self):
        """A raw log whose last entry is 101 days old, counted; line history, a run log and an injection log aged 101 and 99."""
        session = worker_fixture.Raw("worker-activation-retention")
        session.entries = []
        for days in (99, 99, 101):
            session.add("prompt", "turn", at=ago(days))
        (self.root / "raw" / (session.name + ".jsonl")).write_bytes(session.data())
        progress = self.progress()
        progress["logs"][session.name] = 3
        (self.root / "curation.json").write_bytes(format2.curation_bytes(progress))
        # Line history, a run log and an injection log, each with a record 101 days old and one 99.
        history = [dict(HISTORY, at=ago(days), why="retained reason") for days in (101, 99)]
        (self.root / "state-history.jsonl").write_bytes(b"".join(state_types.history_record_bytes(v) for v in history))
        (self.root / "runs" / "r_0000000000a1.json").write_bytes(run_log.log_bytes(logged("r_0000000000a1", ended=ago(101))))
        (self.root / "runs" / "r_0000000000a2.json").write_bytes(run_log.log_bytes(logged("r_0000000000a2", ended=ago(99))))
        (self.root / "injections").mkdir()
        injections = self.root / "injections" / (session.name + ".jsonl")
        injections.write_bytes(b"".join(injection_log.line_bytes(
            {"at": ago(days), "session": session.session, "where": "prompt", "items": [], "outcome": "below"})
            for days in (101, 99)))
        return session, history, injections

    def seqs(self, session):
        return [json.loads(line)["seq"] for line in (self.root / "raw" / (session.name + ".jsonl")).read_bytes().splitlines()]

    def test_tc436_a_session_start_expires_each_format_2_record_by_its_own_time(self):
        session, history, injections = self.aged()
        fence = self.progress()["fence"]
        # An end of a turn applies no retention.
        before = self.files(index=False)
        self.run_worker("end-of-turn")
        self.assertEqual(self.files(index=False), before)
        self.run_worker("start")
        self.assertEqual(self.seqs(session), [1, 2])
        after = self.progress()
        self.assertEqual((after["logs"][session.name], after["fence"]), (2, fence))
        self.assertEqual([json.loads(line)["at"] for line in
                          (self.root / "state-history.jsonl").read_bytes().splitlines()], [history[1]["at"]])
        self.assertEqual(sorted(path.name for path in (self.root / "runs").iterdir()), ["r_0000000000a2.json"])
        self.assertEqual(len(injections.read_bytes().splitlines()), 1)
        self.assertEqual(self.failures(), [])
        self.assertEqual(self.server.requests, [])

    def test_tc436_a_start_curates_then_sweeps_and_an_append_meanwhile_is_not_a_future_entry(self):
        session, _, _ = self.aged()
        said, _ = self.one_turn()
        self.mark(said)
        self.server.answers = [answer(change(quote(said, HOOKS), kind="decision"))]
        inventory, path = retention._inventory, self.root / "raw" / (session.name + ".jsonl")

        def appending(*args, **options):
            # A hook appends to the log after the project's cutoff was fixed and before the log is filtered.
            if len(self.seqs(session)) == 3:
                time.sleep(0.01)
                with path.open("ab") as stream:
                    stream.write(item_types._raw(session.add("prompt", "appended meanwhile", at=base.utc_time()))
                                 + b"\n")
            return inventory(*args, **options)
        with mock.patch.object(retention, "_inventory", side_effect=appending):
            self.run_worker("start")
        self.assertEqual((len(self.server.requests), self.markers()), (1, []))
        self.assertEqual(self.seqs(session), [1, 2, 4])
        self.assertEqual(self.failures(), [])

    def test_tc436_the_sweep_goes_by_the_period_set_when_it_runs(self):
        session, _, injections = self.aged()
        before = self.files(index=False)
        curated = worker_runtime._curated

        def raising(*args, **options):
            # The user raises the period while the run curates, which may last an hour.
            done = curated(*args, **options)
            self.configure(projects={"sample": {"enabled": True, "since": self.since}}, retention={"days": 365})
            return done
        with mock.patch.object(worker_runtime, "_curated", side_effect=raising):
            self.run_worker("start")
        self.assertEqual(self.seqs(session), [1, 2, 3])
        after = self.files(index=False)
        for path in (self.root / "state-history.jsonl", self.root / "runs" / "r_0000000000a1.json", injections):
            name = path.relative_to(self.folder).as_posix()
            self.assertEqual(after[name], before[name])
        self.assertEqual(self.failures(), [])

    def test_tc436_a_linked_run_folder_leaves_only_its_own_family(self):
        session, history, injections = self.aged()
        elsewhere = self.folder.parent / "elsewhere"
        (self.root / "runs").rename(elsewhere)
        try:
            os.symlink(str(elsewhere), str(self.root / "runs"), target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest("symbolic links are not available: %s" % error)
        outside = {path.name: path.read_bytes() for path in elsewhere.iterdir()}
        swept = []
        with mock.patch.object(retention, "retain_logs", side_effect=lambda *args, **options: swept.append(1)):
            self.run_worker("start")
        # The other families still expire, the worker's later phases still run, and nothing outside changes.
        self.assertEqual(self.seqs(session), [1, 2])
        self.assertEqual([json.loads(line)["at"] for line in
                          (self.root / "state-history.jsonl").read_bytes().splitlines()], [history[1]["at"]])
        self.assertEqual(len(injections.read_bytes().splitlines()), 1)
        self.assertEqual({path.name: path.read_bytes() for path in elsewhere.iterdir()}, outside)
        self.assertEqual((swept, self.failures()), ([1], [("retention", "lost-lock")]))

    def run_logs(self):
        return sorted(path.name for path in (self.root / "runs").iterdir())

    def history_times(self):
        return [json.loads(line)["at"] for line in (self.root / "state-history.jsonl").read_bytes().splitlines()]

    def test_tc436_a_raw_step_that_fails_leaves_the_other_families_to_expire(self):
        session, history, injections = self.aged()
        with mock.patch.object(retention, "retain_project", side_effect=PermissionError("held open")):
            self.run_worker("start")
        # The raw log stays for the next start; the line history, run logs and injection logs still expire.
        self.assertEqual(self.seqs(session), [1, 2, 3])
        self.assertEqual(self.history_times(), [history[1]["at"]])
        self.assertEqual(self.run_logs(), ["r_0000000000a2.json"])
        self.assertEqual(len(injections.read_bytes().splitlines()), 1)
        self.assertEqual(self.failures(), [("retention", "PermissionError")])

    def test_tc436_a_family_that_stays_busy_within_the_phase_leaves_the_next_family_to_run(self):
        session, history, injections = self.aged()
        # As when a lease or a read of the run logs outlasts its wait.
        with mock.patch.object(run_log, "expire", side_effect=locks.LockBusy()):
            self.run_worker("start")
        self.assertEqual(self.seqs(session), [1, 2])
        self.assertEqual(self.history_times(), [history[1]["at"]])
        self.assertEqual(self.run_logs(), ["r_0000000000a1.json", "r_0000000000a2.json"])
        self.assertEqual(len(injections.read_bytes().splitlines()), 1)
        self.assertEqual(self.failures(), [])

    def layer_records(self, injections):
        return len(self.history_times()), len(self.run_logs()), len(injections.read_bytes().splitlines())

    def test_tc436_a_line_history_that_stays_busy_before_its_owner_check_leaves_the_others_to_expire(self):
        session, history, injections = self.aged()
        before = (self.root / "state-history.jsonl").read_bytes()
        # As when the line history's own lease or read outlasts its wait, before its owner check.
        with mock.patch.object(history_retention, "retain_history", side_effect=locks.LockBusy()):
            self.run_worker("start")
        # That check did not look, so the run logs and injection logs go by the period read before the sweep.
        self.assertEqual((self.root / "state-history.jsonl").read_bytes(), before)
        self.assertEqual(self.seqs(session), [1, 2])
        self.assertEqual(self.run_logs(), ["r_0000000000a2.json"])
        self.assertEqual(len(injections.read_bytes().splitlines()), 1)
        self.assertEqual(self.failures(), [])

    def unread_period(self, confirmed):
        """A start whose line history's owner check cannot read the configuration after `confirmed` reads."""
        session, history, injections = self.aged()
        retain, read, inside = history_retention.retain_history, c2_store.C2Store.configuration, []

        def history_step(*args, **options):
            inside.append(0)
            try:
                return retain(*args, **options)
            finally:
                inside.pop()

        def busy(memory, *args, **options):
            # The read stays busy for its second, as while a new period is saved.
            if inside:
                inside[0] += 1
                if inside[0] > confirmed:
                    raise locks.LockBusy()
            return read(memory, *args, **options)
        with mock.patch.object(history_retention, "retain_history", side_effect=history_step), \
                mock.patch.object(c2_store.C2Store, "configuration", autospec=True, side_effect=busy):
            self.run_worker("start")
        # The raw log went by the period read before the sweep. Nothing under the layer lease goes by a
        # period that could not be read again: the three wait for the next start, quietly.
        self.assertEqual(self.seqs(session), [1, 2])
        self.assertEqual(self.layer_records(injections), (2, 2, 2))
        self.assertEqual(sorted(path.name for path in self.root.iterdir() if path.name.endswith(".tmp")), [])
        self.assertEqual(self.failures(), [])

    def test_tc436_a_period_that_the_owner_s_check_cannot_read_keeps_the_layer_records(self):
        self.unread_period(confirmed=0)

    def test_tc436_a_period_that_a_later_owner_s_check_cannot_read_keeps_the_layer_records(self):
        # The line history reports a later check's busy read as its own failure, which came from that read.
        self.unread_period(confirmed=1)

    def test_tc436_a_period_changed_during_the_sweep_keeps_the_layer_records(self):
        session, history, injections = self.aged()
        retain = history_retention.retain_history

        def raised(*args, **options):
            # The user raises the period after the sweep read it and the raw log went by it.
            self.configure(projects={"sample": {"enabled": True, "since": self.since}}, retention={"days": 365})
            return retain(*args, **options)
        with mock.patch.object(history_retention, "retain_history", side_effect=raised):
            self.run_worker("start")
        self.assertEqual(self.seqs(session), [1, 2])
        self.assertEqual(self.layer_records(injections), (2, 2, 2))
        self.assertEqual(self.failures(), [("retention", "RuntimeError")])

    def test_tc436_a_file_that_a_family_refuses_leaves_the_others_and_the_sweep_to_run(self):
        session, history, injections = self.aged()
        path = self.root / "state-history.jsonl"
        path.unlink()
        path.mkdir()
        swept = []
        with mock.patch.object(retention, "retain_logs", side_effect=lambda *args, **options: swept.append(1)):
            self.run_worker("start")
        # The line history reports what is no file as a lost lease, though the worker's leases and the
        # store still hold: it is noted, and the other families and the later phases still run.
        self.assertTrue(path.is_dir())
        self.assertEqual(self.seqs(session), [1, 2])
        self.assertEqual(self.run_logs(), ["r_0000000000a2.json"])
        self.assertEqual(len(injections.read_bytes().splitlines()), 1)
        self.assertEqual((swept, self.failures()), ([1], [("retention", "lost-lock")]))

    def test_tc436_a_linked_layer_lease_file_leaves_the_sweep_to_run(self):
        session, history, injections = self.aged()
        elsewhere, lock = self.folder.parent / "layer-lock-elsewhere", self.root / "layer.lock"
        elsewhere.write_bytes(b"")
        if lock.exists():
            lock.unlink()
        try:
            os.symlink(str(elsewhere), str(lock))
        except (OSError, NotImplementedError) as error:
            self.skipTest("symbolic links are not available: %s" % error)
        swept = []
        with mock.patch.object(retention, "retain_logs", side_effect=lambda *args, **options: swept.append(1)):
            self.run_worker("start")
        # Nothing can take the layer lease, so the project's records wait: curation and retention each
        # note the link, and the sweep goes on to the logs. The clean-up, which is C1's, ends the worker
        # at such a link, as C1's rule says.
        self.assertEqual(self.seqs(session), [1, 2, 3])
        self.assertEqual(self.layer_records(injections), (2, 2, 2))
        self.assertEqual(elsewhere.read_bytes(), b"")
        self.assertEqual(swept, [1])
        self.assertEqual(self.failures(), [("curate", "lost-lock"), ("retention", "lost-lock"),
                                           ("restore", "lost-lock")])

    def test_tc436_without_its_layer_folder_a_project_still_expires_its_run_and_injection_logs(self):
        session, history, injections = self.aged()
        before = (self.root / "state-history.jsonl").read_bytes()
        away = self.folder.parent / "layer-away"
        (self.root / "layer").rename(away)
        with mock.patch.object(worker_runtime, "_curated", return_value=True):
            self.run_worker("start")
        # The line history's owner check lists the layer folder: without it the history is kept and noted.
        self.assertFalse((self.root / "layer").exists())
        self.assertEqual((self.root / "state-history.jsonl").read_bytes(), before)
        self.assertEqual(self.seqs(session), [1, 2])
        self.assertEqual(self.run_logs(), ["r_0000000000a2.json"])
        self.assertEqual(len(injections.read_bytes().splitlines()), 1)
        self.assertEqual(self.failures(), [("retention", "RuntimeError")])

    def test_tc436_a_link_that_ends_the_starting_project_s_run_leaves_the_sweep_to_run(self):
        session, history, injections = self.aged()
        said, _ = self.one_turn()
        self.mark(said)
        elsewhere = self.folder.parent / "layer-elsewhere"
        (self.root / "layer").rename(elsewhere)
        try:
            os.symlink(str(elsewhere), str(self.root / "layer"), target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest("symbolic links are not available: %s" % error)

        def outside():
            return {path.relative_to(elsewhere).as_posix(): path.read_bytes()
                    for path in elsewhere.rglob("*") if path.is_file()}
        before, swept = outside(), []
        with mock.patch.object(retention, "retain_logs", side_effect=lambda *args, **options: swept.append(1)):
            self.run_worker("start")
        # Curation ends at the link before anything is sent. The worker's lease and the store still hold,
        # so the sweep runs: the line history waits for its layer folder, and the other families expire.
        self.assertEqual((self.server.requests, len(self.markers())), ([], 1))
        self.assertEqual(self.seqs(session), [1, 2])
        self.assertEqual(len(self.history_times()), 2)
        self.assertEqual(self.run_logs(), ["r_0000000000a2.json"])
        self.assertEqual(len(injections.read_bytes().splitlines()), 1)
        self.assertEqual(outside(), before)
        self.assertEqual((swept, self.failures()), ([1], [("curate", "lost-lock"), ("retention", "lost-lock")]))

    def test_tc436_a_step_that_raises_a_refused_link_ends_the_run_and_leaves_the_sweep_to_run(self):
        session, history, injections = self.aged()
        swept = []
        with mock.patch.object(consolidation_worker, "consolidate", side_effect=worker_support.UnsafePath()), \
                mock.patch.object(retention, "retain_logs", side_effect=lambda *args, **options: swept.append(1)):
            self.run_worker("start")
        # Step 3 raises the link where curation returns it as its reason: the run ends and the sweep runs.
        self.assertEqual(self.seqs(session), [1, 2])
        self.assertEqual(self.layer_records(injections), (1, 1, 1))
        self.assertEqual((swept, self.failures()), ([1], [("consolidate", "lost-lock")]))

    def test_tc436_a_store_record_that_cannot_be_looked_at_ends_the_worker_under_the_step_s_name(self):
        session, history, injections = self.aged()
        stamp, state, swept = worker_support.BoundDiagnostics._stamp, [], []

        def consolidate(*args, **options):
            state.append("ended")
            raise worker_support.UnsafePath()

        def held_open(logger, *args, **options):
            # The look at the store record right after the step ended is refused once.
            if state == ["ended"]:
                state.append("refused")
                raise PermissionError("held open")
            return stamp(logger, *args, **options)
        with mock.patch.object(consolidation_worker, "consolidate", side_effect=consolidate), \
                mock.patch.object(worker_support.BoundDiagnostics, "_stamp", autospec=True, side_effect=held_open), \
                mock.patch.object(retention, "retain_logs", side_effect=lambda *args, **options: swept.append(1)):
            self.run_worker("start")
        self.assertEqual(state, ["ended", "refused"])
        self.assertEqual(swept, [])
        self.assertEqual(self.seqs(session), [1, 2, 3])
        self.assertEqual(self.failures(), [("consolidate", "lost-lock"), ("consolidate", "PermissionError")])

    def test_tc436_a_replaced_store_ends_the_worker_before_the_sweep(self):
        session, history, injections = self.aged()
        said, _ = self.one_turn()
        self.mark(said)
        from memory_lib import curation_worker
        curate, swept = curation_worker.curate, []

        def replaced(*args, **options):
            # The store record is replaced by a copy of itself while the run goes on.
            record = self.folder / "store.json"
            copy = record.with_name("store.json.copy")
            copy.write_bytes(record.read_bytes())
            os.replace(str(copy), str(record))
            return curate(*args, **options)
        with mock.patch.object(curation_worker, "curate", side_effect=replaced), \
                mock.patch.object(retention, "retain_logs", side_effect=lambda *args, **options: swept.append(1)):
            self.run_worker("start")
        self.assertEqual((self.server.requests, len(self.markers()), swept), ([], 1, []))
        self.assertEqual(self.seqs(session), [1, 2, 3])
        self.assertEqual((len(self.history_times()), len(self.run_logs()), len(injections.read_bytes().splitlines())),
                         (2, 2, 2))

    # TC-437

    def test_tc437_a_confirmed_forget_starts_the_worker_which_curates_on_from_there(self):
        said, _ = self.one_turn()
        self.mark(said)
        self.server.answers = [answer(change(quote(said, HOOKS), kind="decision"))]
        self.run_worker("end-of-turn")
        (item,) = self.items()
        # The runner, with the project registered for a checkout, as the skill runs it.
        home, checkout = self.folder.parent / "home", self.folder.parent / "checkout"
        (home / ".corthex").mkdir(parents=True)
        checkout.mkdir()
        (home / ".corthex/projects.json").write_text(json.dumps(
            {"projects": [{"name": "sample", "path": str(checkout)}]}), encoding="utf-8")
        launches = []

        def launch(memory, project, reason, deadline, logger, *, expected_device=None, **options):
            launches.append((project, reason, expected_device, list(memory.held)))
            return True

        def forget(*argv):
            value, _ = commands.run(["--folder", str(checkout), "forget", item] + list(argv))
            return value
        with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home),
                                          "CORTHEX_MEMORY_HOME": str(self.folder)}), \
                mock.patch.object(activation, "_release", ["0.3.0"]), \
                mock.patch.object(worker_launch, "launch", side_effect=launch):
            preview = forget()
            self.assertEqual((preview["outcome"], launches), ("confirm", []))
            done = forget("--confirm", preview["confirm"])
        self.assertEqual(done["outcome"], "done")
        # Only the forget that was done starts the worker, with `skill` and the store's device, after its lease.
        self.assertEqual(launches, [("sample", "skill", DEVICE, [])])
        self.assertEqual(self.items(), {})
        # The worker that it starts finds nothing more to curate and sends nothing.
        self.run_worker("skill")
        self.assertEqual((len(self.server.requests), self.failures()), (1, []))


if __name__ == "__main__":
    unittest.main()
