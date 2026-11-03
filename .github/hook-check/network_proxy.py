"""Loopback-only HTTP(S) egress observer for synthetic installed-host runs."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading


class NetworkProxy:
    def __init__(self):
        self.rows = []
        rows = self.rows

        class Handler(BaseHTTPRequestHandler):
            def parse_request(self):
                accepted = super().parse_request()
                if accepted:
                    rows.append({"method": self.command, "target": self.path})
                return accepted

            def record(self):
                self.send_response(502)
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True

            do_GET = do_POST = do_CONNECT = record

            def log_message(self, *unused):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        port = self.server.server_address[1]
        control = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        control.request("GET", "http://hookcheck.invalid/positive-control")
        response = control.getresponse()
        response.read()
        self.positive_control = response.status == 502 and len(rows) == 1
        control.close()
        rows.clear()
        self.url = "http://127.0.0.1:" + str(port)

    def environment(self):
        return {"HTTP_PROXY": self.url, "HTTPS_PROXY": self.url, "ALL_PROXY": self.url,
                "NO_PROXY": "127.0.0.1,localhost"}

    def finish(self):
        self.server.shutdown()
        self.thread.join(2)
        self.server.server_close()
        return {"verified": self.positive_control and not self.rows, "positive_control": self.positive_control,
                "observed_requests": list(self.rows), "scope": "configured HTTP(S) proxy plus loopback model log; not OS-wide packet capture"}
