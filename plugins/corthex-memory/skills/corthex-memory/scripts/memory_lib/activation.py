"""The 0.3.0 activation (TASK-117): the running release, and the kind of memory store it finds.

Below release 0.3.0 the command runner, the hooks and the memory worker keep C1
behaviour, so the plugin that the marketplace installs from main stays C1 until
the release raises its version. From 0.3.0 each finds the kind of store from its
two store records before its gates. It reads them through the caller's reader,
such as the store's path fence, and restores neither; the binding that it then
chooses reads, restores and refuses as before.
"""
import json
from pathlib import Path

from . import configuration, format2, store

FIRST_C2 = (0, 3, 0)
NAMED = ("store.json", "store.json.bak")
NONE, FORMAT_1, FORMAT_2, MIGRATING, NEWER, DAMAGED = "none", "format-1", "format-2", "migrating", "newer", "damaged"
_MANIFEST = Path(__file__).resolve().parents[4] / ".codex-plugin" / "plugin.json"
_release = []


def release():
    """The running plugin release, from the packaged Codex manifest, read once per process."""
    if not _release:
        _release.append(json.loads(_MANIFEST.read_text(encoding="utf-8"))["version"])
    return _release[0]


def version(text):
    """A release's numbers, such as (0, 3, 0) for `0.3.0`, or None for text that is not one."""
    try:
        return tuple(int(part) for part in text.split("."))
    except (AttributeError, ValueError):
        return None


def c2(text=None):
    """Whether release `text`, by default the running one, is 0.3.0 or later; a manifest that cannot be read is not."""
    try:
        numbers = version(release() if text is None else text)
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return numbers is not None and numbers >= FIRST_C2


def record_kind(data):
    """The kind of one store record's bytes, or None when they are not a store record that can be read."""
    try:
        value = store.json_document(data)
        if not isinstance(value, dict) or not configuration.integer(value.get("format")) or value["format"] < 1:
            return None
        if value["format"] > 2:
            return NEWER
        if value["format"] == 1 and "migrating" not in value:
            store._record(data)
            return FORMAT_1
        return MIGRATING if "migrating" in format2.parse_store(data, allow_migrating=True) else FORMAT_2
    except Exception:
        return None


def combine(primary, backup):
    """The kind of store from the kinds of its store record and backup, None for one that cannot be read.

    A record of a format after 2 makes the store newer and one that carries a
    migration makes it a migration that stopped, whichever record it is.
    Otherwise the store record decides, or while it cannot be read its backup, as
    the gates read them; a store record whose backup has the other format is
    damaged, since restoring that backup would change the store's format.
    """
    for kind in (NEWER, MIGRATING):
        if kind in (primary, backup):
            return kind
    if primary is None:
        return backup or DAMAGED
    if backup is not None and backup != primary:
        return DAMAGED
    return primary


def store_kind(root, read):
    """The kind of store at `root`; `read(path)` gives a record's bytes, through the caller's path fence.

    A missing record, or one that the parsers refuse, cannot be read. Any other
    error of `read`, such as a link that the fence refuses, a lost root or the
    deadline, is raised as the gates would raise it.
    """
    root = Path(root)
    if not root.exists():
        return NONE
    kinds = []
    for name in NAMED:
        try:
            data = read(root / name)
        except FileNotFoundError:
            data = None
        kinds.append(None if data is None else record_kind(data))
    return combine(*kinds)
