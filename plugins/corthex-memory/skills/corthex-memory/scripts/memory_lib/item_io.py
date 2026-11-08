"""Internal C2 item writer; no provisioning, silent restoration or activation.

Each file is atomic, but a batch may publish only a prefix. WriteFailed retains
ID-only attempted/known-published effects; unconfirmed attempts are uncertain.
"""
import os
from pathlib import Path

from . import conflict_counts, conflict_plan, conflict_types, fence_plan, files, item_plan, item_types, revision_io


class WriteFailed(RuntimeError):
    def __init__(self, attempted, published, progress):
        super().__init__('item batch publication incomplete')
        self.attempted, self.published = tuple(attempted), tuple(published)
        self.uncertain = tuple(key for key in attempted if key not in published)
        self.progress = progress


def _present(memory, path):
    return memory.fence.check(path) is not None


def _private(memory, root, item=None):
    paths = [root / 'layer/deleted.json']
    if item is not None:
        paths.append(root / 'layer/tombstones' / (item + '.json'))
    return any(_present(memory, path) or _present(memory, path.with_name(path.name + '.bak')) for path in paths)


def _record(memory, path, parse, deadline, check):
    check()
    memory.fence.check(path.with_name(path.name + '.bak'))
    try:
        value = parse(files._retry(lambda: memory.fence.read(path, deadline), deadline))
    except files._RESTORABLE:
        raise files.RestoreNeeded() from None
    check()
    return value


def _items(memory, root, deadline, check):
    folder = root / 'layer/items'
    check()
    memory.fence.check(folder)
    paths = files._retry(lambda: list(folder.iterdir()), deadline)
    values = []
    for path in sorted(paths):
        check()
        if path.name.endswith('.json.bak') and item_types.ITEM.fullmatch(path.name[:-9]):
            item = path.name[:-9]
            if not _private(memory, root, item) and not _present(memory, folder / (item + '.json')):
                raise files.RestoreNeeded()
        if not path.name.endswith('.json'):
            continue
        item = path.name[:-5]
        if not item_types.ITEM.fullmatch(item):
            raise files.RestoreNeeded()
        if _private(memory, root, item):
            continue
        value = _record(memory, path, item_types.parse_item, deadline, check)
        if value['id'] != item:
            raise files.RestoreNeeded()
        values.append(value)
    check()
    return values


def _checked(memory, root, expected, deadline, curator=False):
    guard = revision_io.guard(memory, root, deadline, curator=curator)

    def check():
        guard()
        if _private(memory, root) or not fence_plan.matches(revision_io.read(memory, root, deadline), expected):
            raise fence_plan.Stale()
        guard()

    check()
    return check, guard


def _publish(path, data, durable, check, path_check, published):
    ready = []
    temporary = files._temporary(path, data, durable, check=check, path_check=path_check, ready=ready.append)
    backup = path.with_name(path.name + '.bak')

    def move():
        files._access(check, path_check, path, backup)
        ready[0]()
        os.replace(str(temporary), str(path))
        published()

    try:
        files._access(check, path_check, path, backup)
        if durable and path.exists():
            files._backup(path, backup, check=check, path_check=path_check)
        files._retry(move)
        if durable:
            files._unlink(backup, lambda: files._access(check, path_check, backup))
    finally:
        files._unlink(temporary, ready[0])


def _conflicts(memory, root, conflicts, items, plan, deadline, check):
    """Bytes for TBL-120 and the candidates they add and close, checked against the batch (TASK-086)."""
    before = _record(memory, root / 'layer/conflicts.json', conflict_types.parse_conflicts, deadline, check)
    final = {value['id']: value['status'] for value in items}
    final.update((item, item_types.parse_item(data)['status']) for item, data in plan['records'])
    data, added, closed = conflict_plan.changes(before, conflicts, {i for i, s in final.items() if s == 'current'})
    return before, (data if added or closed else None), added, closed


def _effects(items, pins, plan, candidates, added, closed):
    """The batch's actual changes as its run log names them (TBL-121): IDs, statuses and pin records, no text."""
    before = {value['id']: value for value in items}

    def status(value):
        return item_types._ordered(value, ('status', 'superseded_by', 'undone_by'))
    saved, statuses = [], []
    for item, data in plan['records']:
        if item in before:
            statuses.append({'item': item, 'before': status(before[item]), 'after': status(item_types.parse_item(data))})
        else:
            saved.append(item)
    moves = []
    if plan['pins'] is not None:
        old = {pin['item']: (index, pin) for index, pin in enumerate(pins['pins'])}
        for index, pin in enumerate(item_types.parse_pins(plan['pins'])['pins']):
            place, prior = old.get(pin['item'], (None, None))
            if prior != pin:
                moves.append({'item': pin['item'], 'from': None if prior is None else
                              item_types._ordered(prior, ('on', 'at', 'device')),
                              'to': item_types._ordered(pin, ('on', 'at', 'device')), 'place': [place, index]})
    after = {} if candidates is None else {
        value['id']: value['status'] for value in conflict_types.parse_conflicts(candidates)['candidates']}
    conflicts = [{'candidate': candidate, 'from': 'absent', 'to': 'open'} for candidate in added]
    conflicts += [{'candidate': candidate, 'from': 'open', 'to': after[candidate]} for candidate in closed]
    return {'saved': saved, 'statuses': statuses, 'pins': moves, 'conflicts': conflicts}


def apply(memory, root, expected, additions, transitions, at, deadline, run_id=None, conflicts=None):
    """Publish item changes and, when `conflicts` is given, the TBL-120 value that goes with them.

    New candidates are counted zero durably (TBL-010) before the reservation,
    and conflicts.json is published after the items that its candidates name.
    A batch without item changes publishes conflicts.json alone, as a merge
    answer that only names disagreements does (TASK-089); a batch that changes
    nothing is refused. Returns the published keys, the reservation's progress
    and the batch's `effects` for its run log (TASK-103), with each object's
    revisions.
    """
    root = Path(root)
    check, ownership = _checked(memory, root, expected, deadline, curator=run_id is not None)
    items = _items(memory, root, deadline, check)
    pins = _record(memory, root / 'layer/pins.json', item_types.parse_pins, deadline, check)
    if additions or transitions or conflicts is None:
        plan = item_plan.plan(items, pins, additions, transitions, at, memory.device)
    else:
        plan = {'records': [], 'pins': None, 'list': None, 'notices': [], 'targets': [], 'pinned': []}
    candidates, added, closed = None, [], []
    if conflicts is not None:
        before, candidates, added, closed = _conflicts(memory, root, conflicts, items, plan, deadline, check)
    targets = sorted(set(plan['targets']) | {'candidate:' + candidate for candidate in added + closed})
    if not targets:
        raise ValueError('item change required')
    effects = _effects(items, pins, plan, candidates, added, closed)
    item_ids = [item for item, data in plan['records']] + plan['pinned']

    def privacy():
        if any(_private(memory, root, item) for item in item_ids):
            raise fence_plan.Stale()

    check()
    privacy()
    if added:
        conflict_counts.initialize(memory, root, added, before, deadline)
        check()
    reservation = revision_io.reserve(memory, root, expected, targets, deadline, run_id)

    def guard():
        ownership()
        reservation.check()
        privacy()
        ownership()
        reservation.check()

    writes = [(root / 'layer/items' / (item + '.json'), data, True, 'item:' + item) for item, data in plan['records']]
    if plan['pins'] is not None:
        writes.append((root / 'layer/pins.json', plan['pins'], True, 'pins'))
    if candidates is not None:
        # Candidates follow the items they name (SPEC-016).
        writes.append((root / 'layer/conflicts.json', candidates, True, 'conflicts'))
    if plan['list'] is not None:
        writes.append((root / 'layer/item-list.txt', plan['list'], False, 'item-list'))
    writes.extend((root / 'notices' / ('pin-' + item + '.json'), data, False, 'notice:pin-' + item)
                  for item, data in plan['notices'])
    attempted, published = [], []
    try:
        for path, data, durable, key in writes:
            guard()
            attempted.append(key)
            _publish(path, data, durable, guard, memory.fence.check, lambda: published.append(key))
        guard()
    except Exception as error:
        raise WriteFailed(attempted, published, reservation.progress) from error
    generation, revisions = reservation.progress['fence']['generation'], expected['fence']['revisions']
    effects['revisions'] = [{'id': key, 'before': revisions.get(key), 'after': generation} for key in targets]
    return {'published': tuple(published), 'progress': reservation.progress, 'effects': effects}


def rebuild_list(memory, root, expected, deadline):
    root = Path(root)
    check, _ = _checked(memory, root, expected, deadline)
    data = item_types.item_list_bytes(_items(memory, root, deadline, check))
    _publish(root / 'layer/item-list.txt', data, False, check, memory.fence.check, lambda: None)
    check()
