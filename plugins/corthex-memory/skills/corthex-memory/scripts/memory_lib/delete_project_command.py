"""The delete-project command (API-026; SPEC-037; TASK-044): its preview, confirmation and deletion, without sync.

The command runner does not hand `delete-project` to this handler before the
0.3.0 activation, so an installed plugin keeps C1 behaviour; until then the
tests call it as the runner will, after its gates, with the format-2 store
binding.

Without a code it changes nothing. It reads, through the store's path fence
and without a lease, so that a lease that stays busy never keeps the user from
a code, what the project's folder holds: the items that no tombstone names,
counted by their files, a backup whose file is missing among them; the
entries of this device's raw logs, a log read from its backup when its file
is missing, damaged and unfinished lines left out; and the pins that are on
for those items, from the pins' file or else its backup. `sync` is on when the
memory configuration holds sync settings. The code covers the project, the
items, the pins and sync, but not the raw log entries, which the user's own
answer adds to, as the maintainer decided for `resume` on 2026-11-09.

A code that matches waits for the store lease, as long as the other commands
wait for theirs, and reads everything again: when the items, the pins or sync
changed, it answers `confirm-stale` with the new data and a new code, takes
nothing over and deletes nothing. Otherwise it takes over at once the
project's curation and curated layer leases, which a heartbeat keeps fresh
(stage 05): a worker that held one finds its token gone and applies nothing.
Under them it reads everything again and answers `confirm-stale` in the same
way when a writer saved something before its lease was taken over. Otherwise
it turns memory off for the project in the memory configuration first, so that
no later session records or curates it, and only then takes over the notice
counter lease and the raw log lease of each session that the folder names,
which nothing refreshes, so that a hook could take one as stale after ten
seconds while memory was on. It looks again and deletes every file in the
project's folder, never through a link: a link, or anything but a file or a
folder, stays, and so do a lease that another process took after that look
and its session's files. Once the project's leases are released, it removes
the folders, the project's own last, and looks again, still under the store
lease; whatever is left answers `files-left` with its paths. The raw log
entries come from the answer's own look, which no look under a lease repeats.
Before memory is off, a busy lease, the deadline or a lost lease answer as for
the other commands and memory stays on; after it, they only end the deletion,
and the say tells the user to turn memory on and run it again, or to delete
what is left by hand. The usage log, the failure log and the hook timings,
outside the project's folder, keep their lines. No release before C3 syncs, so
the deletion leaves no project tombstone (TBL-017): with sync settings in the
configuration, `sync` is on and the say tells that a sync remote and the other
devices keep their copies.
"""
import copy
import json
import os
import re
import stat

from . import base, clock, commands, configuration, curation_rebuild, diagnostics, files, item_types, locks, retention
from .store_deletion import LOG, _identity
from .worker_support import UnsafePath

# The commands' shared lock wait, and the bounds of the preview's read and of the deletion under its leases.
WAIT, PREVIEW, SECONDS = 10.0, 60.0, 300.0
# A session's files in `raw`, `injections` and `compaction`, which change under its raw log lease (stage 05);
# its unprocessed turn markers, which recording makes under that lease too, are `retention.MARKER`'s.
SESSION = re.compile('(' + LOG + r')\.(?:jsonl?|lock)(?:\.|\Z)')
SAY = {
    'ask': ('This deletes the memory of %s on this device: %s, and turns memory off for it. A curation that runs '
            'for it now stops and applies nothing; the usage log keeps its lines. %s'),
    'off': 'Sync is off, so other devices keep theirs.',
    'on': ('The configuration holds sync settings, but no release syncs yet, so a sync remote and other devices '
           'keep theirs.'),
    'done': ('The memory of %s on this device was deleted: %s. Memory is off for it; the usage log keeps its '
             'lines. %s'),
    'stopped': ('The deletion of the memory of %s on this device stopped before it finished. Memory is off for it, '
                'and the files in data.left stay: turn memory on for it and run delete-project again, or delete '
                'them by hand; their paths are inside the memory folder, CORTHEX_MEMORY_HOME or else '
                '~/.corthex/corthex-memory.'),
    'left': ('Memory is off for %s and the rest of its memory on this device was deleted, but the files in '
             'data.left could not be, or were written while it ran. Close any program that holds them, then delete '
             'them by hand; their paths are inside the memory folder, CORTHEX_MEMORY_HOME or else '
             '~/.corthex/corthex-memory.'),
}


def _scan(memory, root):
    """(nodes, blocked): each file and folder in the project's folder by its identity, and what stays untouched.

    A link, a junction or anything but a file or a folder is blocked and never
    followed, and so is a folder that cannot be listed; a link where the
    project's folder goes blocks the whole folder.
    """
    nodes, blocked = {}, set()
    try:
        info = memory.fence.check(root)
    except UnsafePath:
        return nodes, {root}
    if info is None:
        return nodes, blocked
    if not stat.S_ISDIR(info.st_mode):
        return nodes, {root}
    nodes[root] = _identity(info)

    def walk(folder):
        try:
            children = sorted(files._retry(lambda: list(folder.iterdir())))
        except OSError:
            blocked.add(folder)
            return
        for path in children:
            try:
                info = memory.fence.check(path)
            except UnsafePath:
                blocked.add(path)
                continue
            if info is None:
                continue
            nodes[path] = _identity(info)
            if stat.S_ISDIR(info.st_mode):
                walk(path)
            elif not stat.S_ISREG(info.st_mode):
                blocked.add(path)
    walk(root)
    return nodes, blocked


def _names(nodes, folder):
    """The names of the files directly in `folder`."""
    return {path.name for path, identity in nodes.items()
            if path.parent == folder and identity[2] == stat.S_IFREG}


def _ids(names):
    """The item IDs that `<ID>.json` or its backup names."""
    found = set()
    for name in names:
        for suffix in ('.json', '.json.bak'):
            if name.endswith(suffix) and item_types.ITEM.fullmatch(name[:-len(suffix)]):
                found.add(name[:-len(suffix)])
    return found


def _read(memory, path, deadline):
    """The file's bytes, or None when it cannot be read or became a link since the scan."""
    try:
        return files.fence_read(memory, path, deadline)
    except (OSError, UnsafePath):
        return None


def _session(root, path):
    """The session whose raw log lease a file of the project changes under, or None."""
    if path.parent.parent != root:
        return None
    if path.parent.name in ('raw', 'injections', 'compaction'):
        match = SESSION.match(path.name)
        return match[1] if match else None
    if path.parent.name == 'unprocessed':
        match = retention.MARKER.match(path.name)
        return match[2] if match else None
    return None


def _preview(memory, name, root, nodes, settings, deadline):
    """The command's data without the raw log entries: the project, its items and pins, counted, and sync."""
    layer = root / 'layer'
    items = _ids(_names(nodes, layer / 'items')) - _ids(_names(nodes, layer / 'tombstones'))
    pins = 0
    for file in ('pins.json', 'pins.json.bak'):
        if file not in _names(nodes, layer):
            continue
        try:
            records = item_types.parse_pins(_read(memory, layer / file, deadline))['pins']
        except (ValueError, UnicodeError):
            continue
        pins = sum(1 for pin in records if pin['on'] and pin['item'] in items)
        break
    return {'project': name, 'deleted': {'items': len(items), 'entries': 0, 'pins': pins},
            'sync': 'on' if settings.values.get('sync') else 'off'}


def _entries(memory, root, nodes, deadline):
    """This device's raw log entries, as the curator reads them; the code does not cover them."""
    entries, logs = 0, _names(nodes, root / 'raw')
    for log in sorted({file[:-len(suffix)] for file in logs for suffix in ('.jsonl', '.jsonl.bak')
                       if file.endswith(suffix)}):
        if not diagnostics.LOG.fullmatch(log):
            continue
        # The file, or its backup when the file is missing or cannot be read.
        for file in (log + '.jsonl', log + '.jsonl.bak'):
            data = _read(memory, root / 'raw' / file, deadline) if file in logs else None
            if data is not None:
                entries += len(curation_rebuild._parse(data, log, []))
                break
    return entries


def _look(memory, name, root, nodes, settings, deadline):
    """The command's data with the raw log entries."""
    data = _preview(memory, name, root, nodes, settings, deadline)
    data['deleted']['entries'] = _entries(memory, root, nodes, deadline)
    return data


def _bound(data):
    """What the code covers: all but the raw log entries, which the user's own answer adds to."""
    return {'project': data['project'], 'items': data['deleted']['items'], 'pins': data['deleted']['pins'],
            'sync': data['sync']}


def _counted(count, one, many):
    return '%d %s' % (count, one if count == 1 else many)


def _what(data):
    deleted = data['deleted']
    return '%s, %s and %s' % (_counted(deleted['items'], 'item', 'items'),
                              _counted(deleted['entries'], 'raw log entry', 'raw log entries'),
                              _counted(deleted['pins'], 'pin', 'pins'))


def say(data):
    """The preview's say."""
    return SAY['ask'] % (data['project'], _what(data), SAY[data['sync']])


def _plan(root, nodes):
    """The project's leases that the deletion takes over, in stage 05's order."""
    def folder(path):
        return nodes.get(path, (None, None, None))[2] == stat.S_IFDIR
    if not folder(root):
        return []
    planned = [(root / 'curation.lock', 'curation'), (root / 'layer.lock', 'layer')]
    if folder(root / 'notices'):
        planned.append((root / 'notices/conflict-counts.lock', 'notice'))
    if folder(root / 'raw'):
        sessions = {_session(root, path) for path in nodes} - {None}
        planned += [(root / 'raw' / (log + '.lock'), 'raw') for log in sessions]

    def order(row):
        text = row[0].as_posix()
        return locks.POLICIES[row[1]].rank, text.casefold() if os.name == 'nt' else text
    return sorted(planned, key=order)


def _disable(memory, name, settings, deadline, leases):
    """Turn memory off for the project in the memory configuration (TBL-002) that `settings` read under the store lease.

    Each step of the write checks `leases`, the store lease and the project's own; no session's raw log
    lease guards the configuration.
    """
    document = copy.deepcopy(settings.document)
    entry = document.get('projects', {}).get(name)
    if entry is None or not entry.get('enabled', False):
        return
    entry['enabled'] = False
    checked = configuration.prepare(document)

    def check():
        memory.check(deadline, leases)
    files.write_json(memory.folder / 'configuration.json', checked.document, 'TBL-002', check=check,
                     path_check=memory.fence.check)


def _unlink(memory, root, nodes, path, guard):
    """Delete the file when it and the folders above it are still the ones scanned; whether it is gone.

    `guard(path)` checks the deadline, the store and the leases that the file changes under before each try.
    """
    def remove():
        guard(path)
        for place in (path,) + tuple(path.parents):
            info = memory.fence.check(place)
            if info is None:
                return
            if place not in nodes or _identity(info) != nodes[place]:
                raise UnsafePath()
            if place == root:
                break
        path.unlink()
    try:
        files._retry(remove, clock.now() + 1)
        return True
    except (OSError, UnsafePath):
        return False


def _remove_folders(memory, root, nodes):
    """Remove the scanned folders that are empty and still the ones scanned, the deepest first."""
    folders = [path for path, identity in nodes.items() if identity[2] == stat.S_IFDIR]
    for path in sorted(folders, key=lambda p: len(p.parts), reverse=True):
        try:
            info = memory.fence.check(path)
            if info is not None and _identity(info) == nodes[path]:
                path.rmdir()
        except (OSError, UnsafePath):
            pass  # What stays is found by the last look and reported.


def _result(memory, root, data, left, stopped):
    if not left:
        return commands.result('delete-project', data, SAY['done'] % (data['project'], _what(data), SAY[data['sync']]))
    data = dict(data, left=sorted(path.relative_to(memory.folder).as_posix() for path in left))
    return commands.result('delete-project', data, SAY['stopped' if stopped else 'left'] % data['project'],
                           'failed', 'files-left')


def _stale(context, data):
    """The fresh data with a new code, after what the code covers changed; nothing is deleted."""
    context.supplied = 'stale'
    return context.confirm(data, say(data), lambda: None, bound=_bound(data))


def _take_over(memory, planned, deadline, fixed, sessions, taken):
    """Take over the planned leases at once, in stage 05's order, adding each to what changes check.

    A session's raw log lease guards only that session's files, so a change checks the store lease, the
    project's other leases (`fixed`) and its own session's (`sessions`), not every session's.
    """
    for path, kind in planned:
        memory.check(deadline, fixed)
        lease = memory._lock(path, kind, memory.device)
        lease.acquire(min(deadline, clock.now() + WAIT), force=True)
        memory.held.append(lease)
        taken.append(lease)
        if kind == 'raw':
            sessions[path.name[:-len('.lock')]] = lease
        else:
            fixed.append(lease)
    memory.check(deadline, memory.held)


def _off(memory, name):
    """Whether the memory configuration as written leaves memory off for the project; False when unknown."""
    try:
        document = json.loads(files.fence_read(memory, memory.folder / 'configuration.json', clock.now() + 1))
        entry = document['projects'].get(name, {})
        return isinstance(entry, dict) and entry.get('enabled', False) is False
    except (OSError, ValueError, AttributeError, KeyError, TypeError, locks.LockBusy, locks.LostLock):
        return False


def _apply(context, root, bound, data):
    """The confirmed deletion of what `data`, the answer's own look, counted.

    A look under the store lease, the curation and curated layer leases, which a heartbeat keeps fresh, and
    another look; memory off; then the notice counter and raw log leases, which nothing refreshes and which no
    session takes once memory is off, and the files and folders.
    """
    memory, name = context.memory, context.project.name
    deadline = clock.now() + SECONDS
    taken, sessions, stopped = [], {}, False

    def release():
        while taken:
            lease = taken.pop()
            lease.release(report=lambda error, count: memory.note(error, count, 'skill'))
            memory.held.remove(lease)
    with memory.lease(memory.folder / 'store.lock', 'store', deadline, 'skill',
                      acquire_deadline=min(deadline, clock.now() + WAIT)) as owner:
        fixed = [owner]
        try:
            # Only the memory skill writes the configuration, under the store lease, so this read holds throughout.
            settings = memory.configuration(memory.note, deadline=deadline, holding_lock=owner)
            nodes, _ = _scan(memory, root)
            if _bound(_preview(memory, name, root, nodes, settings, deadline)) != bound:
                # Before any lease is taken over, so that no curation stops for a deletion that does not happen.
                return _stale(context, _look(memory, name, root, nodes, settings, deadline))
            _take_over(memory, [row for row in _plan(root, nodes) if row[1] in ('curation', 'layer')],
                       deadline, fixed, sessions, taken)
            # A writer that held a lease may have saved something before it was taken over.
            nodes, _ = _scan(memory, root)
            if _bound(_preview(memory, name, root, nodes, settings, deadline)) != bound:
                return _stale(context, _look(memory, name, root, nodes, settings, deadline))
            off = False
            try:
                _disable(memory, name, settings, deadline, fixed)
                off = True
                nodes, _ = _scan(memory, root)
                held = {lease.path for lease in taken}
                _take_over(memory, [row for row in _plan(root, nodes) if row[0] not in held],
                           deadline, fixed, sessions, taken)
                nodes, blocked = _scan(memory, root)
                held = {lease.path for lease in taken}
                unheld = {path for path, _ in _plan(root, nodes)} - held
                sessioned = nodes.get(root / 'raw', (None, None, None))[2] == stat.S_IFDIR

                def guard(path):
                    session = _session(root, path)
                    memory.check(deadline, fixed + [sessions[session]] if session in sessions else fixed)
                for path, identity in sorted(nodes.items(), reverse=True):
                    session = _session(root, path)
                    # A lease that another process took after the last plan stays, and so do its session's
                    # files; without a `raw` folder no process can hold a raw log lease.
                    if (identity[2] != stat.S_IFDIR and path not in held and path not in blocked
                            and path not in unheld and (session is None or session in sessions or not sessioned)):
                        _unlink(memory, root, nodes, path, guard)
            except (locks.LockBusy, locks.LostLock):
                if not (off or _off(memory, name)):
                    raise  # Memory is still on, so the user can run it again.
                stopped = True  # Memory is off: the deadline or a lost lease only ends the deletion.
        finally:
            release()
        # Under the store lease still, so that no `on` turns memory on again before the last look.
        _remove_folders(memory, root, nodes)
        after, blocked = _scan(memory, root)
    left = {path for path, identity in after.items() if identity[2] != stat.S_IFDIR} | blocked
    if not left:
        left = set(after)  # Folders are named only when no file is left in them.
    return _result(memory, root, data, left, stopped)


def delete_project(context):
    """API-026 after the runner's gates, with the format-2 store binding as `context.memory`."""
    memory = context.memory
    root = memory.folder / 'projects' / base.project_folder_name(context.project.name)
    deadline = clock.now() + PREVIEW
    try:
        memory.check(deadline)
        nodes, _ = _scan(memory, root)
        data = _look(memory, context.project.name, root, nodes, context.configuration, deadline)
        memory.check(deadline)
        bound = _bound(data)
        return context.confirm(data, say(data), lambda: _apply(context, root, bound, data), bound=bound)
    except locks.LockBusy:
        return commands.common_result('delete-project', 'lock-busy')
