# Decision log

One row per decision. The log lives in the project's records location, or in `docs/decisions.md` in the repository when the project has no other place.

## Template

```markdown
| ID | When | Decision | Decided by | Their words | Where | Replaces | Affects | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DEC-001 | 2026-01-05 14:20 KST | The spec database is the source of truth for stage 04 | Product owner | "Let's keep the spec in the shared database" | Kickoff meeting minutes | none | 04-functional-spec | in force |
```

## Rules

- `Their words` is a quote, not a summary. `Where` is enough to find the quote again: the meeting, the thread or the message, with its time.
- An AI recommendation, a read receipt, an emoji or an edit timestamp is not a decision. Record a recommendation as a recommendation until someone decides.
- When a decision replaces an earlier one, set the earlier one's status to `replaced by DEC-…` and fill `Replaces` on the new one.
- `Affects` names the stages or trace IDs that change, so later stages can find the decisions that bind them.
