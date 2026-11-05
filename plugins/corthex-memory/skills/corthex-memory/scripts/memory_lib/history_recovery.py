"""Conditional history repair primitive, never an automatic recovery entry.

The actual maintenance owner must establish supported tombstone-first writers,
complete initialization and an original non-deletion lifecycle context. A lock
or absent project tombstone does not prove that context. This helper supplies
its own strict privacy facts, never a caller filter or completeness boolean.
Actual forget scrub remains layer-only; this repair requires curator then layer.
"""
import hashlib
import os
from pathlib import Path
import stat

from . import base, configuration, curation, diagnostics, fence_plan, files
from . import format2, history_io, item_types, locks, revision_io, state_types, store


class RecoveryFailed(RuntimeError):
    def __init__(self, published, removed=0, reasons_cleared=0, attempted=False):
        super().__init__('history recovery incomplete; cleanup unconfirmed')
        self.published, self.cleanup_pending = published, True
        self.publication_uncertain = attempted and not published
        self.removed = removed if published else 0
        self.reasons_cleared = reasons_cleared if published else 0


def _stamp(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _read(memory, path, deadline, check, durable=False):
    check()
    info = memory.fence.check(path)
    if info is None:
        raise FileNotFoundError()
    if not stat.S_ISREG(info.st_mode):
        raise locks.LostLock()
    flags = ((os.O_RDWR if durable else os.O_RDONLY) | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) |
             getattr(os, 'O_NONBLOCK', 0))
    fd = files._retry(lambda: os.open(str(path), flags), deadline)
    identity = info.st_dev, info.st_ino
    def guard():
        check()
        current, opened = memory.fence.check(path), os.fstat(fd)
        if (current is None or not stat.S_ISREG(opened.st_mode) or
                (current.st_dev,current.st_ino) != identity or
                (opened.st_dev,opened.st_ino) != identity):
            raise locks.LostLock()
        check()
    try:
        before = os.fstat(fd)
        data = history_io._bytes(fd,guard)
        if durable:
            guard()
            files._sync(fd)
            guard()
            if history_io._bytes(fd,guard) != data:
                raise fence_plan.Stale()
        guard()
        after = os.fstat(fd)
        if _stamp(before) != _stamp(after):
            raise fence_plan.Stale()
        current = memory.fence.check(path)
        # Windows can expose different ctime meanings through fstat/lstat.
        # Compare FD stamps with FD stamps and path stamps with path stamps.
        if current is None or _stamp(info) != _stamp(current):
            raise fence_plan.Stale()
        return data, _stamp(current)+(hashlib.sha256(data).digest(),)
    finally:
        os.close(fd)


def _control(memory, root, deadline, ownership):
    try:
        data, _ = _read(memory,root/'curation.json',deadline,ownership)
        return format2.parse_curation(data)
    except (FileNotFoundError,ValueError,UnicodeError):
        raise files.RestoreNeeded() from None


def _maintenance(memory, root, deadline, precondition):
    if not callable(precondition):
        raise TypeError('original non-deletion maintenance precondition required')
    original = revision_io.guard(memory,root,deadline,curator=True)
    proof = fence_plan.snapshot(_control(memory,root,deadline,original))
    fence = proof['fence']
    binding = (proof['applies'],fence['epoch'],fence['generation'],tuple(sorted(fence['revisions'].items())))
    def check():
        original()
        if not fence_plan.matches(_control(memory,root,deadline,original),proof):
            raise fence_plan.Stale()
        if precondition(memory,root,binding) is not None:
            raise TypeError('maintenance precondition must return only None')
        original()
        if not fence_plan.matches(_control(memory,root,deadline,original),proof):
            raise fence_plan.Stale()
        original()
    return history_io._project_check(memory,root,check), original


def _names(memory, folder, deadline, check):
    check()
    info = memory.fence.check(folder)
    if info is None or not stat.S_ISDIR(info.st_mode):
        raise files.RestoreNeeded()
    names = files._retry(lambda: sorted(p.name for p in folder.iterdir()),deadline)
    check()
    again = memory.fence.check(folder)
    if again is None or (again.st_dev,again.st_ino) != (info.st_dev,info.st_ino):
        raise locks.LostLock()
    return names, (info.st_dev,info.st_ino)


def _tombstone(data, item, project):
    value = item_types._document(data)
    curation._shape(value,'item project at device quotes')
    format2._id(value['item'],item_types.ITEM)
    if value['item'] != item or base.project_folder_name(value['project']) != project:
        raise ValueError('tombstone identity mismatch')
    format2._time(value['at'])
    format2._id(value['device'],store.DEVICE)
    # Supported C2 items have at least one quote. An empty fact list cannot
    # establish their full entry-exclusion set for this recovery operation.
    if not isinstance(value['quotes'],list) or not value['quotes']:
        raise ValueError('incomplete tombstone quote facts')
    cites = {item}
    for quote in value['quotes']:
        curation._shape(quote,'device entry log start end')
        format2._id(quote['device'],store.DEVICE)
        format2._id(quote['entry'],item_types.ENTRY)
        format2._id(quote['log'],diagnostics.LOG)
        if (any(not configuration.integer(quote[key]) or quote[key] < 0 for key in ('start','end')) or
                quote['end'] < quote['start']):
            raise ValueError('invalid tombstone quote positions')
        cites.add(quote['entry'])
    return cites


def _privacy(memory, root, deadline, check):
    folder = root/'layer/tombstones'
    names, directory = _names(memory,folder,deadline,check)
    banned, fingerprints = set(), [('tombstones',directory,tuple(names))]
    for name in names:
        item = name[:-5] if name.endswith('.json') else ''
        if not item_types.ITEM.fullmatch(item):
            # Any backup/temp/unpublished or unknown fact artifact must be
            # reconciled by its real owner, never ignored or chosen here.
            raise files.RestoreNeeded()
        data, identity = _read(memory,folder/name,deadline,check)
        try:
            banned.update(_tombstone(data,item,root.name))
        except (ValueError,UnicodeError,TypeError):
            raise files.RestoreNeeded() from None
        fingerprints.append((name,identity))
    marker = root/'layer/state-removed.json'
    siblings, layer = _names(memory,marker.parent,deadline,check)
    family = tuple(n for n in siblings if n == marker.name or n.startswith(marker.name+'.'))
    if family != (marker.name,):
        raise files.RestoreNeeded()
    data, identity = _read(memory,marker,deadline,check)
    try:
        markers = state_types.parse_removed(data)['removed']
    except (ValueError,UnicodeError):
        raise files.RestoreNeeded() from None
    seen = set()
    for value in markers:
        if 'kind' not in value or value['id'] in seen:
            raise files.RestoreNeeded()
        seen.add(value['id'])
    fingerprints.append(('removed',layer,identity))
    if _names(memory,folder,deadline,check)[0] != names:
        raise fence_plan.Stale()
    check()
    return frozenset(banned), tuple(fingerprints)


def _primary(memory, path, deadline, check):
    try:
        data, identity = _read(memory,path,deadline,check)
    except FileNotFoundError:
        return None, ('missing',)
    try:
        records = state_types.parse_history(data)
    except (ValueError,UnicodeError):
        return None, ('damaged',identity)
    return records, ('valid',identity)


def _fast_privacy(memory, root, deadline, ownership, fingerprint):
    names, directory = _names(memory,root/'layer/tombstones',deadline,ownership)
    if ('tombstones',directory,tuple(names)) != fingerprint[0]:
        raise fence_plan.Stale()
    paths = [(root/'layer/tombstones'/name,identity) for name,identity in fingerprint[1:-1]]
    _, layer, identity = fingerprint[-1]
    marker = root/'layer/state-removed.json'
    siblings, current_layer = _names(memory,marker.parent,deadline,ownership)
    if current_layer != layer or tuple(n for n in siblings if n == marker.name or n.startswith(marker.name+'.')) != (marker.name,):
        raise fence_plan.Stale()
    for path,identity in paths+[(marker,identity)]:
        ownership()
        info = memory.fence.check(path)
        if info is None or _stamp(info) != identity[:-1]:
            raise fence_plan.Stale()
    ownership()


def recover(memory, root, deadline, *, maintenance_precondition):
    """Repair only from the named backup; no global scrub/deletion success.

    Required owner callback receives the exact memory/root and immutable
    control binding. It must raise on refusal and return only None on success.
    Healthy primary data wins unchanged, including over a newly readable copy.
    """
    root = Path(root)
    check, ownership = _maintenance(memory,root,deadline,maintenance_precondition)
    path, backup = root/'state-history.jsonl', root/'state-history.jsonl.bak'
    current, initial = _primary(memory,path,deadline,ownership)
    check()
    unchanged = {'published':False,'cleanup_pending':False,'removed':0,'reasons_cleared':0}
    if current is not None:
        return unchanged
    banned, fingerprint = _privacy(memory,root,deadline,ownership)
    check()
    try:
        source, source_identity = _read(memory,backup,deadline,ownership)
        records = state_types.parse_history(source)
    except (FileNotFoundError,ValueError,UnicodeError):
        raise files.RestoreNeeded() from None
    kept, removed, cleared = [], 0, 0
    for record in records:
        value = record.value
        if banned.intersection(value['cites']):
            removed += 1
        elif value['why']:
            value['why'] = ''
            kept.append(state_types.history_record_bytes(value))
            cleared += 1
        else:
            kept.append(record.raw)
    data = b''.join(kept)

    def facts():
        check()
        if _privacy(memory,root,deadline,ownership) != (banned,fingerprint):
            raise fence_plan.Stale()
        check()

    def source_check():
        if _read(memory,backup,deadline,ownership)[1] != source_identity:
            raise fence_plan.Stale()

    def staging_guard():
        check()
        _fast_privacy(memory,root,deadline,ownership,fingerprint)

    def published_check():
        actual, identity = _read(memory,path,deadline,ownership)
        if actual != data or identity != published_identity[0]:
            raise fence_plan.Stale()

    def cleanup_guard():
        facts()
        source_check()
        published_check()
        for target,identity in ((backup,source_identity),(path,published_identity[0])):
            info = memory.fence.check(target)
            if info is None or _stamp(info) != identity[:-1]:
                raise fence_plan.Stale()
        _fast_privacy(memory,root,deadline,ownership,fingerprint)
        ownership()

    ready, attempted, published, error = [], [], [], None
    published_identity = []
    temporary = None
    outcome = unchanged
    try:
        temporary = files._temporary(path,data,True,check=staging_guard,path_check=memory.fence.check,ready=ready.append)
        def move():
            facts()
            ready[0]()
            staged, staged_identity = _read(memory,temporary,deadline,staging_guard,durable=True)
            if staged != data:
                raise fence_plan.Stale()
            staging_guard()
            ready[0]()
            source_check()
            # No expensive validation/caller callback follows this final read.
            latest, identity = _primary(memory,path,deadline,ownership)
            if latest is not None:
                if attempted:
                    raise fence_plan.Stale()
                return
            if identity != initial:
                raise fence_plan.Stale()
            for target,stamp in ((backup,source_identity),(temporary,staged_identity)):
                info = memory.fence.check(target)
                if info is None or _stamp(info) != stamp[:-1]:
                    raise fence_plan.Stale()
            _fast_privacy(memory,root,deadline,ownership,fingerprint)
            ownership()
            attempted.append(True)
            os.replace(str(temporary),str(path))
            published.append(True)
        files._retry(move,deadline)
        if published:
            facts()
            actual, identity = _read(memory,path,deadline,ownership)
            if actual != data:
                raise fence_plan.Stale()
            state_types.parse_history(actual)
            published_identity.append(identity)
            files._unlink(backup,cleanup_guard)
            facts()
            published_check()
            outcome = {'published':True,'cleanup_pending':False,'removed':removed,'reasons_cleared':cleared}
    except Exception as failure:
        error = failure
    finally:
        if temporary is not None:
            try:
                files._unlink(temporary,ready[0])
            except Exception as cleanup:
                if error is None:
                    error = cleanup
    if error is not None:
        raise RecoveryFailed(bool(published),removed,cleared,bool(attempted)) from error
    return outcome
