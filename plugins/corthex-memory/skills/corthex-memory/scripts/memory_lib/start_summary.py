"""TASK-091: the memory part of the start summary from the curated layer (API-001 steps 5 and 7).

`compose` builds what SPEC-021, SPEC-022 and SPEC-143 show for an enabled
project of a format-2 store: the notices of stage 06's table, the pinned items
that are still current, oldest pin first, and the current state's lines that
the validity view keeps (TBL-013), within the start hook's deadline. It reads
without the layer lease and writes nothing to the curated layer, and of the
item files it reads only those that the summary needs: the pinned items, the
items that decision lines cite and the two items of a conflict candidate. The
one lease it takes is the notice-counter lease (TBL-010): once the conflict
line fits among the notices, it reserves one showing of the oldest eligible
candidate, within a quarter of a second, and a reservation that fails leaves
the line out and counts nothing.

When the deadline passes, the memory part is the one line `Memory could not
be read in time.`, and when anything else fails it is the line about an
internal error, with the error for the hook's failure log; neither deletes a
notice or writes the injection log. `after` is step 7: it deletes each stored
notice that the summary showed, unless a later notice of the same name
replaced it meanwhile, and appends the start's line to the session's injection
log (TBL-011).

Nothing calls this module before the 0.3.0 activation, when the start hook
uses it for format-2 stores; until then the installed start hook keeps C1
behaviour. The notices about sync (SPEC-026, SPEC-027) come with sync in C3.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
import re

from . import (base, clock, conflict_counts, conflict_types, curation, curation_triggers, files, format2,
               history_recovery, injection_log, item_types, locks, model_access, start_memory, state_types)

Notice = start_memory.Notice
WEEK = timedelta(days=7)
STORED = {'curation-failed.json': 'curation-failed', 'consolidation-failed.json': 'consolidation-failed',
          'rebuilt.json': 'rebuilt'}
PINNED = re.compile(r'pin-(i_' + format2._DIGITS + r')\.json\Z')
PIN_KINDS = ('pin-moved', 'pin-dropped', 'pin-restored', 'pin-removed')
TITLE_BYTES = 40
RESERVE_SECONDS = 0.25  # the conflict reservation: its wait for the notice-counter lease and its write
STEP_SECONDS = 1.0   # step 7's reads and deletions, after the summary is printed
TIMEOUT = Notice('unreadable', 'Memory could not be read in time.')
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
        pins, lines, conflict = _layer(memory, root, deadline)
        reserved = None
        if conflict is not None:
            line, candidate = conflict
            notices.append(line)
            if any(shown is line for shown in start_memory.fitting(notices)[0]):
                memory.check(deadline)
                if conflict_counts.reserve(memory, root, candidate,
                                           min(deadline, clock.now() + RESERVE_SECONDS)) is None:
                    notices.pop()
                else:
                    reserved = candidate
        summary = start_memory.build_summary(base_text, notices, pins, lines, zone=zone)
        memory.check(deadline)
        shown = start_memory.fitting(notices)[0]
        kept = tuple((path, data) for notice, path, data in stored if any(notice is value for value in shown))
        return Part(summary.text, 'ok', summary.pins, kept, reserved)
    except locks.LockBusy:
        return Part(start_memory.build_summary(base_text, (TIMEOUT,)).text, 'deadline')
    except Exception as error:
        return Part(start_memory.build_summary(base_text, (INTERNAL,)).text, 'error', error=error)


def after(memory, project, part, host, session, *, when=None):
    """API-001 step 7, once the summary is printed.

    Only a memory part that was composed counts. A stored notice is deleted
    only while it holds the bytes that were shown, so that a later notice of
    the same name stays for the next start; the injection log takes the start's
    line with the pinned items shown (TBL-011).
    """
    if part.outcome != 'ok':
        return After(0, False, ())
    deleted, errors = 0, []
    deadline = clock.now() + STEP_SECONDS
    for path, data in part.shown:
        try:
            if files._retry(lambda: memory.fence.read(path, deadline), deadline) != data:
                continue
            files._unlink(path, lambda: memory.fence.check(path))
            deleted += 1
        except FileNotFoundError:
            continue
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
    soon = _retention(memory, root, settings, now, zone)
    if soon is not None:
        notices.append(soon)
    if settings.values.get('temporary'):
        notices.append(Notice('temporary', TEMPORARY))
    return notices


def _retention(memory, root, settings, now, zone):
    """The unprocessed turns that retention deletes within 7 days, and the first local date (SPEC-009)."""
    period = timedelta(days=settings.values['retention']['days'])
    now = datetime.now(timezone.utc) if now is None else now
    ends = sorted(at + period for at in curation_triggers.turns(memory, root).values() if at + period - WEEK <= now)
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
            data = memory.fence.read(path, deadline)
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
    """(pinned items, oldest pin first; the state lines that the validity view keeps; the conflict line).

    The conflict line is (notice, candidate ID) for the oldest eligible
    candidate whose two items are current, or None. A project without a layer,
    or whose memory was deleted (TBL-017), shows nothing from it; a layer file
    that is missing counts as empty.
    """
    folder = root / 'layer'
    if memory.fence.check(folder) is None or any(
            name == 'deleted.json' or name.startswith('deleted.json.') for name in os.listdir(str(folder))):
        return (), (), None

    def read(name):
        try:
            return memory.fence.read(folder / name, deadline)
        except FileNotFoundError:
            return EMPTY[name]

    private, forgotten = _tombstones(memory, folder, root.name, deadline)
    cache = {}

    def current(item):
        """The item while it is current and no tombstone names it, else None."""
        if item in forgotten:
            return None
        if item not in cache:
            try:
                value = item_types.parse_item(memory.fence.read(folder / 'items' / (item + '.json'), deadline))
            except FileNotFoundError:
                value = None
            if value is not None and value['id'] != item:
                raise ValueError('item file name differs from its ID')
            cache[item] = value
        value = cache[item]
        return value if value is not None and value['status'] == 'current' else None

    state = state_types.parse_state(read('state.json'))
    removed = state_types.parse_removed(read('state-removed.json'))
    cited = sorted({cite for line in state['lines'] if line['part'] == 'decisions'
                    for cite in line['cites'] if item_types.ITEM.fullmatch(cite)})
    items = {item: cache[item] for item in cited if current(item) is not None}
    lines = state_types.validity_view(state, removed, items, private)['lines']
    pins = item_types.parse_pins(read('pins.json'))['pins']
    pinned = []
    for pin in sorted(pins, key=lambda pin: pin['at']):
        value = current(pin['item']) if pin['on'] else None
        if value is not None:
            pinned.append(value)
    conflicts = conflict_types.parse_conflicts(read('conflicts.json'))
    total = len(conflict_types.open_candidates(conflicts))
    counts = conflict_counts.read(memory, root, deadline) if total else None
    for candidate in conflict_counts.eligible(conflicts, counts):
        pair = [current(item) for item in candidate['items']]
        if None not in pair:
            text = CONFLICT % (pair[0]['id'], _title(pair[0]['title']), pair[1]['id'], _title(pair[1]['title']),
                               total)
            return tuple(pinned), tuple(lines), (Notice('conflict', text), candidate['id'])
    return tuple(pinned), tuple(lines), None


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
                data = memory.fence.read(path / name, deadline)
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
