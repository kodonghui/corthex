"""TBL-011: the injection log, one file per host session in the project's `injections/` folder.

A line says which items a start summary (`where` `start`, TASK-091) or a
prompt's recall (`prompt`, TASK-094) injected, best first, with recall's
scores; never the text of an item or a prompt. Recall reads it to leave out
the pinned items that the session's start showed and the items that its last
three prompts injected (SPEC-023). The file is named as the session's raw log
file (TBL-007) and is written in a left-out folder too, where no raw log is, by
one append under that raw log file's lock. Retention deletes lines by their own
time (SPEC-009). Nothing writes it before the 0.3.0 activation.
"""
import math

from . import base, clock, curation, diagnostics, files, format2, item_types, locks, raw_log

WHERE = ('start', 'prompt')
ITEMS = 100     # far more than a start summary's 4,000 bytes can show
SESSION = 200   # characters, as the hooks accept a session ID
SECONDS = 1.0   # the append, once the lock is held


def parse_line(data):
    """Strictly read one line of the injection log."""
    value = item_types._document(data)
    curation._shape(value, 'at session where items', 'prompt scores')
    format2._time(value['at'])
    if not isinstance(value['session'], str) or not 1 <= len(value['session']) <= SESSION:
        raise ValueError('invalid injection session')
    curation._choice(value['where'], set(WHERE))
    items = value['items']
    if not isinstance(items, list) or len(items) > ITEMS:
        raise ValueError('invalid injected items')
    for item in items:
        format2._id(item, item_types.ITEM)
    if len(set(items)) != len(items):
        raise ValueError('invalid injected items')
    if value['where'] == 'start' and ('prompt' in value or 'scores' in value):
        raise ValueError('a start line has no prompt or scores')
    if 'prompt' in value:
        format2._id(value['prompt'], item_types.ENTRY)
    if 'scores' in value:
        scores = value['scores']
        if not isinstance(scores, list) or len(scores) != len(items) or any(
                isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score)
                for score in scores):
            raise ValueError('invalid injection scores')
    return value


def line_bytes(value):
    """One checked line, in TBL-011's field order."""
    data = base.json_bytes(value, 'TBL-011', compact=True)
    parse_line(data)
    return data


def append(memory, project, host, session, where, items, *, prompt=None, scores=None, when=None):
    """Append one line for the session: True, or False when its raw log lock stays busy.

    The lock gets one attempt and the short wait of recording (API-001); a lock
    held elsewhere skips the line, as recording skips an entry. Other failures
    propagate to the hook, which notes them in the failure log.
    """
    if host not in diagnostics.HOSTS:
        raise ValueError('invalid host')
    value = {'at': base.utc_time(when), 'session': session, 'where': where, 'items': list(items)}
    if prompt is not None:
        value['prompt'] = prompt
    if scores is not None:
        value['scores'] = list(scores)
    line_bytes(value)
    root = memory.folder / 'projects' / base.project_folder_name(project)
    log = raw_log.log_name(host, session)
    folder = root / 'injections'
    path = folder / (log + '.jsonl')
    step = 'summary' if where == 'start' else 'recall'
    deadline = clock.now() + SECONDS
    try:
        with memory.lease(root / 'raw' / (log + '.lock'), 'raw', deadline, step,
                          acquire_deadline=clock.now() + raw_log.RECORD_SECONDS) as lease:
            def check():
                memory.check(deadline, (lease,))
                memory.fence.check(path)

            check()
            if memory.fence.check(folder) is None:
                base.private_directory(folder)
            files.append_jsonl(path, value, 'TBL-011', lambda error, count: memory.note(error, count, step),
                               check=check, deadline=deadline,
                               reader=lambda candidate: memory.fence.read(candidate, deadline))
    except locks.LockBusy:
        return False
    return True
