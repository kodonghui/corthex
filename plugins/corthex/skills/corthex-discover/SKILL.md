---
name: corthex-discover
description: CORTHEX stage 01, domain discovery. Use when the user runs or summarizes an event storming or domain workshop, wants bounded contexts, domain events, commands, policies and actors written down, or needs a shared glossary before requirements are written. Produces contexts and a glossary with CTX and TERM IDs that later stages trace back to.
license: Apache-2.0
metadata:
  author: kodonghui
  version: "0.1.0"
---

# Domain discovery

This skill covers one stage. Its contract, steps, checks and output template are in the reference file.

| Key | Stage | Contract |
| --- | --- | --- |
| `01-domain` | Domain discovery | [references/01-domain.md](references/01-domain.md) |

## How a stage runs

1. **Settings.** Read the stage's entry under `stages` in `.corthex/project.json`: `human` (where people look), `source` (the text in the repository) and `truth` (`source` or `human`, the side that wins when they differ). If there is no project file, use the `corthex` skill first.
2. **Inputs.** Read the inputs in the stage contract, with their trace IDs. Name any missing input and ask whether to go on without it.
3. **Outputs.** Write the outputs to `source` with the stage's trace IDs. Never reuse or renumber an ID; mark removed items as removed.
4. **Checks.** Run the stage's checks. Report what passed, what failed and what you could not check.
5. **Sync.** Bring the human view and the source into line in the direction `truth` gives. When `truth` is `human`, refresh the source from the human view and do not edit the source directly. If this session cannot reach the human view through an MCP server, a connector or an API, work from the latest export and follow "Human views the AI cannot reach" in the `corthex` skill's stage contract.
6. **Checkpoint.** Stop at the stage's human checkpoint and ask. Silence, a read receipt or an edit is not approval.
7. **Record.** Record decisions and the next action with `corthex-record`.

## Notes for this stage

- A workshop board is a picture of a conversation. Turn it into text, but keep the board's open questions as questions, not as decisions.
- Use the glossary's words in every later stage. When a later stage needs a new term, add it here first.
