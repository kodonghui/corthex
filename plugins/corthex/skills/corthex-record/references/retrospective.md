# Retrospective

Write a retrospective after a large piece of work, such as a contest, a demo, a release or an incident, when the user asks, for the period, stage or pull requests they name. At those moments, offer one; write it when the user says so. Progress records cover single merges, so link them and the decision records instead of repeating them.

## Sources

- Facts come from Git (merged pull requests, tags, commits), check results and the existing records. Copy numbers from their named source.
- When `corthex-memory` records the project, read its records for the period first: curated items where there are any, and the raw records for exact quotes. It keeps prompts and final answers, not tool calls or their results, so take commands, tests and pull request events from Git, the checks and the records. Write the retrospective while the raw records are kept, 100 days by default.
- Say what the sources cover and what they cannot show, such as other devices, older records and projects with recording off.
- Label each statement as a record, a judgement or an estimate. A mistake by the AI is a record only when the user's own words show it. The retrospective is settled once the user has read and corrected it.
- Leave out secrets, other people's names and private material.

## Template

```markdown
# <Work>: retrospective (<period>)
Sources: <Git range, records, memory scope>. Not seen: <what>.
## Result
<What exists now, with links>
## Went well (keep doing)
- <What> — <evidence>
## Went wrong
| What happened | Cause | Effect | Next time |
| --- | --- | --- | --- |
## The AI's mistakes
| What the AI said or did | What was true | The user's words, where and when | Next rule |
| --- | --- | --- | --- |
## The user's reactions
- "<exact words>" (<where>, <when>)
## Checklist for next time
- [ ] <check>
## Checked
<What was verified, and what was not>
```

Keep each "Next time" line and next rule to one sentence, so that similar work can read them first. A next rule becomes a harness rule only after the user approves it.
