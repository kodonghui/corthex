"""TBL-019 to TBL-022: the rebuildable search index, words-1 and BM25 by words.

The index is derived data in projects/<project>/index.db. It is never migrated
or synced: a file SQLite cannot read, or one of another version, schema, word
splitting, embedding model or vector length, is deleted and built again from the
canonical items under the project's layer lease. `sync` makes the rows match
the items again, and `put_vectors` writes the embeddings (TBL-021) that the
memory worker's step 6 makes (TASK-082); an item without one is found by words
only. No hook or command calls this module yet.
"""
from collections import Counter
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import unicodedata

from . import configuration, files, format2, item_io

VERSION = 2
WORDS = 'words-1'
K1, B = 1.2, 0.75
NAMES = ('embedding_model', 'embedding_dims', 'words', 'built')
# The packaged copy of docs/05-erd/memory-index.sql; a test keeps them byte-identical.
DDL = Path(__file__).with_name('memory-index.sql')
# SQLite's own files beside the index, removed before the index itself.
_SIDES = ('-wal', '-shm', '-journal')
_IDENTIFIER = re.compile(r'[A-Za-z0-9_./-]+')
_LETTER = re.compile(r'[A-Za-z]')
_SIGN = re.compile(r'[0-9_./]')
_CAPITAL = re.compile(r'[A-Z]')
# White space and ASCII punctuation always end a run, so the slower loop sees only the rest.
_SEPARATORS = re.compile(r'[\s!-/:-@\[-`{-~]+')
# Step 4: Hangul, CJK ideographs, Hiragana and Katakana give pairs of characters.
_PAIRED = ((0x1100, 0x11FF), (0x3130, 0x318F), (0xAC00, 0xD7A3), (0x3400, 0x4DBF),
           (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x3040, 0x30FF))
_SEPARATE, _ALPHANUMERIC, _PAIR, _COMBINING = range(4)
_classes = {}
_expected = None


class IndexUnavailable(RuntimeError):
    """The index file is not a regular file inside the store."""


def _class(character):
    """How a character takes part in words; a bounded cache keeps long texts fast."""
    kind = _classes.get(character)
    if kind is None:
        code, category = ord(character), unicodedata.category(character)
        kind = (_PAIR if any(low <= code <= high for low, high in _PAIRED) else
                _ALPHANUMERIC if category[0] == 'L' or category == 'Nd' else
                _COMBINING if category[0] == 'M' else _SEPARATE)
        if len(_classes) < 65536:
            _classes[character] = kind
    return kind


def _identifiers(text):
    found = []
    for match in _IDENTIFIER.finditer(text):
        word = match.group().rstrip('./-')
        # A letter or mark of another script beside the run makes it part of a longer
        # word, as in CAFÉ; Hangul and the other paired scripts do not, as in REQ-001을.
        if (2 <= len(word) <= 100 and _LETTER.search(word) and (_SIGN.search(word) or _CAPITAL.search(word, 1)) and
                not any(_class(text[index]) in (_ALPHANUMERIC, _COMBINING)
                        for index in (match.start() - 1, match.end()) if 0 <= index < len(text))):
            found.append(word.lower())
    return found


def identifiers(text):
    """Step 2 of words-1 alone: the identifiers of text, lower-cased, in order."""
    if not isinstance(text, str):
        raise TypeError('text required')
    return _identifiers(unicodedata.normalize('NFC', text))


def words(text):
    """Split text into words the words-1 way (stage 06), identifiers first."""
    if not isinstance(text, str):
        raise TypeError('text required')
    text = unicodedata.normalize('NFC', text)
    # Step 2 sees the capitals, so it runs before lower-casing.
    found = _identifiers(text)
    for chunk in _SEPARATORS.split(text.lower()):
        run, kind = [], _SEPARATE
        for character in chunk + ' ':
            current = _class(character)
            if current == _COMBINING and kind == _ALPHANUMERIC:
                # A combining mark stays in the run it follows, as in i̇stanbul.
                current = _ALPHANUMERIC
            if current != kind:
                if kind == _ALPHANUMERIC and len(run) <= 100:
                    found.append(''.join(run))
                elif kind == _PAIR:
                    found.extend(''.join(run[index:index + 2]) for index in range(max(len(run) - 1, 1)))
                run, kind = [], current
            if current in (_ALPHANUMERIC, _PAIR):
                run.append(character)
    return found


def item_words(item):
    """An item's words: from its kind, title, text and the words of its quotes."""
    found = words(item['kind']) + words(item['title']) + words(item['text'])
    for quote in item['quotes']:
        found.extend(words(quote['words']))
    return found


def schema():
    """The rows of sqlite_master that memory-index.sql makes, sorted."""
    global _expected
    if _expected is None:
        connection = sqlite3.connect(':memory:', isolation_level=None)
        try:
            connection.executescript(DDL.read_text(encoding='utf-8'))
            _expected = _schema(connection)
        finally:
            connection.close()
    return _expected


def _schema(connection):
    return sorted(connection.execute('SELECT type, name, tbl_name, sql FROM sqlite_master').fetchall(),
                  key=lambda row: tuple('' if value is None else value for value in row))


def connect(path, create=False, timeout=1.0):
    """Open an index with the per-connection pragmas; never create one unless asked."""
    uri = Path(os.path.abspath(str(path))).as_uri() + ('?mode=rwc' if create else '?mode=rw')
    connection = sqlite3.connect(uri, uri=True, timeout=timeout, isolation_level=None)
    try:
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute('PRAGMA secure_delete = ON')
    except BaseException:
        connection.close()
        raise
    return connection


def state(connection, *, model, dims, pages=True):
    """None when the index can be used, otherwise why it must be built again.

    SQLite's quick check reads every page, so a damaged table that the schema
    and index_meta do not show is found here rather than by a later search.
    Recall, within the prompt hook's time, leaves it out with `pages=False`; a
    damaged page then fails the read that meets it.
    """
    try:
        if connection.execute('PRAGMA user_version').fetchone()[0] != VERSION:
            return 'version'
        if _schema(connection) != schema():
            return 'schema'
        meta = dict(connection.execute('SELECT name, value FROM index_meta').fetchall())
        if pages and connection.execute('PRAGMA quick_check(1)').fetchall() != [('ok',)]:
            return 'malformed'
    except sqlite3.DatabaseError:
        return 'malformed'
    if set(meta) - set(NAMES) or set(NAMES[:3]) - set(meta):
        return 'malformed'
    if meta['words'] != WORDS:
        return 'words'
    if meta['embedding_model'] != model or meta['embedding_dims'] != str(dims):
        return 'embedding'
    return None if 'built' in meta else 'building'


def _row(item):
    """An item's index_items fields after its ID, and how often each of its words occurs."""
    found = item_words(item)
    deciding = item['quotes'][0]
    return (item['kind'], item['status'], deciding['speaker'], deciding['said'], len(found)), dict(Counter(found))


def put(connection, items):
    """Write the word rows of items, keeping the vector of an item already indexed."""
    _write(connection, [(item['id'],) + _row(item) for item in items])


def _write(connection, rows, stale=(), gone=()):
    """In one transaction: write rows, delete the vectors of `stale` and every row of `gone`."""
    connection.execute('BEGIN IMMEDIATE')
    try:
        for item, fields, counts in rows:
            if not connection.execute('UPDATE index_items SET kind = ?, status = ?, speaker = ?, said = ?, terms = ? '
                                      'WHERE item = ?', fields + (item,)).rowcount:
                connection.execute('INSERT INTO index_items VALUES (?, ?, ?, ?, ?, ?)', (item,) + fields)
            connection.execute('DELETE FROM index_terms WHERE item = ?', (item,))
            connection.executemany('INSERT INTO index_terms VALUES (?, ?, ?)',
                                   [(term, item, count) for term, count in sorted(counts.items())])
        connection.executemany('DELETE FROM index_vectors WHERE item = ?', [(item,) for item in stale])
        connection.executemany('DELETE FROM index_items WHERE item = ?', [(item,) for item in gone])
        connection.execute('COMMIT')
    except BaseException:
        _rollback(connection)
        raise


def rows(connection):
    """What the index holds, read at once: ({item: (fields, counts)}, the items that have a vector)."""
    connection.execute('BEGIN')
    try:
        found = {row[0]: (tuple(row[1:]), {}) for row in connection.execute(
            'SELECT item, kind, status, speaker, said, terms FROM index_items')}
        for item, term, count in connection.execute('SELECT item, term, count FROM index_terms'):
            if item in found:
                found[item][1][term] = count
        vectors = {item for (item,) in connection.execute('SELECT item FROM index_vectors')}
    finally:
        if connection.in_transaction:
            connection.execute('COMMIT')
    return found, vectors


def sync(connection, items):
    """Make the rows match the canonical items: (the items written again, the items whose rows went).

    An item whose row is missing or differs is written again, losing its vector
    when its words changed; the rows of every item not given are deleted, and
    the write-ahead log emptied as after a forget.
    """
    found, _ = rows(connection)
    wanted = {item['id']: _row(item) for item in items}
    changed = [(item,) + value for item, value in sorted(wanted.items()) if found.get(item) != value]
    stale = [item for item, _, counts in changed if item in found and found[item][1] != counts]
    gone = sorted(set(found) - set(wanted))
    if changed or gone:
        _write(connection, changed, stale, gone)
    if gone:
        connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    return [item for item, _, _ in changed], gone


def put_vectors(connection, vectors):
    """Write [(item, vector)] for the items that the index holds, in one transaction; the items written."""
    written = []
    connection.execute('BEGIN IMMEDIATE')
    try:
        for item, vector in vectors:
            if connection.execute('INSERT OR REPLACE INTO index_vectors SELECT item, ? FROM index_items '
                                  'WHERE item = ?', (vector, item)).rowcount:
                written.append(item)
        connection.execute('COMMIT')
    except BaseException:
        _rollback(connection)
        raise
    return written


def _rollback(connection):
    # A failed BEGIN leaves no transaction, and its error must stay the one raised.
    if connection.in_transaction:
        connection.execute('ROLLBACK')


def delete(connection, items, forget=False):
    """Delete every row of the items; a forget also empties the write-ahead log.

    Returns whether the checkpoint moved and truncated the whole log; a reader
    can hold it back, and the caller then tries again before it reports success.
    """
    connection.execute('BEGIN IMMEDIATE')
    try:
        connection.executemany('DELETE FROM index_items WHERE item = ?', [(item,) for item in items])
        connection.execute('COMMIT')
    except BaseException:
        _rollback(connection)
        raise
    if not forget:
        return True
    busy, _, _ = connection.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()
    return busy == 0


def search(connection, text, limit=None):
    """BM25 by words over items of every status: [(item, score)], best first, then by ID.

    k1 1.2 and b 0.75; a word's weight is ln(1 + (N - n + 0.5) / (n + 0.5)) and an
    item's length its number of words. Each distinct word of the request counts once.
    """
    query = sorted(set(words(text)))
    if not query:
        return []
    # One read transaction, so every count comes from the same snapshot.
    connection.execute('BEGIN')
    try:
        total, length = connection.execute('SELECT count(*), coalesce(sum(terms), 0) FROM index_items').fetchone()
        found = {term: connection.execute('SELECT index_terms.item, count, terms FROM index_terms JOIN index_items '
                                          'ON index_items.item = index_terms.item WHERE term = ?', (term,)).fetchall()
                 for term in query}
    finally:
        if connection.in_transaction:
            connection.execute('COMMIT')
    if not total:
        return []
    average, scores = length / total, {}
    for term, rows in found.items():
        if not rows:
            continue
        weight = math.log(1 + (total - len(rows) + 0.5) / (len(rows) + 0.5))
        for item, count, terms in rows:
            scores[item] = scores.get(item, 0.0) + weight * count * (K1 + 1) / (
                count + K1 * (1 - B + B * terms / average))
    ranked = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    return ranked if limit is None else ranked[:limit]


def _regular(memory, path):
    """The file's lstat, None when absent; a link or another kind refuses."""
    info = memory.fence.check(path)
    if info is not None and not stat.S_ISREG(info.st_mode):
        raise IndexUnavailable()
    return info


def open_index(memory, root, timeout=1.0):
    """Open the project's index to read and write, or None when it is missing.

    `timeout` bounds SQLite's wait for a lock that another connection holds.
    """
    path = Path(root) / 'index.db'
    for name in ('index.db',) + tuple('index.db' + side for side in _SIDES):
        _regular(memory, Path(root) / name)
    if _regular(memory, path) is None:
        return None
    return connect(path, timeout=timeout)


def rebuild(memory, root, expected, deadline, *, model, dims, when):
    """Delete the project's index and build it again from its canonical items.

    The caller holds the project's layer lease; expected is its fence proof. A
    reader that opens the file meanwhile finds no `built` and reads nothing.
    """
    root = Path(root)
    if not isinstance(model, str) or not model or not configuration.integer(dims) or dims <= 0:
        raise ValueError('invalid embedding settings')
    format2._time(when)
    check, _ = item_io._checked(memory, root, expected, deadline)
    items = item_io._items(memory, root, deadline, check)
    path = root / 'index.db'
    # Side files first: a log left beside a new index would be read into it.
    for name in tuple('index.db' + side for side in _SIDES) + ('index.db',) + tuple('index.db' + side for side in _SIDES):
        if _regular(memory, root / name) is not None:
            files._unlink(root / name, check)
    check()
    if _regular(memory, path) is not None:
        raise IndexUnavailable()
    connection = connect(path, create=True)
    try:
        connection.executescript(DDL.read_text(encoding='utf-8'))
        connection.execute('BEGIN IMMEDIATE')
        connection.executemany('INSERT INTO index_meta VALUES (?, ?)',
                               [('embedding_model', model), ('embedding_dims', str(dims)), ('words', WORDS)])
        connection.execute('COMMIT')
        check()
        put(connection, items)
        check()
        connection.execute("INSERT INTO index_meta VALUES ('built', ?)", (when,))
        connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    finally:
        connection.close()
    check()
    return len(items)


def ensure(memory, root, expected, deadline, *, model, dims, when):
    """Build the index again when it is missing, unreadable or obsolete.

    Returns None when the existing index was kept, otherwise the reason it was
    built again: missing, malformed, version, schema, words, embedding or building.
    """
    root = Path(root)
    item_io._checked(memory, root, expected, deadline)
    reason = 'missing'
    try:
        connection = open_index(memory, root)
    except sqlite3.DatabaseError:
        connection, reason = None, 'malformed'
    if connection is not None:
        try:
            reason = state(connection, model=model, dims=dims)
        finally:
            connection.close()
        if reason is None:
            return None
    rebuild(memory, root, expected, deadline, model=model, dims=dims, when=when)
    return reason

