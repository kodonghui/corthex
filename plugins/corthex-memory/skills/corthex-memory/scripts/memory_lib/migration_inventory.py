"""Read-only TASK-074 observations, never quiescence or maintenance authority.

No WorkerStore construction, provisioning, recovery, diagnostics or leases.
The actual owner must reacquire a fresh inventory under its original ordered
leases and verified old-writer quiescence before any migration effect.
"""
from dataclasses import dataclass, field
from pathlib import Path
import re
import stat

from . import base, clock, curation, format2, history_recovery
from . import locks, migration_plan, store, worker_support

_TEMP = r'\.[a-z0-9_]{8}\.tmp'
_COPY = re.compile(r'(?:\.bak)?(?:' + _TEMP + r')?\Z')
_LOCK = re.compile(r'\.lock(?:\.[0-9a-f]{32}\.stale)?\Z')
_LOG = r'(?:claude-code|codex)-[0-9a-f]{16}'
_RAW = re.compile(r'(' + _LOG + r')(?:\.jsonl((?:\.bak)?(?:' + _TEMP +
                  r')?)|\.lock(?:\.[0-9a-f]{32}\.stale)?)\Z')
_DIRS = {'raw', 'unprocessed', 'notices', 'injections', 'layer', 'runs'}


class InvalidInventory(ValueError):
    def __init__(self):
        super().__init__('migration inventory unavailable')


def _stamp(info):
    return history_recovery._stamp(info) + (info.st_mode, info.st_nlink)


def _project(name):
    original = name[:-1] if name.endswith('_') and name[:-1] in base.RESERVED else name
    if base.project_folder_name(original) != name:
        raise InvalidInventory()
    return original


def _copies(names, primary):
    candidates = tuple(n for n in names if n.startswith(primary))
    if any(not _COPY.fullmatch(n[len(primary):]) for n in candidates):
        raise InvalidInventory()
    return candidates


@dataclass(frozen=True)
class Project:
    name: str
    folder: str
    exists: bool
    progress: tuple = field(repr=False)
    raw_logs: tuple


@dataclass(frozen=True)
class Inventory:
    folder: Path = field(repr=False)
    projects: tuple
    headers: migration_plan.HeaderPlan = field(repr=False)
    configuration: tuple = field(repr=False)
    leases: tuple
    payloads: tuple
    _observer: object = field(repr=False, compare=False)

    def check(self):
        """Recheck original identities/bytes/names before the original deadline.

        This does not acquire ownership. No rebase or deadline extension exists.
        """
        self._observer.verify()


class _Observer:
    def __init__(self, folder, deadline):
        store.MemoryStore._deadline(deadline)
        path = Path(folder)
        if (not path.is_absolute() or path.is_symlink() or
                getattr(path.lstat(), 'st_file_attributes', 0) & 0x400):
            raise InvalidInventory()
        self.fence = worker_support.PathFence(path)
        self.root, self.deadline = self.fence.root, deadline
        self.dirs, self.files, self.records, self.revoked = {}, {}, {}, False
        self.guard()
        if not stat.S_ISDIR(self.fence.check(self.root).st_mode):
            raise InvalidInventory()

    def guard(self):
        if self.revoked:
            raise locks.LostLock()
        if clock.now() >= self.deadline:
            self.revoked = True
            raise locks.LockBusy()
        try:
            self.fence.check(self.root)
            for name, (identity, _) in self.dirs.items():
                info = self.fence.check(self.root / name)
                if info is None or not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != identity:
                    raise locks.LostLock()
        except Exception:
            self.revoked = True
            raise locks.LostLock() from None

    def directory(self, name):
        self.guard()
        path = self.root / name
        names, identity = history_recovery._names(self, path, self.deadline, self.guard)
        self.dirs[name] = identity, tuple(names)
        self.guard()
        return names

    def file(self, name, read=False, working=False):
        self.guard()
        path = self.root / name
        info = self.fence.check(path)
        if info is None or not stat.S_ISREG(info.st_mode):
            raise InvalidInventory()
        if working:
            return None
        pin = _stamp(info)
        if read:
            data, _ = history_recovery._read(self, path, self.deadline, self.guard)
            self.records[name] = data
        else:
            data = None
        current = self.fence.check(path)
        if current is None or _stamp(current) != pin:
            raise locks.LostLock()
        self.files[name] = pin
        return data

    def aliases(self):
        groups = {}
        for name, pin in self.files.items():
            groups.setdefault(pin[:2], []).append(name)
        for names in groups.values():
            expected = len(names)
            if (any(self.files[n][-1] != expected for n in names) or
                    expected > 1 and (expected != 2 or set(names) != {min(names), min(names) + '.bak'})):
                raise InvalidInventory()

    def verify(self):
        try:
            self.guard()
            for name, (identity, names) in self.dirs.items():
                current, opened = history_recovery._names(self, self.root / name, self.deadline, self.guard)
                if tuple(current) != names or opened != identity:
                    raise locks.LostLock()
            for name, pin in self.files.items():
                self.guard()
                info = self.fence.check(self.root / name)
                if info is None or _stamp(info) != pin:
                    raise locks.LostLock()
                if name in self.records:
                    raw, _ = history_recovery._read(self, self.root / name, self.deadline, self.guard)
                    if raw != self.records[name]:
                        raise locks.LostLock()
            self.guard()
        except Exception as error:
            self.revoked = True
            if isinstance(error, (locks.LostLock, locks.LockBusy)):
                raise
            raise locks.LostLock() from None


def _walk(observer, folder, kind, payloads, raw_logs):
    for name in observer.directory(folder):
        path = folder + '/' + name
        info = observer.fence.check(observer.root / path)
        observer.guard()
        if info is not None and stat.S_ISDIR(info.st_mode):
            if kind != 'layer' or name not in {'items', 'tombstones'}:
                raise InvalidInventory()
            _walk(observer, path, 'payload', payloads, raw_logs)
            continue
        working = bool(_LOCK.search(name))
        if kind == 'raw':
            match = _RAW.fullmatch(name)
            if match is None:
                raise InvalidInventory()
            raw_logs.add(match[1])
        observer.file(path, working=working)
        if not working:
            payloads.append(path)


def _collect(observer, release, when):
    names = observer.directory('.')
    headers = {n: observer.file(n, read=True) for n in _copies(names, 'store.json')}
    proposal = migration_plan.header_fence(headers, release=release, when=when)
    configured, configuration = set(), []
    for name in _copies(names, 'configuration.json'):
        raw = observer.file(name, read=True)
        configured.update(store._configuration(raw).get('projects', {}))
        configuration.append((name, raw))
    actual = set()
    if 'projects' in names:
        actual.update(_project(n) for n in observer.directory('projects'))
    projects, payloads = [], []
    migrating = any('migrating' in store.json_document(raw) for _, raw in proposal.originals)
    for name in sorted(actual | configured):
        folder = 'projects/' + base.project_folder_name(name)
        progress, raw_logs = [], set()
        if name in actual:
            children = observer.directory(folder)
            copies = _copies(children, 'curation.json')
            for child in copies:
                raw = observer.file(folder + '/' + child, read=True)
                value = store.json_document(raw)
                parsed = (format2.parse_curation(raw) if migrating and isinstance(value, dict) and 'fence' in value
                          else curation.parse(raw))
                raw_logs.update(parsed['logs'])
                progress.append((child, raw))
            for child in children:
                if child in copies:
                    continue
                path = folder + '/' + child
                info = observer.fence.check(observer.root / path)
                observer.guard()
                if info is not None and stat.S_ISDIR(info.st_mode):
                    if child not in _DIRS:
                        raise InvalidInventory()
                    _walk(observer, path, child, payloads, raw_logs)
                else:
                    working = bool(_LOCK.search(child))
                    observer.file(path, working=working)
                    if not working:
                        payloads.append(path)
        projects.append(Project(name, folder, name in actual, tuple(progress), tuple(sorted(raw_logs))))
    leases = [('store', 'store.lock')]
    for kind, suffix in (('curation', 'curation.lock'), ('layer', 'layer.lock')):
        leases.extend((kind, path) for path in sorted(p.folder + '/' + suffix for p in projects))
    leases.extend(('raw', path) for path in sorted(p.folder + '/raw/' + log + '.lock'
                  for p in projects for log in p.raw_logs))
    observer.aliases()
    observer.verify()
    return Inventory(observer.root, tuple(projects), proposal, tuple(configuration), tuple(leases),
                     tuple(sorted(payloads)), observer)


def observe(folder, *, release, when, deadline):
    """Observe only; unknown/missing/damaged inputs never trigger restoration.

    Configured missing folders remain absent. Existing unregistered projects
    are included. Payload bytes are never opened and the lease list is a scope
    proposal, not proof that its directories exist or anyone owns those leases.
    """
    observer = None
    try:
        observer = _Observer(folder, deadline)
        return _collect(observer, release, when)
    except Exception as error:
        if observer is not None:
            observer.revoked = True
        if isinstance(error, (locks.LostLock, locks.LockBusy)):
            raise
        raise InvalidInventory() from None
