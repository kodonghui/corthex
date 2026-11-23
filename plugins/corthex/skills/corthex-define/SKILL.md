---
name: corthex-define
description: CORTHEX stages 02 to 04, defining the product. Use when writing or reviewing a PRD or requirements (EARS wording, REQ IDs), user flows or a user flow map (Mermaid, FL IDs), or a functional specification (SPEC rows with exceptions and acceptance criteria), and when checking requirements and specs for gaps, duplicates and contradictions. Also use when a feature change adds, defers, removes or changes approved requirements, flows or spec rows.
license: Apache-2.0
metadata:
  author: kodonghui
  version: "0.17.0"
---

# Defining the product

This skill covers three stages. Each stage's contract, steps, checks and output template are in its reference file. Read only the file for the stage at hand. How to connect a Notion database, sync it with the source and work through its comments is in [references/notion-database.md](references/notion-database.md).

| Key | Stage | Contract |
| --- | --- | --- |
| `02-prd` | PRD | [references/02-prd.md](references/02-prd.md) |
| `03-user-flow` | User flow | [references/03-user-flow.md](references/03-user-flow.md) |
| `04-functional-spec` | Functional spec | [references/04-functional-spec.md](references/04-functional-spec.md) |

## How a stage runs

1. **Settings.** Read the stage's entry under `stages` in `.corthex/project.json`: `human` (where people look), `source` (the text in the repository) and `truth` (`source` or `human`, the side that wins when they differ). If there is no project file, use the `corthex` skill first. If the stage has no entry yet, propose the default human view that the stage's reference file names; when the user picks another, record the choice as a decision and write the entry with a `note`. On a project on NEXUS, NEXUS shows the stage whatever `human` names: give the stage's NEXUS address whenever you show its work ([references/nexus-work.md](references/nexus-work.md)).
2. **Inputs.** Read the inputs in the stage contract, with their trace IDs. Name any missing input and ask whether to go on without it.
3. **Outputs.** Write the outputs to `source` with the stage's trace IDs. Never reuse or renumber an ID; mark removed items as removed.
4. **Checks.** Run the stage's checks. Report what passed, what failed and what you could not check.
5. **Sync.** Bring the human view and the source into line in the direction `truth` gives. When `truth` is `human`, refresh the source from the human view and do not edit the source directly. If this session cannot reach the human view through an MCP server, a connector or an API, work from a person's latest export: ask for a new export at the start and before each checkpoint, and give the date of the copy you used. With `truth: human`, hand over each change as steps a person can apply in the tool or as a file the tool can import, and report it as proposed, not as done, until a newer export shows it. With `truth: source`, a change is done once it is in the source: give the person the file or the steps for the tool, and report the tool as not yet updated until a newer export shows the change.
6. **Checkpoint.** Stop at the stage's human checkpoint and ask. Before the checkpoint's question, list what the work drops or changes from earlier approvals: this stage's items removed, deferred or changed in meaning since its last passed checkpoint, and approved items of earlier stages that it should carry and does not, such as a requirement no spec row covers, each with its ID, its approved text and the reason; or say there are none. Ask about each listed item that has no answer yet as a question of its own: passing the stage answers none of them, and an item without its own answer stays as approved. Record the commit or export the checkpoint approves, so that the next checkpoint can compare with it. Silence, a read receipt or an edit is not approval. On a project on NEXUS, merge the stage's draft of documents and push it first, then ask with the stage's NEXUS address, as the NEXUS work says.
7. **Record.** Record decisions and the next action with `corthex-record`. If the `corthex-hub` skill is installed, also record the stage's state there.

## Notes for these stages

- The three stages feed each other: each flow step names the requirements it serves, and each spec row names its requirements and flows. A requirement no flow or spec row uses is a gap to report.
- By default people review these stages in Notion databases. In a team project the database is often the truth: then `truth` is `human` and the repository holds a refreshed, read-only copy that later stages read.

## Changing approved requirements

Once a checkpoint of these stages has been passed, a new feature, a feature removed or put off, or any other change of scope goes by the `corthex` skill's change procedure. It starts again at stage 01 and goes through every stage in order, writing each stage's difference from its approved version, or "no change" with the reason; no stage is skipped and the new design never starts at a later stage. In these stages that means:

- Each requirement, flow or spec row the change removes, defers or changes in meaning is listed with its ID, its approved text quoted and the reason, and asked about on its own. Approving the new design answers none of them, and one without its own answer stays as approved.
- A deferred item keeps its ID with the status `deferred`, the decision, the date to look at it again and its owner. A removed item keeps its ID with the status `removed`, the date and the decision.
- A bug whose fix needs a new or different requirement or flow is such a change.

## Work in NEXUS

On a project on the user's NEXUS server, NEXUS is where the user reads every stage, talks about its items and passes its checkpoints: follow [references/nexus-work.md](references/nexus-work.md). When the profile names a NEXUS server and neither the project's settings nor the push list say whether the project is on it, ask once to put it there. At a session's start ask the hub whether the session can send, and say once, in one line, what is missing for a project that is expected on a NEXUS server. Read the to-do at the start, again where a unit of stage work starts or ends once a day has passed, and before each checkpoint request; keep explicit user work first, and use claims and verified PR/checkpoint outcomes. Merge a stage's draft of documents and push it before its checkpoint request, and give the stage's NEXUS address whenever you show its work. Continue local work when the hub or token is unavailable. For a project that is expected on a NEXUS server, its rules for a checkpoint request, for telling the user where the work stands and for a browser walk of NEXUS pages hold in every session, also in one without the hub.
