"""Curator request documents (API-006, API-007, API-008) from parsed records.

Pure: it reads no file and sends nothing. Callers pass the TBL-013 validity
view's lines, current items, open conflict candidates and grouped raw turns.
Line history, run logs, revision fences, counters and showing counts are never
inputs, so no request can carry them. Every text is escaped, and characters
that XML 1.0 cannot hold show as U+FFFD, so no text of a turn can open or close
a tag. model_request.document parses the result again and redacts every field
with the keys configured when it is sent.
"""
import re

from . import configuration, conflict_types, curation, diagnostics, format2, item_types, state_types

FORMS = ('full', 'short', 'part')
FORGOTTEN = '[forgotten]'
# Outside the XML 1.0 Char production: C0 controls other than tab, LF and CR,
# surrogate code points, U+FFFE and U+FFFF. The controls are listed one by one
# and every code point is written as an escape.
INVALID = re.compile(r'[\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e\x0f\x10\x11\x12\x13\x14\x15'
                     r'\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f\ud800-\udfff\ufffe\uffff]')


def _text(value):
    if not isinstance(value, str):
        raise ValueError('invalid curator document text')
    value = INVALID.sub('\ufffd', value)
    return value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _element(tag, attributes, content=None):
    pairs = ''.join(' %s="%s"' % (name, _text(value).replace('"', '&quot;'))
                    for name, value in attributes if value is not None)
    if content is None:
        return '<%s%s/>' % (tag, pairs)
    return '<%s%s>%s</%s>' % (tag, pairs, content, tag)


def _block(tag, attributes, children):
    if not children:
        return _element(tag, attributes)
    return _element(tag, attributes, '\n' + '\n'.join(children) + '\n')


def entry_text(entry):
    """An entry's text as requests show it: each forgotten range is [forgotten]."""
    text = entry.get('text', '')
    if not isinstance(text, str):
        raise ValueError('invalid entry text')
    merged = []
    for start, end in sorted(tuple(pair) for pair in entry.get('forgotten', ())):
        if not 0 <= start < end <= len(text):
            raise ValueError('invalid forgotten range')
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    pieces, used = [], 0
    for start, end in merged:
        pieces.extend((text[used:start], FORGOTTEN))
        used = end
    pieces.append(text[used:])
    return ''.join(pieces)


def session(log, entries, after=0):
    """One session of a raw log file: its turns after `after`, with boundary times.

    `entries` are the file's parsed TBL-007 entries in seq order. Entries with
    a seq above `after` are unprocessed and grouped by their turn; `started` is
    the first start boundary and `ended` the end boundary that closes the file.
    """
    format2._id(log, diagnostics.LOG)
    if not configuration.integer(after) or after < 0:
        raise ValueError('invalid processed count')
    started = ended = None
    turns, last = {}, 0
    for entry in entries:
        if not isinstance(entry, dict) or not configuration.integer(entry.get('seq')) or entry['seq'] <= last:
            raise ValueError('raw entries out of order')
        last = entry['seq']
        kind = entry.get('kind')
        if kind == 'start' and started is None:
            started = entry['at']
        ended = entry['at'] if kind == 'end' else None
        if kind in ('prompt', 'answer') and entry['seq'] > after:
            turns.setdefault(entry['turn'], []).append(
                dict(id=entry['id'], speaker=entry['speaker'], at=entry['at'], text=entry_text(entry)))
    return dict(log=log, host=log.rsplit('-', 1)[0], started=started, ended=ended,
                turns=[dict(seq=seq, entries=group) for seq, group in sorted(turns.items())])


def _entry(value, seen):
    curation._shape(value, 'id speaker at text')
    format2._id(value['id'], item_types.ENTRY)
    if value['id'] in seen:
        raise ValueError('duplicate request entry')
    seen.add(value['id'])
    curation._choice(value['speaker'], {'user', 'agent'})
    format2._time(value['at'])
    return _element('entry', (('id', value['id']), ('speaker', value['speaker']), ('at', value['at'])),
                    _text(value['text']))


def _turn(value, seen):
    curation._shape(value, 'seq entries', 'part parts')
    seq, part, parts = value['seq'], value.get('part'), value.get('parts')
    if not configuration.integer(seq) or seq < 1 or ('part' in value) != ('parts' in value):
        raise ValueError('invalid request turn')
    if part is not None and (not configuration.integer(part) or not configuration.integer(parts) or
                             parts < 2 or not 1 <= part <= parts):
        raise ValueError('invalid request turn part')
    if not isinstance(value['entries'], list) or not value['entries']:
        raise ValueError('invalid request turn entries')
    attributes = (('seq', str(seq)), ('part', None if part is None else str(part)),
                  ('parts', None if parts is None else str(parts)))
    return _block('turn', attributes, [_entry(entry, seen) for entry in value['entries']])


def _session(value, seen):
    curation._shape(value, 'log host started ended turns')
    format2._id(value['log'], diagnostics.LOG)
    if value['host'] != value['log'].rsplit('-', 1)[0]:
        raise ValueError('invalid request session host')
    for name in ('started', 'ended'):
        if value[name] is not None:
            format2._time(value[name])
    if not isinstance(value['turns'], list):
        raise ValueError('invalid request session turns')
    attributes = (('log', value['log']), ('host', value['host']), ('started', value['started']),
                  ('ended', value['ended']))
    return _block('session', attributes, [_turn(turn, seen) for turn in value['turns']])


def _turns(sessions):
    if not isinstance(sessions, (list, tuple)):
        raise ValueError('invalid request sessions')
    seen = set()
    # A session whose turns were all processed adds nothing to the request.
    return _block('turns', (), [text for text, value in ((_session(value, seen), value) for value in sessions)
                                if value['turns']])


def _state(lines):
    if not isinstance(lines, (list, tuple)):
        raise ValueError('invalid request state')
    lines = state_types.parse_state(item_types._raw({'lines': list(lines)}))['lines']
    lines.sort(key=lambda v: (state_types.PARTS.index(v['part']), v['pos'], v['id']))
    return _block('state', (), [
        _element('line', (('id', line['id']), ('part', line['part']), ('cites', ' '.join(line['cites']))),
                 _text(line['text'])) for line in lines])


def _item(value, form):
    value = item_types.parse_item(item_types._raw(value))
    if value['status'] != 'current':
        raise ValueError('only current items go to the curator')
    deciding = value['quotes'][0]
    attributes = (('id', value['id']), ('kind', value['kind']), ('speaker', deciding['speaker']),
                  ('date', deciding['said'][:10]))
    children = [_element('title', (), _text(value['title']))]
    if form != 'short' and form != 'part':
        children.append(_element('text', (), _text(value['text'])))
    if form is None:
        children.extend(_element('quote', (('n', str(n)), ('speaker', quote['speaker']), ('said', quote['said'])),
                                 _text(quote['words'])) for n, quote in enumerate(value['quotes'], 1))
    return value['id'], _block('item', attributes, children)


def _items(values, form):
    if form is not None and form not in FORMS or not isinstance(values, (list, tuple)):
        raise ValueError('invalid request item list')
    rendered = [_item(value, form) for value in values]
    carried = [item for item, _ in rendered]
    if len(set(carried)) != len(carried):
        raise ValueError('duplicate request item')
    return set(carried), _block('items', (('form', form),), [text for _, text in rendered])


def _conflicts(candidates, omitted, carried):
    if not configuration.integer(omitted) or omitted < 0 or not isinstance(candidates, (list, tuple)):
        raise ValueError('invalid request conflicts')
    checked = conflict_types.parse_conflicts(item_types._raw({'candidates': list(candidates)}))['candidates']
    children = []
    for candidate in checked:
        # A candidate always travels with both of its items, never with one.
        if candidate['status'] != 'open' or not set(candidate['items']) <= carried:
            raise ValueError('conflict candidate without both items')
        children.append(_element('conflict', (('id', candidate['id']), ('items', ' '.join(candidate['items'])),
                                              ('since', candidate['at'][:10]))))
    return _block('conflicts', (('omitted', str(omitted)),), children)


def _request(attributes, children):
    return _block('request', attributes, children)


def curate(*, lines, items, form, sessions, candidates=(), omitted=0):
    """The curate-2 request: state, item list, known candidates and turns."""
    if form not in FORMS:
        raise ValueError('invalid request item form')
    carried, listed = _items(items, form)
    return _request((('kind', 'curate'), ('instructions', 'curate-2')),
                    [_state(lines), listed, _conflicts(candidates, omitted, carried), _turns(sessions)])


def merge(*, group, items, candidates=(), omitted=0):
    """The merge-2 request: one kind's current items with their quotes."""
    curation._choice(group, item_types.KINDS)
    if any(not isinstance(value, dict) or value.get('kind') != group for value in items):
        raise ValueError('merge group holds another kind')
    carried, listed = _items(items, None)
    return _request((('kind', 'merge'), ('instructions', 'merge-2'), ('group', group)),
                    [listed, _conflicts(candidates, omitted, carried)])


def shorten(*, lines, items, form, candidates=(), omitted=0):
    """The state-1 request: the current state and the item list."""
    if form not in FORMS:
        raise ValueError('invalid request item form')
    carried, listed = _items(items, form)
    return _request((('kind', 'state'), ('instructions', 'state-1')),
                    [_state(lines), listed, _conflicts(candidates, omitted, carried)])
