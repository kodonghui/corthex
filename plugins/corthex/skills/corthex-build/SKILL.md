---
name: corthex-build
description: CORTHEX stages 10 to 12, building and testing. Use when breaking the spec into work items (WBS, TASK IDs), planning or reviewing development work and pull requests that should trace to tasks and specs, or writing a QA test plan, end-to-end tests and bug reports (TC and BUG IDs) from the user flows and acceptance criteria.
license: Apache-2.0
metadata:
  author: kodonghui
  version: "0.1.0"
---

# Building and testing

This skill covers three stages. Each stage's contract, steps, checks and output template are in its reference file. Read only the file for the stage at hand.

| Key | Stage | Contract |
| --- | --- | --- |
| `10-wbs` | WBS | [references/10-wbs.md](references/10-wbs.md) |
| `11-development` | Development | [references/11-development.md](references/11-development.md) |
| `12-qa` | QA | [references/12-qa.md](references/12-qa.md) |

## How a stage runs

1. **Settings.** Read the stage's entry under `stages` in `.corthex/project.json`: `human` (where people look), `source` (the text in the repository) and `truth` (`source` or `human`, the side that wins when they differ). If there is no project file, use the `corthex` skill first.
2. **Inputs.** Read the inputs in the stage contract, with their trace IDs. Name any missing input and ask whether to go on without it.
3. **Outputs.** Write the outputs to `source` with the stage's trace IDs. Never reuse or renumber an ID; mark removed items as removed.
4. **Checks.** Run the stage's checks. Report what passed, what failed and what you could not check.
5. **Sync.** Bring the human view and the source into line in the direction `truth` gives. When `truth` is `human`, refresh the source from the human view and do not edit the source directly. If this session cannot reach the human view through an MCP server, a connector or an API, work from the latest export and follow "Human views the AI cannot reach" in the `corthex` skill's stage contract.
6. **Checkpoint.** Stop at the stage's human checkpoint and ask. Silence, a read receipt or an edit is not approval.
7. **Record.** Record decisions and the next action with `corthex-record`.

## Notes for these stages

- The product repository's own rules for branches, reviews and merges come first. CORTHEX only adds the trace IDs and the checks.
- A test plan comes from the user flows and the acceptance criteria, not from the code, so it can find what the code forgot.
