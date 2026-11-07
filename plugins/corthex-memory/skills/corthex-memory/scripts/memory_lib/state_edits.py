"""Curate-2 line edits of the current state (SPEC-017; TASK-087).

`plan` is pure. From the answer's `state` edits, what its request carried, the
items as the same answer's item changes left them (TASK-086) and the stored
state, it works out the new state and one operation for each line that
changes, which the TBL-013 publisher of TASK-077 checks against the exact
physical difference before it appends each earlier version to TBL-119.

- `change` and `remove` name lines of the request; an edit of an unknown
  line, and every edit of a line named more than once across both lists, is
  dropped and counted. A dropped change keeps the earlier line.
- A changed or added line cites items of the request, entries of the request
  or entries that the request's state already cites, and the items saved by
  the answer's changes, which it names by number. A line under decisions in
  force cites a current decision item.
- Unnamed lines keep their text, citations and time; a decision line left
  without a current decision item is removed as `stale`.
- The text of the lines stays below 3,000 UTF-8 bytes: whole lines are cut,
  the last line of each part in turn from next actions back to the goal, as
  SPEC-021 shortens the start summary from the end of each part. Lines that the answer
  did not name go first, then changed lines and then added ones, so that a
  cut loses as little as it can: the earlier text of an existing line stays
  in TBL-119, while an added line that is cut leaves nothing.
- Positions stay integers; a line moves only when an insertion needs room,
  and the move keeps its text, citations and time.

`apply` publishes the plan under the curation and layer leases. A failure to
append a required earlier version keeps the whole state, its adds included,
while the item changes that were already applied stay. The worker that calls
it (TASK-088) is not wired to a hook or command before the 0.3.0 activation.
"""
from collections import Counter
from dataclasses import dataclass
import hashlib
from pathlib import Path

from . import (base, fence_plan, files, format2, history_io, history_recovery, item_types, locks,
               request_inputs, revision_io, state_io, state_types, store)

# Why a line edit is dropped; each dropped edit counts once, under the first check it fails.
REASONS = ('not-in-request', 'duplicate', 'shape', 'limit', 'cites', 'decision')
STATE_BYTES = 3000
WHY_BYTES = 200


@dataclass(frozen=True)
class Planned:
    proposal: object   # {'state', 'operations'} for the TBL-013 publisher; None when the state stays
    dropped: dict      # reason -> line edits dropped for it; only reasons that occurred
    added: tuple       # IDs of the added lines that the new state keeps, in the answer's order
    cut: tuple         # IDs of existing lines cut to keep the text below 3,000 bytes
    cut_adds: int      # added lines cut for the same reason; they leave no history
    stale: tuple       # IDs of decision lines removed for want of a current decision item


def _encoded(text):
    try:
        return text.encode('utf-8')
    except UnicodeError:
        return None


def _one_line(text):
    data = _encoded(text)
    return data is not None and text.strip() != '' and not any(c in item_types.BREAKS for c in text)


def _reason(why):
    data = _encoded(why)
    return data is not None and len(data) <= WHY_BYTES


def _positions(order, old):
    """Integer positions for one part's lines in `order`; `old` maps existing IDs to theirs.

    Lines are shown by position and then ID, so an existing line keeps its
    position while it still sorts after the line before it. A new line takes
    the next position, and lines before the first existing one count down.
    """
    lead = 0
    while lead < len(order) and order[lead] not in old:
        lead += 1
    if lead == len(order):
        return {line: index for index, line in enumerate(order)}
    first = old[order[lead]]
    result = {order[index]: first - lead + index for index in range(lead)}
    previous = (result[order[lead - 1]], order[lead - 1]) if lead else None
    for line in order[lead:]:
        if line in old and (previous is None or (old[line], line) > previous):
            position = old[line]
        else:
            position = previous[0] + 1
        result[line] = position
        previous = (position, line)
    return result


def plan(edits, *, state, removed, items, private, sent, saved, at, device, make_id=None):
    """The new state and its operations for checked line edits.

    `edits` is the answer's `state` as decoded; `sent` what the request carried
    (`curator_answers.Sent`); `saved` the (change number, new item ID) pairs of
    the item changes applied first; `items` every item record by ID after them;
    `private` the item and entry IDs that tombstones name. `state` and
    `removed` are the TBL-013 records read under the layer lease.
    """
    make_id = base.new_id if make_id is None else make_id
    format2._time(at)
    format2._id(device, store.DEVICE)
    state = state_types.parse_state(item_types._raw(state))
    removed = state_types.parse_removed(item_types._raw(removed))
    view = state_types.validity_view(state, removed, items, private)
    physical = {line['id']: line for line in state['lines']}
    hidden = {value['id']: value['why'] for value in view['hidden']}
    # Lines hidden for privacy or a removal stay as they are, for their own owners.
    touchable = {line for line in physical if hidden.get(line, 'stale') == 'stale'}
    named = {line for line in sent.lines if line in touchable}
    decisions = {item for item, value in items.items()
                 if value['kind'] == 'decision' and value['status'] == 'current'}
    entries = set(sent.entries) | {cite for line in sent.lines if line in physical
                                   for cite in physical[line]['cites'] if cite.startswith('e_')}
    saved = dict(saved)
    dropped = Counter()

    def resolve(edit):
        found = []
        for cite in edit['cites']:
            if cite not in (sent.items if cite.startswith('i_') else entries):
                return None
            found.append(cite)
        for number in edit['changes']:
            if isinstance(number, bool) or number not in saved:
                return None
            found.append(saved[number])
        return list(dict.fromkeys(found)) or None

    def decided(part, cites):
        return part != 'decisions' or any(cite in decisions for cite in cites)

    times = Counter(edit['line'] for edit in edits['change'] + edits['remove'])

    def target(edit):
        if edit['line'] not in named:
            return 'not-in-request'
        return 'duplicate' if times[edit['line']] > 1 else None

    changed, removing = {}, {}
    for edit in edits['change']:
        reason, cites = target(edit), None
        if reason is None and not _one_line(edit['text']):
            reason = 'shape'
        if reason is None and not _reason(edit['why']):
            reason = 'limit'
        if reason is None:
            cites = resolve(edit)
            old = physical[edit['line']]
            reason = 'cites' if cites is None else None if decided(old['part'], cites) else 'decision'
        if reason is not None:
            dropped[reason] += 1
        elif (old['text'], old['cites']) != (edit['text'], cites):
            changed[edit['line']] = (dict(old, text=edit['text'], cites=cites, at=at, device=device), edit['why'])
    for edit in edits['remove']:
        reason = target(edit)
        if reason is None and not _reason(edit['why']):
            reason = 'limit'
        if reason is not None:
            dropped[reason] += 1
        else:
            removing[edit['line']] = edit['why']

    taken = set(physical) | {marker['id'] for marker in removed['removed']}
    sequences = {part: [line['id'] for line in sorted((physical[i] for i in touchable if physical[i]['part'] == part),
                                                      key=lambda v: (v['pos'], v['id']))]
                 for part in state_types.PARTS}
    added, last = {}, {}
    for edit in edits['add']:
        reason, cites = (None, resolve(edit)) if _one_line(edit['text']) else ('shape', None)
        if reason is None:
            reason = 'cites' if cites is None else None if decided(edit['part'], cites) else 'decision'
        if reason is not None:
            dropped[reason] += 1
            continue
        line = make_id('s')
        format2._id(line, state_types.LINE)
        if line in taken:
            raise ValueError('code-made ID collision')
        taken.add(line)
        added[line] = {'id': line, 'part': edit['part'], 'pos': None, 'text': edit['text'], 'cites': cites,
                       'at': at, 'device': device}
        anchor = edit['after']
        if anchor and (anchor not in named or physical[anchor]['part'] != edit['part']):
            anchor = None
        sequence, key = sequences[edit['part']], (edit['part'], anchor)
        if anchor is None:
            sequence.append(line)
        else:
            previous = last.get(key, anchor)
            sequence.insert(sequence.index(previous) + 1 if previous else 0, line)
        last[key] = line

    def current(line):
        return changed[line][0] if line in changed else added[line] if line in added else physical[line]

    stale = tuple(line for part in state_types.PARTS for line in sequences[part]
                  if line in physical and line not in removing and line not in changed and
                  not decided(part, physical[line]['cites']))
    gone = set(removing) | set(stale)
    remaining = {part: [line for line in sequences[part] if line not in gone] for part in state_types.PARTS}
    size = sum(len(current(line)['text'].encode('utf-8')) for lines in remaining.values() for line in lines)

    def tier(line):
        return 2 if line in added else 1 if line in changed else 0

    cut = []
    for level in (0, 1, 2):
        while size >= STATE_BYTES:
            found = False
            for part in reversed(state_types.PARTS):
                lines = [line for line in remaining[part] if tier(line) == level]
                if lines:
                    found = True
                    remaining[part].remove(lines[-1])
                    size -= len(current(lines[-1])['text'].encode('utf-8'))
                    cut.append(lines[-1])
                    if size < STATE_BYTES:
                        break
            if not found:
                break

    lines, operations = [], []
    for part in state_types.PARTS:
        order = remaining[part]
        positions = _positions(order, {line: physical[line]['pos'] for line in order if line in physical})
        for line in order:
            value = dict(current(line), pos=positions[line])
            lines.append(value)
            if line in added:
                operations.append({'id': line, 'op': 'added', 'why': ''})
            elif line in changed:
                operations.append({'id': line, 'op': 'changed', 'why': changed[line][1]})
            elif value['pos'] != physical[line]['pos']:
                operations.append({'id': line, 'op': 'changed', 'why': 'position'})
    for line in sorted(set(physical) - touchable):
        lines.append(physical[line])
    for line in sorted(physical):
        if line in removing:
            operations.append({'id': line, 'op': 'removed', 'why': removing[line]})
        elif line in stale:
            operations.append({'id': line, 'op': 'stale', 'why': 'stale'})
        elif line in cut:
            operations.append({'id': line, 'op': 'cut', 'why': 'cut'})
    lines.sort(key=lambda v: (state_types.PARTS.index(v['part']), v['pos'], v['id']))
    kept = tuple(line for line in added if line not in cut)
    return Planned({'state': {'lines': lines}, 'operations': operations} if operations else None,
                   {reason: dropped[reason] for reason in REASONS if dropped[reason]}, kept,
                   tuple(line for line in cut if line in physical), sum(line in added for line in cut), stale)


def _read(root):
    """The state, removed lines, items and privacy facts, with the digests the publisher binds."""
    folder = root / 'layer'
    try:
        sources = {name: (folder / name).read_bytes() for name in ('state.json', 'state-removed.json')}
    except FileNotFoundError:
        raise files.RestoreNeeded() from None
    items, private, digests = {}, set(), {}
    for item, data in request_inputs._named(folder / 'items'):
        value = item_types.parse_item(data)
        if value['id'] != item:
            raise ValueError('item file name differs from its ID')
        items[item] = value
        digests['items/' + item + '.json'] = hashlib.sha256(data).hexdigest()
    for item, data in request_inputs._named(folder / 'tombstones'):
        private.update(history_recovery._tombstone(data, item, root.name))
        digests['tombstones/' + item + '.json'] = hashlib.sha256(data).hexdigest()
    return sources, items, frozenset(private), digests


def _held(failure):
    """The error's name when a failure before any publication left the state as it was."""
    if failure.attempted:
        return None
    chain, error = [], failure.__cause__
    while error is not None:
        chain.append(error)
        error = error.__cause__
    if not chain or any(isinstance(error, (locks.LostLock, fence_plan.Stale)) for error in chain):
        return None
    if not isinstance(chain[0], (history_io.AppendFailed, files.RestoreNeeded, OSError)):
        return None
    return type(chain[0]).__name__


def _due(memory, root, proof, at, deadline):
    """Make consolidation due now after a cut; the progress written, or None when it already was."""
    consolidation = dict(revision_io.read_primary(memory, root, deadline)['consolidation'])
    if consolidation.get('due', at) < at:
        return None
    consolidation['due'] = at
    return revision_io.update_progress(memory, root, proof, {'consolidation': consolidation}, deadline)


def apply(memory, root, expected, edits, *, sent, saved, at, run, deadline, make_id=None):
    """Apply line edits under the curation and layer leases, after the answer's item changes.

    `expected` is the revision proof that the item apply returned, or the
    request's when it changed nothing. Returns the attempt's `state`
    (`new`, `kept` or `cut`), `held` (None, or the error that kept the state
    when a required earlier version could not be appended), the dropped edits
    by reason, the added, cut and stale line IDs, the publisher's line effects
    and the latest revision proof. Lost leases and stale proofs raise.
    """
    root = Path(root)
    format2._id(run, format2._RUN)
    check = revision_io.guard(memory, root, deadline, curator=True)
    sources, items, private, digests = _read(root)
    planned = plan(edits, state=state_types.parse_state(sources['state.json']),
                   removed=state_types.parse_removed(sources['state-removed.json']), items=items,
                   private=private, sent=sent, saved=saved, at=at, device=memory.device, make_id=make_id)
    outcome = {'state': 'kept', 'held': None, 'dropped': planned.dropped, 'added': (), 'cut': (), 'stale': (),
               'lines': (), 'progress': None}
    if planned.proposal is None:
        # Every add may be cut with nothing else to publish; the cut still makes consolidation due.
        if planned.cut_adds:
            outcome = dict(outcome, state='cut', progress=_due(memory, root, expected, at, deadline))
        return outcome
    bound = tuple(sorted((('state', hashlib.sha256(sources['state.json']).hexdigest()),
                          ('removed', hashlib.sha256(sources['state-removed.json']).hexdigest()))))
    operations = hashlib.sha256(item_types._raw(planned.proposal['operations'])).hexdigest()

    def precondition(bound_memory, bound_root, binding):
        check()
        facts = {name: stamp[-1] for name, stamp in binding.facts[1]}
        if (bound_memory is not memory or bound_root != root or binding.original_sources != bound or
                binding.operations_sha256 != operations or facts != digests):
            raise fence_plan.Stale()
        check()

    try:
        result = state_io.apply(memory, root, expected, planned.proposal, at, deadline, run,
                                state_precondition=precondition)
    except state_io.PublicationFailed as failure:
        error = _held(failure)
        if error is None:
            raise
        return dict(outcome, held=error, progress=failure.progress)
    progress = result['progress']
    if planned.cut or planned.cut_adds:
        progress = _due(memory, root, fence_plan.snapshot(progress), at, deadline) or progress
    return dict(outcome, state='cut' if planned.cut or planned.cut_adds else 'new', added=planned.added,
                cut=planned.cut, stale=planned.stale, lines=result['lines'], progress=progress)
