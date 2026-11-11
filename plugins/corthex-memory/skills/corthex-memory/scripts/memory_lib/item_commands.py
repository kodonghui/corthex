"""The list and open commands (API-020, API-022; SPEC-025, SPEC-020; TASK-040).

The command runner parses `list` and `open` but hands them to no handler
before the 0.3.0 activation, so it answers them as not implemented, as in C1,
and an installed plugin keeps C1 behaviour; until then the tests call these
handlers as the runner will, after its gates, with the format-2 store binding.
Each reads under the project's layer lease, waiting for it as long as the other
commands wait for theirs, through the store's path fence, and changes nothing.

`list` shows the item list (TBL-015) as the project's items make it: one line
per current item that no tombstone names, newest first by its deciding quote's
date and then by ID, only of the kind that `--kind` names, at most `--limit`
lines, with `more` counting the lines that the limit left out. It reads the
items themselves, not item-list.txt, which a stopped undo or forget can leave
behind them.

`open` shows the named items of every status, each with its kind, status, the
item that superseded it or the items it merges, title, text, time saved and
quotes. A quote is `elsewhere` when another device wrote its entry, whose
text this device does not read; `here` when this device's raw log of the
project holds the entry within the retention period, as SPEC-025 lets the
skill read around a quote; and `deleted` when the entry is gone or past that
period, which retention deletes at its next run. With `--around N` a quote
held here also has up to N characters of its entry's text before it and after
it, 2,000 at most, with each range that a forget or a pending tombstone names
shown as [forgotten], as curator requests show it; a mark is never cut. Unlike
the curator, whose worker recovers an interrupted write before it reads, `open`
reads around what such a write left: a tombstone is its file, or its backup
when the file is gone, as the start summary reads it, other names in the
tombstones' folder, such as temporary copies, are skipped, and the items that
stay are read as `list` reads them. Only `--around` and an entry ID read the
tombstones, once for the command: `--around` when a named item quotes this
device's entries, and an entry ID when a raw log's bytes hold it. So a
tombstone that cannot be read fails only such an `open`, while any other
`open`, like `list`, sees only the names in their folder; the items that stay
are read at most once, for both the pending ranges and the closest lines.

`open` of an entry ID shows the entry, as a pointer of injected memory names
it (SPEC-148, TASK-112): from this device's raw logs of the project, a prompt
or an answer within the retention period, with its raw log, speaker and time
and the first 2,000 characters of its text, each range that a forget or a
pending tombstone names shown as [forgotten], as around a quote, and whether
the text is whole: not when `open` cut it, nor when the recording had cut it
(TBL-007 `cut`). Only the raw logs whose bytes hold a named entry's ID are
read as entries, each once, also when a quote's words around it read it
first; a raw log that goes while it is read is skipped, and one that a link
reaches raises, as an item record does. An argument that names no item of
the project and no such entry, or an
item that a tombstone names, is `item-not-found`, with the arguments in
`missing`, the closest lines of the item list in `matches` and the items and
entries that the other arguments name.

A project without a folder, or whose memory is being deleted, has no items. An
item record that cannot be read, or that a link reaches, raises, which the
runner reports as `internal`, as it does for forget and undo.
"""
import stat

from . import base, clock, commands, curation_worker, curator_document, diagnostics, files, forget_plan
from . import history_recovery, item_io, item_types, locks, request_inputs, run_listing, run_log

# The commands' shared lock wait, within one bound for the whole read.
WAIT, SECONDS = 10.0, 60.0
# An argument as the result schema holds it, and the most text around a quote.
ARGUMENT, AROUND = 200, 2000
FORGOTTEN = curator_document.FORGOTTEN
MISSING = 'No item of this project has an ID in data.missing; data.matches holds the closest lines of the item list.'
MISSING_ENTRIES = ('No item of this project and no entry that this device holds has an ID in data.missing; '
                   'data.matches holds the closest lines of the item list.')
TURNS = ('prompt', 'answer')  # the raw entries that have a speaker and a text


def _read(context, read):
    """read(memory, root, deadline, check) under the project's layer lease; None without a folder or while deleted."""
    memory = context.memory
    root = memory.folder / 'projects' / base.project_folder_name(context.project.name)
    if memory.fence.check(root) is None:
        return None
    deadline = clock.now() + SECONDS
    with memory.lease(root / 'layer.lock', 'layer', deadline, 'skill',
                      acquire_deadline=min(deadline, clock.now() + WAIT)):
        if curation_worker._deleted(memory, root):
            return None

        def check():
            memory.check(deadline, memory.held)
        value = read(memory, root, deadline, check)
        check()
        return value


def _items(memory, root, deadline, check):
    """Every item of the project that no tombstone names, as item_io reads them for the index."""
    if memory.fence.check(root / 'layer/items') is None:
        return []
    return item_io._items(memory, root, deadline, check)


def listed(items):
    """The current items in the item list's order (TBL-015): newest first by the deciding quote's date, then by ID."""
    current = sorted((value for value in items if value['status'] == 'current'), key=lambda value: value['id'])
    current.sort(key=lambda value: value['quotes'][0]['said'][:10], reverse=True)
    return current


def _list_say(count, more, kind):
    what = 'current %s item' % kind if kind else 'current item'
    if not count:
        return 'No %ss.' % what
    say = '%d %s%s, newest first' % (count, what, '' if count == 1 else 's')
    return say + ('; --limit left out %d more.' % more if more else '.')


def list_items(context):
    """API-020 after the runner's gates, with the format-2 store binding as `context.memory`."""
    project = context.project.name
    kind, limit = context.arguments.get('kind'), context.arguments.get('limit', 200)
    if kind is not None and kind not in item_types.KINDS or type(limit) is not int or limit < 1:
        return commands.common_result('list', 'usage')
    try:
        items = _read(context, _items) or []
    except locks.LockBusy:
        return commands.common_result('list', 'lock-busy')
    lines = [run_listing.list_line(value) for value in listed(items) if kind is None or value['kind'] == kind]
    data = {'project': project, 'items': lines[:limit], 'more': max(0, len(lines) - limit)}
    say = _list_say(len(data['items']), data['more'], kind)
    return commands.result('list', data, say, 'done' if lines else 'nothing')


def _item(memory, root, name, deadline, check):
    """The project's item that `name` names, or None when there is none or a tombstone names it."""
    if not item_types.ITEM.fullmatch(name) or item_io._private(memory, root, name):
        return None
    path = root / 'layer/items' / (name + '.json')
    if memory.fence.check(path) is None:
        # A backup without its file makes the item list's read below raise RestoreNeeded, as item_io reads it.
        return None
    value = item_io._record(memory, path, item_types.parse_item, deadline, check)
    if value['id'] != name:
        raise files.RestoreNeeded()
    return value


def _pieces(text, ranges, low, high):
    """The text from low to high as (text, is a mark) pieces, each forgotten range in it one [forgotten] mark."""
    pieces, used = [], low
    for start, end in ranges:
        if end <= low or start >= high:
            continue
        start, end = max(start, low), min(end, high)
        if start > used:
            pieces.append((text[used:start], False))
        pieces.append((FORGOTTEN, True))
        used = max(used, end)
    if used < high:
        pieces.append((text[used:high], False))
    return pieces


def _take(pieces, size, backwards):
    """At most `size` characters of the pieces, from the end next to the quote, never part of a mark."""
    taken, left = [], size
    for piece, mark in (reversed(pieces) if backwards else pieces):
        if left <= 0 or mark and len(piece) > left:
            break
        part = piece if mark else (piece[len(piece) - min(left, len(piece)):] if backwards else piece[:left])
        taken.append(part)
        left -= len(part)
    return ''.join(reversed(taken) if backwards else taken)


def _ranges(entry):
    """The entry's forgotten ranges, sorted, those that touch or overlap made one."""
    ranges = []
    for start, end in sorted((int(start), int(end)) for start, end in entry.get('forgotten', ())):
        if ranges and start <= ranges[-1][1]:
            ranges[-1][1] = max(ranges[-1][1], end)
        else:
            ranges.append([start, end])
    return ranges


def around(entry, quote, size):
    """(before, after): up to `size` characters of the entry's text on each side of the quote, as `open` shows them."""
    text = entry.get('text') or ''
    ranges = _ranges(entry)
    start, end = min(int(quote['start']), len(text)), min(int(quote['end']), len(text))
    return (_take(_pieces(text, ranges, 0, start), size, True),
            _take(_pieces(text, ranges, end, len(text)), size, False))


def entry_line(entry, log):
    """A raw entry as `open` shows it (open-entry): the first 2,000 characters of its text, a forgotten range one
    [forgotten] mark that is never cut, and `whole`, false when `open` cut the text or the recording had cut it
    (TBL-007 `cut`)."""
    text = entry['text']
    pieces = _pieces(text, _ranges(entry), 0, len(text))
    shown = _take(pieces, AROUND, False)
    return {'entry': entry['id'], 'log': log, 'speaker': entry['speaker'], 'said': entry['at'], 'text': shown,
            'whole': 'cut' not in entry and len(shown) == sum(len(piece) for piece, _ in pieces)}


def _quote(quote, entries, device, cutoff, size):
    line = {name: quote[name] for name in ('entry', 'log', 'device', 'speaker', 'said', 'words')}
    if quote['device'] != device:
        line['held'] = 'elsewhere'
        return line
    entry = entries(quote['log']).get(quote['entry'])
    # An entry past the retention period is gone for the skill, as retention deletes it at its next run.
    if entry is None or entry['at'] < cutoff:
        line['held'] = 'deleted'
        return line
    line['held'] = 'here'
    if size is not None:
        line['before'], line['after'] = around(entry, quote, size)
    return line


def opened(value, entries, device, cutoff, size=None):
    """An item as `open` shows it (open-item), its quotes with where their entries are held.

    `cutoff` is the time that the retention period starts from, as a TBL-004 time.
    """
    line = {'item': value['id'], 'kind': value['kind'], 'status': value['status']}
    for name in ('superseded_by', 'merges'):
        if name in value:
            line[name] = value[name]
    line.update(title=value['title'], text=value['text'], saved=value['saved'],
                quotes=[_quote(quote, entries, device, cutoff, size) for quote in value['quotes']])
    return line


def _tombstones(memory, root, deadline, read):
    """The documents of the project's tombstones, each read from its file, or from its backup when the file is gone.

    The start summary and recall count a tombstone's backup as the tombstone,
    since an interrupted write can leave it alone, and the start summary reads
    them in the same way; other names, such as such a write's temporary
    copies, are skipped. A tombstone file that cannot be read raises, even
    when its backup reads, as it does for the start summary and the curator.
    """
    folder = root / 'layer/tombstones'
    if memory.fence.check(folder) is None:
        return []
    names = {}
    for path in files._retry(lambda: list(folder.iterdir()), deadline):
        for suffix in ('.json', '.json.bak'):
            item = path.name[:-len(suffix)] if path.name.endswith(suffix) else ''
            if item_types.ITEM.fullmatch(item):
                names.setdefault(item, []).append(path.name)
    stones = []
    for item, found in sorted(names.items()):
        for name in sorted(found):  # the file before its backup
            try:
                data = read(folder / name)
            except FileNotFoundError:
                continue
            history_recovery._tombstone(data, item, root.name)
            stones.append(item_types._document(data))
            break
    return stones


def _pending(memory, root, deadline, read, items):
    """log -> entry ID -> the ranges that pending tombstones name and no item that stays quotes (request_inputs.ranges).

    `items()` gives the items that stay, read as `list` reads them (item_io):
    an item's backup beside its file and temporary copies are skipped, and a
    backup without its file raises RestoreNeeded.
    """
    stones = _tombstones(memory, root, deadline, read)
    return {log: request_inputs.ranges(stones, log, items)
            for log in sorted({quote['log'] for stone in stones for quote in stone['quotes']})}


def _entries(memory, root, read, pending):
    """(entries, found): `entries(log)` gives the log's entries by ID, from this device's raw log of the project, none
    once retention deleted it, and `found` holds the logs read so far, log -> entries by ID.

    `pending()` gives the ranges that pending tombstones name, log -> entry ID
    -> ranges (`_pending`), and is called once, when the first entry is wanted.
    An ID that two entries of a log hold gives the first, as `_raw_entries`
    finds it, and anything but a folder in `raw`'s place holds no entry, as
    there; a link raises, as the fence refuses it.
    """
    found, ranges, folder = {}, [], []

    def entries(log):
        if log not in found:
            if not folder:
                info = memory.fence.check(root / 'raw')
                folder.append(info is not None and stat.S_ISDIR(info.st_mode))
            if not folder[0]:
                found[log] = {}
                return found[log]
            if not ranges:
                ranges.append(pending())
            held = {}
            try:
                for entry in request_inputs.entries(root, log, read, ranges[0].get(log, {})):
                    held.setdefault(entry['id'], entry)
            except FileNotFoundError:
                held = {}
            found[log] = held
        return found[log]
    return entries, found


def _raw_entries(memory, root, names, read, pending, cutoff, deadline, check, parsed):
    """entry ID -> (raw log, entry) for each of `names` that this device's raw logs of the project hold as a prompt
    or an answer within the retention period, its `forgotten` with the ranges that pending tombstones name.

    The logs go in name order, and only one whose bytes hold a named ID that
    is not found yet is read as entries; an entry ID that two logs hold is
    found in the first. `parsed` holds the logs already read as entries with
    the same ranges, log -> entries by ID, which are not read again. Anything
    but a folder in `raw`'s place or a file under a raw log's name, such as a
    folder there, holds no entry, and neither does a log that goes while it
    is read, as retention can delete it; a link raises, as the fence refuses
    it.
    """
    folder = root / 'raw'
    info = memory.fence.check(folder) if names else None
    if info is None or not stat.S_ISDIR(info.st_mode):
        return {}
    found = {}
    for path in sorted(files._retry(lambda: list(folder.iterdir()), deadline)):
        log = path.name[:-len('.jsonl')] if path.name.endswith('.jsonl') else ''
        left = [name for name in names if name not in found]
        if not left:
            break
        if not diagnostics.LOG.fullmatch(log):
            continue
        check()
        if log in parsed:
            held = parsed[log].values()
        else:
            info = files._retry(lambda: memory.fence.check(path), deadline)
            if info is None or not stat.S_ISREG(info.st_mode):
                continue
            try:
                data = read(path)
            except FileNotFoundError:
                continue
            if not any(name.encode('ascii') in data for name in left):
                continue
            held = request_inputs.entries(root, log, lambda _: data, pending().get(log, {}))
        for entry in held:
            if entry['id'] in left and entry['id'] not in found and entry['kind'] in TURNS and entry['at'] >= cutoff:
                found[entry['id']] = (log, entry)
    return found


def _entries_say(entries):
    cut = sum(not line['whole'] for line in entries)
    if len(entries) == 1:
        return '1 entry of this device, with its text%s.' % (', which is cut' if cut else '')
    return '%d entries of this device, with their texts%s.' % (len(entries), '; %d of them cut' % cut if cut else '')


def _open_say(items, size, entries=None):
    if not items and entries:
        return _entries_say(entries)
    said = _items_say(items, size)
    return said + ' ' + _entries_say(entries) if entries else said


def _items_say(items, size):
    count, quotes = len(items), sum(len(value['quotes']) for value in items)
    here = sum(quote['held'] == 'here' for value in items for quote in value['quotes'])
    them = 'it' if quotes == 1 else 'them'
    say = '%s, with %s %s' % ('1 item' if count == 1 else '%d items' % count, 'its' if count == 1 else 'their',
                              'quote' if quotes == 1 else 'quotes')
    if size is None:
        return say + '.'
    if here == quotes:
        return say + ' and the words around %s.' % them
    if not here:
        return say + '; this device does not hold the quoted %s, so nothing around %s is shown.' % (
            'entry' if quotes == 1 else 'entries', them)
    return say + ' and the words around the %d that this device holds.' % here


def open_items(context, *, when=None):
    """API-022 after the runner's gates, with the format-2 store binding as `context.memory`.

    `when` fixes the time that the retention period counts from, for tests.
    """
    project = context.project.name
    names, size = context.arguments.get('item'), context.arguments.get('around')
    if (not isinstance(names, list) or not names or
            any(type(name) is not str or not 1 <= len(name) <= ARGUMENT for name in names) or
            size is not None and (type(size) is not int or not 0 <= size <= AROUND)):
        return commands.common_result('open', 'usage')
    names = list(dict.fromkeys(names))  # each name once, in the order first named
    wanted = [name for name in names if item_types.ENTRY.fullmatch(name)]
    cutoff = run_log._cutoff(base.utc_time(when), context.configuration.values['retention']['days'])[0]

    def read(memory, root, deadline, check):
        staying, ranges = [], []

        def items():
            # The items that stay, read at most once, for the pending ranges and the closest lines.
            if not staying:
                staying.append(_items(memory, root, deadline, check))
            return staying[0]

        def pending():
            # The ranges that pending tombstones name, read at most once, for the words around quotes and entries.
            if not ranges:
                ranges.append(_pending(memory, root, deadline, reader, items))
            return ranges[0]
        values = {name: _item(memory, root, name, deadline, check) for name in names}
        reader = run_listing._reader(memory, deadline)
        # Only the words around a quote and an entry's text show the ranges that pending tombstones name.
        entries, parsed = _entries(memory, root, reader, dict if size is None else pending)
        shown = [opened(value, entries, memory.device, cutoff, size) for value in values.values() if value is not None]
        # The words around quotes read a log's entries with the pending ranges too, so an entry ID uses them.
        raw = _raw_entries(memory, root, wanted, reader, pending, cutoff, deadline, check,
                           {} if size is None else parsed)
        held = [entry_line(raw[name][1], raw[name][0]) for name in wanted if name in raw]
        missing = [name for name, value in values.items() if value is None and name not in raw]
        lines = [run_listing.list_line(value) for value in listed(items())] if missing else []
        return shown, held, missing, lines
    try:
        shown, held, missing, lines = _read(context, read) or ([], [], names, [])
    except locks.LockBusy:
        return commands.common_result('open', 'lock-busy')
    data = {'project': project, 'items': shown}
    if wanted:
        data['entries'] = held
    if not missing:
        return commands.result('open', data, _open_say(shown, size, held))
    data.update(missing=missing, matches=forget_plan.closest(lines, missing))
    found = ['data.items holds the %d found' % len(shown)] if shown else []
    if held:
        found.append('data.entries holds the %d found' % len(held))
    say = (MISSING_ENTRIES if wanted else MISSING) + (' ' + ' and '.join(found) + '.' if found else '')
    return commands.result('open', data, say, 'refused', 'item-not-found')
