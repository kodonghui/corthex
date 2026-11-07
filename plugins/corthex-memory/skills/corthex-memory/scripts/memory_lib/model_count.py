"""API-009: count the input tokens of a curator request (SPEC-015; TASK-080).

The count goes to `/v1/messages/count_tokens` with the body that the request
would send, less `max_tokens` and `stream`, and the same headers. It costs
nothing and has its own usage line: `count-tokens`, the count as `input`, the
cost 0. One attempt within 60 seconds and no retry: when counting fails or
comes late, the caller's safe estimate decides alone (TASK-084).
"""
import copy
from dataclasses import dataclass
import os

from . import clock, configuration, model_access, model_client, model_request, model_transport, model_usage, store

LIMIT = 60


@dataclass(frozen=True)
class Count:
    tokens: object   # the provider's count, or None when counting failed
    failure: object
    logged: int


def payload(sent):
    """The count request for a messages request that `model_request.build` made."""
    if not isinstance(sent, dict) or not isinstance(sent.get('url'), str) or not sent['url'].endswith('/v1/messages'):
        raise ValueError('invalid memory count request')
    body = {key: value for key, value in sent['body'].items() if key not in ('max_tokens', 'stream')}
    return dict(url=sent['url'] + '/count_tokens', headers=dict(sent['headers']), body=body, provider='anthropic')


def _tokens(text):
    value = store.json_document(text.encode('utf-8'))
    if not isinstance(value, dict) or type(value.get('input_tokens')) is not int or value['input_tokens'] < 0:
        raise ValueError('invalid memory token count')
    return value['input_tokens']


def count(memory, *, project, instructions, source, schema, config, check, deadline=None):
    """Count the tokens that `model_client.send` would send for the same request."""
    if not callable(check):
        raise TypeError('original memory client check required')
    begun = clock.now()
    if deadline is not None:
        store.MemoryStore._deadline(deadline)
    deadline = begun + LIMIT if deadline is None else min(deadline, begun + LIMIT)
    model_client._verify(check)
    credentials = model_access.Credentials.read()
    if credentials.headers('anthropic') is None:
        raise model_client.MissingKey()
    config, schema = copy.deepcopy(config), copy.deepcopy(schema)
    settings = configuration.prepare(config, temporary=False).values
    sent, _ = model_request.build(config=config, instructions=instructions, source=source, schema=schema,
                                  credentials=credentials, environment=dict(os.environ))
    wire = payload(sent)
    model_client._verify(check)
    if clock.now() >= deadline:
        return Count(None, model_access.classify('anthropic', reason='timeout'), 0)
    attempt = model_usage.Attempt.start(project=project, call='count-tokens', model=settings['models']['curator'],
                                        prices=settings['prices'], credentials=credentials,
                                        instructions=instructions)
    logged = [0]

    def cancelled(usage, first_ms, request_id):
        logged[0] += model_client._account(attempt, memory, request_id=request_id, aborted=True)
    answer = model_transport.once(wire, deadline=deadline, started=attempt._started, connect=min(30, LIMIT),
                                  gap=LIMIT, check=check, on_cancel=cancelled)
    tokens, failure = None, answer.failure
    if failure is None:
        try:
            tokens = _tokens(answer.text)
        except ValueError:
            failure = model_access.classify('anthropic', reason='bad-answer')
    logged[0] += model_client._account(attempt, memory, usage=None if tokens is None else {'input_tokens': tokens},
                                       failure=failure, request_id=answer.request)
    model_client._verify(check)
    return Count(tokens, failure, logged[0])
