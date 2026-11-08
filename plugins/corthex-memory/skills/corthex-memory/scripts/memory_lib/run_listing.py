"""The runs command (API-152; SPEC-144; TASK-104): a project's recent complete runs.

The command runner does not accept `runs` before the 0.3.0 activation, so an
installed plugin keeps C1 behaviour; until then the tests call the handler as
the runner will, after its gates, with the format-2 store binding. The handler
changes nothing. Under the project's layer lease it reads the curation
record's fence, the run logs and the records of the items that the runs saved,
each through the store's path fence. A run is listed when its log is whole,
written by this device in the fence's epoch, its last apply is the run's
current revision and it ended within the retention period (TBL-121); the
newest come first, 10 unless the limit says otherwise, from 1 to 200.
"""
from . import base, clock, commands, curation_worker, files, item_io, item_types, locks, revision_io, run_log
from . import worker_support

DEFAULT, MOST, TITLES = 10, 200, 3
# The commands' shared lock wait, within one bound for the whole read.
WAIT, SECONDS = 10.0, 60.0
# Each change count names objects once, however many applies changed them.
_KEYS = (('saved', None), ('statuses', 'item'), ('merges', 'item'), ('lines', 'line'), ('pins', 'item'),
         ('conflicts', 'candidate'))
SAY = {
    'none': 'No complete retained runs.',
    'one': 'One complete retained run, newest first.',
    'some': '%d complete retained runs, newest first.',
    'newest': 'The newest of %d complete retained runs.',
    'more': 'The %d newest of %d complete retained runs.',
    'unreadable': ('No run can be listed now because the curation record cannot be read. '
                   'The next curation repairs it.'),
}


def counts(log):
    """How many items, statuses, merges, lines, pins and candidates the run changed, each once."""
    return {field: len(set(log[field] if key is None else (entry[key] for entry in log[field])))
            for field, key in _KEYS}


def undoable(log, progress):
    """Whether an object that the run changed still has the revision that the run last gave it.

    An undo keeps every object whose revision has moved on (SPEC-145), so a
    run whose objects all changed later, or were undone, has nothing to undo.
    The undo preview can still keep an object for its history or a later
    dependent change (TASK-105).
    """
    last = {}
    for entry in log['revisions']:
        last[entry['id']] = max(entry['after'], last.get(entry['id'], entry['after']))
    current = progress['fence']['revisions']
    return any(current.get(key) == after for key, after in last.items())


def list_line(item):
    """An item's line as the item list shows it (TBL-015)."""
    first = item['quotes'][0]
    return {'item': item['id'], 'kind': item['kind'], 'speaker': first['speaker'], 'date': first['said'][:10],
            'title': item['title'].replace('\t', ' ')}


def _reader(memory, deadline):
    return lambda path: files._retry(lambda: memory.fence.read(path, deadline), deadline)


def _titles(memory, root, log, read):
    """Up to three of the run's saved items, in its order, from the records that survive.

    A forgotten item, an item of a deleted project and a record that is
    missing, damaged or reached through a link are left out.
    """
    found = []
    for item in log['saved']:
        if len(found) == TITLES:
            break
        try:
            if item_io._private(memory, root, item):
                continue
            value = item_types.parse_item(read(root / 'layer/items' / (item + '.json')))
        except worker_support.UnsafePath:
            continue
        except files._RESTORABLE:
            continue
        if value['id'] == item:
            found.append(list_line(value))
    return found


def recent(memory, root, deadline, *, days, limit, when=None):
    """(run lines newest first, how many runs are listed), or None when the curation record cannot be read.

    The caller holds no lease of the project; this takes its layer lease for
    the whole read, so no apply, forget or undo changes what it reads.
    """
    if memory.fence.check(root) is None:
        return [], 0
    with memory.lease(root / 'layer.lock', 'layer', deadline, 'skill',
                      acquire_deadline=min(deadline, clock.now() + WAIT)):
        if curation_worker._deleted(memory, root):
            return [], 0
        try:
            progress = revision_io.read(memory, root, deadline)
        except files._RESTORABLE + (files.RestoreNeeded,) as error:
            memory.note(error, step='skill')
            return None
        return listing(memory, root, deadline, progress, _reader(memory, deadline), days=days, limit=limit, when=when)


def listing(memory, root, deadline, progress, read, *, days, limit, when=None):
    """(run lines newest first, how many runs are listed), read under the project's layer lease that the caller holds.

    The undo command (TASK-105) lists the recent runs this way when it finds
    no run to undo.
    """
    logs = run_log.listed(root, progress, memory.device, when=base.utc_time(when), days=days, reader=read)
    found = []
    for log in logs[:limit]:
        memory.check(deadline, memory.held)
        found.append({'run': log['id'], 'kind': log['kind'], 'at': log['at'], 'ended': log['ended'],
                      'counts': counts(log), 'saved': _titles(memory, root, log, read),
                      'undoable': undoable(log, progress)})
    return found, len(logs)


def runs(context, *, when=None):
    """API-152 after the runner's gates, with the format-2 store binding as `context.memory`.

    `when` fixes the time that retention counts from, for tests.
    """
    project = context.project.name
    limit = context.arguments.get('limit', DEFAULT)
    if type(limit) is not int or not 1 <= limit <= MOST:
        return commands.common_result('runs', 'usage')
    memory = context.memory
    root = memory.folder / 'projects' / base.project_folder_name(project)
    days = context.configuration.values['retention']['days']
    try:
        found = recent(memory, root, clock.now() + SECONDS, days=days, limit=limit, when=when)
    except locks.LockBusy:
        return commands.common_result('runs', 'lock-busy')
    data = {'project': project, 'runs': [], 'limit': limit}
    if found is None:
        return commands.result('runs', data, SAY['unreadable'], 'nothing')
    lines, total = found
    data['runs'] = lines
    if not lines:
        return commands.result('runs', data, SAY['none'], 'nothing')
    if total > len(lines):
        say = SAY['newest'] % total if len(lines) == 1 else SAY['more'] % (len(lines), total)
    else:
        say = SAY['one'] if total == 1 else SAY['some'] % total
    return commands.result('runs', data, say)
