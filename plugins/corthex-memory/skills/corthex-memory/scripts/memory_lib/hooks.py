"""Common hook input, host, store and output boundaries. No network imports.

From release 0.3.0 (TASK-117) the hooks find the kind of store first: a
format-2 store takes the C2 steps of `c2_hooks`, and the compaction hooks run;
below it, and for a format-1 store, the hooks record as release 0.2.x does.
"""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from . import activation, base, diagnostics, locks, projects, store
from . import clock

PLUGIN = Path(__file__).resolve().parents[4]
EVENTS = {"start": "SessionStart", "prompt": "UserPromptSubmit", "end-of-turn": "Stop", "end": "SessionEnd"}
SECONDS = {"start": 1.0, "prompt": 0.9, "end-of-turn": 0.3, "end": 0.5}
# From release 0.3.0 (API-155, API-156); they do nothing in Codex and on a format-1 store.
COMPACTION = {"pre-compact": "PreCompact", "post-compact": "PostCompact"}
COMPACTION_SECONDS = {"pre-compact": 0.5, "post-compact": 0.3}
HOST_PROMPTS = ("<task-notification>", "<cross-session-message", "<teammate-message", "<agent-message")
HOST_PROMPTS_VERSION = "host-prompts-2"


def read_input(stream, hook):
    return check_input(parse_input(stream), hook)


def parse_input(stream):
    """The hook's input as JSON, before `check_input` checks its fields."""
    raw = stream.read() if not stream.isatty() else b""
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return store.json_document(raw)


def check_input(event, hook):
    if not isinstance(event, dict) or event.get("hook_event_name") != EVENTS.get(hook, COMPACTION.get(hook)):
        raise ValueError("bad-input")
    session = event.get("session_id")
    if not isinstance(session, str) or not 1 <= len(session) <= 200:
        raise ValueError("bad-input")
    if hook == "prompt" and not isinstance(event.get("prompt"), str):
        raise ValueError("bad-input")
    if hook == "post-compact" and not isinstance(event.get("compact_summary"), str):
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
    format2: bool = False   # a format-2 store, from release 0.3.0: the C2 steps of c2_hooks
    output: object = None
    # The step that a `deadline` outcome's failure line names; None once a C2 step noted its own code.
    late: object = "record"

    def finish(self, outcome):
        if outcome == "deadline" and self.late is not None:
            self.logger.failure("deadline", self.late, self.deadline, hook=self.hook,
                                host=self.host, project=self.project.name, opportunistic=True)
        ms = max(0, int((clock.now() - self.started) * 1000))
        self.logger.timing(self.hook, self.host, ms, outcome, self.deadline, opportunistic=True)

    def failure(self, error):
        self.logger.failure(error, "record", self.deadline, hook=self.hook,
                            host=self.host, project=self.project.name,
                            opportunistic=True)
        self.finish("error")


def process(frame):
    """Record without allowing a whole-hook deadline to skip recording; then, on format 2, the C2 steps."""
    if frame.hook in COMPACTION:
        from . import c2_hooks
        return c2_hooks.compaction(frame)
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
        if frame.format2:
            from . import c2_hooks
            return c2_hooks.prompt(frame, text, recorded)
    elif kind == "answer":
        text = event.get("last_assistant_message")
        if not isinstance(text, str) or not text:
            return "no-answer"
    excluded_kind = "boundary" if kind == "end" else kind
    if kind != "prompt" and frame.project.left_out(frame.configuration, excluded_kind):
        return after_record(frame, "left-out")
    if kind == "end":
        return after_record(frame, record(frame,"end",reason=event.get("reason")))
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
    return after_record(frame, record(frame,kind,prepared,stop_hook_active=event.get("stop_hook_active") is True))


def after_record(frame, outcome):
    """The end-of-turn and session end hooks' outcome; on format 2 the curation triggers follow recording."""
    if frame.format2 and frame.hook in ("end-of-turn", "end"):
        from . import c2_hooks
        return c2_hooks.trigger(frame, outcome)
    return outcome


def record(frame,kind,prepared=None,**options):
    result = recorded(frame,kind,prepared,**options)
    return None if result is None else result.outcome


def recorded(frame,kind,prepared=None,**options):
    """Append one entry; its raw_log.Recorded, or None after a failure noted here."""
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
    return result


def note_failure(logger, error, hook, host, deadline):
    logger.failure(error, "record", deadline, hook=hook,
                   host=host, opportunistic=True)


def run(hook, started, incoming, output):
    c2 = activation.c2()
    if hook not in EVENTS and not (c2 and hook in COMPACTION):
        return
    event, host, logger, frame = None, None, None, None
    start = None
    if hook == "start":
        from .start_hook import Start
        start = Start(started)
    deadline = started + (SECONDS[hook] if hook in SECONDS else COMPACTION_SECONDS[hook])
    notices = []
    early = None
    if hook in COMPACTION:
        # In Codex the compaction hooks end once they have told the host, before any store read and before the
        # input's fields are checked, since Codex gives PostCompact no `compact_summary` (API-155, API-156).
        try:
            early = parse_input(incoming)
        except (OSError, ValueError, TypeError, RecursionError) as error:
            early = error
        if host_for(early if isinstance(early, dict) else {}) == "codex":
            return
        if not isinstance(early, Exception):
            try:
                early = check_input(early, hook)
            except (ValueError, TypeError) as error:
                early = error
    format2 = False
    try:
        try:
            memory = store.MemoryStore()
            if start is not None:
                start.memory = memory
            if c2:
                from . import c2_hooks
                memory, logger, format2 = c2_hooks.bind(memory, deadline)
                if start is not None:
                    start.memory = memory
            else:
                logger = diagnostics.Diagnostics(memory)
            header = logger.read_gate(deadline, lambda error, count: notices.append((error, count)))
            if format2:
                memory.expected = memory.device = header["device"]
                memory.pin = logger._ready[1]
            if start is not None:
                start.header, start.logger, start.format2 = header, logger, format2
        except (OSError, RuntimeError, ValueError) as error:
            if start is not None:
                start.error = error
            logger = None
        if hook in COMPACTION and not format2:
            return  # Nothing to brief or check without a format-2 store.
        try:
            if isinstance(early, Exception):
                raise early
            event = early if early is not None else read_input(incoming, hook)
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
        if format2:
            memory.config = config
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
        frame = Hook(hook, event, host, memory, config, project, logger, started, deadline, format2, output)
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
