"""Configured-origin-only, nonredirecting HTTP with environment-only tokens."""
import json
import http.client
import socket
import threading
import urllib.error
import urllib.parse
import urllib.request

RETRY_STATUSES = {429, 500, 502, 503, 504}
RETRY_ACCESS = {"access_missing", "access_other_app"}
MAX_ANSWER_BYTES = 64 * 1024 * 1024


class Deadline:
    """Cancel a whole request, including slow headers and trickling bodies.

    urllib's timeout applies to individual socket operations. The caller also
    bounds the worker's wait, because a platform DNS lookup can outlast it.
    A lookup that returns after cancellation cannot send HTTP credentials.
    """
    def __init__(self):
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.sockets = []

    def watch(self, sock):
        with self.lock:
            if self.cancelled.is_set():
                try:
                    sock.close()
                except OSError:
                    pass
                raise socket.timeout()
            self.sockets.append(sock)

    def abort(self):
        with self.lock:
            self.cancelled.set()
            for sock in self.sockets:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    sock.close()
                except OSError:
                    pass


def guarded_connection(base, deadline):
    class Connection(base):
        def connect(self):
            if deadline.cancelled.is_set():
                raise socket.timeout()
            super().connect()
            deadline.watch(self.sock)

        def send(self, data):
            if deadline.cancelled.is_set():
                raise socket.timeout()
            super().send(data)
    return Connection


class DeadlineHTTP(urllib.request.HTTPHandler):
    def __init__(self, deadline):
        super().__init__()
        self.connection = guarded_connection(http.client.HTTPConnection, deadline)

    def http_open(self, request):
        return self.do_open(self.connection, request)


class DeadlineHTTPS(urllib.request.HTTPSHandler):
    def __init__(self, deadline):
        super().__init__()
        self.connection = guarded_connection(http.client.HTTPSConnection, deadline)

    def https_open(self, request):
        return self.do_open(self.connection, request, context=self._context)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def result(outcome, answer=None, problem=None, failure=None, retry=False):
    return {"outcome": outcome, "answer": answer, "problem": problem, "failure": failure, "retry": retry}


class Client:
    def __init__(self, base, env, version="0.2.2", timeout=30):
        parsed = urllib.parse.urlsplit(base)
        local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
        if (parsed.scheme not in ("https", "http") or not parsed.hostname or
                (parsed.scheme == "http" and not local) or parsed.username or parsed.password or parsed.query or parsed.fragment or
                any(ord(c) < 33 for c in base)):
            raise ValueError("the NEXUS address must be HTTPS, or HTTP on this device, with no credentials, query or fragment")
        if parsed.port is not None and not 0 < parsed.port <= 65535:
            raise ValueError("the NEXUS address has an invalid port")
        if not isinstance(timeout, (float, int)) or not 0 < timeout <= 30:
            raise ValueError("the request timeout must be positive and at most 30 seconds")
        self.base, self.local, self.version, self.timeout = base.rstrip("/"), local, version, timeout
        self._token = (env.get("CORTHEX_NEXUS_CLIENT_ID"), env.get("CORTHEX_NEXUS_CLIENT_SECRET"))

    def __repr__(self):
        return "NexusClient(configured origin, environment-only credentials)"

    def call(self, method, path, body=None, session=None, write=None):
        if (not isinstance(path, str) or not path.startswith("/api/") or
                any(x in path for x in ("?", "#", "\\", "\r", "\n")) or
                any(part in (".", "..") for part in urllib.parse.unquote(path).split("/"))):
            raise ValueError("a NEXUS request needs its generated API path")
        if not self.local and not all(self._token):
            return result("failed", failure="no service token", retry=True)
        deadline, answers = Deadline(), []

        def run():
            try:
                answers.append(self._call(method, path, body, session, write, deadline))
            except (ValueError, OSError, http.client.HTTPException):
                answers.append(result("failed", failure="invalid transport or server answer", retry=True))

        worker = threading.Thread(target=run, name="nexus-request", daemon=True)
        worker.start()
        worker.join(self.timeout)
        if worker.is_alive():
            deadline.abort()
            return result("failed", failure="timeout", retry=True)
        deadline.abort()
        return answers[0] if answers else result("failed", failure="invalid server answer", retry=True)

    def _call(self, method, path, body, session, write, deadline):
        opener = urllib.request.build_opener(NoRedirect(), DeadlineHTTP(deadline), DeadlineHTTPS(deadline),
                                            *([urllib.request.ProxyHandler({})] if self.local else []))
        encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf8") if body is not None else None
        request = urllib.request.Request(self.base + path, data=encoded, method=method)
        request.add_header("Accept", "application/json, application/problem+json")
        request.add_header("User-Agent", "corthex-nexus/" + self.version)
        if encoded is not None:
            request.add_header("Content-Type", "application/json")
        if session:
            request.add_header("Nexus-Session", session)
        if write:
            request.add_header("Idempotency-Key", '"' + write + '"')
        if all(self._token):
            request.add_header("CF-Access-Client-Id", self._token[0])
            request.add_header("CF-Access-Client-Secret", self._token[1])
        try:
            with opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_ANSWER_BYTES + 1)
                if len(raw) > MAX_ANSWER_BYTES:
                    return result("failed", failure="server answer too large", retry=True)
                try:
                    answer = json.loads(raw.decode("utf8"))
                except (ValueError, UnicodeError):
                    return result("failed", failure="invalid server answer", retry=True)
                if not isinstance(answer, dict):
                    return result("failed", failure="invalid server answer", retry=True)
                return result("done", answer=answer)
        except urllib.error.HTTPError as error:
            status = error.code
            try:
                raw = error.read(8192)
                problem = json.loads(raw.decode("utf8"))
            except (ValueError, OSError, UnicodeError):
                problem = None
            finally:
                error.close()
            if not isinstance(problem, dict) or not isinstance(problem.get("code"), str):
                problem = None
            if status in (301, 302, 303, 307, 308) or (status in (401, 403) and problem is None):
                return result("refused", failure="refused token", retry=True)
            if problem:
                return result("refused", problem=problem, retry=status in RETRY_STATUSES or problem["code"] in RETRY_ACCESS)
            return result("failed", failure="HTTP " + str(status), retry=status in RETRY_STATUSES)
        except (socket.timeout, TimeoutError):
            return result("failed", failure="timeout", retry=True)
        except urllib.error.URLError as error:
            timeout = isinstance(error.reason, (socket.timeout, TimeoutError))
            return result("failed", failure="timeout" if timeout else "no network", retry=True)
        except OSError:
            return result("failed", failure="no network", retry=True)
