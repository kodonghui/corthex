"""One isolated wire attempt. Private stdin/stdout pipes; no store or retry.

The parent owns deadlines, cancellation, eligibility and per-attempt accounting.
This child never writes files, reports exception text or reads host API keys.
"""
import json
import ipaddress
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
from pathlib import Path
import socket
import ssl
import sys
from urllib import error, request
from urllib.parse import urlsplit
import http.client

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from memory_lib import clock, model_access, model_stream, store
else:
    from . import clock, model_access, model_stream, store


def _emit(value):
    raw = (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))+'\n').encode('utf-8')
    sys.stdout.buffer.write(raw); sys.stdout.buffer.flush()


def _failure(value):
    return {'code': value.code, 'lasting': value.lasting, 'status': value.status}


def _retry_after(value):
    if not isinstance(value, str) or len(value) > 100:return None
    try:
        try:seconds = float(value)
        except ValueError:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:return None
            seconds = (date-datetime.now(timezone.utc)).total_seconds()
        return min(301, max(0, seconds)) if math.isfinite(seconds) else None
    except Exception:
        return None


def _contains(value, secret):
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, str) and secret in current:return True
        if isinstance(current, dict):pending.extend(current); pending.extend(current.values())
        elif isinstance(current, list):pending.extend(current)
    return False


def _tls_context():
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _once(value):
    if not isinstance(value, dict) or set(value) != {'url', 'headers', 'body', 'schema', 'connect', 'gap'}:
        raise ValueError()
    if not isinstance(value['url'], str) or any(not 33 <= ord(c) <= 126 for c in value['url']):raise ValueError()
    target = urlsplit(value['url'])
    if (target.scheme not in ('http', 'https') or not target.hostname or target.username is not None or
            target.password is not None or target.fragment or target.query or
            target.scheme == 'http' and target.hostname not in ('localhost', '127.0.0.1', '::1')):
        raise ValueError()
    if not value['url'].endswith('/v1/messages') or not isinstance(value['headers'], dict):
        raise ValueError()
    if any(not isinstance(k, str) or k.lower() not in ('content-type', 'user-agent', 'x-api-key', 'anthropic-version') or
           not isinstance(v, str) or any(not 32 <= ord(c) <= 126 for c in v) for k, v in value['headers'].items()):
        raise ValueError()
    headers = {k.lower(): v for k, v in value['headers'].items()}
    if (len(headers) != len(value['headers']) or set(headers) != {'content-type', 'user-agent', 'x-api-key', 'anthropic-version'} or
            not headers['x-api-key'] or any(not 33 <= ord(c) <= 126 for c in headers['x-api-key']) or
            headers['content-type'] != 'application/json' or headers['anthropic-version'] != '2026-10-21' or
            not headers['user-agent'].startswith('corthex-memory/')):
        raise ValueError()
    value = dict(value, headers=headers)
    if any(type(value[k]) not in (int, float) or not 0 < value[k] <= 1800 for k in ('connect', 'gap')):
        raise ValueError()
    connect, gap = value['connect'], value['gap']
    secret = next((v for k, v in value['headers'].items() if k.lower() == 'x-api-key'), None)
    tls = _tls_context()
    reading = [False]
    def ready(connection):
        connection.sock.settimeout(gap)
        reading[0] = True
        _emit({'phase': 'read'})
    class HTTP(http.client.HTTPConnection):
        def connect(self):
            super().connect()
            if not ipaddress.ip_address(self.sock.getpeername()[0]).is_loopback:
                self.sock.close(); raise ValueError()
            ready(self)
    class HTTPS(http.client.HTTPSConnection):
        def connect(self):
            super().connect(); ready(self)
    class HTTPHandler(request.HTTPHandler):
        def http_open(self, req):return self.do_open(HTTP, req)
    class HTTPSHandler(request.HTTPSHandler):
        def https_open(self, req):return self.do_open(HTTPS, req, context=tls)
    class NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):return None
    original_read = socket.SocketIO.readinto
    def readinto(stream, buffer):
        size = original_read(stream, buffer)
        if size and reading[0]:_emit({'phase': 'byte'})
        return size
    # Private process: proxy/certificate behavior stays with the stdlib opener.
    socket.SocketIO.readinto = readinto
    handlers = [HTTPHandler(), HTTPSHandler(context=tls), NoRedirect()]
    if target.scheme == 'http':handlers.append(request.ProxyHandler({}))
    opener = request.build_opener(*handlers)
    body = json.dumps(value['body'], ensure_ascii=False, allow_nan=False).encode('utf-8')
    req = request.Request(value['url'], body, value['headers'], method='POST')
    decoder = model_stream.Decoder(started=clock.now())
    request_id, retry_after, failure = None, None, None
    response = None
    try:
        _emit({'phase': 'connect'})
        try:
            response = opener.open(req, timeout=connect)
        except error.HTTPError as caught:
            response = caught
        request_id = response.headers.get('request-id')
        if (not isinstance(request_id, str) or not request_id or len(request_id) > 200 or
                any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in request_id) or
                secret and secret in request_id):request_id = None
        status = response.status
        _emit({'response': {'status': status, 'request': request_id}})
        if status != 200:
            if not 400 <= status <= 599:
                failure = model_access.Failure('invalid_request_error', True, status)
            else:
                kind = None
                try:
                    raw = response.read(65537)
                    document = store.json_document(raw) if len(raw) <= 65536 else None
                    if isinstance(document, dict) and isinstance(document.get('error'), dict):
                        kind = document['error'].get('type')
                except Exception:
                    pass
                failure = model_access.classify('anthropic', status=status, error_type=kind)
            retry_after = _retry_after(response.headers.get('retry-after'))
        else:
            if response.headers.get_content_type() != 'text/event-stream':
                failure = model_access.classify('anthropic', reason='bad-answer')
            while failure is None and not decoder.done and decoder.failure is None:
                raw = response.read1(64*1024)
                if not raw:break
                previous = decoder.first_ms
                previous_usage = dict(decoder.usage)
                decoder.feed(raw)
                if decoder.usage != previous_usage:_emit({'usage': decoder.usage})
                if previous is None and decoder.first_ms is not None:_emit({'phase': 'text'})
    except (TimeoutError, socket.timeout):
        failure = model_access.classify('anthropic', reason='timeout')
    except error.URLError as caught:
        reason = 'timeout' if isinstance(caught.reason, (TimeoutError, socket.timeout)) else 'network'
        failure = model_access.classify('anthropic', reason=reason)
    except Exception:
        failure = model_access.classify('anthropic', reason='network')
    finally:
        if response is not None:
            try:response.close()
            except Exception:pass
    answer = decoder.finish(schema=value['schema'])
    failure = failure or answer.failure
    if failure is None:
        if secret and (secret in answer.text or _contains(answer.value, secret)):
            failure = model_access.classify('anthropic', reason='bad-answer')
    return {'text': answer.text if failure is None else '', 'usage': answer.usage,
            'failure': _failure(failure) if failure is not None else None,
            'request': request_id, 'retry_after': retry_after}


def main():
    try:
        raw = sys.stdin.buffer.readline(8*1024*1024+1)
        if len(raw) > 8*1024*1024 or not raw.endswith(b'\n'):raise ValueError()
        value = _once(store.json_document(raw))
    except Exception:
        value = {'text': '', 'usage': {}, 'failure': _failure(model_access.classify('anthropic', reason='network')),
                 'request': None, 'retry_after': None}
    _emit({'final': value})


if __name__ == '__main__':
    main()
