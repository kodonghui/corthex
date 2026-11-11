"""Project recording exclusions for a format-1 store and, from release 0.3.0, a format-2 one."""
import copy
from contextlib import contextmanager
from pathlib import Path

from . import clock, commands, configuration, files, locks, projects, store
from . import enablement
from .worker_support import BoundDiagnostics


class Refused(Exception):
    def __init__(self, code, **data):
        self.code, self.data = code, data


@contextmanager
def _configuration(context):
    original = context.record
    memory = enablement.CommandStore(context.memory.folder, getattr(context.memory, "fence", None))
    context.memory = memory
    notes = []
    report = lambda error, count=None: notes.append((error, count))
    try:
        with context.lock(memory.folder / "store.lock", "store", report=report) as owner:
            pinned, validated, fingerprint = [None], [None], [None]
            def check():
                owner.check()
                if pinned[0] is not None:
                    try:
                        current = enablement._header_stamp(memory, pinned[0])
                    except FileNotFoundError:
                        raise locks.LostLock() from None
                    if fingerprint[0] is not None and current != fingerprint[0]:
                        raise locks.LostLock()
                    fingerprint[0] = current
                owner.check()
            def header(data):
                value = context.header(data)
                if value["device"] != original["device"]:
                    raise locks.LostLock()
                validated[0] = data
                return value
            try:
                record = enablement._read(memory, "store.json", header, check, report)
            except (FileNotFoundError, ValueError, UnicodeError, files.RestoreNeeded):
                raise store.StoreUnavailable("store-damaged") from None
            context.record = record
            pinned[0] = validated[0]
            check()
            try:
                document = enablement._read(memory, "configuration.json", store._configuration, check, report)
            except FileNotFoundError:
                document = {}
            except (ValueError, UnicodeError, files.RestoreNeeded):
                raise configuration.ConfigurationInvalid("$") from None
            context.configuration = configuration.prepare(document)
            previous = context.project
            context.project = projects.locate(context.arguments["folder"])
            if context.project is None or context.project.name != previous.name:
                raise Refused("not-in-project")
            if not context.configuration.values["projects"].get(context.project.name, {}).get("enabled", False):
                raise Refused("not-enabled", project=context.project.name)
            yield check
    except locks.LostLock:
        notes.clear()
        raise
    finally:
        if context.record and notes:
            try:
                logger = BoundDiagnostics(commands.diagnostic_store(memory, context.record["device"], context.format))
                for error, count in notes:
                    logger.failure(error, "restore", clock.now() + 10, count=count)
            except Exception:
                pass  # Diagnostics cannot change a completed command result.


def _relative(raw, context):
    if not raw or len(raw) > 1000 or any(ord(char) < 32 for char in raw):
        raise commands.UsageError()
    try:
        target = Path(raw).expanduser()
        target = (Path(context.arguments["folder"]) / target).resolve()
        if target.exists() and not target.is_dir():
            raise commands.UsageError()
    except (OSError, ValueError, RuntimeError):
        raise commands.UsageError() from None
    root = context.project.folder
    if root is None:
        return None
    identity, parts = projects.identity(root), []
    for path, candidate in projects.ancestors(target):
        if candidate is not None and candidate == identity:
            if not parts:
                raise commands.UsageError()
            return "/".join(reversed(parts))
        parts.append(path.name)
    return None


def leave_out(context):
    try:
        with _configuration(context) as check:
            name, before = context.project.name, context.configuration
            choices = before.values["projects"][name].get("left_out", {})
            data = {"project": name, "folders": copy.deepcopy(choices.get("folders", [])),
                    "kinds": copy.deepcopy(choices.get("kinds", []))}
            normalized, outside = [], []
            for raw in context.arguments["folders"]:
                relative = _relative(raw, context)
                (outside if relative is None else normalized).append(raw if relative is None else relative)
            if outside:
                return commands.result("leave-out", dict(data, outside=outside),
                                       "Folders must be inside the project's folder; no exclusions changed.", "refused", "folder-outside")
            after = copy.deepcopy(data)
            for key, values in (("folders", normalized), ("kinds", context.arguments["kind"])):
                for value in values:
                    if context.arguments["remove"]:
                        after[key] = [item for item in after[key] if item != value]
                    elif value not in after[key]:
                        after[key].append(value)
            say = "Exclusions follow the session folder; sessions elsewhere still record even when reading files in an excluded folder."
            if {"prompt", "answer"} <= set(after["kinds"]):
                say += " With prompts and final answers both excluded, curation has nothing to read."
            if after == data:
                return commands.result("leave-out", after, say, "nothing")
            updated = copy.deepcopy(before.document)
            updated["projects"][name]["left_out"] = {key: after[key] for key in ("folders", "kinds")}
            try:
                configuration.prepare(updated)
            except configuration.ConfigurationInvalid:
                raise commands.UsageError() from None
            check()
            files.write_json(context.memory.folder / "configuration.json", updated, "TBL-002", check=check,
                             path_check=context.memory.fence.check)
            return commands.result("leave-out", after, say)
    except Refused as error:
        return commands.common_result("leave-out", error.code, **error.data)
    except store.StoreUnavailable as error:
        return commands.common_result("leave-out", error.code)
    except configuration.ConfigurationInvalid as error:
        return commands.common_result("leave-out", "configuration-invalid", field=error.field)
    except projects.ProjectError as error:
        return commands.common_result("leave-out", "not-in-project" if error.clash else error.code,
                                      **({"clash": list(error.clash)} if error.clash else {}))
