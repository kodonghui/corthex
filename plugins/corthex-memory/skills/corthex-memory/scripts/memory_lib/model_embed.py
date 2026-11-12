"""API-010 to API-012: OpenAI embeddings (SPEC-016, SPEC-023, SPEC-025; TASK-080).

Each text is redacted as a curator request is, then cut at a character
boundary to 8,192 bytes, which keeps it within the model's 8,192 tokens; an
empty text is never sent. One request carries at most 100 texts and 200,000
bytes, with the configured model and `dims`, and no `user` field. Each vector
must hold `dims` finite numbers and have a length above 0, else `bad-vector`;
it is scaled to length 1 and returned as float32 little-endian bytes
(TBL-021). Every attempt adds one usage line with the prompt tokens that the
answer reports. Only item embeddings (API-011) try a passing failure again,
twice, as the curator does, and only while the caller's `still` says that the
texts may still be sent; a prompt's embedding ends at its hook's deadline.
No hook, worker or command calls this module yet.
"""
import copy
from dataclasses import dataclass, field
import math
import os
import struct

from . import clock, configuration, model_access, model_client, model_request, model_transport, model_usage, store

TEXT_BYTES = 8192
BATCH_TEXTS = 100
BATCH_BYTES = 200000
# The time limit of one attempt, in seconds; a prompt's embedding has only its hook's deadline.
LIMITS = {'embed-prompt': None, 'embed-items': 60, 'embed-search': 10}
# The most seconds that ending the request of a call that has only its hook's deadline, a prompt's embedding, may
# take after its answer or its end, so that the hook still has time to rank, print and log (API-002, API-010).
SETTLE = 0.02


@dataclass(frozen=True)
class Result:
    vectors: tuple = field(repr=False)   # float32 little-endian bytes for each text, in order; () after a failure
    failure: object
    attempts: int
    logged: int


class _Bad(ValueError):
    """An answer that fails its check; the prompt tokens it reports are still billed."""
    def __init__(self, code, tokens=None):
        super().__init__(code)
        self.code, self.tokens = code, tokens


def _cut(text):
    data = text.encode('utf-8')
    return text if len(data) <= TEXT_BYTES else data[:TEXT_BYTES].decode('utf-8', 'ignore')


def prepare(texts, *, credentials, environment):
    """The texts as a request sends them: redacted, then cut; an empty text is refused."""
    if not isinstance(texts, (list, tuple)) or not texts:
        raise ValueError('invalid memory embedding texts')
    sent = []
    for text in texts:
        if not isinstance(text, str):
            raise ValueError('invalid memory embedding text')
        text = _cut(model_request._redact(text, environment, credentials))
        if not text:
            raise ValueError('empty memory embedding text')
        sent.append(text)
    return sent


def batches(sent):
    """Split prepared texts into requests of at most 100 texts and 200,000 bytes: [(start, end)]."""
    result, start, size = [], 0, 0
    for index, text in enumerate(sent):
        length = len(text.encode('utf-8'))
        if index > start and (index - start == BATCH_TEXTS or size + length > BATCH_BYTES):
            result.append((start, index))
            start, size = index, 0
        size += length
    if sent:
        result.append((start, len(sent)))
    return result


def vectors(text, count, dims):
    """The answer's vectors by index, scaled to length 1, and the prompt tokens it reports."""
    try:
        value = store.json_document(text.encode('utf-8'))
    except ValueError:
        raise _Bad('bad-answer') from None
    usage = value.get('usage') if isinstance(value, dict) else None
    tokens = usage.get('prompt_tokens') if isinstance(usage, dict) else None
    tokens = tokens if type(tokens) is int and tokens >= 0 else None
    data = value.get('data') if isinstance(value, dict) else None
    if not isinstance(data, list) or len(data) != count:
        raise _Bad('bad-answer', tokens)
    found = {}
    for entry in data:
        index = entry.get('index') if isinstance(entry, dict) else None
        if type(index) is not int or not 0 <= index < count or index in found:
            raise _Bad('bad-answer', tokens)
        numbers = entry.get('embedding')
        if (not isinstance(numbers, list) or len(numbers) != dims or
                any(type(n) not in (int, float) or not math.isfinite(n) for n in numbers)):
            raise _Bad('bad-vector', tokens)
        largest = max(abs(n) for n in numbers)
        if not largest > 0:
            raise _Bad('bad-vector', tokens)
        # Scaled by the largest first, so that no square overflows.
        length = largest * math.sqrt(math.fsum((n / largest) ** 2 for n in numbers))
        found[index] = struct.pack('<%df' % dims, *(n / length for n in numbers))
    return tuple(found[index] for index in range(count)), tokens


def embed(memory, *, project, call, texts, config, check, deadline, still=None):
    """Embed one request's texts; `deadline` is the caller's, the hook's for a prompt.

    `still`, when given, is asked before each attempt after the first whether
    the texts may still be sent; when it says no, the request is not tried
    again and keeps its last failure.
    """
    if not callable(check):
        raise TypeError('original memory client check required')
    if still is not None and not callable(still):
        raise TypeError('invalid memory embedding recheck')
    if call not in LIMITS:
        raise ValueError('invalid memory embedding call')
    begun = clock.now()
    store.MemoryStore._deadline(deadline)
    if call != 'embed-items' and len(texts) != 1:
        raise ValueError('one text per memory embedding request')
    model_client._verify(check)
    credentials = model_access.Credentials.read()
    headers = credentials.headers('openai')
    if headers is None:
        raise model_client.MissingKey()
    config = copy.deepcopy(config)
    settings = configuration.prepare(config, temporary=False).values
    environment = dict(os.environ)
    url = model_request.endpoint(environment, 'openai', '/v1/embeddings')
    sent = prepare(texts, credentials=credentials, environment=environment)
    if len(sent) > BATCH_TEXTS or sum(len(text.encode('utf-8')) for text in sent) > BATCH_BYTES:
        raise ValueError('memory embedding request too large')
    model, dims = settings['models']['embedding'], settings['models']['dims']
    body = {'model': model, 'input': sent, 'dimensions': dims, 'encoding_format': 'float'}
    headers.update({'content-type': 'application/json', 'user-agent': model_request.agent()})
    wire = dict(url=url, headers=headers, body=body, provider='openai')
    limit = LIMITS[call]
    count, logged, result, failure = 0, [0], (), model_access.classify('openai', reason='timeout')
    while count < 3:
        model_client._verify(check)
        if count and still is not None and not still():
            break
        now = clock.now()
        until = deadline if limit is None else min(deadline, now + limit)
        if now >= until:
            break
        attempt = model_usage.Attempt.start(project=project, call=call, model=model, prices=settings['prices'],
                                            credentials=credentials)
        budget = until - attempt._started
        if budget <= 0:
            break

        def cancelled(usage, first_ms, request_id, attempt=attempt):
            logged[0] += model_client._account(attempt, memory, request_id=request_id, aborted=True)
        count += 1
        answer = model_transport.once(wire, deadline=until, started=attempt._started, connect=min(30, budget),
                                      gap=budget, check=check, on_cancel=cancelled,
                                      settle=SETTLE if limit is None else None)
        failure, tokens = answer.failure, None
        if failure is None:
            try:
                result, tokens = vectors(answer.text, len(sent), dims)
            except _Bad as bad:
                failure, tokens = model_access.classify('openai', reason=bad.code), bad.tokens
        logged[0] += model_client._account(attempt, memory,
                                           usage=None if tokens is None else {'prompt_tokens': tokens},
                                           failure=failure, request_id=answer.request)
        model_client._verify(check)
        if failure is None:
            break
        result = ()
        if call != 'embed-items' or failure.lasting or answer.cleanup_pending or count == 3:
            break
        pause = max((10, 60)[count - 1], answer.retry_after or 0)
        if pause > 300 or clock.now() + pause >= deadline or not model_client._wait(pause, deadline, check):
            break
    model_client._verify(check)
    return Result(result if failure is None else (), failure, count, logged[0])

