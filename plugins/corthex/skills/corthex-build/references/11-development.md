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
4. Back end: return exactly the responses the API contract lists, with their schemas. Run the contract tests against a development or staging server, never production, with a test account: for example `schemathesis run api/openapi.yaml --url <server> -H "Authorization: Bearer <test token>"`.
5. Front end: build each screen against the mock server first (stage 06), show each response the way the screen definition says, then switch to the real server.
6. Write tests for each acceptance criterion the change touches.
7. Open a pull request that names the TASK and SPEC IDs and says what was tested and what was not.

## Checks

- The tests for the touched acceptance criteria pass.
- The contract tests pass for every operation the change touches, and the report names the tool, the server and the commit.
- Each touched operation is reported in two steps that do not imply each other: provided, when the back end passes its contract tests, and accepted, when the front end works against the real server and its screens pass.
- The diff holds only the intended files and no secrets.
- Screen changes match their screen definitions, including the state each response leads to.

## Output template

```markdown
TASK-001 Create order endpoint (SPEC-001)

- Implements API-001 as in api/openapi.yaml
- Contract tests: Schemathesis against staging, all checks passed for API-001 (commit abc1234)
- Tests: payment failure path (REQ-002)
- API-001: provided; not yet accepted, the checkout screen still uses the mock server
- Not tested: load
```
