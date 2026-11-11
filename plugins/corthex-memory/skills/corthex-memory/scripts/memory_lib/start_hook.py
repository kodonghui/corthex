"""Start composition and post-output maintenance (API-001).

Below release 0.3.0, and for a format-1 store, this is C1's: the memory part
holds only the consent notice, with no model or item access. From 0.3.0 a
format-2 store's memory part comes from `start_summary` (TASK-091), which reads
the curated layer, and once it is printed `start_summary.after` deletes the
stored notices that it showed and appends the start's injection log line.
"""
import json
import os
from pathlib import Path

from . import base, clock, configuration, context, locks, projects, start_memory, store, worker_launch


class Start:
    def __init__(self, started):
        self.deadline = started + 1.0
        self.memory = self.header = self.configuration = self.error = None
        self.logger = None
        self.base = None
        self.outcome = None
        self.format2 = False   # a format-2 store from release 0.3.0: the C2 start summary
        self.part = None       # its start_summary.Part, once composed

    def prepare(self, event):
        cwd = event.get("cwd") if event else None
        folder = Path(cwd if isinstance(cwd, str) and cwd else os.getcwd()).expanduser().resolve()
        self.base = context.build_context(folder, Path.home(), limit=None)

    def _notice(self, error=None):
        error = self.error if error is None else error
        if isinstance(error, base.MemoryHomeInvalid):
            return (start_memory.Notice("unreadable", "Memory could not be read: "
                                        "CORTHEX_MEMORY_HOME is not an absolute path."),)
        if isinstance(error, configuration.ConfigurationInvalid):
            return (start_memory.unreadable("configuration is invalid at " + error.field),)
        if isinstance(error, store.StoreUnavailable):
            if error.code == "no-store":
                return None
            if error.code in ("store-newer", "store-migrating"):
                # A newer format, or from release 0.3.0 a store that a migration holds (stage 06, Notices).
                return (start_memory.unreadable("the store format is not supported"),)
            reason = "the store record is damaged" if (self.memory.folder / "store.json").exists() else "the store record is missing"
            return (start_memory.unreadable(reason),)
        if isinstance(error, locks.LockBusy):
            return (start_memory.Notice("unreadable", "Memory could not be read in time."),)
        if error is not None:
            return (start_memory.unreadable("an internal memory error occurred"),)
        return None

    def _fixed(self, notice):
        memory = "## Memory\n\n" + notice.text
        limit = start_memory.SUMMARY_BYTES - 2 - len(memory.encode("utf-8"))
        return context.shorten(self.base, limit) + "\n\n" + memory

    def _failure(self, error, host, project, step="record"):
        # Presentation errors do not invalidate the previously read gates.
        try:
            self.logger.failure(error, step, self.deadline, hook="start", host=host,
                                project=project, opportunistic=True)
        except Exception:
            pass

    def _compose(self, registered, host, frame):
        text, outcome = context.shorten(self.base), self.outcome
        if registered is None:
            return text, outcome
        notices, settings = self._notice(), self.configuration
        wants_memory = settings is not None and settings.values["projects"].get(registered.name, {}).get("enabled", False)
        if notices is not None:
            return self._fixed(notices[0]), outcome
        if not wants_memory:
            return text, outcome
        if self.format2:
            return self._summary(registered, host, frame, outcome)
        timeout = start_memory.Notice("unreadable", "Memory could not be read in time.")
        try:
            if clock.now() >= self.deadline:
                return self._fixed(timeout), "deadline" if frame is not None else outcome
            notices = start_memory.consent_notices(settings)
            composed = start_memory.build_summary(self.base, notices)
            if clock.now() >= self.deadline:
                return self._fixed(timeout), "deadline" if frame is not None else outcome
            return composed.text, outcome
        except Exception as error:
            self._failure(error, host, registered.name)
            return self._fixed(self._notice(error)[0]), "error" if frame is not None else outcome

    def _summary(self, registered, host, frame, outcome):
        """API-001 step 5 for a format-2 store: the start summary of `start_summary`, within the deadline."""
        from . import start_summary
        self.part = start_summary.compose(self.memory, registered.name, self.base, self.deadline,
                                          settings=self.configuration)
        if self.part.outcome == "error":
            self._failure(self.part.error, host, registered.name, "summary")
        if self.part.outcome != "ok" and frame is not None:
            outcome, frame.late = self.part.outcome, "summary"
        return self.part.text, outcome

    def _after(self, event, host, frame):
        """API-001 step 7, once the summary is printed: stored notices shown go, and the injection log's line."""
        if self.part is None or frame is None:
            return
        from . import start_summary
        try:
            done = start_summary.after(self.memory, frame.project.name, self.part, host, event["session_id"])
        except Exception as error:
            self._failure(error, host, frame.project.name, "summary")
            return
        for error in done.errors:
            self._failure(error, host, frame.project.name, "summary")

    def finish(self, event, host, frame, output, print_base):
        if self.base is None:
            # Invalid input uses process cwd, never the rejected event's cwd.
            if event is None or host is None:
                print_base(event, output)
                return
            self.prepare(event)
        try:
            registered = frame.project if frame is not None else projects.locate(event.get("cwd"))
        except projects.ProjectError:
            registered = None
        text, outcome = self._compose(registered, host, frame)
        value = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}
        try:
            output.write(json.dumps(value, ensure_ascii=True).encode("ascii") + b"\n")
            output.flush()
        except Exception as error:
            self._failure(error, host, registered.name if registered is not None else None)
            if frame is not None:
                frame.finish("error")
            raise
        try:
            self._after(event, host, frame)
            # The start deadline limits memory composition, not required recording
            # or the API-001 retention launch. Diagnostics retain that deadline.
            if registered is not None and self.configuration is not None and self.error is None:
                worker_launch.launch(self.memory, registered.name, "start", self.deadline,
                                     frame.logger if frame is not None else self.logger,
                                     expected_device=self.header["device"], hook="start", host=host)
        finally:
            if frame is not None:
                frame.finish(outcome or "error")
