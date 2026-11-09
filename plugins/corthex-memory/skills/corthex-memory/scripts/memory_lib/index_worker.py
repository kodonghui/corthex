"""API-005 step 6: keep a project's search index and embed its current items (TASK-082).

The memory worker calls `keep` as its step 6, under the project's curation
lease. For an enabled project with consent it takes the layer lease to build
the index again when it is missing, unreadable or obsolete (TASK-081), or else
to make its rows match the canonical items: an item whose row is missing or
differs is written again, and the rows of items that are gone or private are
deleted, their words emptied from the write-ahead log as a forget empties them,
or, when a reader keeps the log, with the index's files, which are then built
again. Those rows take the index's `built` mark with them until their words are
gone, so an index left by a step that stopped in between, or whose files cannot
go either, is unfinished, and the next step 6 builds it again. This also
repairs what a stopped writer left, such as the row of an item that a stopped
undo made current again (TASK-108) or the rows that a stopped forget left.

With the OpenAI memory key it then embeds every current item without a vector
(API-011): the item's kind, text and the words of its quotes, joined by line
breaks, which `model_embed` redacts and cuts, in requests of at most 100 texts
and 200,000 bytes. The requests go without the layer lease; before each one,
and before each further attempt of one, the step takes it to read the curation
record's fence again, and when a forget, an undo or a tombstone has moved it,
it reads the items again. A request one of whose items is then gone, changed or
private is not tried again, so an item forgotten before an attempt is never in
it. The step's conditions are read again before each request and each further
attempt, both before that comparison, which may wait for the layer lease, and
after it, right before sending, and once more when no item is left to embed:
once the project is off or consent is withdrawn, nothing more is sent, and the
step ends at once with that reason. A vector is written under the layer
lease only while its item is still current, unchanged and not private, and the
index still has the embedding model and vector length that made it; the vectors
of a request already answered are kept on the device. A failed request is noted
in the failure log with its code, and its items stay without a vector, found by
words, until a later step 6; a lasting failure ends the step. Nothing calls this
module before the 0.3.0 activation.
"""
import contextlib
from dataclasses import dataclass
import os
import sqlite3

from . import (base, clock, configuration, curation_worker, fence_plan, forget_effects, index_io, item_io,
               item_types, locks, model_access, model_client, model_embed, revision_io, worker_support)

RESERVE = curation_worker.RESERVE   # no request starts in the run's last seconds
_BREAKS = curation_worker._BREAKS + (sqlite3.Error,)


@dataclass(frozen=True)
class Outcome:
    """Why step 6 ended (done, configuration, consent, disabled, deleted, key, failed, stale, busy,
    deadline, lost-lock or error) and what it did."""
    reason: str
    rebuilt: object  # why the index was built again (index_io.ensure), or None
    written: tuple   # the items whose rows were written again
    removed: tuple   # the items whose rows were deleted
    embedded: tuple  # the items that got a vector
    requests: int    # the embedding requests sent, each with its own attempts
    failed: tuple    # the failed requests' codes, in order


def text(item):
    """What an item's embedding is made from: its kind, text and the words of its quotes (TC-141)."""
    return '\n'.join([item['kind'], item['text']] + [quote['words'] for quote in item['quotes']])


@contextlib.contextmanager
def _layer(memory, root, deadline, step):
    with memory.lease(root / 'layer.lock', 'layer', deadline, step,
                      acquire_deadline=min(deadline, clock.now() + curation_worker.LAYER_WAIT)) as lease:
        yield lease


def _gate(memory, project, deadline):
    """Step 6's conditions: (None, the configuration), or (why the step ends, None)."""
    try:
        settings = memory.configuration(memory.note, deadline=min(
            deadline, clock.now() + worker_support.OPERATION_SECONDS))
    except configuration.ConfigurationInvalid:
        return 'configuration', None
    if not settings.consented():
        return 'consent', None
    if not settings.enabled(project):
        return 'disabled', None
    return None, settings


def _proof(memory, root, deadline):
    """Under the layer lease: the fence proof, and the check that it and both leases still hold."""
    expected = fence_plan.snapshot(revision_io.read(memory, root, deadline))
    check, _ = item_io._checked(memory, root, expected, deadline, curator=True)
    return expected, check


def _opened(memory, root, model, dims):
    """The index to read and write, or None when it is missing or no longer made with model and dims."""
    connection = index_io.open_index(memory, root)
    if connection is None:
        return None
    if index_io.state(connection, model=model, dims=dims) is not None:
        connection.close()
        return None
    return connection


def _rows(memory, root, deadline, model, dims, at):
    """Under the layer lease: the index built again or its rows made to match the items.

    Every check that a lease or the fence still holds runs before and after the
    reading and before each write; reading the items itself checks only the
    deadline, since no other writer changes them while this lease is held.
    """
    with _layer(memory, root, deadline, 'index'):
        expected, check = _proof(memory, root, deadline)
        rebuilt = index_io.ensure(memory, root, expected, deadline, model=model, dims=dims, when=at)
        items = item_io._items(memory, root, deadline, lambda: memory.check(deadline))
        check()
        written, removed, built = (), (), None
        if rebuilt is None:
            connection = _opened(memory, root, model, dims)
            if connection is None:
                raise index_io.IndexUnavailable()
            try:
                written, removed, built = index_io.sync(connection, items)
            finally:
                connection.close()
            check()
        # The rows that went leave no word in the files: the log is emptied as a forget empties it, or, when a
        # reader keeps it, the index's files go and the index is built again (TC-140). They took the `built`
        # mark with them, so a step that stops before this leaves the index for the next step 6 to build again.
        if removed:
            try:
                how = forget_effects._index(memory, root, removed, deadline, check)
            except (OSError, forget_effects.Unverified):
                # Its files could not go either, as when Windows keeps a file that a reader holds open. When the
                # log went and the index file stayed, the file is back as it was before the rows went, `built`
                # mark and all: the mark goes again, so that readers leave the index and the next step 6 builds
                # it again.
                check()
                index_io.unfinish(memory, root)
                raise
            check()
            if how == 'rows':
                index_io.finish(memory, root, built)
            else:
                rebuilt = index_io.ensure(memory, root, expected, deadline, model=model, dims=dims, when=at)
        connection = _opened(memory, root, model, dims)
        if connection is None:
            raise index_io.IndexUnavailable()
        try:
            _, vectors = index_io.rows(connection)
        finally:
            connection.close()
        check()
    pending = [item for item in items if item['status'] == 'current' and item['id'] not in vectors]
    return rebuilt, tuple(written), tuple(removed), pending, expected


def _still(memory, root, deadline, items):
    """Under the layer lease: those of the items that are still current, unchanged and not private."""
    kept = []
    for item in items:
        path = root / 'layer/items' / (item['id'] + '.json')
        if item_io._private(memory, root, item['id']) or memory.fence.check(path) is None:
            continue
        value = item_io._record(memory, path, item_types.parse_item, deadline, lambda: memory.check(deadline))
        if value['id'] == item['id'] and value['status'] == 'current' and text(value) == text(item):
            kept.append(item)
    return kept


def _fresh(memory, root, deadline, items, expected):
    """Before a request, under the layer lease: the items still to embed, and the fence proof.

    When a forget, an undo or a tombstone has moved the fence since `expected`,
    every remaining item is read again.
    """
    with _layer(memory, root, deadline, 'embed'):
        proof, check = _proof(memory, root, deadline)
        if proof != expected:
            items = _still(memory, root, deadline, items)
        check()
    return items, proof


def _again(memory, project, root, deadline, batch, expected):
    """Asked before each further attempt of a request: whether every item of its batch may still be sent.

    A request is not tried again once the step's conditions no longer hold, as
    when the project was turned off meanwhile: they are read before and after
    the wait for the layer lease. Between the two reads it compares the fence as
    `_fresh` does, against the proof that its last comparison read, so that the
    batch is read again only when the fence has moved since; a request one of
    whose items is gone, changed or private is not tried again, and its items
    wait for a later step 6 (TC-140).
    """
    proof = [expected]

    def still():
        if _gate(memory, project, deadline)[0] is not None:
            return False
        kept, proof[0] = _fresh(memory, root, deadline, batch, proof[0])
        return len(kept) == len(batch) and _gate(memory, project, deadline)[0] is None
    return still


def _store(memory, root, deadline, model, dims, batch, vectors):
    """Under the layer lease: the vectors of the batch's items that may still have one; the items written.

    An index that is gone, or was built again with another model or vector
    length meanwhile, takes none of them: the step is then stale.
    """
    with _layer(memory, root, deadline, 'embed'):
        _, check = _proof(memory, root, deadline)
        kept = {item['id'] for item in _still(memory, root, deadline, batch)}
        check()
        connection = _opened(memory, root, model, dims)
        if connection is None:
            raise fence_plan.Stale()
        try:
            check()
            written = index_io.put_vectors(connection, [(item['id'], vector) for item, vector in zip(batch, vectors)
                                                        if item['id'] in kept])
        finally:
            connection.close()
        check()
    return tuple(written)


def keep(memory, project, owner, deadline, *, when=None):
    """Keep the project's index and embed its current items, under the caller's tracked curation lease.

    `memory` is the format-2 store binding, `owner` the project's curation
    lease that the caller took through `memory.lease` and releases, and
    `deadline` the run's absolute monotonic end. `when` fixes the time that a
    rebuild records, for tests. Returns why the step ended and what it did.
    """
    root = memory.folder / 'projects' / base.project_folder_name(project)
    done = {'rebuilt': None, 'written': (), 'removed': (), 'embedded': (), 'requests': 0, 'failed': ()}
    step = 'index'

    def end(reason):
        return Outcome(reason, **done)

    def check():
        memory.check(deadline, (owner,))

    try:
        curation_worker._owned(memory, root, owner)
        check()
        reason, settings = _gate(memory, project, deadline)
        if reason is not None:
            return end(reason)
        if curation_worker._deleted(memory, root):
            return end('deleted')
        model, dims = settings.values['models']['embedding'], settings.values['models']['dims']
        done['rebuilt'], done['written'], done['removed'], pending, expected = _rows(
            memory, root, deadline, model, dims, base.utc_time(when))
        step = 'embed'
        if not pending:
            # Read again at the end, as the loop below does, so that a project turned off meanwhile says so.
            reason, _ = _gate(memory, project, deadline)
            return end(reason or 'done')
        try:
            credentials = model_access.Credentials.read()
            if credentials.headers('openai') is None:
                return end('key')
        except ValueError:
            return end('key')
        prepared = model_embed.prepare([text(item) for item in pending], credentials=credentials,
                                       environment=dict(os.environ))
        remaining = list(zip(pending, prepared))
        while True:
            # The step's conditions are read again before each request, before and after the wait for the layer
            # lease, and once more when no item is left to embed, so that a project turned off, or consent
            # withdrawn, sends nothing more and ends the step at once with its reason.
            reason, _ = _gate(memory, project, deadline)
            if reason is not None:
                return end(reason)
            if not remaining:
                return end('done')
            curation_worker._left(deadline)
            kept, expected = _fresh(memory, root, deadline, [item for item, _ in remaining], expected)
            kept = {item['id'] for item in kept}
            remaining = [pair for pair in remaining if pair[0]['id'] in kept]
            if not remaining:
                continue
            reason, _ = _gate(memory, project, deadline)
            if reason is not None:
                return end(reason)
            _, stop = model_embed.batches([sent for _, sent in remaining])[0]
            batch, remaining = [item for item, _ in remaining[:stop]], remaining[stop:]
            result = model_embed.embed(memory, project=project, call='embed-items',
                                       texts=[text(item) for item in batch], config=settings.document,
                                       check=check, deadline=deadline - RESERVE,
                                       still=_again(memory, project, root, deadline, batch, expected))
            done['requests'] += 1
            failure = result.failure
            if failure is not None:
                done['failed'] += (failure.code,)
                memory.note(failure.code, step='embed')
                if failure.lasting:
                    return end('failed')
                if failure.code == 'timeout' and clock.now() >= deadline - RESERVE:
                    raise locks.LockBusy()  # the run's own time ran out, not the request's
                continue
            done['embedded'] += _store(memory, root, deadline, model, dims, batch, result.vectors)
    except locks.LostLock:
        memory.note(locks.LostLock(), step=step)
        return end('lost-lock')
    except fence_plan.Stale:
        # The project was deleted, or its index replaced, while the step held no lease.
        return end('stale')
    except locks.LockBusy:
        return end('deadline' if clock.now() >= deadline - RESERVE else 'busy')
    except model_client.MissingKey:
        return end('key')
    except _BREAKS as error:
        memory.note(error, step=step)
        return end('error')
