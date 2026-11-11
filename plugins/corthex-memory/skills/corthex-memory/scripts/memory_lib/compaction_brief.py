"""TASK-113: the compaction brief hook's text for a format-2 store (API-155 steps 2 to 5, SPEC-146).

`compose` is steps 2 to 4. For an enabled project with consent in Claude Code
it reads the current state through the validity view (TBL-013), without the
layer lease, as the start summary reads it, but without the item files, which
only the decision lines need, and builds the text that Claude Code adds to the
instructions of its compaction: the fixed handoff brief `brief-1` (stage 06),
then the state's goal and next-action lines, each on one line under its label
without cited IDs, the goals first, whole lines under 1,500 characters
together. Next actions that do not fit are left out from the last one back, and
then goals; with no state line the brief's last line, which introduces them, is
left out too. In Codex, whose compaction hooks cannot add instructions, and for
a project that is not enabled or without consent, it gives no outcome, so the
hook prints and writes nothing. A deadline that passes gives `deadline`, and a
state that cannot be read or any other failure gives `error`, with what the
hook's failure log notes; either way nothing is printed and the compaction goes
on as it would without the plugin (SPEC-008). It reads the configuration and
the layer only, and writes nothing.

`output` is step 5: the text as UTF-8 with LF line breaks, which starts with
the brief's first line and never with `{`, so that Claude Code takes it as
text and not as hook JSON.

From release 0.3.0 the compaction brief hook calls it for a format-2 store
(`c2_hooks.compaction`), prints `output` and appends its timing line (step 6);
the PreCompact entry joins `hooks/hooks.json` with the release.
"""
from dataclasses import dataclass

from . import base, locks, start_memory, start_summary

BRIEF = (
    'Write the summary as a handoff brief for the next stretch, not a narrative.',
    "1. Objective: quote the user's current request word for word, then one line on the required result.",
    '2. Established facts: exact paths, commands, values and errors. Mark each as observed or unverified.',
    '3. Changes: each file changed or created, what changed, and whether it was checked.',
    '4. Checks: the exact checks run and their results, including failures.',
    '5. Dead ends: approaches that failed and should not be repeated.',
    '6. Remaining plan: next steps in order and the very next action, then a line that starts with "Done when:" and '
    'gives the condition for done.',
    "Keep the user's own decisions and instructions with their wording and time.",
    'If output was cut, name a narrow command or file range to read it again.',
    'Current memory state (do not restate; correct it only if the conversation contradicts it):',
)  # brief-1 (stage 06); its last line introduces the state lines
PARTS = ('goal', 'next')       # the state's parts that the brief carries, goals first
STATE_CHARACTERS = 1500        # the state lines, each with its line break, stay under this many characters


@dataclass(frozen=True)
class Result:
    outcome: object      # 'ok', 'deadline' or 'error'; None when the hook does not apply, prints nothing and logs nothing
    text: str = ''       # the brief and the state lines, empty unless the outcome is 'ok'
    error: object = None  # what the hook's failure log notes for 'deadline' or 'error': a code or an exception


def compose(memory, project, host, deadline, *, settings=None):
    """API-155 steps 2 to 4 for a format-2 store: a Result, whose text step 5 prints.

    `host` is the host that the hook told from its input, `deadline` the
    hook's end on the clock's monotonic time, and `settings` the hook's
    configuration, by default the store's.
    """
    if host != 'claude-code':
        return Result(None)
    try:
        settings = memory.config if settings is None else settings
        if not settings.enabled(project):
            return Result(None)
        root = memory.folder / 'projects' / base.project_folder_name(project)
        memory.check(deadline)
        view = start_summary.layer_view(memory, root, deadline, decisions=False)
        value = text(() if view is None else view.lines)
        # The store is still the one that the hook found, and the deadline has not passed, when the text goes out.
        memory.check(deadline)
    except locks.LockBusy:
        return Result('deadline', error='deadline')
    except Exception as error:
        return Result('error', error=error)
    return Result('ok', value)


def text(lines):
    """`brief-1` and the goal and next-action lines of `lines`, as the validity view keeps and orders the state."""
    rows = {part: [] for part in PARTS}
    for line in lines:
        if line['part'] in rows:
            # As the start summary shows it, a done condition under its own label, without the cited IDs.
            rows[line['part']].append(start_memory.state_line(dict(line, cites=[])))
    goals, actions = rows['goal'], rows['next']
    used = sum(len(row) + 1 for row in goals + actions)
    while used >= STATE_CHARACTERS:
        # From the last next action back, then the goals from the last one back (SPEC-146, API-155 step 4).
        used -= len((actions or goals).pop()) + 1
    shown = goals + actions
    return '\n'.join(BRIEF + tuple(shown) if shown else BRIEF[:-1]) + '\n'


def output(result):
    """API-155 step 5: the text as UTF-8, or b'' when nothing is printed."""
    return result.text.encode('utf-8') if result.outcome == 'ok' else b''
