"""TASK-091: injection log lines (TBL-011) go by their own time once past the retention period (SPEC-009).

TC-424 through the retention helper, on made-up format-2 stores. Nothing calls
it before the 0.3.0 activation, when the session start runs C2's retention, and
the hooks that append the lines are not wired before it either.
"""
import contextlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import files, injection_log, injection_retention, locks, raw_log, worker_support
import test_memory_state_edits as edits_fixture
from test_memory_curator_answers import DEVICE, LATER

WHEN = '2026-11-07T12:00:00.000Z'
OLD = '2026-07-29T12:00:00.000Z'      # 101 days before WHEN
EDGE = '2026-07-30T12:00:00.000Z'     # exactly 100 days before: kept
KEPT = '2026-07-31T12:00:00.000Z'     # 99 days before
FUTURE = '2026-12-01T00:00:00.000Z'   # after WHEN, as with a wrong clock
HOST = 'claude-code'


def line(at, session='session-a', where='prompt'):
    value = {'at': at, 'session': session, 'where': where, 'items': []}
    if where == 'prompt':
        value['outcome'] = 'below'
    return injection_log.line_bytes(value)


class InjectionRetentionTest(unittest.TestCase):
    def setUp(self):
        self.fixture = edits_fixture.StateEditsTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.memory, self.project = self.fixture.memory, self.fixture.project
        self.folder = self.project / 'injections'
        self.folder.mkdir()
        (self.project / 'raw').mkdir()
        self.noted = []
        note = self.memory.note

        def noting(error, count=None, step='restore'):
            self.noted.append((error if isinstance(error, str) else type(error).__name__, count, step))
            note(error, count, step)
        self.memory.note = noting

    def path(self, session='session-a'):
        return self.folder / (raw_log.log_name(HOST, session) + '.jsonl')

    def write(self, *lines, session='session-a'):
        path = self.path(session)
        path.write_bytes(b''.join(lines))
        return path

    def expire(self, when=WHEN, days=100):
        with self.fixture.held():
            return injection_retention.expire(self.memory, self.project, self.fixture.deadline, when=when, days=days)

    def names(self):
        return sorted(path.name for path in self.folder.iterdir())

    def test_tc424_lines_past_retention_go_by_their_own_time(self):
        mixed = self.write(line(OLD, where='start'), line(KEPT), line(EDGE), line(OLD), line(FUTURE))
        gone = self.write(line(OLD, 'session-b', 'start'), line(OLD, 'session-b'), session='session-b')
        for suffix in ('.bak', '.a1b2c3d4.tmp', '.bak.e5f6a7b8.tmp'):
            gone.with_name(gone.name + suffix).write_bytes(line(OLD, 'session-b'))
        fresh = self.write(line(KEPT, 'session-c', 'start'), line(KEPT, 'session-c'), session='session-c')
        before = fresh.stat()
        damaged = self.write(b'{"at": "2026-07-29T12:00:00.000Z"\n', line(OLD, 'session-d'), line(KEPT, 'session-d'),
                             session='session-d')
        (self.folder / 'notes.txt').write_bytes(b'kept')
        self.assertEqual(self.expire(), 5)
        # In order, and with the line exactly 100 days old and the one dated in the future kept.
        self.assertEqual(mixed.read_bytes(), line(KEPT) + line(EDGE) + line(FUTURE))
        # A file with no line left goes with its copies; one with no line past the period stays as it was.
        self.assertFalse(any(name.startswith(gone.name) for name in self.names()))
        after = fresh.stat()
        self.assertEqual((after.st_ino, after.st_size, after.st_mtime_ns), (before.st_ino, before.st_size,
                                                                            before.st_mtime_ns))
        # A line that cannot be read goes with a rewrite, and the failure log counts it.
        self.assertEqual(damaged.read_bytes(), line(KEPT, 'session-d'))
        self.assertEqual(self.noted, [('damaged-line', 1, 'retention')])
        self.assertEqual(self.names(), sorted([mixed.name, fresh.name, damaged.name, 'notes.txt']))
        # Nothing is left to delete, and recall reads the kept lines as before.
        self.assertEqual(self.expire(), 0)
        self.assertEqual(mixed.read_bytes(), line(KEPT) + line(EDGE) + line(FUTURE))
        self.assertEqual(self.expire(when='2026-12-01T00:00:00.000Z', days=7), 5)
        self.assertEqual(mixed.read_bytes(), line(FUTURE))
        self.assertEqual(self.names(), sorted([mixed.name, 'notes.txt']))

    def test_a_shorter_period_goes_by_the_same_rule(self):
        path = self.write(line('2026-10-30T11:59:59.999Z'), line('2026-10-31T12:00:00.000Z'))
        self.assertEqual(self.expire(days=7), 1)
        self.assertEqual(path.read_bytes(), line('2026-10-31T12:00:00.000Z'))

    def test_a_line_appended_meanwhile_is_carried_whole(self):
        path = self.write(line(OLD, where='start'), line(KEPT))
        temporary = files._temporary

        def appending(*args, **kwargs):
            made = temporary(*args, **kwargs)
            if not appending.done:
                appending.done = True
                self.assertTrue(injection_log.append(self.memory, 'sample', HOST, 'session-a', 'prompt', [],
                                                     outcome='short'))
            return made
        appending.done = False
        with mock.patch.object(files, '_temporary', side_effect=appending):
            self.assertEqual(self.expire(), 1)
        rows = path.read_bytes().splitlines(keepends=True)
        self.assertEqual(rows[0], line(KEPT))
        self.assertEqual([injection_log.parse_line(row)['outcome'] for row in rows], ['below', 'short'])
        self.assertEqual(self.names(), [path.name])

    def test_an_unfinished_last_line_is_carried_with_an_append_and_goes_without_one(self):
        partial = line(KEPT)[:20]
        path = self.write(line(OLD), line(KEPT), partial)
        self.assertEqual(self.expire(), 1)
        self.assertEqual(path.read_bytes(), line(KEPT))
        self.assertEqual(self.noted, [('damaged-line', 1, 'retention')])
        self.noted.clear()
        path = self.write(line(OLD, 'session-b'), partial, session='session-b')
        temporary = files._temporary

        def appending(*args, **kwargs):
            made = temporary(*args, **kwargs)
            with path.open('ab') as stream:   # the rest of the line that was being appended
                stream.write(line(KEPT)[20:])
            return made
        with mock.patch.object(files, '_temporary', side_effect=appending):
            self.assertEqual(self.expire(), 1)
        self.assertEqual(path.read_bytes(), line(KEPT))
        self.assertEqual(self.noted, [])
        # An append after a stopped append's unfinished line starts on a line of its own, which leaves that line
        # complete but unreadable: it is carried and counted, as in a raw log's rewrite, and goes at the next pass.
        path = self.write(line(OLD, 'session-c'), partial, session='session-c')

        def crashed(*args, **kwargs):
            made = temporary(*args, **kwargs)
            self.assertTrue(injection_log.append(self.memory, 'sample', HOST, 'session-c', 'prompt', [],
                                                 outcome='short'))
            return made
        with mock.patch.object(files, '_temporary', side_effect=crashed):
            self.assertEqual(self.expire(), 1)
        rows = path.read_bytes().splitlines(keepends=True)
        self.assertEqual(rows[0], partial + b'\n')
        self.assertEqual(injection_log.parse_line(rows[1])['outcome'], 'short')
        self.assertEqual(self.noted, [('damaged-line', 1, 'retention')])
        self.noted.clear()
        self.assertEqual(self.expire(), 0)
        self.assertEqual(path.read_bytes(), rows[1])
        self.assertEqual(self.noted, [('damaged-line', 1, 'retention')])

    def holder(self, path, kind):
        """Hold a lease in another process, as a hook that appends would."""
        code = ("import sys;sys.path.insert(0,sys.argv[1]);from pathlib import Path;import time;"
                "from memory_lib import locks;lease=locks.Lock(Path(sys.argv[2]),sys.argv[3],sys.argv[4]);"
                "lease.acquire(time.monotonic()+5);print('ready',flush=True);sys.stdin.readline();lease.release()")
        scripts = ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'
        child = subprocess.Popen([sys.executable, '-B', '-c', code, str(scripts), str(path), kind, DEVICE],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)

        def stop():
            if child.poll() is None:
                child.stdin.write('release\n')
                child.stdin.flush()
                child.wait(timeout=10)
            child.stdin.close()
            child.stdout.close()
        self.addCleanup(stop)
        self.assertEqual(child.stdout.readline().strip(), 'ready')
        return stop

    def test_a_busy_raw_log_lock_leaves_the_file_for_the_next_start(self):
        path = self.write(line(OLD), line(KEPT))
        copy = path.with_name(path.name + '.bak')
        copy.write_bytes(line(OLD))
        orphan = self.path('orphan').with_name(self.path('orphan').name + '.bak')
        orphan.write_bytes(line(OLD, 'orphan'))
        releases = [self.holder(self.project / 'raw' / (raw_log.log_name(HOST, session) + '.lock'), 'raw')
                    for session in ('session-a', 'orphan')]
        started = time.monotonic()
        self.assertEqual(self.expire(), 0)
        # It waited as briefly as a raw log's rewrite does, not until its deadline.
        self.assertLess(time.monotonic() - started, 3)
        for release in releases:
            release()
        self.assertEqual(path.read_bytes(), line(OLD) + line(KEPT))
        self.assertEqual(self.names(), sorted([path.name, copy.name, orphan.name]))
        self.assertEqual(self.expire(), 2)
        self.assertEqual(path.read_bytes(), line(KEPT))
        self.assertEqual(self.names(), [path.name])

    def test_a_file_changed_otherwise_stops_retention_and_stays(self):
        path = self.write(line(OLD), line(KEPT))
        changed = line(KEPT, 'session-z')
        temporary = files._temporary

        def changing(*args, **kwargs):
            made = temporary(*args, **kwargs)
            with path.open('r+b') as stream:   # same file and size, other bytes
                stream.write(changed[:len(line(OLD))])
            return made
        with mock.patch.object(files, '_temporary', side_effect=changing), self.assertRaises(locks.LostLock):
            self.expire()
        self.assertEqual(path.read_bytes()[:len(line(OLD))], changed[:len(line(OLD))])
        self.assertEqual(self.names(), [path.name])
        # Bytes changed only while the file is read again, and put back before the lock, stop it too: the kept lines
        # come only from the bytes checked under the lock.
        original = line(OLD) + line(KEPT)
        path.write_bytes(original)

        def swapping(*args, **kwargs):
            with path.open('r+b') as stream:
                stream.seek(len(line(OLD)))
                stream.write(changed)
            try:
                return temporary(*args, **kwargs)
            finally:
                with path.open('r+b') as stream:
                    stream.seek(len(line(OLD)))
                    stream.write(line(KEPT))
        with mock.patch.object(files, '_temporary', side_effect=swapping), self.assertRaises(locks.LostLock):
            self.expire()
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.names(), [path.name])
        # A write that does not take the lock, after the bytes read are checked under it, stops it before the move.
        backup = files._backup

        def writing(*args, **kwargs):
            with path.open('ab') as stream:
                stream.write(line(KEPT))
            return backup(*args, **kwargs)
        with mock.patch.object(files, '_backup', side_effect=writing), self.assertRaises(locks.LostLock):
            self.expire()
        self.assertEqual(path.read_bytes(), original + line(KEPT))
        self.assertEqual(self.names(), [path.name])

    def test_each_first_read_lies_between_two_checks_of_the_leases(self):
        # One check of the leases between two files' first reads, as between publishing's reads since TASK-115: the
        # first read writes nothing, and only a file that changes is read again with every check.
        sessions = ('session-a', 'session-b', 'session-c')
        for session in sessions:
            self.write(line(KEPT, session), session=session)
        events = []
        guard, chunks = injection_retention.revision_io.guard, injection_retention.raw_rewrite._chunks

        def recording(*args, **kwargs):
            check = guard(*args, **kwargs)

            def checked():
                events.append('check')
                check()
            return checked

        def reading(memory, path, *args, **kwargs):
            events.append(path.name)
            return chunks(memory, path, *args, **kwargs)
        with mock.patch.object(injection_retention.revision_io, 'guard', recording), \
                mock.patch.object(injection_retention.raw_rewrite, '_chunks', reading):
            self.assertEqual(self.expire(), 0)
        first, second, third = sorted(self.path(session).name for session in sessions)
        self.assertEqual(events, ['check', first, 'check', second, 'check', third, 'check'])

    def test_the_bytes_read_are_checked_under_the_lock_without_the_leases_at_each_step(self):
        # The hooks wait for this lock briefly: the leases are checked before the bytes read are checked unchanged
        # under it and at every later step, but not at each step of that check, which writes nothing.
        path = self.write(line(OLD), line(KEPT))
        events = []
        guard, chunks, lease = (injection_retention.revision_io.guard, injection_retention.raw_rewrite._chunks,
                                injection_retention._lease)

        def recording(*args, **kwargs):
            check = guard(*args, **kwargs)

            def checked():
                events.append('check')
                check()
            return checked

        def reading(*args, **kwargs):
            events.append('read')
            yield from chunks(*args, **kwargs)
            events.append('end')

        @contextlib.contextmanager
        def locking(*args, **kwargs):
            with lease(*args, **kwargs):
                events.append('lock')
                yield
                events.append('unlock')
        with mock.patch.object(injection_retention.revision_io, 'guard', recording), \
                mock.patch.object(injection_retention.raw_rewrite, '_chunks', reading), \
                mock.patch.object(injection_retention, '_lease', locking):
            self.assertEqual(self.expire(), 1)
        self.assertEqual(path.read_bytes(), line(KEPT))
        starts = [index for index, event in enumerate(events) if event == 'read']
        ends = [index for index, event in enumerate(events) if event == 'end']
        # The first read, the read into the temporary file, the check under the lock, and the carry that never came.
        self.assertEqual(len(starts), 3)
        self.assertEqual(['check' in events[start:end] for start, end in zip(starts, ends)], [False, True, False])
        locked, unlocked = events.index('lock'), events.index('unlock')
        self.assertLess(locked, starts[2])
        self.assertLess(ends[2], unlocked)
        self.assertIn('check', events[locked:starts[2]])
        self.assertIn('check', events[ends[2]:unlocked])

    def test_a_lease_lost_during_a_first_read_stops_the_pass_before_any_write(self):
        paths = [self.write(line(OLD, session), line(KEPT, session), session=session)
                 for session in ('session-a', 'session-b')]
        guard, calls = injection_retention.revision_io.guard, []

        def losing(*args, **kwargs):
            check = guard(*args, **kwargs)

            def checked():
                calls.append(None)
                if len(calls) == 2:   # the first check after the first file's read
                    raise locks.LostLock()
                check()
            return checked
        with mock.patch.object(injection_retention.revision_io, 'guard', losing), self.assertRaises(locks.LostLock):
            self.expire()
        self.assertEqual([path.read_bytes() for path in paths],
                         [line(OLD, session) + line(KEPT, session) for session in ('session-a', 'session-b')])
        self.assertEqual(self.names(), sorted(path.name for path in paths))
        self.assertEqual(self.noted, [])

    def test_a_file_that_cannot_be_replaced_waits_for_the_next_start(self):
        path = self.write(line(OLD), line(KEPT))
        replace = os.replace

        def refusing(source, target):
            if Path(target) == path:
                raise PermissionError('in use')
            return replace(source, target)
        with mock.patch.object(injection_retention.os, 'replace', side_effect=refusing):
            self.assertEqual(self.expire(), 0)
        self.assertEqual(path.read_bytes(), line(OLD) + line(KEPT))
        self.assertEqual(self.noted, [('PermissionError', None, 'retention')])
        self.assertNotIn('.tmp', ''.join(self.names()))
        self.assertEqual(self.expire(), 1)
        self.assertEqual(self.names(), [path.name])

    def test_copies_go_under_the_lock_and_a_missing_files_backup_comes_back_first(self):
        # Copies of a file that is here: a backup left by a stopped rewrite, with lines past the period, and a
        # temporary file; neither is read while the file is here.
        kept = self.write(line(KEPT, 'left'), session='left')
        before = kept.stat()
        (self.folder / (kept.name + '.bak')).write_bytes(line(OLD, 'left') + line(KEPT, 'left'))
        (self.folder / (kept.name + '.c1d2e3f4.tmp')).write_bytes(line(OLD, 'left'))
        # A backup of a missing file comes back, as the next append would bring it back, and its lines go by their
        # own time, the one dated in the future included, whatever the copy's modification time.
        orphan = self.path('orphan')
        (self.folder / (orphan.name + '.bak')).write_bytes(line(OLD, 'orphan') + line(KEPT, 'orphan') +
                                                           line(FUTURE, 'orphan'))
        (self.folder / (orphan.name + '.bak.a9b8c7d6.tmp')).write_bytes(line(OLD, 'orphan'))
        stamp = time.mktime(time.strptime('2026-07-01', '%Y-%m-%d'))
        os.utime(str(self.folder / (orphan.name + '.bak')), (stamp, stamp))
        # A temporary file alone is not read by anyone.
        (self.folder / (self.path('tmp').name + '.e5f6a7b8.tmp')).write_bytes(line(OLD, 'tmp'))
        self.assertEqual(self.expire(), 1)
        self.assertEqual(self.names(), sorted([kept.name, orphan.name]))
        after = kept.stat()
        self.assertEqual((after.st_ino, after.st_mtime_ns), (before.st_ino, before.st_mtime_ns))
        self.assertEqual(orphan.read_bytes(), line(KEPT, 'orphan') + line(FUTURE, 'orphan'))
        self.assertEqual(self.noted, [('restored', None, 'restore')])

    def test_unreadable_lines_an_empty_file_and_an_unfinished_line_go_without_a_line_past_the_period(self):
        damaged = self.write(b'garbage\n', line(KEPT, 'session-b'), session='session-b')
        empty = self.write(session='session-c')
        unfinished = self.write(line(KEPT, 'session-d')[:20], session='session-d')
        self.assertEqual(self.expire(), 0)
        self.assertEqual(damaged.read_bytes(), line(KEPT, 'session-b'))
        self.assertEqual(self.names(), [damaged.name])
        self.assertFalse(empty.exists() or unfinished.exists())
        self.assertEqual(sorted(self.noted), [('damaged-line', 1, 'retention')] * 2)

    def test_a_session_that_fails_leaves_the_others_to_expire(self):
        bad = self.write(b'x' * 300, line(OLD, 'bad'), session='bad')
        good = self.write(line(OLD, 'good'), line(KEPT, 'good'), session='good')
        self.assertLess(bad.name, good.name)
        with mock.patch.object(injection_retention.raw_rewrite.cleanup, 'LINE_BYTES', 200):
            self.assertEqual(self.expire(), 1)
        self.assertEqual(self.noted, [('OversizedLine', None, 'retention')])
        self.assertEqual(bad.read_bytes(), b'x' * 300 + line(OLD, 'bad'))
        self.assertEqual(good.read_bytes(), line(KEPT, 'good'))

    def test_expiry_needs_the_layer_lease_and_a_valid_period(self):
        self.write(line(OLD))
        with self.assertRaises(locks.LostLock):
            injection_retention.expire(self.memory, self.project, self.fixture.deadline, when=WHEN, days=100)
        for days in (0, 3651, True, 1.5):
            with self.subTest(days=days), self.assertRaises(ValueError):
                self.expire(days=days)
        with self.assertRaises(ValueError):
            self.expire(when='2026-11-07')
        self.assertEqual(self.path().read_bytes(), line(OLD))

    def test_a_project_without_injection_logs_expires_nothing(self):
        self.folder.rmdir()
        self.assertEqual(self.expire(), 0)
        self.assertFalse(self.folder.exists())

    def outside(self):
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(folder), True)
        return folder

    def alias(self, link, target, directory=False):
        """A symbolic link, or on Windows without the privilege a directory junction."""
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError:
            program = Path(os.environ.get('SystemRoot', '')) / 'System32' / 'cmd.exe'
            if os.name != 'nt' or not directory or not program.is_absolute():
                self.skipTest('symbolic links unavailable')
            made = subprocess.run([str(program), '/d', '/c', 'mklink', '/J', str(link), str(target)],
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
            if made.returncode:
                self.skipTest('directory junctions unavailable')

    def test_a_backup_that_becomes_a_link_before_it_comes_back_is_left(self):
        outside = self.outside()
        (outside / 'bak').write_bytes(line(OLD))
        path = self.path()
        backup = path.with_name(path.name + '.bak')
        backup.write_bytes(line(OLD) + line(KEPT))
        chunks = injection_retention.raw_rewrite._chunks

        def swapping(memory, candidate, *args, **kwargs):
            yield from chunks(memory, candidate, *args, **kwargs)
            if candidate == backup:   # once the backup is read, before it moves
                backup.unlink()
                self.alias(backup, outside / 'bak')
        with mock.patch.object(injection_retention.raw_rewrite, '_chunks', swapping):
            self.assertEqual(self.expire(), 0)
        self.assertFalse(os.path.lexists(str(path)))
        self.assertTrue(backup.is_symlink())
        self.assertEqual((outside / 'bak').read_bytes(), line(OLD))

    def test_expiry_never_reads_or_deletes_through_a_link(self):
        outside = self.outside()
        name = raw_log.log_name(HOST, 'session-a') + '.jsonl'
        (outside / name).write_bytes(line(OLD))
        (outside / (name + '.bak')).write_bytes(line(OLD))
        self.folder.rmdir()
        self.alias(self.folder, outside, directory=True)
        with self.assertRaises(worker_support.UnsafePath):
            self.expire()
        self.assertEqual(sorted(path.name for path in outside.iterdir()), [name, name + '.bak'])

    def test_a_linked_file_or_copy_or_a_folder_in_its_place_is_left_and_nothing_outside_changes(self):
        outside = self.outside()
        for name in ('log', 'bak'):
            (outside / name).write_bytes(line(OLD))
        stamp = time.mktime(time.strptime('2026-07-01', '%Y-%m-%d'))
        os.utime(str(outside / 'bak'), (stamp, stamp))
        linked, copied = self.path('linked'), self.path('copied')
        shared = self.write(line(OLD, 'shared'), line(KEPT, 'shared'), session='shared')
        # A folder named as a file's backup is not a backup: the session is left as a linked one is.
        named = self.write(line(OLD, 'named'), session='named')
        (self.folder / (named.name + '.bak')).mkdir()
        self.alias(linked, outside / 'log')
        self.alias(copied.with_name(copied.name + '.bak'), outside / 'bak')
        os.link(str(shared), str(outside / 'shared'))
        self.assertEqual(self.expire(), 1)
        self.assertEqual(self.names(), sorted([linked.name, copied.name + '.bak', shared.name, named.name,
                                               named.name + '.bak']))
        self.assertEqual(named.read_bytes(), line(OLD, 'named'))
        self.assertEqual(self.noted, [])
        # A file with another name is rewritten as a new file; the other name keeps its bytes.
        self.assertEqual(shared.read_bytes(), line(KEPT, 'shared'))
        self.assertEqual([(outside / name).read_bytes() for name in ('log', 'bak')], [line(OLD)] * 2)
        self.assertEqual((outside / 'shared').read_bytes(), line(OLD, 'shared') + line(KEPT, 'shared'))


if __name__ == '__main__':
    unittest.main()
