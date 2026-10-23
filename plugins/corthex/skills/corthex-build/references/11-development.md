# Stage 11 · Development

| Slot | This stage |
| --- | --- |
| Inputs | Tasks (TASK), the functional spec (SPEC), the API contract (API), the schema (TBL) and the screen definitions (SCR) |
| Outputs | Code and tests on a branch, in a pull request whose title or description names the TASK and SPEC IDs |
| Human view | Pull request review on the code host, such as GitHub |
| Sync | The pull request moves the task's status. Merged counts as done only after the review and the checks pass |
| Human checkpoints | Review approval and the merge, under the repository's own rules |
| Trace IDs | No new IDs; pull requests and commits name TASK and SPEC IDs |

## Steps

1. Read the repository's own rules first, such as `AGENTS.md`, `CLAUDE.md` and `CONTRIBUTING.md`.
2. Check the real repository root, the branch, existing changes and work in progress by others.
3. Implement against the contracts. If the code needs a contract change, change the contract first (stage 05 or 06) and say so.
4. Write tests for each acceptance criterion the change touches.
5. Open a pull request that names the TASK and SPEC IDs and says what was tested and what was not.

## Checks

- The tests for the touched acceptance criteria pass, and so do the contract tests.
- The diff holds only the intended files and no secrets.
- Screen changes match their screen definitions.

## Output template

```markdown
TASK-001 Create order endpoint (SPEC-001)

- Implements API-001 as in api/openapi.yaml
- Tests: contract tests for API-001; payment failure path (REQ-002)
- Not tested: load
```
