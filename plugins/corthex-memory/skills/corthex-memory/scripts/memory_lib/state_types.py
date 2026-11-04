"""Pure C2 state/removed/history types; never an authorization to restore.

Exact history hashes cover original complete JSONL bytes including LF. A run's
actual complete mutation links, privacy guards and revisions remain separate.
"""
import copy
from dataclasses import dataclass, field
import hashlib
import json
import re

from . import configuration, curation, format2, item_types, store

LINE = re.compile(r's_' + format2._DIGITS + r'\Z')
CITE = re.compile(r'[ie]_' + format2._DIGITS + r'\Z')
PARTS = ('goal', 'decisions', 'progress', 'blockers', 'next')
LINE_FIELDS = 'id part pos text cites at device'.split()
REMOVED_FIELDS = 'id at device kind restored_by restored_at'.split()
HISTORY_FIELDS = 'at run epoch generation line part pos op text cites why device'.split()


def _integer(value):
    return type(value) is int or isinstance(value, float) and configuration.integer(value)


def _cites(value, minimum=0):
    if not isinstance(value, list) or len(value) < minimum:
        raise ValueError('invalid state citations')
    for cite in value:
        format2._id(cite, CITE)


def _position(value):
    curation._choice(value['part'], set(PARTS))
    if not _integer(value['pos']):
        raise ValueError('invalid state position')


def parse_state(data):
    value = item_types._document(data)
    curation._shape(value, 'lines')
    if not isinstance(value['lines'], list):
        raise ValueError('invalid state lines')
    seen = set()
    for line in value['lines']:
        curation._shape(line, 'id part pos text cites at device')
        format2._id(line['id'], LINE)
        if line['id'] in seen:
            raise ValueError('duplicate state line')
        seen.add(line['id'])
        _position(line)
        item_types._text(line['text'], line=True)
        _cites(line['cites'], 1)
        format2._time(line['at'])
        format2._id(line['device'], store.DEVICE)
    return value


def parse_removed(data):
    value = item_types._document(data)
    curation._shape(value, 'removed')
    if not isinstance(value['removed'], list):
        raise ValueError('invalid removed lines')
    for marker in value['removed']:
        curation._shape(marker, 'id at device', 'kind restored_by restored_at')
        format2._id(marker['id'], LINE)
        format2._time(marker['at'])
        format2._id(marker['device'], store.DEVICE)
        if 'kind' in marker:
            curation._choice(marker['kind'], {'edit', 'privacy'})
        if 'restored_by' in marker:
            format2._id(marker['restored_by'], format2._RUN)
        if 'restored_at' in marker:
            format2._time(marker['restored_at'])
    return value


def _history(data):
    value = item_types._document(data)
    curation._shape(value, ' '.join(HISTORY_FIELDS))
    format2._time(value['at'])
    format2._id(value['run'], format2._RUN)
    format2._id(value['epoch'], format2._EPOCH)
    format2._revision(value['generation'])
    format2._id(value['line'], LINE)
    _position(value)
    curation._choice(value['op'], {'changed', 'removed', 'cut', 'stale', 'recited', 'undone'})
    item_types._text(value['text'], line=True)
    _cites(value['cites'])
    item_types._text(value['why'], 200)
    format2._id(value['device'], store.DEVICE)
    return value


def state_bytes(value):
    value = parse_state(item_types._raw(value))
    return item_types._bytes({'lines': [item_types._ordered(v, LINE_FIELDS) for v in value['lines']]})


def removed_bytes(value):
    value = parse_removed(item_types._raw(value))
    return item_types._bytes({'removed': [item_types._ordered(v, REMOVED_FIELDS) for v in value['removed']]})


def removal_marker(line_id, at, device, kind):
    """New removal metadata never copies a previous removal's restoration."""
    value = {'id': line_id, 'at': at, 'device': device, 'kind': kind}
    return parse_removed(item_types._raw({'removed': [value]}))['removed'][0]


def history_record_bytes(value):
    value = item_types._ordered(_history(item_types._raw(value)), HISTORY_FIELDS)
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')


@dataclass(frozen=True)
class HistoryRecord:
    raw: bytes = field(repr=False)
    _value: dict = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        if not isinstance(self.raw, (bytes, bytearray)) or not self.raw.endswith(b'\n') or b'\n' in self.raw[:-1]:
            raise ValueError('complete history record required')
        object.__setattr__(self, 'raw', bytes(self.raw))
        object.__setattr__(self, '_value', _history(self.raw))

    @property
    def value(self):
        return copy.deepcopy(self._value)

    @property
    def sha256(self):
        return hashlib.sha256(self.raw).hexdigest()


def parse_history(data):
    if not isinstance(data, (bytes, bytearray)) or data and not data.endswith(b'\n'):
        raise ValueError('complete history stream required')
    # Finish the entire strict validation before exposing any record; a valid
    # prefix cannot hide a damaged, incomplete or blank suffix record.
    return tuple(HistoryRecord(row + b'\n') for row in bytes(data).split(b'\n')[:-1])


def validity_view(state, removed, items, private_cites):
    """Read-only input view. The owner supplies one complete consistent snapshot.

    Missing/ambiguous removal kinds never grant archival or restoration rights.
    Existing verified restoration metadata is independent of run-log retention.
    """
    state = parse_state(item_types._raw(state))
    removed = parse_removed(item_types._raw(removed))
    if not isinstance(items, dict):
        raise ValueError('typed item mapping required')
    current = set()
    for item_id, item in items.items():
        value = item_types.parse_item(item_types._raw(item))
        if value['id'] != item_id:
            raise ValueError('item mapping identity mismatch')
        if value['kind'] == 'decision' and value['status'] == 'current':
            current.add(item_id)
    private = set(private_cites)
    for cite in private:
        format2._id(cite, CITE)
    markers = {}
    for marker in removed['removed']:
        markers.setdefault(marker['id'], []).append(marker)
    lines, hidden = [], []
    for line in state['lines']:
        group = markers.get(line['id'], [])
        reason = None
        if private.intersection(line['cites']) or any(v.get('kind') == 'privacy' for v in group):
            reason = 'privacy'
        elif len(group) > 1 or any('kind' not in v for v in group):
            reason = 'unknown-removal'
        elif group and not {'restored_by', 'restored_at'} <= set(group[0]):
            reason = 'removed'
        elif line['part'] == 'decisions' and not current.intersection(line['cites']):
            reason = 'stale'
        if reason:
            hidden.append({'id': line['id'], 'why': reason})
        else:
            lines.append(line)
    lines.sort(key=lambda v: (PARTS.index(v['part']), v['pos'], v['id']))
    return {'lines': lines, 'hidden': hidden}
