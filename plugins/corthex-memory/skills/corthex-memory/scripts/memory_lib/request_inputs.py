"""Read-only curator request inputs from one project's folder.

From the curated layer it opens only the items, tombstones, current state,
removed lines, pins and conflict candidates, and from raw/ only the named log.
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
    items: dict        # every item by ID
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
    items, private = {}, set()
    for item, data in _named(folder/'items'):
        value = item_types.parse_item(data)
        if value['id'] != item:
            raise ValueError('item file name differs from its ID')
        items[item] = value
    for item, data in _named(folder/'tombstones'):
        private.update(history_recovery._tombstone(data, item, root.name))
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


def session(root, log, after=0):
    """The named raw log's unprocessed turns; damaged and unfinished lines are left out."""
    format2._id(log, diagnostics.LOG)
    data = (Path(root)/'raw'/(log + '.jsonl')).read_bytes()
    entries = []
    for line in data.split(b'\n')[:-1]:
        try:
            entry = raw_rewrite._entry(line, log)
        except (ValueError, UnicodeError):
            continue
        if entries and entry['seq'] <= entries[-1]['seq']:
            continue
        entries.append(entry)
    return curator_document.session(log, entries, after)
