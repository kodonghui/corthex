"""Normalize only the reviewed change that makes the link checks pass over deferred items.

Core 0.14.0 lets a stage mark an approved item `deferred`. The hub's checks
then skip it as they skip a removed item (is_inactive in place of is_removed in
item_checks and requirement_checks); views still use REMOVED. Reviewed on PR #220.
"""

REVIEWED_DEFERRED = {
    "hub.py": (
        (("# A deferred item keeps its ID and is drawn as it is, but the checks pass over it as they pass over a removed one.\n"
         'DEFERRED = {"deferred", "postponed", "보류", "연기"}\n').encode("utf8"), b""),
        (b'def is_inactive(item):\n'
         b'    """Removed or deferred: the checks want no links from it and count none to it."""\n'
         b'    return any(word in REMOVED or word in DEFERRED for word in norm(item.get("status", "")).split())\n\n\n', b""),
        (b'        if is_inactive(item):\n            continue\n', b'        if is_removed(item):\n            continue\n'),
        (b'and is_inactive(items[other]))}', b'and is_removed(items[other]))}'),
        (b'and not is_inactive(item)]', b'and not is_removed(item)]'),
        (b'if not is_inactive(r) and', b'if not is_removed(r) and'),
        (b'or is removed or deferred, covers nothing.', b'or is removed, covers nothing.'),
        (b'and not is_inactive(items[other]) for other', b'and not is_removed(items[other]) for other'),
    ),
}
