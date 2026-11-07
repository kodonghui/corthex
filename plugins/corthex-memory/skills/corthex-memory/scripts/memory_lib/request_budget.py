"""Curate request sizes (SPEC-015, SPEC-143; API-009; TASK-084).

A curate request holds the instructions, the answer schema, the current state,
an item list, the open candidates that travel with both of their items, and
whole unprocessed turns, oldest first, under 100,000 input tokens. The steps
are API-009's:

1. When the safe estimate of the instructions, the schema, the state, the item
   list and the candidates passes 40,000, the list goes in short lines, and
   when that still passes, only in part: the items that the state cites, the
   pinned items, whole candidate bundles in rotation after `conflict_after`,
   then the items that rank highest by words for the batch's turns, or the
   newest items when the index cannot be read. Nothing joins that would pass
   40,000. Any form but `full` makes consolidation due at once.
2. Whole turns join, oldest first, while the working estimate stays under 97,000.
3. A request whose safe estimate is 60,000 or less goes without counting.
4. Any other is counted. A count of 99,000 or less goes; a higher one loses its
   newest turns until its working estimate is lower by the excess and a tenth
   more, and is counted again, three counts at most. When no request could be
   that much lower, because the count reads the text far denser than the
   working estimate, it loses the same share of its working estimate as the
   excess and a tenth more are of the count.
5. When counting fails, or the third count is still too high, the turns are
   filled again by the safe estimate up to 90,000, and the request goes
   without counting.
6. A turn too large alone goes in parts, each sized by the same steps and each
   with the same state, list and candidates. Its entries are cut at paragraph
   breaks, at line breaks inside a paragraph that is too long, and at
   character boundaries inside a line that is still too long, never inside a
   user-perceived character (an extended grapheme cluster of UAX #29, by the
   running Python's character data), a conjunct that a virama joins, CR LF or
   `[forgotten]`.

The estimates read the request document before redaction, with the
instructions and the schema; a count reads the request as sent. Nothing here
reads a file or sends anything but through the caller's `count` and `rank`.
No hook, worker or command calls this module yet (TASK-088).
"""
from dataclasses import dataclass
import json
import re
import sqlite3
import unicodedata

from . import curator_document, format2, index_io, model_prompts, state_types

LIST = 40000
FILL = 97000
UNCOUNTED = 60000
COUNTED = 99000
FALLBACK = 90000
COUNTS = 3
PROVISIONAL = 999999
# The words that rank a partial list come from the oldest turns that fit beside a full list.
RANKING = FILL - LIST
# Unicode's stream-safe form puts at most 30 marks in a row, so a conjunct's virama is looked for that far back.
_MARKS = 30
# UAX #29 classes that a general category does not show, in Unicode 12.1 to 17.0: the letters that join the
# character before them like a mark (Thai and Lao AM, the halfwidth sound marks, the Kirat Rai vowel signs), and the
# prepended signs that join the character after them.
_JOINS_BEFORE = frozenset([0x0E33, 0x0EB3, 0xFF9E, 0xFF9F, 0x16D63, 0x16D67, 0x16D68, 0x16D69, 0x16D6A])
_PREPENDED = frozenset(list(range(0x0600, 0x0606)) + [0x06DD, 0x070F, 0x0890, 0x0891, 0x08E2, 0x0D4E, 0x110BD, 0x110CD,
                       0x111C2, 0x111C3, 0x113D1, 0x1193F, 0x11941, 0x11A3A] + list(range(0x11A84, 0x11A8A)) +
                       [0x11D46, 0x11F02])
_ASCII = bytes(range(128))
_BLANK = re.compile(r'\n[ \t\r]*\n')
_LINE = re.compile(r'\n')
_EMPTY_TURNS = '<turns/>'


@dataclass(frozen=True)
class ItemList:
    form: str          # full, short or part (API-006)
    items: tuple       # the current items it carries, in their order
    candidates: tuple  # the open candidates that go with both of their items, by time and ID
    omitted: int       # open candidates left out for the budget
    after: object      # the conflict_after to record once the batch is applied (TBL-009)
    due: bool          # any form but full makes consolidation due at once


@dataclass(frozen=True)
class Request:
    source: str        # the request document, as curator_document builds it
    turns: tuple       # ((log, seq), ...) of the turns it carries, oldest first
    part: object       # None, or (part, parts) when it carries one part of one turn
    safe: int
    working: int
    counted: object    # the count that let it go, else None
    counts: int        # count calls made while sizing it


@dataclass(frozen=True)
class Plan:
    items: ItemList
    requests: tuple    # one request of whole turns, or the parts of one turn in order


def _pair(text):
    """(ASCII characters, other characters) of a text."""
    data = text.encode('utf-8', 'surrogatepass')
    ascii_count = len(data) - len(data.translate(None, _ASCII))
    return ascii_count, len(text) - ascii_count


def _add(*pairs):
    return sum(pair[0] for pair in pairs), sum(pair[1] for pair in pairs)


def _safe(pair):
    return -(-pair[0] // 2) + 2 * pair[1]


def _working(pair):
    return -(-pair[0] // 4) + pair[1]


def safe(text):
    """The safe estimate: ASCII bytes / 2, rounded up, plus 2 per other character."""
    return _safe(_pair(text))


def working(text):
    """The working estimate: ASCII bytes / 4, rounded up, plus 1 per other character."""
    return _working(_pair(text))


def fixed(instructions, schema):
    """The counts of the instructions and the schema that every request also sends."""
    return _pair(model_prompts.PROMPTS[instructions] + json.dumps(schema, ensure_ascii=False))


class _Block:
    """The counts of curator_document._block's text from its children's counts."""

    def __init__(self, tag, attributes):
        whole = curator_document._element(tag, attributes, '\x00')
        opening, closing = whole.split('\x00')
        self.edges = _add(_pair(opening), _pair(closing))
        self.empty = _pair(curator_document._element(tag, attributes))

    def pair(self, children):
        return self.total(len(children), _add(*children))

    def total(self, number, pair):
        """The counts for `number` children whose counts add up to `pair`."""
        return self.empty if not number else _add(self.edges, (number + 1, 0), pair)


def _session_attributes(session):
    return (('log', session['log']), ('host', session['host']), ('started', session['started']),
            ('ended', session['ended']))


def _turn_attributes(seq, part=None, parts=None):
    return (('seq', str(seq)), ('part', None if part is None else str(part)),
            ('parts', None if parts is None else str(parts)))


class _Frame:
    """A request without its turns: the state, the item list and the candidates."""

    def __init__(self, base, lines, listed, conflicts):
        request = _Block('request', (('kind', 'curate'), ('instructions', 'curate-2')))
        self.children = [_pair(curator_document._state(lines)), listed, conflicts]
        self.base, self.request = base, request

    def pair(self, turns):
        return _add(self.base, self.request.pair(self.children + [turns]))


def _turns_pair(sessions):
    """[(session, [turn pairs])] in order: the counts of the <turns> block."""
    blocks = [_Block('session', _session_attributes(session)).pair(pairs) for session, pairs in sessions if pairs]
    return _Block('turns', ()).pair(blocks) if blocks else _pair(_EMPTY_TURNS)


def _current_cites(layer, current):
    seen, found = set(), []
    for line in sorted(layer.lines, key=lambda v: (state_types.PARTS.index(v['part']), v['pos'], v['id'])):
        for cite in line['cites']:
            if cite in current and cite not in seen:
                seen.add(cite)
                found.append(cite)
    return found


def _conflict(candidate):
    return curator_document._element('conflict', (('id', candidate['id']), ('items', ' '.join(candidate['items'])),
                                                   ('since', candidate['at'][:10])))


def _rotation(layer, after):
    order = list(layer.candidates)
    if after is None or after not in layer.places:
        return order
    place = layer.places[after]
    start = next((index for index, c in enumerate(order) if (c['at'], c['id']) > place), len(order))
    return order[start:] + order[:start]


def choose(layer, base, *, after=None, ranked=lambda: None):
    """The item list of SPEC-015 point 10 and SPEC-143: full, short, or part.

    `ranked` gives the item IDs that the search index ranks highest for the
    batch's turns, best first, or None when the index cannot be read; it is
    asked only for a partial list.
    """
    if after is not None:
        format2._id(after, format2._CANDIDATE)
    current = {value['id']: value for value in layer.current}
    empty_turns = _pair(_EMPTY_TURNS)
    candidates = tuple(layer.candidates)
    conflicts_all = _Block('conflicts', (('omitted', '0'),)).pair([_pair(_conflict(c)) for c in candidates])
    rotated = _rotation(layer, after)
    for form in ('full', 'short'):
        _, listed = curator_document._items(list(layer.current), form)
        frame = _Frame(base, layer.lines, _pair(listed), conflicts_all)
        if _safe(frame.pair(empty_turns)) <= LIST:
            # Every bundle goes; the last in rotation order is the one recorded.
            return ItemList(form, tuple(layer.current), candidates, 0, rotated[-1]['id'] if rotated else after,
                            form != 'full')

    rendered = {item: _pair(curator_document._item(value, 'part')[1]) for item, value in current.items()}
    items_block = _Block('items', (('form', 'part'),))
    state = _pair(curator_document._state(layer.lines))
    request = _Block('request', (('kind', 'curate'), ('instructions', 'curate-2')))
    chosen, carried, sums = [], [], {'items': (0, 0), 'conflicts': (0, 0)}

    def offer(items, candidate=None):
        new = [item for item in items if item not in chosen]
        listed = _add(sums['items'], *[rendered[item] for item in new])
        kept = len(carried) + (candidate is not None)
        known = _add(sums['conflicts'], _pair(_conflict(candidate)) if candidate is not None else (0, 0))
        conflicts = _Block('conflicts', (('omitted', str(len(candidates) - kept)),))
        children = _add(state, items_block.total(len(chosen) + len(new), listed), conflicts.total(kept, known),
                        empty_turns)
        if _safe(_add(base, request.total(4, children))) > LIST:
            return False
        chosen.extend(new)
        sums['items'] = listed
        if candidate is not None:
            carried.append(candidate)
            sums['conflicts'] = known
        return True

    for item in _current_cites(layer, current) + [item for item in layer.pinned if item in current]:
        offer([item])
    last = after
    for candidate in rotated:
        if offer([item for item in candidate['items']], candidate):
            last = candidate['id']
    ranking = ranked()
    if ranking is None:
        ranking = [value['id'] for value in layer.current]
    for item in ranking:
        if item in current:
            offer([item])
    carried.sort(key=lambda c: (c['at'], c['id']))
    return ItemList('part', tuple(current[item] for item in chosen), tuple(carried), len(candidates) - len(carried),
                    last, True)


def _ranking_text(units):
    """The text of the oldest turns whose working estimate fits in RANKING."""
    texts, used = [], (0, 0)
    for _, turn in units:
        for entry in turn['entries']:
            text = entry['text']
            pair = _pair(text)
            if _working(_add(used, pair)) <= RANKING:
                texts.append(text)
                used = _add(used, pair)
                continue
            low, high = 0, len(text)
            while low < high:
                middle = (low + high + 1) // 2
                if _working(_add(used, _pair(text[:middle]))) <= RANKING:
                    low = middle
                else:
                    high = middle - 1
            texts.append(text[:low])
            return '\n'.join(texts)
    return '\n'.join(texts)


def _rank(rank, units):
    if rank is None:
        return None
    try:
        return list(rank(_ranking_text(units)))
    except (index_io.IndexUnavailable, sqlite3.Error, OSError):
        return None


def _boundary(text, index):
    """Whether a cut before text[index] leaves every user-perceived character whole."""
    if index <= 0 or index >= len(text):
        return True
    after, before = text[index], text[index - 1]
    code, previous = ord(after), ord(before)
    # Marks include variation selectors and the keycap; then joiners, skin tones, tags, Hangul V and T jamo, the
    # letters that join like marks and the prepended signs.
    if (unicodedata.category(after)[0] == 'M' or after in '\u200c\u200d' or before == '\u200d' or
            0x1F3FB <= code <= 0x1F3FF or 0xE0020 <= code <= 0xE007F or 0x1160 <= code <= 0x11FF or
            0xD7B0 <= code <= 0xD7FF or code in _JOINS_BEFORE or previous in _PREPENDED or
            before == '\r' and after == '\n'):
        return False
    # A leading Hangul jamo joins the leading jamo or the syllable after it.
    if _leading(previous) and (_leading(code) or 0xAC00 <= code <= 0xD7A3):
        return False
    if unicodedata.category(after)[0] == 'L' and _virama(text, index):
        return False
    if 0x1F1E6 <= code <= 0x1F1FF and 0x1F1E6 <= previous <= 0x1F1FF:
        run = 0
        while index - run - 1 >= 0 and 0x1F1E6 <= ord(text[index - run - 1]) <= 0x1F1FF:
            run += 1
        if run % 2:
            return False
    marker = curator_document.FORGOTTEN
    return not any(text.startswith(marker, start) for start in range(max(0, index - len(marker) + 1), index))


def _leading(code):
    return 0x1100 <= code <= 0x115F or 0xA960 <= code <= 0xA97C


def _virama(text, index):
    """Whether a virama ends the marks before text[index], joining the letter there into a conjunct."""
    for position in range(index - 1, max(-1, index - 1 - _MARKS), -1):
        character = text[position]
        if unicodedata.combining(character) == 9:
            return True
        if unicodedata.category(character)[0] != 'M' and character != '\u200d':
            return False
    return False


def _cut(text, fits):
    """The longest prefix that fits and ends at a character boundary; 0 when none does."""
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if fits(text[:middle]):
            low = middle
        else:
            high = middle - 1
    while low > 0 and not _boundary(text, low):
        low -= 1
    return low


def _shorter(text, fits):
    """The longest prefix that fits: up to a paragraph break, else a line break, else a character boundary."""
    for pattern in (_BLANK, _LINE):
        ends = [end for end in _ends(text, pattern) if end < len(text)]
        low, high = 0, len(ends)
        while low < high:
            middle = (low + high) // 2
            if fits(text[:ends[middle]]):
                low = middle + 1
            else:
                high = middle
        if low:
            return ends[low - 1]
    return _cut(text, fits)


def _ends(text, pattern):
    return [match.end() for match in pattern.finditer(text)]


def _split(text, ends):
    pieces, start = [], 0
    for end in ends:
        if start < end < len(text):
            pieces.append(text[start:end])
            start = end
    pieces.append(text[start:])
    return pieces


class _Part:
    """One part of one turn: pieces of its entries, grouped back by entry."""

    def __init__(self, frame, session, turn, parts):
        self.frame, self.session, self.turn, self.parts = frame, session, turn, parts
        self.entries, self.cache = [], {}
        for entry in turn['entries']:
            whole = curator_document._element('entry', (('id', entry['id']), ('speaker', entry['speaker']),
                                                        ('at', entry['at'])), '\x00')
            opening, closing = whole.split('\x00')
            self.entries.append(_add(_pair(opening), _pair(closing)))

    def pair(self, number, pieces):
        texts = {}
        for index, text in pieces:
            pair = self.cache.get(text)
            if pair is None:
                pair = self.cache[text] = _pair(curator_document._text(text))
            texts[index] = _add(texts.get(index, self.entries[index]), pair)
        turn = _Block('turn', _turn_attributes(self.turn['seq'], number, self.parts)).pair(
            [texts[index] for index in sorted(texts)])
        return self.frame.pair(_turns_pair([(self.session, [turn])]))

    def pieces(self, number):
        """The turn's entries cut so that each piece fits a part alone by the safe estimate."""
        found = []
        for index, entry in enumerate(self.turn['entries']):
            def fits(text, index=index):
                return _safe(self.pair(number, [(index, text)])) <= FALLBACK
            text = entry['text']
            if not text:
                found.append((index, text))
                continue
            for paragraph in _split(text, _ends(text, _BLANK)):
                if fits(paragraph):
                    found.append((index, paragraph))
                    continue
                for line in _split(paragraph, _ends(paragraph, _LINE)):
                    while line:
                        if fits(line):
                            found.append((index, line))
                            break
                        size = _cut(line, fits) or 1
                        found.append((index, line[:size]))
                        line = line[size:]
        return found


def _drop(chosen, rest, measure, target):
    """Move the newest pieces back to the queue until the measure is at most the target."""
    while len(chosen) > 1 and measure(chosen) > target:
        rest.insert(0, chosen.pop())
    return measure(chosen) <= target


def _size(queue, measure_working, measure_safe, count, document, shrink=None):
    """API-009's steps 2 to 5 for one request: (chosen, rest, counted, counts), or None.

    Units are whole turns, or pieces of one turn that `shrink` can cut smaller.
    None means that the first whole turn cannot go alone: it goes in parts.
    """
    chosen, rest = [queue[0]], list(queue[1:])
    while rest and measure_working(chosen + rest[:1]) < FILL:
        chosen.append(rest.pop(0))
    if measure_working(chosen) >= FILL:
        return None
    counts = 0
    if measure_safe(chosen) <= UNCOUNTED:
        return chosen, rest, None, counts
    while True:
        # A request that lost turns after a high count is counted again, whatever its safe estimate.
        tokens = count(document(chosen))
        counts += 1
        if tokens is None:
            break
        if tokens <= COUNTED:
            return chosen, rest, tokens, counts
        if counts == COUNTS:
            break
        excess = tokens - COUNTED
        size, cut = measure_working(chosen), excess - (-excess // 10)
        if size - cut <= measure_working([]):
            # No request is that much lower: the count reads these turns far denser than the
            # working estimate, so they lose the same share of it as the excess and a tenth more are of the count.
            cut = -(-size * cut // tokens)
        target = size - cut
        if not _drop(chosen, rest, measure_working, target):
            if shrink is None:
                return None
            smaller = shrink(chosen[0], lambda piece: measure_working([piece]) <= target)
            if smaller is None:
                break
            chosen, rest = [smaller[0]], [smaller[1]] + rest
    chosen, rest = [], list(queue)
    while rest and measure_safe(chosen + rest[:1]) <= FALLBACK:
        chosen.append(rest.pop(0))
    if not chosen:
        return None
    return chosen, rest, None, counts


def _source(layer, listed, sessions):
    return curator_document.curate(lines=list(layer.lines), items=list(listed.items), form=listed.form,
                                   sessions=sessions, candidates=list(listed.candidates), omitted=listed.omitted)


def _request(source, turns, part, counted, counts):
    return Request(source, tuple(turns), part, safe(source), working(source), counted, counts)


def plan(layer, sessions, *, schema, count, after=None, rank=None, instructions='curate-2'):
    """Size the next curate request of a batch.

    `sessions` are curator_document sessions whose turns are unprocessed, in
    time order; `count(source)` gives API-009's count of a request document, or
    None when counting fails; `rank(text)` gives item IDs best first by the
    search index, and may raise when the index cannot be read.
    """
    if instructions != 'curate-2':
        raise ValueError('invalid curate request instructions')
    if not callable(count) or rank is not None and not callable(rank):
        raise TypeError('memory request counting required')
    units = [(session, turn) for session in sessions for turn in session['turns']]
    if not units:
        raise ValueError('no unprocessed turns')
    base = fixed(instructions, schema)
    listed = choose(layer, base, after=after, ranked=lambda: _rank(rank, units))
    _, items_text = curator_document._items(list(listed.items), listed.form)
    conflicts_text = curator_document._conflicts(list(listed.candidates), listed.omitted,
                                                 {value['id'] for value in listed.items})
    frame = _Frame(base, layer.lines, _pair(items_text), _pair(conflicts_text))
    rendered = [_pair(curator_document._turn(turn, set())) for _, turn in units]
    position = {id(turn): index for index, (_, turn) in enumerate(units)}

    def grouped(chosen):
        sessions_found = []
        for session, turn in chosen:
            if not sessions_found or sessions_found[-1][0] is not session:
                sessions_found.append((session, []))
            sessions_found[-1][1].append(turn)
        return sessions_found

    def whole_pair(chosen):
        return frame.pair(_turns_pair([(session, [rendered[position[id(turn)]] for turn in turns])
                                       for session, turns in grouped(chosen)]))

    def whole_source(chosen):
        return _source(layer, listed, [dict(session, turns=list(turns)) for session, turns in grouped(chosen)])

    sized = _size(units, lambda c: _working(whole_pair(c)), lambda c: _safe(whole_pair(c)), count, whole_source)
    if sized is not None:
        chosen, _, counted, counts = sized
        return Plan(listed, (_request(whole_source(chosen), [(s['log'], t['seq']) for s, t in chosen], None,
                                      counted, counts),))
    session, turn = units[0]
    return Plan(listed, _split_turn(layer, listed, frame, session, turn, count))


def _split_turn(layer, listed, frame, session, turn, count):
    """The parts of one turn: each sized by the same steps, with the same list."""
    # Parts are sized and counted with six-digit numbers, wider than any final number, so
    # each final document is no longer than the one that was measured.
    provisional = PROVISIONAL
    part = _Part(frame, session, turn, provisional)
    queue, sized = part.pieces(provisional), []
    while queue:
        number = len(sized) + 1

        def shrink(piece, fits):
            index, text = piece
            size = _shorter(text, lambda prefix: fits((index, prefix)))
            return None if size == 0 else ((index, text[:size]), (index, text[size:]))

        def document(pieces, number=number):
            return _part_source(layer, listed, session, turn, pieces, number, provisional)
        result = _size(queue, lambda c: _working(part.pair(number, c)), lambda c: _safe(part.pair(number, c)),
                       count, document, shrink)
        if result is None:
            # A piece fits alone by the safe estimate, so this cannot happen; refuse rather than loop.
            raise ValueError('memory request turn cannot be cut')
        chosen, queue, counted, counts = result
        sized.append((chosen, counted, counts))
    if len(sized) == 1:
        chosen, counted, counts = sized[0]
        whole = dict(turn, entries=_entries(turn, chosen))
        return (_request(_source(layer, listed, [dict(session, turns=[whole])]), [(session['log'], turn['seq'])],
                         None, counted, counts),)
    return tuple(_request(_part_source(layer, listed, session, turn, chosen, number, len(sized)),
                          [(session['log'], turn['seq'])], (number, len(sized)), counted, counts)
                 for number, (chosen, counted, counts) in enumerate(sized, 1))


def _entries(turn, pieces):
    texts = {}
    for index, text in pieces:
        texts[index] = texts.get(index, '') + text
    return [dict(turn['entries'][index], text=texts[index]) for index in sorted(texts)]


def _part_source(layer, listed, session, turn, pieces, number, parts):
    value = dict(seq=turn['seq'], part=number, parts=parts, entries=_entries(turn, pieces))
    return _source(layer, listed, [dict(session, turns=[value])])
