# Progress records

Write a progress record when a unit of work ends, when a decision is made and when work is blocked. Continue the record of the same work instead of starting a new one.

## Template

```markdown
### <YYYY-MM-DD HH:MM, time zone> · <work>

- Done: what was done
- Why: the request or decision it serves
- Result: what exists now, with links. Numbers are copied from the command output or source, which is named.
- Checked: what was verified, and what was not
- Next: the next action and who takes it
```

For a blocker, add:

```markdown
- Blocked by: what is missing, such as a login, an access right or a decision
- Needed from: who can unblock it, where, and the exact action
```

## Rules

- Write what happened, not what was planned. A plan goes under `Next`.
- Say which checks ran. "Tests pass" names the tests; "looks right" names what was looked at.
- Never include secrets or credentials.

## Handoff

Write a handoff when work moves to another session, agent, account or person, and before a planned compaction or a long break. It is a briefing for whoever continues, not a diary: give what they need to act, and point to the rest. Keep it to about one screen, 60 lines at most.

```markdown
### Handoff <YYYY-MM-DD HH:MM, time zone> · <work>

- Goal: the result asked for, in one line, with the requester's own words or a link to them
- Facts: exact paths, commands, values and errors that were confirmed, each with its source; label guesses and unverified ideas as such
- Changed: each file, record or setting that was changed, and whether the change was verified
- Checks: the checks that ran, with their results, failures and workarounds
- Dead ends: approaches that failed and should not be tried again, and why
- Next: the remaining steps in order, starting with the very next action or command
- Done when: the condition that ends the work
- Pointers: where to read more: file paths with line ranges, commit SHAs, record links, transcript lines and words to search for
```

### Handoff rules

- Do not paste large material, such as a long log, a whole file or an earlier handoff. List the files, the words to search for and the line ranges to read, so the next session reads only what it needs.
- Copy exact values from their source. A number, a path or an error retyped from memory is a guess and is labelled as one.
- A handoff points to the records it comes from and does not replace them. When the same work moves again, update its handoff instead of writing a second one.
- Never include secrets, credentials or private personal material.
