"""Internal format-2 binding, for already migrated/quiescent stores only.

From release 0.3.0 the command runner binds a format-2 store with CommandStore
(TASK-117); below it nothing does. TASK-074 owns maintenance, header sidecar
fences, and real migrations; constructing this object neither migrates nor
enables C2.
"""
from . import configuration, files, format2, locks, store, worker_support


def parse_header(data):
    """A format-2 store record, as the format-1 gate's store._record parses format 1.

    Another format or a migration is a policy refusal, which never restores a
    backup: `store-migrating`, `store-newer` after format 2, `store-damaged` before it.
    """
    envelope = store.json_document(data)
    if not isinstance(envelope, dict):
        raise ValueError('invalid store record')
    # A policy refusal must never become a restorable typed error.
    if 'migrating' in envelope:
        raise store.StoreUnavailable('store-migrating')
    version = envelope.get('format')
    if not configuration.integer(version) or version < 1:
        raise ValueError('invalid store record')
    if version != 2:
        raise store.StoreUnavailable('store-newer' if version > 2 else 'store-damaged')
    return format2.parse_store(data)


class C2Store(worker_support.WorkerStore):
    def record(self, report=None, *, deadline, holding_lock=None, recording=False):
        self._deadline(deadline)

        def parse(data):
            value = parse_header(data)
            if ((self.expected is not None and value['device'] != self.expected) or
                    holding_lock is not None and value['device'] != holding_lock.device):
                raise locks.LostLock()
            self.check(deadline)
            return value

        path = self.folder / 'store.json'
        try:
            # A valid primary must not hide a format-1 automatic fallback.
            # Unpublished header temps/quiescence are TASK-074's precondition.
            try:
                parse(self.fence.read(path.with_name(path.name + '.bak'), deadline))
            except FileNotFoundError:
                pass
            return self._read_record(path, parse, deadline, report,
                                     holding_lock=holding_lock, recording=recording)
        except (FileNotFoundError, ValueError, UnicodeError, files.RestoreNeeded):
            raise store.StoreUnavailable('store-damaged') from None


class CommandStore(C2Store):
    """The command runner's format-2 binding from release 0.3.0 (TASK-117).

    Unlike C2Store, it reads nothing when it is made: the runner's gates read the
    store record and the configuration as they do for format 1, through the same
    path fence, and bind() then pins the store record that the handlers' checks
    compare with, as C2Store pins the one that it read.
    """

    def __init__(self, fence):
        store.MemoryStore.__init__(self, fence.root)
        self.fence, self.folder = fence, fence.root
        self.expected, self.pin, self.held, self.notes = None, None, [], []
        self.logger = worker_support.BoundDiagnostics(self)
        self.device = self.config = None

    def bind(self, record, settings, deadline):
        """Pin the store record that the gates read; another one since is a lost lease."""
        self.expected = record['device']
        header = self.logger.read_gate(deadline, self.note)
        if header['device'] != record['device']:
            raise locks.LostLock()
        self.device, self.pin = header['device'], self.logger._ready[1]
        self.config = settings
        self.check(deadline)
        self.flush()
