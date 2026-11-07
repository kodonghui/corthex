"""The quote check of SPEC-016: a quote's words found in a stored entry text.

Both sides are compared as the request showed them: characters that XML
cannot hold as U+FFFD, then NFC, then each run of white space, line breaks
included, as one space; the words also lose the white space at both ends. The
words as given are tried first, then with the request's escapes undone. The
first place found that touches no forgotten range gives the quote's start and
end in the stored text (TBL-012). A place counts only when that range of the
stored text, compared the same way, is exactly the words; a place that begins
or ends inside a cluster that NFC changed is narrowed within the cluster. Text
that redaction replaced in the request is not in the stored text, so a quote
of the replacement is never found.
"""
import bisect
import re
import unicodedata

from . import curator_document

_SPACE = re.compile(r'\s+')
_ESCAPE = re.compile('&(amp|lt|gt|quot);')
_UNESCAPED = {'amp': '&', 'lt': '<', 'gt': '>', 'quot': '"'}
# No character below U+0300 and no precomposed Hangul syllable is the second
# part of a canonical composition, and all of them are starters. A cut before
# one of them therefore never changes NFC, so runs of other characters can be
# normalized as pieces, each with the character before it.
_JOINING = re.compile('[^\u0000-\u02ff\uac00-\ud7a3]+')
# At most this many stored ranges are tried for one place inside the clusters
# at its two ends; past it only the whole clusters are.
_NARROWING = 256


def _clusters(text, start, end):
    """Split a piece that NFC changes before each starter that joins nothing before it."""
    first = start
    for index in range(start + 1, end):
        character = text[index]
        if unicodedata.combining(character) == 0:
            cluster = unicodedata.normalize('NFC', text[first:index])
            if unicodedata.normalize('NFC', text[first:index] + character) == cluster + character:
                yield first, index, cluster
                first = index
    yield first, end, unicodedata.normalize('NFC', text[first:end])


def _pieces(text):
    """(stored start, stored end, NFC text) in order, covering the whole text."""
    used = 0
    for match in _JOINING.finditer(text):
        start = max(match.start() - 1, used)
        if used < start:
            yield used, start, text[used:start]
        piece = text[start:match.end()]
        if unicodedata.is_normalized('NFC', piece):
            yield start, match.end(), piece
        else:
            yield from _clusters(text, start, match.end())
        used = match.end()
    if used < len(text):
        yield used, len(text), text[used:]


class Prepared:
    """The compared form of one stored text, with a map back to its positions."""

    def __init__(self, text):
        if not isinstance(text, str):
            raise ValueError('invalid stored text')
        self.text = text
        normal = curator_document.INVALID.sub('\ufffd', text)
        # low[i] and high[i]: the stored range that character i of the NFC text
        # came from; None when NFC changed nothing and the map is the identity.
        self._low = self._high = None
        if not unicodedata.is_normalized('NFC', normal):
            parts, self._low, self._high = [], [], []
            for start, end, piece in _pieces(normal):
                parts.append(piece)
                if piece == normal[start:end]:
                    self._low.extend(range(start, end))
                    self._high.extend(range(start + 1, end + 1))
                else:
                    self._low.extend([start] * len(piece))
                    self._high.extend([end] * len(piece))
            normal = ''.join(parts)
        # Each run of white space becomes one space at form position `at`.
        self._runs, removed = [], 0
        for match in _SPACE.finditer(normal):
            self._runs.append((match.start() - removed, match.start(), match.end()))
            removed += match.end() - match.start() - 1
        self._at = [run[0] for run in self._runs]
        self.form = _SPACE.sub(' ', normal)

    def _normal(self, position, end):
        index = bisect.bisect_right(self._at, position) - 1
        if index < 0:
            return position
        at, start, stop = self._runs[index]
        if position == at:
            return stop - 1 if end else start
        return stop + position - at - 1

    def spans(self, start, end):
        """The stored ranges that the compared form's [start, end) may come from.

        Each character of a cluster that NFC changed maps to the whole cluster,
        so a place that begins or ends inside one may come from part of it:
        every start in the first cluster is paired with every end in the last.
        """
        first, last = self._normal(start, False), self._normal(end - 1, True)
        if self._low is None:
            return [(first, last + 1)]
        starts = range(self._low[first], self._high[first])
        ends = range(self._high[last], self._low[last], -1)
        if len(starts) * len(ends) > _NARROWING:
            starts, ends = starts[:1], ends[:1]
        return [(low, high) for low in starts for high in ends if low < high]


def compared(words):
    """The words as the check compares them, without white space at either end."""
    return Prepared(words).form.strip(' ')


def find(stored, words, forgotten=()):
    """Return the quote's (start, end) in the stored text, or None."""
    prepared = stored if isinstance(stored, Prepared) else Prepared(stored)
    if not isinstance(words, str):
        return None
    tried = [words]
    unescaped = _ESCAPE.sub(lambda match: _UNESCAPED[match.group(1)], words)
    if unescaped != words:
        tried.append(unescaped)
    for candidate in tried:
        target = compared(candidate)
        position = prepared.form.find(target) if target else -1
        while position >= 0:
            for start, end in prepared.spans(position, position + len(target)):
                if (Prepared(prepared.text[start:end]).form == target and
                        not any(start < high and low < end for low, high in forgotten)):
                    return start, end
            position = prepared.form.find(target, position + 1)
    return None
