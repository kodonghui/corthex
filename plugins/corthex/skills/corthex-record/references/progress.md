# Progress records

Write a progress record when a unit of work ends, when a decision is made and when work is blocked. Continue the record of the same work instead of starting a new one.

## Template

```markdown
### <YYYY-MM-DD HH:MM, time zone> · <work>

- Done: what was done
- Why: the request or decision it serves
- Result: what exists now, with links
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
