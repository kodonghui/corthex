"""Internal ordinary state publisher; actual curator/inverse policy is separate.

The original owner supplies a None-only complete validity/provenance precondition.
Our fact catalogue is a stability guard under leases/revisions, not independent
proof of historical privacy completeness or timestamp-preserving external writes.
"""
import contextlib
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path

from . import clock, fence_plan, files, history_io, history_recovery, item_types, locks
from . import revision_io, state_plan, state_types


@dataclass(frozen=True)
class StateContext:
    original_control: tuple
    original_sources: tuple
    planned_sources: tuple
    operations_sha256: str
    facts: tuple
    reservation: object = field(repr=False)
    published: tuple
    building: bool
    history_requirements: tuple


class PublicationFailed(RuntimeError):
    def __init__(self, attempted, published, progress, cleanup_pending):
        super().__init__('state publication incomplete; inspect known prefix')
        self.attempted, self.published = tuple(attempted), tuple(published)
        self.uncertain = tuple(key for key in attempted if key not in published)
        self.progress, self.cleanup_pending = progress, cleanup_pending


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _deadline(deadline):
    if deadline is not None and clock.now() >= deadline:
        raise locks.LockBusy()


def _control(value):
    proof = fence_plan.snapshot(value)
    fence = proof['fence']
    return proof['applies'], fence['epoch'], fence['generation'], tuple(sorted(fence['revisions'].items()))


def _read(memory, path, deadline, ownership, durable=False):
    return history_recovery._read(memory, path, deadline, ownership, durable)


def _fact(memory, path, deadline, ownership):
    """Read a layer fact as `_read` does, with the leases checked after the read.

    The read's own steps check the deadline, the path and the opened file's
    identity and stamps. The pass that reads the fact changes nothing, and the
    previous fact's check or the pass's first one comes before this read, so
    each read still lies between two checks of the leases, which no longer
    repeat around each step of the read. A read that fails checks the leases
    before its error goes on, so that what that check finds, such as a lease
    lost during the read, is what the pass reports.
    """
    try:
        result = _read(memory, path, deadline, lambda: _deadline(deadline))
    except Exception:
        ownership()
        raise
    ownership()
    return result


def _catalogue(memory, root, deadline, ownership):
    inventories, facts, private = [], [], set()
    for folder_name in ('items','tombstones'):
        folder = root/'layer'/folder_name
        names, identity = history_recovery._names(memory, folder, deadline, ownership)
        inventories.append((folder_name, identity, tuple(names)))
        for name in names:
            item = name[:-5] if name.endswith('.json') else ''
            if not item_types.ITEM.fullmatch(item):
                raise files.RestoreNeeded()
            data, stamp = _fact(memory, folder/name, deadline, ownership)
            try:
                if folder_name == 'items':
                    if item_types.parse_item(data)['id'] != item:
                        raise ValueError('item filename mismatch')
                else:
                    private.update(history_recovery._tombstone(data, item, root.name))
            except (ValueError,UnicodeError,TypeError):
                raise files.RestoreNeeded() from None
            facts.append((folder_name+'/'+name, stamp))
    names, identity = history_recovery._names(memory, root/'layer', deadline, ownership)
    if any(name == 'deleted.json' or name.startswith('deleted.json.') for name in names):
        raise fence_plan.Stale()
    inventories.append(('', identity, ()))
    return tuple(inventories), tuple(facts), frozenset(private)


def _facts_check(memory, root, deadline, ownership, catalogue, full=False):
    ownership()
    inventories, facts, _ = catalogue
    for folder_name, identity, expected in inventories:
        names, actual = history_recovery._names(memory, root/'layer'/folder_name, deadline, lambda: _deadline(deadline))
        if not folder_name:
            names = [name for name in names if name == 'deleted.json' or name.startswith('deleted.json.')]
        if actual != identity or tuple(names) != expected:
            raise fence_plan.Stale()
    for name, stamp in facts:
        path = root/'layer'/name
        _deadline(deadline)
        info = memory.fence.check(path)
        if info is None or history_recovery._stamp(info) != stamp[:-1]:
            raise fence_plan.Stale()
        if full and _fact(memory, path, deadline, ownership)[1] != stamp:
            raise fence_plan.Stale()
    ownership()


def _fact_binding(catalogue):
    inventories, facts, _ = catalogue
    return inventories, tuple((name, stamp[:-1]+(stamp[-1].hex(),)) for name,stamp in facts)


def apply(memory, root, expected, proposal, at, deadline, run_id, *, state_precondition):
    """Publish ordinary physical changes with all required histories first.

    The callback binds complete original policy/context, not just these facts.
    It raises on refusal and returns only None. Same-ID reintroduction remains
    a separate verified inverse operation; this API cannot manufacture it.
    """
    root = Path(root)
    if not callable(state_precondition):
        raise TypeError('complete original state precondition required')
    ownership = history_io._project_check(memory, root, revision_io.guard(memory, root, deadline, curator=True))
    proposal = item_types._document(item_types._raw(proposal))
    control_value = revision_io.read_primary(memory, root, deadline)
    if not fence_plan.matches(control_value, expected):
        raise fence_plan.Stale()
    expected = fence_plan.snapshot(control_value)
    control_stamp = [_read(memory, root/'curation.json', deadline, ownership)[1]]
    sources = {}
    for key, name in (('state','state.json'),('removed','state-removed.json')):
        path = root/'layer'/name
        try:
            data, stamp = _read(memory, path, deadline, ownership)
        except FileNotFoundError:
            raise files.RestoreNeeded() from None
        sources[key] = [path, data, stamp]
    try:
        before = state_types.parse_state(sources['state'][1])
        removed = state_types.parse_removed(sources['removed'][1])
    except (ValueError,UnicodeError):
        raise files.RestoreNeeded() from None
    plan = state_plan.plan(before, removed, proposal, at, memory.device)
    catalogue = _catalogue(memory, root, deadline, ownership)
    private = catalogue[2]
    changed_ids = {effect.line for effect in plan.effects}
    for line in before['lines']+proposal['state']['lines']:
        if line['id'] in changed_ids and private.intersection(line['cites']):
            raise fence_plan.Stale()
    original_control = _control(control_value)
    original_sources = tuple((key,_sha(sources[key][1])) for key in sorted(sources))
    planned_sources = (('state',None if plan.state is None else _sha(plan.state)),
                       ('removed',None if plan.removed is None else _sha(plan.removed)))
    operation_sha = _sha(item_types._raw(proposal['operations']))
    owned, attempts, published = {}, [], []
    phase = {'reservation':None, 'receipt':None, 'building':False, 'requirements':(), 'history_pin':None}

    def source_check(full=True):
        for path, data, stamp in sources.values():
            if full:
                ownership()
            _deadline(deadline)
            info = memory.fence.check(path)
            if info is None or history_recovery._stamp(info) != stamp[:-1]:
                raise fence_plan.Stale()
            if full and _read(memory, path, deadline, ownership) != (data,stamp):
                raise fence_plan.Stale()

    def family_check():
        names, _ = history_recovery._names(memory, root/'layer', deadline, lambda: _deadline(deadline))
        for path, _, _ in sources.values():
            actual = {name for name in names if name == path.name or name.startswith(path.name+'.')}
            allowed = {path.name}|{p.name for p in owned if p.name.startswith(path.name+'.')}
            if actual != allowed:
                raise files.RestoreNeeded()

    def owned_check(full=False):
        for path, (data,stamp) in tuple(owned.items()):
            if full:
                ownership()
            _deadline(deadline)
            info = memory.fence.check(path)
            if info is None or history_recovery._stamp(info) != stamp[:-1]:
                raise fence_plan.Stale()
            if full and _read(memory, path, deadline, ownership) != (data,stamp):
                raise fence_plan.Stale()

    def context_check(full=False):
        ownership()
        reservation = phase['reservation']
        if reservation is not None:
            if (type(reservation) is not revision_io.Reservation or not reservation.primary_only or
                    reservation._memory is not memory or reservation._root != root):
                raise ValueError('publisher requires its own strict reservation')
            fence = reservation.progress['fence']
            if (fence['epoch'] != original_control[1] or fence['generation'] != original_control[2]+1 or
                    any(fence['revisions'].get(key) != fence['generation'] for key in plan.targets+('run:'+run_id,))):
                raise fence_plan.Stale()
        if full:
            if reservation is None:
                if not fence_plan.matches(revision_io.read_primary(memory, root, deadline), expected):
                    raise fence_plan.Stale()
            else:
                reservation.check()
            source_check()
            _facts_check(memory, root, deadline, ownership, catalogue, True)
            if not phase['building']:
                family_check()
                owned_check(True)
        binding = StateContext(original_control, original_sources, planned_sources, operation_sha,
                               _fact_binding(catalogue), reservation, tuple(published),
                               phase['building'], phase['requirements'])
        if state_precondition(memory, root, binding) is not None:
            raise TypeError('state precondition must return only None')
        if phase['receipt'] is not None and not phase['receipt']._live:
            raise locks.LostLock()
        ownership()
        info = memory.fence.check(root/'curation.json')
        if info is None or history_recovery._stamp(info) != control_stamp[0][:-1]:
            raise fence_plan.Stale()
        source_check(False)
        _facts_check(memory, root, deadline, ownership, catalogue)
        if not phase['building']:
            family_check()
            owned_check()
        ownership()

    @contextlib.contextmanager
    def receipt_validation():
        receipt = phase['receipt']
        try:
            if receipt is not None and not receipt._live:
                raise locks.LostLock()
            yield receipt
            if receipt is not None and not receipt._live:
                raise locks.LostLock()
        except BaseException as failure:
            if receipt is not None:
                receipt._live = False
                phase.setdefault('proof_failure',failure)
            raise

    def effect_check(full=False):
        with receipt_validation() as receipt:
            context_check(full)
            if receipt is not None:
                # Byte completeness/durability is checked once, at the late
                # pin below; this retains the original receipt's binding.
                receipt._guard()

    def pin_history():
        with receipt_validation() as receipt:
            if receipt is None:
                return
            before = os.fstat(receipt._fd)
            data, stamp = _read(memory, root/'state-history.jsonl', deadline, ownership, durable=True)
            history_io._strict(data)
            after = os.fstat(receipt._fd)
            if (history_recovery._stamp(before) != history_recovery._stamp(after) or
                    (after.st_dev,after.st_ino) != stamp[:2] or len(data) < receipt._size or
                    hashlib.sha256(data[:receipt._size]).digest() != receipt._prefix):
                raise fence_plan.Stale()
            ownership()
            receipt._size, receipt._prefix = len(data), hashlib.sha256(data).digest()
            phase['history_pin'] = receipt, history_recovery._stamp(after), stamp

    def history_fast():
        with receipt_validation() as receipt:
            if receipt is None:
                return
            if phase['history_pin'] is None or phase['history_pin'][0] is not receipt:
                raise locks.LostLock()
            _, fd_stamp, path_stamp = phase['history_pin']
            current = memory.fence.check(root/'state-history.jsonl')
            if (current is None or history_recovery._stamp(current) != path_stamp[:-1] or
                    history_recovery._stamp(os.fstat(receipt._fd)) != fd_stamp):
                raise fence_plan.Stale()

    def joint_guard():
        # Full callbacks/receipt checks precede this final cheap handoff.
        ownership()
        source_check(False)
        owned_check()
        family_check()
        info = memory.fence.check(root/'curation.json')
        if info is None or history_recovery._stamp(info) != control_stamp[0][:-1]:
            raise fence_plan.Stale()
        _facts_check(memory, root, deadline, ownership, catalogue)
        history_fast()
        ownership()

    def stage(path, data):
        ready = []
        phase['building'] = True
        try:
            temporary = files._temporary(path, data, True, check=context_check, path_check=memory.fence.check, ready=ready.append)
            ready[0]()
            info = memory.fence.check(temporary)
            ready[0]()
            if info is None:
                raise locks.LostLock()
            owned[temporary] = (data,history_recovery._stamp(info)+(hashlib.sha256(data).digest(),))
        finally:
            phase['building'] = False
        actual, stamp = _read(memory, temporary, deadline, ownership, durable=True)
        if (actual,stamp) != owned[temporary]:
            raise fence_plan.Stale()
        context_check()
        return temporary

    def move(temporary, path, data, key=None):
        def attempt():
            effect_check(True)
            if _read(memory, temporary, deadline, ownership, durable=True) != owned[temporary]:
                raise fence_plan.Stale()
            source_check()
            pin_history()
            joint_guard()
            if key is not None and key not in attempts:
                attempts.append(key)
            os.replace(str(temporary), str(path))
            if key is not None:
                published.append(key)
        files._retry(attempt, deadline)
        owned.pop(temporary)
        actual, stamp = _read(memory, path, deadline, ownership)
        if actual != data:
            raise fence_plan.Stale()
        if key is None:
            owned[path] = (data,stamp)
        else:
            sources[key] = [path,data,stamp]

    def publish(key, data):
        path, before_data, _ = sources[key]
        backup = path.with_name(path.name+'.bak')
        move(stage(backup, before_data), backup, before_data)
        move(stage(path, data), path, data, key)
        def cleanup_guard():
            effect_check(True)
            source_check()
            owned_check(True)
            pin_history()
            joint_guard()
        files._unlink(backup, cleanup_guard)
        owned.pop(backup)
        context_check()

    context_check(True)
    if not plan.effects:
        return {'attempted':(), 'published':(), 'progress':None, 'lines':(), 'cleanup_pending':False}
    error = None
    try:
        reservation = revision_io.reserve(memory, root, expected, plan.targets, deadline, run_id, primary_only=True)
        phase['reservation'] = reservation
        control_stamp[0] = _read(memory, root/'curation.json', deadline, ownership)[1]
        context_check(True)
        values = plan.history(reservation.progress, run_id, at, memory.device)
        requirements = tuple((value['epoch'],value['generation'],value['run'],value['line'],
                              state_types.HistoryRecord(state_types.history_record_bytes(value)).sha256) for value in values)
        phase['requirements'] = requirements
        def archive_precondition(bound_memory, bound_root, bound_reservation, required):
            if (bound_memory is not memory or bound_root != root or bound_reservation is not reservation or
                    required != requirements):
                raise ValueError('state history binding mismatch')
            context_check()
        history = (history_io.append(memory, root, reservation, values, deadline,
                                     archive_precondition=archive_precondition) if values else contextlib.nullcontext(None))
        with history as receipt:
            phase['receipt'] = receipt
            effect_check(True)
            if plan.removed is not None:
                publish('removed', plan.removed)
            if plan.state is not None:
                publish('state', plan.state)
            effect_check(True)
            pin_history()
            joint_guard()
    except Exception as failure:
        error = failure
    finally:
        for path, (data,stamp) in tuple(owned.items()):
            if not path.name.endswith('.tmp'):
                continue
            def cleanup_owned(path=path, data=data, stamp=stamp):
                ownership()
                if _read(memory, path, deadline, ownership) != (data,stamp):
                    raise fence_plan.Stale()
                ownership()
            try:
                files._unlink(path, cleanup_owned)
                owned.pop(path)
            except Exception as cleanup:
                if error is None:
                    error = cleanup
    if error is not None:
        reservation = phase['reservation']
        raise PublicationFailed(attempts, published, None if reservation is None else reservation.progress, True) from phase.get('proof_failure',error)
    generation = reservation.progress['fence']['generation']
    hashes = {value[3]:value[4] for value in requirements}
    lines = tuple({'line':effect.line, 'op':effect.op, 'generation':generation,
                   'history':None if effect.line not in hashes else (reservation.progress['fence']['epoch'],generation,effect.line,hashes[effect.line]),
                   'before':effect.before_place, 'after':effect.after_place,
                   'before_revision':expected['fence']['revisions'].get('line:'+effect.line),
                   'after_revision':generation} for effect in plan.effects)
    return {'attempted':tuple(attempts), 'published':tuple(published), 'progress':reservation.progress,
            'lines':lines, 'cleanup_pending':False}
