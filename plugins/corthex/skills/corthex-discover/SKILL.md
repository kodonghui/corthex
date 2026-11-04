---
name: corthex-discover
description: CORTHEX stage 01, domain discovery. Use when the user runs or summarizes event storming or a domain workshop, alone or with a team, on a board such as Miro; wants bounded contexts, domain events, commands, aggregates, policies, read models, actors or a context map written down; or needs a shared glossary before requirements are written. Produces a domain design document with CTX and TERM IDs that later stages trace back to.
license: Apache-2.0
metadata:
  author: kodonghui
  version: "0.7.0"
---

# Domain discovery

This skill covers one stage. Its contract, ways of working, steps, checks and output template are in the reference file. The board's legend, layout and tools are in [references/event-storming-board.md](references/event-storming-board.md), and interviews with people are in [references/interviews.md](references/interviews.md).

| Key | Stage | Contract |
| --- | --- | --- |
| `01-domain` | Domain discovery | [references/01-domain.md](references/01-domain.md) |

## How a stage runs

1. **Settings.** Read the stage's entry under `stages` in `.corthex/project.json`: `human` (where people look), `source` (the text in the repository) and `truth` (`source` or `human`, the side that wins when they differ). If there is no project file, use the `corthex` skill first. If the stage has no entry yet, propose the default human view that the stage's reference file names; when the user picks another, record the choice as a decision and write the entry with a `note`.
2. **Inputs.** Read the inputs in the stage contract, with their trace IDs. Name any missing input and ask whether to go on without it.
3. **Outputs.** Write the outputs to `source` with the stage's trace IDs. Never reuse or renumber an ID; mark removed items as removed.
4. **Checks.** Run the stage's checks. Report what passed, what failed and what you could not check.
5. **Sync.** Bring the human view and the source into line in the direction `truth` gives. When `truth` is `human`, refresh the source from the human view and do not edit the source directly. If this session cannot reach the human view through an MCP server, a connector or an API, work from a person's latest export: ask for a new export at the start and before each checkpoint, and give the date of the copy you used. With `truth: human`, hand over each change as steps a person can apply in the tool or as a file the tool can import, and report it as proposed, not as done, until a newer export shows it. With `truth: source`, a change is done once it is in the source: give the person the file or the steps for the tool, and report the tool as not yet updated until a newer export shows the change.
6. **Checkpoint.** Stop at the stage's human checkpoint and ask. Silence, a read receipt or an edit is not approval.
7. **Record.** Record decisions and the next action with `corthex-record`. If the `corthex-hub` skill is installed, also record the stage's state there.

## Notes for this stage

- Start from the user's purpose in their own words, not from what is already built. Existing code and documents are material for the steps, not the goal.
- Run the steps in order, one frame per step, and stop where the chosen way of working says. By default the AI drafts each step on the board, people correct it there, and the AI stops after steps 1-b, 7 and 9.
- A board is a picture of a conversation. Turn it into text, but keep its hotspots as questions, not as decisions.
- Label the AI's confidence and keep checkpoint notes to the three bundles in the reference: guesses, two or three questions and, at checkpoints 2 and 3, core aggregate rules. Record the human participation.
- Set the detail by context type; core contexts keep rule sources and Given–When–Then examples. For an addition to an existing product, use the changed-context procedure in the reference.
- Use the glossary's words in every later stage. When a later stage needs a new term, add it here first.

## Optional NEXUS work

For a project with an installed hub and an authorized NEXUS server, follow [references/nexus-work.md](references/nexus-work.md). Read the to-do once per session/project, keep explicit user work first, and use claims and verified PR/checkpoint outcomes. Continue local work when the hub or token is unavailable.
