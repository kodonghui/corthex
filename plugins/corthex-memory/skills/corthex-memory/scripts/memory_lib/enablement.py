"""Confirmed C1 provisioning and project on/off; no network or background work."""
import copy
import json
import os
from pathlib import Path

from . import base, clock, commands, configuration, curation, files, locks, projects, store
from .worker_support import BoundDiagnostics, PathFence

CONSENT = """CORTHEX memory, consent version 1.

- When memory is on for a project, this device records your prompts and the agent's final answers in sessions that work in that project's folders, after removing secrets and the text you mark with <private>. Tool calls, tool results and files are not recorded.
- To curate memory, the recorded turns, the project's current state and its item list are sent to Anthropic with the key in CORTHEX_MEMORY_ANTHROPIC_API_KEY, to the model in the memory configuration, by default Claude Haiku 5.5.
- To recall and to search, your prompts, search requests and memory items are sent to OpenAI with the key in CORTHEX_MEMORY_OPENAI_API_KEY, to make embeddings, by default with text-embedding-3-small.
- The raw recordings, the search index and the logs never leave this device. Sync is off until you turn it on; then only the curated memory goes to a sync server that you run, through its HTTPS gateway.
- Recordings are deleted after 100 days unless you set another period. You can leave folders or kinds of entries out, pin and forget items, turn memory off for a project, delete a project's memory or delete all memory.
- Anthropic's and OpenAI's terms for their APIs govern what they do with the data they receive. The plugin sets no spending limit; its usage is in the memory status and in each provider's console."""


class CommandStore(store.MemoryStore):
    def __init__(self, folder, fence=None):
        self.fence = fence if fence is not None else PathFence(folder)
        self.fence.check(self.fence.root)
        super().__init__(self.fence.root)

    def _path_check(self, path):
        return self.fence.check(path)

    def _lock(self, path, kind, device):
        return locks.Lock(path, kind, device, path_check=self._path_check)


def _keys():
    return {name: "present" if os.environ.get("CORTHEX_MEMORY_" + name.upper() + "_API_KEY") else "missing"
            for name in ("anthropic", "openai")}


def _data(context, proposal=False):
    data = {"project": context.project.name}
    if proposal and not context.configuration.consented():
        data["consent"] = {"version": configuration.CONSENT_VERSION, "text": CONSENT}
    else:
        values = context.configuration.values
        choices = values["projects"].get(context.project.name, {}).get("left_out", {})
        data.update(keys=_keys(), retention_days=values["retention"]["days"],
                    left_out={key: copy.deepcopy(choices.get(key, [])) for key in ("folders", "kinds")})
    return data


def _say(data, already=False):
    text = ("Memory is " + ("already " if already else "") + "on for this project and records redacted prompts "
            "and final answers for %s days; use leave-out to exclude folders or kinds." % data["retention_days"])
    missing = ["CORTHEX_MEMORY_" + name.upper() + "_API_KEY" for name, state in data["keys"].items() if state == "missing"]
    return text + (" Set " + ", ".join(missing) + " in the environment that starts your host." if missing else "")


def _make_root(folder):
    missing, cursor = [], folder.parent
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    for parent in reversed(missing):
        try:
            parent.mkdir(mode=0o777 if os.name == "nt" else 0o700)
        except FileExistsError:
            pass
    try:
        folder.mkdir(mode=0o777 if os.name == "nt" else 0o700)
        return True
    except FileExistsError:
        return False


def _read(memory, name, parse, check, report=None):
    path = memory.folder / name
    def guard():
        check()
        memory.fence.check(path)
        memory.fence.check(path.with_name(path.name + ".bak"))
    deadline = clock.now() + 10
    return files.read_record(path, parse, report, holding_lock=True, check=guard, deadline=deadline,
                             reader=lambda candidate: memory.fence.read(candidate, deadline))


def _project_files(context, check, existed, report):
    memory, device = context.memory, context.record["device"]
    root = memory.folder / "projects" / base.project_folder_name(context.project.name)
    memory.fence.check(root)
    existed = existed or root.exists()
    for path in (memory.folder / "logs", memory.folder / "projects", root,
                 *(root / name for name in ("raw", "unprocessed", "notices", "injections", "layer",
                                             "layer/items", "layer/tombstones"))):
        check()
        memory.fence.check(path)
        base.private_directory(path)
        check()
        memory.fence.check(path)
    with memory._lock(root / "curation.lock", "curation", device).held(clock.now() + 10, report=report) as owner:
        with memory._lock(root / "layer.lock", "layer", device).held(clock.now() + 10, report=report) as layer:
            path = root / "curation.json"
            def guard():
                check()
                owner.check()
                layer.check()
                memory.fence.check(path)
                memory.fence.check(path.with_name(path.name + ".bak"))
            try:
                guard()
                deadline = clock.now() + 10
                files.read_record(path, curation.parse, report, holding_lock=True, check=guard,
                                  deadline=deadline, reader=lambda candidate: memory.fence.read(candidate, deadline))
            except FileNotFoundError:
                if existed:
                    raise
                value = {"logs": {}, "applies": 0, "recent": [], "consolidation": {"failures": 0}}
                files.write_json(path, value, "TBL-009", check=guard, path_check=memory.fence.check)


def _apply(context, enabled, confirmed=False):
    original, folder = context.record, context.memory.folder
    created, memory, first = False, None, None
    fence, notes = getattr(context.memory, "fence", None), []
    report = lambda error, count=None: notes.append((error, count))
    try:
        if original is None:
            release = json.loads((Path(__file__).resolve().parents[4] / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))["version"]
            first = store.new_record(release)
            created = _make_root(folder)
        memory = CommandStore(folder, fence)
        context.memory = memory
        device = original["device"] if original else first["device"]
        with context.lock(memory.folder / "store.lock", "store", device=device, report=report) as lease:
            pin = [None, False]
            def check():
                lease.check()
                memory.fence.check(memory.folder / "store.json")
                if pin[0] is not None:
                    try:
                        current = memory.fence.read(memory.folder / "store.json", clock.now() + 10)
                    except FileNotFoundError:
                        if pin[1]:
                            return
                        raise locks.LostLock() from None
                    if current != pin[0]:
                        raise locks.LostLock()
                lease.check()
            validated = [None]
            def header(data):
                value = store._record(data)
                if original is not None and value["device"] != original["device"]:
                    raise locks.LostLock()
                validated[0] = data
                return value
            try:
                current = _read(memory, "store.json", header, check, report)
            except (ValueError, UnicodeError, files.RestoreNeeded):
                raise store.StoreUnavailable("store-damaged") from None
            except FileNotFoundError:
                if not created or any(path.name != "store.lock" for path in memory.folder.iterdir()):
                    raise store.StoreUnavailable("store-damaged") from None
                current = None
            context.record = current
            if current is not None:
                pin[0] = validated[0]
                check()
            try:
                document = _read(memory, "configuration.json", store._configuration, check, report) if current else {}
            except FileNotFoundError:
                document = {}
            except (ValueError, UnicodeError, files.RestoreNeeded):
                raise configuration.ConfigurationInvalid("$") from None
            context.configuration = configuration.prepare(document)
            context.project = projects.locate(context.arguments["folder"])
            if context.project is None:
                return commands.common_result(context.command, "not-in-project")

            def write():
                before = context.configuration
                name = context.project.name
                entry = before.document.get("projects", {}).get(name, {})
                if enabled and before.enabled(name):
                    data = _data(context)
                    return commands.result("on", data, _say(data, True), "nothing")
                if not enabled and not entry.get("enabled", False):
                    return commands.common_result("off", "not-enabled", project=name)
                updated = copy.deepcopy(before.document)
                updated.setdefault("projects", {})[name] = copy.deepcopy(entry)
                changed = updated["projects"][name]
                changed["enabled"] = enabled
                if enabled:
                    changed["since"] = base.utc_time()
                    if not before.consented():
                        updated["consent"] = {"at": base.utc_time(), "version": configuration.CONSENT_VERSION}
                        updated.pop("sync", None)
                checked = configuration.prepare(updated)
                if current is None:
                    pin[:] = [base.json_bytes(first, "TBL-001"), True]
                    files.write_json(memory.folder / "store.json", first, "TBL-001", check=check, path_check=memory.fence.check)
                    pin[1] = False
                    context.record = first
                if enabled:
                    _project_files(context, check, name in before.document.get("projects", {}), report)
                check()
                files.write_json(memory.folder / "configuration.json", checked.document, "TBL-002",
                                 check=check, path_check=memory.fence.check)
                context.configuration = checked
                if enabled:
                    data = _data(context)
                    return commands.result("on", data, _say(data))
                return commands.result("off", {"project": name},
                                       "Memory is off for this project; existing memory is kept and the retention policy still applies.")

            if enabled and (confirmed or not context.configuration.consented() or context.supplied is not None):
                return context.confirm(_data(context, True), "Review the memory consent before enabling this project.", write)
            return write()
    except locks.LostLock:
        notes.clear()
        raise
    except store.StoreUnavailable as error:
        return commands.common_result(context.command, error.code)
    except configuration.ConfigurationInvalid as error:
        return commands.common_result(context.command, "configuration-invalid", field=error.field)
    except projects.ProjectError as error:
        return commands.common_result(context.command, "not-in-project" if error.clash else error.code,
                                      **({"clash": list(error.clash)} if error.clash else {}))
    finally:
        if context.record and notes:
            try:
                logger = BoundDiagnostics(commands._DiagnosticStore(context.memory, context.record["device"]))
                for error, count in notes:
                    logger.failure(error, "restore", clock.now() + 10, count=count)
            except Exception:
                pass  # Diagnostics cannot change the command result.
        if created and memory is not None:
            try:
                memory.fence.check(memory.folder)
                if not any(memory.folder.iterdir()):
                    memory.folder.rmdir()
            except OSError:
                pass


def on(context):
    if not context.configuration.consented() or context.supplied is not None:
        return context.confirm(_data(context, True), "Review the memory consent before enabling this project.",
                               lambda: _apply(context, True, True))
    return _apply(context, True)


def off(context):
    return _apply(context, False)
