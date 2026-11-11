"""C1 status reads metadata only; no provider, worker or maintenance execution."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import math
import os
from pathlib import Path
import re
import stat
from urllib.parse import urlsplit

from . import activation, base, clock, commands, command_result, configuration, diagnostics, files, locks
from . import model_access, projects, reading, redaction, retention, status_access, store
from .worker_support import BoundDiagnostics


def _now():
    return datetime.now(timezone.utc)


def _time(value):
    if not isinstance(value, str) or not store.TIME.fullmatch(value):
        raise ValueError()
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


class SnapshotStore(commands._DiagnosticStore):
    def __init__(self, memory, device):
        super().__init__(memory, device)
        self.pin = None

    def check(self):
        self.fence.check(self.folder)
        if self.pin is not None:
            current = diagnostics.Diagnostics._stamp(self.folder / "store.json", clock.now() + 10,
                                                     check=self.fence.check)
            if current != self.pin:
                raise locks.LostLock()

    def _path_check(self, path):
        self.check()
        return self.fence.check(path)

    def record(self, *args, **kwargs):
        self.check()
        return super().record(*args, **kwargs)


class Reader:
    def __init__(self, context):
        # Pure initialization must finish before Reader can restore any backup.
        self.validator = command_result._load()
        self.memory = SnapshotStore(context.memory, context.record["device"])
        context.memory = self.memory
        self.notes, self.logger = [], BoundDiagnostics(self.memory)
        self.header = self.logger.read_gate(clock.now() + 10, self.note)
        self.memory.pin = self.logger._ready[1]
        context.record = self.header
        self.now, self.unreadable = _now(), set()
        # The latest usage row of each API this month; a 401 there shows its key as rejected.
        self.latest = {}

    def note(self, error, count=None):
        self.notes.append((error, count))

    def flush(self):
        # Recovery releases its data lease before status emits safe diagnostics.
        notes, self.notes = self.notes, []
        for error, count in notes:
            self.memory.check()
            self.logger.failure(error, "restore", clock.now() + 10, count=count)

    def rows(self, path, family):
        self.memory.check()
        deadline = clock.now() + 10
        lock = self.memory._lock(path.parent / (family + ".lock"), "log", self.header["device"])
        try:
            rows, damaged = reading.read_record(path, files._lines, lock, deadline, report=self.note,
                                                check=self.memory.check,
                                                reader=lambda candidate: self.memory.fence.read(candidate, deadline))
            if damaged:
                self.unreadable.add(family)
            return rows
        except FileNotFoundError:
            return []
        except OSError:
            self.unreadable.add(family)
            return []

    def paths(self, family):
        folder = self.memory.folder / "logs"
        try:
            self.memory._path_check(folder)
            names = {path.name[:-4] if path.name.endswith(".bak") else path.name for path in folder.iterdir()}
        except FileNotFoundError:
            return []
        except OSError:
            self.unreadable.add(family)
            return []
        result = []
        for name in sorted(names):
            match = re.fullmatch(family + r"-(\d{4}-\d{2}-\d{2})\.jsonl", name)
            if match is None:
                continue
            try:
                day = datetime.strptime(match[1], "%Y-%m-%d").date()
            except ValueError:
                continue
            if day > self.now.date() or family == "hooks" and day < (self.now - timedelta(days=7)).date():
                continue
            result.append(folder / name)
        return result

    def usage(self, config):
        month = self.now.strftime("%Y-%m")
        groups, unpriced = {}, set()
        catalogue = config.values["prices"]
        calls = {"curate", "consolidate", "embed-prompt", "embed-items", "embed-search", "count-tokens"}
        for order, row in enumerate(self.rows(self.memory.folder / "logs" / ("usage-" + month + ".jsonl"), "usage")):
            try:
                stamp = _time(row["at"])
                if stamp.strftime("%Y-%m") != month or stamp > self.now or row["call"] not in calls:
                    raise ValueError()
                if not self.validator.matches(row["model"], {"$ref": "#/$defs/model"}) or row["result"] not in {"ok", "failed", "refused", "limit"}:
                    raise ValueError()
                if not configuration.number(row["cost"]) or row["cost"] < 0:
                    raise ValueError()
                for name in ("input", "output", "cache_read", "cache_write"):
                    if not configuration.integer(row.get(name, 0)) or row.get(name, 0) < 0:
                        raise ValueError()
                api = "openai" if row["call"].startswith("embed-") else "anthropic"
                if (stamp, order) >= self.latest.get(api, ((stamp, order), None))[0]:
                    rejected = row["result"] == "failed" and row.get("error") == "authentication_error"
                    self.latest[api] = ((stamp, order), rejected)
                if row["call"] == "count-tokens":
                    continue
                model = row["model"]
                group = groups.setdefault(model, dict(model=model, calls=0, input=0, output=0, cost=[]))
                group["calls"] += 1
                group["input"] += sum(int(row.get(key, 0)) for key in ("input", "cache_write", "cache_read"))
                group["output"] += int(row.get("output", 0))
                group["cost"].append(row["cost"])
                if row.get("prices") == catalogue["taken"] and model not in catalogue["models"]:
                    unpriced.add(model)
            except (KeyError, TypeError, ValueError):
                self.unreadable.add("usage")
        result = dict(month=month, models=[], cost=0)
        try:
            for _, group in sorted(groups.items()):
                group["cost"] = math.fsum(group["cost"])
                result["models"].append(group)
            result["cost"] = math.fsum(group["cost"] for group in result["models"])
        except OverflowError:
            self.unreadable.add("usage")
        if unpriced:
            result["unpriced"] = sorted(unpriced)
        return result

    def project(self, name, config):
        entry = config.values["projects"][name]
        result = dict(project=name, enabled=entry["enabled"], unprocessed=0,
                      items=dict(current=0, superseded=0, withdrawn=0), pins=[])
        if "since" in entry:
            result["since"] = entry["since"]
        root = self.memory.folder / "projects" / base.project_folder_name(name)
        markers = root / "unprocessed"
        self.memory._path_check(markers)
        turns = {}
        try:
            for path in markers.iterdir():
                info = self.memory._path_check(path)
                match = retention.MARKER.fullmatch(path.name)
                if info is None or not stat.S_ISREG(info.st_mode) or match is None:
                    continue
                try:
                    stamp = datetime.strptime(match[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                key = (match[2], int(match[3]))
                turns[key] = min(stamp, turns.get(key, stamp))
        except FileNotFoundError:
            pass
        result["unprocessed"] = len(turns)
        if turns:
            result["oldest"] = min(turns.values()).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        # C1 creates an empty layer. Existing curated data needs TASK-041's
        # reader; never present invented zero counts for that later format.
        layer = root / "layer"
        self.memory._path_check(layer)
        if layer.exists():
            for path in layer.iterdir():
                info = self.memory._path_check(path)
                if info is None:
                    continue
                if path.name not in ("items", "tombstones") or not stat.S_ISDIR(info.st_mode) or any(path.iterdir()):
                    raise NotImplementedError()
        return result


    def failures(self):
        selected = []
        fields = self.validator.root["$defs"]["failure"]["properties"]
        for path in self.paths("failures"):
            for row in self.rows(path, "failures"):
                value = {key: row[key] for key in fields if key in row}
                try:
                    if not self.validator.matches(value, {"$ref": "#/$defs/failure"}):
                        raise ValueError()
                    stamp = _time(value["at"])
                    if stamp <= self.now:
                        selected.append(value)
                except (ValueError, TypeError):
                    self.unreadable.add("failures")
        return sorted(selected, key=lambda row: row["at"], reverse=True)[:20]

    def hooks(self):
        groups = {}
        for path in self.paths("hooks"):
            for row in self.rows(path, "hooks"):
                try:
                    stamp = _time(row["at"])
                    if row["hook"] not in diagnostics.HOOKS or row["host"] not in diagnostics.HOSTS or row["outcome"] not in diagnostics.OUTCOMES:
                        raise ValueError()
                    ms = row["ms"]
                    if not configuration.integer(ms) or ms < 0:
                        raise ValueError()
                    if self.now - timedelta(days=7) <= stamp <= self.now:
                        groups.setdefault((row["hook"], row["host"]), []).append((int(ms), row["outcome"], row["at"]))
                except (KeyError, ValueError, TypeError):
                    self.unreadable.add("hooks")
        result = []
        for (hook, host), rows in sorted(groups.items()):
            values = sorted(row[0] for row in rows)
            count = len(values)
            # Nearest-rank p95; nonnegative median rounds halves upward.
            median = (values[(count - 1) // 2] + values[count // 2] + 1) // 2
            result.append(dict(hook=hook, host=host, runs=count, median_ms=median,
                               p95_ms=values[(95 * count + 99) // 100 - 1],
                               last=max(row[2] for row in rows), outcomes=dict(Counter(row[1] for row in rows))))
        return result


def _folder_name(folder):
    home, parts = projects.identity(Path.home().resolve()), []
    if home is not None:
        for path, identity in projects.ancestors(folder):
            if identity == home:
                return "~" + ("/" + "/".join(reversed(parts)) if parts else "")
            parts.append(path.name)
    return str(folder)


def _servers():
    result = []
    for name in ("anthropic", "openai"):
        raw = os.environ.get("CORTHEX_MEMORY_" + name.upper() + "_BASE_URL", "")
        try:
            value = urlsplit(raw)
            if value.hostname and (value.port is None or 1 <= value.port <= 65535) and (
                    value.scheme == "https" or value.scheme == "http" and value.hostname in {"localhost", "127.0.0.1", "::1"}):
                result.append(name)
        except ValueError:
            pass
    return result


def _private(value):
    if isinstance(value, str):
        return redaction.redact(value).text
    if isinstance(value, dict):
        return {key: _private(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_private(item) for item in value]
    return value


def status(context):
    reader = Reader(context)
    try:
        return _status(context, reader)
    finally:
        reader.flush()


def _status(context, reader):
    try:
        config = reader.memory.configuration(reader.note, deadline=clock.now() + 10)
        config_status = {"valid": True}
    except configuration.ConfigurationInvalid as error:
        config, config_status = configuration.prepare({}), {"valid": False, "field": error.field}
    reader.memory.check()
    context.configuration = config
    consent = {"needed": configuration.CONSENT_VERSION}
    given = config.values.get("consent")
    if given:
        consent.update(given=given["version"], at=given["at"])
    keys = model_access.Credentials.read().presence()
    names = sorted(config.values["projects"]) if context.arguments["all"] else (
        [context.project.name] if context.project and context.project.name in config.values["projects"] else [])
    data = dict(store=dict(reader.header, folder=_folder_name(reader.memory.folder),
                           writable=status_access.writable(reader.memory.folder)),
                configuration=config_status, consent=consent, keys=keys, temporary=config.values["temporary"],
                test_servers=_servers(), projects=[reader.project(name, config) for name in names],
                sync={"state": "on" if config.values.get("sync") else "off"},
                waits=(["consent"] if not config.consented() else []) + [name + "-key" for name, value in keys.items() if value == "missing"])
    data["store"].pop("made")
    data.update(failures=reader.failures(), hooks=reader.hooks())
    usage = reader.usage(config)
    for api, (_, rejected) in reader.latest.items():
        # Shown only while the key is still set; a later call of that API clears it.
        if rejected and data["keys"].get(api) == "present":
            data["keys"][api] = "rejected"
    if "usage" not in reader.unreadable:
        data["usage"] = usage
    if reader.unreadable:
        data["unreadable"] = sorted(reader.unreadable)
    reader.memory.check()
    say = "Memory status from local recording metadata; model curation is not active in C1."
    if context.kind == activation.FORMAT_1:
        # From release 0.3.0 a format-1 store keeps C1 recording until `migrate` moves it (TASK-117).
        say = ("Memory status from local recording metadata. This store still uses the C1 format: it records, but "
               "curation and recall start only after the migrate command moves it, which asks first.")
    return commands.result("status", _private(data), say)
