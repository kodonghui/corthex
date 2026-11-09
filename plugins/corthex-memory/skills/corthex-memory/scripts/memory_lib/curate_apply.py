"""Apply the checked changes of a curate answer (SPEC-016, SPEC-143; TASK-086).

The changes come from `curator_answers.check_curate`, which already applied
the quote check, the item limits and the speaker rules. Here, in the answer's
order, an add or a replacement saves a new item with a code-made ID, a
replacement marks each target superseded by it and a withdrawal marks its
target withdrawn. Each new item gets one open candidate (TBL-120) with each
item that it may disagree with: its checked conflicts and the targets that
the speaker rules kept current. A pair is recorded only when both items are
current once the whole answer is applied, since a candidate that a later
change of the same answer ends would settle at once; every open candidate
that names an item no longer current is settled. The worker that calls this
(TASK-088) is not wired to a hook or command before the 0.3.0 activation.
"""
from pathlib import Path

from . import base, conflict_plan, conflict_types, curator_answers, format2, item_io


def _end(final, item, status):
    if item not in final or final[item]['status'] != 'current':
        raise ValueError('existing current item required')
    final[item] = dict(final[item], status=status)


def plan(checked, *, items, conflicts, at, device, run, make_id=None):
    """The item additions, status changes and TBL-120 value for checked changes.

    `items` are the stored item records and `conflicts` the TBL-120 value,
    both read under the layer lease. Returns the additions and transitions for
    the item writer, `saved` (each change's number and its new item ID, for
    the line edits of TASK-087), the new TBL-120 value, and the candidates
    opened and settled.
    """
    make_id = base.new_id if make_id is None else make_id
    final = {value['id']: value for value in items}
    additions, transitions, saved, pairs = [], [], [], []
    for change in checked.changes:
        if change.action == 'withdraw':
            transitions.append({'id': change.targets[0], 'status': 'withdrawn'})
            _end(final, change.targets[0], 'withdrawn')
            continue
        item = make_id('i')
        if item in final:
            raise ValueError('code-made ID collision')
        record = curator_answers.item_record(change, item=item, at=at, device=device)
        final[item] = record
        additions.append(record)
        saved.append((change.number, item))
        for target in change.targets:
            transitions.append({'id': target, 'status': 'superseded', 'superseded_by': item})
            _end(final, target, 'superseded')
        pairs.extend((item, other) for other in change.kept + change.conflicts)
    current = {item for item, value in final.items() if value['status'] == 'current'}
    value, settled = conflict_plan.settle(conflicts, current, at)
    value, opened = conflict_plan.record(value, pairs, final, at=at, run=run, by='curate', make_id=make_id)
    return {'additions': additions, 'transitions': transitions, 'saved': saved,
            'conflicts': value, 'opened': opened, 'settled': settled}


def apply(memory, root, expected, checked, at, run, deadline):
    """Apply checked changes under the curation and layer leases; None when there is none.

    `expected` is the revision proof that the request was built from; a stale
    proof, a lost lease or a private item applies nothing (TASK-075). The
    item writer counts each new candidate zero durably before it reserves,
    and publishes conflicts.json after the items (TASK-076, TASK-092).
    """
    root = Path(root)
    format2._id(run, format2._RUN)
    if not checked.changes:
        return None
    check, _ = item_io._checked(memory, root, expected, deadline, curator=True)
    items = item_io._items(memory, root, deadline, check)
    conflicts = item_io._record(memory, root / 'layer/conflicts.json', conflict_types.parse_conflicts, deadline, check)
    planned = plan(checked, items=items, conflicts=conflicts, at=at, device=memory.device, run=run)
    result = item_io.apply(memory, root, expected, planned['additions'], planned['transitions'], at, deadline,
                           run_id=run, conflicts=planned['conflicts'])
    return dict(result, saved=tuple(planned['saved']), opened=tuple(planned['opened']),
                settled=tuple(planned['settled']))
