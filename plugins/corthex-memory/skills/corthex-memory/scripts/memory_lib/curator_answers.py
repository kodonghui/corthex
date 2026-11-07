"""Checks of curator answers that their schemas cannot make (API-006, SPEC-016).

Pure: nothing here reads a file or writes one. The caller passes the answer
that the transport decoded, what its request carried and the stored entries
of the request's turns. It gets back the changes to apply, in order
(TASK-086), and the number of changes dropped for each reason, which the
curation record keeps (TASK-088). A quote is checked here once, against the
stored text of its entry, and keeps its provenance from then on (SPEC-020):
the speaker rules read the speaker that a saved item's quote already holds,
and a merged item copies its quotes without reading any raw log.
"""
import copy
from dataclasses import dataclass
import json
from pathlib import Path
import re

from . import command_result, format2, item_types, model_stream, quote_check, store

SCHEMA = Path(__file__).with_name('curate.schema.json')
# Why a change is dropped; each dropped change counts once, under the first check it fails.
REASONS = ('shape', 'limit', 'not-in-request', 'not-current', 'quote', 'pasted')
QUOTES = 20
ITEM_BYTES = 64 * 1024
_OPEN = re.compile(r'[ \t]*<pasted_content id="([^"]*)">[ \t]*\Z')
_CLOSE = re.compile(r'[ \t]*</pasted_content id="([^"]*)">[ \t]*\Z')
_BREAK = re.compile(r'\r\n|\r|\n')


def schema():
    """The curate-2 answer schema, read from the plugin's copy of stage 06's file."""
    return json.loads(SCHEMA.read_bytes().decode('utf-8'), object_pairs_hook=command_result._pairs)


def decode(value, rules=None):
    """The answer as the schema reads it, with `action` and `kind` in lower case.

    ValueError when it does not fit: the caller's outcome is `bad-answer`.
    """
    rules = schema() if rules is None else rules
    validator = command_result._Validator(rules)
    folded = model_stream._fold(copy.deepcopy(value), rules, validator)
    if not isinstance(folded, dict) or not validator.matches(folded):
        raise ValueError('curate answer does not fit its schema')
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
    """Check a curate-2 answer against its request; see the module's description."""
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
