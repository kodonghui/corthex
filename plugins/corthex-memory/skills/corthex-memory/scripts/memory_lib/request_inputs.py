"""Read-only curator request inputs from one project's folder.

From the curated layer it opens only the items, tombstones, current state,
removed lines, pins and conflict candidates, and from raw/ only the named log.
An item that a tombstone names is left out even while its file remains, as
after a forget stopped between its tombstone and the item's removal (TBL-016),
and the raw ranges its tombstone names show as forgotten until the forget has
rewritten the raw log, except a range kept whole for an item that stays.
Line history, run logs, the curation record and its fences, notices, the
injection log and the search index stay unread, so no request can carry them.
The caller holds the curation and layer leases while it reads (TASK-088); an
apply checks the fences again before any change.
"""
from dataclasses import dataclass
from pathlib import Path

from . import conflict_types, curator_document, diagnostics, format2, history_recovery, item_types
from . import raw_rewrite, state_types


@dataclass(frozen=True)
class Layer:
    lines: tuple       # the TBL-013 validity view, by part, position and ID
    hidden: tuple      # lines the view hides, each with its reason
    items: dict        # every item by ID that no tombstone names
    current: tuple     # current items in item-list order (TBL-015)
    pinned: tuple      # IDs of pinned current items, in pin order
    candidates: tuple  # open candidates of two current items, by time and ID
    places: dict       # every candidate's rotation place (time, ID) by ID, open or closed (SPEC-015)


def _named(folder):
    """Records named <item ID>.json; any other name is refused, never skipped."""
    found = []
    for path in sorted(folder.iterdir(), key=lambda p: p.name):
        item = path.name[:-5] if path.name.endswith('.json') else ''
        if not item_types.ITEM.fullmatch(item) or not path.is_file():
            raise ValueError('unexpected curated layer file')
        found.append((item, path.read_bytes()))
    return found


def layer(root):
    root = Path(root)
    folder = root/'layer'
    items, private, forgotten = {}, set(), set()
    for item, data in _named(folder/'tombstones'):
        private.update(history_recovery._tombstone(data, item, root.name))
        forgotten.add(item)
    for item, data in _named(folder/'items'):
        if item in forgotten:
            continue
        value = item_types.parse_item(data)
        if value['id'] != item:
            raise ValueError('item file name differs from its ID')
        items[item] = value
    view = state_types.validity_view(state_types.parse_state((folder/'state.json').read_bytes()),
                                     state_types.parse_removed((folder/'state-removed.json').read_bytes()),
                                     items, private)
    current = sorted((value for value in items.values() if value['status'] == 'current'), key=lambda v: v['id'])
    current.sort(key=lambda v: v['quotes'][0]['said'][:10], reverse=True)
    pins = item_types.parse_pins((folder/'pins.json').read_bytes())['pins']
    pinned = tuple(pin['item'] for pin in pins if pin['on'] and pin['item'] in items and
                   items[pin['item']]['status'] == 'current')
    conflicts = conflict_types.parse_conflicts((folder/'conflicts.json').read_bytes())
    candidates = conflict_types.open_candidates(conflicts)
    candidates = tuple(c for c in candidates if all(items.get(i, {}).get('status') == 'current' for i in c['items']))
    places = {c['id']: (c['at'], c['id']) for c in conflicts['candidates']}
    return Layer(tuple(view['lines']), tuple(view['hidden']), items, tuple(current), pinned, candidates, places)


def _pending(root, log):
    """Entry ID -> ranges of the log that tombstones name and no item that stays quotes.

    A forget publishes its tombstones before it rewrites the raw log, and a
    stopped forget leaves the rewrite for later (TBL-007, TBL-016). Until then
    each range its tombstones name counts as forgotten, except a range that
    overlaps a quote of an item that stays, which the rewrite keeps whole.
    """
    folder = Path(root)/'layer'
    named, forgotten = {}, set()
    for item, data in _named(folder/'tombstones'):
        history_recovery._tombstone(data, item, Path(root).name)
        forgotten.add(item)
        for quote in item_types._document(data)['quotes']:
            if quote['log'] == log and quote['start'] < quote['end']:
                named.setdefault(quote['entry'], []).append((int(quote['start']), int(quote['end'])))
    kept = {}
    if named:
        for item, data in _named(folder/'items'):
            if item in forgotten:
                continue
            for quote in item_types.parse_item(data)['quotes']:
                if quote['log'] == log and quote['entry'] in named:
                    kept.setdefault(quote['entry'], []).append((quote['start'], quote['end']))
    return {entry: [(start, end) for start, end in ranges
                    if not any(low < end and start < high for low, high in kept.get(entry, ()))]
            for entry, ranges in named.items()}


def entries(root, log):
    """The named raw log's entries in seq order, damaged and unfinished lines left out.

    Each entry's `forgotten` also holds the ranges that pending tombstones name
    (`_pending`), so the request shows them as [forgotten] and no quote of the
    answer can touch them. The quote check of an answer reads these entries.
    """
    format2._id(log, diagnostics.LOG)
    data = (Path(root)/'raw'/(log + '.jsonl')).read_bytes()
    pending, found = _pending(root, log), []
    for line in data.split(b'\n')[:-1]:
        try:
            entry = raw_rewrite._entry(line, log)
        except (ValueError, UnicodeError):
            continue
        if found and entry['seq'] <= found[-1]['seq']:
            continue
        # The raw log and the tombstones accept integral JSON numbers such as
        # 6.0; the ranges hold the integers they are.
        ranges = [[int(start), int(end)] for start, end in entry.get('forgotten', ())]
        ranges += [[start, end] for start, end in pending.get(entry['id'], ())]
        if ranges:
            entry['forgotten'] = ranges
        found.append(entry)
    return found


def session(root, log, after=0):
    """The named raw log's unprocessed turns, from `entries`."""
    return curator_document.session(log, entries(root, log), after)
