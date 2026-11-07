---
name: corthex-build
description: CORTHEX stages 10 to 12, building and testing. Use when breaking the spec into work items (WBS, TASK IDs), planning or reviewing development work and pull requests that should trace to tasks and specs, writing a QA test plan, API tests, end-to-end tests and bug reports (TC and BUG IDs), or preparing a requested learning guide or task HOWTO from the user flows and acceptance criteria. Also use for every QA run, which adds to the project's own tests browser agents that drive ego lite or Aside through the user flows and report what works, what does not and their impressions.
license: Apache-2.0
metadata:
  author: kodonghui
  version: "0.9.0"
---

# Building and testing

This skill covers three stages. Each stage's contract, steps, checks and output template are in its reference file. Read only the file for the stage at hand. How to keep the tasks on GitHub Projects or in a Notion database is in [references/task-board.md](references/task-board.md), and how browser agents walk the flows in ego lite or Aside on every QA run is in [references/browser-agents.md](references/browser-agents.md).

| Key | Stage | Contract |
| --- | --- | --- |
| `10-wbs` | WBS | [references/10-wbs.md](references/10-wbs.md) |
| `11-development` | Development | [references/11-development.md](references/11-development.md) |
| `12-qa` | QA | [references/12-qa.md](references/12-qa.md) |

## How a stage runs

1. **Settings.** Read the stage's entry under `stages` in `.corthex/project.json`: `human` (where people look), `source` (the text in the repository) and `truth` (`source` or `human`, the side that wins when they differ). If there is no project file, use the `corthex` skill first. If the stage has no entry yet, propose the default human view that the stage's reference file names; when the user picks another, record the choice as a decision and write the entry with a `note`.
2. **Inputs.** Read the inputs in the stage contract, with their trace IDs. Name any missing input and ask whether to go on without it.
3. **Outputs.** Write the outputs to `source` with the stage's trace IDs. Never reuse or renumber an ID; mark removed items as removed.
4. **Checks.** Run the stage's checks. Report what passed, what failed and what you could not check.
5. **Sync.** Bring the human view and the source into line in the direction `truth` gives. When `truth` is `human`, refresh the source from the human view and do not edit the source directly. If this session cannot reach the human view through an MCP server, a connector or an API, work from a person's latest export: ask for a new export at the start and before each checkpoint, and give the date of the copy you used. With `truth: human`, hand over each change as steps a person can apply in the tool or as a file the tool can import, and report it as proposed, not as done, until a newer export shows it. With `truth: source`, a change is done once it is in the source: give the person the file or the steps for the tool, and report the tool as not yet updated until a newer export shows the change.
6. **Checkpoint.** Stop at the stage's human checkpoint and ask. Silence, a read receipt or an edit is not approval.
7. **Record.** Record decisions and the next action with `corthex-record`. If the `corthex-hub` skill is installed, also record the stage's state there.

## Notes for these stages

- For a requested guide, read [references/howto.md](references/howto.md). For async AI server implementation, the worked product example is in [references/fastapi-example.md](references/fastapi-example.md).
- The product repository's own rules for branches, reviews and merges come first. CORTHEX only adds the trace IDs and the checks.
- A test plan comes from the user flows and the acceptance criteria, not from the code, so it can find what the code forgot.

## Optional NEXUS work

For a project with an installed hub and an authorized NEXUS server, follow [references/nexus-work.md](references/nexus-work.md). Read the to-do once per session/project, keep explicit user work first, and use claims and verified PR/checkpoint outcomes. Continue local work when the hub or token is unavailable.
