---
name: corthex-record
description: CORTHEX records at any stage. Use when turning meeting notes, a recording transcript or a chat thread into minutes and a decision log (DEC IDs), when recording a decision with the user's exact words and where they said them, when writing a progress record after a unit of work, when writing a retrospective after a contest, a demo, a release or an incident, or when finding what was decided earlier and what replaced it.
license: Apache-2.0
metadata:
  author: kodonghui
  version: "0.6.0"
---

# Records

Records let a later session, or another person, pick up the work without asking again. Write them where the project says (`records` in `.corthex/project.json`), or else where the profile says (`records` in `~/.corthex/profile.json`). If neither says, ask once and suggest a `docs/records/` folder in the repository.

| Record | Use | Format |
| --- | --- | --- |
| Minutes | After a meeting or a call | [references/minutes.md](references/minutes.md) |
| Decision | When the user decides something | [references/decisions.md](references/decisions.md) |
| Progress | After a unit of work, or when blocked | [references/progress.md](references/progress.md) |
| Retrospective | After a contest, a demo, a release or an incident, when the user wants one | [references/retrospective.md](references/retrospective.md) |

## Rules

1. A decision needs the decider's own words, where and when they were said, and what it replaces. An AI recommendation, a read receipt or an edit timestamp is not a decision.
2. Keep the original. Summaries point to the transcript, the thread or the file they came from.
3. Update the existing record for the same work instead of starting a new one. Promote a record as new only when its content changed, not for formatting or moves.
4. When a decision replaces an earlier one, mark the earlier one as replaced and link both ways.
5. Never copy secrets, credentials or private personal material into a record.
6. Do not repeat a report that has nothing new.

## Records in Notion

Use one records database per project, one row per record: minutes, decisions, progress, retrospectives, research and reading copies. Its properties are title, kind, stage, status (draft, under discussion, confirmed or replaced), related IDs, source (the repository path), last changed and what changed.

Items followed across several records, such as decisions (DEC) and action items, have their own databases: one row per item, related to the records they came from. Stage items keep their stage databases, including stages 02 to 04 in `corthex-define`.

Create a page only as a row of one of these databases. A table inside a record becomes an inline database in its place; narrative text stays in the row's body.

Read the schema before writing. Reuse existing databases and the row for the same work; mark rows replaced or removed instead of deleting them. The project's `records.location`, or the profile's `records.hub`, points to the records database.

## Finding past decisions

Search the decision log by DEC ID, by the IDs a decision touches (such as `REQ-012`), and by date. Report the latest decision that is still in force, and say which earlier ones it replaced.
