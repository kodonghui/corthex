"""Format-1 store gate and configuration I/O. No directory is created here."""

import json
import re
from pathlib import Path

from . import base, configuration, files, locks

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

    def record(self, report=None):
        try:
            if not self.folder.exists():
                raise StoreUnavailable("no-store")
            return files._read(self.folder / "store.json", _record, report)
        except (OSError, ValueError):
            raise StoreUnavailable("store-damaged") from None

    def configuration(self, report=None):
        self.record(report)
        try:
            document = files._read(self.folder / "configuration.json", _configuration, report)
        except FileNotFoundError:
            document = {}
        except (OSError, ValueError):
            raise configuration.ConfigurationInvalid("$") from None
        # Schema-invalid JSON is deliberately not rolled back to a backup.
        return configuration.prepare(document)

    def write_configuration(self, document, deadline):
        before = self.record()
        checked = configuration.prepare(document)
        lock = locks.Lock(self.folder / "store.lock", "store", before["device"])
        with lock.held(deadline):
            def guard():
                lock.check()
                if self.record()["device"] != before["device"]:
                    raise locks.LostLock()
            guard()
            files.write_json(self.folder / "configuration.json", checked.document, "TBL-002", check=guard)
        return checked
