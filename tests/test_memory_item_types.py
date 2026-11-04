"""Partial TASK076 pure-type proof, using fabricated records only."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT / 'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import base, item_types

AT = '2026-11-04T03:00:00.000Z'
DEVICE = 'd_0123456789ab'
QUOTE = {'entry': 'e_0123456789ab', 'log': 'codex-0123456789abcdef', 'device': DEVICE,
         'start': 1, 'end': 3, 'speaker': 'user', 'said': AT, 'words': 'A🙂'}
ITEM = {'id': 'i_0123456789ab', 'kind': 'decision', 'title': '원문\t제목', 'text': '본문\n둘째 줄',
        'quotes': [QUOTE], 'status': 'current', 'saved': AT, 'device': DEVICE}


class ItemTypesTest(unittest.TestCase):
    def item(self, **changes):
        value = copy.deepcopy(ITEM)
        value.update(changes)
        return value

    def test_canonical_field_order_unicode_lf_and_immutability(self):
        value = self.item(superseded_by='i_0123456789ac', undone_by='r_0123456789ab', merges=[], changed=AT)
        original = copy.deepcopy(value)
        raw = item_types.item_bytes(value)
        reversed_fields = dict(reversed(list(value.items())))
        self.assertEqual(raw, item_types.item_bytes(reversed_fields))
        self.assertEqual(item_types.parse_item(raw), original)
        self.assertEqual(list(json.loads(raw)), item_types.ITEM_FIELDS)
        self.assertEqual(list(json.loads(raw)['quotes'][0]), item_types.QUOTE_FIELDS)
        self.assertIn('원문'.encode('utf-8'), raw)
        self.assertTrue(raw.endswith(b'\n'))
        self.assertNotIn(b'\r', raw)
        self.assertFalse(raw.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(value, original)

    def test_no_invented_empty_minima_or_status_dependent_field_cleanup(self):
        for status in item_types.STATUSES:
            value = self.item(status=status, title='', text='', changed=AT, merges=[],
                              superseded_by='i_0123456789ac', undone_by='r_0123456789ab')
            value['quotes'][0].update(start=0, end=0, words='')
            self.assertEqual(item_types.parse_item(item_types.item_bytes(value)), value)

    def test_text_limits_are_utf8_bytes_and_only_title_is_one_line(self):
        for field, allowed, rejected in [('title', '한'*66, '한'*67),
                                         ('text', '🙂'*1000, '🙂'*1001)]:
            item_types.item_bytes(self.item(**{field: allowed}))
            with self.subTest(field=field), self.assertRaises(ValueError):
                item_types.item_bytes(self.item(**{field: rejected}))
        for separator in '\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029':
            with self.subTest(separator=repr(separator)), self.assertRaises(ValueError):
                item_types.item_bytes(self.item(title='x'+separator))
        value = self.item()
        value['quotes'][0].update(start=0, end=4, words='a\nb\t')
        self.assertEqual(item_types.parse_item(item_types.item_bytes(value)), value)

    def test_quote_count_and_words_limit(self):
        for count in (0, 21):
            with self.subTest(count=count), self.assertRaises(ValueError):
                item_types.item_bytes(self.item(quotes=[copy.deepcopy(QUOTE) for _ in range(count)]))
        item_types.item_bytes(self.item(quotes=[copy.deepcopy(QUOTE) for _ in range(20)]))
        for count in (500, 501):
            value = self.item()
            value['quotes'][0].update(start=0, end=count, words='🙂'*count)
            if count == 500:
                item_types.item_bytes(value)
            else:
                with self.assertRaises(ValueError):
                    item_types.item_bytes(value)

    def test_distinct_quote_order_and_first_quote_provenance_are_preserved(self):
        first = dict(QUOTE, speaker='agent', said='2026-11-02T03:00:00.000Z', words='first', start=0, end=5)
        later = dict(QUOTE, entry='e_0123456789ac', speaker='user',
                     said='2026-11-05T22:00:00.000Z', words='later', start=0, end=5)
        value = self.item(quotes=[first, later], saved='2026-11-06T00:00:00.000Z')
        original = copy.deepcopy(value)
        self.assertEqual(item_types.parse_item(item_types.item_bytes(value))['quotes'], [first, later])
        other = self.item(id='i_0123456789ac')
        rows = [row.split('\t') for row in item_types.item_list_bytes([value, other]).decode('utf-8').splitlines()]
        self.assertEqual([row[0] for row in rows], ['i_0123456789ac', 'i_0123456789ab'])
        self.assertEqual(rows[1][2:4], ['agent', '2026-11-02'])
        self.assertEqual(value, original)

    def test_codepoint_range_integral_number_convention_and_boolean_refusal(self):
        value = self.item()
        value['quotes'][0].update(start=1.0, end=3.0)
        self.assertEqual(item_types.parse_item(item_types.item_bytes(value)), value)
        for start, end in ((True, 3), (1, False), (1.5, 3.5), (-1, 1), (3, 1), (1, 4)):
            value = self.item()
            value['quotes'][0].update(start=start, end=end)
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                item_types.item_bytes(value)
        value['quotes'][0].update(start=0, end=2, words='e\u0301')
        self.assertEqual(item_types.parse_item(item_types.item_bytes(value))['quotes'][0]['words'], 'e\u0301')

    def test_quote_log_is_stem_not_filename_or_path(self):
        for name in ('codex-0123456789abcdef.jsonl', '../codex-0123456789abcdef', 'Codex-0123456789abcdef'):
            value = self.item()
            value['quotes'][0]['log'] = name
            with self.subTest(name=name), self.assertRaises(ValueError):
                item_types.item_bytes(value)

    def test_unknown_duplicate_missing_fields_and_invalid_times_fail(self):
        raw = json.dumps(ITEM, ensure_ascii=False).encode('utf-8')
        bad = [raw.replace(b'{"id":', b'{"id":"i_0123456789ac","id":', 1),
               json.dumps(self.item(extra=True)).encode('utf-8')]
        for field in ('id', 'title', 'quotes', 'saved'):
            value = self.item()
            del value[field]
            bad.append(json.dumps(value).encode('utf-8'))
        for data in bad:
            with self.assertRaises(ValueError):
                item_types.parse_item(data)
        for at in ('2026-02-30T03:00:00.000Z', '2026-11-04T03:00:00Z', '2026-11-04T03:00:00.000+00:00'):
            with self.subTest(at=at), self.assertRaises(ValueError):
                item_types.item_bytes(self.item(saved=at))

    def test_list_uses_current_date_then_id_and_replaces_only_title_tabs(self):
        values = [self.item(id='i_0123456789ac'), self.item(), self.item(id='i_0123456789ad'),
                  self.item(id='i_0123456789ae', status='undone')]
        values[0]['quotes'][0]['said'] = '2026-11-04T22:00:00.000Z'
        values[2]['quotes'][0]['said'] = '2026-11-05T00:00:00.000Z'
        lines = [row.split('\t') for row in item_types.item_list_bytes(values).decode('utf-8').splitlines()]
        self.assertEqual([row[0] for row in lines], ['i_0123456789ad','i_0123456789ab','i_0123456789ac'])
        self.assertTrue(all(len(row) == 5 and row[-1] == '원문 제목' for row in lines))
        self.assertEqual(item_types.item_list_bytes([]), b'')
        with self.assertRaises(ValueError):
            item_types.item_list_bytes([self.item(), self.item()])

    def test_pins_keep_off_records_and_reject_duplicate_ids_or_nonboolean_on(self):
        pin = {'item': ITEM['id'], 'on': False, 'at': AT, 'device': DEVICE}
        value = {'pins': [pin]}
        self.assertEqual(item_types.parse_pins(item_types.pins_bytes(value)), value)
        for bad in ({'pins': [pin, pin]}, {'pins': [dict(pin, on=0)]}, {'pins': [dict(pin, extra=1)]}):
            with self.assertRaises(ValueError):
                item_types.pins_bytes(bad)

    def test_notice_field_order_ids_and_count_range(self):
        value = {'at': AT, 'kind': 'pin-moved', 'item': ITEM['id'], 'to': 'i_0123456789ac'}
        self.assertEqual(item_types.parse_notice(item_types.notice_bytes(value)), value)
        conflict = {'at': AT, 'kind': 'conflict', 'candidate': 'c_0123456789ab', 'shown': 3.0}
        self.assertEqual(item_types.parse_notice(item_types.notice_bytes(conflict)), conflict)
        for count in (-1, 4, True, 1.5):
            with self.subTest(count=count), self.assertRaises(ValueError):
                item_types.notice_bytes(dict(conflict, shown=count))

    def test_codecs_do_no_file_io_or_global_c1_registry_mutation(self):
        fields = copy.deepcopy(base.FIELDS)
        with mock.patch('builtins.open', side_effect=AssertionError('unexpected I/O')), \
                mock.patch.object(Path, 'read_bytes', side_effect=AssertionError('unexpected I/O')), \
                mock.patch.object(Path, 'write_bytes', side_effect=AssertionError('unexpected I/O')):
            item_types.item_bytes(self.item())
            item_types.item_list_bytes([self.item()])
            item_types.pins_bytes({'pins': []})
            item_types.notice_bytes({'at': AT, 'kind': 'rebuilt'})
        self.assertEqual(base.FIELDS, fields)
