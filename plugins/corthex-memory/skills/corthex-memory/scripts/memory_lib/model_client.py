"""One curator retry owner; original caller gates retain all apply authority."""
from dataclasses import dataclass, field
import copy
import os
import time

from . import clock, configuration, model_access, model_request, model_transport, model_usage, store


class MissingKey(ValueError):
    def __init__(self):super().__init__('dedicated memory API key missing')


@dataclass(frozen=True)
class Result:
    response: model_transport.Response
    document: str = field(repr=False)
    attempts: int
    logged: int


def _verify(check):
    if check() is not None:raise TypeError('memory client check must return only None')


def _wait(seconds, deadline, check):
    until = clock.now()+seconds
    while clock.now() < until:
        _verify(check)
        left = min(until, deadline)-clock.now()
        if left <= 0:return False
        time.sleep(min(.1,left))
    _verify(check)
    return clock.now() < deadline


def _account(attempt, memory, **row):
    try:return bool(attempt.record(memory,clock.now()+1,**row))
    except Exception:return False


def send(memory, *, project, instructions, source, schema, config, check, deadline=None, size=None):
    """Use dedicated credentials; return actual sent context, counters and limits.

    No enabled-project, consent, source/provenance, initialization or application
    authority is inferred from a valid response. This is an internal sending port.
    `size` is a curate request's size fields (TBL-003), written on each attempt's line.
    """
    if not callable(check):raise TypeError('original memory client check required')
    begun = clock.now()
    if deadline is not None:store.MemoryStore._deadline(deadline)
    deadline = begun+1800 if deadline is None else min(deadline,begun+1800)
    _verify(check)
    credentials = model_access.Credentials.read()
    if credentials.headers('anthropic') is None:raise MissingKey()
    config, schema = copy.deepcopy(config), copy.deepcopy(schema)
    settings = configuration.prepare(config, temporary=False).values
    if instructions not in model_request._KINDS:raise ValueError('invalid memory instructions')
    call = 'curate' if instructions == 'curate-2' else 'consolidate'
    size = model_usage._size(call, copy.deepcopy(size))
    endpoint_name = 'CORTHEX_MEMORY_ANTHROPIC_BASE_URL'
    original_endpoint = os.environ.get(endpoint_name)
    count, logged, sent, answer = 0, [0], '', model_transport._failed('timeout')
    while count < 3:
        _verify(check)
        if clock.now() >= deadline:break
        environment = dict(os.environ)
        if original_endpoint is None:environment.pop(endpoint_name,None)
        else:environment[endpoint_name] = original_endpoint
        payload, candidate = model_request.build(config=config, instructions=instructions, source=source,
            schema=schema, credentials=credentials, environment=environment)
        _verify(check)
        if clock.now() >= deadline:break
        attempt = model_usage.Attempt.start(project=project, call=call, model=settings['models']['curator'],
            prices=settings['prices'], credentials=credentials, instructions=instructions, size=size)
        def cancelled(usage, first_ms, request_id):
            # No invented provider error and no extension of the network deadline.
            logged[0] += _account(attempt,memory,usage=usage,
                first_ms=first_ms,request_id=request_id,aborted=True)
        count += 1
        sent = candidate
        answer = model_transport.once(payload, deadline=deadline, started=attempt._started,
                                      check=check, on_cancel=cancelled)
        logged[0] += _account(attempt,memory,usage=answer.usage,
            failure=answer.failure,first_ms=answer.first_ms,request_id=answer.request)
        _verify(check)
        if answer.failure is None or answer.failure.lasting or answer.cleanup_pending or count == 3:break
        pause = max((10,60)[count-1], answer.retry_after or 0)
        if pause > 300 or clock.now()+pause >= deadline or not _wait(pause,deadline,check):break
    _verify(check)
    if clock.now() >= deadline and answer.failure is None:
        answer = model_transport.Response('',answer.usage,answer.first_ms,
            model_access.classify('anthropic',reason='timeout'),answer.request,None,answer.cleanup_pending)
    return Result(answer,sent,count,logged[0])
