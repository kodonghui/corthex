"""Confirmed device-folder deletion; no provider, process killing or remote access."""
import os
from pathlib import Path
import re
import stat

from . import base, clock, commands, configuration, diagnostics, files, locks, raw_log, store
from .worker_support import PathFence, UnsafePath

LOG = r"(?:claude-code|codex)-[0-9a-f]{16}"


def protect(folder):
    """Refuse aliases and folders that contain the profile, registry or plugin."""
    if ".." in Path(folder).parts:
        raise UnsafePath()  # Check the original spelling before abspath collapses it.
    folder = Path(os.path.abspath(str(folder)))
    for path in (folder,) + tuple(folder.parents):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise UnsafePath()
    root, home = folder.resolve(), Path.home().resolve()
    plugin = Path(__file__).resolve().parents[4]
    for kept in (home, home / ".corthex", home / ".corthex/profile.json",
                 home / ".corthex/projects.json", plugin):
        if root == kept or root in kept.parents or kept == plugin and kept in root.parents:
            raise UnsafePath()
    return root


def _identity(info):
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


class Deletion:
    def __init__(self, context):
        self.context = context
        self.fence = getattr(context.memory, "fence", None) or PathFence(protect(context.memory.folder))
        self.root, self.active = self.fence.root, []
        self.parent = _identity(self.root.parent.lstat())
        self.pin, self.retired = self.header(), False
        self.device = context.record["device"] if context.record else base.new_id("d")
        self.nodes, self.blocked = {}, set()

    def header(self):
        path = self.root / "store.json"
        self.fence.check(path)
        try:
            return diagnostics.Diagnostics._stamp(path, clock.now() + 1, check=self.fence.check)
        except OSError:
            # Unreadable metadata is unknown, but its named file remains pinned.
            info = self.fence.check(path)
            return None if info is None else (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)

    def check(self):
        self.fence.check(self.root)
        if self.header() != (None if self.retired else self.pin):
            raise locks.LostLock()
        for lease in self.active:
            lease.check()

    def scan(self):
        self.check()
        nodes, blocked = {}, set()
        def walk(folder):
            try:
                children = sorted(folder.iterdir())
            except OSError:
                blocked.add(folder)
                return
            for path in children:
                try:
                    self.check()
                    info = self.fence.check(path)
                    if info is None:
                        continue
                    nodes[path] = _identity(info)
                    if stat.S_ISDIR(info.st_mode):
                        walk(path)
                    elif not stat.S_ISREG(info.st_mode):
                        blocked.add(path)
                except UnsafePath:
                    blocked.add(path)
        walk(self.root)
        self.nodes, self.blocked = nodes, blocked

    def read(self, path):
        self.check()
        data = self.fence.read(path, clock.now() + 10)
        self.check()
        return data

    def count(self, paths, raw=False):
        total = 0
        try:
            for path in paths:
                content = self.read(path)
                if content and not content.endswith(b"\n"):
                    raise ValueError()
                for line in content.splitlines():
                    value = store.json_document(line)
                    if raw:
                        raw_log._parsed_entry(value, value["host"], value["session"])
                        if raw_log.log_name(value["host"], value["session"]) + ".jsonl" != path.name:
                            raise ValueError()
                    elif not isinstance(value, dict):
                        raise ValueError()
                    total += 1
            return total
        except (OSError, ValueError, KeyError, TypeError, UnicodeError):
            return None

    def preview(self):
        self.scan()
        try:
            shown = "~/" + self.root.relative_to(Path.home().resolve()).as_posix()
        except ValueError:
            shown = str(self.root)
        data = dict(folder=shown, projects=None, deleted=dict(items=None, entries=None, usage=None), sync="unknown")
        try:
            header = store._record(self.read(self.root / "store.json"))
        except (OSError, ValueError, UnicodeError, store.StoreUnavailable):
            return data  # An opaque layout is not interpreted as empty C1 data.
        if self.context.record and header["device"] != self.context.record["device"]:
            raise locks.LostLock()
        names, raw, usage, items = [], [], [], []
        complete = not any(p == self.root or p == self.root / "projects" for p in self.blocked)
        raw_known = items_known = complete
        usage_known = self.root not in self.blocked  # Logs do not depend on project enumeration.
        for path in self.blocked:
            parts = path.relative_to(self.root).parts
            parent = len(parts) <= 2 and parts and parts[0] == "projects"
            if parent and path not in self.nodes:
                complete = False  # An aliased project is not a complete list.
            raw_known &= not parent and "raw" not in parts
            items_known &= not parent and "layer" not in parts
            usage_known &= not parts or parts[0] != "logs"
        for path in self.nodes:
            relative = path.relative_to(self.root)
            parts = relative.parts
            if len(parts) == 2 and parts[0] == "projects":
                name = parts[1][:-1] if parts[1].endswith("_") else parts[1]
                if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,59}", name) and base.project_folder_name(name) == parts[1]:
                    names.append(name)
                else:
                    complete = False
            if len(parts) == 4 and parts[0] == "projects" and parts[2] == "raw":
                if re.fullmatch(LOG + r"\.jsonl", path.name):
                    raw.append(path)
                elif path.name.endswith((".jsonl", ".bak")):
                    raw_known = False
            if len(parts) == 2 and parts[0] == "logs" and re.fullmatch(r"usage-\d{4}-\d{2}\.jsonl", path.name):
                usage.append(path)
            if len(parts) == 2 and parts[0] == "logs" and path.name.startswith("usage-") and path.name.endswith(".bak"):
                usage_known = False
            if len(parts) >= 5 and parts[0] == "projects" and parts[2:4] == ("layer", "items"):
                items.append(path)
        data["projects"] = sorted(names) if complete else None
        data["deleted"] = dict(items=0 if complete and items_known and not items else None,
                               entries=self.count(raw, True) if complete and raw_known else None,
                               usage=self.count(usage) if usage_known else None)
        try:
            document = store._configuration(self.read(self.root / "configuration.json"))
            data["sync"] = "on" if configuration.prepare(document).values.get("sync") else "off"
        except FileNotFoundError:
            if not (self.root / "configuration.json.bak").exists():
                data["sync"] = "off"
        except (OSError, ValueError, UnicodeError, configuration.ConfigurationInvalid):
            pass
        return data

    def plan(self):
        planned = {(0, self.root / "store.lock", "store")}
        for path, identity in self.nodes.items():
            if identity[2] != stat.S_IFDIR:
                continue
            parts = path.relative_to(self.root).parts
            if len(parts) == 2 and parts[0] == "projects":
                planned.update(((1, path / "curation.lock", "curation"), (3, path / "layer.lock", "layer")))
            if parts == ("sync",):
                planned.add((2, path / "sync.lock", "sync"))
            if parts == ("logs",):
                planned.update((5, path / (name + ".lock"), "log") for name in ("failures", "hooks", "usage"))
        for path in self.nodes:
            parts = path.relative_to(self.root).parts
            # A session's files in `raw`, `injections` and `compaction` change under its raw log lock.
            if len(parts) == 4 and parts[0] == "projects" and parts[2] in ("raw", "injections", "compaction"):
                match = re.match("(" + LOG + r")\.(?:jsonl?|lock)(?:\.|$)", path.name)
                parent = path.parent if parts[2] == "raw" else path.parent.parent / "raw"
                if match and parent in self.nodes:
                    planned.add((4, parent / (match[1] + ".lock"), "raw"))
        return sorted(planned, key=lambda row: (row[0], row[1].as_posix().casefold() if os.name == "nt" else row[1].as_posix()))

    def unlink(self, path):
        def remove():
            self.check()
            for ancestor in (path,) + tuple(path.parents):
                if ancestor == self.root:
                    break
                info = self.fence.check(ancestor)
                if info is None:
                    raise locks.LostLock()  # Never call foreign disappearance our unlink.
                if ancestor not in self.nodes or _identity(info) != self.nodes[ancestor]:
                    raise locks.LostLock()
            path.unlink()
        try:
            files._retry(remove, clock.now() + 1)
            return True
        except (OSError, UnsafePath):
            return False

    def apply(self, expected):
        try:
            for _, path, kind in self.plan():
                self.check()
                ready = [False]
                def guard(candidate, ready=ready):
                    if not ready[0]:
                        self.check()  # Every retry/rename/create needs prior authority.
                    return self.fence.check(candidate)
                lease = locks.Lock(path, kind, self.device, path_check=guard)
                lease.acquire(clock.now() + 10, force=True)
                ready[0] = True  # Active checks must not recursively check themselves.
                self.active.append(lease)
                self.check()
            fresh = self.preview()
            if fresh != expected:
                self.context.supplied = "stale"
                return self.context.confirm(fresh, _say(fresh), lambda: None)
            held = {lease.path for lease in self.active}
            # Remove recovery sources before retiring the header. Its absence
            # becomes an owned, checked state; no guard is disabled afterward.
            headers = [p for p in self.nodes if p.name.startswith("store.json.") and p.parent == self.root]
            headers += [self.root / "store.json"] if self.pin is not None else []
            for path in headers:
                if not self.unlink(path):
                    return self.left(expected, [path])
                if path.name == "store.json":
                    self.retired = True
                    self.context.record = None  # No after-delete diagnostic recovery.
            self.check()
            left = set(self.blocked)
            for path, identity in sorted(self.nodes.items(), reverse=True):
                if identity[2] != stat.S_IFDIR and path not in held and path not in headers:
                    if not self.unlink(path):
                        left.add(path)
        finally:
            while self.active:
                lease = self.active.pop()
                lease.release()  # Own token cleanup; never restore/log into a deleted root.
        self.check()
        directories = [p for p, identity in self.nodes.items() if identity[2] == stat.S_IFDIR]
        for path in sorted(directories, key=lambda p: len(p.parts), reverse=True):
            self.check()
            try:
                if _identity(self.fence.check(path)) != self.nodes[path]:
                    raise locks.LostLock()
                path.rmdir()
            except OSError:
                pass  # Retained leaves are reported below, without duplicates.
        self.scan()
        left.update(p for p, identity in self.nodes.items() if identity[2] != stat.S_IFDIR)
        left.update(self.blocked)
        if left or self.nodes:
            return self.left(expected, left or self.nodes)
        self.check()
        if _identity(self.root.parent.lstat()) != self.parent:
            raise locks.LostLock()
        self.root.rmdir()  # Empty only: never recurse after the final lease release.
        try:
            self.root.lstat()  # A dangling alias is an occupied named slot too.
            raise locks.LostLock()
        except FileNotFoundError:
            pass
        if _identity(self.root.parent.lstat()) != self.parent:
            raise locks.LostLock()
        return commands.result("purge", expected, "Memory on this device was deleted. Any sync remote and other devices keep their copies.")

    def left(self, data, paths):
        data = dict(data, left=sorted(p.relative_to(self.root).as_posix() or "." for p in paths))
        return commands.result("purge", data, "Some files remain. Close programs holding the listed files, then delete those paths inside the shown memory folder by hand or run purge again. Any sync remote and other devices keep their copies.", "failed", "files-left")


def _say(data):
    unknown = data["projects"] is None or None in data["deleted"].values() or data["sync"] == "unknown"
    return ("Some metadata is unknown and cannot be verified. " if unknown else "") + "Confirm deletion of the entire shown memory folder, including configuration and consent. The profile, project list and plugin stay; any sync remote and other devices keep their copies."


def purge(context):
    root = protect(base.memory_home())
    if not root.exists():
        data = dict(folder=str(root), projects=[], deleted=dict(items=0, entries=0, usage=0), sync="off")
        return commands.result("purge", data, "There is no memory folder on this device to delete.", "nothing")
    deletion = Deletion(context)
    data = deletion.preview()
    return context.confirm(data, _say(data), lambda: deletion.apply(data))
