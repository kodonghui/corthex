---
name: corthex-define
description: CORTHEX stages 02 to 04, defining the product. Use when writing or reviewing a PRD or requirements (EARS wording, REQ IDs), user flows or a user flow map (Mermaid, FL IDs), or a functional specification (SPEC rows with exceptions and acceptance criteria), and when checking requirements and specs for gaps, duplicates and contradictions.
license: Apache-2.0
metadata:
  author: kodonghui
  version: "0.1.0"
---

# Defining the product

This skill covers three stages. Each stage's contract, steps, checks and output template are in its reference file. Read only the file for the stage at hand.

| Key | Stage | Contract |
| --- | --- | --- |
| `02-prd` | PRD | [references/02-prd.md](references/02-prd.md) |
| `03-user-flow` | User flow | [references/03-user-flow.md](references/03-user-flow.md) |
| `04-functional-spec` | Functional spec | [references/04-functional-spec.md](references/04-functional-spec.md) |

## How a stage runs

1. **Settings.** Read the stage's entry under `stages` in `.corthex/project.json`: `human` (where people look), `source` (the text in the repository) and `truth` (`source` or `human`, the side that wins when they differ). If there is no project file, use the `corthex` skill first.
2. **Inputs.** Read the inputs in the stage contract, with their trace IDs. Name any missing input and ask whether to go on without it.
3. **Outputs.** Write the outputs to `source` with the stage's trace IDs. Never reuse or renumber an ID; mark removed items as removed.
4. **Checks.** Run the stage's checks. Report what passed, what failed and what you could not check.
5. **Sync.** Bring the human view and the source into line in the direction `truth` gives. When `truth` is `human`, refresh the source from the human view and do not edit the source directly.
6. **Checkpoint.** Stop at the stage's human checkpoint and ask. Silence, a read receipt or an edit is not approval.
7. **Record.** Record decisions and the next action with `corthex-record`. If the `corthex-hub` skill is installed, also record the stage's state there.

## Notes for these stages

- The three stages feed each other: each flow step names the requirements it serves, and each spec row names its requirements and flows. A requirement no flow or spec row uses is a gap to report.
- In a team project the functional spec is often kept in a shared database. Then `truth` is `human` and the repository holds a refreshed, read-only copy.
