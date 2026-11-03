"""A bounded Unix terminal for the installed CLI, not a hook-input simulator."""
import errno
import os
from pathlib import Path
import select
import signal
import struct
import time


class Terminal:
    def __init__(self, command, environment, cwd, output):
        if os.name == "nt":
            raise RuntimeError("Windows native terminal observations are operator-run")
        import fcntl
        import pty
        import termios
        self.output = Path(output)
        self.data = bytearray()
        self.pid, self.fd = pty.fork()
        if not self.pid:
            os.chdir(str(cwd))
            environment = dict(environment, TERM="xterm-256color", COLUMNS="120", LINES="35")
            os.execvpe(command[0], command, environment)
        self.status = None
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 35, 120, 0, 0))
        except BaseException:
            self.close()
            raise

    def pump(self):
        if select.select([self.fd], [], [], .05)[0]:
            try:
                chunk = os.read(self.fd, 65536)
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
                chunk = b""
            self.data.extend(chunk)
            if b"\x1b[6n" in chunk:
                os.write(self.fd, b"\x1b[1;1R")
        if self.status is None:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.status = status

    def wait(self, predicate, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.pump()
            if predicate():
                return
            if self.status is not None:
                break
        raise AssertionError("Native terminal did not reach its expected state")

    def key(self, value, pause=.2):
        os.write(self.fd, value)
        deadline = time.monotonic() + pause
        while time.monotonic() < deadline and self.status is None:
            self.pump()

    def line(self, text):
        # Keep Enter separate from paste so the host's paste-burst parser submits it.
        self.key(b"\x1b[200~" + text.encode("utf-8") + b"\x1b[201~", pause=.3)
        self.key(b"\r")

    def close(self):
        try:
            if self.status is None:
                try:
                    os.write(self.fd, b"\x03")
                    self.pump()
                    if self.status is None:
                        os.write(self.fd, b"\x03")
                    self.wait(lambda: self.status is not None, timeout=10)
                except (AssertionError, OSError):
                    pass
                finally:
                    if self.status is None:
                        # pty.fork owns this new session/group. End its foreground
                        # children as well as the CLI if graceful shutdown fails.
                        try:
                            os.killpg(self.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        _, self.status = os.waitpid(self.pid, 0)
        finally:
            try:
                self.output.write_bytes(self.data)
            finally:
                os.close(self.fd)
        return self.status
