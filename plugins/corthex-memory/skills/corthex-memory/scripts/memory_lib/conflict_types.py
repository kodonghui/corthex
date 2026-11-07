"""Pure TBL-120 conflict candidate records: item IDs only, never text.

Publication, settlement and showing counts belong to their writers
(TASK-086, TASK-070, TASK-092); this module reads and orders records.
"""
from . import curation, format2, item_types

STATUSES = {'open', 'settled', 'dismissed'}


def _candidate(value):
    curation._shape(value, 'id items at run by status', 'closed')
    format2._id(value['id'], format2._CANDIDATE)
    pair = value['items']
    if not isinstance(pair, list) or len(pair) != 2 or pair[0] == pair[1]:
        raise ValueError('invalid conflict candidate items')
    for item in pair:
        format2._id(item, item_types.ITEM)
    format2._time(value['at'])
    format2._id(value['run'], format2._RUN)
    curation._choice(value['by'], {'curate', 'consolidate'})
    curation._choice(value['status'], STATUSES)
    # An open candidate has no closing time; a closed one keeps when it closed.
    if (value['status'] == 'open') == ('closed' in value):
        raise ValueError('invalid conflict candidate closing')
    if 'closed' in value:
        format2._time(value['closed'])


def parse_conflicts(data):
    """Strictly read conflicts.json; one open candidate per unordered pair."""
    value = item_types._document(data)
    curation._shape(value, 'candidates')
    if not isinstance(value['candidates'], list):
        raise ValueError('invalid conflict candidates')
    seen, pairs = set(), set()
    for candidate in value['candidates']:
        _candidate(candidate)
        if candidate['id'] in seen:
            raise ValueError('duplicate conflict candidate')
        seen.add(candidate['id'])
        if candidate['status'] == 'open':
            pair = frozenset(candidate['items'])
            if pair in pairs:
                raise ValueError('duplicate open conflict pair')
            pairs.add(pair)
    return value


def open_candidates(value):
    """Open candidates in the rotation order of SPEC-015: time, then ID."""
    value = parse_conflicts(item_types._raw(value))
    return sorted((c for c in value['candidates'] if c['status'] == 'open'), key=lambda c: (c['at'], c['id']))
