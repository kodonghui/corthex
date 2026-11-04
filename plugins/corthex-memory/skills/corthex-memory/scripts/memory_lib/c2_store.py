"""Internal format-2 binding, for already migrated/quiescent stores only.

No hook/CLI uses this binding. TASK-074 owns maintenance, header sidecar fences,
and real migrations; constructing this object neither migrates nor enables C2.
"""
from . import configuration, files, format2, locks, store, worker_support


class C2Store(worker_support.WorkerStore):
    def record(self, report=None, *, deadline, holding_lock=None, recording=False):
        self._deadline(deadline)

        def parse(data):
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
            value = format2.parse_store(data)
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
