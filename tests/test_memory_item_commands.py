"""TASK-040: the list and open commands (API-020, API-022; SPEC-025, SPEC-020); TASK-112: open of a raw entry.

TC-223, TC-227, TC-228 and TC-406, and the open part of TC-222, at the
handlers' boundary, on made-up format-2 stores. The runner parses both commands but hands
them to no handler before the 0.3.0 activation, which a test checks, so these
are the handlers' own results, called as the runner will call them.
"""
import contextlib
from datetime import datetime, timedelta, timezone
import json
import os
import subprocess
import sys
import types
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import clock, commands, files, forget_plan, item_commands, item_types, raw_log, request_inputs
from memory_lib import history_recovery, run_listing, worker_support
import test_memory_commands as commands_fixture
import test_memory_curation_worker as worker_fixture
import test_memory_recall as recall_fixture

AT, DEVICE, HOOKS, WHEN = worker_fixture.AT, worker_fixture.DEVICE, worker_fixture.HOOKS, worker_fixture.WHEN
OTHER = 'd_zyxwvtsrqpnm'
ident = worker_fixture.ident
EXAMPLES = json.loads((ROOT / 'docs/06-api/memory-examples.json').read_text(encoding='utf-8'))['result']['valid']


def dated(value, day):
    """The item with its deciding quote said on `day`."""
    value['quotes'][0]['said'] = day + value['quotes'][0]['said'][10:]
    return value


class ItemCommandsTest(unittest.TestCase):
    Fixture, Ranking = worker_fixture.CurationWorkerTest, recall_fixture.RecallTest
    configure, layer, saved, one_turn, items, write, snapshot = (
        Fixture.configure, Fixture.layer, Fixture.saved, Fixture.one_turn, Fixture.items, Fixture.write,
        Fixture.snapshot)
    item = Ranking.item

    def setUp(self):
        self.Fixture.setUp(self)
        self.said, _ = self.one_turn()

    def context(self, command, arguments, project='sample'):
        context = commands.Context(command, dict(arguments, folder=str(self.root)), None, self.memory)
        context.project = types.SimpleNamespace(name=project)
        context.record = {'device': DEVICE}
        context.configuration = self.memory.configuration(deadline=clock.now() + 10)
        return context

    def list(self, **arguments):
        value = item_commands.list_items(self.context('list', arguments))
        commands.validate_result(value, 'list')
        return value

    def open(self, *names, around=None, project='sample', when=WHEN):
        arguments = {'item': list(names)}
        if around is not None:
            arguments['around'] = around
        value = item_commands.open_items(self.context('open', arguments, project), when=when)
        commands.validate_result(value, 'open')
        return value

    def tombstone(self, value, backup=False):
        cited = value['quotes'][0]
        stone = dict(item=value['id'], project='sample', at=AT, device=DEVICE,
                     quotes=[{name: cited[name] for name in ('device', 'entry', 'log', 'start', 'end')}])
        name = value['id'] + '.json' + ('.bak' if backup else '')
        (self.root / 'layer/tombstones' / name).write_bytes(item_types._raw(stone) + b'\n')

    def lines(self, values):
        return [run_listing.list_line(value) for value in values]

    @contextlib.contextmanager
    def held(self, name, kind):
        """Another process holding one of the project's leases, as a curation or an apply would."""
        code = ("import sys,time;sys.path.insert(0,sys.argv[1]);from pathlib import Path;"
                "from memory_lib import locks;lease=locks.Lock(Path(sys.argv[2]),sys.argv[3],sys.argv[4]);"
                "lease.acquire(time.monotonic()+5);print('ready',flush=True);"
                "sys.stdin.readline();lease.release()")
        child = subprocess.Popen([sys.executable, '-B', '-c', code,
                                  str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'),
                                  str(self.root / name), kind, DEVICE],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            yield
        finally:
            child.stdin.write('\n')
            child.stdin.flush()
            child.wait(timeout=10)
            child.stdin.close()
            child.stdout.close()

    # API-020: the item list (TC-223)

    def test_tc223_the_list_shows_200_current_items_newest_first_and_counts_the_rest(self):
        empty = self.list(limit=200)
        self.assertEqual((empty['outcome'], empty['code'], empty['data'], empty['say']),
                         ('nothing', 'ok', {'project': 'sample', 'items': [], 'more': 0}, 'No current items.'))
        kinds = sorted(item_types.KINDS)
        values = [dated(self.item('Item %03d' % number, kind=kinds[number % 5]), '2026-10-%02d' % (1 + number % 28))
                  for number in range(250)]
        self.layer(values)
        # The order of the item list that curation writes (TBL-015): newest first, then by ID.
        expected = [line.split('\t')[0] for line in item_types.item_list_bytes(values).decode('utf-8').splitlines()]
        found = self.list(limit=200)
        self.assertEqual((found['outcome'], found['data']['more']), ('done', 50))
        self.assertEqual([line['item'] for line in found['data']['items']], expected[:200])
        self.assertEqual(found['data']['items'][0], run_listing.list_line(
            next(value for value in values if value['id'] == expected[0])))
        self.assertEqual(found['say'], '200 current items, newest first; --limit left out 50 more.')
        decisions = [item for item in expected
                     if next(value for value in values if value['id'] == item)['kind'] == 'decision']
        narrowed = self.list(kind='decision', limit=200)
        self.assertEqual(([line['item'] for line in narrowed['data']['items']], narrowed['data']['more']),
                         (decisions, 0))
        self.assertEqual(narrowed['say'], '50 current decision items, newest first.')
        short = self.list(kind='decision', limit=5)
        self.assertEqual(([line['item'] for line in short['data']['items']], short['data']['more']),
                         (decisions[:5], 45))
        self.assertEqual([line['item'] for line in self.list(limit=5)['data']['items']], expected[:5])
        one = self.list(limit=1)
        self.assertEqual(one['say'], '1 current item, newest first; --limit left out 249 more.')
        # The order does not depend on the order in which the items are read.
        self.assertEqual(item_commands.listed(values[::-1]), item_commands.listed(values))

    def test_the_list_holds_only_current_items_that_no_tombstone_names(self):
        values = [self.item('Current %d' % number) for number in range(4)]
        others = [self.item(status, status=status) for status in ('superseded', 'withdrawn', 'undone')]
        self.layer(values + others)
        # A stopped forget leaves the item's file, and its item list line, behind its tombstone.
        self.tombstone(values[0])
        self.tombstone(values[1], backup=True)
        found = self.list(limit=200)
        self.assertEqual(found['data']['items'], self.lines(sorted(values[2:], key=lambda value: value['id'])))
        self.assertIn(values[0]['id'].encode(), (self.root / 'layer/item-list.txt').read_bytes())
        self.assertEqual(found['say'], '2 current items, newest first.')
        self.assertEqual(self.list(kind='lesson', limit=200)['say'], 'No current lesson items.')

    def test_the_example_says_what_the_list_says(self):
        example = EXAMPLES['list']
        values = []
        for line in example['data']['items']:
            value = self.item(line['title'], kind=line['kind'])
            value['id'] = line['item']
            value['quotes'][0]['speaker'] = line['speaker']
            values.append(dated(value, line['date']))
        self.layer(values)
        found = self.list(limit=200)
        self.assertEqual((found['data']['items'], found['say']), (example['data']['items'], example['say']))

    def test_a_project_without_a_folder_or_being_deleted_lists_no_items(self):
        self.layer([self.item('Kept')])
        self.assertEqual(self.list(limit=200)['data']['more'], 0)
        other = item_commands.list_items(self.context('list', {'limit': 200}, project='other'))
        self.assertEqual((other['outcome'], other['data']['items']), ('nothing', []))
        # A copy of the project's tombstone already counts, as the memory worker counts it (TBL-017).
        copy = self.root / 'layer/deleted.json.0123456789abcdef.tmp'
        copy.write_bytes(b'{}\n')
        self.assertEqual(self.list(limit=200)['data']['items'], [])
        copy.unlink()
        (self.root / 'layer/deleted.json').write_bytes(b'{}\n')
        before = self.snapshot()
        self.assertEqual(self.list(limit=200)['data']['items'], [])
        self.assertEqual(self.snapshot(), before)

    def test_a_project_that_no_curation_has_run_for_lists_and_opens_nothing(self):
        # C1 recorded its raw log, and no curated layer exists yet.
        fresh = self.folder / 'projects/fresh'
        (fresh / 'raw').mkdir(parents=True)
        before = self.snapshot()
        found = item_commands.list_items(self.context('list', {'limit': 200}, project='fresh'))
        self.assertEqual((found['outcome'], found['data']['items'], found['data']['more']), ('nothing', [], 0))
        opened = self.open(ident('i'), project='fresh')
        self.assertEqual((opened['code'], opened['data']['matches']), ('item-not-found', []))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(sorted(path.name for path in fresh.iterdir()), ['raw'])

    def test_an_item_record_that_cannot_be_read_raises_and_changes_nothing(self):
        value = self.item('Damaged')
        self.layer([value])
        path = self.root / 'layer/items' / (value['id'] + '.json')
        path.write_bytes(b'{')
        before = self.snapshot()
        with self.assertRaises(files.RestoreNeeded):
            self.list(limit=200)
        with self.assertRaises(files.RestoreNeeded):
            self.open(value['id'])
        path.unlink()
        path.with_name(path.name + '.bak').write_bytes(item_types.item_bytes(value))
        with self.assertRaises(files.RestoreNeeded):
            self.list(limit=200)
        with self.assertRaises(files.RestoreNeeded):
            self.open(value['id'])
        self.assertEqual(set(self.snapshot()) - set(before), {'layer/items/%s.json.bak' % value['id']})
        path.with_name(path.name + '.bak').unlink()
        # A file that holds another item.
        path.write_bytes(item_types.item_bytes(self.item('Another')))
        with self.assertRaises(files.RestoreNeeded):
            self.open(value['id'])
        path.unlink()
        outside = self.folder.parent / 'outside.json'
        outside.write_bytes(item_types.item_bytes(value))
        try:
            os.symlink(str(outside), str(path))
        except (OSError, NotImplementedError):
            self.skipTest('symbolic links are not available')
        with self.assertRaises(worker_support.UnsafePath):
            self.list(limit=200)
        with self.assertRaises(worker_support.UnsafePath):
            self.open(value['id'])

    def test_list_arguments_outside_the_schema_are_usage(self):
        for arguments in ({'kind': 'note'}, {'limit': 0}, {'limit': True}, {'limit': '5'}, {'kind': 7}):
            with self.subTest(arguments=arguments):
                value = item_commands.list_items(self.context('list', arguments))
                self.assertEqual((value['outcome'], value['code']), ('refused', 'usage'))

    def test_a_layer_lease_held_past_the_wait_is_lock_busy(self):
        self.layer([self.item('Kept')])
        before = self.snapshot()
        with mock.patch.object(item_commands, 'WAIT', 0.2), self.held('layer.lock', 'layer'):
            for command, handler, arguments in (('list', item_commands.list_items, {'limit': 200}),
                                                ('open', item_commands.open_items, {'item': [ident('i')]})):
                with self.subTest(command=command):
                    started = clock.now()
                    value = handler(self.context(command, arguments))
                    self.assertEqual((value['code'], value['outcome']), ('lock-busy', 'failed'))
                    self.assertLess(clock.now() - started, 5)
        # A curation's lease does not hold them up.
        with self.held('curation.lock', 'curation'):
            self.assertEqual(self.list(limit=200)['code'], 'ok')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.memory.held, [])

    # API-022: open (TC-222, TC-227, TC-228)

    def test_tc227_each_quote_says_where_its_entry_is_held_and_shows_2000_characters_around_it(self):
        words = 'keep the raw logs on this machine'
        said, _ = self.raw.turn('L' * 1500 + 'l' * 1000 + words + 'r' * 1000 + 'R' * 1500, 'Done.')
        self.write()
        value = self.saved(said, words)
        here = value['quotes'][0]
        deleted = dict(here, entry=ident('e'), log=raw_log.log_name('claude-code', 'gone-session-040'))
        elsewhere = dict(here, entry=ident('e'), log=raw_log.log_name('codex', 'other-device-040'), device=OTHER)
        value['quotes'] = [here, deleted, elsewhere]
        self.layer([value])
        found = self.open(value['id'], around=2000)
        self.assertEqual((found['outcome'], found['code']), ('done', 'ok'))
        quotes = found['data']['items'][0]['quotes']
        self.assertEqual([quote['held'] for quote in quotes], ['here', 'deleted', 'elsewhere'])
        self.assertEqual((quotes[0]['before'], quotes[0]['after']), ('L' * 1000 + 'l' * 1000, 'r' * 1000 + 'R' * 1000))
        for quote in quotes[1:]:
            self.assertNotIn('before', quote)
            self.assertNotIn('after', quote)
        self.assertEqual(found['say'], '1 item, with its quotes and the words around the 1 that this device holds.')
        shown = found['data']['items'][0]
        self.assertEqual(shown, {
            'item': value['id'], 'kind': 'decision', 'status': 'current', 'title': value['title'],
            'text': value['text'], 'saved': value['saved'], 'quotes': [
                dict({name: quote[name] for name in ('entry', 'log', 'device', 'speaker', 'said', 'words')},
                     **extra) for quote, extra in zip(value['quotes'], (
                         {'held': 'here', 'before': 'L' * 1000 + 'l' * 1000, 'after': 'r' * 1000 + 'R' * 1000},
                         {'held': 'deleted'}, {'held': 'elsewhere'}))]})
        smaller = self.open(value['id'], around=5)['data']['items'][0]['quotes'][0]
        self.assertEqual((smaller['before'], smaller['after']), ('l' * 5, 'r' * 5))
        nothing = self.open(value['id'], around=0)['data']['items'][0]['quotes'][0]
        self.assertEqual((nothing['before'], nothing['after']), ('', ''))
        plain = self.open(value['id'])
        self.assertNotIn('before', plain['data']['items'][0]['quotes'][0])
        self.assertEqual([quote['held'] for quote in plain['data']['items'][0]['quotes']],
                         ['here', 'deleted', 'elsewhere'])
        self.assertEqual(plain['say'], '1 item, with its quotes.')
        # The runner refuses more than 2,000 as usage (TC-074), and so does the handler.
        for size in (2001, -1, True, '5'):
            with self.subTest(around=size):
                refused = item_commands.open_items(self.context('open', {'item': [value['id']], 'around': size}))
                self.assertEqual(refused['code'], 'usage')

    def test_a_quote_whose_entry_retention_deleted_is_deleted_and_the_item_keeps_its_words(self):
        value = self.saved(self.said, HOOKS)
        self.layer([value])
        log = self.root / 'raw' / (self.raw.name + '.jsonl')
        log.write_bytes(b'')
        found = self.open(value['id'], around=100)
        quote = found['data']['items'][0]['quotes'][0]
        self.assertEqual((quote['held'], quote['words']), ('deleted', HOOKS))
        self.assertEqual(found['say'], "1 item, with its quote; this device does not hold the quoted entry, "
                                       "so nothing around it is shown.")
        log.unlink()
        self.assertEqual(self.open(value['id'], around=100)['data']['items'][0]['quotes'][0]['held'], 'deleted')

    def test_only_this_device_s_entries_within_the_retention_period_are_read_around_a_quote(self):
        value = self.saved(self.said, HOOKS)
        # Another device's quote naming an entry that this device's log holds: its text is not read.
        value['quotes'].append(dict(value['quotes'][0], device=OTHER))
        self.layer([value])
        self.configure(retention={'days': 7})
        said = datetime.strptime(self.said['at'], '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)
        last = said + timedelta(days=7)
        quotes = self.open(value['id'], around=100, when=last)['data']['items'][0]['quotes']
        self.assertEqual([quote['held'] for quote in quotes], ['here', 'elsewhere'])
        start = value['quotes'][0]['start']
        self.assertEqual(quotes[0]['before'], self.said['text'][max(0, start - 100):start])
        self.assertNotIn('before', quotes[1])
        # Once the entry is past the retention period it is deleted for `open`, as retention deletes it next (SPEC-025).
        late = last + timedelta(seconds=1)
        found = self.open(value['id'], around=100, when=late)
        quotes = found['data']['items'][0]['quotes']
        self.assertEqual([quote['held'] for quote in quotes], ['deleted', 'elsewhere'])
        for quote in quotes:
            self.assertNotIn('before', quote)
        self.assertEqual(found['say'], "1 item, with its quotes; this device does not hold the quoted entries, "
                                       "so nothing around them is shown.")
        self.assertEqual(self.open(value['id'], when=late)['data']['items'][0]['quotes'][0]['held'], 'deleted')

    def test_forgotten_ranges_around_a_quote_show_as_one_mark_that_is_never_cut(self):
        words, secret, pending = 'the hooks stay in one script', 'a private remark', 'another private remark'
        text = 'Before ' + secret + ' then ' + words + ' and ' + pending + ' after.'
        said, _ = self.raw.turn(text, 'Done.')
        start = text.index(secret)
        # A forget's rewrite filled the first range; the second is a stopped forget's tombstone.
        said['text'] = text[:start] + '�' * len(secret) + text[start + len(secret):]
        said['forgotten'] = [[start, start + len(secret)]]
        self.write()
        value, gone = self.saved(said, words), self.saved(said, pending)
        self.layer([value])
        self.tombstone(gone)
        quote = self.open(value['id'], around=2000)['data']['items'][0]['quotes'][0]
        self.assertEqual((quote['before'], quote['after']), ('Before [forgotten] then ', ' and [forgotten] after.'))
        for size, before, after in ((17, '[forgotten] then ', ' and [forgotten] '), (16, ' then ', ' and [forgotten]'),
                                    (10, ' then ', ' and '), (5, 'then ', ' and ')):
            with self.subTest(size=size):
                quote = self.open(value['id'], around=size)['data']['items'][0]['quotes'][0]
                self.assertEqual((quote['before'], quote['after']), (before, after))
                self.assertLessEqual(max(len(quote['before']), len(quote['after'])), size)
        self.assertNotIn(secret, json.dumps(self.open(value['id'], around=2000)))
        self.assertNotIn(pending, json.dumps(self.open(value['id'], around=2000)))
        self.assertIn(pending, said['text'])

    def test_a_tombstone_backup_or_a_temporary_copy_neither_fails_open_nor_shows_its_range(self):
        words, pending = 'the hooks stay in one script', 'a private remark'
        text = 'Before ' + words + ' and ' + pending + ' after.'
        said, _ = self.raw.turn(text, 'Done.')
        self.write()
        value, gone = self.saved(said, words), self.saved(said, pending)
        self.layer([value])
        # A rewrite of the tombstone stopped with only its backup, and other writes left temporary copies of a
        # tombstone and of an item, whose backup is beside its file.
        self.tombstone(gone, backup=True)
        (self.root / 'layer/tombstones' / (gone['id'] + '.json.k2j4x9.tmp')).write_bytes(b'{')
        path = self.root / 'layer/items' / (value['id'] + '.json')
        path.with_name(path.name + '.bak').write_bytes(path.read_bytes())
        path.with_name(path.name + '.7fq2m1.tmp').write_bytes(b'{')
        before = self.snapshot()
        found = self.open(value['id'])
        self.assertEqual((found['outcome'], found['code'], found['data']['items'][0]['quotes'][0]['held']),
                         ('done', 'ok', 'here'))
        quote = self.open(value['id'], around=2000)['data']['items'][0]['quotes'][0]
        self.assertEqual((quote['before'], quote['after']), ('Before ', ' and [forgotten] after.'))
        self.assertEqual(self.snapshot(), before)

    def test_open_reads_each_tombstone_once_for_quotes_in_several_logs(self):
        other = worker_fixture.Raw('other-session-040')
        first, _ = self.raw.turn('Keep the hooks in one script and drop the old remark.', 'Done.')
        second, _ = other.turn('Keep the logs on this device and drop the other remark.', 'Done.')
        self.write()
        (self.root / 'raw' / (other.name + '.jsonl')).write_bytes(other.data())
        value, gone = self.saved(first, 'Keep the hooks in one script'), self.saved(first, 'the old remark')
        theirs = 'Keep the logs on this device'
        value['quotes'].append(dict(value['quotes'][0], entry=second['id'], log=other.name, start=0, end=len(theirs),
                                    words=theirs, said=second['at']))
        start = second['text'].index('the other remark')
        other_gone = dict(gone, id=ident('i'), quotes=[dict(gone['quotes'][0], entry=second['id'], log=other.name,
                                                            start=start, end=start + len('the other remark'))])
        self.layer([value])
        self.tombstone(gone)
        self.tombstone(other_gone)
        with mock.patch.object(history_recovery, '_tombstone', wraps=history_recovery._tombstone) as read:
            quotes = self.open(value['id'], around=2000)['data']['items'][0]['quotes']
        self.assertEqual([(quote['held'], quote['after']) for quote in quotes],
                         [('here', ' and drop [forgotten].'), ('here', ' and drop [forgotten].')])
        self.assertEqual(read.call_count, 2)

    def test_only_around_reads_the_tombstones_and_open_reads_the_items_at_most_once(self):
        # The ranges that pending tombstones name show only in the words around a quote, and the items that stay,
        # which those ranges need, also give the closest lines for an argument that names no item.
        said, _ = self.raw.turn('Keep the hooks in one script and drop the old remark.', 'Done.')
        self.write()
        value, gone = self.saved(said, 'Keep the hooks in one script'), self.saved(said, 'the old remark')
        self.layer([value])
        self.tombstone(gone)
        missing = ident('i')
        with mock.patch.object(item_commands, '_tombstones', wraps=item_commands._tombstones) as stones, \
                mock.patch.object(item_commands, '_items', wraps=item_commands._items) as items:
            found = self.open(value['id'])
            self.assertEqual(found['data']['items'][0]['quotes'][0]['held'], 'here')
            self.assertEqual((stones.call_count, items.call_count), (0, 0))
            refused = self.open(value['id'], missing, around=2000)
            self.assertEqual((refused['code'], refused['data']['missing']), ('item-not-found', [missing]))
            self.assertEqual(refused['data']['items'][0]['quotes'][0]['after'], ' and drop [forgotten].')
            self.assertEqual((stones.call_count, items.call_count), (1, 1))

    def test_a_tombstone_that_cannot_be_read_fails_only_around(self):
        # Without --around, open sees only the names in the tombstones' folder, as list does.
        said, _ = self.raw.turn('Keep the hooks in one script and drop the old remark.', 'Done.')
        self.write()
        value, gone = self.saved(said, 'Keep the hooks in one script'), self.saved(said, 'the old remark')
        self.layer([value])
        (self.root / 'layer/tombstones' / (gone['id'] + '.json')).write_bytes(b'{')
        before = self.snapshot()
        found = self.open(value['id'])
        self.assertEqual((found['code'], found['data']['items'][0]['quotes'][0]['held']), ('ok', 'here'))
        refused = self.open(gone['id'])
        self.assertEqual((refused['code'], refused['data']['missing']), ('item-not-found', [gone['id']]))
        with self.assertRaises(ValueError):
            self.open(value['id'], around=10)
        self.assertEqual(self.snapshot(), before)

    def test_adjacent_and_overlapping_forgotten_ranges_make_one_mark(self):
        entry = {'text': 'abcdefghijklmnop', 'forgotten': [[4, 6], [2, 4], [5, 8]]}
        self.assertEqual(item_commands.around(entry, {'start': 10, 'end': 12}, 2000), ('ab[forgotten]ij', 'mnop'))
        # The mark is 11 characters: 13 take it whole, 12 leave it out rather than cut it.
        for size, before in ((14, 'b[forgotten]ij'), (13, '[forgotten]ij'), (12, 'ij')):
            with self.subTest(size=size):
                self.assertEqual(item_commands.around(entry, {'start': 10, 'end': 12}, size), (before, 'mnop'))

    def test_tc222_open_shows_each_status_with_what_superseded_or_merges_it(self):
        current, withdrawn, undone = self.item('Current'), self.item('Gone', status='withdrawn'), self.item(
            'Undone', status='undone')
        older = self.item('Older', status='superseded')
        older['superseded_by'] = current['id']
        current['merges'] = [older['id']]
        undone['undone_by'] = 'r_0123456789ab'
        self.layer([current, withdrawn, undone, older])
        found = self.open(withdrawn['id'], older['id'], current['id'], undone['id'], withdrawn['id'])
        shown = found['data']['items']
        self.assertEqual([(line['item'], line['status']) for line in shown], [
            (withdrawn['id'], 'withdrawn'), (older['id'], 'superseded'), (current['id'], 'current'),
            (undone['id'], 'undone')])
        self.assertEqual((shown[1]['superseded_by'], shown[2]['merges']), (current['id'], [older['id']]))
        self.assertNotIn('superseded_by', shown[0])
        self.assertNotIn('undone_by', shown[3])
        self.assertEqual(found['say'], '4 items, with their quotes.')

    def test_tc228_arguments_that_name_no_item_of_the_project_are_item_not_found(self):
        kept, forgotten = self.item('Keep the raw logs'), self.item('Forgotten')
        self.layer([kept, forgotten])
        self.tombstone(forgotten)
        other = self.folder / 'projects/other/layer/items'
        other.mkdir(parents=True)
        foreign = self.item('Of another project')
        (other / (foreign['id'] + '.json')).write_bytes(item_types.item_bytes(foreign))
        made_up, entry = ident('i'), self.said['id']
        before = self.snapshot()
        found = self.open(made_up, foreign['id'])
        self.assertEqual((found['outcome'], found['code']), ('refused', 'item-not-found'))
        lines = self.lines([kept])
        self.assertEqual(found['data'], {'project': 'sample', 'items': [], 'missing': [made_up, foreign['id']],
                                         'matches': forget_plan.closest(lines, [made_up, foreign['id']])})
        self.assertEqual(found['data']['matches'], lines)
        self.assertEqual(found['say'], item_commands.MISSING)
        # The found items come with the missing ones; a forgotten item and an entry ID that names no entry of this
        # device name nothing, while an entry that this device holds opens (TASK-112).
        unknown = ident('e')
        mixed = self.open(kept['id'], forgotten['id'], unknown, 'raw logs', entry)
        self.assertEqual((mixed['code'], mixed['data']['missing']), ('item-not-found', [forgotten['id'], unknown,
                                                                                       'raw logs']))
        self.assertEqual([line['item'] for line in mixed['data']['items']], [kept['id']])
        self.assertEqual([line['entry'] for line in mixed['data']['entries']], [entry])
        self.assertEqual(mixed['say'], item_commands.MISSING_ENTRIES +
                         ' data.items holds the 1 found and data.entries holds the 1 found.')
        alone = self.open(unknown)
        self.assertEqual((alone['data']['entries'], alone['say']), ([], item_commands.MISSING_ENTRIES))
        self.assertEqual(self.snapshot(), before)
        # A name that is not an item ID never reaches a file, not even another project's.
        sneaky = '../../../other/layer/items/' + foreign['id']
        refused = self.open(sneaky)
        self.assertEqual((refused['code'], refused['data']['missing']), ('item-not-found', [sneaky]))
        # Another project's own items are its own.
        theirs = self.open(foreign['id'], project='other')
        self.assertEqual((theirs['code'], theirs['data']['items'][0]['item']), ('ok', foreign['id']))

    # SPEC-148: open of a raw entry (TC-406)

    def test_tc406_open_shows_an_entry_that_this_device_holds_with_at_most_2000_characters_of_its_text(self):
        secret, pending = 'a private remark', 'another private remark'
        text = 'Before ' + secret + ' then keep the hooks and ' + pending + ' after.'
        long, answer = self.raw.turn('x' * 1990 + 'y' * 1010, 'Done.')
        marked, _ = self.raw.turn(text, 'Noted.')
        start = text.index(secret)
        # A forget's rewrite filled the first range; the second is a stopped forget's tombstone.
        marked['text'] = text[:start] + '\ufffd' * len(secret) + text[start + len(secret):]
        marked['forgotten'] = [[start, start + len(secret)]]
        self.write()
        self.tombstone(self.saved(marked, pending))
        unknown = ident('e')
        found = self.open(self.said['id'], long['id'], marked['id'], answer['id'], unknown, self.said['id'])
        self.assertEqual((found['outcome'], found['code']), ('refused', 'item-not-found'))
        self.assertEqual((found['data']['items'], found['data']['missing']), ([], [unknown]))
        entries = found['data']['entries']
        self.assertEqual(entries[0], {'entry': self.said['id'], 'log': self.raw.name, 'speaker': 'user',
                                      'said': self.said['at'], 'text': self.said['text'], 'whole': True})
        self.assertEqual([(line['entry'], line['speaker'], line['whole']) for line in entries[1:]], [
            (long['id'], 'user', False), (marked['id'], 'user', True), (answer['id'], 'agent', True)])
        self.assertEqual(entries[1]['text'], 'x' * 1990 + 'y' * 10)
        self.assertEqual(entries[2]['text'], 'Before [forgotten] then keep the hooks and [forgotten] after.')
        self.assertEqual(entries[3]['text'], 'Done.')
        for words in (secret, pending):
            self.assertNotIn(words, json.dumps(found))
        self.assertEqual(found['say'], item_commands.MISSING_ENTRIES + ' data.entries holds the 4 found.')
        held = self.open(self.said['id'], long['id'])
        self.assertEqual((held['code'], held['say']), ('ok', '2 entries of this device, with their texts; 1 of them '
                                                       'cut.'))
        self.assertEqual(self.open(long['id'])['say'], '1 entry of this device, with its text, which is cut.')
        self.assertEqual(self.open(answer['id'])['say'], '1 entry of this device, with its text.')

    def test_an_entry_that_the_recording_cut_is_not_whole(self):
        # A text cut when it was recorded (TBL-007 `cut`, SPEC-002) is not whole however short it is.
        cut, _ = self.raw.turn('The first part of a long prompt', 'Done.')
        cut['cut'] = 600000
        self.write()
        found = self.open(cut['id'])
        self.assertEqual([(line['text'], line['whole']) for line in found['data']['entries']],
                         [('The first part of a long prompt', False)])
        self.assertEqual(found['say'], '1 entry of this device, with its text, which is cut.')

    def test_a_forgotten_range_at_the_2000th_character_is_left_out_rather_than_cut(self):
        said, _ = self.raw.turn('a' * 1995 + 'private words' + 'b', 'Done.')
        said['text'] = 'a' * 1995 + '\ufffd' * len('private words') + 'b'
        said['forgotten'] = [[1995, 1995 + len('private words')]]
        self.write()
        line = self.open(said['id'])['data']['entries'][0]
        self.assertEqual((line['text'], line['whole']), ('a' * 1995, False))
        self.assertEqual(item_commands.entry_line(dict(said, text='a' * 1989 + '\ufffd' * 5 + 'b',
                                                        forgotten=[[1989, 1994]]), self.raw.name)['text'],
                         'a' * 1989 + '[forgotten]')

    def test_an_entry_that_is_a_boundary_past_retention_or_with_its_item_found_is_named_once(self):
        value = self.saved(self.said, HOOKS)
        self.layer([value])
        self.configure(retention={'days': 7})
        said = datetime.strptime(self.said['at'], '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc)
        boundary = self.raw.entries[0]['id']
        found = self.open(value['id'], self.said['id'], boundary, when=said + timedelta(days=7))
        self.assertEqual(found['data']['missing'], [boundary])  # a session boundary has no speaker and no text
        self.assertEqual(([line['item'] for line in found['data']['items']],
                          [line['entry'] for line in found['data']['entries']]), ([value['id']], [self.said['id']]))
        # Past the retention period the entry is gone for `open`, as retention deletes it next (SPEC-025).
        late = self.open(self.said['id'], when=said + timedelta(days=7, seconds=1))
        self.assertEqual((late['code'], late['data']['entries'], late['data']['missing']),
                         ('item-not-found', [], [self.said['id']]))

    def test_only_the_raw_logs_that_hold_a_named_entry_s_id_are_read_as_entries(self):
        other = worker_fixture.Raw('other-session-112')
        theirs, _ = other.turn('Another session.', 'Yes.')
        (self.root / 'raw' / (other.name + '.jsonl')).write_bytes(other.data())
        (self.root / 'raw' / (self.raw.name + '.lock')).write_bytes(b'')
        # A folder under a raw log's name holds no entry and is not read.
        (self.root / 'raw' / (worker_fixture.Raw('folder-session-112').name + '.jsonl')).mkdir()
        before = self.snapshot()
        with mock.patch.object(request_inputs, 'entries', wraps=request_inputs.entries) as parsed:
            found = self.open(theirs['id'])
            self.assertEqual(([line['log'] for line in found['data']['entries']], parsed.call_count), ([other.name], 1))
            # An ID that no log holds takes the scan through every log, the folder too, and parses none of them.
            unknown = ident('e')
            missing = self.open(theirs['id'], unknown)
            self.assertEqual(([line['entry'] for line in missing['data']['entries']], missing['data']['missing'],
                              parsed.call_count), ([theirs['id']], [unknown], 2))
            # Without an entry ID no raw log is read as entries.
            self.open(ident('i'))
            self.assertEqual(parsed.call_count, 2)
        self.assertEqual(self.snapshot(), before)
        # The words around a quote and an entry ID in one `open` read the quote's log as entries once.
        value = self.saved(self.said, HOOKS)
        self.layer([value])
        with mock.patch.object(request_inputs, 'entries', wraps=request_inputs.entries) as parsed:
            together = self.open(value['id'], self.said['id'], around=10)
        self.assertEqual(([line['item'] for line in together['data']['items']],
                          [line['entry'] for line in together['data']['entries']],
                          [call.args[1] for call in parsed.call_args_list]),
                         ([value['id']], [self.said['id']], [self.raw.name]))
        self.assertEqual(together['data']['items'][0]['quotes'][0]['held'], 'here')

    def test_a_raw_log_that_goes_while_open_reads_it_holds_no_entry(self):
        # Retention can delete a raw log between its look and its read, while `open` holds only the layer lease.
        path = self.root / 'raw' / (self.raw.name + '.jsonl')
        read = run_listing._reader

        def reader(memory, deadline):
            real = read(memory, deadline)

            def gone(target):
                if target == path:
                    path.unlink()
                return real(target)
            return gone
        with mock.patch.object(run_listing, '_reader', reader):
            found = self.open(self.said['id'])
        self.assertEqual((found['code'], found['data']['entries'], found['data']['missing']),
                         ('item-not-found', [], [self.said['id']]))

    def test_an_id_that_a_raw_log_holds_twice_opens_its_first_entry_with_or_without_the_words_around_a_quote(self):
        # A later line under the same ID, as a replayed append can leave it, which the entry parser keeps by its seq.
        seq = self.raw.entries[-1]['seq'] + 1
        self.raw.entries.append(dict(self.said, seq=seq, turn=seq, text=HOOKS + ' was said again, later.'))
        self.write()
        self.assertEqual([entry['text'] for entry in request_inputs.entries(self.root, self.raw.name)
                          if entry['id'] == self.said['id']], [self.said['text'], HOOKS + ' was said again, later.'])
        value = self.saved(self.said, HOOKS)
        self.layer([value])
        alone = self.open(self.said['id'])
        self.assertEqual([line['text'] for line in alone['data']['entries']], [self.said['text']])
        together = self.open(value['id'], self.said['id'], around=10)
        self.assertEqual(together['data']['entries'], alone['data']['entries'])
        quote = together['data']['items'][0]['quotes'][0]
        self.assertEqual((quote['held'], quote['after']), ('here', self.said['text'][len(HOOKS):][:10]))

    def test_a_raw_folder_that_is_a_file_holds_no_entry(self):
        value = self.saved(self.said, HOOKS)
        self.layer([value])
        raw = self.root / 'raw'
        for path in raw.iterdir():
            path.unlink()
        raw.rmdir()
        raw.write_bytes(self.raw.data())
        found = self.open(self.said['id'])
        self.assertEqual((found['outcome'], found['code'], found['data']['entries'], found['data']['missing']),
                         ('refused', 'item-not-found', [], [self.said['id']]))
        # An item whose quote this device wrote is shown, its entry deleted, with or without the words around it.
        for size in (None, 10):
            with self.subTest(around=size):
                both = self.open(value['id'], self.said['id'], around=size)
                self.assertEqual((both['code'], [line['item'] for line in both['data']['items']],
                                  both['data']['items'][0]['quotes'][0]['held'], both['data']['entries'],
                                  both['data']['missing']),
                                 ('item-not-found', [value['id']], 'deleted', [], [self.said['id']]))

    def test_a_raw_log_that_windows_refuses_to_look_at_for_a_moment_is_looked_at_again(self):
        # The curator's rewrite of a raw log can leave it delete-pending on Windows for a moment.
        path = self.root / 'raw' / (self.raw.name + '.jsonl')
        check, refused = self.memory.fence.check, []

        def looking(target, *args, **kwargs):
            if target == path and not refused:
                refused.append(True)
                raise PermissionError(13, 'refused')
            return check(target, *args, **kwargs)
        with mock.patch.object(files, '_WINDOWS', True), \
                mock.patch.object(self.memory.fence, 'check', side_effect=looking):
            found = self.open(self.said['id'])
        self.assertEqual((refused, [line['entry'] for line in found['data']['entries']]), ([True], [self.said['id']]))

    def test_a_raw_log_that_a_link_reaches_raises_as_an_item_record_does(self):
        other = worker_fixture.Raw('other-session-112')
        theirs, _ = other.turn('Another session.', 'Yes.')
        (self.root / 'raw' / (other.name + '.jsonl')).write_bytes(other.data())
        path = self.root / 'raw' / (self.raw.name + '.jsonl')
        outside = self.folder.parent / 'outside.jsonl'
        outside.write_bytes(path.read_bytes())
        path.unlink()
        try:
            os.symlink(str(outside), str(path))
        except (OSError, NotImplementedError):
            self.skipTest('symbolic links are not available')
        # Whichever log holds the named entry, the scan reads the linked one's bytes no further than the fence.
        for name in (self.said['id'], theirs['id'] if other.name > self.raw.name else self.said['id']):
            with self.assertRaises(worker_support.UnsafePath):
                self.open(name)
        self.assertEqual(outside.read_bytes(), self.raw.data())

    def test_matches_are_the_lines_most_like_the_missing_arguments(self):
        kept = dated(self.item('Keep the raw logs on this device'), '2026-10-01')
        newer = [dated(self.item('Newer item %d' % number), '2026-10-%02d' % (10 + number)) for number in range(6)]
        self.layer([kept] + newer)
        found = self.open('Keep the raw logs')
        lines = self.lines(item_commands.listed([kept] + newer))
        self.assertEqual(lines[-1]['item'], kept['id'])
        self.assertEqual(found['data']['matches'], forget_plan.closest(lines, ['Keep the raw logs']))
        self.assertEqual(found['data']['matches'][0]['item'], kept['id'])

    def test_a_project_without_a_folder_or_being_deleted_opens_nothing(self):
        value = self.item('Kept')
        self.layer([value])
        # Each argument is missing once, as when the project has a folder.
        missing = self.open(value['id'], value['id'], project='nowhere')
        self.assertEqual((missing['code'], missing['data']['missing'], missing['data']['matches']),
                         ('item-not-found', [value['id']], []))
        copy = self.root / 'layer/deleted.json.0123456789abcdef.tmp'
        copy.write_bytes(b'{}\n')
        deleted = self.open(value['id'])
        self.assertEqual((deleted['code'], deleted['data']['missing'], deleted['data']['matches']),
                         ('item-not-found', [value['id']], []))
        copy.unlink()
        (self.root / 'layer/deleted.json').write_bytes(b'{}\n')
        deleted = self.open(value['id'], value['id'])
        self.assertEqual((deleted['code'], deleted['data']['missing'], deleted['data']['matches']),
                         ('item-not-found', [value['id']], []))

    def test_the_open_example_says_what_open_says(self):
        example = EXAMPLES['open-around']['data']['items'][0]
        quote = example['quotes'][0]
        said, _ = self.raw.turn(quote['before'] + quote['words'] + quote['after'], 'Done.')
        self.write()
        value = self.saved(said, quote['words'])
        self.layer([value])
        self.assertEqual(self.open(value['id'], around=2000)['say'], EXAMPLES['open-around']['say'])

    def test_open_arguments_outside_the_schema_are_usage(self):
        for names in ([], [''], ['x' * 201], [7], 'i_0123456789ab', None):
            with self.subTest(names=names):
                value = item_commands.open_items(self.context('open', {'item': names}))
                self.assertEqual((value['outcome'], value['code']), ('refused', 'usage'))
        value = self.open('x' * 200)
        self.assertEqual((value['code'], value['data']['missing']), ('item-not-found', ['x' * 200]))


class RunnerTest(unittest.TestCase):
    """The runner parses list, search and open but hands them to no handler before the 0.3.0 activation."""
    reset_store, snapshot = commands_fixture.CommandsTest.reset_store, commands_fixture.CommandsTest.snapshot

    def test_the_runner_answers_list_search_and_open_as_not_implemented(self):
        commands_fixture.CommandsTest.setUp(self)
        before = self.snapshot()
        for argv in (['list'], ['search', 'raw logs'], ['open', 'i_7f3k2m9q4x1v', '--around', '2000']):
            with self.subTest(argv=argv):
                value, status = commands.run(['--folder', str(self.project)] + argv)
                self.assertEqual((value['command'], value['code'], value['data'], status),
                                 (argv[0], 'internal', {'error': 'NotImplementedError'}, 1))
                self.assertIn('not implemented', value['say'])
        log = [line for path in (self.root / 'logs').glob('failures-*.jsonl') for line in path.read_text().splitlines()]
        self.assertEqual(len(log), 3)
        # The parser refuses --around above 2,000 before any handler (TC-074), so TC-227 runs 2,000.
        value, status = commands.run(['--folder', str(self.project), 'open', 'i_7f3k2m9q4x1v', '--around', '5000'])
        self.assertEqual((value['command'], value['code'], status), ('open', 'usage', 2))
        after = self.snapshot()
        self.assertEqual({name for name in after if not name.startswith('logs/')},
                         {name for name in before if not name.startswith('logs/')})


if __name__ == '__main__':
    unittest.main()
