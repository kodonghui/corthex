"""TASK-091: the memory part of the start summary from the curated layer (API-001 steps 5 and 7).

`compose` builds what SPEC-021, SPEC-022 and SPEC-143 show for an enabled
project of a format-2 store: the notices of stage 06's table, the pinned items
that are still current, oldest pin first, and the current state's lines that
the validity view keeps (TBL-013), within the start hook's deadline. It reads
without the layer lease and writes nothing to the curated layer, and of the
item files it reads only those that the summary needs: the pinned items, the
items that decision lines cite, the two items of a conflict candidate and, for
where to read the lines' sources again (SPEC-148), at most 30 other items that
the lines cite. A file that another process is replacing on Windows is read
again within the deadline. The one lease it takes is the notice-counter lease
(TBL-010): once the conflict line fits among the notices, it reserves one
showing of the oldest eligible candidate, within a quarter of a second. A
reservation that fails leaves the line out and counts nothing, unless it failed
after its move, which uses up that showing as a stop before the output does;
one that holds goes out with the summary, also when the deadline passes while
the summary is built.

When the deadline passes, the memory part is the one line `Memory could not
be read in time.`, and when anything else fails it is the line about an
internal error, with the error for the hook's failure log; neither deletes a
notice or writes the injection log. `after` is step 7: under the project's
layer lease, which every notice writer holds, it deletes each stored notice
that the summary showed, unless a later notice of the same name replaced it
meanwhile, and appends the start's line to the session's injection log
(TBL-011).

From release 0.3.0 the start hook uses it for a format-2 store
(`start_hook.Start`); below 0.3.0, and for any other store, the start hook
keeps C1 behaviour. The notices about sync (SPEC-026, SPEC-027) come with sync
in C3.
"""
from collections import namedtuple
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
import re
import stat

from . import (base, clock, conflict_counts, conflict_types, curation, curation_triggers, files, format2,
               history_recovery, injection_log, item_types, locks, model_access, start_memory, state_types,
               worker_support)

Notice = start_memory.Notice
LayerView = namedtuple('LayerView', 'read current lines known')
WEEK = timedelta(days=7)
STORED = {'curation-failed.json': 'curation-failed', 'consolidation-failed.json': 'consolidation-failed',
          'rebuilt.json': 'rebuilt'}
PINNED = re.compile(r'pin-(i_' + format2._DIGITS + r')\.json\Z')
PIN_KINDS = ('pin-moved', 'pin-dropped', 'pin-restored', 'pin-removed')
TITLE_BYTES = 40
POINTER_READS = 30  # the most item files that the summary reads only for the lines' pointers (SPEC-148)
# What makes a cited item unreadable for a pointer, which it then does not give; a replaced store still ends the
# memory part, and so does the deadline, which `compose` checks after the summary.
UNREADABLE = (OSError, ValueError, UnicodeError, RecursionError, worker_support.UnsafePath)
RESERVE_SECONDS = 0.25  # the conflict reservation: its wait for the notice-counter lease and its write
# The reads for pointers end this long before the deadline, which leaves the summary its checks and the reservation
# its wait; an item not read by then gives no pointer.
POINTER_MARGIN = 0.3
STEP_SECONDS = 1.0   # step 7's reads and deletions, after the summary is printed
TIMEOUT = Notice('unreadable', 'Memory could not be read in time.')
_read = files.fence_read  # reads without a lease: again on a Windows sharing violation, until the deadline
INTERNAL = start_memory.unreadable('an internal memory error occurred')
STOPPED = ('Curation is stopped for this project after three failed attempts in a row (%s). '
           'The memory status can resume it.')
WAITS = (('anthropic', "Curation is waiting for CORTHEX_MEMORY_ANTHROPIC_API_KEY, which the hook's "
                       "environment does not have."),
         ('openai', "Recall and search by meaning are waiting for CORTHEX_MEMORY_OPENAI_API_KEY, which the "
                    "hook's environment does not have."))
KEYS = ("Memory keys are read only from the environment that the host starts in, such as a shell profile or a "
        "cloud environment's secret settings.")
SCRUB = "Claude Code's CLAUDE_CODE_SUBPROCESS_ENV_SCRUB setting can remove it from hooks."
RETENTION = ('%d turns are not curated yet and will be deleted on %s by the retention period, unless curation '
             'goes on before then.')
TEMPORARY = ('This is a temporary device and sync is off, so what memory records and curates here goes with '
             'the device.')
FAILED = '%s failed since the last session (%s).'
REBUILT = ('The curation record was made again from the raw log, so some turns may be curated twice and merged '
           'later.')
MOVED = 'The pinned item %s was superseded, so the pin moved to %s.'
DROPPED = 'The pinned item %s was withdrawn, so its pin was dropped.'
RESTORED = 'The pin returned to %s by undo %s.'
REMOVED = 'The pin of %s was removed by undo %s.'
CONFLICT = ('Memory items %s ("%s") and %s ("%s") may disagree; neither replaces the other until the user says '
            "which holds (%d open; the memory skill's conflicts command lists them).")
EMPTY = {'state.json': state_types.state_bytes({'lines': []}),
         'state-removed.json': state_types.removed_bytes({'removed': []}),
         'pins.json': item_types.pins_bytes({'pins': []}),
         'conflicts.json': item_types._raw({'candidates': []})}


@dataclass(frozen=True)
class Part:
    text: str              # the start summary: the base and the memory part
    outcome: str           # 'ok', 'deadline' or 'error'
    pins: tuple = ()       # IDs of the pinned items shown, oldest pin first
    shown: tuple = ()      # (path, bytes) of each stored notice shown
    reserved: object = None  # the conflict candidate whose showing was reserved
    error: object = None     # what made the outcome 'error', for the hook's failure log


@dataclass(frozen=True)
class After:
    deleted: int       # stored notices deleted
    injected: bool     # whether the injection log took the start's line
    errors: tuple      # failures to note in the failure log; each leaves its notice for the next start


def compose(memory, project, base_text, deadline, *, settings=None, environment=None, now=None, zone=None):
    """API-001 step 5 for an enabled project: the start summary, as a Part.

    `base_text` is the unshortened base (`build_context(..., limit=None)`);
    `settings` is the hook's configuration, by default the store's; `environment`
    is where the memory keys are looked for, by default the hook's own.
    """
    root = memory.folder / 'projects' / base.project_folder_name(project)
    try:
        memory.check(deadline)
        settings = memory.config if settings is None else settings
        environment = os.environ if environment is None else environment
        notices = _lasting(memory, root, settings, deadline, environment, now, zone)
        stored = _stored(memory, root, deadline)
        notices.extend(notice for notice, _, _ in stored)
        pins, lines, conflict, reread = _layer(memory, root, deadline)
        reserved = summary = None
        if conflict is not None:
            line, candidate = conflict
            notices.append(line)
            if any(shown is line for shown in start_memory.fitting(notices)[0]):
                # The summary is built before the reservation, with the item reads that its pointers need, so that
                # a deadline in those reads uses up no showing that no summary shows.
                summary = start_memory.build_summary(base_text, notices, pins, lines, zone=zone, reread=reread)
                memory.check(deadline)
                if conflict_counts.reserve(memory, root, candidate,
                                           min(deadline, clock.now() + RESERVE_SECONDS)) is None:
                    notices.pop()
                    summary = None
                else:
                    reserved = candidate
        if summary is None:
            summary = start_memory.build_summary(base_text, notices, pins, lines, zone=zone, reread=reread)
        # A reserved showing is used up, so it goes out even when the deadline passed while the summary was
        # built; the store is still checked.
        memory.check(deadline if reserved is None else max(deadline, clock.now() + RESERVE_SECONDS))
        shown = start_memory.fitting(notices)[0]
        kept = tuple((path, data) for notice, path, data in stored if any(notice is value for value in shown))
        return Part(summary.text, 'ok', summary.pins, kept, reserved)
    except locks.LockBusy:
        return Part(start_memory.build_summary(base_text, (TIMEOUT,)).text, 'deadline')
    except Exception as error:
        return Part(start_memory.build_summary(base_text, (INTERNAL,)).text, 'error', error=error)


def after(memory, project, part, host, session, *, when=None):
    """API-001 step 7, once the summary is printed.

    Only a memory part that was composed deletes notices. The stored notices
    shown are deleted under the project's layer lease, which every notice
    writer holds, so that no notice is written between the reading and the
    deletion of its file; the lease and the deletions get the step's one
    second, and a lease that stays busy leaves them all for the next start. A
    notice is deleted only while it holds the bytes that were shown, so that a
    later notice of the same name stays for the next start. The lease goes
    before the injection log takes the start's line with the pinned items shown
    (TBL-011). A late or failing memory part showed none, and its start still
    takes the line, so that recall counts the prompts again after it (SPEC-023).
    """
    deleted, errors = 0, []
    if part.outcome == 'ok' and part.shown:
        root = memory.folder / 'projects' / base.project_folder_name(project)
        deadline = clock.now() + STEP_SECONDS
        try:
            with memory.lease(root / 'layer.lock', 'layer', deadline, 'summary', acquire_deadline=deadline):
                for path, data in part.shown:
                    def check(path=path):
                        memory.check(deadline, memory.held)
                        memory.fence.check(path)
                    try:
                        if _read(memory, path, deadline) != data:
                            continue
                        files._unlink(path, check)
                        deleted += 1
                    except FileNotFoundError:
                        continue
                    except (OSError, ValueError) as error:
                        errors.append(error)
        except locks.LockBusy:
            pass  # the notices not deleted yet are shown again at the next start
        except (OSError, RuntimeError, ValueError) as error:
            errors.append(error)
    try:
        injected = injection_log.append(memory, project, host, session, 'start', part.pins, when=when)
    except (OSError, RuntimeError, ValueError) as error:
        injected = False
        errors.append(error)
    return After(deleted, injected, tuple(errors))


def _lasting(memory, root, settings, deadline, environment, now, zone):
    """The notices worked out at every start while their conditions last, in no particular order."""
    notices = []
    progress = curation_triggers._progress(memory, root, deadline)
    if progress is not None and 'stopped' in progress:
        notices.append(Notice('stopped', STOPPED % (', '.join(progress['stopped']['errors']) or 'RuntimeError')))
    notices.extend(start_memory.consent_notices(settings))
    presence = model_access.Credentials.read(environment).presence()
    scrub = [SCRUB] if environment.get('CLAUDE_CODE_SUBPROCESS_ENV_SCRUB') else []
    for provider, text in WAITS:
        if presence[provider] != 'present':
            notices.append(Notice('key', ' '.join([text, KEYS] + scrub)))
    soon = _retention(memory, root, settings, deadline, now, zone)
    if soon is not None:
        notices.append(soon)
    if settings.values.get('temporary'):
        notices.append(Notice('temporary', TEMPORARY))
    return notices


def _retention(memory, root, settings, deadline, now, zone):
    """The unprocessed turns that retention deletes within 7 days, and the first local date (SPEC-009)."""
    period = timedelta(days=settings.values['retention']['days'])
    now = datetime.now(timezone.utc) if now is None else now
    ends = sorted(at + period for at in curation_triggers.turns(memory, root, deadline).values()
                  if at + period - WEEK <= now)
    if not ends:
        return None
    return Notice('retention', RETENTION % (len(ends), max(ends[0], now).astimezone(zone).date().isoformat()))


def _stored(memory, root, deadline):
    """The stored notices (TBL-010), by time and name: (notice, path, bytes) each.

    Only the names that TBL-010 gives are read, and a notice whose kind does
    not fit its name is skipped. A damaged notice is skipped and left as it is.
    """
    folder = root / 'notices'
    if memory.fence.check(folder) is None:
        return []
    found = []
    for name in sorted(os.listdir(str(folder))):
        pinned = PINNED.fullmatch(name)
        if name not in STORED and pinned is None:
            continue
        path = folder / name
        try:
            data = _read(memory, path, deadline)
        except FileNotFoundError:
            continue
        try:
            value = item_types.parse_notice(data)
        except (ValueError, UnicodeError):
            continue
        if pinned is None and value['kind'] != STORED[name] or pinned is not None and (
                value['kind'] not in PIN_KINDS or value.get('item') != pinned.group(1)):
            continue
        text = _said(value)
        if text is not None:
            found.append((value['at'], name, Notice(value['kind'], text), path, data))
    found.sort(key=lambda entry: entry[:2])
    return [entry[2:] for entry in found]


def _said(value):
    """A stored notice's line, or None when the notice lacks what its line names."""
    kind = value['kind']
    if kind in ('curation-failed', 'consolidation-failed'):
        error = value.get('error')
        return FAILED % ('Curation' if kind == 'curation-failed' else 'Consolidation',
                         error if error in curation.ERRORS else 'RuntimeError')
    if kind == 'rebuilt':
        return REBUILT
    if kind == 'pin-moved':
        return MOVED % (value['item'], value['to']) if 'to' in value else None
    if kind == 'pin-dropped':
        return DROPPED % value['item']
    if 'run' not in value:
        return None
    return (RESTORED if kind == 'pin-restored' else REMOVED) % (value['item'], value['run'])


def _layer(memory, root, deadline):
    """(pinned items, oldest pin first; the state lines that the validity view keeps; the conflict line; what
    finds a pinned item's or a line's pointers, `_pointers`, or None).

    The conflict line is (notice, candidate ID) for the oldest eligible
    candidate whose two items are current, or None. A project without a layer,
    or whose memory was deleted (TBL-017), shows nothing from it; a layer file
    that is missing counts as empty.
    """
    view = layer_view(memory, root, deadline)
    if view is None:
        return (), (), None, None
    read, current, lines, known = view
    pins = item_types.parse_pins(read('pins.json'))['pins']
    pinned = start_memory.pinned(pins, current)
    conflicts = conflict_types.parse_conflicts(read('conflicts.json'))
    total = len(conflict_types.open_candidates(conflicts))
    counts = conflict_counts.read(memory, root, deadline) if total else None
    conflict = None
    for candidate in conflict_counts.eligible(conflicts, counts):
        pair = [current(item) for item in candidate['items']]
        if None not in pair:
            text = CONFLICT % (pair[0]['id'], _title(pair[0]['title']), pair[1]['id'], _title(pair[1]['title']),
                               total)
            conflict = (Notice('conflict', text), candidate['id'])
            break
    return tuple(pinned), tuple(lines), conflict, _pointers(memory, root, pinned, current, known, deadline)


def _pointers(memory, root, pinned, current, known, deadline):
    """`reread(value)`: where to read a pinned item's or a state line's sources again (SPEC-148), found only when
    `build_summary` asks, which it does in the block's order for the lines whose pointers fit.

    A pinned item's record gives its deciding quote. A cited item is looked
    at once, however many lines cite it: an item already read gives its
    deciding quote as it is, and of the others the first 30 that the lines
    need are read, until 0.3 seconds before the deadline (POINTER_MARGIN).
    A cited item that cannot be read by then, or that is not current, gives
    no pointer, as does one whose place cannot be looked at, after
    `files._retry`'s wait on Windows. Anything but a file in an item's place,
    such as a folder, which Windows refuses to read until the deadline, gives
    none without a read.
    """
    pins = {value['id'] for value in pinned}
    quotes, reads, until = {}, [POINTER_READS], deadline - POINTER_MARGIN

    def look(item):
        if not known(item):
            if not reads[0] or clock.now() >= until:
                return None
            reads[0] -= 1
            path = root / 'layer' / 'items' / (item + '.json')
            try:
                info = files._retry(lambda: memory.fence.check(path), until)
            except UNREADABLE:
                return None
            if info is None or not stat.S_ISREG(info.st_mode):
                return None
        try:
            value = current(item, until)
        except UNREADABLE + (locks.LockBusy,):  # a read still waiting when the reads for pointers end gives none
            return None
        return None if value is None else value['quotes'][0]

    def quote(item):
        if item not in quotes:
            quotes[item] = look(item)
        return quotes[item]

    def reread(value):
        if value['id'] in pins:
            return start_memory.item_pointers(value)
        return start_memory.line_pointers(value, quote)
    return reread


def layer_view(memory, root, deadline, *, decisions=True):
    """A LayerView of a project's curated layer, or None for a project without one or whose memory was deleted
    (TBL-017); the compaction brief (TASK-113) reads the state lines through it too.

    `read(name)` reads a layer file within the deadline, a missing one as
    empty; `current(item, until=None)` is the item's record while it is
    current and no tombstone names it, else None, read by `until` when that
    comes before the deadline; `lines` are the state lines that the
    validity view keeps (TBL-013); `known(item)` is whether `current` has its
    answer without reading a file. It reads the tombstones, the state and its
    removals, and of the item files only those that decision lines cite. With
    `decisions` false it reads no item file and gives no `current`: the
    decision lines, whose validity needs their items, are left out, and the
    other parts' lines, which no item's status decides, are as the validity
    view keeps them.
    """
    folder = root / 'layer'
    if memory.fence.check(folder) is None or any(
            name == 'deleted.json' or name.startswith('deleted.json.') for name in os.listdir(str(folder))):
        return None

    def read(name):
        try:
            return _read(memory, folder / name, deadline)
        except FileNotFoundError:
            return EMPTY[name]

    private, forgotten = _tombstones(memory, folder, root.name, deadline)
    cache = {}

    def current(item, until=None):
        """The item while it is current and no tombstone names it, else None."""
        if item in forgotten:
            return None
        if item not in cache:
            path = folder / 'items' / (item + '.json')
            try:
                value = item_types.parse_item(_read(memory, path, deadline if until is None else min(deadline, until)))
            except FileNotFoundError:
                value = None
            if value is not None and value['id'] != item:
                raise ValueError('item file name differs from its ID')
            cache[item] = value
        value = cache[item]
        return value if value is not None and value['status'] == 'current' else None

    def known(item):
        return item in forgotten or item in cache

    if not decisions:
        current = None
    lines = _lines(state_types.parse_state(read('state.json')), state_types.parse_removed(read('state-removed.json')),
                   private, current)
    return LayerView(read, current, lines, known)


def _lines(state, removed, private, current):
    """The state lines that the validity view keeps, each decision that they cite checked with `current`; without a
    `current`, no decision line."""
    cited = sorted({cite for line in state['lines'] if line['part'] == 'decisions'
                    for cite in line['cites'] if item_types.ITEM.fullmatch(cite)}) if current is not None else ()
    items = {}
    for item in cited:
        value = current(item)
        if value is not None:
            items[item] = value
    return state_types.validity_view(state, removed, items, private)['lines']


def state_lines(memory, root, state, removed, current, deadline):
    """The current state lines that the next start would show, for the pin command's room (TASK-095).

    `state` and `removed` are the project's TBL-013 records, as the caller
    read them, and `current(item)` the item's record while it is current and
    no tombstone names it, else None. The tombstones make cites private as the
    start summary reads them.
    """
    private, _ = _tombstones(memory, root / 'layer', root.name, deadline)
    return _lines(state, removed, private, current)


def _tombstones(memory, folder, project, deadline):
    """(the cites that tombstones make private, the forgotten item IDs); a backup counts as its tombstone."""
    path = folder / 'tombstones'
    if memory.fence.check(path) is None:
        return set(), set()
    names = {}
    for name in os.listdir(str(path)):
        for suffix in ('.json', '.json.bak'):
            item = name[:-len(suffix)] if name.endswith(suffix) else ''
            if item_types.ITEM.fullmatch(item):
                names.setdefault(item, []).append(name)
    private = set()
    for item, found in sorted(names.items()):
        for name in sorted(found):
            try:
                data = _read(memory, path / name, deadline)
            except FileNotFoundError:
                continue
            private.update(history_recovery._tombstone(data, item, project))
            break
        private.add(item)
    return private, set(names)


def _title(text):
    """A title on one line, cut at a character boundary to 40 UTF-8 bytes with a final `...` when cut."""
    text = start_memory.one_line(text)
    data = text.encode('utf-8')
    if len(data) <= TITLE_BYTES:
        return text
    return data[:TITLE_BYTES - 3].decode('utf-8', errors='ignore') + '...'
