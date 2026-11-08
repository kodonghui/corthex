"""Consolidation's changes to the current state (SPEC-019, SPEC-017; TASK-089, TASK-090).

`recite` and `rewrite` are pure. Each works out the new state and one
operation for each line that changes, which the TBL-013 publisher of TASK-077
checks against the exact physical difference before it appends each earlier
version to TBL-119; `apply_recite` and `apply_rewrite` publish them under the
curation and layer leases.

- After a merge, each line that cites a merged item cites the item that merged
  it instead, in a `recited` change. An item is followed while the item that
  superseded it merged it, up to a current item, so a line that an earlier
  merge left behind, when its change could not be written, is recited too.
  A replacement by curation is never followed: the curator changes those
  lines itself (SPEC-017).
- The last request's answer (state-1) gives the whole current state, in the
  same five parts. A line that names a line of the request in `keeps` keeps
  that line's ID, and its time when its text and citations stay; an empty
  `keeps` adds a line. A line cites items of the request, or entries that the
  request's state already cites, and cites at least one; `changes` name
  nothing here, since the request has no item changes. A line under
  decisions in force cites a current decision item. A line that fails a
  check is dropped and counted once, under the first check it fails:
  `not-in-request`, `duplicate` (every line that keeps a line named more than
  once), `shape`, `cites` or `decision`. The line that a dropped line keeps
  stays as it was, so a bad line never loses an existing one. A line of the
  request that the answer leaves out is removed with the reason
  `consolidation`; five empty parts keep the state as it is.
- As for curation, lines hidden for privacy or a removal stay for their own
  owners, a decision line without a current decision item is removed as
  `stale`, and whole lines are cut while the text is 3,000 UTF-8 bytes or
  more: lines that stay as they were first, then changed lines and then
  added ones. A cut here does not make consolidation due again.

A failure to append a required earlier version keeps the whole state as it
was. The worker that calls these (TASK-089) is not wired to a hook or command
before the 0.3.0 activation.
"""
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from . import base, format2, item_types, revision_io, state_edits, state_types, store

REASONS = format2.EDIT_REASONS
RECITED = 'recited'
CONSOLIDATION = 'consolidation'


@dataclass(frozen=True)
class Planned:
    proposal: object   # {'state', 'operations'} for the TBL-013 publisher; None when the state stays
    dropped: dict      # reason -> lines dropped for it; only reasons that occurred
    added: tuple       # IDs of the added lines that the new state keeps, in the answer's order
    removed: tuple     # IDs of the request's lines that the answer left out
    cut: tuple         # IDs of existing lines cut to keep the text below 3,000 bytes
    cut_adds: int      # added lines cut for the same reason; they leave no history
    stale: tuple       # IDs of decision lines removed for want of a current decision item


def _checked(state, removed, items, private, at, device):
    format2._time(at)
    format2._id(device, store.DEVICE)
    state = state_types.parse_state(item_types._raw(state))
    removed = state_types.parse_removed(item_types._raw(removed))
    view = state_types.validity_view(state, removed, items, private)
    physical = {line['id']: line for line in state['lines']}
    hidden = {value['id']: value['why'] for value in view['hidden']}
    # Lines hidden for privacy or a removal stay as they are, for their own owners.
    touchable = {line for line in physical if hidden.get(line, 'stale') == 'stale'}
    return physical, touchable


def _ordered(lines):
    return sorted(lines, key=lambda v: (state_types.PARTS.index(v['part']), v['pos'], v['id']))


def merged_by(items):
    """Item ID -> the current item that merged it, following merges; only items that a merge superseded."""
    found = {}
    for item, value in items.items():
        seen, at = set(), item
        while (at in items and items[at]['status'] == 'superseded' and at not in seen and
               at in items.get(items[at].get('superseded_by'), {}).get('merges', ())):
            seen.add(at)
            at = items[at]['superseded_by']
        if seen and at in items and items[at]['status'] == 'current':
            found[item] = at
    return found


def recite(*, state, removed, items, private, at, device):
    """The state with each merged item that a line cites replaced by the item that merged it; None when none does.

    `items` maps every item ID to its record after the merges; `private` holds
    the item and entry IDs that tombstones name.
    """
    physical, touchable = _checked(state, removed, items, private, at, device)
    moves = merged_by(items)
    lines, operations = [], []
    for line_id in sorted(physical):
        line = physical[line_id]
        cites = list(dict.fromkeys(moves.get(cite, cite) for cite in line['cites']))
        if line_id in touchable and cites != line['cites']:
            lines.append(dict(line, cites=cites, at=at, device=device))
            operations.append({'id': line_id, 'op': 'recited', 'why': RECITED})
        else:
            lines.append(line)
    if not operations:
        return None
    return {'state': {'lines': _ordered(lines)}, 'operations': operations}


def rewrite(answer, *, state, removed, items, private, lines, listed, at, device, make_id=None):
    """The new state and its operations for a state-1 answer's `state` (API-008).

    `answer` is the answer's `state` as decoded; `lines` the IDs of the
    request's state lines and `listed` the IDs of the items its list carried.
    `items` maps every item ID to its record and `private` holds the item and
    entry IDs that tombstones name; `state` and `removed` are the TBL-013
    records read under the layer lease.
    """
    make_id = base.new_id if make_id is None else make_id
    physical, touchable = _checked(state, removed, items, private, at, device)
    named = {line for line in lines if line in touchable}
    listed = set(listed)
    decisions = {item for item, value in items.items()
                 if value['kind'] == 'decision' and value['status'] == 'current'}
    entries = {cite for line in named for cite in physical[line]['cites'] if cite.startswith('e_')}
    parts = state_types.PARTS
    given = [(part, line) for part in parts for line in answer[part]]
    times = Counter(line['keeps'] for _, line in given if line['keeps'])
    dropped, sequences, values, added = Counter(), {part: [] for part in parts}, {}, []
    taken = set(physical) | {marker['id'] for marker in state_types.parse_removed(item_types._raw(removed))['removed']}

    def resolve(line):
        if line['changes']:
            return None
        found = [cite for cite in line['cites'] if cite in (listed if cite.startswith('i_') else entries)]
        if len(found) != len(line['cites']):
            return None
        return list(dict.fromkeys(found)) or None

    def keep(line_id):
        # The line that a dropped line keeps stays as it was, in its own part.
        if line_id not in values:
            values[line_id] = physical[line_id]
            sequences[physical[line_id]['part']].append(line_id)

    if not given:
        # Five empty parts keep the state as it is, as an answer without line edits does.
        for line_id in sorted(touchable, key=lambda i: (physical[i]['pos'], i)):
            sequences[physical[line_id]['part']].append(line_id)
            values[line_id] = physical[line_id]
    for part, line in given:
        kept, reason, cites = line['keeps'], None, None
        if kept and kept not in named:
            reason = 'not-in-request'
        elif kept and times[kept] > 1:
            reason = 'duplicate'
        elif not state_edits._one_line(line['text']):
            reason = 'shape'
        else:
            cites = resolve(line)
            if cites is None:
                reason = 'cites'
            elif part == 'decisions' and not decisions.intersection(cites):
                reason = 'decision'
        if reason is not None:
            dropped[reason] += 1
            if kept in named:
                keep(kept)
            continue
        if kept:
            old = physical[kept]
            if (old['text'], old['cites']) == (line['text'], cites):
                values[kept] = dict(old, part=part)
            else:
                values[kept] = dict(old, part=part, text=line['text'], cites=cites, at=at, device=device)
            sequences[part].append(kept)
            continue
        new = make_id('s')
        format2._id(new, state_types.LINE)
        if new in taken:
            raise ValueError('code-made ID collision')
        taken.add(new)
        values[new] = {'id': new, 'part': part, 'pos': None, 'text': line['text'], 'cites': cites, 'at': at,
                       'device': device}
        sequences[part].append(new)
        added.append(new)

    placed = set(values)
    removing = tuple(sorted(line for line in named if line not in placed))
    stale = tuple(line for part in parts for line in sequences[part]
                  if part == 'decisions' and not decisions.intersection(values[line]['cites']))
    # Hidden stale lines that the request could not carry go as curation removes them.
    stale += tuple(sorted(line for line in touchable - named - placed))
    gone = set(stale)
    remaining = {part: [line for line in sequences[part] if line not in gone] for part in parts}

    def tier(line):
        if line not in physical:
            return 2
        old = physical[line]
        return 0 if (old['text'], old['cites']) == (values[line]['text'], values[line]['cites']) else 1

    cut = state_edits.cap(remaining, lambda line: values[line]['text'], tier)
    result, operations = [], []
    for part in parts:
        order = remaining[part]
        positions = state_edits._positions(order, {line: physical[line]['pos'] for line in order
                                                   if line in physical and physical[line]['part'] == part})
        for line in order:
            value = dict(values[line], pos=positions[line])
            result.append(value)
            if line not in physical:
                operations.append({'id': line, 'op': 'added', 'why': ''})
            elif tier(line):
                operations.append({'id': line, 'op': 'changed', 'why': CONSOLIDATION})
            elif (value['part'], value['pos']) != (physical[line]['part'], physical[line]['pos']):
                operations.append({'id': line, 'op': 'changed', 'why': 'position'})
    for line in sorted(set(physical) - touchable):
        result.append(physical[line])
    for line in sorted(physical):
        if line in removing:
            operations.append({'id': line, 'op': 'removed', 'why': CONSOLIDATION})
        elif line in gone:
            operations.append({'id': line, 'op': 'stale', 'why': 'stale'})
        elif line in cut:
            operations.append({'id': line, 'op': 'cut', 'why': 'cut'})
    kept_adds = tuple(line for line in added if line not in cut)
    return Planned({'state': {'lines': _ordered(result)}, 'operations': operations} if operations else None,
                   {reason: dropped[reason] for reason in REASONS if dropped[reason]}, kept_adds, removing,
                   tuple(line for line in cut if line in physical), sum(line in added for line in cut), stale)


def _publish(memory, root, expected, plan, at, run, deadline):
    root = Path(root)
    format2._id(run, format2._RUN)
    revision_io.guard(memory, root, deadline, curator=True)
    sources, items, private, digests = state_edits._read(root)
    planned = plan(state_types.parse_state(sources['state.json']),
                   state_types.parse_removed(sources['state-removed.json']), items, private)
    proposal = planned if isinstance(planned, dict) or planned is None else planned.proposal
    if proposal is None:
        return planned, None, None, None
    result, held, progress = state_edits.publish(memory, root, expected, proposal, sources, digests, at=at, run=run,
                                                 deadline=deadline)
    return planned, result, held, progress


def apply_recite(memory, root, expected, *, at, run, deadline):
    """Recite the lines that cite merged items, under the curation and layer leases.

    Returns `held` (None, or the error that kept the state when a required
    earlier version could not be appended), the publisher's line effects and
    the latest progress, None when nothing changed. Lost leases and stale
    proofs raise.
    """
    def plan(state, removed, items, private):
        return recite(state=state, removed=removed, items=items, private=private, at=at, device=memory.device)
    _, result, held, progress = _publish(memory, root, expected, plan, at, run, deadline)
    if result is None:
        return {'held': held, 'lines': (), 'progress': progress}
    return {'held': None, 'lines': result['lines'], 'progress': result['progress']}


def apply_rewrite(memory, root, expected, answer, *, lines, listed, at, run, deadline, make_id=None):
    """Apply the last request's answer under the curation and layer leases (TASK-090).

    Returns the attempt's `state` (`new`, `kept` or `cut`), `held`, the lines
    dropped by reason, the added, removed, cut and stale line IDs, the
    publisher's line effects and the latest progress. Lost leases and stale
    proofs raise.
    """
    def plan(state, removed, items, private):
        return rewrite(answer, state=state, removed=removed, items=items, private=private, lines=lines,
                       listed=listed, at=at, device=memory.device, make_id=make_id)
    planned, result, held, progress = _publish(memory, root, expected, plan, at, run, deadline)
    outcome = {'state': 'kept', 'held': held, 'dropped': planned.dropped, 'added': (), 'removed': (), 'cut': (),
               'stale': (), 'lines': (), 'progress': progress}
    if result is None:
        # Every added line may be cut with nothing else to publish.
        return dict(outcome, state='cut' if held is None and planned.cut_adds else 'kept')
    return dict(outcome, state='cut' if planned.cut or planned.cut_adds else 'new', added=planned.added,
                removed=planned.removed, cut=planned.cut, stale=planned.stale, lines=result['lines'],
                progress=result['progress'])
