# Stage 10 · WBS

| Slot | This stage |
| --- | --- |
| Inputs | The functional spec (SPEC), the API contract (API) and the screen definitions (SCR) |
| Outputs | `wbs.md`, by default `docs/10-wbs/wbs.md`, or issues in the tracker: one TASK per small, testable slice, such as one create, read, update or delete operation of one SPEC row, with its dependencies, owner and estimate |
| Human view | A board such as GitHub Projects or a shared database, as set in `human` |
| Sync | When the tracker is the truth, the file is a refreshed list. Every task links back to its SPEC IDs |
| Human checkpoints | The plan for the next iteration is agreed |
| Trace IDs | TASK-001… |

## Steps

1. Slice each SPEC row into tasks that one person can finish and test on their own.
2. Add the API operations and screens each task touches.
3. Mark the dependencies, then the owner and the estimate on the project's scale.

## Checks

- Every Must SPEC row has tasks.
- Every task has one owner and a done condition someone else can check.
- The dependencies have no cycles.

## Output template

```markdown
| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-001 | Create order endpoint | SPEC-001 | API-001, TBL-001 | none | backend | 1 day | Contract tests for API-001 pass |
```
