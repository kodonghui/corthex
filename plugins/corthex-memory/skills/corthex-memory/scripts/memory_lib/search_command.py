"""The search command (API-021 with API-012; SPEC-025, SPEC-004; TASK-040): items by words and by meaning.

The command runner parses `search` but hands it to no handler before the 0.3.0
activation, so it answers it as not implemented, as in C1, and an installed
plugin keeps C1 behaviour; until then the tests call this handler as the runner
will, after its gates, with the format-2 store binding.

By words, the project's items are ranked by BM25 over its search index
(`index_io.search`). When the index cannot give its words, because it is
missing, being built, damaged, reached through a link, or of another version,
schema or word splitting, the words come from the project's items through an
index made in memory in the same way, so that a search never waits for the
memory worker's step 6 to build it again. By meaning, with consent, the OpenAI
memory key and an index built with the configured embedding model and vector
length, the request is redacted and embedded (API-012), with its usage line,
before any lease is taken and within 10 seconds; the items with a vector are
ranked by their cosine with the request's, those above 0. Both rankings hold
items of every status, each once, and with `--kind` only items of that kind.
An item's score is then the sum of 1 / (60 + its rank) over the rankings it is
in, and equal scores go by ID. Otherwise the search goes by words only, and
`reason` says why: `asked` with `--words-only`, `no-consent`, `no-key`,
`index-not-ready` when the index cannot give vectors, and `embedding-failed`
when the request could not be sent or its answer failed, which the failure log
notes with the step `embed`. Nothing is sent in the first four cases.

Under the project's layer lease, waiting for it as long as the other commands
wait for theirs, it reads the index, the names of the items and tombstones and
the results' item files through the store's path fence, and changes nothing.
The rankings leave out items that a tombstone names and items without a file,
whose rows the index can still hold, and each result shows what its own file
says: kind, status, the deciding quote's speaker and date, and title. A project
without a folder, or whose memory is being deleted, has no results. An item
file that cannot be read raises, which the runner reports as `internal`.
"""
import math
import operator
import sqlite3
import struct

from . import base, clock, commands, curation_worker, files, index_io, item_io, item_types, locks, model_access
from . import model_client, model_embed, recall, run_listing

# The commands' shared lock wait, within one bound for the whole search.
WAIT, SECONDS = 10.0, 60.0
FUSION = 60  # each ranking adds 1 / (FUSION + rank) to an item's score
REASONS = {
    'asked': 'as asked',
    'no-consent': 'since memory has no consent to send search requests',
    'no-key': 'since CORTHEX_MEMORY_OPENAI_API_KEY is missing',
    'index-not-ready': 'since the search index has no vectors of the configured model yet',
    'embedding-failed': "since the search request's embedding failed",
}


def _without(settings, only):
    """Why the search goes by words only before anything is read: asked, no-consent, no-key, else None."""
    if only:
        return 'asked'
    if not settings.consented():
        return 'no-consent'
    try:
        key = model_access.Credentials.read().headers('openai')
    except ValueError:
        key = None
    return None if key is not None else 'no-key'


def _ready(memory, root, model, dims, deadline):
    """Whether the index can rank by meaning, read without a lease as recall reads it, so nothing is sent for nothing.

    An index that SQLite cannot read, for a lock that outlasts the search's time
    or another error, is not ready either: the search goes by words, as
    `_ranked` does with such an index.
    """
    try:
        return recall._index(memory, root, model, dims, deadline, lambda connection: True) is not None
    except sqlite3.DatabaseError:
        return False


def _embedded(memory, project, words, settings, dims, deadline):
    """API-012 without any lease: (the request's vector, None), or (None, why the search goes by words)."""
    try:
        answer = model_embed.embed(memory, project=project, call='embed-search', texts=[words],
                                   config=settings.document, check=lambda: memory.check(deadline), deadline=deadline)
    except model_client.MissingKey:
        return None, 'no-key'
    except ValueError as error:
        # Redaction or the request's size refused it (SPEC-004): nothing was sent.
        failure = error
    else:
        if answer.failure is None:
            return struct.unpack('<%df' % dims, answer.vectors[0]), None
        failure = answer.failure.code
    memory.note(failure, step='embed')
    memory.flush()
    return None, 'embedding-failed'


def fused(*rankings):
    """The items of the rankings by the sum of 1 / (60 + rank) over those they are in, then by ID."""
    scores = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (FUSION + rank)
    return [item for item, _ in sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))]


def _items(memory, root, deadline, check):
    if memory.fence.check(root / 'layer/items') is None:
        return []
    return item_io._items(memory, root, deadline, check)


def _present(memory, root, deadline):
    """The items whose files are in the layer and that no tombstone or tombstone's backup names."""
    folder = root / 'layer/items'
    if memory.fence.check(folder) is None:
        return set()
    names = {path.name[:-5] for path in files._retry(lambda: list(folder.iterdir()), deadline)
             if path.name.endswith('.json')}
    return names - recall._forgotten(memory, root / 'layer')


def _meaning(rows, vector, dims, deadline):
    """The items of [(item, vector)] whose cosine with the request's vector is above 0, best first, then by ID.

    The dot product is summed exactly, so that a vector at right angles to the
    request's scores 0 rather than what rounding leaves.
    """
    point, norm = recall._point(vector, dims)
    unpack, size = struct.Struct('<%df' % dims).unpack, 4 * dims
    scored = []
    for index, (item, data) in enumerate(rows):
        if index % recall.EVERY == 0 and clock.now() >= deadline:
            raise locks.LockBusy()
        if len(data) != size:
            continue
        values = unpack(data)
        length = math.hypot(*values)
        if not math.isfinite(length) or length <= 0:
            continue
        cosine = math.fsum(map(operator.mul, point, values)) / (norm * length)
        if cosine > 0:
            scored.append((-cosine, item))
    scored.sort()
    return [item for _, item in scored]


def _rank(connection, words, vector, kind, dims, present, deadline):
    """(by words, by meaning or None) from one index; the meaning only with a vector."""
    kinds = dict(connection.execute('SELECT item, kind FROM index_items').fetchall())

    def wanted(item):
        return item in present and (kind is None or kinds.get(item) == kind)
    by_words = [item for item, _ in index_io.search(connection, words) if wanted(item)]
    if vector is None:
        return by_words, None
    rows = [row for row in connection.execute('SELECT item, vector FROM index_vectors').fetchall() if wanted(row[0])]
    return by_words, _meaning(rows, vector, dims, deadline)


def _ranked(memory, root, words, vector, kind, model, dims, deadline, check):
    """(the item IDs best first, whether the meaning ranked them too), under the layer lease."""
    present = _present(memory, root, deadline)
    try:
        connection = index_io.open_index(memory, root, timeout=max(0.0, deadline - clock.now()))
    except (sqlite3.DatabaseError, index_io.IndexUnavailable):
        connection = None
    if connection is not None:
        try:
            state = index_io.state(connection, model=model, dims=dims, reader=True)
            if state in (None, 'embedding'):
                by_words, by_meaning = _rank(connection, words, vector if state is None else None, kind, dims,
                                             present, deadline)
                return (by_words, False) if by_meaning is None else (fused(by_words, by_meaning), True)
        except sqlite3.DatabaseError:
            pass  # a damaged page that the quick look did not meet: the words come from the items
        finally:
            connection.close()
    connection = sqlite3.connect(':memory:', isolation_level=None)
    try:
        connection.executescript(index_io.DDL.read_text(encoding='utf-8'))
        index_io.put(connection, _items(memory, root, deadline, check))
        return _rank(connection, words, None, kind, dims, present, deadline)[0], False
    finally:
        connection.close()


def _results(memory, root, ranked, kind, limit, deadline, check):
    """The first `limit` ranked items as their own files show them (data-search results)."""
    results = []
    for item in ranked:
        if len(results) == limit:
            break
        value = item_io._record(memory, root / 'layer/items' / (item + '.json'), item_types.parse_item, deadline,
                                check)
        if value['id'] != item:
            raise files.RestoreNeeded()
        if kind is not None and value['kind'] != kind:
            continue
        line = run_listing.list_line(value)
        results.append(dict(line, status=value['status']))
    return results


def _say(meant, reason, count):
    found = 'no item found' if not count else '1 item found' if count == 1 else '%d items found' % count
    if meant:
        return 'Searched by words and meaning; %s.' % found
    return 'Searched by words only, %s; %s.' % (REASONS[reason], found)


def search(context):
    """API-021 after the runner's gates, with the format-2 store binding as `context.memory`."""
    project, arguments = context.project.name, context.arguments
    words, kind = arguments.get('words'), arguments.get('kind')
    limit, only = arguments.get('limit', 20), arguments.get('words_only', False)
    if (type(words) is not str or not words.strip() or kind is not None and kind not in item_types.KINDS or
            type(limit) is not int or limit < 1 or type(only) is not bool):
        return commands.common_result('search', 'usage')
    memory, settings = context.memory, context.configuration
    model, dims = settings.values['models']['embedding'], settings.values['models']['dims']
    root = memory.folder / 'projects' / base.project_folder_name(project)
    deadline = clock.now() + SECONDS
    vector, reason, meant, results = None, _without(settings, only), False, []
    try:
        if reason is None and not _ready(memory, root, model, dims, deadline):
            reason = 'index-not-ready'
        if reason is None:
            vector, reason = _embedded(memory, project, words, settings, dims, deadline)
        if memory.fence.check(root) is not None:
            with memory.lease(root / 'layer.lock', 'layer', deadline, 'skill',
                              acquire_deadline=min(deadline, clock.now() + WAIT)):
                if not curation_worker._deleted(memory, root):
                    def check():
                        memory.check(deadline, memory.held)
                    ranked, meant = _ranked(memory, root, words, vector, kind, model, dims, deadline, check)
                    results = _results(memory, root, ranked, kind, limit, deadline, check)
                    check()
    except locks.LockBusy:
        return commands.common_result('search', 'lock-busy')
    if not meant and reason is None:
        reason = 'index-not-ready'  # the index changed between the look before the request and the search
    data = {'project': project, 'by': 'both' if meant else 'words', 'results': results}
    if not meant:
        data['reason'] = reason
    return commands.result('search', data, _say(meant, reason, len(results)), 'done' if results else 'nothing')
