"""TASK-091: the start summary's memory part from the curated layer, and its step 7.

TC-198 to TC-204 and TC-350, and the start summary's lines of TC-120, TC-148,
TC-170 and TC-196, on made-up format-2 stores, with keys made up during the
run. Nothing calls the module before the 0.3.0 activation, so these are direct
module results: the hook's output, timing line and exit code remain for the
activation.
"""
from datetime import datetime, timedelta, timezone
import json
import os
import secrets
import subprocess
import sys
import time
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import (clock, configuration, conflict_counts, curation_triggers, format2, injection_log,
                        item_types, locks, raw_log, start_memory, start_summary, state_types)
import test_memory_curation_worker as worker_fixture

AT, WHEN, DEVICE = worker_fixture.AT, worker_fixture.WHEN, worker_fixture.DEVICE
EPOCH, SESSION = worker_fixture.EPOCH, 'fixture-start-091'
BASE = '# Working principles\n\nThe base of the start summary, as 0.1.0 builds it.'
UTC = timezone.utc
ident = worker_fixture.ident


def line(part, pos, text, cites):
    return dict(id=ident('s'), part=part, pos=pos, text=text, cites=list(cites), at=AT, device=DEVICE)


def pin(item, at, on=True):
    return dict(item=item['id'], on=on, at=at, device=DEVICE)


class StartSummaryTest(unittest.TestCase):
    """The memory part on the curation worker's store fixture, whose own tests stay in their module."""
    Fixture = worker_fixture.CurationWorkerTest
    configure, layer, saved, one_turn = Fixture.configure, Fixture.layer, Fixture.saved, Fixture.one_turn
    items, write = Fixture.items, Fixture.write

    def setUp(self):
        remote = mock.patch.dict(os.environ, {'CLAUDE_CODE_REMOTE': ''})
        remote.start()
        self.addCleanup(remote.stop)
        self.Fixture.setUp(self)
        self.environment = {name: 'memory-key-' + secrets.token_hex(12) for name in (
            'CORTHEX_MEMORY_ANTHROPIC_API_KEY', 'CORTHEX_MEMORY_OPENAI_API_KEY')}
        self.said, _ = self.one_turn()

    # The store

    def item(self, title, kind='decision', **fields):
        value = self.saved(self.said, worker_fixture.HOOKS, kind=kind)
        value.update(title=title, text=title + ' holds.')
        value.update(fields)
        return value

    def pins(self, *records):
        (self.root / 'layer/pins.json').write_bytes(item_types.pins_bytes({'pins': list(records)}))

    def notice(self, name, **value):
        value.setdefault('at', AT)
        path = self.root / 'notices' / name
        path.write_bytes(item_types.notice_bytes(value))
        return path

    def progress(self, **changes):
        value = {'logs': {}, 'applies': 0, 'recent': [], 'consolidation': {'failures': 0},
                 'fence': {'epoch': EPOCH, 'generation': 0, 'revisions': {}}}
        value.update(changes)
        (self.root / 'curation.json').write_bytes(format2.curation_bytes(value))

    def marker(self, at, turn):
        name = '%s.%s.%d' % (at.strftime('%Y%m%dT%H%M%SZ'), self.raw.name, turn)
        (self.root / 'unprocessed' / name).write_bytes(b'')

    def holder(self, path, kind):
        """Hold a lease in another process, as a concurrent start or hook would."""
        code = ("import sys;sys.path.insert(0,sys.argv[1]);from pathlib import Path;import time;"
                "from memory_lib import locks;lease=locks.Lock(Path(sys.argv[2]),sys.argv[3],sys.argv[4]);"
                "lease.acquire(time.monotonic()+5);print('ready',flush=True);sys.stdin.readline();lease.release()")
        child = subprocess.Popen([sys.executable, '-B', '-c', code, str(worker_fixture.SCRIPTS), str(path), kind,
                                  DEVICE], stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)

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

    def counts(self):
        path = self.root / 'notices' / conflict_counts.NAME
        return json.loads(path.read_bytes())['counts'] if path.exists() else None

    # Starting

    def start(self, seconds=5, environment=None, **options):
        settings = self.memory.configuration(deadline=clock.now() + 10)
        environment = dict(self.environment) if environment is None else environment
        return start_summary.compose(self.memory, 'sample', BASE, clock.now() + seconds, settings=settings,
                                     environment=environment, now=WHEN, zone=UTC, **options)

    def memory_part(self, part):
        self.assertEqual(part.outcome, 'ok')
        self.assertTrue(part.text.startswith(BASE + '\n\n## Memory\n\n'), part.text)
        return part.text[len(BASE) + 2:]

    def notices(self, part):
        """The notice rows of a composed memory part, without their dashes."""
        rows = self.memory_part(part).split('\n\n')[1].splitlines()
        if rows[0] != start_memory.NOTICE_HEADING:
            return []
        return [row[2:] if row.startswith('- ') else row for row in rows[1:]]

    def after(self, part):
        return start_summary.after(self.memory, 'sample', part, 'claude-code', SESSION, when=WHEN)

    def injections(self):
        path = self.root / 'injections' / (raw_log.log_name('claude-code', SESSION) + '.jsonl')
        return [injection_log.parse_line(data) for data in path.read_bytes().splitlines()] if path.exists() else []

    # SPEC-021

    def test_tc198_notices_then_pins_in_the_order_they_were_pinned_then_the_state_by_part_and_position(self):
        first, second = self.item('Keep one script'), self.item('Prefer short names', kind='preference')
        goal, rule, extra = self.item('Ship it', kind='fact'), self.item('One hook file'), self.item('Note', 'lesson')
        lines = [line('next', 2, 'Tag the release.', [first['id'], second['id'], goal['id'], extra['id']]),
                 line('goal', 1, 'Ship the start summary.', [goal['id']]),
                 line('decisions', 1, 'One script serves the hooks.', [rule['id']]),
                 line('progress', 1, 'The\tnotices of  stage 06.', [self.said['id']]),
                 line('blockers', 1, 'Windows sharing.', [extra['id']]),
                 line('next', 1, 'Write the tests.', [extra['id']])]
        self.layer([first, second, goal, rule, extra], lines)
        # The pins file lists the later pin first; the summary goes by when each was pinned.
        self.pins(pin(second, '2026-11-05T00:00:00.000Z'), pin(first, '2026-11-04T00:00:00.000Z'))
        self.notice('rebuilt.json', kind='rebuilt')
        del self.environment['CORTHEX_MEMORY_OPENAI_API_KEY']
        part = self.start()
        self.assertEqual(self.memory_part(part), '\n\n'.join([
            '## Memory',
            'Notices from the memory plugin:\n'
            "- Recall and search by meaning are waiting for CORTHEX_MEMORY_OPENAI_API_KEY, which the hook's "
            'environment does not have. Memory keys are read only from the environment that the host starts in, '
            "such as a shell profile or a cloud environment's secret settings.\n"
            '- The curation record was made again from the raw log, so some turns may be curated twice and '
            'merged later.',
            start_memory.REFERENCE,
            'Pinned:\n'
            '- %s | decision | user decision | 2026-11-04 | Keep one script holds.\n'
            '- %s | preference | user | 2026-11-04 | Prefer short names holds.' % (first['id'], second['id']),
            'Current state:\n'
            '- Goal: Ship the start summary. (%s)\n'
            '- Decision in force: One script serves the hooks. (%s)\n'
            '- Work in progress: The notices of stage 06.\n'
            '- Blocker: Windows sharing. (%s)\n'
            '- Next action: Write the tests. (%s)\n'
            '- Next action: Tag the release. (%s, %s, %s)' % (
                goal['id'], rule['id'], extra['id'], extra['id'], first['id'], second['id'], goal['id'])]))
        self.assertEqual(part.pins, (first['id'], second['id']))
        self.assertLess(len(part.text.encode('utf-8')), 8000)
        self.assertEqual(json.dumps(part.text).count(self.environment['CORTHEX_MEMORY_ANTHROPIC_API_KEY']), 0)

    def test_tc403_a_dead_end_and_the_done_condition_show_labelled_without_their_marker(self):
        rule = self.item('Keep one script')
        lines = [line('blockers', 1, 'Dead end: Polling the raw lock in a loop hangs on Windows.', [self.said['id']]),
                 line('blockers', 2, 'Windows sharing.', [rule['id']]),
                 line('next', 1, 'Done when: the hook check passes on Windows.', [rule['id']]),
                 line('next', 2, 'Write the hook check.', [rule['id']])]
        self.layer([rule], lines)
        self.assertEqual(self.memory_part(self.start()).split('\n\n')[-1],
                         'Current state:\n'
                         '- Dead end: Polling the raw lock in a loop hangs on Windows.\n'
                         '- Blocker: Windows sharing. (%s)\n'
                         '- Done when: the hook check passes on Windows. (%s)\n'
                         '- Next action: Write the hook check. (%s)' % (rule['id'], rule['id'], rule['id']))

    def test_a_pin_or_line_that_is_not_current_or_valid_is_not_shown(self):
        kept, old, new = self.item('Kept'), self.item('Old'), self.item('New')
        withdrawn, undone = self.item('Withdrawn', status='withdrawn'), self.item('Undone', status='undone')
        forgotten, gone, backed = self.item('Forgotten'), self.item('Gone'), self.item('Backed up')
        old.update(status='superseded', superseded_by=new['id'])
        stale = line('decisions', 1, 'Rests on a superseded decision.', [old['id']])
        held = line('decisions', 2, 'Rests on the new decision.', [new['id']])
        private = line('progress', 1, 'Quotes forgotten words.', [forgotten['quotes'][0]['entry']])
        removed = line('progress', 2, 'Removed by an edit.', [kept['id']])
        self.layer([kept, old, new, withdrawn, undone, forgotten, gone, backed], [stale, held, private, removed])
        (self.root / 'layer/items' / (gone['id'] + '.json')).unlink()
        tombstone = dict(item=forgotten['id'], project='sample', at=AT, device=DEVICE, quotes=[
            {k: forgotten['quotes'][0][k] for k in ('device', 'entry', 'log', 'start', 'end')}])
        (self.root / 'layer/tombstones' / (forgotten['id'] + '.json')).write_bytes(item_types._raw(tombstone))
        # A tombstone that only its backup holds, as a stopped write leaves it, hides its item too.
        (self.root / 'layer/tombstones' / (backed['id'] + '.json.bak')).write_bytes(item_types._raw(
            dict(tombstone, item=backed['id'])))
        (self.root / 'layer/state-removed.json').write_bytes(state_types.removed_bytes({'removed': [
            dict(id=removed['id'], at=AT, device=DEVICE, kind='edit')]}))
        self.pins(*(pin(value, AT) for value in (old, withdrawn, undone, forgotten, gone, backed)),
                  pin(new, AT, on=False), pin(kept, AT))
        part = self.start()
        self.assertEqual(part.pins, (kept['id'],))
        rows = self.memory_part(part).split('\n\n')
        self.assertEqual(rows[2], 'Pinned:\n- %s | decision | user decision | 2026-11-04 | Kept holds.' % kept['id'])
        self.assertEqual(rows[3], 'Current state:\n- Decision in force: Rests on the new decision. (%s)' % new['id'])

    def test_without_a_layer_or_its_files_or_after_the_projects_memory_was_deleted_memory_holds_nothing(self):
        item = self.item('Kept')
        self.layer([item], [line('goal', 1, 'A goal.', [item['id']])], pinned=[item['id']])
        (self.root / 'layer/deleted.json').write_bytes(b'{}\n')
        empty = '\n\n'.join(['## Memory', start_memory.REFERENCE, start_memory.NOTHING])
        self.assertEqual(self.memory_part(self.start()), empty)
        for name in ('deleted.json', 'state.json', 'state-removed.json', 'pins.json', 'conflicts.json'):
            (self.root / 'layer' / name).unlink()
        self.assertEqual(self.memory_part(self.start()), empty)
        for path in sorted((self.root / 'layer').rglob('*'), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        (self.root / 'layer').rmdir()
        self.assertEqual(self.memory_part(self.start()), empty)

    def test_a_long_current_state_leaves_the_base_whole_and_the_memory_part_within_4000_bytes(self):
        items = [self.item('Pinned %d' % n) for n in range(3)]
        lines = [line('next', n, 'Step %02d %s' % (n, 'x' * 480), [items[0]['id']]) for n in range(20)]
        self.layer(items, lines)
        self.pins(*(pin(value, '2026-11-0%dT00:00:00.000Z' % (n + 1)) for n, value in enumerate(items)))
        self.assertGreater(len((self.root / 'layer/state.json').read_bytes()), 10000)
        part = self.start()
        memory = self.memory_part(part)
        self.assertLessEqual(len(memory.encode('utf-8')), 4000)
        self.assertTrue(memory.endswith('Left out for room: 14 current state lines and 0 pinned items.'), memory)
        self.assertEqual(part.pins, tuple(value['id'] for value in items))

    def test_pins_left_out_for_room_are_not_logged_as_shown(self):
        items = [self.item('Pinned %02d' % n, text='Pinned item number %02d %s' % (n, 'y' * 200)) for n in range(20)]
        self.layer(items)
        self.pins(*(pin(value, '2026-11-04T00:00:%02d.000Z' % n) for n, value in enumerate(items)))
        part = self.start()
        memory = self.memory_part(part)
        shown = tuple(value['id'] for value in items if value['id'] in memory)
        self.assertTrue(memory.endswith('Left out for room: 0 current state lines and %d pinned items.' % (
            20 - len(shown))), memory)
        self.assertEqual(part.pins, shown)
        self.assertEqual(shown, tuple(value['id'] for value in items[20 - len(shown):]))   # the oldest pins go
        self.after(part)
        self.assertEqual(self.injections()[0]['items'], list(shown))

    # SPEC-022

    def test_tc199_the_anthropic_key_missing_names_its_variable_and_where_to_set_it(self):
        self.layer()
        del self.environment['CORTHEX_MEMORY_ANTHROPIC_API_KEY']
        wait = ("Curation is waiting for CORTHEX_MEMORY_ANTHROPIC_API_KEY, which the hook's environment does not "
                "have. Memory keys are read only from the environment that the host starts in, such as a shell "
                "profile or a cloud environment's secret settings.")
        part = self.start()
        self.assertEqual(self.notices(part), [wait])
        self.assertNotIn(self.environment['CORTHEX_MEMORY_OPENAI_API_KEY'], part.text)
        self.environment['CLAUDE_CODE_SUBPROCESS_ENV_SCRUB'] = '1'
        self.assertEqual(self.notices(self.start()), [
            wait + " Claude Code's CLAUDE_CODE_SUBPROCESS_ENV_SCRUB setting can remove it from hooks."])
        # A key set to nothing is missing too.
        self.environment.update(CLAUDE_CODE_SUBPROCESS_ENV_SCRUB='', CORTHEX_MEMORY_ANTHROPIC_API_KEY='')
        self.assertEqual(self.notices(self.start()), [wait])

    def test_tc200_the_openai_key_missing_and_both_keys_missing_in_the_tables_order(self):
        self.layer()
        recall = ("Recall and search by meaning are waiting for CORTHEX_MEMORY_OPENAI_API_KEY, which the hook's "
                  "environment does not have.")
        del self.environment['CORTHEX_MEMORY_OPENAI_API_KEY']
        self.assertEqual([row.split(' Memory keys')[0] for row in self.notices(self.start())], [recall])
        self.assertEqual([row.split(' Memory keys')[0] for row in self.notices(self.start(environment={}))], [
            "Curation is waiting for CORTHEX_MEMORY_ANTHROPIC_API_KEY, which the hook's environment does not "
            "have.", recall])

    def test_tc201_and_tc170_a_stop_and_the_turns_that_retention_deletes_within_seven_days(self):
        self.layer()
        self.progress(stopped={'at': AT, 'by': 'curate', 'errors': ['refusal']})
        for days, turn in ((92, 2), (94, 4), (95, 6)):
            self.marker(WHEN - timedelta(days=days), turn)
        self.marker(WHEN - timedelta(days=95, seconds=-1), 6)   # a second marker of one turn counts once
        self.assertEqual(self.notices(self.start()), [
            'Curation is stopped for this project after three failed attempts in a row (refusal). '
            'The memory status can resume it.',
            '2 turns are not curated yet and will be deleted on 2026-11-13 by the retention period, unless '
            'curation goes on before then.'])
        self.progress(stopped={'at': AT, 'by': 'consolidate', 'errors': ['timeout', 'refusal']})
        self.configure(retention={'days': 93})
        self.marker(WHEN - timedelta(days=101), 8)   # already past the period: deleted at this start
        self.assertEqual(self.notices(self.start()), [
            'Curation is stopped for this project after three failed attempts in a row (timeout, refusal). '
            'The memory status can resume it.',
            '4 turns are not curated yet and will be deleted on 2026-11-08 by the retention period, unless '
            'curation goes on before then.'])
        self.progress()
        self.configure()
        for path in (self.root / 'unprocessed').iterdir():
            path.unlink()
        self.marker(WHEN - timedelta(days=92), 2)
        self.assertEqual(self.notices(self.start()), [])

    def test_tc202_a_temporary_device_without_sync_says_so_at_every_start(self):
        self.layer()
        temporary = ('This is a temporary device and sync is off, so what memory records and curates here goes '
                     'with the device.')
        with mock.patch.dict(os.environ, {'CLAUDE_CODE_REMOTE': 'true'}):
            self.assertEqual(self.notices(self.start()), [temporary])
            self.assertEqual(self.notices(self.start()), [temporary])
            self.configure(temporary=False)
            self.assertEqual(self.notices(self.start()), [])
        self.configure(temporary=True)
        self.assertEqual(self.notices(self.start()), [temporary])

    def test_seven_conditions_show_five_notices_and_count_the_rest(self):
        self.layer()
        self.configure(consent=None, temporary=True)
        self.progress(stopped={'at': AT, 'by': 'curate', 'errors': ['refusal']})
        self.marker(WHEN - timedelta(days=95), 2)
        for name in ('curation-failed', 'consolidation-failed'):
            self.notice(name + '.json', kind=name, error='refusal')
        self.notice('rebuilt.json', kind='rebuilt')
        part = self.start()
        rows = self.notices(part)
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[1], start_memory.consent_notices(
            configuration.prepare({'projects': {}}, temporary=False))[0].text)
        self.assertEqual(rows[4:], ['Curation failed since the last session (refusal).',
                                    '2 more notices are in the memory status.'])
        # Only the stored notice that was shown goes; the two counted ones wait for the next start.
        self.assertEqual(self.after(part).deleted, 1)
        self.assertEqual(sorted(path.name for path in (self.root / 'notices').iterdir()),
                         ['consolidation-failed.json', 'rebuilt.json'])

    def test_tc203_stored_notices_are_shown_once_in_the_tables_order_and_each_start_logs_its_pins(self):
        old, new, kept = self.item('Old'), self.item('New'), self.item('Kept')
        self.layer([old, new, kept])
        self.pins(pin(kept, AT))
        self.notice('curation-failed.json', kind='curation-failed', error='refusal')
        self.notice('curation-failed.json', kind='curation-failed', error='timeout', at=STAMP_LATER)
        self.notice('consolidation-failed.json', kind='consolidation-failed', error='bad-answer')
        self.notice('rebuilt.json', kind='rebuilt')
        self.notice('pin-%s.json' % old['id'], kind='pin-moved', item=old['id'], to=new['id'])
        part = self.start()
        self.assertEqual(self.notices(part), [
            'Curation failed since the last session (timeout).',
            'Consolidation failed since the last session (bad-answer).',
            'The curation record was made again from the raw log, so some turns may be curated twice and '
            'merged later.',
            'The pinned item %s was superseded, so the pin moved to %s.' % (old['id'], new['id'])])
        self.assertEqual(self.after(part), start_summary.After(4, True, ()))
        self.assertEqual(sorted(path.name for path in (self.root / 'notices').iterdir()), [])
        second = self.start()
        self.assertEqual(self.notices(second), [])
        self.assertEqual(self.after(second), start_summary.After(0, True, ()))
        self.assertEqual(self.injections(), [
            {'at': worker_fixture.STAMP, 'session': SESSION, 'where': 'start', 'items': [kept['id']]}] * 2)

    def test_the_start_summary_lines_of_pins_that_an_undo_or_a_curation_moved(self):
        a, b, c, d = (self.item(name) for name in 'ABCD')
        self.layer([a, b, c, d])
        run = 'r_' + ident('i')[2:]
        self.notice('pin-%s.json' % a['id'], kind='pin-restored', item=a['id'], run=run)
        self.notice('pin-%s.json' % b['id'], kind='pin-removed', item=b['id'], run=run)
        self.notice('pin-%s.json' % c['id'], kind='pin-dropped', item=c['id'])
        # A notice that lacks what its line names, names another item or is damaged is skipped and kept.
        self.notice('pin-%s.json' % d['id'], kind='pin-moved', item=d['id'])
        skipped = self.notice('pin-%s.json' % ident('i'), kind='pin-dropped', item=d['id'])
        (self.root / 'notices/rebuilt.json').write_bytes(b'{"at": ')
        self.notice('curation-failed.json', kind='rebuilt')
        part = self.start()
        self.assertEqual(self.notices(part), [
            'The pinned item %s was withdrawn, so its pin was dropped.' % c['id'],
            'The pin returned to %s by undo %s.' % (a['id'], run),
            'The pin of %s was removed by undo %s.' % (b['id'], run)])
        self.assertEqual(self.after(part).deleted, 3)
        self.assertEqual(sorted(path.name for path in (self.root / 'notices').iterdir()), sorted([
            'pin-%s.json' % d['id'], skipped.name, 'rebuilt.json', 'curation-failed.json']))

    def test_a_notice_replaced_after_it_was_shown_stays_for_the_next_start(self):
        self.layer()
        self.notice('curation-failed.json', kind='curation-failed', error='refusal')
        part = self.start()
        self.assertEqual(self.notices(part), ['Curation failed since the last session (refusal).'])
        self.notice('curation-failed.json', kind='curation-failed', error='timeout', at=STAMP_LATER)
        self.assertEqual(self.after(part).deleted, 0)
        self.assertEqual(self.notices(self.start()), ['Curation failed since the last session (timeout).'])

    def test_step_7_deletes_notices_only_under_the_layer_lease_that_every_notice_writer_holds(self):
        self.layer()
        stored = self.notice('rebuilt.json', kind='rebuilt')
        part = self.start()
        self.assertEqual(part.shown, ((stored, stored.read_bytes()),))
        # A curation, consolidation, pin or undo holding the lease may write the notice again at any moment.
        release = self.holder(self.root / 'layer.lock', 'layer')
        started = time.monotonic()
        self.assertEqual(self.after(part), start_summary.After(0, True, ()))
        waited = time.monotonic() - started
        release()
        # It waited for the lease within the step's second, then left the notice for the next start.
        self.assertGreaterEqual(waited, start_summary.STEP_SECONDS * 0.8)
        self.assertLess(waited, 3)
        self.assertTrue(stored.exists())
        again = self.start()
        self.assertEqual(self.notices(again), [start_summary.REBUILT])
        self.assertEqual(self.after(again), start_summary.After(1, True, ()))
        self.assertFalse(stored.exists())
        self.assertFalse((self.root / 'layer.lock').exists())

    def test_a_failures_error_that_is_not_a_known_code_shows_as_runtimeerror(self):
        self.layer()
        self.notice('curation-failed.json', kind='curation-failed', error='Traceback: secret words')
        self.assertEqual(self.notices(self.start()), ['Curation failed since the last session (RuntimeError).'])

    # API-001 deadline and errors

    def test_tc204_a_late_memory_part_is_one_line_after_the_whole_base_and_deletes_nothing(self):
        item = self.item('Kept')
        self.layer([item], pinned=[item['id']])
        stored = self.notice('rebuilt.json', kind='rebuilt')
        layer = start_summary._layer

        def slow(*args):
            time.sleep(0.4)
            return layer(*args)
        with mock.patch.object(start_summary, '_layer', side_effect=slow):
            part = self.start(seconds=0.3)
        self.assertEqual((part.outcome, part.pins, part.shown), ('deadline', (), ()))
        self.assertEqual(part.text, BASE + '\n\n## Memory\n\nMemory could not be read in time.')
        # The start still takes its injection log line, with no pinned item shown, so that recall counts the
        # prompts again after it (SPEC-023).
        self.assertEqual(self.after(part), start_summary.After(0, True, ()))
        self.assertTrue(stored.exists())
        self.assertEqual(self.injections(), [
            {'at': worker_fixture.STAMP, 'session': SESSION, 'where': 'start', 'items': []}])

    def test_tc204_a_failing_memory_part_is_the_line_about_an_internal_error_and_deletes_nothing(self):
        self.layer()
        stored = self.notice('rebuilt.json', kind='rebuilt')
        error = RuntimeError('a stand-in failure')
        with mock.patch.object(start_summary, '_layer', side_effect=error):
            part = self.start()
        self.assertEqual((part.outcome, part.error), ('error', error))
        self.assertEqual(part.text, BASE + '\n\n## Memory\n\nMemory could not be read: an internal memory error '
                                           'occurred. The memory status says more.')
        self.assertEqual(self.after(part), start_summary.After(0, True, ()))
        self.assertTrue(stored.exists())
        self.assertEqual(self.injections(), [
            {'at': worker_fixture.STAMP, 'session': SESSION, 'where': 'start', 'items': []}])
        # A damaged layer file is such an error too, never a guess about which file.
        (self.root / 'layer/state.json').write_bytes(b'{"lines": [')
        self.assertEqual(self.start().outcome, 'error')

    def test_files_that_another_process_is_replacing_on_windows_are_read_again_within_the_deadline(self):
        item = self.item('Kept')
        self.layer([item], pinned=[item['id']])
        self.notice('rebuilt.json', kind='rebuilt')
        self.progress(stopped={'at': AT, 'by': 'curate', 'errors': ['refusal']})
        settings = self.memory.configuration(deadline=clock.now() + 10)
        read, refused = self.memory.fence.read, []

        def sharing(path, deadline):
            """Windows refuses the first read of each file, as while a worker's move replaces it."""
            if path not in refused:
                refused.append(path)
                raise PermissionError(13, 'The process cannot access the file', str(path))
            return read(path, deadline)
        with mock.patch.object(start_summary.files, '_WINDOWS', True), \
                mock.patch.object(self.memory.fence, 'read', side_effect=sharing):
            part = start_summary.compose(self.memory, 'sample', BASE, clock.now() + 5, settings=settings,
                                         environment=dict(self.environment), now=WHEN, zone=UTC)
        self.assertEqual(part.pins, (item['id'],))
        self.assertEqual(self.notices(part), [start_summary.STOPPED % 'refusal', start_summary.REBUILT])
        self.assertTrue({self.root / 'curation.json', self.root / 'notices/rebuilt.json',
                         self.root / 'layer/state.json', self.root / 'layer/pins.json',
                         self.root / 'layer/items' / (item['id'] + '.json')} <= set(refused), refused)

        # A file still being replaced when the deadline passes gives the line about the deadline, not an error.
        def replacing(path, deadline):
            if path.name == 'state.json':
                raise PermissionError(13, 'The process cannot access the file', str(path))
            return read(path, deadline)
        with mock.patch.object(start_summary.files, '_WINDOWS', True), \
                mock.patch.object(self.memory.fence, 'read', side_effect=replacing):
            part = start_summary.compose(self.memory, 'sample', BASE, clock.now() + 0.5, settings=settings,
                                         environment=dict(self.environment), now=WHEN, zone=UTC)
        self.assertEqual(part.outcome, 'deadline')

    def test_a_deadline_that_passes_while_the_unprocessed_turns_are_listed_ends_the_memory_part(self):
        self.layer()
        self.marker(WHEN - timedelta(days=92), 2)
        self.assertTrue(curation_triggers.turns(self.memory, self.root))
        with self.assertRaises(locks.LockBusy):
            curation_triggers.turns(self.memory, self.root, clock.now())
        with mock.patch.object(start_summary.curation_triggers, 'clock', mock.Mock(now=lambda: float('inf'))):
            part = self.start()
        self.assertEqual((part.outcome, part.shown), ('deadline', ()))

    # SPEC-143

    def candidate(self, at=AT, titles=('The first item', 'The second item')):
        newer, older = self.item(titles[0]), self.item(titles[1])
        value = dict(id='c_' + ident('i')[2:], items=[newer['id'], older['id']], at=at, run='r_' + ident('i')[2:],
                     by='curate', status='open')
        return value, newer, older

    def test_tc350_one_new_candidate_is_shown_by_three_starts_and_not_the_fourth(self):
        value, newer, older = self.candidate()
        self.layer([newer, older], candidates=[value])
        (self.root / 'notices' / conflict_counts.NAME).write_bytes(conflict_counts.counts_bytes({value['id']: 0}))
        conflicts = (self.root / 'layer/conflicts.json').read_bytes()
        line_text = ('Memory items %s ("The first item") and %s ("The second item") may disagree; neither '
                     'replaces the other until the user says which holds (1 open; the memory skill\'s conflicts '
                     'command lists them).' % (newer['id'], older['id']))
        shown = []
        for _ in range(4):
            part = self.start()
            shown.append((self.notices(part), part.reserved))
            self.after(part)
        self.assertEqual(shown, [([line_text], value['id'])] * 3 + [([], None)])
        self.assertEqual(self.counts(), {value['id']: 3})
        self.assertEqual((self.root / 'layer/conflicts.json').read_bytes(), conflicts)

    def test_a_candidate_without_a_count_or_with_an_item_no_longer_current_is_not_shown(self):
        value, newer, older = self.candidate()
        other, first, second = self.candidate(at='2026-11-05T03:00:00.000Z', titles=(
            'A title that runs on well past forty bytes', 'Ünïcödé títlè cút ät à bóúndàrý'))
        newer['status'] = 'withdrawn'
        self.layer([newer, older, first, second], candidates=[value, other])
        self.assertEqual(self.notices(self.start()), [])   # no counts file: every candidate counts as shown
        (self.root / 'notices' / conflict_counts.NAME).write_bytes(conflict_counts.counts_bytes(
            {value['id']: 0, other['id']: 0}))
        part = self.start()
        self.assertEqual(self.notices(part), [
            'Memory items %s ("A title that runs on well past forty ...") and %s ("Ünïcödé títlè cút ät à bóú...") '
            'may disagree; neither replaces the other until the user says which holds (2 open; the memory '
            "skill's conflicts command lists them)." % (first['id'], second['id'])])
        self.assertEqual(self.counts(), {value['id']: 0, other['id']: 1})

    def test_the_conflict_line_comes_after_the_pin_notices_of_a_curation_and_before_those_of_an_undo(self):
        value, newer, older = self.candidate()
        moved, restored = self.item('Moved'), self.item('Restored')
        self.layer([newer, older, moved, restored], candidates=[value])
        (self.root / 'notices' / conflict_counts.NAME).write_bytes(conflict_counts.counts_bytes({value['id']: 0}))
        run = 'r_' + ident('i')[2:]
        self.notice('pin-%s.json' % restored['id'], kind='pin-restored', item=restored['id'], run=run)
        self.notice('pin-%s.json' % moved['id'], kind='pin-moved', item=moved['id'], to=newer['id'])
        rows = self.notices(self.start())
        self.assertEqual(len(rows), 3)
        self.assertTrue(rows[0].startswith('The pinned item %s was superseded' % moved['id']), rows[0])
        self.assertTrue(rows[1].startswith('Memory items %s ("' % newer['id']), rows[1])
        self.assertEqual(rows[2], 'The pin returned to %s by undo %s.' % (restored['id'], run))

    def test_a_busy_counter_lease_leaves_the_line_out_and_counts_nothing(self):
        value, newer, older = self.candidate()
        self.layer([newer, older], candidates=[value])
        (self.root / 'notices' / conflict_counts.NAME).write_bytes(conflict_counts.counts_bytes({value['id']: 0}))
        release = self.holder(self.root / 'notices' / conflict_counts.LOCK, 'notice')
        started = time.monotonic()
        part = self.start()
        waited = time.monotonic() - started
        release()
        self.assertEqual((self.notices(part), part.reserved), ([], None))
        # It waited for the lease held elsewhere, briefly, rather than failing at once.
        self.assertGreaterEqual(waited, start_summary.RESERVE_SECONDS * 0.8)
        self.assertLess(waited, 3)
        self.assertEqual(self.counts(), {value['id']: 0})
        self.assertEqual(self.notices(self.start())[0][:12], 'Memory items')

    def test_a_conflict_line_that_does_not_fit_is_counted_and_not_reserved(self):
        value, newer, older = self.candidate()
        self.layer([newer, older], candidates=[value])
        (self.root / 'notices' / conflict_counts.NAME).write_bytes(conflict_counts.counts_bytes({value['id']: 0}))
        self.progress(stopped={'at': AT, 'by': 'curate', 'errors': ['refusal']})
        part = self.start(environment={})
        rows = self.notices(part)
        self.assertEqual((len(rows), rows[-1], part.reserved), (3, '2 more notices are in the memory status.', None))
        self.assertEqual(self.counts(), {value['id']: 0})

    def test_a_reserved_showing_goes_out_when_the_deadline_passes_while_the_summary_is_built(self):
        value, newer, older = self.candidate()
        self.layer([newer, older], candidates=[value])
        counts = self.root / 'notices' / conflict_counts.NAME
        counts.write_bytes(conflict_counts.counts_bytes({value['id']: 0}))
        build, now, late, pin = start_memory.build_summary, clock.now, [], self.memory.pin
        reserve = conflict_counts.reserve

        def start(replaced=False):
            def building(*args, **kwargs):
                late.append(True)   # from here on the clock reads a minute later: the deadline has passed
                if replaced:
                    self.memory.pin = 'another store'
                return build(*args, **kwargs)

            def reserving(memory, root, candidate, deadline):
                # The reservation may use the start's five seconds: this test is about a deadline that passes while
                # the summary is built, not about the reservation's quarter of a second, which a Windows runner with
                # Python 3.8 once took longer than, leaving the line out. The check after the build keeps its bound.
                return reserve(memory, root, candidate, clock.now() + 5)
            late.clear()
            try:
                with mock.patch.object(start_summary.start_memory, 'build_summary', side_effect=building), \
                        mock.patch.object(clock, 'now', side_effect=lambda: now() + (60 if late else 0)), \
                        mock.patch.object(conflict_counts, 'reserve', side_effect=reserving):
                    return self.start()
            finally:
                self.memory.pin = pin
        part = start()
        # The reservation used up a showing, so the summary goes out with its line.
        self.assertEqual((part.outcome, part.reserved, self.counts()), ('ok', value['id'], {value['id']: 1}))
        self.assertEqual(self.notices(part)[0][:12], 'Memory items')
        # The store is still checked: one replaced meanwhile gives the line about an internal error.
        part = start(replaced=True)
        self.assertEqual((part.outcome, type(part.error), self.counts()),
                         ('error', locks.LostLock, {value['id']: 2}))
        # Without a reservation, the same lateness gives the line about the deadline.
        counts.write_bytes(conflict_counts.counts_bytes({value['id']: 3}))
        self.assertEqual(start().outcome, 'deadline')

    # TBL-011

    def test_the_injection_log_line_waits_for_the_raw_log_lock_once_and_holds_no_text(self):
        item = self.item('Kept')
        self.layer([item], pinned=[item['id']])
        part = self.start()
        release = self.holder(self.root / 'raw' / (raw_log.log_name('claude-code', SESSION) + '.lock'), 'raw')
        started = time.monotonic()
        self.assertEqual(self.after(part), start_summary.After(0, False, ()))
        # One attempt and recording's 50 ms wait, not the append's one-second budget.
        self.assertLess(time.monotonic() - started, 0.5)
        release()
        self.assertEqual(self.injections(), [])
        self.assertEqual(self.after(part), start_summary.After(0, True, ()))
        data = next((self.root / 'injections').iterdir()).read_bytes()
        self.assertEqual(data, ('{"at":"%s","session":"%s","where":"start","items":["%s"]}\n' % (
            worker_fixture.STAMP, SESSION, item['id'])).encode('ascii'))
        self.assertNotIn(b'Kept', data)

    def test_injection_lines_are_checked_strictly(self):
        item, entry = ident('i'), ident('e')
        good = dict(at=AT, session=SESSION, where='prompt', prompt=entry, outcome='injected', items=[item],
                    scores=[0.5])
        self.assertEqual(injection_log.parse_line(injection_log.line_bytes(good)), good)
        for change in (dict(where='start'), dict(scores=[0.5, 0.4]), dict(scores=[float('nan')]),
                       dict(scores=[True]), dict(items=[item, item], scores=[1, 1]), dict(prompt=item),
                       dict(session=''), dict(session='s' * 201), dict(where='end'), dict(items=['i_x']),
                       dict(items=[[item]]), dict(items=[{'id': item}])):
            with self.subTest(change=change), self.assertRaises(ValueError):
                injection_log.line_bytes(dict(good, **change))
        with self.assertRaises(ValueError):
            injection_log.append(self.memory, 'sample', 'other-host', SESSION, 'start', [])


STAMP_LATER = '2026-11-06T03:00:00.000Z'

if __name__ == '__main__':
    unittest.main()
