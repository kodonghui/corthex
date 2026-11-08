"""The conflicts command (API-151; SPEC-143; TASK-070): the open candidates, or the dismissal of one.

The command runner does not accept `conflicts` before the 0.3.0 activation, so
an installed plugin keeps C1 behaviour; until then the tests call the handler
as the runner will, after its gates, with the format-2 store binding. Under
the project's layer lease, waiting for it as long as the other commands wait
for theirs, it reads the candidates (TBL-120) and the records of the items
that the open ones name, each through the store's path fence.

Without `--dismiss` it lists the open candidates in the order that curation
carries them, oldest first, each with both items' lines as the item list shows
them (TBL-015), and changes nothing. A candidate whose items are not both
current, or whose item records cannot be read, is left out, as the start
summary leaves it out; the next writer of the candidates settles it. A project
without candidates, or without its candidates' file, has none to list, and a
candidates' file that cannot be read is an error, as it is for forget and undo.

With `--dismiss <candidate>` a listed candidate closes as `dismissed`, with
the time, once its revision is reserved (SPEC-012), so that a curator request,
a confirmation or an undo planned before it goes stale. No item, pin, line or
other candidate changes, no run is recorded, and the candidate's showing count
stays (TBL-010): only open candidates are shown. Any other argument is
`conflict-not-found`, with the open candidates.

Without the command a candidate settles when either of its items stops being
current: curation and consolidation (`curate_apply`, `consolidation_worker`),
forget (`forget_effects`) and undo (`undo_effects`) each settle the candidates
that name an item that they make not current.
"""
import copy

from . import base, clock, commands, conflict_plan, conflict_types, curation_worker, fence_plan, files, format2
from . import item_io, item_types, locks, revision_io, run_listing, worker_support

# The commands' shared lock wait, within one bound for the whole command.
WAIT, SECONDS = 10.0, 60.0
# An argument as the result schema holds it.
ARGUMENT = 200
SAY = {
    'none': 'No open conflict candidates.',
    'one': 'One open conflict candidate; both items remain current.',
    'some': '%d open conflict candidates; both items of each remain current.',
    'dismissed': 'The conflict candidate was dismissed. Both items remain current.',
    'missing': 'No conflict candidate matches that ID.',
}


def _item(memory, root, item, read):
    """The item's record while it is current and not forgotten, else None.

    A record that is missing, damaged, reached through a link or named for
    another item counts as not current here, as the runs command leaves such a
    record out.
    """
    try:
        if item_io._private(memory, root, item):
            return None
        value = item_types.parse_item(read(root / 'layer/items' / (item + '.json')))
    except worker_support.UnsafePath:
        return None
    except files._RESTORABLE:
        return None
    return value if value['id'] == item and value['status'] == 'current' else None


def listed(memory, root, conflicts, read):
    """The open candidates whose two items are current, oldest first, as conflict lines (data-conflicts)."""
    lines, cache = [], {}
    for candidate in conflict_types.open_candidates(conflicts):
        pair = []
        for item in candidate['items']:
            if item not in cache:
                cache[item] = _item(memory, root, item, read)
            pair.append(cache[item])
        if None not in pair:
            lines.append({'candidate': candidate['id'], 'items': [run_listing.list_line(value) for value in pair],
                          'at': candidate['at']})
    return lines


def dismissed(conflicts, candidate, at):
    """conflicts.json with only `candidate`, which is open, closed as dismissed at `at`."""
    format2._time(at)
    value = copy.deepcopy(conflict_types.parse_conflicts(item_types._raw(conflicts)))
    found = [c for c in value['candidates'] if c['id'] == candidate and c['status'] == 'open']
    if len(found) != 1:
        raise ValueError('only an open candidate is dismissed')
    found[0].update(status='dismissed', closed=at)
    return value


def _candidates(memory, root, deadline):
    """The project's candidates (TBL-120); none while it has no candidates' file.

    A file that cannot be read raises, and so does a missing one whose backup
    can be read, which a writer of the candidates restores.
    """
    try:
        return files.read_record(root / 'layer/conflicts.json', conflict_types.parse_conflicts, deadline=deadline,
                                 reader=lambda path: memory.fence.read(path, deadline))
    except FileNotFoundError:
        return {'candidates': []}


def _dismiss(memory, root, conflicts, candidate, at, deadline):
    """Reserve the candidate's revision, then publish conflicts.json with it dismissed and read it back."""
    path = root / 'layer/conflicts.json'
    value = dismissed(conflicts, candidate, at)
    data = conflict_plan.conflicts_bytes(value)
    expected = fence_plan.snapshot(revision_io.read_primary(memory, root, deadline))
    reservation = revision_io.reserve(memory, root, expected, ['candidate:' + candidate], deadline, primary_only=True)
    files.replace_bytes(path, data, check=reservation.check, path_check=memory.fence.check)
    after = item_io._record(memory, path, conflict_types.parse_conflicts, deadline, reservation.check)
    if conflict_plan.conflicts_bytes(after) != data:
        raise RuntimeError('the dismissal did not read back')
    return after


def conflicts(context, *, at=None):
    """API-151 after the runner's gates, with the format-2 store binding as `context.memory`.

    `at` fixes the dismissal's time, for tests.
    """
    project = context.project.name
    candidate = context.arguments.get('dismiss')
    if candidate is not None and (type(candidate) is not str or not 1 <= len(candidate) <= ARGUMENT):
        return commands.common_result('conflicts', 'usage')
    data = {'project': project, 'open': []}
    memory = context.memory
    root = memory.folder / 'projects' / base.project_folder_name(project)

    def answer():
        if candidate is not None:
            return commands.result('conflicts', dict(data, candidate=candidate), SAY['missing'], 'refused',
                                   'conflict-not-found')
        count = len(data['open'])
        if not count:
            return commands.result('conflicts', data, SAY['none'], 'nothing')
        return commands.result('conflicts', data, SAY['one'] if count == 1 else SAY['some'] % count)
    if memory.fence.check(root) is None:
        return answer()
    deadline = clock.now() + SECONDS
    try:
        with memory.lease(root / 'layer.lock', 'layer', deadline, 'skill',
                          acquire_deadline=min(deadline, clock.now() + WAIT)):
            if curation_worker._deleted(memory, root):
                return answer()
            value = _candidates(memory, root, deadline)
            data['open'] = listed(memory, root, value, run_listing._reader(memory, deadline))
            memory.check(deadline, memory.held)
            if candidate is None or candidate not in {line['candidate'] for line in data['open']}:
                return answer()
            after = _dismiss(memory, root, value, candidate, base.utc_time() if at is None else at, deadline)
            if any(c['id'] == candidate and c['status'] == 'open' for c in after['candidates']):
                raise RuntimeError('the dismissal did not close the candidate')
            data['open'] = [line for line in data['open'] if line['candidate'] != candidate]
            data['dismissed'] = candidate
            return commands.result('conflicts', data, SAY['dismissed'])
    except locks.LockBusy:
        return commands.common_result('conflicts', 'lock-busy')
