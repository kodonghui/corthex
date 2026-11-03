"""Repair only an irrecoverable TBL-001; never provision or reset consent."""
import hashlib
import json
import os
from pathlib import Path

from . import base, clock, commands, diagnostics, files, locks, store
from .worker_support import BoundDiagnostics, PathFence

SAY = "The store record is missing or damaged and no readable backup can be restored. Confirm a new store record with a new device ID; all other memory, configuration and consent stay unchanged."


class Repair:
    def __init__(self, context):
        self.context, self.memory = context, context.memory
        self.fence = getattr(self.memory, "fence", None) or PathFence(self.memory.folder)
        self.root, self.lease, self.pins = self.fence.root, None, {}
        self.notes = []

    def root_check(self):
        self.fence.check(self.root)
        if self.lease is not None:
            self.lease.check()

    def stamp(self, path):
        self.root_check()
        value = diagnostics.Diagnostics._stamp(path, clock.now() + 1, check=self.fence.check)
        self.root_check()
        return value

    def read(self, path):
        before = self.stamp(path)
        if before is None:
            return None, None
        data = self.fence.read(path, clock.now() + 10)
        after = self.stamp(path)
        if before != after or after[-1] != hashlib.sha256(data).digest():
            raise locks.LostLock()
        return data, after

    def classify(self):
        """Pure last classification, including foreign-device recovery candidates."""
        self.pins, original = {}, None
        for name in ("store.json", "store.json.bak"):
            data, pin = self.read(self.root / name)
            self.pins[name] = pin
            if name == "store.json":
                original = data
            try:
                record = store._record(data) if data is not None else None
            except (ValueError, UnicodeError):
                record = None
            if record is not None:
                return ("current" if name == "store.json" else "recover"), record, original
        return "broken", None, original

    def guard(self):
        self.root_check()
        for name, pin in self.pins.items():
            if self.stamp(self.root / name) != pin:
                raise locks.LostLock()
        self.root_check()

    def commit(self, path, payload):
        ready = []
        temporary = files._temporary(path, payload, True, check=self.guard,
                                     path_check=self.fence.check, ready=ready.append)
        temporary_pin = self.stamp(temporary)
        try:
            def move():
                ready[0]()
                self.guard()
                os.replace(str(temporary), str(path))
                # Only this successful replace authorizes the new expectation.
                self.pins[path.name] = temporary_pin
                self.guard()
            files._retry(move)
        finally:
            files._unlink(temporary, ready[0])

    def write(self, candidate, original):
        self.guard()
        if original is not None:
            self.commit(self.root / "store.json.bak", original)
        self.commit(self.root / "store.json", base.json_bytes(candidate, "TBL-001"))
        backup = self.root / "store.json.bak"
        if self.pins[backup.name] is not None:
            def remove():
                self.guard()
                backup.unlink()
                self.pins[backup.name] = None
                self.guard()
            files._retry(remove)
        self.guard()
        data, pin = self.read(self.root / "store.json")
        if pin != self.pins["store.json"] or store._record(data) != candidate:
            raise locks.LostLock()
        self.context.record = candidate
        return commands.result("repair", dict(device=candidate["device"]),
                               "The store record was repaired with a new device ID. All other memory, configuration and consent were preserved.")

    def nothing(self, record):
        self.context.record = record
        return commands.result("repair", dict(device=record["device"]),
                               "The store record can be read and needs no repair. No new device ID was made.", "nothing")

    def recover(self):
        # No candidate-device lease remains when ordinary recovery reads the
        # foreign-device backup. Preserve its gate, wait and notice behavior.
        answer = commands._gates(self.context)
        if answer is not None:
            return answer
        if self.context.record is None:
            raise locks.LostLock()
        state, record, _ = self.classify()
        if state != "current":
            raise locks.LostLock()
        return self.nothing(record)

    def flush(self):
        if not self.notes or self.context.record is None:
            return
        try:
            self.guard()
            logger = BoundDiagnostics(commands._DiagnosticStore(self.memory, self.context.record["device"]))
            for error, count in self.notes:
                self.guard()
                logger.failure(error, "skill", clock.now() + 10, count=count)
        except Exception:
            pass  # Release notices never replace a completed result or adopt a new root.

    def apply(self):
        version = json.loads((Path(__file__).resolve().parents[4] / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
        candidate = store.new_record(version)
        with self.context.lock(self.root / "store.lock", "store", device=candidate["device"],
                               report=lambda error, count: self.notes.append((error, count))) as lease:
            self.lease = lease
            try:
                state, record, original = self.classify()
                if state == "current":
                    return self.nothing(record)
                if state == "broken":
                    return self.context.confirm({}, SAY, lambda: self.write(candidate, original))
            finally:
                self.lease = None
        return self.recover()


def repair(context):
    if not context.memory.folder.exists():
        return commands.result("repair", {}, "There is no memory folder to repair. Use on for a project to create one.", "nothing")
    operation = Repair(context)
    try:
        state, record, _ = operation.classify()
        if state == "current":
            return operation.nothing(record)
        if state == "recover":
            return operation.recover()
        return context.confirm({}, SAY, operation.apply)
    except store.StoreUnavailable as error:
        return commands.common_result("repair", error.code)
    finally:
        operation.flush()
