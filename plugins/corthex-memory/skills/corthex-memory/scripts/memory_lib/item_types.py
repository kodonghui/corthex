"""Pure TBL-010/012/014 types and TBL-015 bytes; no file or model access."""
import json
import re

from . import configuration, curation, diagnostics, format2, store

KINDS = {'decision', 'preference', 'lesson', 'reference', 'fact'}
STATUSES = {'current', 'superseded', 'withdrawn', 'undone'}
ITEM = re.compile(r'i_' + format2._DIGITS + r'\Z')
ENTRY = re.compile(r'e_' + format2._DIGITS + r'\Z')
ITEM_FIELDS = 'id kind title text quotes status superseded_by undone_by merges saved device changed'.split()
QUOTE_FIELDS = 'entry log device start end speaker said words'.split()
PIN_FIELDS = 'item on at device'.split()
NOTICE_FIELDS = 'at kind error item to candidate shown'.split()
BREAKS = '\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029'


def _document(data):
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError('record bytes required')
    return store.json_document(data)


def _text(value, limit=None, line=False):
    if not isinstance(value, str):
        raise ValueError('invalid record text')
    data = value.encode('utf-8')
    if limit is not None and len(data) > limit or line and any(c in value for c in BREAKS):
        raise ValueError('invalid record text')


def _quote(value):
    curation._shape(value, 'entry log device start end speaker said words')
    format2._id(value['entry'], ENTRY)
    format2._id(value['log'], diagnostics.LOG)
    format2._id(value['device'], store.DEVICE)
    curation._choice(value['speaker'], {'user', 'agent'})
    format2._time(value['said'])
    _text(value['words'], 2000)
    for name in ('start', 'end'):
        if not configuration.integer(value[name]) or value[name] < 0:
            raise ValueError('invalid quote range')
    if value['end'] < value['start'] or value['end'] - value['start'] != len(value['words']):
        raise ValueError('invalid quote range')


def parse_item(data):
    value = _document(data)
    curation._shape(value, 'id kind title text quotes status saved device',
                    'superseded_by undone_by merges changed')
    format2._id(value['id'], ITEM)
    curation._choice(value['kind'], KINDS)
    curation._choice(value['status'], STATUSES)
    _text(value['title'], 200, line=True)
    _text(value['text'], 4000)
    if not isinstance(value['quotes'], list) or not 1 <= len(value['quotes']) <= 20:
        raise ValueError('invalid item quotes')
    for quote in value['quotes']:
        _quote(quote)
    for field in ('superseded_by', 'undone_by'):
        if field in value:
            format2._id(value[field], ITEM if field == 'superseded_by' else format2._RUN)
    if 'merges' in value:
        if not isinstance(value['merges'], list):
            raise ValueError('invalid merged item IDs')
        for item in value['merges']:
            format2._id(item, ITEM)
    format2._time(value['saved'])
    format2._id(value['device'], store.DEVICE)
    if 'changed' in value:
        format2._time(value['changed'])
    return value


def parse_pins(data):
    value = _document(data)
    curation._shape(value, 'pins')
    if not isinstance(value['pins'], list):
        raise ValueError('invalid pins')
    seen = set()
    for pin in value['pins']:
        curation._shape(pin, 'item on at device')
        format2._id(pin['item'], ITEM)
        if not isinstance(pin['on'], bool) or pin['item'] in seen:
            raise ValueError('invalid pin')
        seen.add(pin['item'])
        format2._time(pin['at'])
        format2._id(pin['device'], store.DEVICE)
    return value


def parse_notice(data):
    value = _document(data)
    curation._shape(value, 'at kind', 'error item to candidate shown')
    format2._time(value['at'])
    curation._choice(value['kind'], {'curation-failed', 'consolidation-failed', 'rebuilt',
                                    'pin-moved', 'pin-dropped', 'conflict'})
    if 'error' in value:
        _text(value['error'])
    for name in ('item', 'to', 'candidate'):
        if name in value:
            format2._id(value[name], format2._CANDIDATE if name == 'candidate' else ITEM)
    if 'shown' in value and (not configuration.integer(value['shown']) or not 0 <= value['shown'] <= 3):
        raise ValueError('invalid notice count')
    return value


def _raw(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')


def _ordered(value, fields):
    return {name: value[name] for name in fields if name in value}


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode('utf-8')


def item_bytes(value):
    value = _ordered(parse_item(_raw(value)), ITEM_FIELDS)
    value['quotes'] = [_ordered(q, QUOTE_FIELDS) for q in value['quotes']]
    return _bytes(value)


def pins_bytes(value):
    value = parse_pins(_raw(value))
    return _bytes({'pins': [_ordered(pin, PIN_FIELDS) for pin in value['pins']]})


def notice_bytes(value):
    return _bytes(_ordered(parse_notice(_raw(value)), NOTICE_FIELDS))


def item_list_bytes(items):
    records = [parse_item(_raw(value)) for value in items]
    if len({value['id'] for value in records}) != len(records):
        raise ValueError('duplicate item ID')
    current = sorted((value for value in records if value['status'] == 'current'), key=lambda v: v['id'])
    current.sort(key=lambda v: v['quotes'][0]['said'][:10], reverse=True)
    return ''.join('\t'.join((value['id'], value['kind'], value['quotes'][0]['speaker'],
                               value['quotes'][0]['said'][:10], value['title'].replace('\t', ' '))) + '\n'
                   for value in current).encode('utf-8')
