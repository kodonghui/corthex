"""IDs, UTC times, private paths and the stage 05 JSON representation.

Importing this module creates nothing. Only the future `on` command may call
private_directory to create the store. Callers validate and redact records first.
"""

import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"
FIELDS = {
    "TBL-001": "format device made release migrating",
    "TBL-001.migrating": "from to started",
    "TBL-002": "consent projects retention triggers temporary models recall prices sync",
    "TBL-002.consent": "at version",
    "TBL-002.projects.*": "enabled since left_out",
    "TBL-002.projects.*.left_out": "folders kinds",
    "TBL-002.retention": "days",
    "TBL-002.triggers": "turns minutes",
    "TBL-002.models": "curator effort embedding dims",
    "TBL-002.recall": "threshold skip",
    "TBL-002.prices": "taken from models",
    "TBL-002.prices.models.*": "input output cache_write cache_read above",
    "TBL-002.prices.models.*.above": "tokens input output",
    "TBL-002.sync": "address branch",
    "TBL-003": "at project call model instructions input output cache_write cache_read first_ms total_ms result error request cost prices",
    "TBL-004": "at step hook host project error log count",
    "TBL-005": "at hook host ms outcome",
    "TBL-007": "id seq turn at host session kind speaker text cut event reason forgotten",
    "TBL-009": "logs applies recent failures consolidation stopped rebuilt",
    "TBL-009.recent[]": "at kind result error applied dropped state",
    "TBL-009.failures": "count log turn",
    "TBL-009.consolidation": "last due failures",
    "TBL-009.stopped": "at by errors",
    "TBL-011": "at session where prompt items scores",
}
MAPS = {"TBL-002.projects", "TBL-002.prices.models", "TBL-009.logs"}
RESERVED = {"con", "prn", "aux", "nul"} | {
    prefix + str(n) for prefix in ("com", "lpt") for n in range(10)
}


def new_id(prefix):
    """Return a device/entry/item/state/candidate ID with 60 random bits."""
    if prefix not in ("d", "e", "i", "s", "c"):
        raise ValueError("unknown ID prefix")
    bits = secrets.randbits(60)
    return prefix + "_" + "".join(CROCKFORD[(bits >> shift) & 31]
                                 for shift in range(55, -1, -5))


def utc_time(value=None):
    value = datetime.now(timezone.utc) if value is None else value
    if value.utcoffset() is None:
        raise ValueError("a timezone is required")
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def utc_date(value=None):
    return utc_time(value)[:10]


class MemoryHomeInvalid(ValueError):
    code = "configuration-invalid"
    field = "CORTHEX_MEMORY_HOME"

    def __init__(self):
        super().__init__("CORTHEX_MEMORY_HOME must be an absolute path")


def memory_home():
    """Resolve the store without reading it or creating it."""
    override = os.environ.get("CORTHEX_MEMORY_HOME")
    if not override:
        return Path.home() / ".corthex" / "corthex-memory"
    try:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise MemoryHomeInvalid()
        return path
    except (OSError, RuntimeError, ValueError):
        raise MemoryHomeInvalid() from None


def project_folder_name(name):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,59}", name):
        raise ValueError("invalid project name")
    return name + "_" if name in RESERVED else name


def private_directory(path):
    """Explicitly create a directory and missing parents, private on POSIX."""
    path = Path(path)
    missing, cursor = [], path
    while not cursor.exists():
        missing.append(cursor)
        parent = cursor.parent
        if parent == cursor:
            raise FileNotFoundError("directory root is missing")
        cursor = parent
    for directory in reversed(missing):
        # Python 3.13's Windows 0700 disables inheritance; use its default there.
        directory.mkdir(mode=0o777 if os.name == "nt" else 0o700, exist_ok=True)
        if os.name != "nt":
            directory.chmod(0o700)
    if not path.is_dir():
        raise NotADirectoryError("a directory is required")
    if os.name != "nt":
        path.chmod(0o700)
    return path


def private_open(path, flags):
    """Open only the named file; never create its parent directories."""
    fd = os.open(str(path), flags | getattr(os, "O_BINARY", 0), 0o600)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _ordered(value, where):
    if isinstance(value, dict):
        fields = FIELDS.get(where, "").split()
        keys = [key for key in fields if key in value]
        keys += sorted(key for key in value if key not in fields)
        return {key: _ordered(value[key], where + (".*" if where in MAPS else "." + key))
                for key in keys}
    if isinstance(value, list):
        return [_ordered(item, where + "[]") for item in value]
    return value


def json_bytes(record, table, compact=False):
    """Encode a C1 record, ordered by its table; dynamic mapping keys sort.

    This is representation, not record validation (TASK-004). Unknown fields
    are retained in sorted order, never silently dropped.
    """
    if table not in FIELDS or "." in table:
        raise ValueError("unknown record table")
    if not isinstance(record, dict):
        raise ValueError("a record must be an object")
    options = {"separators": (",", ":")} if compact else {"indent": 2}
    return (json.dumps(_ordered(record, table), ensure_ascii=False, allow_nan=False,
                       **options) + "\n").encode("utf-8")
