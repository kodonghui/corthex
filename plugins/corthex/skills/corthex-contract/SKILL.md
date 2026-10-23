---
name: corthex-contract
description: CORTHEX stages 05 and 06, the data and API contracts. Use when designing or changing the database schema or ERD (DDL, migrations, TBL IDs), comparing the schema in the repository with an ERD tool, or writing and reviewing an OpenAPI contract before implementation (API IDs), including breaking-change checks against the functional spec.
license: Apache-2.0
metadata:
  author: kodonghui
  version: "0.1.0"
---

# Data and API contracts

This skill covers two stages. Each stage's contract, steps, checks and output template are in its reference file. Read only the file for the stage at hand.

| Key | Stage | Contract |
| --- | --- | --- |
| `05-erd` | ERD | [references/05-erd.md](references/05-erd.md) |
| `06-api` | API | [references/06-api.md](references/06-api.md) |

## How a stage runs

1. **Settings.** Read the stage's entry under `stages` in `.corthex/project.json`: `human` (where people look), `source` (the text in the repository) and `truth` (`source` or `human`, the side that wins when they differ). If there is no project file, use the `corthex` skill first.
2. **Inputs.** Read the inputs in the stage contract, with their trace IDs. Name any missing input and ask whether to go on without it.
3. **Outputs.** Write the outputs to `source` with the stage's trace IDs. Never reuse or renumber an ID; mark removed items as removed.
4. **Checks.** Run the stage's checks. Report what passed, what failed and what you could not check.
5. **Sync.** Bring the human view and the source into line in the direction `truth` gives. When `truth` is `human`, refresh the source from the human view and do not edit the source directly. If this session cannot reach the human view through an MCP server, a connector or an API, work from the latest export and follow "Human views the AI cannot reach" in the `corthex` skill's stage contract.
6. **Checkpoint.** Stop at the stage's human checkpoint and ask. Silence, a read receipt or an edit is not approval.
7. **Record.** Record decisions and the next action with `corthex-record`.

## Notes for these stages

- Contracts come before code. Change the schema or the API contract first, then the code that follows it.
- A change that breaks data a screen already shows, or a client already sends, needs the user's decision before it is made.
