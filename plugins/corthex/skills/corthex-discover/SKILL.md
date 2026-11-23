---
name: corthex-discover
description: CORTHEX stage 01, domain discovery. Use when the user runs or summarizes event storming or a domain workshop, alone or with a team, on a board such as Miro, or reviews the domain's DDD board in NEXUS; wants bounded contexts, domain events, commands, aggregates, policies, read models, actors or a context map written down; or needs a shared glossary before requirements are written. Produces a domain design document with CTX and TERM IDs that later stages trace back to.
license: Apache-2.0
metadata:
  author: kodonghui
  version: "0.17.0"
---

# Domain discovery

This skill covers one stage. Its contract, ways of working, steps, checks and output template are in the reference file. The board's legend, layout and tools are in [references/event-storming-board.md](references/event-storming-board.md), and interviews with people are in [references/interviews.md](references/interviews.md).

| Key | Stage | Contract |
| --- | --- | --- |
| `01-domain` | Domain discovery | [references/01-domain.md](references/01-domain.md) |

## How a stage runs

1. **Settings.** Read the stage's entry under `stages` in `.corthex/project.json`: `human` (where people look), `source` (the text in the repository) and `truth` (`source` or `human`, the side that wins when they differ). If there is no project file, use the `corthex` skill first. If the stage has no entry yet, propose the default human view that the stage's reference file names; when the user picks another, record the choice as a decision and write the entry with a `note`. On a project on NEXUS, NEXUS shows the stage whatever `human` names: give the stage's NEXUS address whenever you show its work ([references/nexus-work.md](references/nexus-work.md)).
2. **Inputs.** Read the inputs in the stage contract, with their trace IDs. Name any missing input and ask whether to go on without it.
3. **Outputs.** Write the outputs to `source` with the stage's trace IDs. Never reuse or renumber an ID; mark removed items as removed.
4. **Checks.** Run the stage's checks. Report what passed, what failed and what you could not check.
5. **Sync.** Bring the human view and the source into line in the direction `truth` gives. When `truth` is `human`, refresh the source from the human view and do not edit the source directly. If this session cannot reach the human view through an MCP server, a connector or an API, work from a person's latest export: ask for a new export at the start and before each checkpoint, and give the date of the copy you used. With `truth: human`, hand over each change as steps a person can apply in the tool or as a file the tool can import, and report it as proposed, not as done, until a newer export shows it. With `truth: source`, a change is done once it is in the source: give the person the file or the steps for the tool, and report the tool as not yet updated until a newer export shows the change.
6. **Checkpoint.** Stop at the stage's human checkpoint and ask. Before the checkpoint's question, list what the work drops or changes from earlier approvals: this stage's items removed, deferred or changed in meaning since its last passed checkpoint, and approved items of earlier stages that it should carry and does not, such as a requirement no spec row covers, each with its ID, its approved text and the reason; or say there are none. Ask about each listed item that has no answer yet as a question of its own: passing the stage answers none of them, and an item without its own answer stays as approved. Record the commit or export the checkpoint approves, so that the next checkpoint can compare with it. Silence, a read receipt or an edit is not approval. On a project on NEXUS, merge the stage's draft of documents and push it first, then ask with the stage's NEXUS address, as the NEXUS work says.
7. **Record.** Record decisions and the next action with `corthex-record`. If the `corthex-hub` skill is installed, also record the stage's state there.

## Notes for this stage

- Start from the user's purpose in their own words, not from what is already built. Existing code and documents are material for the steps, not the goal.
- Run the steps in order, one frame per step, and stop where the chosen way of working says. By default the AI drafts each step on the board, people correct it there, and the AI stops after steps 1-b, 7 and 9.
- The steps run on a Miro board, also on a project on NEXUS: NEXUS draws a DDD board only once the contexts have their IDs, and it cannot be edited yet. Check before step 0 that the session has Miro's tools. Once the contexts have IDs, NEXUS draws the board step by step from the domain source, and checkpoint 3 and every later review happen there ([references/event-storming-board.md](references/event-storming-board.md)).
- A board is a picture of a conversation. Turn it into text, but keep its hotspots as questions, not as decisions.
- Label the AI's confidence and keep checkpoint notes to the three bundles in the reference: guesses, two or three questions and, at checkpoints 2 and 3, core aggregate rules. Record the human participation.
- Set the detail by context type; core contexts keep rule sources and Given–When–Then examples. For an addition to an existing product, use the changed-context procedure in the reference.
- Use the glossary's words in every later stage. When a later stage needs a new term, add it here first. Each term is the field's standard term; when one turns out to be a coined word, correct it here under its TERM ID instead of carrying it into later stages.

## Work in NEXUS

On a project on the user's NEXUS server, NEXUS is where the user reads every stage, talks about its items and passes its checkpoints: follow [references/nexus-work.md](references/nexus-work.md). When the profile names a NEXUS server and neither the project's settings nor the push list say whether the project is on it, ask once to put it there. At a session's start ask the hub whether the session can send, and say once, in one line, what is missing for a project that is expected on a NEXUS server. Read the to-do at the start, again where a unit of stage work starts or ends once a day has passed, and before each checkpoint request; keep explicit user work first, and use claims and verified PR/checkpoint outcomes. Merge a stage's draft of documents and push it before its checkpoint request, and give the stage's NEXUS address whenever you show its work. Continue local work when the hub or token is unavailable. For a project that is expected on a NEXUS server, its rules for a checkpoint request, for telling the user where the work stands and for a browser walk of NEXUS pages hold in every session, also in one without the hub.
