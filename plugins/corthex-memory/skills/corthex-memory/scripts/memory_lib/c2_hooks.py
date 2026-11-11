"""The hooks' C2 steps for a format-2 store, from release 0.3.0 (TASK-117 step 2).

`hooks.run` finds the kind of store from its two store records, as the command
runner does, once the running release is 0.3.0 or later. A format-2 store gets
the format-2 binding (`c2_store.CommandStore`), whose gate pins the store record
that it read, and these steps; a format-1 store, and every store below 0.3.0,
keeps C1's hooks, which record and do nothing more. A store that a migration
holds, of a newer format or damaged refuses as the kind says, before any record
is read or restored, so that its start summary names what is wrong.

- Prompt hook (API-002): the prompt is redacted once and recorded unless it is
  left out; recall then runs also where it is left out (SPEC-006), the session's
  compaction check is read, both go out as one added context, the check that
  was printed is deleted and the injection log takes the prompt's line.
- End-of-turn and session end hooks (API-003, API-004): after recording, the
  curation triggers (SPEC-010) may start the memory worker.
- Start hook (API-001): `start_summary` builds the memory part and, once it is
  printed, deletes the stored notices it showed and appends the start's
  injection log line (`hooks.Start`).
- Compaction hooks (API-155, API-156): the brief before a compaction and the
  check after it, in Claude Code only; in Codex they end before any store read.

Network and SQLite modules load only for recall, from `prompt_recall`.
"""
from . import activation, clock, locks

# What a store that the hooks do not read refuses, by its kind.
REFUSED = {activation.MIGRATING: "store-migrating", activation.NEWER: "store-newer",
           activation.DAMAGED: "store-damaged"}


def bind(memory, deadline):
    """The binding and logger for the kind of store at `memory.folder`, and whether it is of format 2.

    A missing folder, and a format-1 store, keep C1's binding and its gate.
    """
    from . import c2_store, diagnostics, files, store, worker_support
    if not memory.folder.exists():
        return memory, diagnostics.Diagnostics(memory), False
    fence = worker_support.PathFence(memory.folder)
    kind = activation.store_kind(fence.root, lambda path: files._retry(lambda: fence.read(path, deadline), deadline))
    if kind in REFUSED:
        raise store.StoreUnavailable(REFUSED[kind])
    if kind != activation.FORMAT_2:
        return memory, diagnostics.Diagnostics(memory), False
    bound = c2_store.CommandStore(fence)
    return bound, bound.logger, True


def note(frame, error, step, **fields):
    """One failure log line for a C2 step, as the hook's own failures are noted."""
    frame.logger.failure(error, step, frame.deadline, hook=frame.hook, host=frame.host,
                         project=frame.project.name, opportunistic=True, **fields)


def prompt(frame, text, record):
    """API-002 steps 3 to 9 for a prompt that the host did not make; the hook's outcome.

    `record(frame, kind, prepared)` records the prompt and gives its
    `raw_log.Recorded`, or None after a failure that it noted.
    """
    from . import compaction_check, prompt_recall, raw_log
    try:
        prepared = raw_log.prepare(text)
    except Exception:
        frame.failure("redaction")
        return None
    outcome, entry = "left-out", None
    if not frame.project.left_out(frame.configuration, "prompt"):
        recorded = record(frame, "prompt", prepared)
        if recorded is None:
            return None
        # The line names the prompt's raw entry when one was written (TBL-011).
        outcome, entry = recorded.outcome, recorded.entry["id"] if recorded.entry else None
    memory, project, host = frame.memory, frame.project.name, frame.host
    session, deadline = frame.event["session_id"], frame.deadline
    result = prompt_recall.recall(memory, project, host, session, prepared.text, frame.started, deadline,
                                  settings=frame.configuration)
    late, failed = result.outcome == "late", result.outcome == "failed"
    if late or failed:
        note(frame, result.error, "recall")  # A late recall's line carries its code, so no second line.
    frame.late, busy, pending = None, False, None
    try:
        # A check not yet read when the deadline passes, or whose lock stays busy, waits for the next prompt.
        if clock.now() >= deadline:
            late, frame.late = True, "compaction"
        else:
            pending = compaction_check.pending(memory, project, host, session, deadline)
    except locks.LockBusy:
        busy = True
    except Exception as error:
        note(frame, error, "compaction")
        failed = True
    data = prompt_recall.output(result, compaction_check.line(pending.missing) if pending else None)
    if data:
        frame.output.write(data)
        frame.output.flush()
        if pending:
            try:
                compaction_check.clear(memory, project, host, session, pending, deadline)
            except locks.LockBusy:
                pass  # The check stays, and the next prompt shows its line again.
            except Exception as error:
                note(frame, error, "compaction")
                failed = True
    try:
        prompt_recall.log(memory, project, host, session, result, entry=entry)
    except Exception as error:
        note(frame, error, "recall")
        failed = True
    if outcome in ("ok", "left-out"):
        outcome = "error" if failed else "deadline" if late else "lock-busy" if busy else outcome
    return outcome


def trigger(frame, outcome):
    """API-003 step 4 and API-004 step 3, after recording: the hook's outcome."""
    if outcome in (None, "no-answer"):
        return outcome
    from . import curation_triggers
    try:
        reason = curation_triggers.start(frame.memory, frame.configuration, frame.project.name, frame.hook,
                                         frame.deadline, frame.logger, host=frame.host)
    except Exception as error:
        note(frame, error, "trigger")
        return "error" if outcome in ("ok", "left-out") else outcome
    if reason == "deadline" and outcome in ("ok", "left-out"):
        frame.late = "trigger"
        return "deadline"
    return outcome


def compaction(frame):
    """API-155 steps 2 to 5 and API-156 steps 2 to 5: the hook's outcome, None when it does not apply."""
    memory, project, host, deadline = frame.memory, frame.project.name, frame.host, frame.deadline
    if frame.hook == "pre-compact":
        from . import compaction_brief
        result = compaction_brief.compose(memory, project, host, deadline, settings=frame.configuration)
        data = compaction_brief.output(result)
        if data:
            frame.output.write(data)
            frame.output.flush()
    else:
        from . import compaction_check
        result = compaction_check.check(memory, project, host, frame.event["session_id"],
                                        frame.event["compact_summary"], deadline, settings=frame.configuration)
        for log, error in result.errors:
            note(frame, error, "compaction", log=log)
    frame.late = "compaction"
    if result.outcome is not None and result.error is not None:
        note(frame, result.error, "compaction")
        frame.late = None
    return result.outcome
