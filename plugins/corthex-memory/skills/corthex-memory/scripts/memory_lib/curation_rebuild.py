"""Make a lost curation record again (TBL-009) and replace a raw log's markers (TBL-008).

Not wired: the worker (TASK-088) calls `rebuild` under its curation and layer
leases when neither the record nor its backup parses, and `replace_markers`
after it applies; no hook or command reaches this module, so installed C1
behaviour is unchanged.

For each raw log file, the newest entry that an item quotes or a state line
cites counts as processed, with the entries before it, and every entry after it
as unprocessed, even in its own turn. The rebuilt record has a new fence epoch,
so no earlier request or undo proof applies, and it loses the fault guard's
stop. A `rebuilt` notice (TBL-010) says once that some turns may be curated
twice; consolidation merges what was.
"""
from datetime import datetime
import os
from pathlib import Path

from . import base, clock, diagnostics, files, item_types, locks, raw_rewrite, request_inputs
from . import retention, revision_io, state_types, worker_support

_PLACEHOLDER = '0' * 32
RAW_WAIT = 1.0


def _parse(data, log, found):
    """Add the complete entries of `data` in seq order; damaged and unfinished lines left out."""
    for line in data.split(b'\n')[:-1]:
        try:
            entry = raw_rewrite._entry(line, log)
        except (ValueError, UnicodeError):
            continue
        if found and entry['seq'] <= found[-1]['seq']:
            continue
        found.append(entry)
    return found


def _entries(memory, path, log, deadline):
    return _parse(memory.fence.read(path, deadline), log, [])


def _suffix(memory, path, offset, deadline):
    """The bytes after `offset`, which hooks appended since a read without the raw lease."""
    memory.fence.check(path)
    chunks = []
    with path.open('rb') as source:
        source.seek(offset)
        while True:
            if clock.now() >= deadline:
                raise locks.LockBusy()
            memory.fence.check(path)
            chunk = source.read(worker_support.CHUNK)
            if not chunk:
                break
            chunks.append(chunk)
    memory.fence.check(path)
    return b''.join(chunks)


def _logs(memory, root):
    folder = root / 'raw'
    if memory.fence.check(folder) is None:
        return []
    names = (name[:-6] for name in os.listdir(str(folder)) if name.endswith('.jsonl'))
    return sorted(name for name in names if diagnostics.LOG.fullmatch(name))


def processed(memory, root, deadline):
    """Each raw log's processed count: the seq of the newest entry quoted or cited, else 0.

    Items are those that no tombstone names (TBL-016); every line of the
    current state counts, also one that the validity view hides. The caller
    holds the layer lease, under which no raw log is rewritten.
    """
    root = Path(root)
    quoted = {}
    for value in request_inputs.layer(root).items.values():
        for quote in value['quotes']:
            quoted.setdefault(quote['log'], set()).add(quote['entry'])
    state = state_types.parse_state(memory.fence.read(root / 'layer' / 'state.json', deadline))
    cited = {cite for line in state['lines'] for cite in line['cites'] if item_types.ENTRY.fullmatch(cite)}
    counts = {}
    for log in _logs(memory, root):
        known = cited | quoted.get(log, set())
        seqs = [entry['seq'] for entry in _entries(memory, root / 'raw' / (log + '.jsonl'), log, deadline)
                if entry['id'] in known]
        counts[log] = max(seqs, default=0)
    return counts


def _stamp(at):
    return at[:19].replace('-', '').replace(':', '') + 'Z'


def replace_markers(memory, root, log, count, deadline):
    """Under the log's raw lease, keep one marker for each turn with entries after `count`.

    The caller holds the layer lease, so the log is only appended to. Its
    complete lines are read before the raw lease and only the lines appended
    since are read under it, so a hook that records waits as briefly as it
    does for another hook. A marker is named by the time of its turn's oldest
    unprocessed entry. New markers are made before stale ones are removed, so
    a stop in between only makes a trigger early. Returns how many markers
    were made and removed.
    """
    root = Path(root)
    path = root / 'raw' / (log + '.jsonl')
    folder = root / 'unprocessed'
    before = memory.fence.check(path)
    if before is None:
        raise FileNotFoundError('no raw log')
    data = memory.fence.read(path, deadline)
    prefix = data[:data.rfind(b'\n') + 1]
    found = _parse(prefix, log, [])
    acquire = min(deadline, clock.now() + RAW_WAIT)
    with memory.lease(path.with_suffix('.lock'), 'raw', deadline, acquire_deadline=acquire):
        def check():
            memory.check(deadline, memory.held)
        after = memory.fence.check(path)
        if (after is None or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino) or
                after.st_size < len(prefix)):
            raise locks.LostLock()
        _parse(_suffix(memory, path, len(prefix), deadline), log, found)
        wanted = {}
        for entry in found:
            if entry['kind'] in ('prompt', 'answer') and entry['seq'] > count:
                turn, stamp = int(entry['turn']), _stamp(entry['at'])
                wanted[turn] = min(stamp, wanted.get(turn, stamp))
        names = {'%s.%s.%d' % (stamp, log, turn) for turn, stamp in wanted.items()}
        check()
        if memory.fence.check(folder) is None:
            raise FileNotFoundError('no unprocessed folder')
        existing = {}
        for name in os.listdir(str(folder)):
            match = retention.MARKER.fullmatch(name)
            if match is None or match.group(2) != log:
                continue
            try:
                datetime.strptime(match.group(1), '%Y%m%dT%H%M%SZ')
            except ValueError:
                continue  # No hook names a marker so; it is not the plugin's.
            existing[name] = int(match.group(3))
        made = 0
        for name in sorted(names - set(existing)):
            target = folder / name

            def create():
                check()
                memory.fence.check(target)
                try:
                    fd = base.private_open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    return 0
                os.close(fd)
                return 1
            made += files._retry(create, deadline)
        stale = [(folder / name, turn) for name, turn in sorted(existing.items()) if name not in names]
        removed = retention._markers(memory, stale, frozenset(), check, deadline)
        check()
    return made, removed


def rebuild(memory, root, deadline, now=None):
    """Make the record again under the caller's curation and layer leases and return it.

    Refused while the record or its backup parses. The notice follows the
    record, and each raw log's markers follow the notice.
    """
    root = Path(root)
    check = revision_io.guard(memory, root, deadline, curator=True)
    counts = processed(memory, root, deadline)
    at = base.utc_time(now)
    value = {'logs': {log: count for log, count in counts.items() if count},
             'applies': 0, 'recent': [], 'consolidation': {'failures': 0}, 'rebuilt': at,
             'fence': {'epoch': _PLACEHOLDER, 'generation': 0, 'revisions': {}}}
    published = revision_io.rebuild(memory, root, value, deadline)
    files.replace_bytes(root / 'notices' / 'rebuilt.json',
                        item_types.notice_bytes({'at': at, 'kind': 'rebuilt'}), True,
                        check=check, path_check=memory.fence.check)
    for log in counts:
        replace_markers(memory, root, log, counts[log], deadline)
    check()
    return published
