"""Command parsing, ordered gates, results and confirmation for later handlers.

An internal handler receives Context and returns a result made with result().
It reads a fresh preview, then calls context.confirm() before changing anything.
It owns the operation's locks and rechecks store identity, project state and the
preview under them before applying;
lock() supplies the shared ten-second wait, ordering and lease checks. No command
effects or public test switches live in this framework.
"""

import argparse
import hashlib
import json
import sys
import time
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import base, clock, command_result, configuration, diagnostics, locks, projects, store

COMMANDS = tuple("on off status resume list search open pin unpin forget delete-project "
                 "purge leave-out retention sync setup repair".split())
ALL = frozenset(COMMANDS)
# `migrate`, a store command that joins COMMANDS at the 0.3.0 activation, takes no project either.
PROJECT = ALL - {"status", "purge", "retention", "sync", "repair", "migrate"}
CHANGES = ALL - {"status", "list", "search", "open", "setup"}
# migrate (API-154) and undo (API-153) ask first but stay out of COMMANDS until the 0.3.0 activation.
ASKS = frozenset("on resume forget delete-project purge retention sync repair migrate undo".split())
# The common command-code applicability table, including the on/off exceptions.
# Invalid CORTHEX_MEMORY_HOME precedes the store and overrides the schema row.
COMMON = {
    "usage": (ALL | {"none"}, "refused"),
    "no-store": (ALL - {"on", "purge", "repair"}, "refused"),
    "store-newer": (ALL - {"purge", "migrate"}, "refused"),
    "store-damaged": (ALL - {"purge", "repair"}, "refused"),
    "configuration-invalid": (ALL - {"status", "purge", "repair"}, "refused"),
    "no-project-list": (PROJECT, "refused"),
    "not-in-project": (PROJECT, "refused"),
    "not-enabled": (PROJECT - {"on"}, "refused"),
    # Every reader can need a write lease to restore a backup. Ordinary reads
    # acquire no lock; effect handlers use lock() only for changing commands.
    "lock-busy": (ALL, "failed"),
    "internal": (ALL | {"none"}, "failed"),
}
MESSAGES = {
    "usage": "The command or arguments are not valid. Use a documented memory command and its arguments.",
    "no-store": "There is no memory store on this device. Turn memory on for a project first.",
    "store-newer": "This memory store needs a newer plugin. Update the plugin before using it.",
    "store-damaged": "The store record cannot be read. Repair it after reviewing the proposed change.",
    "configuration-invalid": "The memory configuration is not valid. Correct the reported field before trying again.",
    "no-project-list": "The project list cannot be read. The corthex skill can add or repair it.",
    "not-in-project": "This folder does not identify one project. The corthex skill can update the project list.",
    "not-enabled": "Memory is off for this project. The on command turns it on.",
    "lock-busy": "A memory lock stayed busy for ten seconds. Try again later.",
    "internal": "Memory hit an unexpected error. The failure log records its class when the store is writable.",
}


class UsageError(Exception):
    pass


class _DiagnosticStore(store.MemoryStore):
    """Keep best-effort diagnostics bound to the operation's readable device."""
    def __init__(self, memory, device):
        from .worker_support import PathFence
        self.device = device
        self.fence = getattr(memory, "fence", None)
        if self.fence is None:
            self.fence = PathFence(memory.folder)
        self.folder, self.held = self.fence.root, ()

    def _path_check(self, path):
        return self.fence.check(path)

    def _lock(self, path, kind, device):
        return locks.Lock(path, kind, device, path_check=self._path_check)

    def _read_record(self, path, parse, deadline, report, **options):
        return super()._read_record(path, parse, deadline, report,
                                    reader=lambda candidate: self.fence.read(candidate, deadline), **options)

    def record(self, *args, **kwargs):
        previous = kwargs.pop("precondition", None)
        def check(value):
            if self.device is not None and value["device"] != self.device:
                raise locks.LostLock()
            if previous is not None:
                previous(value)
        return super().record(*args, precondition=check, **kwargs)


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, add_help=False, allow_abbrev=False, **kwargs)

    def error(self, message):
        # argparse's message can contain keys pasted as unknown arguments.
        raise UsageError()


def number_between(low, high=None):
    def parse(value):
        try:
            number = int(value)
        except ValueError:
            raise UsageError() from None
        if number < low or high is not None and number > high:
            raise UsageError()
        return number
    return parse


def device_folder(value):
    """`setup --at`: the project's folder on the temporary device, an absolute POSIX path (API-031)."""
    if (not value.startswith("/") or len(value) > 1000 or
            any(unicodedata.category(character) == "Cc" for character in value)):
        raise UsageError()
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise UsageError() from None
    return value


def parser():
    root = Parser(prog="memory.py")
    root.add_argument("--folder", default=argparse.SUPPRESS)
    sub = root.add_subparsers(dest="command", required=True)
    kinds = ("decision", "preference", "lesson", "reference", "fact")
    for name in COMMANDS:
        part = sub.add_parser(name)
        part.add_argument("--folder", default=argparse.SUPPRESS)
        if name in ASKS and name != "sync":
            part.add_argument("--confirm")
        if name == "status":
            part.add_argument("--all", action="store_true")
        if name in ("list", "search"):
            part.add_argument("--kind", choices=kinds)
            part.add_argument("--limit", type=number_between(1), default=200 if name == "list" else 20)
        if name == "search":
            part.add_argument("words")
            part.add_argument("--words-only", action="store_true")
        if name in ("open", "pin", "unpin", "forget"):
            part.add_argument("item", nargs="+" if name == "open" else None)
        if name == "open":
            part.add_argument("--around", type=number_between(0, 2000))
        if name == "forget":
            part.add_argument("--with", dest="with_items", action="append", default=[])
        if name == "leave-out":
            part.add_argument("folders", nargs="*")
            part.add_argument("--kind", action="append", choices=sorted(projects.KINDS), default=[])
            part.add_argument("--remove", action="store_true")
        if name == "retention":
            part.add_argument("days", type=number_between(1, 3650))
        if name == "setup":
            part.add_argument("--at", required=True, type=device_folder)
        if name == "sync":
            modes = part.add_subparsers(dest="mode", required=True)
            for mode in ("on", "off", "now"):
                child = modes.add_parser(mode)
                child.add_argument("--folder", default=argparse.SUPPRESS)
                if mode == "on":
                    child.add_argument("address")
                    child.add_argument("--branch", default="main")
                    child.add_argument("--confirm")
    return root


def command_name(argv):
    # Skip only the documented leading global option, never guess from a value.
    rest = list(argv)
    while rest and (rest[0] == "--folder" or rest[0].startswith("--folder=")):
        rest = rest[2:] if rest[0] == "--folder" else rest[1:]
    return rest[0] if rest and rest[0] in ALL else "none"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def confirmation(device, command, arguments, data, period):
    # One canonical JSON array frames the five fields without delimiter collisions.
    payload = canonical([device or "none", command, arguments, data, period]).encode("ascii")
    bits = int.from_bytes(hashlib.sha256(payload).digest()[:5], "big")
    return "".join(base.CROCKFORD[(bits >> shift) & 31] for shift in range(35, -1, -5))


def common_outcome(command, code):
    if (code, command) in (("no-store", "status"), ("not-enabled", "off")):
        return "nothing"
    return COMMON[code][1]


def result(command, data, say, outcome="done", code="ok", confirm=None):
    value = dict(command=command, outcome=outcome, code=code, say=say, data=data)
    if confirm is not None:
        value["confirm"] = confirm
    validate_result(value, command)
    return value


def validate_result(value, command):
    try:
        if type(value) is not dict or value.get("command") != command:
            raise command_result.ResultInvalid()
        command_result.validate(value)
        if not value["say"].isascii():
            raise command_result.ResultInvalid()
    except (command_result.ResultInvalid, command_result.SchemaInvalid):
        raise
    except Exception:
        raise command_result.ResultInvalid() from None


def common_result(command, code, **data):
    say = MESSAGES[code]
    if data.get("field") == "CORTHEX_MEMORY_HOME":
        say = "CORTHEX_MEMORY_HOME must expand to an absolute path. No store was read or changed."
    # Common gates and exception handling reach the one final boundary too.
    return dict(command=command, data=data, say=say, outcome=common_outcome(command, code), code=code)


@dataclass
class Context:
    command: str
    arguments: dict
    supplied: object
    memory: object
    record: object = None
    configuration: object = None
    project: object = None
    store_error: object = None
    configuration_error: object = None

    def confirm(self, data, say, apply, code="ok", bound=None):
        """Ask without calling apply; a mismatch always returns a fresh preview.

        The code covers the preview's data, or only `bound` when a command's
        confirmation covers less than its preview shows.
        """
        if self.command not in ASKS or self.command == "sync" and self.arguments["mode"] != "on":
            raise ValueError()
        device = self.record["device"] if self.record else "none"
        # Check the typed preview before even serializing data into a token.
        preview = result(self.command, data, say, "confirm", code, "00000000")
        period = int(time.time() // 600)
        basis = data if bound is None else bound
        current = confirmation(device, self.command, self.arguments, basis, period)
        accepted = (current, confirmation(device, self.command, self.arguments, basis, period - 1))
        preview["confirm"] = current
        if self.supplied not in accepted:
            stale = self.supplied is not None
            return result(self.command, data, "The confirmation is stale. Review the current proposal and confirm again."
                          if stale else say, "confirm", "confirm-stale", current) if stale else preview
        return apply()

    @contextmanager
    def lock(self, path, kind, force=False, device=None, report=None):
        """Handlers select the contract's lock and keep its lease until mutation ends."""
        if self.command not in CHANGES or force and self.command not in ("purge", "delete-project"):
            raise ValueError()
        lease = self.memory._lock(path, kind, self.record["device"] if self.record else device)
        with lease.held(clock.now() + 10, force=force, report=report) as held:
            held.check()
            yield held


def _gates(context):
    notes = []
    try:
        return _read_gates(context, lambda error, count=None: notes.append((error, count)))
    except locks.LostLock:
        notes.clear()
        raise
    finally:
        if context.record and notes:
            try:
                from .worker_support import BoundDiagnostics
                logger = BoundDiagnostics(_DiagnosticStore(context.memory, context.record["device"]))
                for error, count in notes:
                    logger.failure(error, "restore", clock.now() + 10, count=count)
            except Exception:
                pass  # A diagnostic failure never replaces the gate's result.


def _read_gates(context, report):
    command, memory = context.command, context.memory
    try:
        context.record = memory.record(report, deadline=clock.now() + 10)
    except store.StoreUnavailable as error:
        context.store_error = error.code
        if command in COMMON[error.code][0]:
            return common_result(command, error.code)
    except OSError:
        if command != "purge":
            raise
        context.store_error = "unreadable"
    if context.record:
        if isinstance(memory, _DiagnosticStore):
            memory.device = context.record["device"]
        try:
            context.configuration = memory.configuration(report, deadline=clock.now() + 10)
        except configuration.ConfigurationInvalid as error:
            context.configuration_error = error.field
            if command in COMMON["configuration-invalid"][0]:
                return common_result(command, "configuration-invalid", field=error.field)
        except OSError:
            if command != "purge":
                raise
            context.configuration_error = "unreadable"
        except store.StoreUnavailable as error:
            context.record, context.store_error = None, error.code
            if command in COMMON[error.code][0]:
                return common_result(command, error.code)
    if context.configuration is None and command == "on":
        context.configuration = configuration.prepare({})
    if command in PROJECT or command == "status":
        try:
            context.project = projects.locate(context.arguments["folder"])
        except projects.ProjectError as error:
            if command in PROJECT:
                code = "not-in-project" if error.code == "project-clash" else error.code
                return common_result(command, code, **({"clash": list(error.clash)} if error.clash else {}))
        if command in PROJECT:
            if context.project is None:
                return common_result(command, "not-in-project")
            # Consent gates sending/recording, not local reading (search without
            # consent must still support words). on may enable a disabled project.
            enabled = context.configuration.values["projects"].get(context.project.name, {}).get("enabled", False)
            if command != "on" and not enabled:
                return common_result(command, "not-enabled", project=context.project.name)
    return None


def run(argv, handlers=None):
    """Return the result and status; handler registration is internal Python only."""
    command, context, unimplemented = command_name(argv), None, False
    failed_validation = False
    try:
        args = vars(parser().parse_args(argv))
        command = args.pop("command")
        supplied = args.pop("confirm", None)
        folder = args["folder"] if "folder" in args else Path.cwd()
        if not str(folder).strip():
            raise UsageError()
        args["folder"] = str(Path(folder).expanduser().resolve())
        memory = store.MemoryStore()
        if command == "purge":
            from . import store_deletion
            memory.folder = store_deletion.protect(memory.folder)  # Before gate recovery.
        if memory.folder.exists():
            memory = _DiagnosticStore(memory, None)  # Pin the existing root before gate recovery.
        if command == "purge" and store_deletion.protect(base.memory_home()) != memory.folder:
            raise locks.LostLock()
        context = Context(command, args, supplied, memory)
        answer = _gates(context)
        if answer is None:
            if handlers is None:
                from . import enablement, status, recording_exclusions, retention_settings, store_deletion, store_repair
                handlers = {"on": enablement.on, "off": enablement.off, "status": status.status,
                            "leave-out": recording_exclusions.leave_out, "retention": retention_settings.retention, "purge": store_deletion.purge, "repair": store_repair.repair}
            handler = (handlers or {}).get(command)
            if handler is None:
                unimplemented = True
                raise NotImplementedError()
            answer = handler(context)
        validate_result(answer, command)
    except UsageError:
        answer = common_result(command, "usage")
    except base.MemoryHomeInvalid as error:
        answer = common_result(command, "configuration-invalid", field=error.field)
    except Exception as error:
        if isinstance(error, locks.LockBusy):
            answer = common_result(command, "lock-busy")
        else:
            failed_validation = isinstance(error, (command_result.ResultInvalid, command_result.SchemaInvalid))
            kind = diagnostics.error_kind(error)
            if kind not in diagnostics.EXCEPTIONS.values():
                kind = "RuntimeError"
            answer = command_result._internal(command, error) if failed_validation else common_result(command, "internal", error=kind)
            if failed_validation:
                kind = answer["data"]["error"]
            if unimplemented:
                answer["say"] = "This operation is not implemented in this stage. No command effects were applied."
            # Losing the lease or path identity forbids further writes, even
            # diagnostics that could otherwise restore a different header.
            if context is not None and context.record is not None and not isinstance(error, locks.LostLock):
                try:
                    from .worker_support import BoundDiagnostics
                    memory = _DiagnosticStore(context.memory, context.record["device"])
                    BoundDiagnostics(memory).failure(kind, "skill", clock.now() + 10,
                                                     project=context.project.name if context.project else None)
                except Exception:
                    pass
    # A failed loader/validator is never reused to build or check its fallback.
    return (answer, 1) if failed_validation else command_result.finalize(command, answer)


def main(argv=None):
    answer, status = run(sys.argv[1:] if argv is None else argv)
    sys.stdout.write(canonical(answer) + "\n")
    return status
