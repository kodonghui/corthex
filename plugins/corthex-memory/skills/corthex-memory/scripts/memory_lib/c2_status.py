"""The memory status of C2 (API-018; SPEC-033, SPEC-018; TASK-096).

Until the 0.3.0 activation the command runner hands `status` to the C1 handler
(`status.status`), and its store gate refuses a format-2 store as
`store-newer`, so nothing calls this module and an installed plugin keeps C1
behaviour; until then the tests call `status` as the runner will, after its
gates, with the format-2 store binding.

It shows what the C1 status shows, read as the C1 status reads it
(`status.Reader`): the store, the configuration, consent, keys, test servers,
this month's usage by model with the models that the price list does not name,
whose calls cost 0, the recent failures, the hook timings, sync and what waits
for consent or a key, with `unreadable` naming a log that cannot be read while
the rest is shown. Each project's part comes from the project's own records:
the unprocessed turns and the oldest's time from the markers' names, as the
triggers count them (TBL-008), and, under the project's layer lease, waiting
for it as long as the other commands wait for theirs, through the store's path
fence, the curation record as the start summary reads it, the primary or else
its backup with nothing restored (TBL-009), the items of every status that no
tombstone names, the pinned items that are still current, oldest pin first, as
the start summary shows them (TBL-014), the open conflict candidates whose two
items are current, as `conflicts` lists them (TBL-120), counted from the items
already read, and the newest run that `runs` lists (TBL-121). From the curation
record come the last curation attempt with its result, its error and how many
failed in a row, the fault guard's stop, and the last consolidation with the
time it is due and its failures in a row. A record that cannot be read leaves
its fields out. `runs` reads only the primary record, so while the primary
cannot be read the status shows no last run either, and says so. A
project without its pins or candidates file and without its backup, as before
its first curation, has none, as the start summary reads it; an item, pins or
candidates file that cannot be read, or a missing one whose backup is there,
raises, which the runner reports as `internal`, as it does for the other
commands. Nothing is written but the failure log's notes of what was restored, which the binding
writes only while the store record is the one that it pinned.

No conversation text and no key is shown: items appear by ID, errors by their
codes, and every string goes through the C1 status's redaction.
"""
import copy

from . import base, clock, command_result, commands, conflict_types, conflicts_command, curation_triggers
from . import curation_worker, item_commands, item_io, item_types, locks, resume_command, run_listing, run_log
from . import start_memory
from . import status as c1_status

# The commands' shared lock wait, within one bound for each project's read.
WAIT, SECONDS = 10.0, 60.0
STATUSES = ('current', 'superseded', 'withdrawn', 'undone')
SAY = {
    'status': 'Memory status from the memory store and its logs, with no conversation text and no key.',
    'stopped': '%s; resume can start it again.',
    'record': 'The curation record of %s cannot be read, so its last run is not shown; the next curation repairs it.',
}


def record_fields(progress):
    """The project status's fields from its curation record (TBL-009): curation, stopped and consolidation."""
    fields = {'consolidation': copy.deepcopy(progress['consolidation'])}
    last = next((attempt for attempt in progress['recent'] if attempt['kind'] == 'curate'), None)
    if last is not None:
        fields['curation'] = {key: last[key] for key in ('at', 'result', 'error') if key in last}
        count = progress['failures']['count'] if 'failures' in progress else 0
        if count:
            fields['curation']['failed_in_row'] = count
    if 'stopped' in progress:
        fields['stopped'] = copy.deepcopy(progress['stopped'])
    return fields


class _Binding:
    """The format-2 store binding with the calls that the C1 status reader makes of its store."""

    def __init__(self, memory):
        self.store, self.fence, self.folder = memory, memory.fence, memory.folder

    def check(self):
        # As the C1 reader checks its store: the store record unchanged, each check within 10 seconds.
        self.store.check(clock.now() + 10, self.store.held)

    def _path_check(self, path):
        self.check()
        return self.fence.check(path)

    def _lock(self, path, kind, device):
        return self.store._lock(path, kind, device)

    def configuration(self, report, deadline):
        return self.store.configuration(report, deadline=deadline)


class Reader(c1_status.Reader):
    """The C1 status reader over the format-2 binding, with each project's part read from its records."""

    def __init__(self, context, when=None):
        self.validator = command_result._load()
        self.store = context.memory
        self.memory = _Binding(context.memory)
        self.notes, self.logger = [], context.memory.logger
        self.header = context.memory.record(self.note, deadline=clock.now() + 10)
        self.now = c1_status._now() if when is None else when
        self.unreadable, self.latest = set(), {}
        # The projects whose primary curation record cannot be read, which `runs` reads alone.
        self.unread = []

    def flush(self):
        notes, self.notes = self.notes, []
        for error, count in notes:
            self.store.note(error, count)
        self.store.flush()

    def project(self, name, config):
        entry = config.values['projects'][name]
        result = dict(project=name, enabled=entry['enabled'], unprocessed=0, items=dict.fromkeys(STATUSES, 0),
                      pins=[])
        if 'since' in entry:
            result['since'] = entry['since']
        memory = self.store
        root = memory.folder / 'projects' / base.project_folder_name(name)
        if memory.fence.check(root) is None:
            return result
        deadline = clock.now() + SECONDS
        with memory.lease(root / 'layer.lock', 'layer', deadline, 'skill',
                          acquire_deadline=min(deadline, clock.now() + WAIT)):
            if curation_worker._deleted(memory, root):
                return result

            def check():
                memory.check(deadline, memory.held)
            markers = curation_triggers.scan(memory, root)
            result['unprocessed'] = markers.count
            if markers.count:
                result['oldest'] = base.utc_time(markers.oldest)
            progress, primary = curation_triggers.read_progress(memory, root, deadline)
            if progress is not None:
                result.update(record_fields(progress))
            items = item_commands._items(memory, root, deadline, check)
            for value in items:
                result['items'][value['status']] += 1
            current = {value['id']: value for value in items if value['status'] == 'current'}
            pins = item_io.optional_record(memory, root / 'layer/pins.json', item_types.parse_pins, deadline, check,
                                           {'pins': []})['pins']
            result['pins'] = [value['id'] for value in start_memory.pinned(pins, current.get)]
            candidates = conflicts_command._candidates(memory, root, deadline, check)
            # The open candidates whose two items are current, as `conflicts` lists them.
            result['open_conflicts'] = len(conflict_types.open_current(candidates, current.__contains__))
            if primary:
                logs = run_log.listed(root, progress, memory.device, when=base.utc_time(self.now),
                                      days=config.values['retention']['days'],
                                      reader=run_listing._reader(memory, deadline))
                if logs:
                    result['last_run'] = {'run': logs[0]['id'], 'kind': logs[0]['kind']}
            else:
                self.unread.append(name)
            check()
        return result


def _say(projects, unread):
    said = []
    for value in projects:
        if 'stopped' in value:
            said.append(SAY['stopped'] % resume_command.stopped_said(value['project'], value['stopped']))
        if value['project'] in unread:
            said.append(SAY['record'] % value['project'])
    return ' '.join(said) or SAY['status']


def status(context, *, when=None):
    """API-018 after the runner's gates, with the format-2 store binding as `context.memory`.

    `when`, an aware time, fixes the time that the usage month, the logs' days
    and the runs' retention count from, for tests.
    """
    try:
        reader = Reader(context, when)
        try:
            value = c1_status._status(context, reader)
        finally:
            reader.flush()
    except locks.LockBusy:
        return commands.common_result('status', 'lock-busy')
    return commands.result('status', value['data'], _say(value['data']['projects'], reader.unread))
