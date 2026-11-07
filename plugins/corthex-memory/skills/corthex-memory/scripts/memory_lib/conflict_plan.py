"""Pure TBL-120 changes: open candidates and settle them (SPEC-016, SPEC-143).

A layer writer reads conflicts.json and the items under the layer lease, plans
here and checks the result with `changes`. Each new candidate's showing count
is then set to zero durably (TBL-010, TASK-092) before conflicts.json is
published after the items that it names. Nothing here reads or writes a file.
"""
import copy

from . import base, conflict_types, curation, format2, item_types

FIELDS = 'id items at run by status closed'.split()


def _parsed(value):
    return conflict_types.parse_conflicts(item_types._raw(value))


def conflicts_bytes(value):
    """conflicts.json as the layer records are written: candidates in the order they were recorded."""
    value = _parsed(value)
    return item_types._bytes({'candidates': [item_types._ordered(c, FIELDS) for c in value['candidates']]})


def settle(conflicts, current, at):
    """Settle each open candidate that names an item not in `current`; the new value and the settled IDs.

    `current` holds the IDs of the items that are current once the writer's
    changes are applied; an item that is gone or private is not current.
    """
    format2._time(at)
    current = frozenset(current)
    value = copy.deepcopy(_parsed(conflicts))
    settled = []
    for candidate in value['candidates']:
        if candidate['status'] == 'open' and not set(candidate['items']) <= current:
            candidate.update(status='settled', closed=at)
            settled.append(candidate['id'])
    return value, settled


def record(conflicts, pairs, items, *, at, run, by, make_id=None):
    """Open one candidate for each new unordered pair of two current items; the new value and the new IDs.

    `pairs` are proposed in order and `items` maps item IDs to their records
    once the writer's changes are applied. A pair that names one item twice,
    an item that is not current, or a pair that an open candidate already
    names in either order, is left out. The newer item comes first, by the
    time it was saved, then by ID; candidate IDs come from the code.
    """
    format2._time(at)
    format2._id(run, format2._RUN)
    curation._choice(by, {'curate', 'consolidate'})
    make_id = base.new_id if make_id is None else make_id
    value = copy.deepcopy(_parsed(conflicts))
    known = {candidate['id'] for candidate in value['candidates']}
    opened = {frozenset(candidate['items']) for candidate in value['candidates'] if candidate['status'] == 'open'}
    added = []
    for first, second in pairs:
        pair = frozenset((first, second))
        if len(pair) != 2 or pair in opened or any(
                item not in items or items[item]['status'] != 'current' for item in pair):
            continue
        identifier = make_id('c')
        format2._id(identifier, format2._CANDIDATE)
        if identifier in known:
            raise ValueError('code-made ID collision')
        ordered = sorted(pair)
        ordered.sort(key=lambda item: items[item]['saved'], reverse=True)
        value['candidates'].append({'id': identifier, 'items': ordered, 'at': at, 'run': run, 'by': by,
                                    'status': 'open'})
        known.add(identifier)
        opened.add(pair)
        added.append(identifier)
    _parsed(value)
    return value, added


def changes(before, after, current):
    """Check a TBL-120 publication; its bytes, the candidates it adds and those it closes.

    `after` keeps every candidate of `before` in place. A candidate may
    change only from open to settled or dismissed, with its closing time; new
    candidates follow, open. Once the writer's changes are applied, `current`
    holds the current item IDs, and every open candidate names two of them.
    """
    before, after, current = _parsed(before), _parsed(after), frozenset(current)
    old, new = before['candidates'], after['candidates']
    if len(new) < len(old):
        raise ValueError('conflict candidates are retained')
    closed = []
    for was, now in zip(old, new):
        if now == was:
            continue
        kept = {name: now.get(name) for name in FIELDS if name not in ('status', 'closed')}
        if (was['status'] != 'open' or now['status'] == 'open' or
                kept != {name: was.get(name) for name in kept}):
            raise ValueError('only an open candidate closes')
        closed.append(now['id'])
    added = []
    for candidate in new[len(old):]:
        if candidate['status'] != 'open':
            raise ValueError('new conflict candidates are open')
        added.append(candidate['id'])
    if any(candidate['status'] == 'open' and not set(candidate['items']) <= current for candidate in new):
        raise ValueError('an open conflict candidate names an item that is not current')
    return conflicts_bytes(after), added, closed
