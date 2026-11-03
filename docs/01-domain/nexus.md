---
synced_at: 2026-10-24T22:44+09:00
---

# NEXUS: domain

[한국어](nexus.ko.md)

Stage 01 of CORTHEX's own project, for NEXUS: the `corthex-nexus` plugin and the server in [`nexus/`](../../nexus/). Status: steps 0 to 9 done on an event storming board, checkpoints 1 to 3 passed on 2026-10-24. Stage 02's scope check answered hotspots 2, 4, 8 and 13 on 2026-10-25. At the joint checkpoint of NEXUS's stages 03 to 08 on 2026-11-03, the maintainer approved writing the read model of Edit picture in CTX-010 as Picture view, the name in the glossary, since the board's table of read models already says what the view shows on an edit conflict (stage 07's change 3). This version replaces the draft of the same day, which started from the hub built in phase 1; the board started again from the maintainer's own words about what NEXUS is for. When this file and its Korean translation differ, this file is the source.

This file holds the contexts and the glossary of NEXUS. Its IDs continue after those of CORTHEX-MEMORY in [memory.md](memory.md): contexts from CTX-006 and terms from TERM-047, the terms added with the board from TERM-109, after the ones that memory took up to TERM-108, and those added with the functional spec from TERM-124. Contexts and terms that went away keep their IDs and are marked as removed. The terms that memory.md already defines keep their meaning here, such as Agent, Session, Project settings and Project list; where NEXUS uses a word differently, its glossary row says how.

Sources read:

- The maintainer's words of 2026-10-24 about what NEXUS is for, kept word for word in Step 0 of the board, and the decision of the same day to build NEXUS in stages.
- The event storming board, Steps 0 to 9, read at the time in `synced_at`, with the maintainer's answers at the three checkpoints. The board is private; its link is in the project's records.
- The draft of this file (2026-10-24) and phase 1 as built: [`plugins/corthex-nexus/`](../../plugins/corthex-nexus/), [`nexus/`](../../nexus/) and [docs/architecture.md](../architecture.md#project-hub), deployed on the maintainer's own address on 2026-10-24.
- The decision of 2026-10-24 that NEXUS builds no ERD editor and that new projects use ERD Editor for stage 05.
- The memory domain in [memory.md](memory.md), for the shared terms.

## 1. Service overview

NEXUS is where the user and the AI discuss a project's pictures. In the maintainer's words, translated: "What I had in mind for NEXUS is a place where, for each project, the AI and I collaborate on what we need to discuss, in pictures such as DDD (like Miro), ERD and SiteMap. If possible, I can edit them too. And it would be even better to have things like Notion and Jira all managed on one platform."

Priorities, in the order and tone of those words:

1. Discuss with the AI over pictures: required.
2. Edit the pictures directly: if possible.
3. Manage records and work items, such as Notion pages and Jira issues, in the same place: better still.

What only NEXUS does, since NEXUS builds only what existing tools cannot do:

- It draws the pictures from the stage sources in Git, so the pictures always match them.
- It joins the DDD board, the ERD and the sitemap by ID and finds where they disagree, such as an ERD table with no matching aggregate.
- It keeps all the pictures of a project in one place.

Pictures that the AI drafts and people correct are not by themselves a reason to build: Miro does that, as the board of this stage shows.

- In scope: a space of pictures for each project; discussion and editing by the user and the AI; keeping the pictures and the stage sources equal; checks across pictures; later, links to Notion and Jira.
- Out of scope: building Notion or Jira again (NEXUS links to them); building a picture editor from scratch (NEXUS embeds an open-source one); memory (CORTHEX-MEMORY).

The plan, decided on 2026-10-24: NEXUS is built in stages, phase ① discussion over pictures, phase ② editing with an embedded open-source editor and phase ③ links to Notion and Jira. The hub of phase 1 stays as each project's home page. Stages 01 and 02 decide what to build; building comes after the memory plugin.

Answers at checkpoint 1, the AI's recommendations as approved:

| Question | Answer |
| --- | --- |
| Which pictures | The DDD board, the ERD and the sitemap first; user flows and others later |
| Who uses NEXUS | The user and the AI first; sharing with team members later |
| Where the pictures come from | The stage sources in Git; the AI reflects edited pictures in them |
| Where discussion happens | Both: the AI answers comments on picture items at its next work, and long talks happen in the conversation |
| Phone | Viewing on a phone too; editing on a PC first |
| Notion and Jira | Linked, not moved: a link and its state, with each tool staying the source |

What follows from these answers, in every context:

- NEXUS draws the pictures; the AI does not.
- The AI is an actor. It comes at its next work, reads what waits for it and answers; NEXUS never calls it.
- NEXUS never writes to Git. The AI reflects edits and decisions in the stage sources by pull request.
- Positions in a picture stay in NEXUS; only the content goes to the stage sources.

Actors and external systems:

- User: discusses, edits pictures on a PC, accepts or dismisses proposals and passes checkpoints. At first the maintainer alone.
- Agent (TERM-002), the AI on the board: comments, proposes, records decisions and reflects edits, at its next work in a session.
- Git repository (external): holds the stage sources. The agent writes decisions and stage states there.
- Session (TERM-003), the conversation on the board (external): where long talks happen; the agent writes down what was decided.
- Notion and Jira (external, phase ③): the sources of records and work items.

## 2. Event storming

- Board: private, with one frame per step; its link and the links of its frames are in the project's records.
- Frames: Step 0 (purpose and scope), 1-a (events), 1-b (timeline), one frame each for Steps 2 to 7, 8-a (policies and read models), 8-b (context map) and 9 (context tables).
- Way of working: draft and correct. The AI drafted each step from the maintainer's words; the maintainer answered at the checkpoints in the conversation and changed nothing on the board.
- Checkpoints, all passed on 2026-10-24 with the maintainer's approval of everything as drawn: 1, the purpose, the priorities, the six questions of Step 0, the 18 events and the five lanes; 2, the six contexts and the recommended answers to eight hotspots; 3, the five policies, the context map, the numbering and the 14 command rows.
- Material: the same board keeps, in a separate column, a first attempt that started from the hub of phase 1 instead of the maintainer's purpose. It stopped before step 8 and is not a source of this file.

The timeline, one lane per flow. The events are in order, and "or" joins outcomes of which only one happens, the usual one first.

| Lane | What happens | Events |
| --- | --- | --- |
| Drawing pictures | When a stage source appears or changes, NEXUS draws the pictures and checks them against each other | Project space created → Stage source changed → Picture drawn, or Picture redrawn → Discrepancy found |
| Discussing together | Over the pictures, the user and the AI exchange comments and proposals and decide; long talks happen in the conversation | Comment left → Proposal made → Proposal accepted, or Proposal dismissed → Decision recorded → Comment resolved |
| Editing directly | The user edits a picture on a PC, and the AI reflects it in the stage sources at its next work | Picture edited, or Edit conflict found → Edit reflected |
| Closing a stage | When the discrepancies are resolved and the user checks, the stage is done | Discrepancy resolved → Checkpoint passed |
| Linking tools (candidate, phase ③) | Notion records and Jira work items are linked to the pictures, which show only their state; each tool stays the source | Record linked → Work item linked |

Left out, because they only read and change no data: picture opened, zoom and pan, space browsed, signed in. Changed by the answers at checkpoint 1: NEXUS draws the pictures, not the AI; and "Work item created" became "Work item linked", since work items are created in Jira.

## 3. Bounded contexts and packages

Six contexts on the board, numbered at checkpoint 2: two continue the IDs of the draft (CTX-007 and CTX-010) and four are new (CTX-012 to CTX-015). The hub of phase 1 is kept as each project's home and was not redrawn. The package names of the new contexts are candidates, named here and not on the board.

| Context | Type | Aggregates | Package |
| --- | --- | --- | --- |
| CTX-012 Pictures | core | Project space, Picture | `pictures` |
| CTX-013 Cross-checking | core | Discrepancy | `crosscheck` |
| CTX-014 Discussion | supporting | Comment, Proposal | `discussion` |
| CTX-010 Editing | supporting; the editor is generic | Edit | `editing` |
| CTX-007 Stage progress | supporting | Stage record | `progress`; phase 1 built its recording part in `corthex-hub` |
| CTX-015 Tool links | generic, a candidate for phase ③ | Tool link | `toollinks` |
| CTX-006 Reading | built in phase 1 | not drawn | `corthex-hub` |
| CTX-008 Overview | built in phase 1 | not drawn | `corthex-hub` and the server in `nexus/` |
| CTX-009 Sharing | built in phase 1 | not drawn | `corthex-hub` and the server in `nexus/` |

Removed, with its ID kept:

| ID | Name | Status | Why |
| --- | --- | --- | --- |
| CTX-011 | Assistant access | removed | The agent comes to NEXUS at its next work instead of NEXUS reaching assistants in chat clients; Discussion and Stage progress share what it was for. Confirmed at checkpoint 3 |

## 4. Context tables

Five policies connect events to the commands they trigger. Three of them cross a boundary and appear in the dependencies.

| Policy | Crosses |
| --- | --- |
| When Project space created or Stage source changed, Draw picture | no |
| When Picture drawn, Cross-check pictures | from CTX-012 to CTX-013 |
| When Picture redrawn, Cross-check the open discrepancies again | from CTX-012 to CTX-013 |
| When Proposal accepted, Edit picture as proposed | from CTX-014 to CTX-010 |
| When Decision recorded, Close comment | no |

Three read models are what an actor looks at before a command. Stage progress (CTX-007) serves the agent to-do and the stage overview.

| Read model | Shows | Read before |
| --- | --- | --- |
| Picture view | A picture with its comments, proposals and discrepancies on it; on an edit conflict, the user's edit over the new picture | Leave comment, Accept proposal, Dismiss proposal, Edit picture |
| Agent to-do | Open comments and discrepancies, and the pending reflections: edited pictures and accepted proposals | Make proposal, Reflect in stage source |
| Stage overview | What is left in a stage: its open discrepancies, comments and pending reflections | Pass checkpoint |

The hub contexts, CTX-006, CTX-008 and CTX-009, come last: they are built and kept as each project's home, and the board did not redraw them.

### CTX-012 Pictures

Purpose: draw a project's pictures, the DDD board, the ERD and the sitemap, from its stage sources in Git.

| Given by | Read model | Command | Aggregate | Events |
| --- | --- | --- | --- | --- |
| User, Agent | | Create space | Project space | Project space created |
| Policy: when Project space created or Stage source changed | | Draw picture | Picture | Picture drawn, Picture redrawn |

- Aggregate rules: one project space for each project, bound to its repository. One picture for each document version, always equal to it; the stage sources are the truth of every picture.
- External systems: Git repository. The stage sources come through the hub of phase 1.
- Links: the hub sends the snapshot (event); tells Cross-checking that a picture was drawn or redrawn (event); Editing asks for the picture to edit and its document version (call).
- Hotspots: 1 repositories per space (answered); 2 how the stage sources reach NEXUS (answered in stage 02: the hub on a device pushes them); 3 positions (answered: they stay in NEXUS).

### CTX-013 Cross-checking

Purpose: pair the items of the pictures by ID to find discrepancies, and see whether they are resolved.

| Given by | Read model | Command | Aggregate | Events |
| --- | --- | --- | --- | --- |
| Policy: when Picture drawn or Picture redrawn (CTX-012) | | Cross-check pictures | Discrepancy | Discrepancy found, Discrepancy resolved |

- Aggregate rules: only one discrepancy is open for each pair; it is resolved when a new cross-check no longer finds it.
- External systems: none.
- Links: follows Picture drawn and Picture redrawn of Pictures (event); Stage progress asks for the open discrepancies (call).
- Hotspots: 4 pairs to compare (answered in stage 02: by glossary term).

### CTX-014 Discussion

Purpose: the user and the agent exchange comments and proposals over the pictures, and decide.

| Given by | Read model | Command | Aggregate | Events |
| --- | --- | --- | --- | --- |
| User, Agent | Picture view | Leave comment | Comment | Comment left |
| Agent, at its next work | Agent to-do | Make proposal | Proposal | Proposal made |
| User | Picture view | Accept proposal | Proposal | Proposal accepted |
| User | Picture view | Dismiss proposal | Proposal | Proposal dismissed |
| Agent, as the user says | | Record decision | Comment | Decision recorded |
| User, Agent; policy: when Decision recorded | | Close comment | Comment | Comment resolved |

- Aggregate rules: a comment is attached to an item's trace ID in a picture, not to a position, so it follows the item when the picture is redrawn; it closes when a decision is attached or it is answered. The agent makes a proposal, and only the user accepts or dismisses it; an accepted proposal waits to be reflected.
- External systems: Git repository, the stage sources that decisions go into; Session, for long talks, where the agent writes down what was decided.
- Links: tells Editing that a proposal was accepted (event); Stage progress asks for the open comments (call).
- Hotspots: 5 comments on a phone, 6 when the agent reads and 7 where decisions go (answered); 13 where the agent reads its to-do (answered in stage 02: through the hub).

### CTX-010 Editing

Purpose: the user edits pictures on a PC, and the agent reflects the edits in the stage sources at its next work. It was Structure editing, a candidate of the draft; the board brings it forward with an embedded open-source editor, which is generic.

| Given by | Read model | Command | Aggregate | Events |
| --- | --- | --- | --- | --- |
| User, on a PC; policy: when Proposal accepted (CTX-014) | Picture view | Edit picture | Edit | Picture edited, or Edit conflict found |
| Agent, at its next work | Agent to-do | Reflect in stage source | Edit | Edit reflected |

- Aggregate rules: an edit is bound to the document version that its picture was drawn from, and a newer version makes it a conflict. It closes once it is in the stage sources, and so does an accepted proposal.
- External systems: Git repository, where the agent opens a pull request. The open-source editor is embedded in NEXUS.
- Links: asks Pictures for the picture to edit and its document version (call); follows Proposal accepted of Discussion (event); Stage progress asks for the pending reflections (call).
- Hotspots: 8 which editor (answered in stage 02: Excalidraw and ERD Editor); 9 conflicts and 10 writing to Git (answered).

### CTX-007 Stage progress

Purpose: gather and show what is left in a stage, so that the user passes its checkpoint. It was Progress, whose recording part phase 1 built.

| Given by | Read model | Command | Aggregate | Events |
| --- | --- | --- | --- | --- |
| User only | Stage overview | Pass checkpoint | Stage record | Checkpoint passed |

- Aggregate rules: only the user passes a checkpoint.
- Read models it serves: the stage overview, for the user, and the agent to-do, for the agent.
- External systems: Git repository, where the agent writes the stage state.
- Links: asks Cross-checking, Discussion and Editing what is left (three calls).
- Hotspots: 11 what remains (answered: it is shown together, and the user decides).
- Built in phase 1: `hub.py status` records a stage's state, its last checkpoint, its next action and review findings, in a status file on each device and outside every repository. A stage's state comes only from what was recorded, never from the files that exist; `done` needs a checkpoint and its date, and an AI recommendation, a read receipt or an edit time is not a checkpoint. On the board the agent writes the stage state to the Git repository; stage 02 decided that the stage records move into the project's repository, and that the hub reads a status file only while a project has none (D12).

### CTX-015 Tool links

Purpose: link Notion records and Jira work items to the items in the pictures, and show only their state. A candidate for phase ③.

| Given by | Read model | Command | Aggregate | Events |
| --- | --- | --- | --- | --- |
| User, Agent | | Link record | Tool link | Record linked |
| User, Agent | | Link work item | Tool link | Work item linked |

- Aggregate rules: a link and a state only; each tool stays the source.
- External systems: Notion, the source of records; Jira, the source of work items.
- Links: asks Notion and Jira for the state (calls).
- Hotspots: 12 reading their state (open, decided when the links are built).

### CTX-006 Reading

Purpose: turn the stage sources of each registered project into a snapshot of its trace items, their links and the checks, without changing anything. Built in phase 1; on the board, the hub reads the stage sources from Git and gives the snapshot to Pictures.

- Events: Snapshot built, Stage read, Stage not read, Files skipped, Check raised, Project refused, Snapshot cut
- Commands: Build snapshot
- Policies: Read only the projects in the project list, each only under its registered name. Read text only: never run a project's code, Git hooks or Git filters, and never write to a repository. An ID is defined only in the stage that creates its kind; anywhere else it is a mention. Skip files that look like secrets, and translations that define only their original's IDs. Keep file contents and local paths out of the snapshot, and redact secrets and email addresses. A check finds structure, not meaning: it is a lead, not a verdict. Never renumber an ID to clear a check.
- Actors: User, Agent, Hub
- Open questions: How the snapshot reaches Pictures was hotspot 2, which stage 02 answered (D8). From the draft: should the hub read a stage whose truth is a human view, such as a Notion database, from that tool, or only from a text copy as now? Should it read results that are not stage sources, such as test runs for `12-qa` or the state of tasks for `10-wbs`?

### CTX-008 Overview

Purpose: show every project on one page, so that the user sees where each one stands, follows any ID through the stages and opens the tool behind each stage. Built in phase 1 and kept as each project's home page.

- Events: Hub page built, Hub page opened, Trace followed, Human view opened
- Commands: Build hub page, Open hub page, Trace ID, Search items
- Policies: One page for all registered projects, the same on a device and on the server. Each project shows its current stage and next action first. Link to each stage's human view instead of rebuilding the tool. Show text only as text, and load nothing from the network. Follow the profile's language and the system's light or dark mode. Leave off projects that are no longer in the project list.
- Actors: User, Viewer
- Open questions, from the draft: What should the first screen on a phone show? What should a viewer see before any project has been pushed? Which summaries of single stages are worth a place, such as the API list of `06-api`, the progress of tasks in `10-wbs` or the test results of `12-qa`? Should the page show what changed since the viewer's last visit, and link the project's records? Should it show memory's current state of each project?

### CTX-009 Sharing

Purpose: put the hub on an address of the user's own, so that it opens on any device, while nothing leaves a device unless the user sends it and only allowed people can open it. Built in phase 1 and deployed on 2026-10-24.

- Events: Push previewed, Snapshot pushed, Snapshot stored, Snapshot refused, Project removed, Request refused, Viewer signed in
- Commands: Preview push, Push snapshots, Remove project, Sign in
- Policies: Nothing leaves a device until the user pushes. Push only the projects in the push list, and ask before the first push of each project. Read the service token only from the environment, and never write or show it. Follow no redirects, so that a refused token is reported instead of sent on. The server answers only requests that Cloudflare Access checked, at the address the user set and nowhere else. It keeps only the newest snapshot of each project and nothing but snapshots. It has no AI and no rights on any repository. Remove a project only with the user's go-ahead.
- Actors: User, Agent, Hub, NEXUS server, Cloudflare Access, Viewer
- Open questions: Whether a push follows each change on its own was part of hotspot 2: under D8 of stage 02 the agent pushes after each merge of stage work and each checkpoint. From the draft: should the server keep earlier snapshots, so that the page can show changes over time? Team members come later (checkpoint 1); how would Cloudflare Access tell their projects apart?

## 5. Dependencies between contexts

On the board a solid arrow is a call (sync) and a dashed one an event (async), and each leaves the side that asks or tells. The agent is an actor, not a context, so it is not on the map: it reads the agent to-do, gives commands to Discussion and Editing, and opens pull requests on Git. No calls run in a circle.

| From | To | Kind | Why | Data |
| --- | --- | --- | --- | --- |
| Hub (CTX-006) | Git repository | call (sync) | Read the stage sources | stage sources |
| Hub (CTX-006, CTX-009) | CTX-012 | event (async) | Draw from the new snapshot, which the hub on a device pushes (hotspot 2, D8 of stage 02) | snapshot |
| CTX-012 | CTX-013 | event (async) | Cross-check what was drawn | Picture drawn, Picture redrawn |
| CTX-014 | CTX-010 | event (async) | Edit the picture as proposed | Proposal accepted |
| CTX-010 | CTX-012 | call (sync) | Edit the picture that the user sees | the picture and its document version |
| CTX-007 | CTX-013 | call (sync) | Gather what is left | open discrepancies |
| CTX-007 | CTX-014 | call (sync) | Gather what is left | open comments |
| CTX-007 | CTX-010 | call (sync) | Gather what is left | pending reflections |
| CTX-015 | Notion | call (sync) | Show a record's state; the permissions are hotspot 12 | state |
| CTX-015 | Jira | call (sync) | Show a work item's state; the permissions are hotspot 12 | state |

## 6. Hotspots

The answers to eight hotspots are the AI's recommendations, approved at checkpoint 2. Number 13 was added at step 8. Stage 02 answered numbers 2, 4, 8 and 13 with its decisions D8, D10, D11 and D9, which the maintainer approved at its scope check on 2026-10-25.

| Hotspot | Context | State | Answer or next step |
| --- | --- | --- | --- |
| 1. Repositories per space: what about a project with two repositories? | CTX-012 | answered | One repository per project space at first |
| 2. How the stage sources reach NEXUS once they are merged | CTX-012 | answered | The hub on a device pushes snapshots that carry what the pictures show (stage 02, D8) |
| 3. Positions: the layout is automatic; should moved positions reach the stage sources? | CTX-012 | answered | Positions stay in NEXUS; only the content goes to the stage sources |
| 4. Pairs to compare: which items of the DDD board and the ERD, and of the DDD board and the sitemap? | CTX-013 | answered | By glossary term: each aggregate with its ERD tables, and each read model with its sitemap screens (stage 02, D10) |
| 5. Comments on a phone | CTX-014 | answered | Comments work on a phone too; only editing pictures needs a PC |
| 6. When the agent reads new comments | CTX-014 | answered | At the start of its work, open comments first; anything urgent goes in the conversation |
| 7. Where decisions go | CTX-014 | answered | As the current rules say: specs in Git, the user's choices in the records |
| 8. Which open-source editor, such as Excalidraw, ERD Editor or draw.io | CTX-010 | answered | Excalidraw for the DDD board and the sitemap, and ERD Editor for the ERD (stage 02, D11) |
| 9. Conflicts: what if the stage source changes during an edit? | CTX-010 | answered | The edit is shown again over the new picture, and the user chooses |
| 10. Writing to Git: does NEXUS write to Git itself? | CTX-010 | answered | No: the agent opens a pull request at its next work |
| 11. What remains: can a stage pass with open discrepancies or comments? | CTX-007 | answered | They are shown together, and the user decides |
| 12. Reading the state of Notion and Jira: with what permissions? | CTX-015 | open | Decided when the links are built, in phase ③ |
| 13. Where the agent reads its to-do: the hub on a device, an API of the server or another way? | CTX-014, CTX-007 | answered | Through the hub, which reads it from the server's API with the service token (stage 02, D9) |

Stage 02 also took up, beyond the hotspots:

- Where NEXUS keeps spaces, pictures, comments, proposals and edits, and how the agent and the hub reach them, together with hotspots 2 and 13.
- How the stage state that the agent writes to Git meets the status file of phase 1 (CTX-007).
- The screens: the picture view on a phone, for viewing and comments, and on a PC, for editing; and how the hub page leads to each project's pictures.
- The open questions kept from the draft under CTX-006, CTX-008 and CTX-009.

## 7. Glossary

| ID | Term | Definition | Context | Avoid |
| --- | --- | --- | --- | --- |
| TERM-047 | NEXUS | The part of CORTHEX where the user and the agent discuss each project's pictures, drawn from its stage sources, and edit them, with the hub as each project's home; later it also links records and work items. Made of the `corthex-nexus` plugin and the NEXUS server | all | hub (one of its parts) |
| TERM-048 | Hub | The `corthex-hub` skill and its script `hub.py`, which read projects, record progress, build the hub page and push snapshots on a device. Built in phase 1 and kept as each project's home | CTX-006, CTX-007, CTX-008, CTX-009 | NEXUS (the whole), dashboard |
| TERM-049 | Device | A computer where the user runs a host and the hub, with its own project list, checkouts and status files. A cloud session runs on a device whose files are lost when the session's container is reclaimed | all | machine, computer |
| TERM-050 | Project (NEXUS) | A project in the project list together with the other repositories that its settings name under `repos`, read and shown as one. For memory (TERM-005), a project is the repository that a session runs in | CTX-006, CTX-008, CTX-009, CTX-012 | workspace, repo |
| TERM-051 | Registered name | The name of a project in the project list; the hub reads and pushes a project only under that name | CTX-006, CTX-009 | |
| TERM-052 | Checkout | A local copy of one of a project's repositories, listed for the project in the project list | CTX-006 | clone |
| TERM-053 | Stage | One of the 13 steps of the CORTHEX workflow, from `01-domain` to `13-presentation`, each with its six-slot contract | CTX-006, CTX-007, CTX-008 | phase (TERM-097), step |
| TERM-054 | Stage source | The text in a repository that a stage writes and later stages read, set as the stage's `source` in the project settings. The board calls it the stage document; NEXUS draws its pictures from the stage sources in Git | CTX-006, CTX-012, CTX-010 | source alone (TERM-018 uses it for a quote's place) |
| TERM-055 | Human view | Where people look at and edit a stage's work, such as Notion, Miro or ERD Editor, set as the stage's `human` | CTX-006, CTX-008 | tool, UI |
| TERM-056 | Truth | Which side wins when a stage source and its human view differ: `source` or `human`. For the pictures of NEXUS, always the stage sources | CTX-006, CTX-012, CTX-010 | master, primary |
| TERM-057 | Text copy | A stage source refreshed from a human view that is the truth; it records when it was copied | CTX-006 | export, mirror |
| TERM-058 | Trace ID | An ID that a stage creates for an item, made of a prefix for its kind, a hyphen and digits; later stages name it, and it is never reused or renumbered | all | key, number |
| TERM-059 | Item | A trace ID where it is defined, with its title, its fields and its place (file and line) | CTX-006, CTX-008, CTX-012 | record, entry, node |
| TERM-060 | Definition | The one place in the stage sources that creates an item | CTX-006 | declaration |
| TERM-061 | Mention | An ID written anywhere but in its definition | CTX-006 | reference |
| TERM-062 | Link | A connection between two items, made by a mention inside a definition; it counts in both directions | CTX-006, CTX-008 | relation, edge |
| TERM-063 | Check | A finding about how a project's items connect, with a level (`error`, `warn` or `info`) and the IDs concerned; a lead, not a verdict | CTX-006, CTX-007, CTX-008 | verdict, lint |
| TERM-064 | Check rule | A named rule of the hub that raises checks, such as `duplicate-id` | CTX-006 | |
| TERM-065 | Snapshot | What one reading of a project saved: its items, links, checks, stage settings and recorded progress, without file contents or local paths | CTX-006, CTX-008, CTX-009, CTX-012 | export, backup, dump |
| TERM-066 | Redaction (hub) | Replacing secrets and email addresses in a snapshot's titles and fields with `[redacted]`, and leaving out a link that holds one. Memory's redaction (TERM-010) works on conversation text before it is written | CTX-006 | masking |
| TERM-067 | Stage state | A stage's recorded progress: `done`, `in_progress`, `not_started` or `skipped`, and `unknown` while nothing is recorded | CTX-007, CTX-008 | status, progress |
| TERM-068 | Checkpoint | A stage's human checkpoint as recorded: what was approved, by whom and where, with its date | CTX-007 | approval, sign-off |
| TERM-069 | Next action | The step that a stage's record names as next | CTX-007, CTX-008 | task, to-do (TASK is the trace ID of `10-wbs`) |
| TERM-070 | Review finding | A check that a person or an agent recorded after reading the sources, such as a spec that contradicts its requirement | CTX-007 | comment |
| TERM-071 | Status file | The file on a device with a project's recorded stage states, checkpoints, next actions and review findings, outside every repository; where phase 1 keeps the stage records | CTX-007 | progress file |
| TERM-072 | Records | The project's place for meetings, decisions and progress notes, set as `records` in the project settings, such as a Notion database | CTX-007, CTX-008, CTX-014, CTX-015 | log, notes |
| TERM-073 | Hub page | The one page with every registered project's stages, checks and items: built on a device, or served by the NEXUS server | CTX-008 | dashboard, site |
| TERM-074 | Trace view | The part of the hub page that shows, for one ID, what it comes from and what it leads to through the stages | CTX-008 | graph, map |
| TERM-075 | Viewer | A person who opens the hub page: on a device, the user; on the server, anyone that Cloudflare Access lets in | CTX-008, CTX-009 | visitor |
| TERM-076 | NEXUS server | The user's own server that keeps pushed snapshots and serves the hub page behind Cloudflare Access; in phase 1 a Cloudflare Worker with a D1 database, deployed by the user | CTX-009 | cloud, backend, sync remote (TERM-033) |
| TERM-077 | Push | Sending saved snapshots from a device to the NEXUS server | CTX-009 | sync (memory's CTX-004), upload |
| TERM-078 | Push list | The projects that a device may push, listed in the profile | CTX-009 | allowlist |
| TERM-079 | Dry run | Showing what a push would send, without sending it | CTX-009 | test push |
| TERM-080 | Removal | Deleting a project and its snapshot from the NEXUS server; the project's sources and the device's files stay | CTX-009 | purge (TERM-036) |
| TERM-081 | Server revision | How many snapshots of a project the NEXUS server has stored | CTX-009 | version |
| TERM-082 | Cloudflare Access | The sign-in in front of the NEXUS server; the server answers only the requests that it checked | CTX-009 | login, auth |
| TERM-083 | Service token | The Cloudflare Access credential that a push uses, read from environment variables | CTX-009 | API key, password |
| TERM-084 | Allowed people | The people that an Access policy lets open the NEXUS server; for one person, their own account | CTX-009 | users, members |
| TERM-085 | Picture | A diagram that NEXUS draws from a stage source, such as the DDD board, the ERD or the sitemap: one for each document version, always equal to it. Its nodes are items, so comments, discrepancies and tool links attach to their trace IDs, not to positions | CTX-012, CTX-013, CTX-014, CTX-010 | structure diagram (its earlier name), canvas, whiteboard |
| TERM-088 | Proposal | A change to a picture that the agent puts on it at its next work, with its reason; only the user accepts or dismisses it, and an accepted proposal waits to be reflected | CTX-014, CTX-010 | suggestion |
| TERM-089 | Accept | The user's taking a proposal; the picture is then edited as proposed, and the agent reflects the edit like any other | CTX-014, CTX-010 | import (its earlier name), merge |
| TERM-091 | Edit conflict | An edit made on a picture whose document version is no longer the latest, because the stage source changed meanwhile; the edit is shown again over the new picture, and the user chooses | CTX-010 | |
| TERM-092 | Reflect | The agent's writing edits and accepted proposals into the stage sources, by pull request at its next work; NEXUS never writes to Git | CTX-010 | apply (its earlier name), sync, publish, deploy |
| TERM-093 | Team project | A project that several people work on, with `team: true` in its settings | CTX-009, CTX-010 | shared project |
| TERM-097 | Phase | One step of the plan for NEXUS: phase 1, the hub and the server, is built; the plan of 2026-10-24 follows it with phase ① discussion over pictures, phase ② editing pictures and phase ③ links to Notion and Jira | all | stage (TERM-053), release |
| TERM-109 | Project space | The place in NEXUS for one project's pictures, bound to its repository: one for each project, and at first one repository for each space | CTX-012 | workspace, board |
| TERM-110 | Document version | The stage sources at one commit in Git. A picture is drawn for one document version, and an edit is bound to the version that its picture was drawn from | CTX-012, CTX-010 | revision (TERM-081 counts snapshots), board revision |
| TERM-111 | Picture view | A picture with its comments, proposals and discrepancies on it: what the user looks at before commenting, accepting or dismissing a proposal and editing | CTX-012, CTX-014, CTX-010 | canvas |
| TERM-112 | Discrepancy | A place where two pictures of a project disagree when their items are paired by ID, such as an ERD table with no matching aggregate on the DDD board. Only one is open for each pair, and it is resolved when a new cross-check no longer finds it. Unlike a check (TERM-063), it has a state and can be discussed | CTX-013, CTX-007 | mismatch, conflict (TERM-091), error |
| TERM-113 | Pair | The two things that a cross-check compares, such as an aggregate on the DDD board and a table in the ERD; which pairs are compared first is decision D10 of stage 02 (hotspot 4) | CTX-013 | match |
| TERM-114 | Comment | A note that the user or the agent attaches to an item in a picture by its trace ID, so that it follows the item when the picture is redrawn. It closes when a decision is attached or it is answered. Comments work on a phone too | CTX-014, CTX-007 | review finding (TERM-070) |
| TERM-115 | Decision | What the user settles about a comment, which the agent writes down as the user said: specs into the stage sources in Git, the user's choices into the records | CTX-014 | approval, user decision (TERM-020, a memory item) |
| TERM-116 | Edit | A change to a picture, made by the user on a PC with the open-source editor or by an accepted proposal. It is bound to the document version that its picture was drawn from, and it closes once it is reflected | CTX-010 | change, patch |
| TERM-117 | Pending reflection | An edit, or an accepted proposal, that is not yet reflected in the stage sources | CTX-010, CTX-007 | draft, unsaved change |
| TERM-118 | Open-source editor | An existing editor that NEXUS embeds for editing pictures, such as Excalidraw, ERD Editor or draw.io; stage 02 chose Excalidraw and ERD Editor (D11, hotspot 8). NEXUS does not build an editor from scratch | CTX-010 | canvas |
| TERM-119 | Stage record | What Stage progress keeps for one stage: its state, its checkpoints and its next action. Only the user passes a checkpoint, and the agent writes the stage state to Git | CTX-007 | status file (TERM-071, where phase 1 keeps it) |
| TERM-120 | Stage overview | What is left in a stage before its checkpoint: its open discrepancies, comments and pending reflections, shown together so that the user decides | CTX-007 | dashboard, stage state (TERM-067) |
| TERM-121 | Agent to-do | What the agent reads when it starts its work: open comments and discrepancies, and pending reflections; it reads them through the hub (D9 of stage 02, hotspot 13) | CTX-007, CTX-014, CTX-010 | next action (TERM-069), task (TASK is the trace ID of `10-wbs`), inbox |
| TERM-122 | Tool link | A link from an item in a picture to a record in Notion or a work item in Jira, which shows only its state; each tool stays the source. A candidate for phase ③ | CTX-015 | link alone (TERM-062), sync, import |
| TERM-123 | Work item | A unit of work in a tracker such as Jira | CTX-015 | task (TASK is the trace ID of `10-wbs`), ticket |
| TERM-124 | Part | A named portion of one project: the documents whose paths in each stage source start with the part's name, such as `memory` and `nexus` in this repository. Set as `parts` in the project settings; each part has its own pictures and stage records | CTX-006, CTX-007, CTX-012 | module, component |
| TERM-125 | Picture source | What the hub takes from a part's stage source for one picture: its items, their connections and their terms, without a layout. A snapshot carries it to the NEXUS server, which keeps it as the picture of its document version | CTX-006, CTX-012 | layout, image |
| TERM-126 | Default branch | The branch that a repository's `origin` remote names as its head, such as `main`. NEXUS takes pictures and stage records only from its commit as the checkout last fetched it | CTX-006 | main (a branch's name, not this role) |
| TERM-127 | Reply | A note under a comment, by the user or the agent. A user's reply can settle the comment, or open a closed one again | CTX-014 | answer (a comment is answered when it closes) |
| TERM-128 | Claim | The NEXUS server's hold of one entry of the agent to-do for one agent session: other sessions' writes on the entry are refused until a set time after the session's last write on it (60 minutes by default) or until the entry closes | CTX-007 | lock, lease |
| TERM-129 | Outbox | The file on a device where the hub keeps the agent's writes that it could not send, until its next contact with the NEXUS server | CTX-014, CTX-009 | queue |

Removed with the board, with their IDs kept:

| ID | Term | Status | Why |
| --- | --- | --- | --- |
| TERM-086 | User board | removed | A picture has one version that the user and the agent both see, and proposals show on it in the picture view |
| TERM-087 | Proposal board | removed | As for TERM-086 |
| TERM-090 | Board revision | removed | An edit is bound to the document version (TERM-110) instead |
| TERM-094 | MCP server (NEXUS) | removed | Removed with CTX-011 |
| TERM-095 | Chat client | removed | Removed with CTX-011 |
| TERM-096 | In-chat view | removed | Removed with CTX-011 |

Changed with the board on 2026-10-24: TERM-085, TERM-089 and TERM-092 have new names and definitions under the same IDs; TERM-047, TERM-048, TERM-054, TERM-056, TERM-071, TERM-088, TERM-091 and TERM-097 have new definitions; TERM-050, TERM-059, TERM-065, TERM-072, TERM-076 and TERM-082 have only updated contexts; TERM-109 to TERM-123 are new. TERM-124 to TERM-129 were added with the functional spec on 2026-11-02 ([docs/04-functional-spec/nexus.md](../04-functional-spec/nexus.md#new-words)).
