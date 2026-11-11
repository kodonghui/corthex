"""ID-only run logs (TBL-121; SPEC-144; TASK-103).

One file per run, `runs/<run>.json`, kept on this device and deleted by its
own time after the retention period. A curation, a consolidation or an undo
adds one apply to its log after that apply's revision reservation and before
it writes curation progress. The reservation advances the mandatory run:<id>
revision; this module never does, so a log that cannot be written leaves the
apply in place, notes the failure, and leaves the run unlisted and unundoable.
A log holds IDs, kinds, counters, times and hashes, never item, line or turn
text. The curator adds its applies (TASK-088), consolidation its own
(TASK-089) and undo reads them (TASK-105 to 108); from release 0.3.0 (TASK-117)
the memory worker and the command runner reach them for a format-2 store, and a
session start's retention expires them (`c2_retention`).
"""
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re

from . import (conflict_types, curation, diagnostics, files, format2, item_types, revision_io, state_types, store,
               worker_support)

KINDS = {'curate', 'consolidate', 'undo'}
FIELDS = 'id kind at ended device undoes epoch last turns saved statuses merges lines pins conflicts kept revisions applies'.split()
OPS = {'added', 'changed', 'recited', 'removed', 'cut', 'stale', 'undone'}
CANDIDATES = {'absent'} | conflict_types.STATUSES
KEPT = {'later-run', 'later-unlogged-change', 'forgotten', 'history-unavailable', 'revision-unavailable',
        'later-dependent-change'}
# The failure log names the step that could not log its run (TBL-004).
STEPS = {'curate': 'curate', 'consolidate': 'consolidate', 'undo': 'skill'}
_SHA256 = re.compile(r'[0-9a-f]{64}\Z')
_ORDER = {
    'statuses': 'item before after', 'merges': 'item merged', 'lines': 'line op generation history before after',
    'pins': 'item from to place', 'conflicts': 'candidate from to', 'kept': 'id by why',
    'revisions': 'id before after', 'applies': 'generation at changes'}


def _list(value, check):
    if not isinstance(value, list):
        raise ValueError('invalid run log list')
    for entry in value:
        check(entry)


def _key(value, prefix=None):
    format2._id(value, format2._OBJECT)
    if prefix is not None and not value.startswith(prefix + ':'):
        raise ValueError('invalid run log object')


def _status(value):
    curation._shape(value, 'status', 'superseded_by undone_by')
    curation._choice(value['status'], item_types.STATUSES)
    if 'superseded_by' in value:
        format2._id(value['superseded_by'], item_types.ITEM)
    if 'undone_by' in value:
        format2._id(value['undone_by'], format2._RUN)


def _place(value):
    if value == []:
        return
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError('invalid run log place')
    part, pos, before, after = value
    curation._choice(part, set(state_types.PARTS))
    format2._revision(pos)
    for neighbour in (before, after):
        if neighbour != '':
            format2._id(neighbour, state_types.LINE)


def _line(value):
    curation._shape(value, _ORDER['lines'])
    format2._id(value['line'], state_types.LINE)
    curation._choice(value['op'], OPS)
    format2._revision(value['generation'])
    history = value['history']
    if history is not None:
        if not isinstance(history, list) or len(history) != 4:
            raise ValueError('invalid run log history reference')
        format2._id(history[0], format2._EPOCH)
        format2._revision(history[1])
        if history[1] != value['generation'] or history[2] != value['line']:
            raise ValueError('history reference names another apply or line')
        format2._id(history[3], _SHA256)
    _place(value['before'])
    _place(value['after'])
    # The publisher's rules (TASK-077): only an added line was absent, and a removal leaves none.
    if ((value['before'] == []) != (value['op'] == 'added') or
            value['after'] == [] and value['op'] not in {'removed', 'cut', 'stale', 'undone'} or
            value['after'] != [] and value['op'] in {'removed', 'cut', 'stale'}):
        raise ValueError('line operation does not fit its places')


def _pin(value):
    curation._shape(value, _ORDER['pins'])
    format2._id(value['item'], item_types.ITEM)
    for side in ('from', 'to'):
        record = value[side]
        if record is not None:
            curation._shape(record, 'on at device')
            if type(record['on']) is not bool:
                raise ValueError('invalid run log pin')
            format2._time(record['at'])
            format2._id(record['device'], store.DEVICE)
    place = value['place']
    if not isinstance(place, list) or len(place) != 2 or place == [None, None]:
        raise ValueError('invalid run log pin place')
    for index in place:
        if index is not None:
            format2._revision(index)
    if (value['from'] is None) != (place[0] is None) or (value['to'] is None) != (place[1] is None):
        raise ValueError('pin place does not fit its records')
    if value['from'] == value['to'] and place[0] == place[1]:
        raise ValueError('a pin entry must change the pin')


def _check(value):
    curation._shape(value, ' '.join(FIELDS))
    format2._id(value['id'], format2._RUN)
    curation._choice(value['kind'], KINDS)
    format2._time(value['at'])
    format2._time(value['ended'])
    format2._id(value['device'], store.DEVICE)
    if value['kind'] == 'undo':
        format2._id(value['undoes'], format2._RUN)
    elif value['undoes'] != '':
        raise ValueError('only an undo reverses a run')
    format2._id(value['epoch'], format2._EPOCH)
    format2._revision(value['last'])
    if not isinstance(value['turns'], dict):
        raise ValueError('invalid run log turns')
    for stem, seqs in value['turns'].items():
        format2._id(stem, diagnostics.LOG)
        if not isinstance(seqs, list) or len(seqs) != 2:
            raise ValueError('invalid run log turns')
        for seq in seqs:
            format2._revision(seq)
        if not 1 <= seqs[0] <= seqs[1]:
            raise ValueError('invalid run log turns')
    _list(value['saved'], lambda item: format2._id(item, item_types.ITEM))

    def status(entry):
        curation._shape(entry, _ORDER['statuses'])
        format2._id(entry['item'], item_types.ITEM)
        _status(entry['before'])
        _status(entry['after'])
        if entry['before'] == entry['after']:
            raise ValueError('a status entry must change the status')
    _list(value['statuses'], status)

    def merge(entry):
        curation._shape(entry, _ORDER['merges'])
        format2._id(entry['item'], item_types.ITEM)
        if not isinstance(entry['merged'], list) or not entry['merged'] or entry['item'] in entry['merged']:
            raise ValueError('invalid run log merge')
        for item in entry['merged']:
            format2._id(item, item_types.ITEM)
    _list(value['merges'], merge)
    _list(value['lines'], _line)
    _list(value['pins'], _pin)

    def conflict(entry):
        curation._shape(entry, _ORDER['conflicts'])
        format2._id(entry['candidate'], format2._CANDIDATE)
        curation._choice(entry['from'], CANDIDATES)
        curation._choice(entry['to'], CANDIDATES)
        if entry['from'] == entry['to']:
            raise ValueError('a candidate entry must change the candidate')
    _list(value['conflicts'], conflict)

    def kept(entry):
        curation._shape(entry, _ORDER['kept'])
        _key(entry['id'])
        if entry['by'] != '':
            format2._id(entry['by'], format2._RUN)
        curation._choice(entry['why'], KEPT)
    _list(value['kept'], kept)

    def revision(entry):
        curation._shape(entry, _ORDER['revisions'])
        _key(entry['id'])
        if entry['before'] is not None:
            format2._revision(entry['before'])
        format2._revision(entry['after'])
        if entry['before'] is not None and entry['before'] >= entry['after']:
            raise ValueError('a revision must advance')
    _list(value['revisions'], revision)

    def apply(entry):
        curation._shape(entry, _ORDER['applies'])
        format2._revision(entry['generation'])
        format2._time(entry['at'])
        if not isinstance(entry['changes'], list) or not entry['changes'] or entry['changes'] != sorted(set(entry['changes'])):
            raise ValueError('invalid run log apply')
        for key in entry['changes']:
            _key(key)
    _list(value['applies'], apply)
    _links(value)
    return value


def _links(value):
    """Every apply's changes, revisions and aggregate entries name one another (TBL-121)."""
    applies = value['applies']
    if not applies:
        raise ValueError('a run log needs an apply')
    generations = [entry['generation'] for entry in applies]
    if generations != sorted(set(generations)) or generations[-1] != value['last']:
        raise ValueError('run log applies out of order')
    times = [value['at']] + [entry['at'] for entry in applies]
    if times != sorted(times) or applies[-1]['at'] != value['ended']:
        raise ValueError('run log times out of order')
    linked = {(key, entry['generation']) for entry in applies for key in entry['changes']}
    revisions = [(entry['id'], entry['after']) for entry in value['revisions']]
    if len(revisions) != len(set(revisions)) or set(revisions) != linked:
        raise ValueError('run log revisions do not match its applies')
    previous = {}
    for entry in sorted(value['revisions'], key=lambda entry: entry['after']):
        if entry['id'] in previous and entry['before'] != previous[entry['id']]:
            raise ValueError('run log revisions skip a change')
        previous[entry['id']] = entry['after']
    named = {'item:' + item for item in value['saved']}
    named |= {'item:' + entry['item'] for entry in value['statuses']}
    named |= {'item:' + entry['item'] for entry in value['merges']}
    named |= {'pin:' + entry['item'] for entry in value['pins']}
    named |= {'candidate:' + entry['candidate'] for entry in value['conflicts']}
    # A line's revision at each apply has its own entry: its history reference finds the version before.
    lines = {('line:' + entry['line'], entry['generation']) for entry in value['lines']}
    if len(lines) != len(value['lines']) or lines != {pair for pair in linked if pair[0].startswith('line:')}:
        raise ValueError('run log lines do not match its applies')
    if any(entry['history'] is not None and entry['history'][0].lower() != value['epoch'].lower()
           for entry in value['lines']):
        raise ValueError('a history reference names another epoch')
    named |= {key for key, _ in lines}
    if named != {key for key, _ in linked}:
        raise ValueError('run log entries do not match its applies')
    saved = value['saved']
    if len(saved) != len(set(saved)) or any(entry['item'] not in saved for entry in value['merges']):
        raise ValueError('a merged item must be saved by its run')


def parse(data):
    """A strict TBL-121 log; anything else raises ValueError and is unlisted."""
    value = format2._document(data)
    return _check(value)


def log_bytes(value):
    value = _check(json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False)))
    ordered = {key: value[key] for key in FIELDS}
    for field, order in _ORDER.items():
        fields = order.split()
        ordered[field] = [{key: entry[key] for key in fields} for entry in value[field]]
    for entry in ordered['statuses']:
        entry['before'], entry['after'] = (item_types._ordered(entry[side], ('status', 'superseded_by', 'undone_by'))
                                           for side in ('before', 'after'))
    for entry in ordered['pins']:
        for side in ('from', 'to'):
            if entry[side] is not None:
                entry[side] = item_types._ordered(entry[side], ('on', 'at', 'device'))
    ordered['turns'] = {stem: value['turns'][stem] for stem in sorted(value['turns'])}
    return (json.dumps(ordered, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode('utf-8')


def start(run, kind, at, device, undoes=''):
    """A run's log before its first apply; only a run that changes something is written."""
    format2._id(run, format2._RUN)
    curation._choice(kind, KINDS)
    format2._time(at)
    format2._id(device, store.DEVICE)
    return {'id': run, 'kind': kind, 'at': at, 'ended': at, 'device': device, 'undoes': undoes, 'epoch': None,
            'last': None, 'turns': {}, 'saved': [], 'statuses': [], 'merges': [], 'lines': [], 'pins': [],
            'conflicts': [], 'kept': [], 'revisions': [], 'applies': []}


def lines(effects):
    """The run log entries and revisions of the TASK-077 publisher's line effects."""
    entries, revisions = [], []
    for effect in effects:
        history = effect['history']
        entries.append({'line': effect['line'], 'op': effect['op'], 'generation': effect['generation'],
                        'history': None if history is None else list(history),
                        'before': list(effect['before']), 'after': list(effect['after'])})
        revisions.append({'id': 'line:' + effect['line'], 'before': effect['before_revision'],
                          'after': effect['after_revision']})
    return {'lines': entries, 'revisions': revisions}


def add(log, progress, at, effects):
    """The log with one more apply, read from the reservation's progress and the apply's effects.

    `effects` holds the apply's `revisions` and any of `saved`, `statuses`,
    `merges`, `lines`, `pins`, `conflicts`, `kept` and `turns`. The apply's
    changes are its revisions' objects, which must all have this generation.
    """
    fence = format2.parse_curation(format2.curation_bytes(progress))['fence']
    generation, epoch = fence['generation'], fence['epoch']
    if fence['revisions'].get('run:' + log['id']) != generation:
        raise ValueError('the reservation did not advance this run')
    if log['epoch'] not in (None, epoch):
        raise ValueError('the fence epoch changed within the run')
    unknown = set(effects) - {'saved', 'statuses', 'merges', 'lines', 'pins', 'conflicts', 'kept', 'revisions', 'turns'}
    if unknown or not effects.get('revisions'):
        raise ValueError('an apply needs its revisions')
    if any(entry['after'] != generation for entry in effects['revisions']):
        raise ValueError('an apply revision names another generation')
    value = copy.deepcopy(log)
    for field in ('saved', 'statuses', 'merges', 'lines', 'pins', 'conflicts', 'kept', 'revisions'):
        value[field].extend(copy.deepcopy(list(effects.get(field, ()))))
    for stem, (first, last) in dict(effects.get('turns', {})).items():
        known = value['turns'].get(stem)
        value['turns'][stem] = [first, last] if known is None else [min(known[0], first), max(known[1], last)]
    changes = sorted({entry['id'] for entry in effects['revisions']})
    value['applies'].append({'generation': generation, 'at': at, 'changes': changes})
    value.update(epoch=epoch, last=generation, ended=at)
    return _check(value)


def path(root, run):
    format2._id(run, format2._RUN)
    return Path(root) / 'runs' / (run + '.json')


def write(memory, root, log, check):
    """Durably replace the run's log; False, with the failure noted, when it could not.

    A lost lease or a stale fence raises: the caller must stop. Any other
    failure leaves the apply in place and the run unlisted (SPEC-144).
    """
    try:
        data = log_bytes(log)
        files.replace_bytes(path(root, log['id']), data, check=check, path_check=memory.fence.check)
    except (OSError, ValueError, UnicodeError, TypeError, KeyError) as error:
        memory.note(error, step=STEPS.get(log.get('kind'), 'curate') if isinstance(log, dict) else 'curate')
        return False
    return True


def read(root, run, reader=None):
    """The run's log, or None when it is missing, damaged, incomplete, another run's or reached through a link.

    `reader` reads a path's bytes, as a store binding's path fence does; by
    default the file is read directly.
    """
    target = path(root, run)
    try:
        value = parse(target.read_bytes() if reader is None else reader(target))
    except worker_support.UnsafePath:
        return None
    except (OSError, ValueError, UnicodeError, TypeError, KeyError):
        return None
    return value if value['id'] == run else None


def eligible(log, progress, device):
    """Whether the run can be listed or undone: its last apply is the run's current revision."""
    if log is None:
        return False
    fence = progress['fence']
    return (log['device'] == device and log['epoch'].lower() == fence['epoch'].lower() and
            fence['revisions'].get('run:' + log['id']) == log['last'])


def _cutoff(when, days):
    """The retention cutoff as a TBL-121 time and as an aware UTC moment."""
    format2._time(when)
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 3650:
        raise ValueError('invalid retention days')
    moment = datetime.strptime(when, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=timezone.utc) - timedelta(days=days)
    return moment.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (moment.microsecond // 1000), moment


def listed(root, progress, device, *, when, days, reader=None):
    """The runs that can be selected, newest first: whole, current and not past retention."""
    cutoff = _cutoff(when, days)[0]
    found = []
    for name in _names(Path(root) / 'runs'):
        run = name[:-5] if name.endswith('.json') else ''
        if not format2._RUN.fullmatch(run):
            continue
        log = read(root, run, reader)
        if eligible(log, progress, device) and log['ended'] >= cutoff:
            found.append(log)
    return sorted(found, key=lambda log: (log['ended'], log['id']), reverse=True)


def _names(folder):
    """The names in the run log folder; none when it is missing."""
    try:
        return sorted(os.listdir(str(folder)))
    except FileNotFoundError:
        return []


def _copy(name):
    """The run whose backup or temporary log copy `name` is, else ''."""
    run, _, rest = name.partition('.')
    rest = '.' + rest
    if format2._RUN.fullmatch(run) and (rest == '.json.bak' or rest.startswith('.json.') and rest.endswith('.tmp')
                                         and len(rest) >= len('.json') + 5):
        return run
    return ''


def expire(memory, root, deadline, *, when, days):
    """Delete the run logs whose own time is past retention; returns how many.

    A log's time is its last apply. A log that cannot be read, and a backup
    or temporary copy whose log is gone, go by their file's modification
    time. The holder of the layer lease calls this; a lost lease stops it,
    and what is left waits for the next start. Nothing is read or deleted
    through a link: a linked run folder raises UnsafePath, and a linked log
    or copy is left with its run.
    """
    root = Path(root)
    check = revision_io.guard(memory, root, deadline)
    cutoff, moment = _cutoff(when, days)
    limit = moment.timestamp()
    folder = root / 'runs'
    if memory.fence.check(folder) is None:
        check()
        return 0
    names = _names(folder)
    present, copies = set(names), {}
    for name in names:
        if _copy(name):
            copies.setdefault(_copy(name), []).append(name)

    def fenced(path):
        def guard():
            check()
            memory.fence.check(path)
        return guard
    removed = 0
    for name in names:
        check()
        run = name[:-5] if name.endswith('.json') else ''
        if not format2._RUN.fullmatch(run):
            continue
        primary = folder / name
        try:
            info = memory.fence.check(primary)
            if info is None:
                continue
            log = read(root, run)
            expired = log['ended'] < cutoff if log is not None else info.st_mtime < limit
            if not expired:
                continue
            # Its backup and temporary copies go first, so a failed cleanup keeps the log.
            for other in copies.get(run, []) + [name]:
                files._unlink(folder / other, fenced(folder / other))
        except worker_support.UnsafePath:
            continue
        removed += 1
    for name in names:
        run = _copy(name)
        if not run or run + '.json' in present:
            continue
        check()
        try:
            info = memory.fence.check(folder / name)
            if info is not None and info.st_mtime < limit:
                files._unlink(folder / name, fenced(folder / name))
        except worker_support.UnsafePath:
            continue
    check()
    return removed
