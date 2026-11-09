"""The pin and unpin commands (API-023, API-024; SPEC-034; TASK-095).

The command runner parses `pin` and `unpin` but hands them to no handler
before the 0.3.0 activation, so it answers them as not implemented, as in C1,
and an installed plugin keeps C1 behaviour; until then the tests call these
handlers as the runner will, after its gates, with the format-2 store binding.
Each works under the project's layer lease, waiting for it as long as the other
commands wait for theirs, and reads through the store's path fence: the named
item, the pins (TBL-014), the pinned items' records and, for a new pin, the
current state (TBL-013) and the decisions that it cites, as the start summary
keeps its lines; the conflict candidates and notices are not read. A state
record that the project lacks counts as empty, as the start summary reads it.
An argument that names no item of
the project, or names one that a tombstone names, is `item-not-found`, with the
closest lines of the item list (TBL-015).

`pin` takes a current item. A superseded item is `item-not-current`, with the
current item at the end of its replacements in `current` when there is one; a
withdrawn or undone item is `item-not-current` without it. An item already
pinned is `nothing`. A new pin has to fit: the start summary that a session in
the command's folder would get, with its base (`build_context`), the pinned
items, the new one last, and the current state as the start shows it now, has
to show every pinned item, as SPEC-021 composes it; otherwise the answer is
`pin-no-room` with the pins, oldest pin first, since the oldest go first when
the summary is short of room, and says to unpin one first only when the item
would fit with no other pin. State lines are cut before any pinned item, but a
start that cuts them says so in a line that takes room too. Notices, which come
and go, are not counted: a start that shows notices, or more state lines than
now, leaves the oldest pinned items out for room, and says so (SPEC-021).

`unpin` takes an item of any status: a pin that is on turns off, and an item
that is not pinned is `nothing`.

A change reserves the pin's revision in the curation record's fence (TBL-009)
before it writes, so that a curator request, a confirmation or an undo planned
before it goes stale (SPEC-012), and an undo of an earlier run that moved the
pin keeps the pin as a later change (SPEC-145). It then writes the pins with the
item's record on or off at the command's time and with this device, in the
record's place or last for a new record, and reads them back. The record stays
after an unpin (TBL-014). No notice is written and no run is recorded.
`data.pins` holds the pinned items afterwards, oldest pin first, as the start
summary shows them: the current items whose pins are on. Their records are read
before the reservation, so that a record that cannot be read fails the command
before anything changes.

A project without a folder, or whose memory is being deleted, has no items. An
item record or pin file that cannot be read, or that a link reaches, raises,
which the runner reports as `internal`, as it does for forget and undo.
"""
from pathlib import Path

from . import base, clock, commands, context as start_context, curation_worker, fence_plan, files
from . import forget_plan, item_commands, item_io, item_types, locks, revision_io, run_listing, start_memory
from . import start_summary, state_types

# The commands' shared lock wait, within one bound for the whole command.
WAIT, SECONDS = 10.0, 60.0
# An argument as the result schema holds it.
ARGUMENT = 200
SAY = {
    'pinned': 'Pinned %s; the start summary shows it from the next session.',
    'already': '%s is already pinned.',
    'unpinned': 'Unpinned %s; the start summary no longer shows it.',
    'not-pinned': '%s is not pinned.',
    'no-room': 'The start summary has no room for another pinned item. Unpin one of these first.',
    'base': 'The start summary has no room for a pinned item, since its base takes the room.',
    'superseded': '%s was superseded by %s, which can be pinned instead.',
    'replaced': '%s was superseded; %s replaces it now and can be pinned instead.',
    'superseded-only': '%s was superseded, and no current item replaces it.',
    'withdrawn': '%s was withdrawn, so it cannot be pinned.',
    'undone': '%s was undone, so it cannot be pinned.',
    'undone-by': '%s was undone by %s, so it cannot be pinned.',
    'missing': 'No item %s in %s.',
}


def fits(base_text, values, value, lines=()):
    """Whether the start summary with this base, pinned items and state lines, `value` the newest pin, shows every pin.

    `lines` are the state lines as the start summary keeps them; those that do
    not fit are cut before any pinned item, and the line that says so counts.
    """
    values = list(values) + [value]
    shown = start_memory.build_summary(base_text, (), values, lines).pins
    return set(shown) == {item['id'] for item in values}


def replacement(value, find):
    """The current item at the end of a superseded item's replacements, or None.

    `find(item)` gives the record of an item of the project that no tombstone
    names, else None.
    """
    seen = {value['id']}
    while value is not None and value['status'] == 'superseded':
        after = value.get('superseded_by')
        if after is None or after in seen:
            return None
        seen.add(after)
        value = find(after)
    return value if value is not None and value['status'] == 'current' else None


def changed(pins, item, on, at, device):
    """The pins with the item's record turned on or off at `at`: in its place, or last when it has none."""
    record = {'item': item, 'on': on, 'at': at, 'device': device}
    if any(pin['item'] == item for pin in pins):
        return [record if pin['item'] == item else dict(pin) for pin in pins]
    return [dict(pin) for pin in pins] + [record]


def _closest(name, project, matches):
    say = SAY['missing'] % (name, project)
    found = [line['item'] for line in matches]
    if len(found) == 1:
        return say + ' The closest is %s.' % found[0]
    if found:
        return say + ' The closest are %s and %s.' % (', '.join(found[:-1]), found[-1])
    return say


def _not_found(command, project, name, matches):
    data = {'project': project, 'item': name, 'matches': matches}
    return commands.result(command, data, _closest(name, project, matches), 'refused', 'item-not-found')


def _not_current(project, value, current):
    name, data = value['id'], {'project': project, 'item': value['id']}
    if value['status'] == 'withdrawn':
        say = SAY['withdrawn'] % name
    elif value['status'] == 'undone':
        say = SAY['undone-by'] % (name, value['undone_by']) if 'undone_by' in value else SAY['undone'] % name
    elif current is None:
        say = SAY['superseded-only'] % name
    else:
        data['current'] = current['id']
        say = SAY['superseded' if value['superseded_by'] == current['id'] else 'replaced'] % (name, current['id'])
    return commands.result('pin', data, say, 'refused', 'item-not-current')


def _publish(memory, root, pins, item, deadline):
    """Reserve the pin's revision, then write the pins and read them back."""
    path = root / 'layer/pins.json'
    data = item_types.pins_bytes({'pins': pins})
    expected = fence_plan.snapshot(revision_io.read_primary(memory, root, deadline))
    reservation = revision_io.reserve(memory, root, expected, ['pin:' + item], deadline, primary_only=True)
    files.replace_bytes(path, data, check=reservation.check, path_check=memory.fence.check)
    after = item_io._record(memory, path, item_types.parse_pins, deadline, reservation.check)
    if item_types.pins_bytes(after) != data:
        raise RuntimeError('the pins did not read back')


def _command(context, command, at, start_base=None):
    """Either command; `start_base()` gives the start summary's unshortened base, which only `pin` needs."""
    project = context.project.name
    name = context.arguments.get('item')
    if type(name) is not str or not 1 <= len(name) <= ARGUMENT:
        return commands.common_result(command, 'usage')
    memory = context.memory
    root = memory.folder / 'projects' / base.project_folder_name(project)
    if memory.fence.check(root) is None:
        return _not_found(command, project, name, [])
    deadline = clock.now() + SECONDS
    try:
        with memory.lease(root / 'layer.lock', 'layer', deadline, 'skill',
                          acquire_deadline=min(deadline, clock.now() + WAIT)):
            if curation_worker._deleted(memory, root):
                return _not_found(command, project, name, [])

            def check():
                memory.check(deadline, memory.held)
            found = {}

            def find(item):
                if item not in found:
                    found[item] = item_commands._item(memory, root, item, deadline, check)
                return found[item]

            def current(item):
                value = find(item)
                return value if value is not None and value['status'] == 'current' else None
            value = find(name)
            if value is None:
                items = item_commands._items(memory, root, deadline, check)
                lines = [run_listing.list_line(item) for item in item_commands.listed(items)]
                return _not_found(command, project, name, forget_plan.closest(lines, [name]))
            if command == 'pin' and value['status'] != 'current':
                return _not_current(project, value, replacement(value, find))
            pins = item_io._record(memory, root / 'layer/pins.json', item_types.parse_pins, deadline, check)['pins']
            on = any(pin['item'] == name and pin['on'] for pin in pins)
            data = {'project': project, 'item': name}
            if on == (command == 'pin'):
                data['pins'] = [item['id'] for item in start_memory.pinned(pins, current)]
                check()
                return commands.result(command, data, SAY['already' if on else 'not-pinned'] % name, 'nothing')
            if command == 'pin':
                # The pinned items and state lines as the next start would show them, notices aside.
                now = start_memory.pinned(pins, current)
                state, removed = (item_io.optional_record(memory, root / 'layer' / name, parse, deadline, check,
                                                          parse(start_summary.EMPTY[name]))
                                  for name, parse in (('state.json', state_types.parse_state),
                                                      ('state-removed.json', state_types.parse_removed)))
                lines = start_summary.state_lines(memory, root, state, removed, current, deadline)
                text = start_base()
                if not fits(text, now, value, lines):
                    data['pins'] = [item['id'] for item in now]
                    check()
                    # Unpinning helps only when the item fits without any other pin.
                    say = SAY['no-room'] if now and fits(text, (), value, lines) else SAY['base']
                    return commands.result('pin', data, say, 'refused', 'pin-no-room')
            after = changed(pins, name, command == 'pin', at or base.utc_time(), memory.device)
            data['pins'] = [item['id'] for item in start_memory.pinned(after, current)]
            check()
            _publish(memory, root, after, name, deadline)
            return commands.result(command, data, SAY['pinned' if command == 'pin' else 'unpinned'] % name)
    except locks.LockBusy:
        return commands.common_result(command, 'lock-busy')


def _base(context):
    """The unshortened base that the start hook builds for a session in the command's folder."""
    return start_context.build_context(Path(context.arguments['folder']), Path.home(), limit=None)


def pin(context, *, at=None, base_text=None):
    """API-023 after the runner's gates, with the format-2 store binding as `context.memory`.

    `at` fixes the pin's time and `base_text` the start summary's base, for tests.
    """
    return _command(context, 'pin', at, lambda: _base(context) if base_text is None else base_text)


def unpin(context, *, at=None):
    """API-024 after the runner's gates, with the format-2 store binding as `context.memory`.

    `at` fixes the unpin's time, for tests.
    """
    return _command(context, 'unpin', at)
