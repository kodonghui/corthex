"""TASK-034: the curation triggers from the markers' names, without a hook (unwired).

The TASK-034 parts of TC-142 to TC-147 and TC-149 to TC-151 on a made-up
format-2 store. No worker runs: the launch goes to a mocked Popen, and keys are
made up while the test runs.
"""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import clock, configuration, curation_triggers, format2, locks, worker_launch, worker_support
from memory_lib.c2_store import C2Store
from test_memory_fence_plan import PROGRESS

DEVICE = 'd_0123456789ab'
AT = '2026-11-04T13:00:00.000Z'
LOG = 'codex-0123456789abcdef'
OTHER = 'claude-code-fedcba9876543210'
NOW = datetime(2026, 11, 7, 12, 0, 0, tzinfo=timezone.utc)

_AUDIT = []


def _audit(event, args):
    if _AUDIT and event in ('open', 'os.scandir', 'os.listdir', 'os.rename', 'os.remove', 'os.truncate'):
        _AUDIT[-1].append((event, args))


sys.addaudithook(_audit)


def settings(document=None, temporary=False, consent=1):
    value = {'projects': {'sample': {'enabled': True, 'since': AT}}}
    if consent is not None:
        value['consent'] = {'at': AT, 'version': consent}
    value.update(document or {})
    return configuration.prepare(value, temporary=temporary)


class TriggerTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name).resolve() / 'memory'
        (self.folder / 'logs').mkdir(parents=True)
        self.project = self.folder / 'projects' / 'sample'
        for name in ('raw', 'unprocessed', 'notices', 'layer'):
            (self.project / name).mkdir(parents=True)
        (self.folder / 'store.json').write_bytes(format2.store_bytes(
            {'format': 2, 'device': DEVICE, 'made': AT, 'release': '0.2.1'}))
        (self.project / 'curation.json').write_bytes(format2.curation_bytes(PROGRESS))
        self.memory = C2Store(self.folder, expected_device=DEVICE)
        self.key = {'CORTHEX_MEMORY_ANTHROPIC_API_KEY': 'fixture-' + secrets.token_hex(12)}
        self.deadline = clock.now() + 10
        self.failures = []
        self.logger = mock.Mock(failure=lambda *args, **options: self.failures.append((args, options)))

    def mark(self, turn, minutes=1, log=LOG, seconds=0):
        at = NOW - timedelta(minutes=minutes, seconds=seconds)
        path = self.project / 'unprocessed' / ('%s.%s.%d' % (at.strftime('%Y%m%dT%H%M%SZ'), log, turn))
        path.write_bytes(b'')
        return path

    def decide(self, hook='end-of-turn', config=None, environment=None, now=NOW):
        return curation_triggers.decide(self.memory, config or settings(), 'sample', hook, self.deadline,
                                        now=now, environment=self.key if environment is None else environment)

    def start(self, hook='end-of-turn', config=None, deadline=None):
        with mock.patch.object(worker_launch.subprocess, 'Popen') as popen:
            outcome = curation_triggers.start(self.memory, config or settings(), 'sample', hook,
                                              deadline or self.deadline, self.logger, host='codex',
                                              now=NOW, environment=self.key)
        return outcome, [call.args[0] for call in popen.call_args_list]

    def test_tc142_nine_young_turns_do_not_meet_the_trigger_and_ten_start_the_worker(self):
        for turn in range(1, 10):
            self.mark(turn, minutes=29)
        self.assertEqual(self.decide(), 'not-met')
        self.assertEqual(self.start(), ('not-met', []))
        self.mark(10, minutes=1)
        self.assertEqual(self.decide(), 'start')
        outcome, commands = self.start()
        self.assertEqual(outcome, 'started')
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][-6:], ['--reason', 'end-of-turn', '--project', 'sample', '--expect-device', DEVICE])
        self.assertEqual(Path(commands[0][2]), worker_launch.WORKER)
        self.assertEqual(self.failures, [])

    def test_tc143_the_oldest_marker_name_older_than_the_minutes_setting(self):
        self.mark(1, minutes=31)
        self.mark(2, minutes=5)
        self.mark(3, minutes=1)
        self.assertEqual(self.decide(), 'start')
        self.assertEqual(self.decide(config=settings({'triggers': {'minutes': 60}})), 'not-met')
        self.assertEqual(self.decide(config=settings({'triggers': {'turns': 3, 'minutes': 60}})), 'start')
        # More than the minutes is needed: a turn exactly 30 minutes old waits.
        self.assertEqual(self.decide(now=NOW - timedelta(minutes=1)), 'not-met')
        self.assertEqual(self.decide(now=NOW - timedelta(minutes=1) + timedelta(microseconds=1)), 'start')

    def test_tc144_a_session_end_starts_the_worker_for_one_unprocessed_turn(self):
        self.assertEqual(self.decide('end'), 'not-met')
        self.mark(1, minutes=0)
        self.assertEqual(self.decide(), 'not-met')
        self.assertEqual(self.decide('end'), 'start')
        outcome, commands = self.start('end')
        self.assertEqual(outcome, 'started')
        self.assertEqual(commands[0][-6:-4], ['--reason', 'end'])
        # On a temporary device one turn meets the end-of-turn trigger (SPEC-011).
        self.assertEqual(self.decide(config=settings(temporary=True)), 'start')
        with self.assertRaises(ValueError):
            self.decide('start')

    def test_marker_names_count_each_turn_once_and_skip_other_names(self):
        self.mark(4, minutes=40)
        self.mark(4, minutes=2)
        self.mark(4, minutes=2, log=OTHER)
        folder = self.project / 'unprocessed'
        for name in ('20261107T120000Z.%s.0' % LOG, '20261131T120000Z.%s.5' % LOG, 'notes.txt',
                     '20261107T115900Z.%s.6.tmp' % LOG):
            (folder / name).write_bytes(b'')
        (folder / ('20261107T115900Z.%s.7' % LOG)).mkdir()
        markers = curation_triggers.scan(self.memory, self.project)
        self.assertEqual(markers.count, 2)
        self.assertEqual(markers.oldest, NOW - timedelta(minutes=40))
        self.assertEqual(curation_triggers.scan(self.memory, self.folder / 'projects' / 'absent'), (0, None))

    def test_tc150_stop_consent_key_and_a_fresh_lock_keep_the_worker_from_starting(self):
        for turn in range(1, 11):
            self.mark(turn)
        stopped = dict(PROGRESS, stopped={'at': AT, 'by': 'curate', 'errors': ['overloaded_error'] * 3})
        (self.project / 'curation.json').write_bytes(format2.curation_bytes(stopped))
        self.assertEqual(self.start(), ('stopped', []))
        (self.project / 'curation.json').write_bytes(format2.curation_bytes(PROGRESS))
        self.assertEqual(self.decide(config=settings(consent=None)), 'consent')
        self.assertEqual(self.decide(config=settings(consent=2)), 'consent')
        general = {'ANTHROPIC_API_KEY': 'fixture-' + secrets.token_hex(8), 'OPENAI_API_KEY': 'fixture-' + secrets.token_hex(8)}
        for environment in ({}, general,
                            {'CORTHEX_MEMORY_ANTHROPIC_API_KEY': ''},
                            {'CORTHEX_MEMORY_OPENAI_API_KEY': 'fixture-' + secrets.token_hex(8)}):
            with self.subTest(environment=sorted(environment)):
                self.assertEqual(self.decide(environment=environment), 'key')
        lock = self.project / 'curation.lock'
        lock.write_bytes(b'{}')
        self.assertEqual(self.decide(), 'fresh')
        self.assertEqual(self.start(), ('fresh', []))
        # TC-146: a lock not refreshed for 11 minutes no longer keeps a worker from starting.
        old = time.time() - 11 * 60
        os.utime(str(lock), (old, old))
        self.assertEqual(self.start()[0], 'started')
        # TC-147: a disabled project starts nothing.
        disabled = settings({'projects': {'sample': {'enabled': False, 'since': AT}}})
        self.assertEqual(self.start(config=disabled), ('disabled', []))
        self.assertEqual(self.failures, [])

    def test_a_missing_or_damaged_record_meets_no_trigger_until_the_worker_makes_it_again(self):
        for turn in range(1, 11):
            self.mark(turn)
        primary = self.project / 'curation.json'
        backup = self.project / 'curation.json.bak'
        backup.write_bytes(format2.curation_bytes(dict(PROGRESS, stopped={'at': AT, 'by': 'curate', 'errors': []})))
        primary.write_bytes(b'{damaged')
        # A readable backup decides; only the worker restores it, under its leases.
        self.assertEqual(self.decide(), 'stopped')
        backup.write_bytes(format2.curation_bytes(PROGRESS))
        self.assertEqual(self.decide(), 'start')
        self.assertEqual(primary.read_bytes(), b'{damaged')
        backup.write_bytes(b'{"logs": {}}')
        self.assertEqual(self.start(), ('record', []))
        primary.unlink()
        backup.unlink()
        self.assertEqual(self.start(), ('record', []))

    def test_tc149_a_late_check_is_skipped_and_an_error_reaches_the_hook(self):
        for turn in range(1, 11):
            self.mark(turn)
        self.assertEqual(self.start(deadline=clock.now() - 0.001), ('deadline', []))
        # A check that ends after the deadline starts no worker.
        now = clock.now()
        with mock.patch.object(curation_triggers, 'decide', return_value='start'), \
                mock.patch.object(clock, 'now', side_effect=[now, now + 60]):
            self.assertEqual(self.start(deadline=now + 30), ('deadline', []))
        # A record read that finds the deadline passed skips the start too.
        with mock.patch.object(curation_triggers, 'decide', side_effect=locks.LockBusy()):
            self.assertEqual(self.start(), ('deadline', []))
        with mock.patch.object(curation_triggers, 'scan', side_effect=PermissionError()):
            with self.assertRaises(PermissionError):
                self.start()
        with mock.patch.object(worker_launch.subprocess, 'Popen', side_effect=OSError()):
            outcome = curation_triggers.start(self.memory, settings(), 'sample', 'end-of-turn', self.deadline,
                                              self.logger, host='codex', now=NOW, environment=self.key)
        self.assertEqual(outcome, 'not-started')
        self.assertEqual([args[:2] for args, _ in self.failures], [('worker-start', 'trigger')])
        self.assertEqual(self.failures[0][1]['hook'], 'end-of-turn')

    def test_tc151_the_check_lists_the_markers_and_reads_the_record_only(self):
        for turn in range(1, 1001):
            self.mark(turn, minutes=turn % 29, seconds=turn % 60)
        with open(str(self.project / 'raw' / (LOG + '.jsonl')), 'wb') as raw:
            raw.truncate(100 * 1024 * 1024)
        self.decide()  # The first call loads what the later ones reuse.
        _AUDIT.append([])
        try:
            started = time.perf_counter()
            outcome = self.decide()
            elapsed = time.perf_counter() - started
        finally:
            events = _AUDIT.pop()
        self.assertEqual(outcome, 'start')
        self.assertLess(elapsed, 0.3)
        # Python 3.8's pathlib reports one opening twice, through io.open and os.open.
        opened = {(Path(os.fsdecode(args[0])).name, ''.join(sorted(set(args[1] or '') & set('wax+'))))
                  for event, args in events if event == 'open'}
        listed = [Path(os.fsdecode(args[0])).name for event, args in events if event in ('os.scandir', 'os.listdir')]
        self.assertEqual(opened, {('curation.json', '')})
        self.assertEqual(listed, ['unprocessed'])
        self.assertEqual([event for event, _ in events if event not in ('open', 'os.scandir', 'os.listdir')], [])

    def test_an_unsafe_markers_folder_is_refused(self):
        if not hasattr(os, 'symlink'):
            self.skipTest('no symbolic links')
        folder = self.project / 'unprocessed'
        folder.rmdir()
        outside = self.folder.parent / 'outside'
        outside.mkdir()
        try:
            os.symlink(str(outside), str(folder), target_is_directory=True)
        except OSError:
            self.skipTest('symbolic links need a privilege here')
        with self.assertRaises(worker_support.UnsafePath):
            self.decide()


if __name__ == '__main__':
    unittest.main()
