"""TASK-114: the compaction check hook (API-156, SPEC-147) and its line in the next prompt (API-002 steps 6 to 8).

`missing` is API-156 step 3: it looks in a compaction summary, by stage 06's
rules `check-1` and without a model, for the seven parts of a handoff brief,
and gives the parts that it lacks in TBL-122's order. It reads the summary in
slices of whole lines and checks the deadline between them, so that a summary
of many lines ends within the hook's 300 ms; one line longer than a slice is
read as one slice.

`check` is steps 2 to 5 for a format-2 store. In Codex, and for a project
that is not enabled or without consent, it gives no outcome and writes
nothing. Otherwise, under the session's raw log lock with recording's short
wait, it writes the session's compaction check (TBL-122), the missing parts
and the time, through a new file and a move without the flush and the backup,
as a notice is written, or deletes the session's check when no part is
missing; with no check to delete it takes no lock, and a link or a folder in
the check's place is left and gives `error`. It then deletes the project's
checks of other sessions that are more than 7 days old, by their time or, when
they cannot be read, by their file's time, and the copies, of any session,
that a stopped write left without a check beside them by their files' time,
each under its session's raw log lock with one attempt. A busy lock leaves the
check for a later compaction; a check that cannot be read or deleted is noted
in the failure log, and one whose place a link or a folder takes is left, as
retention leaves them. Nothing of the summary goes into a file, a log line or
a request.

`pending`, `line` and `clear` are the prompt hook's steps 6 to 8: the
session's check, read under its raw log lock; the line that names its missing
parts; and the check's deletion under the same lock once the line is printed,
only while the file still holds the bytes that were read, so that a check
that a later compaction wrote stays for the next prompt.

From release 0.3.0 the compaction check hook calls `check`, and the prompt
hook `pending`, `line` and `clear`, for a format-2 store (`c2_hooks`); the
PostCompact entry joins `hooks/hooks.json` with the release.
"""
import contextlib
from dataclasses import dataclass
from datetime import datetime, timezone
import re
import stat
import unicodedata

from . import base, cleanup, clock, files, format2, item_types, locks, raw_log, retention, run_log, worker_support

PARTS = ('objective', 'facts', 'changes', 'checks', 'dead-ends', 'plan', 'done')
SHOWN = dict(zip(PARTS, ('objective', 'established facts', 'changes', 'checks', 'dead ends', 'remaining plan',
                         'done condition')))
NAMES = dict(zip(PARTS, (
    ('objective', 'goal', 'current request', 'user request', 'task', '목표', '목적', '현재 요청', '사용자 요청'),
    ('established facts', 'facts', 'findings', '확인된 사실', '사실', '알아낸 것'),
    ('changes', 'changes made', 'files changed', 'changed files', '바꾼 것', '바꾼 파일', '변경', '변경 사항'),
    ('checks', 'checks run', 'tests', 'test results', 'verification', '검사', '검사 결과', '테스트'),
    ('dead ends', 'dead end', 'failed approaches', 'what failed', '막힌 길', '막다른 길', '실패한 시도', '실패한 접근'),
    ('remaining plan', 'plan', 'next steps', 'remaining steps', '남은 계획', '계획', '다음 단계', '남은 일'),
    ('done when', 'done condition', 'condition for done', 'definition of done', '끝나는 조건', '완료 조건', '완료 기준'),
)))  # check-1 (stage 06)
VERSION = 'check-1'
DAYS = 7                 # the age past which a check deletes other sessions' checks
SLICE = 64 * 1024        # characters of the summary read between two deadline checks
LINE = 'The last compaction summary has no %s; read the handoff record or the transcript before going on.'
# A check, or a copy that `files.delete_file` deletes with it: its backup and any temporary file.
NAME = re.compile('(' + cleanup.LOG + r')\.json(?:\.bak|\..*\.tmp)?\Z', re.S)

# check-1's form of a line: in NFC and lower case, without #, *, _, `, > and +, each - and each run of white space
# one space, trimmed, and without a leading list number of up to three digits or one letter and `.` or `)`.
_FORM = str.maketrans({'#': None, '*': None, '_': None, '`': None, '>': None, '+': None, '-': ' '})
_BLANKS = re.compile(r'[^\S\n]+')
_BREAK = re.compile(r'\r\n?|\n')
_NUMBER = r'(?:(?:[0-9]{1,3}|[^\W\d_])[.)] )?'


def _pattern(parts):
    """Lines in check-1's form that start with a name of one of `parts`, followed by the end or a non-alphanumeric."""
    names = '|'.join('(?P<%s>%s)' % (part.replace('-', '_'), '|'.join(
        re.escape(name) for name in sorted(NAMES[part], key=len, reverse=True))) for part in parts)
    return re.compile(r'^ ?%s(?:%s)(?!\w)' % (_NUMBER, names), re.M)


def _form(lines):
    """Whole lines in check-1's form, with LF line breaks."""
    text = unicodedata.normalize('NFC', lines).lower().replace('\r\n', '\n').replace('\r', '\n')
    return _BLANKS.sub(' ', text.translate(_FORM))


def missing(summary, deadline=None):
    """API-156 step 3: the parts of a handoff brief that `summary` lacks, in TBL-122's order (check-1).

    The summary is read in slices of whole lines, each about SLICE characters
    or one longer line, and a deadline that has passed before a slice raises
    `LockBusy`. A part found in one slice is not looked for in the next ones.
    """
    left, start = list(PARTS), 0
    pattern = _pattern(left)
    while left and start < len(summary):
        if deadline is not None and clock.now() >= deadline:
            raise locks.LockBusy()
        found = _BREAK.search(summary, min(start + SLICE, len(summary)))
        end = len(summary) if found is None else found.end()
        parts = {match.lastgroup.replace('_', '-') for match in pattern.finditer(_form(summary[start:end]))}
        if parts:
            left = [part for part in left if part not in parts]
            pattern = _pattern(left) if left else None
        start = end
    return left


@dataclass(frozen=True)
class Result:
    outcome: object      # 'ok', 'lock-busy', 'deadline' or 'error'; None when the hook does not apply and writes nothing
    missing: tuple = ()  # the parts that the summary lacks, which the session's check names once step 4 moved it
                         # into place, also when a later step stops
    errors: tuple = ()   # (log, error) of each other session's check deleted unread or that could not be read or
                         # deleted, which the failure log notes, whatever the outcome
    error: object = None  # what the failure log notes for 'lock-busy', 'deadline' or 'error': a code or an exception


@dataclass(frozen=True)
class Pending:
    missing: tuple       # the parts that the session's check names
    data: bytes          # the check's bytes, which `clear` deletes only while the file still holds them


def parse_check(data):
    """Strictly read a compaction check (TBL-122); any content that it cannot read raises ValueError."""
    try:
        value = item_types._document(data)
    except RecursionError:
        raise ValueError('invalid compaction check') from None
    if not isinstance(value, dict) or set(value) != {'at', 'missing'}:
        raise ValueError('invalid compaction check')
    format2._time(value['at'])
    parts = value['missing']
    if not isinstance(parts, list) or not parts or not all(isinstance(part, str) and part in PARTS for part in parts) \
            or parts != sorted(set(parts), key=PARTS.index):
        raise ValueError('invalid compaction check')
    return value


def check_bytes(value):
    value = parse_check(item_types._raw(value))
    return item_types._bytes({'at': value['at'], 'missing': value['missing']})


def line(parts):
    """API-002 step 7's line for the parts that a check names, joined by `, ` and a final ` or `."""
    shown = [SHOWN[part] for part in parts]
    return LINE % (shown[0] if len(shown) == 1 else ', '.join(shown[:-1]) + ' or ' + shown[-1])


def check(memory, project, host, session, summary, deadline, *, settings=None, when=None):
    """API-156 steps 2 to 5 for a format-2 store: a Result; the hook appends its timing line (step 6).

    `host` is the host that the hook told from its input, `session` the
    session's ID, `summary` the input's `compact_summary`, a string, and
    `deadline` the hook's end on the clock's monotonic time; `settings` is the
    hook's configuration, by default the store's, and `when` the check's time.
    """
    if host != 'claude-code':
        return Result(None)
    unreadable, parts, data, path = [], (), None, None
    try:
        settings = memory.config if settings is None else settings
        if not settings.enabled(project):
            return Result(None)
        root, log, path = _place(memory, project, host, session)
        at = base.utc_time(when)
        memory.check(deadline)
        parts = tuple(missing(summary, deadline))
        data = check_bytes({'at': at, 'missing': list(parts)}) if parts else None
        _session(memory, root, log, path, data, deadline)
        _expire(memory, root, at, deadline, unreadable)
    except locks.LockBusy:
        code = 'deadline' if clock.now() >= deadline else 'lock-busy'
        return Result(code, _written(memory, path, data, parts), tuple(unreadable), code)
    except Exception as error:
        return Result('error', _written(memory, path, data, parts), tuple(unreadable), error)
    return Result('ok', parts, tuple(unreadable))


def _place(memory, project, host, session):
    """The project's folder, the session's raw log name and the path of the session's check."""
    root = memory.folder / 'projects' / base.project_folder_name(project)
    log = raw_log.log_name(host, session)
    return root, log, root / 'compaction' / (log + '.json')


@contextlib.contextmanager
def _locked(memory, root, log, path, deadline, step, wait=True):
    """The session's raw log lock, with recording's short wait or one attempt, and a guard of it and of `path`."""
    acquire = clock.now() + raw_log.RECORD_SECONDS if wait else None
    with memory.lease(root / 'raw' / (log + '.lock'), 'raw', deadline, step, acquire_deadline=acquire) as lease:
        def guard():
            memory.check(deadline, (lease,))
            _file(memory, path)

        yield guard


def _file(memory, path):
    """`path`'s stat result, or None when nothing is there; UnsafePath for a link, a folder or anything else that
    is not a file, which no step reads, replaces or deletes."""
    info = memory.fence.check(path)
    if info is not None and not stat.S_ISREG(info.st_mode):
        raise worker_support.UnsafePath()
    return info


def _session(memory, root, log, path, data, deadline):
    """Step 4: the session's check written with `data`, or deleted without it, under its raw log lock.

    With no `data` and no check, there is nothing to delete and no lock to wait
    for: only this session's own hooks write its check. A link or a folder in
    its place raises UnsafePath, before the lock and again under it, and is
    left with its copies.
    """
    if _file(memory, path) is None and data is None:
        return
    with _locked(memory, root, log, path, deadline, 'compaction') as guard:
        guard()
        if data is None:
            files.delete_file(path, guard)
            return
        if memory.fence.check(path.parent) is None:
            base.private_directory(path.parent)
        files.replace_bytes(path, data, True, check=guard, path_check=memory.fence.check)


def _written(memory, path, data, parts):
    """`parts` when the session's check holds `data` once a step stopped, read once more; () otherwise.

    The check names them from the move on: a deadline or a lost lease can stop
    the clean-up just after the move, as it can stop step 5.
    """
    if data is None:
        return ()
    try:
        return parts if memory.fence.read(path, clock.now() + 1) == data else ()
    except Exception:
        return ()


def _expire(memory, root, at, deadline, unreadable):
    """Step 5: the project's checks of other sessions more than 7 days old, deleted under their raw log locks.

    A check goes by its `at`, or by its file's time when it cannot be read, and
    the copies that a stopped write left without a check beside them by their
    newest file's time, also this session's: step 4 has just written its check
    at `at` or deleted it, so only its copies can be old. Each old one is read
    again under its session's raw log lock, with one attempt, since a later
    compaction of that session writes under the same lock, and a busy lock
    leaves it for a later check. Each deleted check that could not be read, and
    each check or copy that could not be read or deleted otherwise, joins
    `unreadable` as its raw log's name and the error, for the failure log, as
    soon as it is found, so that a step that ends early still notes it; the
    others go on. A session whose check or copy is a link or a folder is left.
    """
    folder = root / 'compaction'
    if memory.fence.check(folder) is None:
        return
    cutoff = run_log._cutoff(at, DAYS)[1]
    sessions = {}
    for name in run_log._names(folder):
        match = NAME.fullmatch(name)
        if match:
            sessions.setdefault(match.group(1), []).append(folder / name)
    for log in sorted(sessions):
        memory.check(deadline)
        path = folder / (log + '.json')
        copies = [name for name in sessions[log] if name != path]
        try:
            found = _age(memory, path, copies, deadline)
            if found is None or found[0] >= cutoff:
                continue
            with _locked(memory, root, log, path, deadline, 'compaction', wait=False) as guard:
                found = _age(memory, path, copies, deadline)
                if found is not None and found[0] < cutoff:
                    files.delete_file(path, guard)
                    if found[1] is not None:
                        unreadable.append((log, found[1]))
        except worker_support.UnsafePath:
            continue
        except locks.LockBusy:
            if clock.now() >= deadline:
                raise
        except OSError as error:
            unreadable.append((log, error))


def _age(memory, path, copies, deadline):
    """A check's time and None, or its file's time and the error when it cannot be read; without a check, the
    newest time of the copies in `copies` that are still there and None; None when nothing is left.

    A link or a folder in the place of the check or a copy raises UnsafePath,
    since the check's deletion would take the copies too.
    """
    found = [_file(memory, copy) for copy in copies]
    info = _file(memory, path)
    if info is not None:
        try:
            return retention._time(parse_check(files.fence_read(memory, path, deadline))['at']), None
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as error:
            return datetime.fromtimestamp(info.st_mtime, timezone.utc), error
    times = [entry.st_mtime for entry in found if entry is not None]
    return (datetime.fromtimestamp(max(times), timezone.utc), None) if times else None


def pending(memory, project, host, session, deadline):
    """API-002 step 6: the session's check as a Pending, or None; read under the session's raw log lock.

    A check that cannot be read, for its content or an error of the system, is
    deleted under the same lock and raises its error for the failure log
    (TBL-122); on Windows a file that another process holds is read again until
    the deadline. A busy lock, or a deadline that passes, raises `LockBusy`,
    which leaves the check for a later prompt. A link or a folder in the
    check's place raises UnsafePath and is left, also under the lock.
    """
    root, log, path = _place(memory, project, host, session)
    if _file(memory, path) is None:
        return None
    with _locked(memory, root, log, path, deadline, 'recall') as guard:
        guard()
        try:
            data = files.fence_read(memory, path, deadline)
            return Pending(tuple(parse_check(data)['missing']), data)
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            files.delete_file(path, guard)
            raise


def clear(memory, project, host, session, shown, deadline):
    """API-002 step 8: the check whose line was printed deleted under the session's raw log lock.

    Only while the file still holds the bytes that were read: a check that a
    later compaction wrote stays for the next prompt. True when it was deleted.
    """
    root, log, path = _place(memory, project, host, session)
    with _locked(memory, root, log, path, deadline, 'recall') as guard:
        try:
            if files.fence_read(memory, path, deadline) != shown.data:
                return False
        except FileNotFoundError:
            return False
        files.delete_file(path, guard)
        return True
