"""TASK-114: the compaction check hook (API-156; SPEC-147) and its line in the next prompt (API-002 steps 6 to 8).

TC-412 to TC-418 at `compaction_check` and `prompt_recall.output` on made-up
format-2 stores. Nothing calls them before the 0.3.0 activation, so these are
direct module results: the hooks' input, their exit codes, timing lines and
failure log lines, and the prompt hook's order of steps, remain for the
activation.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import types
import unicodedata
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import clock, compaction_check, files, locks, prompt_recall, raw_log, store_deletion, worker_support
import test_memory_curation_worker as worker_fixture
import test_memory_start_summary as start_fixture

DEVICE = worker_fixture.DEVICE
HOST, SESSION = 'claude-code', 'session-compacted'
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
AT = '2026-11-12T12:00:00.000Z'
PARTS = compaction_check.PARTS
HEADINGS = ('Objective', 'Established facts', 'Changes', 'Checks', 'Dead ends', 'Remaining plan', 'Done when')


def summary(*names, body='Text under it.'):
    return ''.join('## %s\n%s\n\n' % (name, body) for name in names)


class CompactionCheckTest(unittest.TestCase):
    """The check on the start summary's store fixture, whose own tests stay in their module."""
    Fixture = worker_fixture.CurationWorkerTest
    configure, layer, saved, one_turn = Fixture.configure, Fixture.layer, Fixture.saved, Fixture.one_turn
    items, write = Fixture.items, Fixture.write
    setUp = start_fixture.StartSummaryTest.setUp

    def check(self, text, host=HOST, session=SESSION, seconds=5, when=NOW):
        settings = self.memory.configuration(deadline=clock.now() + 10)
        return compaction_check.check(self.memory, 'sample', host, session, text, clock.now() + seconds,
                                      settings=settings, when=when)

    def path(self, session=SESSION):
        return self.root / 'compaction' / (raw_log.log_name(HOST, session) + '.json')

    def record(self, session=SESSION):
        return compaction_check.parse_check(self.path(session).read_bytes())

    def pending(self, seconds=0.9):
        return compaction_check.pending(self.memory, 'sample', HOST, SESSION, clock.now() + seconds)

    def clear(self, shown, seconds=0.9):
        return compaction_check.clear(self.memory, 'sample', HOST, SESSION, shown, clock.now() + seconds)

    def files(self):
        return {path.relative_to(self.folder).as_posix(): path.read_bytes()
                for path in sorted(self.folder.rglob('*')) if path.is_file()}

    def holder(self, session):
        """Hold the session's raw log lock in another process, as a hook that records would."""
        path = self.root / 'raw' / (raw_log.log_name(HOST, session) + '.lock')
        code = ("import sys;sys.path.insert(0,sys.argv[1]);from pathlib import Path;import time;"
                "from memory_lib import locks;lease=locks.Lock(Path(sys.argv[2]),'raw',sys.argv[3]);"
                "lease.acquire(time.monotonic()+5);print('ready',flush=True);sys.stdin.readline();lease.release()")
        scripts = ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'
        child = subprocess.Popen([sys.executable, '-B', '-c', code, str(scripts), str(path), DEVICE],
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

    # check-1 (stage 06)

    def test_check_1_reads_each_line_in_its_form(self):
        missing = compaction_check.missing
        self.assertEqual(missing(''), list(PARTS))
        # Markdown marks, list marks, a list number and white space go, in either language and either case.
        self.assertEqual(missing('### **OBJECTIVE:** ship\r\n> - established   facts\r3) Changes made\n'
                                 '+ `Test results`\n* Dead-ends\nA. Next steps\n__Done when__: green'), [])
        # 가) is one letter and `)`, so the line after it names the plan.
        self.assertEqual(missing('# 목표\n- 확인된 사실\n1. 변경 사항\n**검사 결과**\n> 막힌 길\n가) 남은 계획\n완료 조건: 통과'), [])
        # Text in NFD is read in NFC.
        self.assertEqual(missing(unicodedata.normalize('NFD', '목표\n사실\n변경\n검사\n막힌 길\n계획\n완료 기준')), [])
        # A name counts only at the start of a line and before a character that is not a letter or a digit.
        for text in ('Objectives', 'Task1', '목표를 정함', 'The objective is', '1000. Objective', 'ab. Objective',
                     '1.Objective', 'objectiveé', 'Text\nmore text Objective'):
            with self.subTest(text=text):
                self.assertIn('objective', missing(text))
        for text in ('Objective', 'Goal:', 'task — ship it', '100. Objective', 'a) Objective', 'Objective…',
                     '  Objective', '\t-- Objective', 'Current request (verbatim)', '목표:', 'Text\n\n\n  Goal'):
            with self.subTest(text=text):
                self.assertNotIn('objective', missing(text))

    def test_no_name_of_one_part_starts_a_name_of_another(self):
        # One line names one part, so that a part's name never hides another's.
        for part, names in compaction_check.NAMES.items():
            for other, theirs in compaction_check.NAMES.items():
                if other != part:
                    for name in names:
                        for their in theirs:
                            self.assertFalse(their.startswith(name) and (len(their) == len(name) or
                                                                         not their[len(name)].isalnum()),
                                             (name, their))

    def test_a_deadline_that_passes_while_it_reads_raises_lock_busy(self):
        text = summary('Objective') * 20000
        now, calls = clock.now, []

        def later():
            calls.append(None)
            return now() + (10 if len(calls) > 1 else 0)
        with mock.patch.object(clock, 'now', side_effect=later):
            with self.assertRaises(locks.LockBusy):
                compaction_check.missing(text + 'Done when: x\n', now() + 5)
        self.assertGreater(len(text), compaction_check.SLICE)

    # SPEC-147#1

    def test_tc412_a_summary_with_all_seven_parts_leaves_no_check(self):
        forms = {
            'english headings': summary(*HEADINGS),
            'korean headings': summary('목표', '확인된 사실', '변경 사항', '검사 결과', '막힌 길', '남은 계획', '완료 조건'),
            'numbered': '1. Objective: ship\n2. Facts: one\n3) Changes made: two\n4. Tests: pass\n5. What failed: x\n'
                        '6. Next steps: y\n7. Definition of done: z\n',
            'bold': '**Objective:** a\n**Findings**\n**Files changed:**\n**Verification**\n**Failed approaches**\n'
                    '**Remaining steps**\n**Condition for done:** b\n',
            'list items': '- Goal: a\n* Facts\n+ Changed files\n- Test results\n- Dead end: polling\n- Plan\n- Done when: b\n',
        }
        for name, text in forms.items():
            with self.subTest(form=name):
                self.assertEqual(self.check(summary('Objective')).outcome, 'ok')
                self.assertTrue(self.path().is_file())
                result = self.check(text)
                self.assertEqual((result.outcome, result.missing, result.errors), ('ok', (), ()))
                # The earlier check is deleted, so the next prompt adds no line.
                self.assertFalse(self.path().exists())
                self.assertIsNone(self.pending())

    # SPEC-147#2

    def test_tc413_missing_parts_named_once_in_the_next_prompt(self):
        result = self.check(summary('Objective', 'Established facts', 'Changes', 'Checks', 'Remaining plan'))
        self.assertEqual((result.outcome, result.missing), ('ok', ('dead-ends', 'done')))
        self.assertEqual(self.record(), {'at': AT, 'missing': ['dead-ends', 'done']})
        shown = self.pending()
        self.assertEqual(shown, compaction_check.Pending(('dead-ends', 'done'), self.path().read_bytes()))
        line = compaction_check.line(shown.missing)
        self.assertEqual(line, 'The last compaction summary has no dead ends or done condition; read the handoff '
                               'record or the transcript before going on.')
        # The line comes first, then a blank line and the recall block, as one added context; alone without a block.
        recalled = prompt_recall.Result('injected', block='Memory for this prompt:\n- i_0123456789ab | decision')
        for value, context in ((recalled, line + '\n\n' + recalled.block), (prompt_recall.Result('below'), line)):
            data = prompt_recall.output(value, line)
            self.assertTrue(data.isascii())
            self.assertEqual(json.loads(data), {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit',
                                                                       'additionalContext': context}})
        self.assertEqual(prompt_recall.output(recalled), prompt_recall.output(recalled, None))
        self.assertEqual(prompt_recall.output(prompt_recall.Result('below')), b'')
        # After that prompt the check is gone, and the second prompt adds no line.
        self.assertTrue(self.clear(shown))
        self.assertFalse(self.path().exists())
        self.assertIsNone(self.pending())
        self.assertFalse(self.clear(shown))

    def test_the_line_names_one_part_alone_and_more_with_commas_and_or(self):
        line = compaction_check.line
        self.assertIn(' no remaining plan; ', line(['plan']))
        self.assertIn(' no objective, established facts, changes, checks, dead ends, remaining plan or done condition; ',
                      line(list(PARTS)))

    def test_a_check_that_a_later_compaction_wrote_stays_for_the_next_prompt(self):
        self.check(summary('Objective'))
        shown = self.pending()
        self.check(summary('Objective', 'Checks'), when=NOW + timedelta(minutes=5))
        self.assertFalse(self.clear(shown))
        self.assertEqual(self.record()['missing'], ['facts', 'changes', 'dead-ends', 'plan', 'done'])

    # SPEC-147#3

    def test_tc414_an_empty_summary_names_all_seven_parts_and_a_large_one_ends_within_the_deadline(self):
        started = time.monotonic()
        result = self.check('')
        self.assertLess(time.monotonic() - started, 0.3)
        self.assertEqual((result.outcome, result.missing), ('ok', PARTS))
        self.assertEqual(self.record()['missing'], list(PARTS))
        # 2 MB of ordinary lines with the done condition last: `ok` within the hook's 300 ms, or `deadline` on a
        # runner too slow for it, with no check written once the deadline has passed; either way the hook ends
        # within its deadline and one slice of the summary.
        text = ''.join('Line %d of the work that went on, with nothing that names a part.\n' % n for n in range(31000))
        text += 'Done when: green\n'
        self.assertGreaterEqual(len(text.encode('utf-8')), 2 * 1000 * 1000)
        before = self.path().read_bytes()
        after = compaction_check.check_bytes({'at': AT, 'missing': list(PARTS[:-1])})
        started = time.monotonic()
        result = self.check(text, seconds=0.3)
        self.assertLess(time.monotonic() - started, 0.3 + 0.2)
        if result.outcome == 'ok':
            self.assertEqual(self.path().read_bytes(), after)
        else:
            # The deadline passed while the summary was read, with nothing written, or after the check was written in
            # time, which the result then names.
            self.assertEqual(result.outcome, 'deadline')
            self.assertIn((self.path().read_bytes(), result.missing), ((before, ()), (after, PARTS[:-1])))

    def test_tc414_a_check_that_passes_300_ms_before_it_writes_writes_nothing(self):
        self.check(summary('Objective'))
        before = self.files()
        found = compaction_check.missing

        def slow(*args):
            value = found(*args)
            time.sleep(0.35)
            return value
        with mock.patch.object(compaction_check, 'missing', side_effect=slow):
            result = self.check(summary(*HEADINGS), seconds=0.3)
        self.assertEqual((result.outcome, result.error, result.missing), ('deadline', 'deadline', ()))
        self.assertEqual(self.files(), before)
        self.assertEqual(self.check(summary(*HEADINGS), seconds=0).outcome, 'deadline')
        self.assertEqual(self.files(), before)

    def test_a_check_written_before_step_5_fails_is_named_in_the_result(self):
        now, late = clock.now, []

        def failing(*args):
            late.append(None)
            raise locks.LockBusy()
        with mock.patch.object(compaction_check, '_expire', side_effect=failing), \
                mock.patch.object(clock, 'now', side_effect=lambda: now() + (60 if late else 0)):
            result = self.check(summary('Objective'))
        self.assertEqual((result.outcome, result.missing), ('deadline', PARTS[1:]))
        self.assertEqual(self.record()['missing'], list(PARTS[1:]))
        with mock.patch.object(compaction_check, '_expire', side_effect=OSError('listing failed')):
            result = self.check(summary('Objective', 'Checks'))
        self.assertEqual((result.outcome, result.missing, type(result.error)),
                         ('error', ('facts', 'changes', 'dead-ends', 'plan', 'done'), OSError))
        # And a configuration that cannot tell whether the project is enabled gives `error` before anything is written.
        class Unreadable:
            def enabled(self, project):
                raise ValueError('unreadable configuration')
        result = compaction_check.check(self.memory, 'sample', HOST, SESSION, '', clock.now() + 5,
                                        settings=Unreadable())
        self.assertEqual((result.outcome, result.missing, type(result.error)), ('error', (), ValueError))

    def test_a_deadline_just_after_the_move_names_the_parts_and_one_before_it_none(self):
        # The clean-up after the move checks the deadline and the lease too, so the check can be in place when step 4
        # stops: the result names what the session's check then holds.
        now, replace, moved = clock.now, os.replace, []

        def moving(*args):
            replace(*args)
            moved.append(None)
        with mock.patch.object(os, 'replace', side_effect=moving), \
                mock.patch.object(clock, 'now', side_effect=lambda: now() + (60 if moved else 0)):
            result = self.check(summary('Objective'))
        self.assertEqual((result.outcome, result.missing), ('deadline', PARTS[1:]))
        self.assertEqual(self.record()['missing'], list(PARTS[1:]))
        # A deadline before the move leaves the earlier check, and the result names no part.
        late = []

        def stopping(*args, **kwargs):
            late.append(None)
            raise locks.LockBusy()
        with mock.patch.object(files, 'replace_bytes', side_effect=stopping), \
                mock.patch.object(clock, 'now', side_effect=lambda: now() + (60 if late else 0)):
            result = self.check(summary('Objective', 'Checks'), when=NOW + timedelta(minutes=5))
        self.assertEqual((result.outcome, result.missing), ('deadline', ()))
        self.assertEqual(self.record()['missing'], list(PARTS[1:]))

    # SPEC-147#4

    def test_tc415_no_word_of_a_summary_is_kept(self):
        marker = 'MARKER_' + os.urandom(8).hex()
        text = summary('Objective', 'Established facts', 'Changes', 'Checks', 'Remaining plan', body=marker)
        text += marker + '\n'
        result = self.check(text)
        self.assertEqual(result.missing, ('dead-ends', 'done'))
        shown = self.pending()
        self.assertNotIn(marker, compaction_check.line(shown.missing))
        self.assertTrue(self.clear(shown))
        self.check(text)
        for name, data in self.files().items():
            self.assertNotIn(marker.encode('utf-8'), data, name)

    # SPEC-147#5

    def test_tc416_reading_the_check_leaves_it_until_its_line_is_printed(self):
        # A host-made prompt ends before step 6 (API-002 step 2), so it neither reads nor deletes the check; reading
        # it alone deletes nothing either, and only the prompt that printed its line deletes it.
        self.check(summary('Objective', 'Changes'))
        shown = self.pending()
        self.assertEqual(self.pending(), shown)
        self.assertTrue(self.path().is_file())
        self.assertTrue(self.clear(shown))
        self.assertFalse(self.path().exists())

    # SPEC-147#6

    def test_tc417_nothing_in_codex_for_a_project_not_enabled_or_without_consent(self):
        self.assertEqual(self.check('', host='codex'), compaction_check.Result(None))
        for options in (dict(enabled=False), dict(consent=None), dict(consent=2)):
            self.configure(**options)
            self.assertEqual(self.check(''), compaction_check.Result(None), options)
        self.assertFalse((self.root / 'compaction').exists())

    def test_tc417_a_compaction_folder_that_cannot_be_written_gives_error(self):
        (self.root / 'compaction').write_bytes(b'')
        result = self.check('')
        self.assertEqual(result.outcome, 'error')
        self.assertIsInstance(result.error, Exception)
        self.assertEqual((self.root / 'compaction').read_bytes(), b'')

    def test_a_check_that_cannot_be_read_is_deleted_when_the_prompt_reads_it(self):
        self.path().parent.mkdir()
        self.path().write_bytes(b'{"at": "2026-11-12T12:00:00.000Z", "missing": []}\n')
        with self.assertRaises(ValueError):
            self.pending()
        self.assertFalse(self.path().exists())
        self.assertIsNone(self.pending())
        # So is one that the system refuses to read.
        self.check(summary('Objective'))
        read = self.memory.fence.read

        def refused(path, *args, **kwargs):
            if Path(path).name == self.path().name:
                raise PermissionError(13, 'refused')
            return read(path, *args, **kwargs)
        with mock.patch.object(self.memory.fence, 'read', side_effect=refused), self.assertRaises(PermissionError):
            self.pending()
        self.assertFalse(self.path().exists())
        # And so is one nested too deeply for the JSON reader, here and in another session's place.
        deep = b'[' * 100000 + b']' * 100000
        self.path().write_bytes(deep)
        with self.assertRaises(ValueError):
            self.pending()
        self.assertFalse(self.path().exists())
        self.path('deep').write_bytes(deep)
        moment = (NOW - timedelta(days=8)).timestamp()
        os.utime(str(self.path('deep')), (moment, moment))
        result = self.check(summary(*HEADINGS))
        self.assertEqual([(log, type(error)) for log, error in result.errors],
                         [(raw_log.log_name(HOST, 'deep'), ValueError)])
        self.assertFalse(self.path('deep').exists())

    def test_a_check_that_another_process_holds_on_windows_is_read_again(self):
        # A sharing violation is read again until the deadline, as the other hooks read their files: neither the
        # session's check nor another session's old one is taken for unreadable.
        old = (NOW - timedelta(days=8)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        self.check(summary('Objective'))
        self.path('other').write_bytes(compaction_check.check_bytes({'at': old, 'missing': ['done']}))
        read, refused = self.memory.fence.read, set()

        def sharing(path, *args, **kwargs):
            path = Path(path)
            if path.parent.name == 'compaction' and path.name not in refused:
                refused.add(path.name)
                raise PermissionError(13, 'sharing violation')
            return read(path, *args, **kwargs)
        with mock.patch.object(files, '_WINDOWS', True), \
                mock.patch.object(self.memory.fence, 'read', side_effect=sharing):
            shown = self.pending()
            result = self.check(summary('Objective'), when=NOW + timedelta(minutes=5))
        self.assertEqual(shown.missing, PARTS[1:])
        self.assertEqual((result.outcome, result.errors), ('ok', ()))
        self.assertEqual(refused, {self.path().name, self.path('other').name})
        self.assertFalse(self.path('other').exists())

    # TC-418

    def test_tc418_a_held_raw_log_lock_gives_lock_busy_and_the_check_waits(self):
        self.check(summary('Objective'))
        release = self.holder(SESSION)
        before = self.files()
        started = time.monotonic()
        result = self.check(summary(*HEADINGS))
        self.assertLess(time.monotonic() - started, 0.3)
        self.assertEqual((result.outcome, result.error), ('lock-busy', 'lock-busy'))
        with self.assertRaises(locks.LockBusy):
            self.pending()
        self.assertEqual(self.files(), before)
        release()
        shown = self.pending()
        self.assertEqual(shown.missing, PARTS[1:])
        self.assertTrue(self.clear(shown))

    def test_tc418_old_checks_of_other_sessions_go_and_a_held_one_waits(self):
        old = (NOW - timedelta(days=8)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        recent = (NOW - timedelta(days=6)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        folder = self.root / 'compaction'
        folder.mkdir()
        for session, at in (('old', old), ('held', old), ('recent', recent)):
            self.path(session).write_bytes(compaction_check.check_bytes({'at': at, 'missing': ['done']}))
        self.path('unreadable').write_bytes(b'not json')
        self.path('unreadable-new').write_bytes(b'not json')
        moment = (NOW - timedelta(days=8)).timestamp()
        os.utime(str(self.path('unreadable')), (moment, moment))
        (folder / 'notes.txt').write_bytes(b'not a check')
        release = self.holder('held')
        result = self.check(summary(*HEADINGS))
        self.assertEqual(result.outcome, 'ok')
        # The unreadable old one is noted with its raw log's name and its error's kind (TBL-004).
        self.assertEqual([(log, type(error)) for log, error in result.errors],
                         [(raw_log.log_name(HOST, 'unreadable'), json.JSONDecodeError)])
        names = sorted(path.name for path in folder.iterdir())
        self.assertEqual(names, sorted([self.path(session).name for session in ('held', 'recent', 'unreadable-new')]
                                       + ['notes.txt']))
        # The held one goes at a later check, once its session's lock is free.
        release()
        self.assertEqual(self.check(summary(*HEADINGS)).errors, ())
        self.assertFalse(self.path('held').exists())
        self.assertTrue(self.path('recent').exists())

    def test_a_summary_with_every_part_and_no_check_waits_for_no_lock(self):
        release = self.holder(SESSION)
        self.assertEqual(self.check(summary(*HEADINGS)), compaction_check.Result('ok'))
        release()

    def test_other_sessions_checks_that_cannot_be_read_or_deleted_are_noted_and_the_rest_go(self):
        old = (NOW - timedelta(days=8)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        moment = (NOW - timedelta(days=8)).timestamp()
        (self.root / 'compaction').mkdir()
        sessions = ('refused', 'kept', 'gone')
        for session in sessions:
            self.path(session).write_bytes(compaction_check.check_bytes({'at': old, 'missing': ['done']}))
            os.utime(str(self.path(session)), (moment, moment))
        read, delete = self.memory.fence.read, files.delete_file

        def reading(path, *args, **kwargs):
            if Path(path).name == self.path('refused').name:
                raise PermissionError(13, 'refused')
            return read(path, *args, **kwargs)

        def deleting(path, check=None):
            if Path(path).name == self.path('kept').name:
                raise PermissionError(13, 'in use')
            return delete(path, check)
        with mock.patch.object(self.memory.fence, 'read', side_effect=reading), \
                mock.patch.object(files, 'delete_file', side_effect=deleting):
            result = self.check(summary(*HEADINGS))
        self.assertEqual(result.outcome, 'ok')
        # The one that cannot be read goes by its file's time and is noted; the one that cannot be deleted is noted and
        # stays for a later check; the third goes whatever their order.
        self.assertEqual(sorted((log, type(error)) for log, error in result.errors),
                         sorted((raw_log.log_name(HOST, session), PermissionError) for session in ('refused', 'kept')))
        self.assertEqual([self.path(session).exists() for session in sessions], [False, True, False])

    @unittest.skipIf(os.name == 'nt', 'a symbolic link needs a privilege on Windows')
    def test_a_link_in_a_checks_place_is_left_and_the_others_go(self):
        old = (NOW - timedelta(days=8)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        (self.root / 'compaction').mkdir()
        outside = self.folder / 'outside.json'
        outside.write_bytes(compaction_check.check_bytes({'at': old, 'missing': ['done']}))
        os.symlink(str(outside), str(self.path('linked')))
        for session in ('one', 'two'):
            self.path(session).write_bytes(compaction_check.check_bytes({'at': old, 'missing': ['done']}))
        result = self.check(summary(*HEADINGS))
        self.assertEqual((result.outcome, result.errors), ('ok', ()))
        self.assertTrue(os.path.islink(str(self.path('linked'))))
        self.assertTrue(outside.is_file())
        self.assertEqual([self.path(session).exists() for session in ('one', 'two')], [False, False])

    def test_a_folder_in_a_copys_place_leaves_its_session_and_the_others_go(self):
        # Any temporary name that the deletion of a check would take counts as its copy.
        old = (NOW - timedelta(days=8)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        folder = self.root / 'compaction'
        folder.mkdir()
        for session in ('blocked', 'other'):
            self.path(session).write_bytes(compaction_check.check_bytes({'at': old, 'missing': ['done']}))
        (folder / (raw_log.log_name(HOST, 'blocked') + '.json.partial.tmp')).mkdir()
        result = self.check(summary(*HEADINGS))
        self.assertEqual((result.outcome, result.errors), ('ok', ()))
        self.assertEqual([self.path(session).exists() for session in ('blocked', 'other')], [True, False])

    def test_a_folder_in_this_sessions_checks_place_is_left_and_gives_error(self):
        # Neither step 4 nor the prompt reads, replaces or deletes it, or the copies that a check's deletion takes,
        # and neither waits for the session's lock to find it.
        self.path().mkdir(parents=True)
        copy = self.path().with_name(self.path().name + '.abcd1234.tmp')
        copy.write_bytes(b'{"at": ')
        old = (NOW - timedelta(days=8)).timestamp()
        os.utime(str(copy), (old, old))
        release = self.holder(SESSION)
        for text in (summary(*HEADINGS), summary('Objective')):
            result = self.check(text)
            self.assertEqual((result.outcome, result.missing), ('error', ()), text)
            self.assertIsInstance(result.error, worker_support.UnsafePath)
        with self.assertRaises(worker_support.UnsafePath):
            self.pending()
        release()
        self.assertTrue(self.path().is_dir())
        self.assertEqual(copy.read_bytes(), b'{"at": ')

    def test_a_folder_that_takes_the_checks_place_before_the_lock_is_left_too(self):
        # The look before the lock found a file; the guard under the lock finds the folder before any read or change.
        self.path().mkdir(parents=True)
        copy = self.path().with_name(self.path().name + '.bak')
        copy.write_bytes(b'{"at": ')
        real, seen = compaction_check._file, []
        read, reads = self.memory.fence.read, []

        def earlier(memory, path):
            if path == self.path() and not seen:
                seen.append(path)
                return os.stat(__file__)
            return real(memory, path)

        def reading(path, *args, **kwargs):
            if Path(path).parent.name == 'compaction':
                reads.append(Path(path).name)
            return read(path, *args, **kwargs)
        for step in (lambda: self.check(summary(*HEADINGS)).error, self.pending):
            seen.clear()
            with mock.patch.object(compaction_check, '_file', side_effect=earlier), \
                    mock.patch.object(self.memory.fence, 'read', side_effect=reading):
                try:
                    error = step()
                except worker_support.UnsafePath as raised:
                    error = raised
            self.assertIsInstance(error, worker_support.UnsafePath)
            self.assertEqual((seen, reads), ([self.path()], []))
        self.assertTrue(self.path().is_dir())
        self.assertEqual(copy.read_bytes(), b'{"at": ')

    def test_this_sessions_copies_that_a_stopped_write_left_go_by_their_files_time_too(self):
        # Step 4 has just written this session's check or deleted it, so only its copies can be old.
        folder = self.root / 'compaction'
        folder.mkdir()
        old, recent = (NOW - timedelta(days=8)).timestamp(), (NOW - timedelta(days=6)).timestamp()
        stopped = folder / (self.path().name + '.abcd1234.tmp')
        stopped.write_bytes(b'{"at": ')
        os.utime(str(stopped), (old, old))
        self.assertEqual(self.check(summary(*HEADINGS)), compaction_check.Result('ok'))
        self.assertEqual(list(folder.iterdir()), [])
        # A recent one stays, and an old one beside a check stays until the check goes.
        stopped.write_bytes(b'{"at": ')
        os.utime(str(stopped), (recent, recent))
        self.assertEqual(self.check(summary(*HEADINGS)), compaction_check.Result('ok'))
        self.assertTrue(stopped.exists())
        os.utime(str(stopped), (old, old))
        self.assertEqual(self.check(summary('Objective')), compaction_check.Result('ok', PARTS[1:]))
        self.assertTrue(stopped.exists())
        self.assertTrue(self.clear(self.pending()))
        self.assertEqual(list(folder.iterdir()), [])

    def test_deleting_all_memory_takes_the_raw_log_lock_of_a_session_with_a_compaction_check(self):
        # A check and its copies change under the session's raw log lock, so a purge takes it before it deletes them,
        # also for a session whose raw log is gone.
        project = self.folder / 'projects' / 'sample'
        log, other = raw_log.log_name(HOST, SESSION), raw_log.log_name(HOST, 'other')
        kinds = {self.folder / 'projects': stat.S_IFDIR, project: stat.S_IFDIR, project / 'raw': stat.S_IFDIR,
                 project / 'compaction': stat.S_IFDIR, project / 'compaction' / (log + '.json'): stat.S_IFREG,
                 project / 'compaction' / (other + '.json.abcd1234.tmp'): stat.S_IFREG}
        deletion = types.SimpleNamespace(root=self.folder, nodes={
            path: (0, number, kind) for number, (path, kind) in enumerate(kinds.items())})
        planned = set(store_deletion.Deletion.plan(deletion))
        self.assertLessEqual({(4, project / 'raw' / (name + '.lock'), 'raw') for name in (log, other)}, planned)

    def test_copies_that_a_stopped_write_left_go_by_their_files_time(self):
        folder = self.root / 'compaction'
        folder.mkdir()
        old, recent = (NOW - timedelta(days=8)).timestamp(), (NOW - timedelta(days=6)).timestamp()
        copies = {'stopped': '.json.abcd1234.tmp', 'backed': '.json.bak', 'fresh': '.json.wxyz5678.tmp'}
        for session, suffix in copies.items():
            path = folder / (raw_log.log_name(HOST, session) + suffix)
            path.write_bytes(b'{"at": ')
            moment = recent if session == 'fresh' else old
            os.utime(str(path), (moment, moment))
        result = self.check(summary(*HEADINGS))
        self.assertEqual((result.outcome, result.errors), ('ok', ()))
        self.assertEqual(sorted(path.name for path in folder.iterdir()),
                         [raw_log.log_name(HOST, 'fresh') + copies['fresh']])

    def test_an_unreadable_check_deleted_before_the_deadline_passes_is_still_noted(self):
        # Step 5 notes each unreadable check as soon as it deletes it, so that a deadline that passes before the next
        # one still leaves the deleted one for the failure log (TBL-122).
        old = (NOW - timedelta(days=8)).timestamp()
        (self.root / 'compaction').mkdir()
        first, second = sorted(('one', 'two'), key=lambda session: raw_log.log_name(HOST, session))
        for session in (first, second):
            self.path(session).write_bytes(b'not json')
            os.utime(str(self.path(session)), (old, old))
        delete, now, late = files.delete_file, clock.now, []

        def deleting(path, check=None):
            delete(path, check)
            if path.name == self.path(first).name:
                late.append(None)
        with mock.patch.object(files, 'delete_file', side_effect=deleting), \
                mock.patch.object(clock, 'now', side_effect=lambda: now() + (60 if late else 0)):
            result = self.check(summary(*HEADINGS))
        self.assertEqual(result.outcome, 'deadline')
        self.assertEqual([(log, type(error)) for log, error in result.errors],
                         [(raw_log.log_name(HOST, first), json.JSONDecodeError)])
        self.assertEqual((self.path(first).exists(), self.path(second).exists()), (False, True))

    def test_the_check_is_written_as_a_notice_is_written(self):
        # Through a new file and a move, without the flush to disk and the backup (TBL-122).
        calls = []
        replace = files.replace_bytes

        def replacing(path, data, rebuildable=False, *args, **kwargs):
            calls.append((path.name, rebuildable))
            return replace(path, data, rebuildable, *args, **kwargs)
        with mock.patch.object(files, 'replace_bytes', side_effect=replacing):
            self.check(summary('Objective'))
        self.assertEqual(calls, [(self.path().name, True)])
        self.assertEqual(sorted(path.name for path in self.path().parent.iterdir()), [self.path().name])
        if os.name != 'nt':
            self.assertEqual(self.path().stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
