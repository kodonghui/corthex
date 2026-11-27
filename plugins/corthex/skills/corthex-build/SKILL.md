---
name: corthex-build
description: CORTHEX stages 10 to 12, building and testing. Use when breaking the spec into tasks (WBS, TASK IDs), planning or reviewing development work and pull requests, writing QA plans, API tests, end-to-end tests and bug files (TC and BUG IDs), fixing a bug with a failing regression test or handling a production incident, or preparing a requested learning guide or task HOWTO. Use for every QA run with browser, desktop and device walks, for the release gate and after-release checks, and for a verification runbook.
license: Apache-2.0
metadata:
  author: kodonghui
  version: "0.18.0"
---

# Building and testing

This skill covers three stages. Each stage's contract, steps, checks and output template are in its reference file. Read only the file for the stage at hand. How to keep the tasks on GitHub Projects or in a Notion database is in [references/task-board.md](references/task-board.md).

| Key | Stage | Contract |
| --- | --- | --- |
| `10-wbs` | WBS | [references/10-wbs.md](references/10-wbs.md) |
| `11-development` | Development | [references/11-development.md](references/11-development.md) |
| `12-qa` | QA | [references/12-qa.md](references/12-qa.md) |

## How a stage runs

1. **Settings.** Read the stage's entry under `stages` in `.corthex/project.json`: `human` (where people look), `source` (the text in the repository) and `truth` (`source` or `human`, the side that wins when they differ). If there is no project file, use the `corthex` skill first. If the stage has no entry yet, propose the default human view that the stage's reference file names; when the user picks another, record the choice as a decision and write the entry with a `note`. On a project on NEXUS, NEXUS shows the stage whatever `human` names: give the stage's NEXUS address whenever you show its work ([references/nexus-work.md](references/nexus-work.md)).
2. **Inputs.** Read the inputs in the stage contract, with their trace IDs. Name any missing input and ask whether to go on without it.
3. **Outputs.** Write the outputs to `source` with the stage's trace IDs. Never reuse or renumber an ID; mark removed items as removed.
4. **Checks.** Run the stage's checks. Report what passed, what failed and what you could not check.
5. **Sync.** Bring the human view and the source into line in the direction `truth` gives. When `truth` is `human`, refresh the source from the human view and do not edit the source directly. If this session cannot reach the human view through an MCP server, a connector or an API, work from a person's latest export: ask for a new export at the start and before each checkpoint, and give the date of the copy you used. With `truth: human`, hand over each change as steps a person can apply in the tool or as a file the tool can import, and report it as proposed, not as done, until a newer export shows it. With `truth: source`, a change is done once it is in the source: give the person the file or the steps for the tool, and report the tool as not yet updated until a newer export shows the change.
6. **Checkpoint.** Stop at the stage's human checkpoint and ask its owner: the user, or the delegate that their `checkpoints` setting names for the stage (the `corthex` skill's stage contract). Before the checkpoint's question, list what the work drops or changes from earlier approvals: this stage's items removed, deferred or changed in meaning since its last passed checkpoint, and approved items of earlier stages that it should carry and does not, such as a requirement no spec row covers, each with its ID, its approved text and the reason; or say there are none. Ask about each listed item that has no answer yet as a question of its own: passing the stage answers none of them, and an item without its own answer stays as approved. Record the commit or export the checkpoint approves, so that the next checkpoint can compare with it. Silence, a read receipt or an edit is not approval. On a project on NEXUS, merge the stage's draft of documents and push it first, then ask with the stage's NEXUS address, as the NEXUS work says.
7. **Record.** Record decisions and the next action with `corthex-record`. If the `corthex-hub` skill is installed, also record the stage's state there.

## Notes for these stages

- For a requested guide, read [references/howto.md](references/howto.md). For async AI server implementation, the worked product example is in [references/fastapi-example.md](references/fastapi-example.md).
- The product repository's own rules for branches, reviews and merges come first. CORTHEX only adds the trace IDs and the checks.
- A test plan comes from the user flows and the acceptance criteria, not from the code, so it can find what the code forgot.
- QA starts and cleans up the product by its [verification runbook](references/verify-runbook.md).
- On every QA run, walk the screens using [browser and desktop agents](references/browser-agents.md) or [device agents](references/device-agents.md). Apply the [release gate](references/12-qa.md#release-gate) before go/no-go and record the [after-release check](references/12-qa.md#after-release).
- Work found while building that adds, removes, defers or changes an approved requirement, flow or spec row is a feature change: follow the `corthex` skill's change procedure from stage 01, never fold it into the current tasks.

## Fixing a bug

Fix every bug by [references/bug-fix.md](references/bug-fix.md), whichever stage finds it: record it, reproduce it, fix the document of the stage with its cause first, then the code behind a regression test that failed before the fix. A fix that needs a new or different requirement or flow is a feature change instead.

## Work in NEXUS

On a project on the user's NEXUS server, NEXUS is where the user reads every stage, talks about its items and passes its checkpoints: follow [references/nexus-work.md](references/nexus-work.md). When the profile names a NEXUS server and neither the project's settings nor the push list say whether the project is on it, ask once to put it there. At a session's start ask the hub whether the session can send, and say once, in one line, what is missing for a project that is expected on a NEXUS server. Read the to-do at the start, again where a unit of stage work starts or ends once a day has passed, and before each checkpoint request; keep explicit user work first, and use claims and verified PR/checkpoint outcomes. Merge a stage's draft of documents and push it before its checkpoint request, and give the stage's NEXUS address whenever you show its work. Continue local work when the hub or token is unavailable. For a project that is expected on a NEXUS server, its rules for a checkpoint request, for telling the user where the work stands and for a browser walk of NEXUS pages hold in every session, also in one without the hub.
