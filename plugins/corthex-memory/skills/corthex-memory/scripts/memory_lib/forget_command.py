"""The forget command (API-025; SPEC-035; TASK-097): its preview and confirmation.

The command runner does not hand `forget` to this handler before the 0.3.0
activation, so an installed plugin keeps C1 behaviour; until then the tests
call it as the runner will, after its gates, with the format-2 store binding.
Under the project's layer lease, waiting for it as long as the other commands
wait for theirs, it reads the items, tombstones, current state, pins,
candidates, line history and the raw logs that the forgotten items quote, each
through the store's path fence, and changes nothing. Without a code it returns
the preview (`forget_plan`). With a code it checks the code against the preview
that it has just read under the same lease, so a missing item or any change to
what the preview shows refuses the forget before anything is deleted; the
confirmed effects arrive with TASK-098.
"""
from . import base, clock, commands, conflict_types, curation_worker, files, forget_plan, history_io
from . import history_recovery, item_types, locks, raw_rewrite, request_inputs, run_listing, state_types

# The commands' shared lock wait, within one bound for the whole read.
WAIT, SECONDS = 10.0, 60.0
# An argument as the result schema holds it.
ARGUMENT = 200
SAY = {
    'missing': ('No item of this project has an ID in data.missing, so nothing was forgotten; '
                'data.matches holds the closest lines of the item list.'),
}


def _not_found(project, item, extra, missing, matches):
    data = {'project': project, 'item': item, 'with': list(extra), 'missing': list(missing), 'matches': matches}
    return commands.result('forget', data, SAY['missing'], 'refused', 'item-not-found')


def _held(root, selected, read):
    """(log, entry ID) -> each entry that the items quote and this device's raw logs hold.

    A damaged or unfinished line is left out, as the request reader leaves it
    out (`request_inputs.entries`), and so is a log that retention deleted.
    """
    wanted = {}
    for value in selected:
        for quote in value['quotes']:
            wanted.setdefault(quote['log'], set()).add(quote['entry'])
    held = {}
    for log in sorted(wanted):
        try:
            data = read(root / 'raw' / (log + '.jsonl'))
        except FileNotFoundError:
            continue
        last = 0
        for line in data.split(b'\n')[:-1]:
            try:
                entry = raw_rewrite._entry(line, log)
            except (ValueError, UnicodeError):
                continue
            if entry['seq'] <= last:
                continue
            last = entry['seq']
            if entry['id'] in wanted[log]:
                held[(log, entry['id'])] = entry
    return held


def _history(memory, root, deadline, read):
    """The primary line history and its backup when that reads, or None when the primary cannot be read.

    A forget clears reasons in every copy that the plugin can restore
    (TBL-119); the preview counts each record once across them. A backup that
    cannot be read restores nothing.
    """
    try:
        copies = [history_io.read(memory, root, deadline)]
    except files.RestoreNeeded:
        return None
    try:
        copies.append(state_types.parse_history(read(root / 'state-history.jsonl.bak')))
    except files._RESTORABLE:
        pass
    return copies


def _plan(memory, root, deadline, read, layer, project, item, extra, names):
    selected = [layer.items[name] for name in names]
    staying = [value for key, value in sorted(layer.items.items()) if key not in names]
    tombstones = []
    for name, data in request_inputs._named(root / 'layer/tombstones', read):
        history_recovery._tombstone(data, name, root.name)
        tombstones.append(item_types._document(data))
    pins = item_types.parse_pins(read(root / 'layer/pins.json'))['pins']
    candidates = conflict_types.open_candidates(
        conflict_types.parse_conflicts(read(root / 'layer/conflicts.json')))
    return forget_plan.preview(project, item, extra, selected, staying, lines=layer.lines, pins=pins,
                               candidates=candidates, tombstones=tombstones, held=_held(root, selected, read),
                               copies=_history(memory, root, deadline, read))


def _apply(memory, root, plan, deadline):
    """The confirmed forget's effects, under the lease that read the plan (TASK-098)."""
    raise NotImplementedError('the forget effects arrive with TASK-098')


def forget(context):
    """API-025 after the runner's gates, with the format-2 store binding as `context.memory`."""
    project = context.project.name
    item = context.arguments.get('item')
    extra = list(context.arguments.get('with_items') or ())
    if any(type(name) is not str or not 1 <= len(name) <= ARGUMENT for name in [item] + extra):
        return commands.common_result('forget', 'usage')
    names = list(dict.fromkeys([item] + extra))
    memory = context.memory
    root = memory.folder / 'projects' / base.project_folder_name(project)
    if memory.fence.check(root) is None:
        return _not_found(project, item, extra, names, [])
    deadline = clock.now() + SECONDS
    try:
        with memory.lease(root / 'layer.lock', 'layer', deadline, 'skill',
                          acquire_deadline=min(deadline, clock.now() + WAIT)):
            if curation_worker._deleted(memory, root):
                return _not_found(project, item, extra, names, [])
            read = run_listing._reader(memory, deadline)
            layer = request_inputs.layer(root, read)
            missing = [name for name in names if name not in layer.items]
            if missing:
                lines = [run_listing.list_line(value) for value in layer.current]
                return _not_found(project, item, extra, missing, forget_plan.closest(lines, missing))
            plan = _plan(memory, root, deadline, read, layer, project, item, extra, names)
            memory.check(deadline, memory.held)
            return context.confirm(plan.data, forget_plan.say(plan), lambda: _apply(memory, root, plan, deadline))
    except locks.LockBusy:
        return commands.common_result('forget', 'lock-busy')
