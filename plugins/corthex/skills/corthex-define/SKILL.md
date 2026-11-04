---
name: corthex-define
description: CORTHEX stages 02 to 04, defining the product. Use when writing or reviewing a PRD or requirements (EARS wording, REQ IDs), user flows or a user flow map (Mermaid, FL IDs), or a functional specification (SPEC rows with exceptions and acceptance criteria), and when checking requirements and specs for gaps, duplicates and contradictions.
license: Apache-2.0
metadata:
  author: kodonghui
  version: "0.6.0"
---

# Defining the product

This skill covers three stages. Each stage's contract, steps, checks and output template are in its reference file. Read only the file for the stage at hand. How to connect a Notion database, sync it with the source and work through its comments is in [references/notion-database.md](references/notion-database.md).

| Key | Stage | Contract |
| --- | --- | --- |
| `02-prd` | PRD | [references/02-prd.md](references/02-prd.md) |
| `03-user-flow` | User flow | [references/03-user-flow.md](references/03-user-flow.md) |
| `04-functional-spec` | Functional spec | [references/04-functional-spec.md](references/04-functional-spec.md) |

## How a stage runs

1. **Settings.** Read the stage's entry under `stages` in `.corthex/project.json`: `human` (where people look), `source` (the text in the repository) and `truth` (`source` or `human`, the side that wins when they differ). If there is no project file, use the `corthex` skill first. If the stage has no entry yet, propose the default human view that the stage's reference file names; when the user picks another, record the choice as a decision and write the entry with a `note`.
2. **Inputs.** Read the inputs in the stage contract, with their trace IDs. Name any missing input and ask whether to go on without it.
3. **Outputs.** Write the outputs to `source` with the stage's trace IDs. Never reuse or renumber an ID; mark removed items as removed.
4. **Checks.** Run the stage's checks. Report what passed, what failed and what you could not check.
5. **Sync.** Bring the human view and the source into line in the direction `truth` gives. When `truth` is `human`, refresh the source from the human view and do not edit the source directly. If this session cannot reach the human view through an MCP server, a connector or an API, work from a person's latest export: ask for a new export at the start and before each checkpoint, and give the date of the copy you used. With `truth: human`, hand over each change as steps a person can apply in the tool or as a file the tool can import, and report it as proposed, not as done, until a newer export shows it. With `truth: source`, a change is done once it is in the source: give the person the file or the steps for the tool, and report the tool as not yet updated until a newer export shows the change.
6. **Checkpoint.** Stop at the stage's human checkpoint and ask. Silence, a read receipt or an edit is not approval.
7. **Record.** Record decisions and the next action with `corthex-record`. If the `corthex-hub` skill is installed, also record the stage's state there.

## Notes for these stages

- The three stages feed each other: each flow step names the requirements it serves, and each spec row names its requirements and flows. A requirement no flow or spec row uses is a gap to report.
- By default people review these stages in Notion databases. In a team project the database is often the truth: then `truth` is `human` and the repository holds a refreshed, read-only copy that later stages read.
