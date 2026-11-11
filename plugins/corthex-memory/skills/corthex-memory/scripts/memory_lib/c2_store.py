"""Internal format-2 binding, for already migrated/quiescent stores only.

From release 0.3.0 the command runner binds a format-2 store with CommandStore
(TASK-117); below it nothing does. TASK-074 owns maintenance, header sidecar
fences, and real migrations; constructing this object neither migrates nor
enables C2.

From release 0.3.0 the hooks bind a format-2 store with HookStore (TASK-117
step 2), which reads the store record, the configuration and the hooks' own log
files as C1's hooks read them: past the whole-hook deadline too, which bounds
only the waits for locks and the retries, so that a hook that starts late still
records (stage 06, Deadlines).
"""
import math

from . import activation, configuration, files, format2, locks, store, worker_support

# What a readable backup beside a format-2 store record refuses, by its kind.
BACKUP_REFUSALS = {activation.FORMAT_1: 'store-damaged', activation.MIGRATING: 'store-migrating',
                   activation.NEWER: 'store-newer'}


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
    # Whether the store record is read, and checked, past the deadline, as C1's hooks read it (HookStore).
    LATE = False

    def _pinned(self, leases=()):
        """`check` without its deadline: the leases, and the store record that the gate pinned."""
        for lease in leases:
            lease.check()
        if self.pin is not None and self.logger._stamp(self.folder / 'store.json') != self.pin:
            raise locks.LostLock()
        for lease in leases:
            lease.check()

    def record(self, report=None, *, deadline, holding_lock=None, recording=False):
        self._deadline(deadline)
        reads = math.inf if self.LATE else deadline

        def parse(data):
            value = parse_header(data)
            if ((self.expected is not None and value['device'] != self.expected) or
                    holding_lock is not None and value['device'] != holding_lock.device):
                raise locks.LostLock()
            if self.LATE:
                self._pinned()
            else:
                self.check(deadline)
            return value

        path = self.folder / 'store.json'
        try:
            # A valid primary must not hide a backup of another format or a migration, which the runner's kind
            # finds damaged, migrating or newer (TASK-117). A backup that cannot be read, or of another device,
            # hides nothing that restoring it could bring back here, so the record decides, as for format 1.
            # Unpublished header temps/quiescence are TASK-074's precondition.
            try:
                backup = activation.record_kind(self.fence.read(path.with_name(path.name + '.bak'), reads))
            except FileNotFoundError:
                backup = None
            if backup in BACKUP_REFUSALS:
                raise store.StoreUnavailable(BACKUP_REFUSALS[backup])
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


class HookDiagnostics(worker_support.BoundDiagnostics):
    """The hooks' failure and timing lines on a format-2 store: read past the deadline, as C1's hooks read them."""

    def _reader(self, path, deadline):
        return self.store.fence.read(path, math.inf)


class HookStore(CommandStore):
    """The hooks' format-2 binding from release 0.3.0 (TASK-117 step 2).

    It reads the store record and the configuration through the path fence,
    past the whole-hook deadline as C1's hooks do (`files.read_record` makes one
    attempt): the deadline bounds only the wait for a lock, which recording
    attempts once even when its 50 ms window has passed, and a recovery of a
    record outside recording. The C2 steps keep their own deadlines, through
    `check` and the fence's reads, so a late hook records and only recall, the
    triggers and the summary are cut. Its gate pins the store record as
    CommandStore's does.
    """
    LATE = True
    FENCED_RAW = True   # raw_log.RawLog takes the raw lock and checks the log's paths through the fence

    def __init__(self, fence):
        super().__init__(fence)
        self.logger = HookDiagnostics(self)

    def _read_record(self, path, parse, deadline, report, **options):
        return store.MemoryStore._read_record(self, path, parse, deadline, report,
                                             reader=lambda p: self.fence.read(p, math.inf), **options)

    def _guard(self, lock, deadline, recording=False):
        if recording:
            return lambda: self._pinned((lock,))
        return super()._guard(lock, deadline, recording)
