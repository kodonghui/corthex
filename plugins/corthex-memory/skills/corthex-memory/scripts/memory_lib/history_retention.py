"""Healthy-primary-only TBL119 retention; no runner, repair or privacy scrub.

The actual project runner still owns curation then layer. This primitive only
needs the original layer lease, and never edits progress, state, run logs or
revision counters. Its owner establishes supported canonical/non-deletion
context and the current retention policy through a mandatory None-only check.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import os
from pathlib import Path
import re
import stat
import time

from . import base, cleanup, configuration, fence_plan, files, format2
from . import history_io, history_recovery, locks, revision_io, state_types


@dataclass(frozen=True)
class RetentionContext:
    control: tuple
    original_sha256: str
    retained_sha256: str
    at: str
    cutoff: str
    days: int
    published: bool


class RetentionFailed(RuntimeError):
    def __init__(self, published, attempted, removed, artifacts):
        super().__init__('history retention incomplete; cleanup unconfirmed')
        self.published = published
        self.publication_uncertain = attempted and not published
        self.cleanup_pending = True
        self.removed = removed if published else 0
        self.artifacts_removed = artifacts


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _time(value):
    return datetime.fromisoformat(value[:-1]+'+00:00')


def _binding(data):
    proof = fence_plan.snapshot(format2.parse_curation(data))
    fence = proof['fence']
    return proof['applies'], fence['epoch'], fence['generation'], tuple(sorted(fence['revisions'].items()))


def retain_history(memory, root, deadline, *, when, days, history_precondition):
    """Trim by one fixed cutoff, then clean only known eligible history copies.

    Callback(memory, root, frozen_context) must raise on refusal and return None.
    Counts describe this invocation, not whole-project status or privacy success.
    Retained raw bytes/hashes stay exact; no retained reason is rewritten.
    """
    if not callable(history_precondition):
        raise TypeError('history retention precondition required')
    if not configuration.integer(days) or days < 1:
        raise ValueError('positive retention days required')
    days = int(days)
    at = base.utc_time(when)
    cutoff = _time(at)-timedelta(days=days)
    root = Path(root)
    ownership = revision_io.guard(memory,root,deadline)
    path = root/'state-history.jsonl'
    backup = path.with_name(path.name+'.bak')
    try:
        primary, source_identity = history_recovery._read(memory,path,deadline,ownership)
    except FileNotFoundError:
        raise files.RestoreNeeded() from None
    records = history_io._strict(primary)
    control_data, control_identity = history_recovery._read(memory,root/'curation.json',deadline,ownership)
    try:
        control = _binding(control_data)
    except (ValueError,UnicodeError):
        raise files.RestoreNeeded() from None
    kept = tuple(record for record in records if _time(record.value['at']) >= cutoff)
    retained = b''.join(record.raw for record in kept)
    removed = len(records)-len(kept)
    future = sum(_time(record.value['at']) > _time(at) for record in records)
    original_sha256, retained_sha256 = _sha(primary), _sha(retained)
    phase = dict(published=False, attempted=False, artifacts=0)
    current = [primary, source_identity]
    owned = {}
    temporary_pattern = re.compile(re.escape(path.name)+r'(?:\.bak)?\.[a-z0-9_]{8}\.tmp\Z')

    def proven(function):
        def guarded(*args, **kwargs):
            if 'proof_failure' in phase:
                raise phase['proof_failure']
            try:
                return function(*args, **kwargs)
            except BaseException as failure:
                phase.setdefault('proof_failure',failure)
                raise
        return guarded

    def context():
        return RetentionContext(control,original_sha256,retained_sha256,at,base.utc_time(cutoff),days,phase['published'])

    @proven
    def known_links():
        info = memory.fence.check(path)
        if info is None:
            raise fence_plan.Stale()
        if info.st_nlink == 1:
            return False
        other = memory.fence.check(backup)
        if (info.st_nlink != 2 or other is None or not stat.S_ISREG(other.st_mode) or
                (info.st_dev,info.st_ino) != (other.st_dev,other.st_ino) or other.st_nlink != 2):
            raise locks.LostLock()
        return True

    @proven
    def after_own_unlink(was_linked):
        if not was_linked:
            return
        # Only the just-completed owned unlink may explain a ctime change.
        # Bytes, inode, size, mtime and the exact 2-to-1 link decrement remain
        # bound; an unrelated link or changed source is never rebaselined.
        data, identity = history_recovery._read(memory,path,deadline,ownership,durable=True)
        info = memory.fence.check(path)
        if (info is None or info.st_nlink != 1 or data != current[0] or
                identity[:4] != current[1][:4]):
            raise fence_plan.Stale()
        current[1] = identity

    def deleted_check():
        names, _ = history_recovery._names(memory,root/'layer',deadline,ownership)
        if any(name == 'deleted.json' or name.startswith('deleted.json.') for name in names):
            raise fence_plan.Stale()

    @proven
    def owner_check():
        ownership()
        deleted_check()
        data, identity = history_recovery._read(memory,root/'curation.json',deadline,ownership)
        if (data,identity) != (control_data,control_identity):
            raise fence_plan.Stale()
        if history_precondition(memory,root,context()) is not None:
            raise TypeError('history precondition must return only None')
        ownership()

    @proven
    def source_check(durable=False):
        known_links()
        data, identity = history_recovery._read(memory,path,deadline,ownership,durable=durable)
        history_io._strict(data)
        if (data,identity) != tuple(current):
            raise fence_plan.Stale()

    @proven
    def fast(artifacts=()):
        # No caller callback follows the last complete source read.
        ownership()
        deleted_check()
        known_links()
        for target, identity in [(path,current[1]),(root/'curation.json',control_identity)]+list(artifacts):
            info = memory.fence.check(target)
            if info is None or history_recovery._stamp(info) != identity[:-1]:
                raise fence_plan.Stale()
        ownership()

    @proven
    def validate(artifacts=()):
        owner_check()
        for target, identity in artifacts:
            if history_recovery._read(memory,target,deadline,ownership)[1] != identity:
                raise fence_plan.Stale()
        source_check(durable=True)
        fast(artifacts)

    def stage(target, data):
        owner_check()
        source_check()
        ready = []
        temporary = files._temporary(target,data,True,check=owner_check,path_check=memory.fence.check,ready=ready.append)
        ready[0]()
        info = memory.fence.check(temporary)
        ready[0]()
        if info is None:
            raise locks.LostLock()
        identity = history_recovery._stamp(info)+(hashlib.sha256(data).digest(),)
        # Register the original creation guard before subsequent read/fsync.
        owned[temporary] = ready[0]
        if history_recovery._read(memory,temporary,deadline,ownership,durable=True) != (data,identity):
            raise fence_plan.Stale()
        return temporary, identity

    def existing_backup():
        try:
            return history_recovery._read(memory,backup,deadline,ownership)[1]
        except FileNotFoundError:
            return None

    @proven
    def backup_fast(expected):
        info = memory.fence.check(backup)
        if expected is None:
            if info is not None:
                raise fence_plan.Stale()
        elif info is None or history_recovery._stamp(info) != expected[:-1]:
            raise fence_plan.Stale()
        ownership()

    owner_check()
    source_check()
    if not removed:
        # No rewrite (including no inode change); cleanup below still applies.
        source_check(durable=True)
    error = None
    try:
        if removed:
            old_backup = existing_backup()
            staged_backup, backup_identity = stage(backup,primary)
            def publish_backup():
                validate(((staged_backup,backup_identity),))
                backup_fast(old_backup)
                linked = known_links()
                fast(((staged_backup,backup_identity),)+(((backup,old_backup),) if old_backup is not None else ()))
                os.replace(str(staged_backup),str(backup))
                after_own_unlink(linked)
            files._retry(publish_backup,deadline)
            owned.pop(staged_backup)
            actual, backup_identity = history_recovery._read(memory,backup,deadline,ownership,durable=True)
            if actual != primary:
                raise fence_plan.Stale()
            staged, staged_identity = stage(path,retained)
            def publish_primary():
                validate(((staged,staged_identity),(backup,backup_identity)))
                phase['attempted'] = True
                os.replace(str(staged),str(path))
                phase['published'] = True
            files._retry(publish_primary,deadline)
            owned.pop(staged)
            actual, identity = history_recovery._read(memory,path,deadline,ownership,durable=True)
            if actual != retained:
                raise fence_plan.Stale()
            history_io._strict(actual)
            current[:] = actual, identity

        # A healthy, verified primary is mandatory even for old orphan temps.
        validate()
        names, directory = history_recovery._names(memory,root,deadline,ownership)
        now_ns = time.time_ns()
        for name in names:
            candidate = root/name
            is_backup = name == backup.name
            if not is_backup and not temporary_pattern.fullmatch(name):
                continue
            info = memory.fence.check(candidate)
            if info is None or not stat.S_ISREG(info.st_mode):
                continue
            linked_backup = is_backup and (info.st_dev,info.st_ino) == current[1][:2]
            if info.st_nlink != (2 if linked_backup else 1):
                continue
            if not is_backup and now_ns-info.st_mtime_ns <= cleanup.AGE_NS:
                continue
            _, identity = history_recovery._read(memory,candidate,deadline,ownership)
            @proven
            def remove_check():
                validate(((candidate,identity),))
                current_names, current_directory = history_recovery._names(memory,root,deadline,ownership)
                if current_directory != directory or candidate.name not in current_names:
                    raise fence_plan.Stale()
                check_info = memory.fence.check(candidate)
                if check_info is None or history_recovery._stamp(check_info) != identity[:-1]:
                    raise fence_plan.Stale()
                if not is_backup and time.time_ns()-check_info.st_mtime_ns <= cleanup.AGE_NS:
                    raise fence_plan.Stale()
                fast(((candidate,identity),))
            def remove():
                linked = is_backup and known_links()
                remove_check()
                candidate.unlink()
                phase['artifacts'] += 1
                after_own_unlink(linked)
            files._retry(remove,deadline)
        validate()
    except Exception as failure:
        error = failure
    finally:
        for temporary, guard in tuple(owned.items()):
            try:
                files._unlink(temporary,guard)
            except Exception as failure:
                if error is None:
                    error = failure
    if error is not None:
        raise RetentionFailed(phase['published'],phase['attempted'],removed,phase['artifacts']) from error
    return {'published':phase['published'],'removed':removed,'kept':len(kept),'future':future,
            'artifacts_removed':phase['artifacts'],'cleanup_pending':False}
