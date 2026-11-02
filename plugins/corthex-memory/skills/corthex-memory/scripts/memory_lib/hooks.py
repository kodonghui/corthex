"""Common hook input, host, store and output boundaries. No network imports."""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from . import base, diagnostics, locks, projects, store
from . import clock

PLUGIN = Path(__file__).resolve().parents[4]
EVENTS = {"start": "SessionStart", "prompt": "UserPromptSubmit", "end-of-turn": "Stop", "end": "SessionEnd"}
SECONDS = {"start": 1.0, "prompt": 0.9, "end-of-turn": 0.3, "end": 0.5}
HOST_PROMPTS = ("<task-notification>", "<cross-session-message", "<teammate-message")
HOST_PROMPTS_VERSION = "host-prompts-1"


def read_input(stream, hook):
    raw = stream.read() if not stream.isatty() else b""
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    event = store.json_document(raw)
    if not isinstance(event, dict) or event.get("hook_event_name") != EVENTS[hook]:
        raise ValueError("bad-input")
    session = event.get("session_id")
    if not isinstance(session, str) or not 1 <= len(session) <= 200:
        raise ValueError("bad-input")
    if hook == "prompt" and not isinstance(event.get("prompt"), str):
        raise ValueError("bad-input")
    return event


def host_for(event):
    try:
        if os.path.samefile(os.environ.get("PLUGIN_ROOT", ""), PLUGIN):
            return "codex"
    except (OSError, ValueError, TypeError):
        pass
    if os.environ.get("CLAUDECODE") == "1":
        return "claude-code"
    if "turn_id" in event:
        return "codex"
    if "prompt_id" in event:
        return "claude-code"
    return None


def print_base(event, output):
    from . import context
    cwd = event.get("cwd") if event else None
    folder = Path(cwd if isinstance(cwd, str) and cwd else os.getcwd()).expanduser().resolve()
    text = context.build_context(folder, Path.home())
    value = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}
    output.write(json.dumps(value, ensure_ascii=True).encode("ascii") + b"\n")
    output.flush()


@dataclass
class Hook:
    hook: str
    event: dict
    host: str
    memory: object
    configuration: object
    project: object
    logger: object
    started: float
    deadline: float

    def finish(self, outcome):
        if outcome == "deadline":
            self.logger.failure("deadline", "record", self.deadline, hook=self.hook,
                                host=self.host, project=self.project.name, opportunistic=True)
        ms = max(0, int((clock.now() - self.started) * 1000))
        self.logger.timing(self.hook, self.host, ms, outcome, self.deadline, opportunistic=True)

    def failure(self, error):
        self.logger.failure(error, "record", self.deadline, hook=self.hook,
                            host=self.host, project=self.project.name,
                            opportunistic=True)
        self.finish("error")


def process(frame):
    """Record without allowing a whole-hook deadline to skip recording."""
    if frame.hook == "start":
        if frame.project.left_out(frame.configuration, "boundary"):
            return "left-out"
        outcome = record(frame, "start", source=frame.event.get("source"))
        return "error" if outcome == "lock-busy" else outcome
    from . import raw_log
    event = frame.event
    kind = {"prompt": "prompt", "end-of-turn": "answer", "end": "end"}[frame.hook]
    if kind == "prompt":
        text = event["prompt"]
        if text.lstrip().startswith(HOST_PROMPTS):
            return "left-out"
    elif kind == "answer":
        text = event.get("last_assistant_message")
        if not isinstance(text, str) or not text:
            return "no-answer"
    excluded_kind = "boundary" if kind == "end" else kind
    if kind != "prompt" and frame.project.left_out(frame.configuration, excluded_kind):
        return "left-out"
    if kind == "end":
        return record(frame,"end",reason=event.get("reason"))
    try:
        prepared = raw_log.prepare(text)
    except Exception:
        frame.failure("redaction")
        return None
    if kind == "prompt" and frame.project.left_out(frame.configuration, "prompt"):
        return "left-out"
    # Started redaction finishes, and its entry retains the post-redaction
    # lock wait even if the whole-hook deadline has since passed. An acquired
    # raw lease finishes its bounded read, append and marker.
    return record(frame,kind,prepared,stop_hook_active=event.get("stop_hook_active") is True)


def record(frame,kind,prepared=None,**options):
    from . import raw_log
    log = raw_log.RawLog(frame.memory,frame.project.name,frame.host,frame.event["session_id"])
    notices = []
    def failure(error,count=None):
        frame.logger.failure(error,"record",frame.deadline,hook=frame.hook,host=frame.host,
                             project=frame.project.name,log=log.log,count=count,
                             opportunistic=True)
    try:
        result = log.append(kind,prepared,diagnostic_deadline=frame.deadline,notices=notices,**options)
    except FileNotFoundError as error:
        failure(error)
        return None
    missing = next((error for error,_ in notices if isinstance(error,FileNotFoundError)),None)
    if missing is not None:
        failure(missing)
        return None
    for error,count in notices:
        failure(error,count)
    return result.outcome


def note_failure(logger, error, hook, host, deadline):
    logger.failure(error, "record", deadline, hook=hook,
                   host=host, opportunistic=True)


def run(hook, started, incoming, output):
    if hook not in EVENTS:
        return
    event, host, logger, frame = None, None, None, None
    start = None
    if hook == "start":
        from .start_hook import Start
        start = Start(started)
    deadline = started + SECONDS[hook]
    notices = []
    try:
        try:
            memory = store.MemoryStore()
            if start is not None:
                start.memory = memory
            logger = diagnostics.Diagnostics(memory)
            header = logger.read_gate(deadline, lambda error, count: notices.append((error, count)))
            if start is not None:
                start.header, start.logger = header, logger
        except (OSError, RuntimeError, ValueError) as error:
            if start is not None:
                start.error = error
            logger = None
        try:
            event = read_input(incoming, hook)
        except (OSError, ValueError, TypeError, RecursionError):
            if logger is not None:
                note_failure(logger, "bad-input", hook, None, deadline)
            return
        host = host_for(event)
        if host is None:
            if logger is not None:
                note_failure(logger, "unknown-host", hook, None, deadline)
            return
        if logger is None:
            return
        config = memory.configuration(lambda error, count: notices.append((error, count)), deadline=deadline)
        if start is not None:
            start.configuration = config
            start.prepare(event)
        for error, count in notices:
            logger.failure(error, "record", deadline, hook=hook, host=host, count=count,
                           opportunistic=True)
        if not config.consented():
            return
        project = projects.find(config, event.get("cwd"))
        if project is None:
            return
        frame = Hook(hook, event, host, memory, config, project, logger, started, deadline)
        outcome = process(frame)
        if start is not None:
            start.outcome = outcome
        elif outcome is not None:
            frame.finish(outcome)
    except Exception as error:
        if start is not None:
            start.error, start.outcome = error, "error"
        if isinstance(error,store.StoreUnavailable):
            pass
        elif frame is not None and isinstance(error,locks.LockBusy):
            frame.logger.failure(error,"record",deadline,hook=hook,host=host,project=frame.project.name,
                                 opportunistic=True)
            if start is None:
                frame.finish("lock-busy")
        elif frame is not None:
            if start is None:
                frame.failure(error)
            else:
                frame.logger.failure(error, "record", deadline, hook=hook, host=host,
                                     project=frame.project.name, opportunistic=True)
        elif logger is not None:
            note_failure(logger, error, hook, host, deadline)
    finally:
        if hook == "start":
            try:
                start.finish(event, host, frame, output, print_base)
            except Exception as error:
                sys.stderr.write("corthex-memory: " + type(error).__name__ + "\n")
