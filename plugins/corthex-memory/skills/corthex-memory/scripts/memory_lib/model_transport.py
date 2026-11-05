"""Bounded lifetime for an isolated wire attempt; no retries or store effects."""
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading

from . import clock, model_access, model_usage, store

_ENV = 'SYSTEMROOT WINDIR TEMP TMP PATH HTTPS_PROXY HTTP_PROXY NO_PROXY ALL_PROXY https_proxy http_proxy no_proxy all_proxy SSL_CERT_FILE SSL_CERT_DIR'.split()


@dataclass(frozen=True)
class Response:
    text: str = field(repr=False)
    usage: dict
    first_ms: object
    failure: object
    request: object = field(repr=False)
    retry_after: object
    cleanup_pending: bool = False


def _failed(code):
    return Response('', {}, None, model_access.classify('anthropic', reason=code), None, None)


def _tokens(value):
    if not isinstance(value, dict):raise ValueError()
    tokens = model_usage._tokens('curate', value)
    mapping = {'input': 'input_tokens', 'output': 'output_tokens',
               'cache_write': 'cache_creation_input_tokens', 'cache_read': 'cache_read_input_tokens'}
    return {mapping[k]: n for k, n in tokens.items()}


def _partial(state, code):
    failure = model_access.classify('anthropic', reason=code)
    status = state['status']
    if status is not None and status >= 400:
        failure = model_access.classify('anthropic', status=status)
    return Response('', dict(state['usage']), state['first'], failure, state['request'], None)


def _result(value, first):
    if not isinstance(value, dict) or set(value) != {'text', 'usage', 'failure', 'request', 'retry_after'}:
        raise ValueError()
    if not isinstance(value['text'], str) or len(value['text'].encode('utf-8')) > 8*1024*1024:
        raise ValueError()
    usage = _tokens(value['usage'])
    failure = value['failure']
    if failure is not None:
        if (not isinstance(failure, dict) or set(failure) != {'code', 'lasting', 'status'} or
                failure['code'] not in model_access._KINDS or type(failure['lasting']) is not bool or
                failure['status'] is not None and (type(failure['status']) is not int or not 100 <= failure['status'] <= 599)):
            raise ValueError()
        failure = model_access.Failure(failure['code'], failure['lasting'], failure['status'])
    request = value['request']
    if request is not None and (not isinstance(request, str) or not model_usage._REQUEST.fullmatch(request)):
        raise ValueError()
    retry = value['retry_after']
    if retry is not None and (type(retry) not in (int, float) or not math.isfinite(retry) or not 0 <= retry <= 301):
        raise ValueError()
    return Response(value['text'] if failure is None else '', usage, first, failure, request, retry)


def once(payload, *, deadline, started, connect=30, gap=600, check):
    """Count startup/DNS/TLS/headers/body under the parent's original deadline.

    The required original caller check retains eligibility/ownership authority;
    its exception is preserved after canceling the private child. Keys/body use
    stdin only. The child has no store, lease or project path and cannot retry.
    """
    store.MemoryStore._deadline(deadline)
    if not callable(check) or any(type(n) not in (int, float) or not math.isfinite(n) or n <= 0 for n in (connect, gap)):
        raise ValueError('invalid memory transport budget')
    if type(started) not in (int, float) or not math.isfinite(started) or started > clock.now():
        raise ValueError('invalid memory transport clock')
    def verify():
        if check() is not None:raise TypeError('memory transport check must return only None')
    verify()
    if clock.now() >= deadline:return _failed('timeout')
    if not Path(sys.executable).is_absolute():raise ValueError('absolute memory interpreter required')
    connect, gap = min(connect, 30), min(gap, 600)
    wire = dict(payload, connect=connect, gap=gap)
    encoded = (json.dumps(wire, ensure_ascii=False, allow_nan=False)+'\n').encode('utf-8')
    if len(encoded) > 8*1024*1024:raise ValueError('memory wire input too large')
    environment = {name: os.environ[name] for name in _ENV if name in os.environ}
    verify()
    if clock.now() >= min(deadline, started+connect):return _failed('timeout')
    try:
        process = subprocess.Popen([sys.executable, '-I', '-B', '-X', 'utf8', str(Path(__file__).with_name('model_wire.py').resolve())],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), close_fds=True)
    except OSError:
        verify()
        return _failed('timeout' if clock.now() >= min(deadline, started+connect) else 'network')
    mutex, wake = threading.Lock(), threading.Event()
    state = {'phase': 'connect', 'connect_end': started+connect, 'last_byte': None, 'first': None,
             'result': None, 'status': None, 'request': None, 'usage': {}}
    def failed(code):
        with mutex:
            if state['result'] is None:state['result'] = _partial(state, code)
            wake.set()
    def writer():
        try:
            with process.stdin:
                process.stdin.write(encoded); process.stdin.flush()
        except Exception:failed('network')
    def reader():
        try:
            with process.stdout:
                while True:
                    raw = process.stdout.readline(18*1024*1024+1)
                    if not raw:break
                    if len(raw) > 18*1024*1024 or not raw.endswith(b'\n'):raise ValueError()
                    item = store.json_document(raw)
                    if not isinstance(item, dict):raise ValueError()
                    with mutex:
                        end = min(deadline, state['connect_end'] if state['phase'] == 'connect' else state['last_byte']+gap)
                        if clock.now() >= end:
                            if state['result'] is None:state['result'] = _partial(state, 'timeout')
                            wake.set(); return
                        if set(item) == {'final'}:
                            result = _result(item['final'], state['first'])
                            if state['result'] is None:state['result'] = result
                            wake.set(); return
                        if set(item) == {'response'}:
                            meta = item['response']
                            if (state['phase'] != 'read' or state['status'] is not None or not isinstance(meta, dict) or
                                    set(meta) != {'status', 'request'} or type(meta['status']) is not int or
                                    not 100 <= meta['status'] <= 599 or meta['request'] is not None and
                                    (not isinstance(meta['request'], str) or not model_usage._REQUEST.fullmatch(meta['request']))):
                                raise ValueError()
                            state['status'], state['request'] = meta['status'], meta['request']
                            wake.set(); continue
                        if set(item) == {'usage'}:
                            if state['phase'] != 'read' or state['status'] != 200:raise ValueError()
                            state['usage'].update(_tokens(item['usage'])); wake.set(); continue
                        if set(item) != {'phase'}:raise ValueError()
                        phase = item['phase']
                        if phase == 'connect':
                            if state['phase'] != 'connect':raise ValueError()
                        elif phase == 'read':
                            if state['phase'] != 'connect':raise ValueError()
                            state['phase'], state['last_byte'] = 'read', clock.now()
                        elif phase in ('byte', 'text'):
                            if state['phase'] != 'read':raise ValueError()
                            if phase == 'byte':state['last_byte'] = clock.now()
                            elif state['first'] is None:state['first'] = max(0, int((clock.now()-started)*1000))
                        else:raise ValueError()
                        wake.set()
            failed('network')
        except Exception:failed('bad-answer')
    threads = [threading.Thread(target=writer, daemon=True), threading.Thread(target=reader, daemon=True)]
    answer, original_error, pending = None, None, False
    try:
        verify()
        if clock.now() >= min(deadline, state['connect_end']):answer = _partial(state, 'timeout')
        if answer is None:
            for thread in threads:thread.start()
        while answer is None:
            verify()
            with mutex:
                end = min(deadline, state['connect_end'] if state['phase'] == 'connect' else state['last_byte']+gap)
                left = end-clock.now()
                if left <= 0:
                    answer = _partial(state, 'timeout'); break
                if state['result'] is not None:
                    answer = state['result']; break
                wake.clear()
            wake.wait(min(.05, left))
        verify()
    except BaseException as caught:
        original_error = caught
    finally:
        # This process is ours and has no data/lease effects to roll back.
        try:
            if process.poll() is None:process.kill()
            process.wait(timeout=.2)
        except Exception:
            pending = True
        for thread, stream in zip(threads, (process.stdin, process.stdout)):
            if thread.ident is not None:thread.join(timeout=.1)
            else:stream.close()
            if thread.is_alive():pending = True
    if original_error is not None:raise original_error
    return Response(answer.text, answer.usage, answer.first_ms, answer.failure,
                    answer.request, answer.retry_after, pending)
