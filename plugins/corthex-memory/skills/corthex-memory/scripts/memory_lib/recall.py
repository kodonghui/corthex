"""TASK-093: recall for a prompt (SPEC-023, SPEC-024): ranking, exclusions and the injected block.

`skipped` says whether recall skips a prompt, as a short one or a command,
counting characters in NFC. `rank` scores the current items of the session's
project that have a vector in the search index: the cosine of the prompt's
vector and the item's, plus 0.1 times the share of the prompt's identifiers
that are among the item's words. It leaves out the pinned items that the
session's latest start summary showed and the items that its last three
prompts injected (TBL-011), and reads the files of the best items, so that an
item that the index still holds as current but that is no longer current, or
that a tombstone names, is never injected (REQ-037). The five best eligible
items are the line's candidates, also below the threshold; those at or above
it are injected, best first, and dropped from the end until the safe estimate
of the whole block is under 600 tokens.

It reads the index, the injection log and the item files without a lease, as
stage 05 lets a reader, and writes nothing: the prompt hook prints the block
and appends the injection log line (TASK-094). The index's check and its rows
come from one read, and a file that another process is replacing on Windows
is read again within the deadline, as the start summary reads. Nothing calls
this module before the 0.3.0 activation.
"""
from collections import Counter
from dataclasses import dataclass
import math
import os
import sqlite3
import struct
import unicodedata

from . import base, clock, files, index_io, injection_log, item_types, locks, raw_log, request_budget, start_memory

BOOST = 0.1        # the most that the prompt's identifiers add to a score
ITEMS = injection_log.CANDIDATES  # the most items that one prompt injects, and the candidates of its line
TOKENS = 600       # the block's safe estimate stays under this
PROMPTS = 3        # the last prompts of the session whose injected items are left out
TERMS = 500        # identifiers per query, under SQLite's oldest limit of 999 variables
EVERY = 512        # vectors scored between two looks at the deadline
LOCK_MARGIN = 0.005  # seconds that SQLite's wait for a lock goes past the deadline


@dataclass(frozen=True)
class Recall:
    outcome: str            # 'injected', 'below', 'no-threshold', 'no-index' or 'late'
    block: str = ''         # the recall block, empty unless items are injected
    items: tuple = ()       # the injected items' IDs, best first
    scores: tuple = ()      # their scores, in the same order
    candidates: tuple = ()  # (item, score) of the five best eligible items, also below the threshold


def skipped(prompt, skip):
    """'command' or 'short' for a prompt that recall skips, else None (SPEC-023).

    The prompt is the redacted one; it is trimmed and put in NFC before its
    characters are counted, so that a prompt pasted in NFD counts as it reads.
    """
    text = unicodedata.normalize('NFC', prompt).strip()
    if text[:1] == '/' and text[1:2].isalpha():
        return 'command'
    if len(text) < skip:
        return 'short'
    return None


def rank(memory, project, host, session, prompt, vector, deadline, *, settings=None, zone=None):
    """Recall for one prompt: a Recall, whose block the hook prints as it is.

    `prompt` is the redacted prompt and `vector` its embedding, with the
    configuration's number of dimensions; `settings` is the hook's configuration,
    by default the store's. A deadline that passes makes the outcome `late`.
    """
    settings = memory.config if settings is None else settings
    threshold = settings.values['recall'].get('threshold')
    if threshold is None:
        return Recall('no-threshold')
    model, dims = settings.values['models']['embedding'], settings.values['models']['dims']
    point = _point(vector, dims)
    root = memory.folder / 'projects' / base.project_folder_name(project)
    try:
        read = _index(memory, root, model, dims, deadline, lambda connection: _rows(connection, prompt))
        if read is None:
            return Recall('no-index')
        rows, hits, identifiers = read
        excluded = _excluded(memory, root, host, session, deadline)
        scored = _scores(rows, hits, identifiers, point, dims, excluded, deadline)
        candidates = _candidates(memory, root / 'layer', scored, deadline, zone)
        lines = [(item, score, line) for item, score, line in candidates if score >= threshold]
        while lines and request_budget.safe(_block(lines)) >= TOKENS:
            lines.pop()
        memory.check(deadline)
    except locks.LockBusy:
        return Recall('late')
    except sqlite3.OperationalError as error:
        # SQLite stopped waiting for another connection's lock, which it does just after the deadline;
        # any other error, such as a disk's, is a failure even then.
        if clock.now() < deadline or not _locked(error):
            raise
        return Recall('late')
    shown = tuple((item, score) for item, score, _ in candidates)
    if not lines:
        return Recall('below', candidates=shown)
    return Recall('injected', _block(lines), tuple(item for item, _, _ in lines),
                  tuple(score for _, score, _ in lines), shown)


def ready(memory, project, deadline, *, settings=None):
    """Whether recall has an index to use: None, or `no-index` or `late` (API-002 step 5).

    The prompt hook asks before it embeds the prompt, so that nothing is sent
    for a project without a curated layer or a usable index, or whose memory
    is being deleted. It reads as `rank` does and writes nothing.
    """
    settings = memory.config if settings is None else settings
    model, dims = settings.values['models']['embedding'], settings.values['models']['dims']
    root = memory.folder / 'projects' / base.project_folder_name(project)
    try:
        found = _index(memory, root, model, dims, deadline, lambda connection: True)
    except locks.LockBusy:
        return 'late'
    except sqlite3.OperationalError:
        if clock.now() < deadline:
            raise
        return 'late'
    return None if found else 'no-index'


def _index(memory, root, model, dims, deadline, then):
    """`_read`'s result when the project has a curated layer and its memory is not being deleted, else None."""
    memory.check(deadline)
    folder = root / 'layer'
    if memory.fence.check(folder) is None or _deleted(folder):
        return None
    found = _read(memory, root, model, dims, deadline, then)
    if found is None:
        memory.check(deadline)
    return found


def _point(vector, dims):
    """The prompt's vector as a tuple of floats, with its length, or ValueError."""
    if isinstance(vector, (str, bytes)) or len(vector) != dims:
        raise ValueError('invalid prompt vector')
    point = tuple(float(value) for value in vector)
    norm = math.hypot(*point)
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError('invalid prompt vector')
    return point, norm


def _deleted(folder):
    """Whether the project's memory is being deleted (TBL-017)."""
    return any(name == 'deleted.json' or name.startswith('deleted.json.') for name in os.listdir(str(folder)))


def _locked(error):
    """Whether SQLite stopped waiting for another connection's lock (SQLITE_BUSY).

    Python 3.11 and later give the error's code; before, its message tells.
    """
    code = getattr(error, 'sqlite_errorcode', None)
    if code is not None:
        return code & 0xff == 5
    return str(error).startswith('database is locked')


def _wait(deadline):
    """Seconds that SQLite may wait for another connection's lock: until just after the deadline."""
    return max(0.0, deadline - clock.now()) + LOCK_MARGIN


def _read(memory, root, model, dims, deadline, then):
    """`then(connection)` in one read of the index after its check; None when the index is missing, cannot be read,
    or is not built with the configuration's model and vector length.

    The check and what `then` reads come from the same read, so that a writer
    that commits in between, taking the `built` mark away, is not seen. Only
    the read's first statement waits for another connection's lock, and only
    until just after the deadline (SQLite counts whole milliseconds), so that a
    lock that outlasts the deadline makes the outcome `late`. An index that
    cannot be opened, or that the check finds not to be a database or damaged,
    is like a missing one; SQLite's other errors, such as a disk's or a damaged
    page that the check does not read, propagate. Closing the connection ends
    the read, so that no statement runs after an error.
    """
    try:
        connection = index_io.open_index(memory, root, timeout=0)  # opening reads nothing; the read sets the wait
    except (sqlite3.DatabaseError, index_io.IndexUnavailable):
        return None
    if connection is None:
        return None
    try:
        connection.execute('PRAGMA busy_timeout = %d' % int(_wait(deadline) * 1000))
        connection.execute('BEGIN')
        if index_io.state(connection, model=model, dims=dims, reader=True) is not None:
            return None
        return then(connection)
    finally:
        connection.close()


def _rows(connection, prompt):
    """(item, vector) of every current item with a vector, the prompt's identifiers that each holds, and those."""
    identifiers = sorted(set(index_io.identifiers(prompt)))
    hits = Counter()
    rows = connection.execute(
        "SELECT index_vectors.item, index_vectors.vector FROM index_vectors JOIN index_items "
        "ON index_items.item = index_vectors.item WHERE index_items.status = 'current'").fetchall()
    for start in range(0, len(identifiers), TERMS):
        chunk = identifiers[start:start + TERMS]
        hits.update(item for (item,) in connection.execute(
            'SELECT item FROM index_terms WHERE term IN (%s)' % ', '.join('?' * len(chunk)), chunk))
    return rows, hits, identifiers


def _excluded(memory, root, host, session, deadline):
    """The pinned items that the session's latest start showed and the items that its last three prompts injected.

    A line that cannot be read is left out, as the last one can be while it is
    being appended; a log whose file is missing is read from its backup.
    """
    path = root / 'injections' / (raw_log.log_name(host, session) + '.jsonl')
    data = b''
    for candidate in (path, path.with_name(path.name + '.bak')):
        try:
            data = files.fence_read(memory, candidate, deadline)
            break
        except FileNotFoundError:
            continue
    start, prompts = (), []
    for line in data.split(b'\n'):
        try:
            value = injection_log.parse_line(line)
        except (ValueError, UnicodeError):
            continue
        if value['session'] != session:
            continue
        if value['where'] == 'start':
            start = value['items']
        else:
            prompts.append(value['items'])
    excluded = set(start)
    for items in prompts[-PROMPTS:]:
        excluded.update(items)
    return excluded


def _scores(rows, hits, identifiers, point, dims, excluded, deadline):
    """[(score, item)] of the rows that take part, best first and then by ID.

    The cosine comes from the distance and the lengths, which the math module
    computes in C, so that 20,000 vectors of 512 numbers score in plain Python
    within the prompt hook's time (REQ-034).
    """
    point, norm = point
    unpack, size = struct.Struct('<%df' % dims).unpack, 4 * dims
    scored = []
    for index, (item, data) in enumerate(rows):
        if index % EVERY == 0 and clock.now() >= deadline:
            raise locks.LockBusy()
        if item in excluded or len(data) != size:
            continue
        values = unpack(data)
        length = math.hypot(*values)
        if not math.isfinite(length) or length <= 0:
            continue
        distance = math.dist(point, values)
        score = (norm * norm + length * length - distance * distance) / (2 * norm * length)
        if identifiers:
            score += BOOST * hits[item] / len(identifiers)
        scored.append((-score, item))
    scored.sort()
    return [(item, -negative) for negative, item in scored]


def _candidates(memory, folder, scored, deadline, zone):
    """[(item, score, line)] of the five best items whose files say they are current and that no tombstone names."""
    forgotten = _forgotten(memory, folder)
    found = []
    for item, score in scored:
        if len(found) == ITEMS:
            break
        if item in forgotten or not item_types.ITEM.fullmatch(item):
            continue
        try:
            value = item_types.parse_item(files.fence_read(memory, folder / 'items' / (item + '.json'), deadline))
        except FileNotFoundError:
            continue
        if value['id'] != item:
            raise ValueError('item file name differs from its ID')
        line = start_memory.item_line(value, zone) if value['status'] == 'current' else None
        if line is not None:
            found.append((item, score, line))
    return found


def _forgotten(memory, folder):
    """The items that a tombstone or its backup names."""
    path = folder / 'tombstones'
    if memory.fence.check(path) is None:
        return set()
    found = set()
    for name in os.listdir(str(path)):
        for suffix in ('.json', '.json.bak'):
            if name.endswith(suffix):
                found.add(name[:-len(suffix)])
    return found


def _block(lines):
    """The recall block: the first line about reference material and the item lines, nothing before or after."""
    return '\n'.join([start_memory.REFERENCE] + [line for _, _, line in lines])
