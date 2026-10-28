"""Format-1 store gate and configuration I/O. No directory is created here."""

import json
import math
import re
from pathlib import Path

from . import base, configuration, files, locks, reading
from . import clock

TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z\Z")
DEVICE = re.compile(r"d_[0-9a-hjkmnp-tv-z]{12}\Z")


class StoreUnavailable(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("non-finite JSON number")


def json_document(data):
    return json.loads(data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)


def _record(data):
    value = json_document(data)
    if not isinstance(value, dict) or not configuration.integer(value.get("format")) or value["format"] < 1:
        raise ValueError("invalid store record")
    # Future formats and migrations are opaque: never validate or read past them.
    if value["format"] != 1 or "migrating" in value:
        raise StoreUnavailable("store-newer")
    if set(value) != {"format", "device", "made", "release"}:
        raise ValueError("invalid store record")
    if not isinstance(value["device"], str) or not DEVICE.fullmatch(value["device"]):
        raise ValueError("invalid store record")
    if not isinstance(value["made"], str) or not TIME.fullmatch(value["made"]):
        raise ValueError("invalid store record")
    if not isinstance(value["release"], str) or not value["release"]:
        raise ValueError("invalid store record")
    value["format"] = 1
    return value


def new_record(release):
    """Pure record factory for the later on/repair/migration writers."""
    value = {"format": 1, "device": base.new_id("d"), "made": base.utc_time(), "release": release}
    return _record(base.json_bytes(value, "TBL-001"))


def _configuration(data):
    value = json_document(data)
    configuration.validate(value)
    return value


class MemoryStore:
    def __init__(self, folder=None):
        self.folder = Path(folder) if folder is not None else base.memory_home()

    @staticmethod
    def _deadline(deadline):
        if not configuration.number(deadline) or not math.isfinite(deadline):
            raise ValueError("a finite read deadline is required")

    @staticmethod
    def _guard(lock, deadline, recording=False):
        def check():
            if not recording and clock.now() >= deadline:
                raise locks.LockBusy()
            lock.check()
        return check

    def _read_record(self, path, parse, deadline, report, device=None, holding_lock=None,
                     recording=False):
        operation_deadline = None if recording else deadline
        if holding_lock is not None:
            check = self._guard(holding_lock, deadline, recording)
            check()
            return files.read_record(path, parse, report, holding_lock=True, check=check,
                                     deadline=operation_deadline)
        if device is not None:
            lock = locks.Lock(self.folder / "store.lock", "store", device)
            def gate():
                self.record(report, deadline=deadline, holding_lock=lock)
            return reading.read_record(path, parse, lock, deadline, report, check=gate)
        try:
            return files.read_record(path, parse, report, deadline=operation_deadline)
        except files.RestoreNeeded:
            # A damaged store has no usable primary device ID. Validate the
            # readable backup before creating a lock, keeping opaque headers
            # completely read-only. Never manufacture another device identity.
            backup = path.with_name(path.name + ".bak")
            try:
                header = files.read_record(backup, _record, deadline=operation_deadline)
            except FileNotFoundError:
                # Another reader may already have restored the same backup.
                return files.read_record(path, parse, report, deadline=operation_deadline)
            lock = locks.Lock(self.folder / "store.lock", "store", header["device"])
            def gate():
                self.record(report, deadline=deadline, holding_lock=lock, recording=recording)
            return reading.read_record(path, parse, lock, deadline, report, check=gate,
                                       finish_recovery=recording)

    def record(self, report=None, *, deadline, holding_lock=None, recording=False):
        """Read the gate; recovery borrows the caller's operation deadline.

        Malformed/missing records without recovery are store-damaged. Ordinary
        I/O errors propagate for the command's internal result; a recovery
        lease that is busy keeps lock-busy. No blocked state writes a log.
        recording=True limits only recovery-lock waiting; acquired recovery
        finishes and makes its first attempt even when that wait has expired.
        """
        self._deadline(deadline)
        if not self.folder.exists():
            raise StoreUnavailable("no-store")
        def parse(data):
            value = _record(data)
            if holding_lock is not None and value["device"] != holding_lock.device:
                # Policy refusal must precede restoration, including a backup.
                raise locks.LostLock()
            return value
        try:
            return self._read_record(self.folder / "store.json", parse, deadline,
                                     report, holding_lock=holding_lock, recording=recording)
        except (FileNotFoundError, ValueError, UnicodeError, files.RestoreNeeded):
            raise StoreUnavailable("store-damaged") from None

    def configuration(self, report=None, *, deadline, holding_lock=None):
        header = self.record(report, deadline=deadline, holding_lock=holding_lock)
        try:
            document = self._read_record(self.folder / "configuration.json", _configuration,
                                         deadline, report, device=header["device"],
                                         holding_lock=holding_lock)
        except FileNotFoundError:
            document = {}
        except (ValueError, UnicodeError, files.RestoreNeeded):
            raise configuration.ConfigurationInvalid("$") from None
        # Schema-invalid JSON is deliberately not rolled back to a backup.
        return configuration.prepare(document)

    def write_configuration(self, document, deadline):
        before = self.record(deadline=deadline)
        checked = configuration.prepare(document)
        lock = locks.Lock(self.folder / "store.lock", "store", before["device"])
        def report_release(error, count):
            from .diagnostics import Diagnostics
            Diagnostics(self).failure(error, "skill", deadline)
        with lock.held(deadline, report=report_release):
            def guard():
                self._guard(lock, deadline)()
                if self.record(deadline=deadline, holding_lock=lock)["device"] != before["device"]:
                    raise locks.LostLock()
            guard()
            files.write_json(self.folder / "configuration.json", checked.document, "TBL-002", check=guard)
        return checked
