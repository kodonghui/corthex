---
name: corthex-screen
description: CORTHEX stages 07 to 09, screens. Use when building or changing a sitemap (SCR IDs), writing screen definitions with their states (normal, loading, empty, error, permission and stale), or producing mockups and design tokens, including how many design candidates to make and when to fix one direction.
license: Apache-2.0
metadata:
  author: kodonghui
  version: "0.1.0"
---

# Screens

This skill covers three stages. Each stage's contract, steps, checks and output template are in its reference file. Read only the file for the stage at hand.

| Key | Stage | Contract |
| --- | --- | --- |
| `07-sitemap` | Sitemap | [references/07-sitemap.md](references/07-sitemap.md) |
| `08-screen-states` | Screen states | [references/08-screen-states.md](references/08-screen-states.md) |
| `09-mockup` | Mockup | [references/09-mockup.md](references/09-mockup.md) |

## How a stage runs

1. **Settings.** Read the stage's entry under `stages` in `.corthex/project.json`: `human` (where people look), `source` (the text in the repository) and `truth` (`source` or `human`, the side that wins when they differ). If there is no project file, use the `corthex` skill first.
2. **Inputs.** Read the inputs in the stage contract, with their trace IDs. Name any missing input and ask whether to go on without it.
3. **Outputs.** Write the outputs to `source` with the stage's trace IDs. Never reuse or renumber an ID; mark removed items as removed.
4. **Checks.** Run the stage's checks. Report what passed, what failed and what you could not check.
5. **Sync.** Bring the human view and the source into line in the direction `truth` gives. When `truth` is `human`, refresh the source from the human view and do not edit the source directly. If this session cannot reach the human view through an MCP server, a connector or an API, work from a person's latest export. Ask for a new export at the start and before each checkpoint, and give the date of the copy you used. Hand over each change as steps a person can apply in the tool or as a file the tool can import, and report it as proposed, not done, until a newer export shows it.
6. **Checkpoint.** Stop at the stage's human checkpoint and ask. Silence, a read receipt or an edit is not approval.
7. **Record.** Record decisions and the next action with `corthex-record`.

## Notes for these stages

- Write or update the screen definition before changing a screen's code.
- More candidates are not better by default. Many generated designs make choosing slow and expensive, so the mockup stage starts with two candidates per screen and fixes one direction early.
- A passing design check is not a screen review. Say which widths and states you actually looked at.
