"""Partial TASK077 pure proof on fabricated values; no storage activation."""
import copy
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

from _common import ROOT
sys.path.insert(0, str(ROOT/'plugins/corthex-memory/skills/corthex-memory/scripts'))
from memory_lib import base, state_types
from test_memory_item_types import AT, DEVICE, ITEM

LINE = {'id':'s_0123456789ab','part':'decisions','pos':1,'text':'앞선 내용',
        'cites':[ITEM['id']],'at':AT,'device':DEVICE}
REMOVED = {'id':LINE['id'],'at':AT,'device':DEVICE,'kind':'edit'}
HISTORY = {'at':AT,'run':'r_0123456789ab','epoch':'a'*32,'generation':1,'line':LINE['id'],
           'part':LINE['part'],'pos':LINE['pos'],'op':'changed','text':LINE['text'],
           'cites':LINE['cites'],'why':'한 가지 변경','device':DEVICE}


class StateTypesTest(unittest.TestCase):
    def line(self, **changes):
        value = copy.deepcopy(LINE)
        value.update(changes)
        return value

    def history(self, **changes):
        value = copy.deepcopy(HISTORY)
        value.update(changes)
        return value

    def test_state_canonical_order_unicode_lf_and_input_order_are_preserved(self):
        first = self.line(id='s_0123456789ac',pos=-1)
        value = {'lines':[first,self.line()]}
        original = copy.deepcopy(value)
        data = state_types.state_bytes(value)
        reversed_fields = {'lines':[dict(reversed(list(v.items()))) for v in value['lines']]}
        self.assertEqual(data,state_types.state_bytes(reversed_fields))
        self.assertEqual(state_types.parse_state(data),original)
        self.assertEqual(list(json.loads(data)['lines'][0]),['id','part','pos','text','cites','at','device'])
        self.assertEqual(value,original)
        self.assertIn('앞선'.encode('utf-8'),data)
        self.assertTrue(data.endswith(b'\n'))
        self.assertNotIn(b'\r',data)

    def test_positions_have_no_minimum_and_keep_integral_float_convention(self):
        for pos in (-100,0,2.0,10**400):
            self.assertEqual(state_types.parse_state(state_types.state_bytes({'lines':[self.line(pos=pos)]}))['lines'][0]['pos'],pos)
        for pos in (True,False,1.5,float('nan'),float('inf'),'1'):
            with self.subTest(pos=pos),self.assertRaises(ValueError):
                state_types.state_bytes({'lines':[self.line(pos=pos)]})

    def test_empty_text_duplicate_cites_and_post_merge_size_are_not_new_rejections(self):
        for text in ('','한'*1100):
            value = {'lines':[self.line(text=text,cites=[ITEM['id'],ITEM['id']])]}
            self.assertEqual(state_types.parse_state(state_types.state_bytes(value)),value)
        for text in ('x\ny','x\ry','x\u2028y'):
            with self.assertRaises(ValueError):
                state_types.state_bytes({'lines':[self.line(text=text)]})
        with self.assertRaises(ValueError):
            state_types.state_bytes({'lines':[self.line(cites=[])]})

    def test_duplicate_state_id_unknown_fields_bad_ids_and_times_fail(self):
        for lines in ([self.line(),self.line()], [self.line(extra=True)],
                      [self.line(id=ITEM['id'])], [self.line(cites=['not-an-id'])],
                      [self.line(at='2026-02-30T03:00:00.000Z')]):
            with self.assertRaises(ValueError):
                state_types.state_bytes({'lines':lines})
        data = state_types.state_bytes({'lines':[self.line()]})
        with self.assertRaises(ValueError):
            state_types.parse_state(data.replace(b'"lines":',b'"lines":[],"lines":',1))

    def test_removed_legacy_partial_restoration_and_duplicate_markers_round_trip(self):
        legacy = {key:value for key,value in REMOVED.items() if key!='kind'}
        values = [legacy,dict(REMOVED,restored_by='r_0123456789ab'),dict(REMOVED,restored_at=AT)]
        document = {'removed':values}
        self.assertEqual(state_types.parse_removed(state_types.removed_bytes(document)),document)
        full = dict(REMOVED,restored_by='r_0123456789ab',restored_at=AT)
        self.assertEqual(list(json.loads(state_types.removed_bytes({'removed':[full]}))['removed'][0]),
                         ['id','at','device','kind','restored_by','restored_at'])
        for marker in (dict(REMOVED,kind='other'),dict(REMOVED,restored_by='bad'),dict(REMOVED,restored_at='bad')):
            with self.assertRaises(ValueError):
                state_types.removed_bytes({'removed':[marker]})

    def test_privacy_dominates_restoration_fields_and_other_current_decision_cites(self):
        marker = dict(REMOVED,kind='privacy',restored_by='r_0123456789ab',restored_at=AT)
        state = {'lines':[self.line()]}
        result = state_types.validity_view(state,{'removed':[marker]},{ITEM['id']:ITEM},[])
        self.assertEqual(result,{'lines':[],'hidden':[{'id':LINE['id'],'why':'privacy'}]})
        line = self.line(cites=[ITEM['id'],'e_0123456789ab'])
        result = state_types.validity_view({'lines':[line]},{'removed':[]},{ITEM['id']:ITEM},['e_0123456789ab'])
        self.assertEqual(result['hidden'][0]['why'],'privacy')

    def test_legacy_or_ambiguous_removal_is_not_ordinary_stale_or_restoration(self):
        legacy = {key:value for key,value in REMOVED.items() if key!='kind'}
        restored = dict(REMOVED,restored_by='r_0123456789ab',restored_at=AT)
        for markers in ([legacy],[restored,restored]):
            result = state_types.validity_view({'lines':[self.line()]},{'removed':markers},{ITEM['id']:ITEM},[])
            self.assertEqual(result['hidden'],[{'id':LINE['id'],'why':'unknown-removal'}])
        result = state_types.validity_view({'lines':[self.line()]},{'removed':[dict(REMOVED,restored_by='r_0123456789ab')]},{ITEM['id']:ITEM},[])
        self.assertEqual(result['hidden'][0]['why'],'removed')

    def test_verified_restoration_does_not_depend_on_retained_run_log(self):
        marker = dict(REMOVED,restored_by='r_0123456789ab',restored_at='2026-11-05T00:00:00.000Z')
        result = state_types.validity_view({'lines':[self.line()]},{'removed':[marker]},{ITEM['id']:ITEM},[])
        self.assertEqual(result,{'lines':[self.line()],'hidden':[]})

    def test_new_removal_never_reuses_previous_restoration_metadata(self):
        old = dict(REMOVED,restored_by='r_0123456789ab',restored_at=AT)
        at = '2026-11-05T00:00:00.000Z'
        new = state_types.removal_marker(LINE['id'],at,DEVICE,'edit')
        self.assertEqual(new,dict(REMOVED,at=at))
        self.assertIn('restored_by',old)
        result = state_types.validity_view({'lines':[self.line()]},{'removed':[new]},{ITEM['id']:ITEM},[])
        self.assertEqual(result['hidden'][0]['why'],'removed')

    def test_decisions_need_current_decision_items_but_other_parts_do_not_reread_raw(self):
        for item in (dict(ITEM,kind='fact'),dict(ITEM,status='withdrawn'),dict(ITEM,status='undone')):
            result = state_types.validity_view({'lines':[self.line()]},{'removed':[]},{ITEM['id']:item},[])
            self.assertEqual(result['hidden'][0]['why'],'stale')
        agent = copy.deepcopy(ITEM)
        agent['quotes'][0]['speaker']='agent'
        result = state_types.validity_view({'lines':[self.line()]},{'removed':[]},{ITEM['id']:agent},[])
        self.assertEqual(result['lines'],[self.line()])
        line = self.line(part='goal',cites=['e_0123456789ab'])
        self.assertEqual(state_types.validity_view({'lines':[line]},{'removed':[]},{},[])['lines'],[line])

    def test_view_sorts_semantic_order_without_mutating_state_or_items(self):
        state = {'lines':[self.line(part='next'),self.line(id='s_0123456789ac',part='goal',pos=-1)]}
        items = {ITEM['id']:copy.deepcopy(ITEM)}
        original = copy.deepcopy((state,items))
        result = state_types.validity_view(state,{'removed':[]},items,[])
        self.assertEqual([v['part'] for v in result['lines']],['goal','next'])
        self.assertEqual((state,items),original)
        result['lines'][0]['text']='changed detached output'
        self.assertEqual((state,items),original)

    def test_same_part_positions_and_equal_position_id_ties_are_ordered(self):
        state = {'lines':[self.line(id='s_0123456789ae',part='goal',pos=2),
                          self.line(id='s_0123456789ac',part='goal',pos=1.0),
                          self.line(part='goal',pos=1),
                          self.line(id='s_0123456789ad',part='goal',pos=-1)]}
        original = copy.deepcopy(state)
        result = state_types.validity_view(state,{'removed':[]},{},[])
        self.assertEqual([v['id'] for v in result['lines']],
                         ['s_0123456789ad','s_0123456789ab','s_0123456789ac','s_0123456789ae'])
        self.assertEqual(state,original)

    def test_history_canonical_fields_utf8_why_limit_and_no_empty_cites_minimum(self):
        value = self.history(cites=[],why='한'*66)
        data = state_types.history_record_bytes(value)
        self.assertEqual(list(json.loads(data)),
                         ['at','run','epoch','generation','line','part','pos','op','text','cites','why','device'])
        self.assertEqual(state_types.HistoryRecord(data).value,value)
        for why in ('','reason\nnext'):
            state_types.history_record_bytes(self.history(why=why))
        with self.assertRaises(ValueError):
            state_types.history_record_bytes(self.history(why='한'*67))
        for generation in (True,-1,1.0):
            with self.assertRaises(ValueError):
                state_types.history_record_bytes(self.history(generation=generation))

    def test_history_exact_raw_hash_includes_lf_and_preserves_noncanonical_bytes(self):
        data = state_types.history_record_bytes(self.history())
        record = state_types.HistoryRecord(data)
        self.assertEqual(record.sha256,hashlib.sha256(data).hexdigest())
        self.assertNotEqual(record.sha256,hashlib.sha256(data[:-1]).hexdigest())
        spaced = b' '+data[:-1]+b'\r\n'
        other = state_types.HistoryRecord(spaced)
        self.assertEqual(other.value,record.value)
        self.assertEqual(other.raw,spaced)
        self.assertNotEqual(other.sha256,record.sha256)

    def test_history_strict_full_stream_rejects_damaged_or_incomplete_suffix(self):
        data = state_types.history_record_bytes(self.history())
        self.assertEqual(state_types.parse_history(b''),())
        self.assertEqual(len(state_types.parse_history(data+data)),2)
        for stream in (data[:-1],data+b'{broken\n',data+b'{broken',data+b'\n',b'\xef\xbb\xbf'+data):
            with self.subTest(stream=stream[-20:]),self.assertRaises((ValueError,UnicodeError)):
                state_types.parse_history(stream)

    def test_history_record_is_detached_immutable_and_does_not_expose_body_in_repr(self):
        data = bytearray(state_types.history_record_bytes(self.history()))
        record = state_types.HistoryRecord(data)
        digest = record.sha256
        data[0]=ord(' ')
        record.value['text']='caller mutation'
        self.assertEqual(record.value,HISTORY)
        self.assertEqual(record.sha256,digest)
        self.assertNotIn(HISTORY['text'],repr(record))
        with self.assertRaises(FrozenInstanceError):
            record.raw=b'changed'

    def test_pure_types_and_view_do_no_file_io_or_c1_registry_changes(self):
        fields = copy.deepcopy(base.FIELDS)
        with mock.patch('builtins.open',side_effect=AssertionError('unexpected file I/O')), \
                mock.patch.object(Path,'read_bytes',side_effect=AssertionError('unexpected file I/O')), \
                mock.patch.object(Path,'write_bytes',side_effect=AssertionError('unexpected file I/O')):
            state_types.state_bytes({'lines':[self.line()]})
            state_types.removed_bytes({'removed':[REMOVED]})
            state_types.parse_history(state_types.history_record_bytes(self.history()))
            state_types.validity_view({'lines':[self.line()]},{'removed':[]},{ITEM['id']:ITEM},[])
        self.assertEqual(base.FIELDS,fields)
