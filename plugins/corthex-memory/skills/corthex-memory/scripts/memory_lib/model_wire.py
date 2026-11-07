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


def _target(url, path):
    """The parsed URL: https, or http to a loopback host only, ending with the API's path."""
    if not isinstance(url, str) or any(not 33 <= ord(c) <= 126 for c in url):raise ValueError()
    target = urlsplit(url)
    if (target.scheme not in ('http', 'https') or not target.hostname or target.username is not None or
            target.password is not None or target.fragment or target.query or
            target.scheme == 'http' and target.hostname not in ('localhost', '127.0.0.1', '::1')):
        raise ValueError()
    if not url.endswith(path):raise ValueError()
    return target


def _opener(target, tls, gap):
    """A urllib opener that reports the read phase and every byte, follows no redirect
    and keeps the API's authentication away from an environment proxy on loopback http."""
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
    return request.build_opener(*handlers)


def _request_id(response, name, secret):
    value = response.headers.get(name)
    if (not isinstance(value, str) or not value or len(value) > 200 or
            any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in value) or
            secret and secret in value):
        return None
    return value


def _once(value):
    if not isinstance(value, dict) or set(value) != {'url', 'headers', 'body', 'schema', 'connect', 'gap'}:
        raise ValueError()
    target = _target(value['url'], '/v1/messages')
    if not isinstance(value['headers'], dict):
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
    opener = _opener(target, _tls_context(), gap)
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
        request_id = _request_id(response, 'request-id', secret)
        status = response.status
        retry_after = _retry_after(response.headers.get('retry-after')) if status != 200 else None
        _emit({'response': {'status': status, 'request': request_id, 'retry_after': retry_after}})
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


# The JSON endpoints: Anthropic's token count (API-009) and OpenAI's embeddings (API-010 to API-012).
_JSON = {'anthropic': ('/v1/messages/count_tokens', 'request-id',
                       {'content-type', 'user-agent', 'x-api-key', 'anthropic-version'}),
         'openai': ('/v1/embeddings', 'x-request-id', {'content-type', 'user-agent', 'authorization'})}
JSON_BYTES = 8*1024*1024


def _json_headers(headers, provider):
    """The exact header set of the provider; returns the headers and the key they carry."""
    if not isinstance(headers, dict):raise ValueError()
    if any(not isinstance(k, str) or not isinstance(v, str) or any(not 32 <= ord(c) <= 126 for c in v)
           for k, v in headers.items()):
        raise ValueError()
    lowered = {k.lower(): v for k, v in headers.items()}
    if len(lowered) != len(headers) or set(lowered) != _JSON[provider][2]:raise ValueError()
    if lowered['content-type'] != 'application/json' or not lowered['user-agent'].startswith('corthex-memory/'):
        raise ValueError()
    if provider == 'anthropic':
        secret = lowered['x-api-key']
        if lowered['anthropic-version'] != '2026-10-21':raise ValueError()
    else:
        if not lowered['authorization'].startswith('Bearer '):raise ValueError()
        secret = lowered['authorization'][len('Bearer '):]
    if not secret or any(not 33 <= ord(c) <= 126 for c in secret):raise ValueError()
    return lowered, secret


def _json_once(value):
    """One JSON POST: the answer's text when the API says 200 with a JSON body, else a closed failure."""
    if not isinstance(value, dict) or set(value) != {'url', 'headers', 'body', 'provider', 'connect', 'gap'}:
        raise ValueError()
    provider = value['provider']
    if not isinstance(provider, str) or provider not in _JSON:raise ValueError()
    path, id_header, _ = _JSON[provider]
    target = _target(value['url'], path)
    headers, secret = _json_headers(value['headers'], provider)
    if not isinstance(value['body'], dict):raise ValueError()
    if any(type(value[k]) not in (int, float) or not 0 < value[k] <= 1800 for k in ('connect', 'gap')):
        raise ValueError()
    connect, gap = value['connect'], value['gap']
    opener = _opener(target, _tls_context(), gap)
    body = json.dumps(value['body'], ensure_ascii=False, allow_nan=False).encode('utf-8')
    req = request.Request(value['url'], body, headers, method='POST')
    request_id, retry_after, failure, text, response = None, None, None, '', None
    try:
        _emit({'phase': 'connect'})
        try:
            response = opener.open(req, timeout=connect)
        except error.HTTPError as caught:
            response = caught
        request_id = _request_id(response, id_header, secret)
        status = response.status
        retry_after = _retry_after(response.headers.get('retry-after')) if status != 200 else None
        _emit({'response': {'status': status, 'request': request_id, 'retry_after': retry_after}})
        if status != 200:
            if not 400 <= status <= 599:
                failure = model_access.Failure('invalid_request_error', True, status)
            else:
                kind = code = None
                try:
                    raw = response.read(65537)
                    document = store.json_document(raw) if len(raw) <= 65536 else None
                    if isinstance(document, dict) and isinstance(document.get('error'), dict):
                        kind, code = document['error'].get('type'), document['error'].get('code')
                except Exception:
                    pass
                failure = model_access.classify(provider, status=status, error_type=kind, error_code=code)
        elif response.headers.get_content_type() != 'application/json':
            failure = model_access.classify(provider, reason='bad-answer')
        else:
            chunks, size = [], 0
            while True:
                raw = response.read1(64*1024)
                if not raw:break
                size += len(raw)
                if size > JSON_BYTES:raise ValueError()
                chunks.append(raw)
            data = b''.join(chunks)
            text = data.decode('utf-8')
            # The key, also when escaped, makes the whole answer unusable.
            if secret in text or _contains(store.json_document(data), secret):
                failure, text = model_access.classify(provider, reason='bad-answer'), ''
    except (TimeoutError, socket.timeout):
        failure = model_access.classify(provider, reason='timeout')
    except error.URLError as caught:
        reason = 'timeout' if isinstance(caught.reason, (TimeoutError, socket.timeout)) else 'network'
        failure = model_access.classify(provider, reason=reason)
    except (ValueError, UnicodeError):
        failure = model_access.classify(provider, reason='bad-answer')
    except Exception:
        failure = model_access.classify(provider, reason='network')
    finally:
        if response is not None:
            try:response.close()
            except Exception:pass
    return {'text': text if failure is None else '', 'usage': {},
            'failure': _failure(failure) if failure is not None else None,
            'request': request_id, 'retry_after': retry_after}


def main():
    try:
        raw = sys.stdin.buffer.readline(8*1024*1024+1)
        if len(raw) > 8*1024*1024 or not raw.endswith(b'\n'):raise ValueError()
        value = store.json_document(raw)
        value = _json_once(value) if isinstance(value, dict) and 'provider' in value else _once(value)
    except Exception:
        value = {'text': '', 'usage': {}, 'failure': _failure(model_access.classify('anthropic', reason='network')),
                 'request': None, 'retry_after': None}
    _emit({'final': value})


if __name__ == '__main__':
    main()
