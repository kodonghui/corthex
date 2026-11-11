"""TASK-094: recall for a prompt as the prompt hook runs it for a format-2 store (API-002 steps 5, 7 and 9).

`recall` is step 5. It runs for an enabled project with consent, as the hook's
step 1 finds one, and otherwise gives no outcome and nothing to log. It needs
the OpenAI memory key, a recall threshold, a prompt that is neither short nor a
command, and an index that it can use, in that order, and says in one word
which was missing (TBL-011); none of these sends anything. A key that cannot be
sent counts as missing, as the index worker counts it, and the index is looked
at within the embedding's 800 ms. It then embeds the redacted prompt (API-010)
with a request that ends 800 ms after the hook's start and adds a usage line,
and ranks the project's items within the hook's own deadline (TASK-093). An
index that a rebuild or a deletion takes away while the request is out gives
`no-index` after it. An embedding that comes too late, or a deadline that
passes while it ranks, makes the outcome `late`, with `timeout` only for a
request that started and timed out; a failed request or answer, a vector of
the wrong length and any other error make it `failed`. Either way nothing is
injected and the result carries what the hook's failure log notes.
Recording comes before recall (step 4) and recall writes only the usage log,
so the prompt goes on whatever recall does (REQ-035).

`output` is step 7's line: the hook's JSON, with the compaction check's line
(TASK-114), the block or both as its added context, the line first, or nothing
when there is neither. `log` is step 9: the injection log line with recall's
outcome, the injected items and their scores and the candidates, also when
nothing is injected. The line names the prompt's raw entry when the prompt was
recorded; a prompt that recording leaves out is still recalled (SPEC-006).

Nothing calls this module before the 0.3.0 activation, when the prompt hook
uses it for format-2 stores; until then the installed prompt hook keeps C1
behaviour.
"""
from dataclasses import dataclass
import json
import struct

from . import injection_log, locks, model_access, model_embed, recall as ranking

EMBED_SECONDS = 0.8  # the prompt's embedding request ends this long after the hook's start (API-010)
RANKED = ('injected', 'below')


@dataclass(frozen=True)
class Result:
    outcome: object         # a TBL-011 outcome, or None when recall does not apply and nothing is logged
    block: str = ''         # the recall block, empty unless items are injected
    items: tuple = ()       # the injected items' IDs, best first
    scores: tuple = ()      # their scores, in the same order
    candidates: tuple = ()  # (item, score) of the five best eligible items, once recall has ranked them
    error: object = None    # what the hook's failure log notes for `late` or `failed`: a code or an exception


def recall(memory, project, host, session, prompt, started, deadline, *, settings=None, zone=None):
    """API-002 step 5 for the redacted prompt: a Result, whose block step 7 prints.

    `started` is the hook's start and `deadline` its end, both on the clock's
    monotonic time; `settings` is the hook's configuration, by default the
    store's.
    """
    settings = memory.config if settings is None else settings
    if not settings.enabled(project):
        return Result(None)
    try:
        key = model_access.Credentials.read().headers('openai')
    except ValueError:
        key = None  # a key that cannot be read or sent, as the index worker's step 6 counts it
    if key is None:
        return Result('no-key')
    values = settings.values['recall']
    if values.get('threshold') is None:
        return Result('no-threshold')
    skipped = ranking.skipped(prompt, values['skip'])
    if skipped is not None:
        return Result(skipped)
    # The embedding's end; the index is looked at only before it, since a lock that outlasts it leaves no time to send.
    sent_by = min(deadline, started + EMBED_SECONDS)
    try:
        missing = ranking.ready(memory, project, sent_by, settings=settings)
        if missing == 'late':
            return Result('late', error='deadline')
        if missing is not None:
            return Result(missing)
        answer = model_embed.embed(memory, project=project, call='embed-prompt', texts=[prompt],
                                   config=settings.document, check=lambda: memory.check(deadline), deadline=sent_by)
        if answer.failure is not None and not answer.attempts:
            # The embedding's time ran out before its request could start, as it does after a look at the index that
            # SQLite's wait for a lock made longer than asked: nothing was sent, so no request timed out.
            return Result('late', error='deadline')
        if answer.failure is not None:
            code = answer.failure.code
            return Result('late' if code == 'timeout' else 'failed', error=code)
        vector = struct.unpack('<%df' % settings.values['models']['dims'], answer.vectors[0])
        found = ranking.rank(memory, project, host, session, prompt, vector, deadline, settings=settings, zone=zone)
    except locks.LockBusy:
        return Result('late', error='deadline')
    except Exception as error:
        return Result('failed', error=error)
    if found.outcome == 'late':
        return Result('late', error='deadline')
    return Result(found.outcome, found.block, found.items, found.scores, found.candidates)


def output(result, line=None):
    """API-002 step 7: the hook's one JSON line, in ASCII, with the added context; b'' without any.

    The context is the compaction check's `line`, when there is one, then a
    blank line and the recall block, when there is one (TASK-114).
    """
    context = '\n\n'.join(part for part in (line, result.block) if part)
    if not context:
        return b''
    value = {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': context}}
    return json.dumps(value, ensure_ascii=True).encode('ascii') + b'\n'


def log(memory, project, host, session, result, *, entry=None, when=None):
    """API-002 step 9: the prompt's injection log line (TBL-011).

    `entry` is the prompt's raw entry ID when the prompt was recorded. False
    when recall did not apply, or when the session's raw log lock stays busy,
    as recording skips an entry; other failures go to the hook's failure log.
    """
    if result.outcome is None:
        return False
    ranked = result.outcome in RANKED
    return injection_log.append(memory, project, host, session, 'prompt', result.items, prompt=entry,
                                outcome=result.outcome, scores=result.scores if ranked else None,
                                candidates=result.candidates if ranked else None, when=when)
