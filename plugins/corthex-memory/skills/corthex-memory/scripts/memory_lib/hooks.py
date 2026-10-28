"""Common hook input, host, store and output boundaries. No network imports."""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from . import base, diagnostics, projects, store
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
        late = clock.now() >= self.deadline
        if late:
            outcome = "deadline"
            self.logger.failure("deadline", "record", self.deadline, hook=self.hook,
                                host=self.host, project=self.project.name, opportunistic=True)
        ms = max(0, int((clock.now() - self.started) * 1000))
        self.logger.timing(self.hook, self.host, ms, outcome, self.deadline, opportunistic=late)

    def failure(self, error):
        if clock.now() < self.deadline:
            self.logger.failure(error, "record", self.deadline, hook=self.hook,
                                host=self.host, project=self.project.name)
        self.finish("error")


def process(frame):
    """Recording is added by TASK-010–012; start memory is TASK-017."""
    return None


def note_failure(logger, error, hook, host, deadline):
    late = clock.now() >= deadline
    logger.failure("deadline" if late else error, "record", deadline, hook=hook,
                   host=host, opportunistic=late)


def run(hook, started, incoming, output):
    if hook not in EVENTS:
        return
    event, host, logger, frame = None, None, None, None
    deadline = started + SECONDS[hook]
    notices = []
    try:
        try:
            memory = store.MemoryStore()
            logger = diagnostics.Diagnostics(memory)
            logger.read_gate(deadline, lambda error, count: notices.append((error, count)))
        except (OSError, RuntimeError, ValueError):
            logger = None
        try:
            event = read_input(incoming, hook)
        except (OSError, ValueError, TypeError):
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
        for error, count in notices:
            logger.failure(error, "record", deadline, hook=hook, host=host, count=count)
        if not config.consented():
            return
        project = projects.find(config, event.get("cwd"))
        if project is None:
            return
        frame = Hook(hook, event, host, memory, config, project, logger, started, deadline)
        if clock.now() >= deadline:
            frame.finish("deadline")
            return
        outcome = process(frame)
        if outcome is not None:
            frame.finish(outcome)
    except Exception as error:
        if frame is not None:
            frame.failure(error)
        elif logger is not None:
            note_failure(logger, error, hook, host, deadline)
    finally:
        if hook == "start":
            try:
                print_base(event, output)
            except Exception as error:
                sys.stderr.write("corthex-memory: " + type(error).__name__ + "\n")
