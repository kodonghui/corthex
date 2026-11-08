"""The forget preview (API-025; SPEC-035; TASK-097), from one snapshot of a project.

Pure functions; `forget_command` reads the snapshot under the project's layer
lease, and the confirmed forget's effects arrive with TASK-098. The preview
names what goes with the forgotten items:

- `also`: every other item that stays and quotes text overlapping one of their
  quotes in the same raw log entry, whatever its status or device.
- `raw`: for each entry that this device's raw logs hold, the ranges that the
  forget fills with U+FFFD and their ranges kept whole, because they overlap a
  quote of an item that stays (TBL-007). An earlier tombstone's range in the
  same entry that no item that stays overlaps any more is filled too, unless the
  entry already lists it as forgotten. Once the forget's tombstones exist, the
  request reader hides the same ranges (`request_inputs._pending`).
- `state_lines`: the lines of the TBL-013 validity view that cite a forgotten
  item or an entry that one quotes, with their text; a line that the view
  hides is not shown.
- `pinned` and `settled_conflicts`: their pins, and the open candidates that
  name one of them.
- `history_records`: line-history records (TBL-119) that go, because they cite
  a forgotten item or an entry that one quotes, or that keep a nonempty reason,
  which the forget clears; each record once, by its epoch, generation and line,
  across the copies read.
"""
import difflib
from dataclasses import dataclass

OUTSIDE = ('host-transcript', 'providers', 'devices-without-sync')
MATCHES = 5


@dataclass(frozen=True)
class Plan:
    selected: tuple    # the forgotten items' IDs, the item first, each once
    targets: frozenset  # those IDs and the entries their quotes name
    data: dict         # the preview that the confirmation code binds


def _spans(quotes, places=None):
    """(log, entry) -> nonempty quoted ranges, only at `places` when they are given."""
    found = {}
    for quote in quotes:
        key = (quote['log'], quote['entry'])
        start, end = int(quote['start']), int(quote['end'])
        if start < end and (places is None or key in places):
            found.setdefault(key, []).append((start, end))
    return found


def _overlaps(span, others):
    return any(low < span[1] and span[0] < high for low, high in others)


def targets(selected):
    """The forgotten items and the entries that they quote, which no state line or history record may cite."""
    return frozenset([item['id'] for item in selected] +
                     [quote['entry'] for item in selected for quote in item['quotes']])


def shared(selected, staying):
    """The items that stay and quote text that overlaps a forgotten item's quote, by ID."""
    mine = _spans(quote for item in selected for quote in item['quotes'])
    return sorted(item['id'] for item in staying
                  if any(_overlaps(span, mine[key]) for key, spans in _spans(item['quotes'], mine).items()
                         for span in spans))


def raw(selected, staying, tombstones, held):
    """This device's entries whose quoted ranges the forget fills or keeps whole.

    `held` maps (log, entry ID) to the entries that this device's raw logs hold.
    A range that does not fit its entry's text names nothing to fill.
    """
    mine = _spans(quote for item in selected for quote in item['quotes'])
    earlier = _spans((quote for stone in tombstones for quote in stone['quotes']), mine)
    guards = _spans((quote for item in staying for quote in item['quotes']), mine)
    found = []
    for key in sorted(mine):
        entry = held.get(key)
        if entry is None or not isinstance(entry.get('text'), str):
            continue
        size, guard = len(entry['text']), guards.get(key, ())
        done = {(int(start), int(end)) for start, end in entry.get('forgotten', ())}
        own = [span for span in mine[key] if span[1] <= size]
        old = [span for span in earlier.get(key, ()) if span[1] <= size]
        kept = sorted({span for span in own if _overlaps(span, guard)})
        filled = sorted({span for span in own + old if not _overlaps(span, guard)} - done)
        if kept or filled:
            found.append({'entry': key[1], 'log': key[0], 'forgotten': [list(span) for span in filled],
                          'kept': [list(span) for span in kept]})
    return found


def state_lines(lines, cited):
    """The visible lines that cite a forgotten item or an entry that one quotes, in the view's order."""
    return [{'line': line['id'], 'part': line['part'], 'text': line['text']}
            for line in lines if cited.intersection(line['cites'])]


def pinned(selected, pins):
    on = {pin['item'] for pin in pins if pin['on']}
    return [item for item in selected if item in on]


def settled(selected, candidates):
    """The open candidates, in their rotation order, that name a forgotten item."""
    return [candidate['id'] for candidate in candidates if set(selected).intersection(candidate['items'])]


def history(copies, cited):
    """How many records go or lose a nonempty reason, each once by (epoch, generation, line)."""
    counted = set()
    for records in copies:
        for record in records:
            value = record.value
            if cited.intersection(value['cites']) or value['why']:
                counted.add((value['epoch'], value['generation'], value['line']))
    return len(counted)


def _ratio(argument, text):
    return difflib.SequenceMatcher(None, argument, text, autojunk=False).ratio()


def closest(lines, arguments, limit=MATCHES):
    """Up to `limit` item-list lines most like the arguments, by ID or title, ties in list order."""
    folded = [argument.casefold() for argument in arguments]

    def score(line):
        title = line['title'].casefold()
        return max(max(_ratio(argument, line['item']), _ratio(argument, title)) for argument in folded)
    return sorted(lines, key=lambda line: -score(line))[:limit] if folded else []


def preview(project, item, extra, selected, staying, *, lines, pins, candidates, tombstones, held, copies):
    """The plan of a forget, whose data the confirmation binds.

    `selected` holds the forgotten items' records, the item first, each once;
    `staying` every other item that no tombstone names. `copies` holds the
    line-history copies read, or is None when the primary cannot be read.
    """
    ids = tuple(value['id'] for value in selected)
    cited = targets(selected)
    data = {'project': project, 'item': item, 'with': list(extra), 'also': shared(selected, staying),
            'state_lines': state_lines(lines, cited), 'pinned': pinned(ids, pins),
            'raw': raw(selected, staying, tombstones, held), 'outside': list(OUTSIDE),
            'settled_conflicts': settled(ids, candidates)}
    if copies is not None:
        data['history_records'] = history(copies, cited)
    return Plan(ids, cited, data)


def _plural(count, one, many=None):
    return '%d %s' % (count, one if count == 1 else many or one + 's')


def _names(ids, most=3):
    shown = list(ids[:most])
    if len(ids) > most:
        shown.append('%d more' % (len(ids) - most))
    return shown[0] if len(shown) == 1 else ', '.join(shown[:-1]) + ' and ' + shown[-1]


def say(plan):
    """What the agent tells the user before the yes: one short sentence for each kind of effect."""
    data, many = plan.data, len(plan.selected) > 1
    subject = data['item'] if not many else '%s and %s' % (
        data['item'], _plural(len(plan.selected) - 1, 'other item'))
    goes = ['them and their search index rows' if many else 'it and its search index rows']
    if data['state_lines']:
        goes.append(_plural(len(data['state_lines']), 'current state line'))
    if data['pinned']:
        goes.append(_plural(len(data['pinned']), 'pin'))
    words = ['Forgetting %s removes %s.' % (subject, ', '.join(goes[:-1]) + ' and ' + goes[-1]
                                             if len(goes) > 1 else goes[0])]
    filled = sum(1 for entry in data['raw'] if entry['forgotten'])
    if filled:
        words.append('It fills the quoted words in %s on this device.' % _plural(filled, 'raw log entry',
                                                                                  'raw log entries'))
    if data['also']:
        words.append('Words that %s also quote%s stay whole; name %s with --with to forget %s too.' % (
            _names(data['also']), 's' if len(data['also']) == 1 else '',
            'that item' if len(data['also']) == 1 else 'those items',
            'it' if len(data['also']) == 1 else 'them'))
    if data['settled_conflicts']:
        words.append('%s settled.' % (_plural(len(data['settled_conflicts']), 'open conflict candidate') +
                                      (' is' if len(data['settled_conflicts']) == 1 else ' are')))
    if 'history_records' not in data:
        words.append('The line history cannot be read now, so this forget cannot yet count or verify its '
                     'line-history cleanup.')
    elif data['history_records']:
        count = data['history_records']
        words.append('%s removed or cleared of %s reason, so undoing an older run may be partial.' % (
            _plural(count, 'line-history record') + (' is' if count == 1 else ' are'),
            'its' if count == 1 else 'their'))
    words.append('Copies in the host transcript, at the model providers and on devices without sync stay.')
    return ' '.join(words)
