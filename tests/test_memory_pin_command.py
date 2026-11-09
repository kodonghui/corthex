"""TASK-095: the pin and unpin commands (API-023, API-024; SPEC-034) on format-2 stores.

TC-229, TC-230 and TC-232. The runner parses both commands but hands them to
no handler before the 0.3.0 activation, which a test checks, so these tests
call the handlers as the runner will, after its gates, with the format-2 store
binding. The curations are real ones against the local test server of the
curation worker's tests, the forget and the undo are the commands' own,
confirmed with their codes, and the start summary is the module that the
session start hook will call (TASK-091); no provider is called.
"""
import os
import sys
import tempfile
import time
import types
import unittest
from datetime import timezone
from pathlib import Path
from unittest import mock

from _common import ROOT, load_json
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import (base, clock, commands, fence_plan, files, forget_plan, item_types, pin_command, run_listing,
                        run_log, start_memory, start_summary, worker_support)
from test_memory_curator_answers import answer, change, quote
import test_memory_commands as commands_fixture
import test_memory_conflicts_command as conflicts_fixture
import test_memory_curation_worker as worker_fixture
import test_memory_start_summary as start_fixture

AT, DEVICE, WHEN, STAMP = worker_fixture.AT, worker_fixture.DEVICE, worker_fixture.WHEN, worker_fixture.STAMP
BASE, SESSION = start_fixture.BASE, start_fixture.SESSION
# Before the curations of these tests, which apply at STAMP, and after them.
PINNED, AGAIN = '2026-11-08T08:00:00.000Z', '2026-11-08T08:10:00.000Z'
UNPINNED, LAST = '2026-11-08T10:00:00.000Z', '2026-11-08T10:10:00.000Z'
SAY = pin_command.SAY
MADE_UP = 'i_7f3k2m9q4x1w'


def minute(number):
    return '2026-11-08T08:%02d:00.000Z' % number


def memory_bytes(values):
    """The memory part with only these pinned items, unshortened, as SPEC-021 lays it out."""
    rows = [start_memory.item_line(value) for value in values]
    part = '\n\n'.join(['## Memory', start_memory.REFERENCE, 'Pinned:\n' + '\n'.join(rows)])
    return len(part.encode('utf-8'))


class PinStore(conflicts_fixture.ConflictsStore):
    """A format-2 project with one recorded turn, and the pin commands run as the runner will run them."""

    def context(self, command, item, project='sample', memory=None):
        context = commands.Context(command, {'folder': str(self.root), 'item': item}, None, memory or self.memory)
        context.project = types.SimpleNamespace(name=project)
        context.record = {'device': DEVICE}
        return context

    def pin(self, item, at=PINNED, base_text=BASE, **options):
        value = pin_command.pin(self.context('pin', item, **options), at=at, base_text=base_text)
        commands.validate_result(value, 'pin')
        return value

    def unpin(self, item, at=UNPINNED, **options):
        value = pin_command.unpin(self.context('unpin', item, **options), at=at)
        commands.validate_result(value, 'unpin')
        return value

    def pins(self):
        return item_types.parse_pins((self.root / 'layer/pins.json').read_bytes())['pins']

    def record(self, value, at, on=True):
        return {'item': value['id'], 'on': on, 'at': at, 'device': DEVICE}

    def long(self, number):
        """A current decision whose line in the start summary takes its most: its text is cut at 300 bytes."""
        value = self.item('Pinned decision %02d' % number)
        value['text'] = 'Pinned decision %02d holds. ' % number + 'It keeps a long reason for the start summary. ' * 9
        return value

    def compose(self, base_text=BASE):
        """A session start's composed summary, then its step 7."""
        settings = self.memory.configuration(deadline=clock.now() + 10)
        part = start_summary.compose(self.memory, 'sample', base_text, clock.now() + 5, settings=settings,
                                     environment=self.environment, now=WHEN, zone=timezone.utc)
        self.assertEqual(part.outcome, 'ok')
        start_summary.after(self.memory, 'sample', part, 'claude-code', SESSION, when=WHEN)
        return part


class PinCommandTest(PinStore, unittest.TestCase):
    # TC-232

    def test_tc232_pins_again_and_pins_of_wrong_items(self):
        older, value = self.item('Keep one script'), self.item('Keep one script for the four hooks')
        older.update(status='superseded', superseded_by=value['id'])
        self.fixture.layer(items=[older, value])
        progress = self.fixture.progress()
        first = self.pin(value['id'])
        self.assertEqual((first['outcome'], first['code'], first['say']), ('done', 'ok', SAY['pinned'] % value['id']))
        # What the user reads: the pin shows from the next session's start summary.
        self.assertEqual(first['say'], 'Pinned %s; the start summary shows it from the next session.' % value['id'])
        self.assertEqual(first['data'], {'project': 'sample', 'item': value['id'], 'pins': [value['id']]})
        self.assertEqual(self.pins(), [self.record(value, PINNED)])
        fence = self.fixture.progress()['fence']
        self.assertEqual(fence['generation'], progress['fence']['generation'] + 1)
        self.assertEqual(fence['revisions'], {'pin:' + value['id']: fence['generation']})
        before = self.tree()
        second = self.pin(value['id'], at=AGAIN)
        self.assertEqual((second['outcome'], second['code'], second['say']),
                         ('nothing', 'ok', SAY['already'] % value['id']))
        self.assertEqual(second['data'], first['data'])
        self.assertEqual(self.tree(), before)
        third = self.unpin(value['id'])
        self.assertEqual((third['outcome'], third['code'], third['say']),
                         ('done', 'ok', SAY['unpinned'] % value['id']))
        self.assertEqual(third['say'], 'Unpinned %s; the start summary no longer shows it.' % value['id'])
        self.assertEqual(third['data'], {'project': 'sample', 'item': value['id'], 'pins': []})
        # The record stays after the unpin, with the unpin's time (TBL-014).
        self.assertEqual(self.pins(), [self.record(value, UNPINNED, on=False)])
        self.assertEqual(self.fixture.progress()['fence']['revisions'], {'pin:' + value['id']: fence['generation'] + 1})
        before = self.tree()
        fourth = self.unpin(value['id'], at=LAST)
        self.assertEqual((fourth['outcome'], fourth['code'], fourth['say']),
                         ('nothing', 'ok', SAY['not-pinned'] % value['id']))
        self.assertEqual(fourth['data'], third['data'])
        superseded = self.pin(older['id'])
        self.assertEqual((superseded['outcome'], superseded['code'], superseded['say']),
                         ('refused', 'item-not-current', SAY['superseded'] % (older['id'], value['id'])))
        self.assertEqual(superseded['data'], {'project': 'sample', 'item': older['id'], 'current': value['id']})
        lines = [run_listing.list_line(value)]
        for command in (self.pin, self.unpin):
            with self.subTest(command=command.__name__):
                made_up = command(MADE_UP)
                self.assertEqual((made_up['outcome'], made_up['code'], made_up['say']),
                                 ('refused', 'item-not-found',
                                  'No item %s in sample. The closest is %s.' % (MADE_UP, value['id'])))
                self.assertEqual(made_up['data'], {'project': 'sample', 'item': MADE_UP, 'matches': lines})
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.memory.held, [])
        # A pin again after the unpin is a new pin with its own time, in the record's place.
        self.assertEqual(self.pin(value['id'], at=LAST)['code'], 'ok')
        self.assertEqual(self.pins(), [self.record(value, LAST)])

    def test_a_pin_again_goes_last_in_the_pin_order_while_its_record_keeps_its_place(self):
        first, second = self.item('First'), self.item('Second')
        self.fixture.layer(items=[first, second])
        self.pin(first['id'], at=minute(1))
        self.assertEqual(self.pin(second['id'], at=minute(2))['data']['pins'], [first['id'], second['id']])
        self.unpin(first['id'], at=minute(3))
        again = self.pin(first['id'], at=minute(4))
        # The start summary shows the pinned items in the order they were pinned (TBL-014).
        self.assertEqual(again['data']['pins'], [second['id'], first['id']])
        self.assertEqual(self.pins(), [self.record(first, minute(4)), self.record(second, minute(2))])
        self.assertEqual(self.compose().pins, (second['id'], first['id']))

    def test_pins_that_do_not_read_back_as_written_fail_after_the_revision_is_reserved(self):
        value = self.item('Pinned')
        self.fixture.layer(items=[value])
        before, progress = self.pins(), self.fixture.progress()
        write = files.replace_bytes

        def lost(path, data, *rest, **options):
            # The curation record's reservation is written; the pins' write is lost.
            if Path(path).name != 'pins.json':
                write(path, data, *rest, **options)
        with mock.patch.object(pin_command.files, 'replace_bytes', lost):
            with self.assertRaisesRegex(RuntimeError, 'the pins did not read back'):
                self.pin(value['id'])
        self.assertEqual(self.pins(), before)
        # The reservation stays, so a request or an undo planned before it is stale all the same.
        self.assertEqual(self.fixture.progress()['fence']['revisions'],
                         {'pin:' + value['id']: progress['fence']['generation'] + 1})
        self.assertEqual(self.memory.held, [])
        self.assertEqual(self.pin(value['id'])['data']['pins'], [value['id']])

    def test_a_reservation_that_fails_leaves_the_pins_as_they_were(self):
        value = self.item('Pinned')
        self.fixture.layer(items=[value])
        before = self.tree()
        # The revision is reserved before the pins are written, so a reservation that fails writes nothing.
        with mock.patch.object(pin_command.revision_io, 'reserve', side_effect=fence_plan.Stale()):
            with self.assertRaises(fence_plan.Stale):
                self.pin(value['id'])
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.memory.held, [])

    def test_the_documented_examples_fit_the_results(self):
        examples = load_json(ROOT / 'docs/06-api/memory-examples.json')['result']['valid']
        for name in ('pin-no-room', 'pin-not-found', 'pin-superseded'):
            with self.subTest(name):
                commands.validate_result(examples[name], 'pin')
        # The example's sentence is the command's.
        self.assertEqual(examples['pin-no-room']['say'], SAY['no-room'])
        self.assertEqual(examples['pin-superseded']['say'],
                         SAY['superseded'] % (examples['pin-superseded']['data']['item'],
                                              examples['pin-superseded']['data']['current']))

    def test_an_item_that_is_not_current_offers_the_current_item_at_the_end_of_its_replacements(self):
        values = {name: self.item(name.capitalize()) for name in (
            'first', 'second', 'third', 'ended', 'withdrawn', 'undone', 'gone', 'forgotten', 'lost', 'loop', 'back')}
        chain = (('first', 'second'), ('second', 'third'), ('ended', 'withdrawn'), ('gone', 'forgotten'),
                 ('lost', None), ('loop', 'back'), ('back', 'loop'))
        for name, after in chain:
            values[name].update(status='superseded',
                                superseded_by=after and values[after]['id'] or 'i_' + '0' * 12)
        values['withdrawn']['status'] = 'withdrawn'
        values['undone'].update(status='undone', undone_by='r_0123456789ab')
        self.fixture.layer(items=values.values())
        self.tombstone(values['forgotten'])
        before = self.tree()
        expected = {
            'first': (SAY['replaced'] % (values['first']['id'], values['third']['id']), values['third']['id']),
            'second': (SAY['superseded'] % (values['second']['id'], values['third']['id']), values['third']['id']),
            'ended': (SAY['superseded-only'] % values['ended']['id'], None),
            'withdrawn': (SAY['withdrawn'] % values['withdrawn']['id'], None),
            'undone': (SAY['undone-by'] % (values['undone']['id'], 'r_0123456789ab'), None),
            'gone': (SAY['superseded-only'] % values['gone']['id'], None),
            'lost': (SAY['superseded-only'] % values['lost']['id'], None),
            'loop': (SAY['superseded-only'] % values['loop']['id'], None),
        }
        for name, (say, current) in expected.items():
            with self.subTest(name):
                value = self.pin(values[name]['id'])
                self.assertEqual((value['outcome'], value['code'], value['say']), ('refused', 'item-not-current', say))
                data = {'project': 'sample', 'item': values[name]['id']}
                if current:
                    data['current'] = current
                self.assertEqual(value['data'], data)
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.pin(values['third']['id'])['code'], 'ok')
        # An undone item without the run that undid it says only that.
        del values['undone']['undone_by']
        (self.root / 'layer/items' / (values['undone']['id'] + '.json')).write_bytes(
            item_types.item_bytes(values['undone']))
        self.assertEqual(self.pin(values['undone']['id'])['say'], SAY['undone'] % values['undone']['id'])

    def tombstone(self, value):
        cited = value['quotes'][0]
        stone = dict(item=value['id'], project='sample', at=AT, device=DEVICE,
                     quotes=[{name: cited[name] for name in ('device', 'entry', 'log', 'start', 'end')}])
        (self.root / 'layer/tombstones' / (value['id'] + '.json')).write_bytes(item_types._raw(stone) + b'\n')

    def test_unpin_takes_an_item_of_any_status_and_a_forgotten_or_other_projects_item_is_not_found(self):
        stale, moved, other = self.item('Withdrawn but pinned'), self.item('Moved'), self.item('Elsewhere')
        current, forgotten = self.item('Current'), self.item('Forgotten')
        stale['status'] = 'withdrawn'
        moved.update(status='superseded', superseded_by=current['id'])
        self.fixture.layer(items=[stale, moved, current, forgotten])
        (self.root / 'layer/pins.json').write_bytes(item_types.pins_bytes({'pins': [
            self.record(stale, AT), self.record(moved, STAMP, on=False), self.record(current, STAMP),
            self.record(forgotten, AT)]}))
        self.tombstone(forgotten)
        elsewhere = self.fixture.folder / 'projects/other/layer/items'
        elsewhere.mkdir(parents=True)
        (elsewhere / (other['id'] + '.json')).write_bytes(item_types.item_bytes(other))
        # A pin left on an item that is no longer current is not shown, and an unpin turns it off.
        self.assertEqual(self.pin(current['id'])['data']['pins'], [current['id']])
        value = self.unpin(stale['id'])
        self.assertEqual((value['outcome'], value['code'], value['data']['pins']), ('done', 'ok', [current['id']]))
        self.assertEqual(self.pins()[0], self.record(stale, UNPINNED, on=False))
        before = self.tree()
        value = self.unpin(moved['id'])
        self.assertEqual((value['outcome'], value['say'], value['data']['pins']),
                         ('nothing', SAY['not-pinned'] % moved['id'], [current['id']]))
        for name in (forgotten['id'], other['id'], '../other/layer/items/' + other['id'], 'Current'):
            for command in (self.pin, self.unpin):
                with self.subTest(name=name, command=command.__name__):
                    value = command(name)
                    self.assertEqual((value['outcome'], value['code']), ('refused', 'item-not-found'))
                    self.assertEqual(value['data']['matches'][0], run_listing.list_line(current))
        self.assertEqual(self.tree(), before)

    # TC-230

    def test_tc230_a_pin_that_would_take_the_memory_part_past_4000_bytes_is_refused_with_the_pins(self):
        values = [self.long(number) for number in range(14)]
        self.fixture.layer(items=values)
        pinned = []
        for number, value in enumerate(values):
            answer_ = self.pin(value['id'], at=minute(number))
            if answer_['code'] != 'ok':
                break
            pinned.append(value)
            self.assertLessEqual(memory_bytes(pinned), start_memory.MEMORY_BYTES)
        self.assertGreater(len(pinned), 5)
        refused = values[len(pinned)]
        self.assertGreater(memory_bytes(pinned + [refused]), start_memory.MEMORY_BYTES)
        self.assertEqual((answer_['outcome'], answer_['code'], answer_['say']),
                         ('refused', 'pin-no-room', SAY['no-room']))
        ids = [value['id'] for value in pinned]
        self.assertEqual(answer_['data'], {'project': 'sample', 'item': refused['id'], 'pins': ids})
        self.assertEqual([pin['item'] for pin in self.pins()], ids)
        # The next start shows every pin, oldest first, and its memory part stays within 4,000 bytes.
        part = self.compose()
        self.assertEqual(part.pins, tuple(ids))
        memory = part.text[len(BASE) + 2:]
        self.assertLessEqual(len(memory.encode('utf-8')), start_memory.MEMORY_BYTES)
        self.assertNotIn('Left out for room', memory)
        self.assertEqual([row.split(' | ')[0][2:] for row in memory.split('Pinned:\n')[1].splitlines()], ids)
        # With the oldest pin gone the refused item fits.
        self.assertEqual(self.unpin(ids[0])['data']['pins'], ids[1:])
        self.assertEqual(self.pin(refused['id'], at=UNPINNED)['data']['pins'], ids[1:] + [refused['id']])

    def test_a_base_that_leaves_less_room_refuses_a_pin_sooner(self):
        values = [self.long(number) for number in range(4)]
        self.fixture.layer(items=values)
        # The whole start summary stays under 8,000 bytes (FL-008, REQ-030): a base that leaves room for two long pins.
        room = (memory_bytes(values[:2]) + memory_bytes(values[:3])) // 2
        large = BASE + '\n\n' + ('The base is large. ' * 400)[:start_memory.SUMMARY_BYTES - 2 - room - len(BASE) - 2]
        self.assertEqual(start_memory.SUMMARY_BYTES - len(large.encode('utf-8')) - 2, room)
        self.assertLess(memory_bytes(values[:2]), room)
        self.assertGreater(memory_bytes(values[:3]), room)
        found = [self.pin(value['id'], at=minute(number), base_text=large) for number, value in enumerate(values[:3])]
        self.assertEqual([value['code'] for value in found], ['ok', 'ok', 'pin-no-room'])
        self.assertEqual(found[2]['data']['pins'], [values[0]['id'], values[1]['id']])
        summary = start_memory.build_summary(large, (), values[:2], ())
        self.assertEqual(summary.pins, (values[0]['id'], values[1]['id']))
        self.assertLess(len(summary.text.encode('utf-8')), 8000)
        # With the small base the third fits.
        self.assertEqual(self.pin(values[2]['id'], at=minute(2))['code'], 'ok')
        # A base that leaves no room for any pinned item says so.
        for value in values[:3]:
            self.unpin(value['id'])
        before = self.tree()
        full = BASE + '\n\n' + 'The base fills it. ' * 410
        value = self.pin(values[3]['id'], base_text=full)
        self.assertEqual((value['outcome'], value['code'], value['say'], value['data']['pins']),
                         ('refused', 'pin-no-room', SAY['base'], []))
        self.assertEqual(self.tree(), before)

    def test_the_line_that_says_how_many_state_lines_the_start_cuts_takes_room_too(self):
        values = [self.long(number) for number in range(2)]
        goal = start_fixture.line('goal', 0, 'Keep the pinned items in the start summary.', [self.said['id']])
        self.fixture.layer(items=values, lines=[goal])
        # A base that leaves room for both long pins, but not for them and the line that says the goal was cut.
        room = memory_bytes(values) + 30
        large = BASE + '\n\n' + ('The base is large. ' * 400)[:start_memory.SUMMARY_BYTES - 2 - room - len(BASE) - 2]
        self.assertEqual(start_memory.SUMMARY_BYTES - len(large.encode('utf-8')) - 2, room)
        self.assertEqual(start_memory.build_summary(large, (), values, ()).pins, tuple(v['id'] for v in values))
        cut = start_memory.build_summary(large, (), values, [goal])
        self.assertEqual(cut.pins, (values[1]['id'],))
        self.assertIn('Left out for room: 1 current state lines and 1 pinned items.', cut.text)
        found = [self.pin(value['id'], at=minute(number), base_text=large) for number, value in enumerate(values)]
        self.assertEqual([value['code'] for value in found], ['ok', 'pin-no-room'])
        self.assertEqual((found[1]['say'], found[1]['data']['pins']), (SAY['no-room'], [values[0]['id']]))
        self.assertEqual([pin['item'] for pin in self.pins()], [values[0]['id']])
        # The start that the first pin left shows it with the goal.
        shown = start_memory.build_summary(large, (), values[:1], [goal])
        self.assertEqual(shown.pins, (values[0]['id'],))
        self.assertNotIn('Left out for room', shown.text)

    def test_a_base_that_leaves_no_room_for_the_item_alone_says_so_while_other_items_are_pinned(self):
        values = [self.long(number) for number in range(2)]
        self.fixture.layer(items=values)
        self.assertEqual(self.pin(values[0]['id'])['code'], 'ok')
        full = BASE + '\n\n' + 'The base fills it. ' * 410
        before = self.tree()
        value = self.pin(values[1]['id'], at=AGAIN, base_text=full)
        self.assertEqual((value['outcome'], value['code'], value['say'], value['data']['pins']),
                         ('refused', 'pin-no-room', SAY['base'], [values[0]['id']]))
        self.assertEqual(self.tree(), before)

    def test_notices_are_not_counted_and_a_start_that_shows_them_leaves_the_oldest_pin_out(self):
        values = [self.long(number) for number in range(14)]
        self.fixture.layer(items=values)
        pinned = []
        for number, value in enumerate(values):
            if self.pin(value['id'], at=minute(number))['code'] != 'ok':
                break
            pinned.append(value)
        ids = tuple(value['id'] for value in pinned)
        self.assertEqual(self.pin(values[len(pinned)]['id'])['code'], 'pin-no-room')
        # Pins dropped elsewhere leave notices for the next start only, which the pins did not count.
        notices = []
        for value in values[-3:]:
            path = self.root / 'notices' / ('pin-%s.json' % value['id'])
            path.write_bytes(item_types.notice_bytes({'at': STAMP, 'kind': 'pin-dropped', 'item': value['id']}))
            notices.append(start_memory.Notice('pin-dropped', start_summary.DROPPED % value['id']))
        notice_bytes = len(start_memory.notice_part(notices).encode('utf-8'))
        self.assertGreater(memory_bytes(pinned) + 2 + notice_bytes, start_memory.MEMORY_BYTES)
        first = self.compose()
        for notice in notices:
            self.assertIn(notice.text, first.text)
        self.assertEqual(first.pins, ids[1:])
        self.assertIn('Left out for room: 0 current state lines and 1 pinned items.', first.text)
        self.assertEqual(self.compose().pins, ids)

    def test_the_base_is_the_one_that_the_start_hook_builds_for_the_folder(self):
        value = self.item('Pinned')
        self.fixture.layer(items=[value])
        calls = []

        def build(folder, home, limit=8000):
            calls.append((folder, home, limit))
            return 'A base that takes the room. ' * 285
        with mock.patch.object(pin_command.start_context, 'build_context', build):
            refused = pin_command.pin(self.context('pin', value['id']), at=PINNED)
        self.assertEqual(calls, [(self.root, Path.home(), None)])
        self.assertEqual((refused['code'], refused['say'], refused['data']['pins']), ('pin-no-room', SAY['base'], []))
        # With the base that the start hook would build and the command's own time.
        earlier = base.utc_time()
        with tempfile.TemporaryDirectory() as home:
            with mock.patch.dict(os.environ, {'HOME': home, 'USERPROFILE': home}):
                done = pin_command.pin(self.context('pin', value['id']))
        self.assertEqual((done['outcome'], done['code'], done['data']['pins']), ('done', 'ok', [value['id']]))
        (record,) = self.pins()
        self.assertTrue(earlier <= record['at'] <= base.utc_time())
        self.assertEqual(record, self.record(value, record['at']))

    # TC-229

    def test_tc229_a_pin_moves_with_its_item_and_the_next_start_says_so_once(self):
        value = self.item('Keep the four hooks in one script', words='Keep the four hooks in one script')
        self.fixture.layer(items=[value])
        self.assertEqual(self.pin(value['id'])['data']['pins'], [value['id']])
        run = self.curate('Keep the four hooks in two scripts instead.', lambda said: answer(change(
            quote(said, 'Keep the four hooks in two scripts'), action='replace', targets=[value['id']],
            kind='decision', title='Two scripts')))
        (new,) = run_log.read(self.root, run)['saved']
        items = self.fixture.items()
        self.assertEqual((items[value['id']]['status'], items[value['id']]['superseded_by']), ('superseded', new))
        # The curation turned the pin off and pinned the item that superseded it, at the same time.
        self.assertEqual(self.pins(), [dict(self.record(value, STAMP, on=False)),
                                       {'item': new, 'on': True, 'at': STAMP, 'device': DEVICE}])
        moved = start_summary.MOVED % (value['id'], new)
        first, second = self.compose(), self.compose()
        self.assertEqual(first.text.count(moved), 1)
        self.assertEqual((first.pins, second.pins), ((new,), (new,)))
        self.assertNotIn(moved, second.text)
        self.assertFalse((self.root / 'notices' / ('pin-%s.json' % value['id'])).exists())
        # The commands see the moved pin.
        self.assertEqual(self.pin(new)['say'], SAY['already'] % new)
        self.assertEqual(self.unpin(value['id'])['say'], SAY['not-pinned'] % value['id'])
        again = self.pin(value['id'])
        self.assertEqual((again['code'], again['data']['current']), ('item-not-current', new))

    def test_a_withdrawn_or_forgotten_item_loses_the_pin_that_the_command_made(self):
        ended = self.item('Keep the raw logs here', words='keep the raw logs on this device')
        gone = self.item('One script', words='Keep the four hooks in one script')
        self.fixture.layer(items=[ended, gone])
        self.pin(ended['id'], at=minute(1))
        self.pin(gone['id'], at=minute(2))
        self.curate('The raw logs no longer stay on this device.', lambda said: answer(change(
            quote(said, 'The raw logs no longer stay on this device'), action='withdraw', targets=[ended['id']],
            kind='decision')))
        self.assertEqual(self.pins()[0], self.record(ended, STAMP, on=False))
        dropped = start_summary.DROPPED % ended['id']
        first = self.compose()
        self.assertEqual((first.text.count(dropped), first.pins), (1, (gone['id'],)))
        self.assertNotIn(dropped, self.compose().text)
        value = self.pin(ended['id'])
        self.assertEqual((value['code'], value['say']), ('item-not-current', SAY['withdrawn'] % ended['id']))
        preview, done = self.forget(gone['id'])
        self.assertEqual(preview['data']['pinned'], [gone['id']])
        self.assertEqual([pin['item'] for pin in self.pins()], [ended['id']])
        for command in (self.pin, self.unpin):
            with self.subTest(command=command.__name__):
                self.assertEqual(command(gone['id'])['code'], 'item-not-found')
        self.assertEqual(self.compose().pins, ())

    def test_an_undo_of_an_earlier_run_keeps_a_pin_that_the_user_changed_after_it(self):
        value = self.item('Keep the four hooks in one script', words='Keep the four hooks in one script')
        self.fixture.layer(items=[value])
        self.pin(value['id'])
        run = self.curate('Keep the four hooks in two scripts instead.', lambda said: answer(change(
            quote(said, 'Keep the four hooks in two scripts'), action='replace', targets=[value['id']],
            kind='decision', title='Two scripts')))
        (new,) = run_log.read(self.root, run)['saved']
        self.assertEqual(self.unpin(new)['data']['pins'], [])
        before = self.tree()
        # The unpin is a later change of the pin that the run moved, so the run's item and pin changes stay together.
        preview = self.command(run)
        self.assertEqual((preview['outcome'], preview['code']), ('nothing', 'ok'))
        kept = [{'target': 'pin:' + new, 'by': '', 'why': 'later-unlogged-change'}] + [
            {'target': target, 'by': '', 'why': 'later-dependent-change'}
            for target in ('item:' + new, 'item:' + value['id'], 'pin:' + value['id'])]
        self.assertEqual(preview['data']['kept'], sorted(kept, key=lambda entry: entry['target']))
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.compose().pins, ())

    def test_a_pin_makes_a_request_or_confirmation_planned_before_it_stale(self):
        first, second = self.item('First'), self.item('Second')
        self.fixture.layer(items=[first, second])
        progress = self.fixture.progress()
        self.pin(first['id'])
        after = self.fixture.progress()
        self.assertFalse(fence_plan.matches(after, fence_plan.snapshot(progress)))
        self.unpin(first['id'])
        self.pin(second['id'], at=AGAIN)
        fence = self.fixture.progress()['fence']
        self.assertEqual(fence['generation'], progress['fence']['generation'] + 3)
        self.assertEqual(fence['revisions'], {'pin:' + first['id']: fence['generation'] - 1,
                                              'pin:' + second['id']: fence['generation']})
        # Only the pins and the curation record's fence changed: no item, line, list, notice or run.
        self.assertEqual(after['applies'], progress['applies'])

    def test_a_busy_layer_lease_answers_lock_busy_and_changes_nothing(self):
        value = self.item('Pinned')
        self.fixture.layer(items=[value])
        before = self.tree()
        with self.held('layer.lock', 'layer'), mock.patch.object(pin_command, 'WAIT', 0.2):
            for command in (self.pin, self.unpin):
                with self.subTest(command=command.__name__):
                    started = time.monotonic()
                    found = command(value['id'])
                    self.assertEqual((found['outcome'], found['code']), ('failed', 'lock-busy'))
                    # The commands' wait, not the whole command's bound of 60 seconds.
                    self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.memory.held, [])

    def test_a_project_without_a_folder_or_being_deleted_has_no_items(self):
        value = self.item('Pinned')
        self.fixture.layer(items=[value])
        # A copy of the project's tombstone already counts, as the memory worker counts it (TBL-017).
        for name, path in (('no folder', None), ('a copy of its tombstone', 'layer/deleted.json.0123456789abcdef.tmp'),
                           ('being deleted', 'layer/deleted.json')):
            with self.subTest(name):
                project = 'missing' if path is None else 'sample'
                if path is not None:
                    (self.root / path).write_bytes(b'{}\n')
                before = self.tree()
                for command in (self.pin, self.unpin):
                    found = command(value['id'], project=project)
                    self.assertEqual((found['outcome'], found['code'], found['data']),
                                     ('refused', 'item-not-found',
                                      {'project': project, 'item': value['id'], 'matches': []}))
                    self.assertEqual(found['say'], 'No item %s in %s.' % (value['id'], project))
                self.assertEqual(self.tree(), before)
                if path is not None:
                    (self.root / path).unlink()

    def test_an_argument_outside_the_result_schema_is_usage(self):
        before = self.tree()
        for name in ('', 'i' * 201, None, 7, ['i_7f3k2m9q4x1v']):
            for command in (self.pin, self.unpin):
                with self.subTest(name=name, command=command.__name__):
                    self.assertEqual(command(name)['code'], 'usage')
        self.assertEqual(self.tree(), before)

    def test_the_closest_lines_name_up_to_five_items(self):
        values = [self.item('Decision %d' % number) for number in range(7)]
        self.fixture.layer(items=values)
        # The item list's order: one date, so by ID. The title of its last line comes first among the closest.
        lines = sorted((run_listing.list_line(item) for item in values), key=lambda line: line['item'])
        name = lines[-1]['title']
        value = self.pin(name)
        matches = forget_plan.closest(lines, [name])
        self.assertEqual(matches[0], lines[-1])
        self.assertEqual(value['data']['matches'], matches)
        found = [line['item'] for line in matches]
        self.assertEqual(len(found), 5)
        self.assertEqual(value['say'], 'No item %s in sample. The closest are %s and %s.'
                         % (name, ', '.join(found[:-1]), found[-1]))

    def test_pins_that_cannot_be_read_or_that_a_link_reaches_raise_and_change_nothing(self):
        value = self.item('Pinned')
        self.fixture.layer(items=[value])
        path = self.root / 'layer/pins.json'
        good = path.read_bytes()
        for name, damage in (('damaged', b'{"pins": ['), ('missing', None)):
            with self.subTest(name):
                if damage is None:
                    path.unlink()
                else:
                    path.write_bytes(damage)
                before = self.tree()
                with self.assertRaises(files.RestoreNeeded):
                    pin_command.pin(self.context('pin', value['id']), at=PINNED, base_text=BASE)
                self.assertEqual(self.tree(), before)
                path.write_bytes(good)
        # Another pinned item's record that cannot be read fails an unpin before the revision or the pins change.
        other = self.item('Also pinned')
        self.fixture.layer(items=[value, other], pinned=[value['id'], other['id']])
        record = self.root / 'layer/items' / (other['id'] + '.json')
        record.write_bytes(b'{"id": ')
        before = self.tree()
        with self.assertRaises(files.RestoreNeeded):
            pin_command.unpin(self.context('unpin', value['id']), at=UNPINNED)
        self.assertEqual(self.tree(), before)
        record.write_bytes(item_types.item_bytes(other))
        path.write_bytes(good)
        target = self.fixture.folder / 'elsewhere.json'
        target.write_bytes(good)
        path.unlink()
        if not self.link(path, target):
            self.skipTest('this system does not let the test make a symbolic link')
        before = self.tree()
        with self.assertRaises(worker_support.UnsafePath):
            pin_command.unpin(self.context('unpin', value['id']), at=UNPINNED)
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.memory.held, [])


class PinRunnerTest(unittest.TestCase):
    reset_store, snapshot = commands_fixture.CommandsTest.reset_store, commands_fixture.CommandsTest.snapshot

    def setUp(self):
        commands_fixture.CommandsTest.setUp(self)

    def test_the_runner_answers_pin_and_unpin_as_not_implemented(self):
        before = self.snapshot()
        for argv in (['pin', 'i_7f3k2m9q4x1v'], ['unpin', 'i_7f3k2m9q4x1v']):
            with self.subTest(argv=argv):
                value, status = commands.run(['--folder', str(self.project)] + argv)
                self.assertEqual((value['command'], value['code'], value['data'], status),
                                 (argv[0], 'internal', {'error': 'NotImplementedError'}, 1))
                self.assertIn('not implemented', value['say'])
        log = [line for path in (self.root / 'logs').glob('failures-*.jsonl') for line in path.read_text().splitlines()]
        self.assertEqual(len(log), 2)
        after = self.snapshot()
        self.assertEqual({name for name in after if not name.startswith('logs/')},
                         {name for name in before if not name.startswith('logs/')})


if __name__ == '__main__':
    unittest.main()
