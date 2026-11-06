---
name: corthex-screen
description: CORTHEX stages 07 to 09, screens. Use when building or changing a sitemap (SCR IDs), writing screen definitions with their states (normal, loading, empty, error, permission and stale), or producing mockups and design tokens, including how many design candidates to make and when to fix one direction.
license: Apache-2.0
metadata:
  author: kodonghui
  version: "0.8.0"
---

# Screens

This skill covers three stages. Each stage's contract, steps, checks and output template are in its reference file. Read only the file for the stage at hand. How to work with Figma and Claude Design in stage 09 is in [references/design-tools.md](references/design-tools.md).

| Key | Stage | Contract |
| --- | --- | --- |
| `07-sitemap` | Sitemap | [references/07-sitemap.md](references/07-sitemap.md) |
| `08-screen-states` | Screen states | [references/08-screen-states.md](references/08-screen-states.md) |
| `09-mockup` | Mockup | [references/09-mockup.md](references/09-mockup.md) |

## How a stage runs

1. **Settings.** Read the stage's entry under `stages` in `.corthex/project.json`: `human` (where people look), `source` (the text in the repository) and `truth` (`source` or `human`, the side that wins when they differ). If there is no project file, use the `corthex` skill first. If the stage has no entry yet, propose the default human view that the stage's reference file names; when the user picks another, record the choice as a decision and write the entry with a `note`.
2. **Inputs.** Read the inputs in the stage contract, with their trace IDs. Name any missing input and ask whether to go on without it.
3. **Outputs.** Write the outputs to `source` with the stage's trace IDs. Never reuse or renumber an ID; mark removed items as removed.
4. **Checks.** Run the stage's checks. Report what passed, what failed and what you could not check.
5. **Sync.** Bring the human view and the source into line in the direction `truth` gives. When `truth` is `human`, refresh the source from the human view and do not edit the source directly. If this session cannot reach the human view through an MCP server, a connector or an API, work from a person's latest export: ask for a new export at the start and before each checkpoint, and give the date of the copy you used. With `truth: human`, hand over each change as steps a person can apply in the tool or as a file the tool can import, and report it as proposed, not as done, until a newer export shows it. With `truth: source`, a change is done once it is in the source: give the person the file or the steps for the tool, and report the tool as not yet updated until a newer export shows the change.
6. **Checkpoint.** Stop at the stage's human checkpoint and ask. Silence, a read receipt or an edit is not approval.
7. **Record.** Record decisions and the next action with `corthex-record`. If the `corthex-hub` skill is installed, also record the stage's state there.

## Notes for these stages

- Write or update the screen definition before changing a screen's code.
- More candidates are not better by default. Many generated designs make choosing slow and expensive, so the mockup stage starts with two candidates per screen and fixes one direction early.
- A passing design check is not a screen review. Say which widths and states you actually looked at.
- For the craft inside a screen, use the `corthex-uxui` skill: names and numbers for parts, spacing, type and motion, and the checks on a real render (line breaks, including Korean, contrast and target size). The project's tokens and screen definitions win over its numbers.

## Optional NEXUS work

For a project with an installed hub and an authorized NEXUS server, follow [references/nexus-work.md](references/nexus-work.md). Read the to-do once per session/project, keep explicit user work first, and use claims and verified PR/checkpoint outcomes. Continue local work when the hub or token is unavailable.
