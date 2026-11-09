"""Checks of curator answers that their schemas cannot make (API-006, API-007, SPEC-016, SPEC-019).

Pure: nothing here reads a file or writes one. The caller passes the answer
that the transport decoded, what its request carried and the stored entries
of the request's turns. It gets back the changes to apply, in order
(TASK-086), and the number of changes dropped for each reason, which the
curation record keeps (TASK-088). A quote is checked here once, against the
stored text of its entry, and keeps its provenance from then on (SPEC-020):
the speaker rules read the speaker that a saved item's quote already holds,
and a merged item copies its quotes without reading any raw log (TASK-089).
"""
import copy
from dataclasses import dataclass
import json
from pathlib import Path
import re

from . import command_result, format2, item_types, model_stream, quote_check, store

SCHEMA = Path(__file__).with_name('curate.schema.json')
MERGE_SCHEMA = Path(__file__).with_name('merge.schema.json')
STATE_SCHEMA = Path(__file__).with_name('state.schema.json')
# Why a change or a merge is dropped; each counts once, under the first check it fails.
REASONS = format2.CHANGE_REASONS
MERGE_REASONS = format2.MERGE_REASONS
QUOTES = 20
ITEM_BYTES = 64 * 1024
_OPEN = re.compile(r'[ \t]*<pasted_content id="([^"]*)">[ \t]*\Z')
_CLOSE = re.compile(r'[ \t]*</pasted_content id="([^"]*)">[ \t]*\Z')
_BREAK = re.compile(r'\r\n|\r|\n')


def _schema(path):
    return json.loads(path.read_bytes().decode('utf-8'), object_pairs_hook=command_result._pairs)


def schema():
    """The curate answer schema (API-006), read from the plugin's copy of stage 06's file."""
    return _schema(SCHEMA)


def merge_schema():
    """The merge answer schema (API-007), read from the plugin's copy of stage 06's file."""
    return _schema(MERGE_SCHEMA)


def state_schema():
    """The state answer schema (API-008), read from the plugin's copy of stage 06's file."""
    return _schema(STATE_SCHEMA)


def decode(value, rules=None):
    """The answer as the schema reads it, with `action` and `kind` in lower case.

    `rules` is the answer's schema, the curate one by default. ValueError
    when it does not fit: the caller's outcome is `bad-answer`.
    """
    rules = schema() if rules is None else rules
    validator = command_result._Validator(rules)
    folded = model_stream._fold(copy.deepcopy(value), rules, validator)
    if not isinstance(folded, dict) or not validator.matches(folded):
        raise ValueError('curator answer does not fit its schema')
    return folded


@dataclass(frozen=True)
class Sent:
    """What one curate request carried, as the checks need it."""
    items: dict      # item ID -> saved item record, every item of the request
    entries: dict    # entry ID -> (raw log name, stored TBL-007 entry), every entry of its turns
    lines: frozenset = frozenset()  # IDs of the request's state lines, for the line edits (TASK-087)


def sent(*, items, logs, lines=()):
    """`logs` holds (raw log name, the stored entries of that log the request carried)."""
    carried, entries = {}, {}
    for value in items:
        value = item_types.parse_item(item_types.item_bytes(value))
        if value['id'] in carried:
            raise ValueError('duplicate request item')
        carried[value['id']] = value
    for log, stored in logs:
        for entry in stored:
            if entry.get('kind') not in ('prompt', 'answer') or entry['id'] in entries:
                raise ValueError('invalid request entry')
            entries[entry['id']] = (log, entry)
    return Sent(carried, entries, frozenset(lines))


@dataclass(frozen=True)
class Change:
    number: int        # the change's place in the answer, from 1; state lines name changes by it
    action: str        # add, replace or withdraw; add when the speaker rules keep the targets
    targets: tuple     # the items it replaces or takes back; none for add
    kept: tuple        # targets the speaker rules keep current; the new item may disagree with each
    kind: str
    title: str
    text: str
    quotes: tuple      # TBL-012 quote records, the deciding quote first
    conflicts: tuple   # items of the request, current at this change, that it may disagree with

    @property
    def speaker(self):
        return self.quotes[0]['speaker']


@dataclass(frozen=True)
class Checked:
    changes: tuple     # the changes that passed, in the answer's order
    dropped: dict      # reason -> number of changes dropped for it; only reasons that occurred
    state: dict        # the answer's line edits as decoded, for TASK-087


def pasted(text):
    """[start, end) spans of pasted text in an entry, each through its closing line.

    A span opens at a line `<pasted_content id="...">` and closes at the line
    `</pasted_content id="...">` with the same ID; without one it runs to the end.
    Lines end at CR LF, LF or a lone CR, as the request shows each as LF.
    """
    spans, opened, name, at = [], None, None, 0
    for end in [m.start() for m in _BREAK.finditer(text)] + [len(text)]:
        line = text[at:end]
        if opened is None:
            match = _OPEN.match(line)
            if match:
                opened, name = at, match.group(1)
        elif _CLOSE.match(line) and _CLOSE.match(line).group(1) == name:
            spans.append((opened, end))
            opened = None
        at = end + (2 if text.startswith('\r\n', end) else 1)
    if opened is not None:
        spans.append((opened, len(text)))
    return spans


def _quote(log, entry, start, end, device):
    record = dict(entry=entry['id'], log=log, device=device, start=start, end=end,
                  speaker=entry['speaker'], said=entry['at'], words=entry['text'][start:end])
    item_types._quote(record)
    return record


_EPOCH = '2000-01-01T00:00:00.000Z'


def _item_bytes(change, quotes, item, at, device):
    if isinstance(change, Change):
        change = dict(kind=change.kind, title=change.title, text=change.text)
    return item_types.item_bytes(dict(id=item, kind=change['kind'], title=change['title'], text=change['text'],
                                      quotes=[copy.deepcopy(q) for q in quotes], status='current', saved=at,
                                      device=device))


def item_record(change, *, item, at, device):
    """The saved record of the item that a checked change adds; its ID and time come from the code."""
    if change.action == 'withdraw':
        raise ValueError('a withdrawal adds no item')
    data = _item_bytes(change, change.quotes, item, at, device)
    if len(data) > ITEM_BYTES:
        raise ValueError('item file too large')
    return item_types.parse_item(data)


def _targets(change, current, sent):
    targets = change['targets']
    expected = {'add': (0, 0), 'replace': (1, None), 'withdraw': (1, 1)}[change['action']]
    if len(set(targets)) != len(targets) or len(targets) < expected[0] or (
            expected[1] is not None and len(targets) > expected[1]):
        return 'shape'
    if any(target not in sent.items for target in targets):
        return 'not-in-request'
    if any(target not in current for target in targets):
        return 'not-current'
    return None


def check_curate(value, *, sent, device, rules=None):
    """Check a curate answer against its request; see the module's description."""
    format2._id(device, store.DEVICE)
    answer = decode(value, rules)
    current = {item for item, record in sent.items.items() if record['status'] == 'current'}
    prepared, changes, dropped = {}, [], {}

    def drop(reason):
        dropped[reason] = dropped.get(reason, 0) + 1

    for number, change in enumerate(answer['changes'], 1):
        reason = _targets(change, current, sent)
        if reason is not None:
            drop(reason)
            continue
        try:
            item_types._text(change['title'], 200, line=True)
            item_types._text(change['text'], 4000)
            if len(change['quotes']) > QUOTES:
                raise ValueError('too many quotes')
            for quote in change['quotes']:
                item_types._text(quote['words'], 2000)
        except ValueError:
            drop('limit')
            continue
        quotes, reason = [], None
        for quote in change['quotes']:
            if quote['entry'] not in sent.entries:
                reason = 'not-in-request'
                break
            log, entry = sent.entries[quote['entry']]
            if quote['entry'] not in prepared:
                prepared[quote['entry']] = quote_check.Prepared(entry['text'])
            forgotten = [tuple(pair) for pair in entry.get('forgotten', ())]
            found = quote_check.find(prepared[quote['entry']], quote['words'], forgotten)
            if found is None:
                reason = 'quote'
                break
            try:
                quotes.append(_quote(log, entry, found[0], found[1], device))
            except ValueError:
                reason = 'limit'
                break
        if reason is not None:
            drop(reason)
            continue
        deciding = quotes[0]
        if change['kind'] == 'decision' and any(
                start < deciding['end'] and deciding['start'] < end
                for start, end in pasted(sent.entries[deciding['entry']][1]['text'])):
            drop('pasted')
            continue
        targets, kept, action = tuple(change['targets']), (), change['action']
        speakers = [sent.items[target]['quotes'][0]['speaker'] for target in targets]
        # Only the user's own words supersede the user's item, and only an
        # item's own speaker takes it back; otherwise the statement is an item
        # of its own and the targets stay current (SPEC-016).
        if (action == 'replace' and deciding['speaker'] != 'user' and 'user' in speakers or
                action == 'withdraw' and speakers[0] != deciding['speaker']):
            targets, kept, action = (), targets, 'add'
        if action != 'withdraw' and len(_item_bytes(change, quotes, 'i_' + '0' * 12, _EPOCH, device)) > ITEM_BYTES:
            drop('limit')
            continue
        current.difference_update(targets)
        conflicts = []
        for item in change['conflicts']:
            if item in current and item not in change['targets'] and item not in conflicts:
                conflicts.append(item)
        changes.append(Change(number, action, targets, kept, change['kind'], change['title'], change['text'],
                              tuple(quotes), tuple(conflicts)))
    return Checked(tuple(changes), dropped, answer['state'])


def copied_quotes(items, picks):
    """The quotes that a merge names by item and number, copied as they were saved.

    No raw log is read and no quote is checked again (SPEC-020), so a quote
    whose entry retention deleted keeps its provenance. A number may be any
    integral JSON number, as the schema allows. ValueError when a pick names no
    quote of its item, or when there are more than 20.
    """
    saved = {}
    for value in items:
        value = item_types.parse_item(item_types.item_bytes(value))
        saved[value['id']] = value
    if not 1 <= len(picks) <= QUOTES:
        raise ValueError('invalid merged quotes')
    copied = []
    for pick in picks:
        if not isinstance(pick, dict) or set(pick) != {'item', 'number'} or pick['item'] not in saved:
            raise ValueError('invalid merged quote')
        number = pick['number']
        if not command_result._integer(number) or not 1 <= number <= len(saved[pick['item']]['quotes']):
            raise ValueError('invalid merged quote')
        copied.append(copy.deepcopy(saved[pick['item']]['quotes'][int(number) - 1]))
    return copied


@dataclass(frozen=True)
class Merge:
    number: int        # the merge's place in the answer, from 1
    items: tuple       # the items of the request that it merges, in the answer's order
    title: str
    text: str
    quotes: tuple      # TBL-012 quote records copied from its items, the deciding quote first


@dataclass(frozen=True)
class Merged:
    merges: tuple      # the merges that passed, in the answer's order
    dropped: dict      # reason -> number of merges dropped for it; only reasons that occurred
    conflicts: tuple   # (item, item) pairs of two distinct request items that the answer says may disagree


def _merged_bytes(group, merge, quotes, item, at, device):
    return item_types.item_bytes(dict(id=item, kind=group, title=merge['title'], text=merge['text'],
                                      quotes=[copy.deepcopy(q) for q in quotes], status='current',
                                      merges=list(merge['items']), saved=at, device=device))


def merged_record(merge, *, group, item, at, device):
    """The saved record of the item that a checked merge makes; its ID and time come from the code."""
    data = _merged_bytes(group, {'title': merge.title, 'text': merge.text, 'items': merge.items}, merge.quotes,
                         item, at, device)
    if len(data) > ITEM_BYTES:
        raise ValueError('item file too large')
    return item_types.parse_item(data)


def check_merge(value, *, items, device, rules=None):
    """Check a merge answer against its request (API-007, SPEC-019, SPEC-020).

    `items` are the saved records of the items that the request carried, all
    current and of the request's group. In the answer's order, a merge names
    two or more different items of the request that no earlier merge of the
    answer merged, keeps the item limits, and names its quotes by item and
    number among its own items; the code copies them as they were saved,
    without reading a raw log or checking them again. Its first quote is the
    deciding quote of one of its items and, when one of them is the user's,
    the user's, so that a merge never makes an item the user's or takes one
    from the user. A dropped merge counts once, under the first check it
    fails, and its items stay current. Conflicts keep the pairs of two
    different items of the request; the caller records those that are still
    current and not already open.
    """
    format2._id(device, store.DEVICE)
    answer = decode(value, merge_schema() if rules is None else rules)
    carried = {}
    for record in items:
        record = item_types.parse_item(item_types.item_bytes(record))
        if record['id'] in carried or record['status'] != 'current':
            raise ValueError('invalid merge request items')
        carried[record['id']] = record
    if len({record['kind'] for record in carried.values()}) > 1:
        raise ValueError('a merge request holds one kind')
    group = next(iter(carried.values()))['kind'] if carried else None
    merges, merged, dropped = [], set(), {}

    def drop(reason):
        dropped[reason] = dropped.get(reason, 0) + 1

    for number, merge in enumerate(answer['merges'], 1):
        named = merge['items']
        if len(named) < 2 or len(set(named)) != len(named):
            drop('shape')
            continue
        if any(item not in carried for item in named):
            drop('not-in-request')
            continue
        if any(item in merged for item in named):
            drop('not-current')
            continue
        try:
            item_types._text(merge['title'], 200, line=True)
            item_types._text(merge['text'], 4000)
            if len(merge['quotes']) > QUOTES:
                raise ValueError('too many quotes')
        except ValueError:
            drop('limit')
            continue
        try:
            picked = copied_quotes([carried[item] for item in named], merge['quotes'])
        except ValueError:
            drop('quote')
            continue
        # Two items curated from the same turn often hold the same quote; the merged item keeps it once.
        quotes = []
        for quote in picked:
            if quote not in quotes:
                quotes.append(quote)
        first = merge['quotes'][0]
        users = [item for item in named if carried[item]['quotes'][0]['speaker'] == 'user']
        if int(first['number']) != 1 or users and quotes[0]['speaker'] != 'user':
            drop('speaker')
            continue
        if len(_merged_bytes(group, merge, quotes, 'i_' + '0' * 12, _EPOCH, device)) > ITEM_BYTES:
            drop('limit')
            continue
        merged.update(named)
        merges.append(Merge(number, tuple(named), merge['title'], merge['text'], tuple(quotes)))
    conflicts = []
    for conflict in answer['conflicts']:
        pair = conflict['items']
        if len(pair) == 2 and pair[0] != pair[1] and all(item in carried for item in pair):
            conflicts.append((pair[0], pair[1]))
    return Merged(tuple(merges), {reason: dropped[reason] for reason in MERGE_REASONS if reason in dropped},
                  tuple(conflicts))
