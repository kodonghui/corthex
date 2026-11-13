"""A device's seven-day, per-project, idempotent write outbox.

The lease is an exclusive-create file. A short native OS lock serializes lease
creation, stale takeover and renewal; the OS releases that guard on a crash.
The guard never spans a network request. Each send uses its original write ID.
"""
import contextlib
import json
import os
import re
import secrets
import stat
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REQUESTS = {"comment", "reply", "answered", "decision", "proposal", "withdraw-proposal", "report-edit", "report-checkpoint"}
ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"
WRITE = re.compile(r"nw_[0-9a-hjkmnp-tv-z]{12}\Z")
PROJECT = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
SESSION = re.compile(r"[A-Za-z0-9._:-]{1,100}\Z")
SEVEN_DAYS = 7 * 24 * 60 * 60
COMMENT = re.compile(r"nc_[0-9a-hjkmnp-tv-z]{12}\Z")


class Busy(RuntimeError):
    pass


class Lost(RuntimeError):
    pass


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


@contextlib.contextmanager
def guard_file(path):
    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND
    for option in ("O_BINARY", "O_NOFOLLOW", "O_NONBLOCK", "O_NOINHERIT"):
        flags |= getattr(os, option, 0)
    descriptor = None
    try:
        descriptor = os.open(str(path), flags, 0o600)
        info, named = os.fstat(descriptor), path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                not stat.S_ISREG(named.st_mode) or getattr(named, "st_file_attributes", 0) & 0x400 or
                (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)):
            raise Busy("outbox guard must be a single-link regular file")
        handle = os.fdopen(descriptor, "a+b")
        descriptor = None
    except OSError:
        raise Busy("outbox guard is unavailable")
    finally:
        if descriptor is not None:
            os.close(descriptor)
    with handle:
        yield handle


@contextlib.contextmanager
def guard(path):
    with guard_file(path) as handle:
        handle.seek(0, 2)
        if not handle.tell():
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        start = time.monotonic()
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, BlockingIOError):
                if time.monotonic() - start >= 2:
                    raise Busy("another hub is updating the outbox lock")
                time.sleep(0.01)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class Lease:
    def __init__(self, root, project, clock=time.time):
        self.root, self.clock = Path(root), clock
        self.path = self.root / (project + ".lock")
        self.guard_path = self.root / (project + ".guard")
        self.owner = secrets.token_hex(16)

    def read(self):
        try:
            value = json.loads(self.path.read_text(encoding="utf8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def payload(self):
        return {"pid": os.getpid(), "time": self.clock(), "owner": self.owner}

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with guard(self.guard_path):
            if self.path.is_symlink():
                raise Busy("outbox lock is a symbolic link")
            if self.path.exists():
                if self.clock() - self.path.stat().st_mtime <= 120:
                    raise Busy("another hub is sending this project's outbox")
                self.path.unlink()
            with open(self.path, "x", encoding="utf8") as handle:
                json.dump(self.payload(), handle)
            os.utime(self.path, (self.clock(), self.clock()))
        return self

    @contextlib.contextmanager
    def owned(self):
        with guard(self.guard_path):
            if self.read().get("owner") != self.owner:
                raise Lost("the outbox lock was taken over")
            yield

    def renew(self):
        with self.owned():
            atomic(self.path, self.payload())
            os.utime(self.path, (self.clock(), self.clock()))

    def __exit__(self, *args):
        with guard(self.guard_path):
            if self.read().get("owner") == self.owner:
                self.path.unlink()


def utc_text(now):
    return datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def timestamp(text):
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.utcoffset() is not None else None
    except (ValueError, TypeError, AttributeError, OverflowError, OSError):
        return None


def request_path(project, request, path):
    base = "/api/spaces/" + project
    suffix = {
        "comment": r"/comments", "proposal": r"/proposals",
        "reply": r"/comments/nc_[0-9a-hjkmnp-tv-z]{12}/replies",
        "answered": r"/comments/nc_[0-9a-hjkmnp-tv-z]{12}/answered",
        "decision": r"/comments/nc_[0-9a-hjkmnp-tv-z]{12}/decisions",
        "withdraw-proposal": r"/proposals/np_[0-9a-hjkmnp-tv-z]{12}/withdraw",
        "report-edit": r"/edits/ne_[0-9a-hjkmnp-tv-z]{12}/report",
        "report-checkpoint": r"/checkpoints/nk_[0-9a-hjkmnp-tv-z]{12}/report",
    }.get(request)
    return bool(suffix and isinstance(path, str) and re.fullmatch(re.escape(base) + suffix, path))


def valid(data, project):
    return (isinstance(data, dict) and type(data.get("format")) is int and data.get("format") == 1 and
            data.get("project") == project and isinstance(data.get("write"), str) and WRITE.fullmatch(data["write"]) and
            isinstance(data.get("request"), str) and data["request"] in REQUESTS and request_path(project, data["request"], data.get("path")) and
            isinstance(data.get("session"), str) and SESSION.fullmatch(data["session"]) and
            timestamp(data.get("made")) is not None and isinstance(data.get("body"), dict) and
            type(data.get("tries")) is int and data["tries"] >= 0 and
            ("failure" not in data or isinstance(data["failure"], str) and len(data["failure"]) <= 120) and
            not (set(data) - {"format", "write", "project", "request", "path", "session", "made", "body", "tries", "failure"}))


def failure_of(attempt):
    if attempt.get("failure"):
        return attempt["failure"][:120]
    status = (attempt.get("problem") or {}).get("status")
    return "HTTP " + str(status) if type(status) is int else "refused by server"


def new_write(project, request, path, session, body, clock=time.time):
    data = {"format": 1, "write": "nw_" + "".join(secrets.choice(ALPHABET) for _ in range(12)),
            "project": project, "request": request, "path": path, "session": session,
            "made": utc_text(clock()), "body": body, "tries": 0}
    if not valid(data, project):
        raise ValueError("a queued write must match the agent request and session format")
    return data


def as_reply(data, attempt, clock=time.time):
    """SPEC-197: a checkpoint request that the server refuses because its stage has an open one goes as a reply on it.

    The reply has a new write ID and keeps the request's text, look_first, session and time, so that it takes the
    request's place in the outbox and its seven days.
    """
    problem = attempt.get("problem") or {}
    comment = problem.get("comment")
    if (attempt.get("outcome") != "refused" or problem.get("code") != "checkpoint_requested" or
            data["request"] not in ("comment", "reply") or data["body"].get("asks") != "checkpoint" or
            not isinstance(comment, str) or not COMMENT.fullmatch(comment)):
        return None
    body = {key: data["body"][key] for key in ("text", "asks", "look_first") if key in data["body"]}
    reply = new_write(data["project"], "reply", "/api/spaces/" + data["project"] + "/comments/" + comment + "/replies",
                      data["session"], body, clock)
    reply["made"] = data["made"]
    return reply


class Outbox:
    def __init__(self, home, project, clock=time.time):
        if not isinstance(project, str) or not PROJECT.fullmatch(project):
            raise ValueError("invalid outbox project name")
        self.root = Path(home) / ".corthex" / "hub" / "outbox"
        self.folder = self.root / project
        self.order_path = self.root / (project + ".order")
        self.project, self.clock = project, clock
        self.attempts, self.replies = {}, {}
        try:
            self.folder.resolve().relative_to(self.root.resolve())
            within = True
        except ValueError:
            within = False
        if len(project) > 100 or self.root.is_symlink() or self.folder.is_symlink() or not within:
            raise ValueError("outbox paths must stay in this device's hub")

    def lease(self):
        return Lease(self.root, self.project, self.clock)

    def files(self):
        files = sorted(self.folder.glob("*.json")) if self.folder.is_dir() else []
        order = {write: index for index, write in enumerate(self.order())}
        return sorted(files, key=lambda p: (p.name.split(".", 1)[0], 0, order[self.file_id(p)])
                      if self.file_id(p) in order else (p.name.split(".", 1)[0], 1, p.name))

    @staticmethod
    def file_id(path):
        pieces = path.name.split(".")
        return pieces[1] if len(pieces) == 3 and WRITE.fullmatch(pieces[1]) else None

    def order(self):
        if self.order_path.is_symlink():
            raise ValueError("outbox ordering metadata is a symbolic link")
        if not self.order_path.exists():
            return []
        try:
            data = json.loads(self.order_path.read_text(encoding="utf8"))
        except (OSError, ValueError):
            raise ValueError("outbox ordering metadata is invalid; preserve and repair it before sending")
        if (not isinstance(data, list) or any(not isinstance(x, str) or not WRITE.fullmatch(x) for x in data) or
                len(set(data)) != len(data)):
            raise ValueError("outbox ordering metadata is invalid; preserve and repair it before sending")
        return data

    def make(self, request, path, session, body):
        return new_write(self.project, request, path, session, body, self.clock)

    def save(self, data, attempt, lease, count_attempt=True):
        data = dict(data, tries=data["tries"] + int(count_attempt))
        if attempt is not None:
            data["failure"] = failure_of(attempt)
        made = datetime.fromtimestamp(timestamp(data["made"]), timezone.utc)
        prefix = made.strftime("%Y%m%dT%H%M%S") + ("%03d" % (made.microsecond // 1000)) + "Z"
        path = self.folder / (prefix + "." + data["write"] + ".json")
        self.root.mkdir(parents=True, exist_ok=True)
        # A new unique file can be appended under the same short OS guard
        # while another sender owns the lease. It joins a later drain; it is
        # never sent ahead of that sender's waiting head.
        with lease.owned() if lease is not None else guard(self.root / (self.project + ".guard")):
            files = self.files()
            same = next((p for p in files if self.file_id(p) == data["write"]), None)
            if same is not None:
                held = self.load(same)
                stable = ("format", "write", "project", "request", "path", "session", "made", "body")
                if same != path or held is None or any(held[key] != data[key] for key in stable):
                    raise ValueError("the queued write ID already identifies another write")
                if lease is None:
                    return held  # recovery never rewrites the new holder's file
            else:
                order = [self.file_id(p) for p in files if self.file_id(p)]
                order.append(data["write"])
                # Reserve admission order before the atomic file publication.
                atomic(self.order_path, order)
            atomic(path, data)
        return data

    def load(self, path):
        if path.is_symlink() or not path.is_file():
            return None
        try:
            with open(path, "r", encoding="utf8") as handle:
                text = handle.read(2 * 1024 * 1024 + 1)
            data = json.loads(text) if len(text) <= 2 * 1024 * 1024 else None
        except (OSError, ValueError):
            return None
        if not valid(data, self.project):
            return None
        made = datetime.fromtimestamp(timestamp(data["made"]), timezone.utc)
        expected = made.strftime("%Y%m%dT%H%M%S") + ("%03d" % (made.microsecond // 1000)) + "Z." + data["write"] + ".json"
        return data if path.name == expected else None

    def as_reply_in_place(self, path, data, reply, lease):
        """Put the reply where the request was, in the same admission order."""
        made = datetime.fromtimestamp(timestamp(reply["made"]), timezone.utc)
        target = self.folder / (made.strftime("%Y%m%dT%H%M%S") + ("%03d" % (made.microsecond // 1000)) + "Z." + reply["write"] + ".json")
        with lease.owned():
            order = self.order()
            if data["write"] in order:
                order[order.index(data["write"])] = reply["write"]
                atomic(self.order_path, order)
            atomic(target, reply)
            path.unlink()
        return target

    def drain(self, client, lease, send=True):
        self.attempts, self.replies = {}, {}
        stats = {"sent": 0, "dropped": 0, "waiting": 0, "notices": []}
        waiting, stopped = [], False
        for path in self.files():
            data = self.load(path)
            made = timestamp(data["made"]) if data else None
            expired = made is not None and self.clock() - made >= SEVEN_DAYS
            if data is None or expired:
                with lease.owned():
                    path.unlink()
                stats["dropped"] += 1
                stats["notices"].append({"write": data["write"] if data else None, "failure": "expired after 7 days" if expired else "invalid outbox file"})
                continue
            info = {key: data[key] for key in ("write", "request", "made", "tries")}
            if "failure" in data:
                info["failure"] = data["failure"]
            if not send or stopped:
                waiting.append(info)
                continue
            lease.renew()
            attempt = client.call("POST", data["path"], data["body"], data["session"], data["write"])
            reply = as_reply(data, attempt, self.clock)
            if reply is not None:
                # Once: the reply's own answer stands, whatever it is.
                path = self.as_reply_in_place(path, data, reply, lease)
                self.replies[data["write"]] = reply["write"]
                data = reply
                info = {key: data[key] for key in ("write", "request", "made", "tries")}
                lease.renew()
                attempt = client.call("POST", data["path"], data["body"], data["session"], data["write"])
            self.attempts[data["write"]] = attempt
            with lease.owned():
                if attempt["outcome"] == "done":
                    path.unlink()
                    stats["sent"] += 1
                elif attempt.get("retry"):
                    data["tries"] += 1
                    data["failure"] = failure_of(attempt)
                    atomic(path, data)
                    info.update(tries=data["tries"], failure=data["failure"])
                    waiting.append(info)
                    stopped = True
                else:
                    path.unlink()
                    stats["dropped"] += 1
                    stats["notices"].append({"write": data["write"], "problem": attempt.get("problem"), "failure": attempt.get("failure")})
            lease.renew()
        # A second hub may append during HTTP under the short guard. Those
        # writes join the next drain, and must keep the caller's fresh write
        # behind the now-waiting head rather than reporting an empty queue.
        waiting = []
        with lease.owned():
            remaining = self.files()
            order = [self.file_id(p) for p in remaining if self.file_id(p)]
            if not order:
                if self.order_path.exists():
                    self.order_path.unlink()
            elif order != self.order():
                atomic(self.order_path, order)
        for path in remaining:
            data = self.load(path)
            if data is None:
                waiting.append({"write": None, "request": "unknown", "made": None, "tries": 0, "failure": "invalid outbox file"})
                continue
            info = {key: data[key] for key in ("write", "request", "made", "tries")}
            if "failure" in data:
                info["failure"] = data["failure"]
            waiting.append(info)
        stats["waiting"] = len(waiting)
        return stats, waiting

    def clear(self, lease):
        with lease.owned():
            for path in self.files():
                if path.is_symlink():
                    raise ValueError("invalid outbox file")
                path.unlink()
            if self.folder.exists():
                for path in self.folder.iterdir():
                    # A crashed atomic replacement may leave its unique temp.
                    # Preserve unrelated files instead of failing a removal
                    # that already succeeded on the server.
                    if path.name.startswith(".") and path.name.endswith(".tmp") and path.is_file() and not path.is_symlink():
                        path.unlink()
                if not any(self.folder.iterdir()):
                    self.folder.rmdir()
            if self.order_path.exists() and not self.order_path.is_symlink():
                self.order_path.unlink()
