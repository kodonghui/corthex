# NEXUS: domain

[한국어](nexus.ko.md)

Stage 01 of CORTHEX's own project, for NEXUS: the `corthex-nexus` plugin and the server in [`nexus/`](../../nexus/). Status: draft of 2026-10-24, for the maintainer's check together with the requirements built on it (stage 02). Phase 1 of NEXUS is built and deployed; this file describes the whole domain again, so that the requirements can decide what NEXUS keeps, changes and adds. When this file and its Korean translation differ, this file is the source.

This file holds both the contexts and the glossary of NEXUS. Its IDs continue after those of CORTHEX-MEMORY in [memory.md](memory.md): contexts from CTX-006, terms from TERM-047. The terms that memory.md already defines keep their meaning here, such as Host, Agent, Profile, Project settings and Project list; where NEXUS uses a word differently, its glossary row says how.

Sources read:

- The maintainer's goal for NEXUS in the project's records: where a stage needs a tool that no existing tool provides, build it under the name NEXUS, deploy it on the maintainer's own domain, and work on several projects from one page.
- The design draft for NEXUS in the maintainer's records (2026-10-23): what earlier attempts under the same name left (ideas, but no code), which stages only link to an existing tool, the plan in three phases, and the decision of the same day to start with the hub.
- Phase 1 as built: [`plugins/corthex-nexus/`](../../plugins/corthex-nexus/), [`nexus/`](../../nexus/) and [docs/architecture.md](../architecture.md#project-hub).
- The deployment of 2026-10-24: the server on the maintainer's own address behind Cloudflare Access, a sign-in from a phone, a push with a service token, and a sample project.
- The maintainer's questions of 2026-10-24 after opening the hub before any project was on it, and the decision of the same day to define NEXUS from stage 01 with the harness, keeping phase 1 as material.
- The decision of 2026-10-24 that NEXUS builds no ERD editor and that new projects use ERD Editor for stage 05.
- The memory domain in [memory.md](memory.md), for the shared terms and the boundary with memory.

## Contexts

Six contexts. CTX-006 to CTX-009 exist in phase 1 (`corthex-nexus` 0.1.0 and the server). CTX-010 and CTX-011 are candidates from the design draft and are not built.

### CTX-006 Reading

Purpose: turn the stage sources of each registered project into a snapshot of its trace items, their links and the checks, without changing anything.

- Events: Snapshot built, Stage read, Stage not read, Files skipped, Check raised, Project refused, Snapshot cut
- Commands: Build snapshot
- Policies: Read only the projects in the project list, each only under its registered name. Read text only: never run a project's code, Git hooks or Git filters, and never write to a repository. An ID is defined only in the stage that creates its kind; anywhere else it is a mention. Skip files that look like secrets, and translations that define only their original's IDs. Keep file contents and local paths out of the snapshot, and redact secrets and email addresses. A check finds structure, not meaning: it is a lead, not a verdict. Never renumber an ID to clear a check.
- Actors: User, Agent, Hub
- Open questions: Should the hub read a stage whose truth is a human view, such as a Notion database, from that tool, or only from a text copy as now? Should it read results that are not stage sources, such as test runs for `12-qa` or the state of tasks for `10-wbs`? Should a snapshot be built on its own, for example after each merge, or only when someone runs the hub?

### CTX-007 Progress

Purpose: keep what people decided about each stage: its state, its last checkpoint, its next action and the findings of reviews.

- Events: Stage state recorded, Checkpoint recorded, Next action set, Review finding recorded, Findings cleared, Stage record reset, Done refused
- Commands: Record stage state, Record checkpoint, Set next action, Record review finding, Clear findings, Reset stage record
- Policies: A stage's state comes only from what was recorded, never from the files that exist. `done` needs a checkpoint and its date; an AI recommendation, a read receipt or an edit time is not a checkpoint. Record only what the user said or what was checked. Keep the status file outside every repository, with its previous version as a backup.
- Actors: User, Agent
- Open questions: Where should progress live when the user works on several devices, including cloud sessions whose files are lost when the session ends: each device's status file as now, the repository, the NEXUS server or the project's records? Should progress be recorded from the hub page or a phone, not only by an agent? The records, such as a Notion project page, and memory's current state (TERM-014) also hold next actions: which one is the truth, and should the others follow it?

### CTX-008 Overview

Purpose: show every project on one page, so that the user sees where each one stands, follows any ID through the stages and opens the tool behind each stage.

- Events: Hub page built, Hub page opened, Trace followed, Human view opened
- Commands: Build hub page, Open hub page, Trace ID, Search items
- Policies: One page for all registered projects, the same on a device and on the server. Each project shows its current stage and next action first. Link to each stage's human view instead of rebuilding the tool. Show text only as text, and load nothing from the network. Follow the profile's language and the system's light or dark mode. Leave off projects that are no longer in the project list.
- Actors: User, Viewer
- Open questions: What should the first screen on a phone show? What should a viewer see before any project has been pushed? Which summaries of single stages are worth a place, such as the API list of `06-api`, the progress of tasks in `10-wbs` or the test results of `12-qa`? Should the page show what changed since the viewer's last visit, and link the project's records? Should it show memory's current state of each project?

### CTX-009 Sharing

Purpose: put the hub on an address of the user's own, so that it opens on any device, while nothing leaves a device unless the user sends it and only allowed people can open it.

- Events: Push previewed, Snapshot pushed, Snapshot stored, Snapshot refused, Project removed, Request refused, Viewer signed in
- Commands: Preview push, Push snapshots, Remove project, Sign in
- Policies: Nothing leaves a device until the user pushes. Push only the projects in the push list, and ask before the first push of each project. Read the service token only from the environment, and never write or show it. Follow no redirects, so that a refused token is reported instead of sent on. The server answers only requests that Cloudflare Access checked, at the address the user set and nowhere else. It keeps only the newest snapshot of each project and nothing but snapshots. It has no AI and no rights on any repository. Remove a project only with the user's go-ahead.
- Actors: User, Agent, Hub, NEXUS server, Cloudflare Access, Viewer
- Open questions: Should a push follow each build or each stage change on its own, or wait for a request as now? Should the server keep earlier snapshots, so that the page can show changes over time? Should people other than the user, such as team members, see some of the projects, and how would Cloudflare Access tell those projects apart?

### CTX-010 Structure editing

Purpose: let the user and agents change diagrams whose every node is a trace item, such as the sitemap and the user flows, in one place and without losing the trace. A candidate from the design draft, not built.

- Events: Board edited, Proposal made, Proposal imported, Proposal dismissed, Edit conflict found, Change applied
- Commands: Edit board, Propose change, Import proposal, Dismiss proposal, Apply change
- Policies, from the design draft and not decided: Agents write only to the proposal board and give a reason for each proposal; only the user moves a proposal to the user board. Each saved change gets a revision and a reason, and an edit based on an older revision is refused. The server runs no AI: agents on a device decide and apply. A change reaches the stage source only through an agent on a device, never through the server, and never straight into a team project's repositories.
- Actors: User, Agent, NEXUS server
- Open questions: Is it needed, or do Mermaid files in the repository with Excalidraw or Miro do the job? For which stages: `07-sitemap`, `03-user-flow` or others? Which side is the truth of a diagram, the stage source or the board? How should a change reach a team project: as a pull request, or not at all?

### CTX-011 Assistant access

Purpose: let assistants in chat clients read the hub, propose changes where structure editing exists, and show small views of the hub inside a conversation. A candidate from the design draft, not built.

- Events: Assistant connected, Project read by an assistant, In-chat view shown
- Commands: Connect assistant, Read project, Show in-chat view
- Policies, from the design draft and not decided: An assistant reads what the hub page shows and nothing more. It signs in through Cloudflare Access, as a viewer does. It changes nothing except through proposals under the policies of CTX-010.
- Actors: User, Chat client, NEXUS server, Cloudflare Access
- Open questions: Is it needed, or is it enough that an agent in a session reads the snapshots on its device? Which chat clients matter: the Claude apps on a phone or a desktop, ChatGPT, Codex? Can chat clients sign in through Cloudflare Access on the plan in use? Should assistants record progress through it?

## Context map

- **Reading to Overview and Sharing.** The snapshot, in the format `corthex-hub/0.1`, is all that the other contexts get from the stage sources.
- **Progress to Reading.** Recorded progress joins the snapshot when the snapshot is built. The status file is never pushed by itself.
- **Sharing to Overview.** The server serves the same page from the pushed snapshots, so a viewer there sees what the last push of each project carried.
- **Structure editing to Reading** (candidate). An applied change shows on the hub only through the stage source and the next snapshot.
- **Assistant access to Overview and Structure editing** (candidate). It reads what the page shows and proposes under the policies of structure editing.
- **Outside NEXUS.** Human views stay in their tools, such as Miro, Notion, ERD Editor, Swagger UI, Figma and GitHub, and the hub links to them. Meetings and decisions stay in the project's records. Memory (CTX-001 to CTX-005) keeps the context of conversations; phase 1 of NEXUS reads no conversations and no memory.

## Glossary

| ID | Term | Definition | Context | Avoid |
| --- | --- | --- | --- | --- |
| TERM-047 | NEXUS | The part of CORTHEX that puts all of a user's projects on one page and builds the tools that stages need where no existing tool fits: the `corthex-nexus` plugin and the NEXUS server | all | hub (one of its parts) |
| TERM-048 | Hub | The `corthex-hub` skill and its script `hub.py`, which read projects, record progress, build the hub page and push snapshots on a device | CTX-006, CTX-007, CTX-008, CTX-009 | NEXUS (the whole), dashboard |
| TERM-049 | Device | A computer where the user runs a host and the hub, with its own project list, checkouts and status files. A cloud session runs on a device whose files are lost when the session's container is reclaimed | all | machine, computer |
| TERM-050 | Project (NEXUS) | A project in the project list together with the other repositories that its settings name under `repos`, read and shown as one. For memory (TERM-005), a project is the repository that a session runs in | CTX-006, CTX-008, CTX-009 | workspace, repo |
| TERM-051 | Registered name | The name of a project in the project list; the hub reads and pushes a project only under that name | CTX-006, CTX-009 | |
| TERM-052 | Checkout | A local copy of one of a project's repositories, listed for the project in the project list | CTX-006 | clone |
| TERM-053 | Stage | One of the 13 steps of the CORTHEX workflow, from `01-domain` to `13-presentation`, each with its six-slot contract | CTX-006, CTX-007, CTX-008 | phase (TERM-097), step |
| TERM-054 | Stage source | The text in a repository that a stage writes and later stages read, set as the stage's `source` in the project settings | CTX-006 | source alone (TERM-018 uses it for a quote's place), document |
| TERM-055 | Human view | Where people look at and edit a stage's work, such as Notion, Miro or ERD Editor, set as the stage's `human` | CTX-006, CTX-008 | tool, UI |
| TERM-056 | Truth | Which side wins when a stage source and its human view differ: `source` or `human` | CTX-006, CTX-010 | master, primary |
| TERM-057 | Text copy | A stage source refreshed from a human view that is the truth; it records when it was copied | CTX-006 | export, mirror |
| TERM-058 | Trace ID | An ID that a stage creates for an item, made of a prefix for its kind, a hyphen and digits; later stages name it, and it is never reused or renumbered | all | key, number |
| TERM-059 | Item | A trace ID where it is defined, with its title, its fields and its place (file and line) | CTX-006, CTX-008 | record, entry, node |
| TERM-060 | Definition | The one place in the stage sources that creates an item | CTX-006 | declaration |
| TERM-061 | Mention | An ID written anywhere but in its definition | CTX-006 | reference |
| TERM-062 | Link | A connection between two items, made by a mention inside a definition; it counts in both directions | CTX-006, CTX-008 | relation, edge |
| TERM-063 | Check | A finding about how a project's items connect, with a level (`error`, `warn` or `info`) and the IDs concerned; a lead, not a verdict | CTX-006, CTX-007, CTX-008 | verdict, lint |
| TERM-064 | Check rule | A named rule of the hub that raises checks, such as `duplicate-id` | CTX-006 | |
| TERM-065 | Snapshot | What one reading of a project saved: its items, links, checks, stage settings and recorded progress, without file contents or local paths | CTX-006, CTX-008, CTX-009 | export, backup, dump |
| TERM-066 | Redaction (hub) | Replacing secrets and email addresses in a snapshot's titles and fields with `[redacted]`, and leaving out a link that holds one. Memory's redaction (TERM-010) works on conversation text before it is written | CTX-006 | masking |
| TERM-067 | Stage state | A stage's recorded progress: `done`, `in_progress`, `not_started` or `skipped`, and `unknown` while nothing is recorded | CTX-007, CTX-008 | status, progress |
| TERM-068 | Checkpoint | A stage's human checkpoint as recorded: what was approved, by whom and where, with its date | CTX-007 | approval, sign-off |
| TERM-069 | Next action | The step that a stage's record names as next | CTX-007, CTX-008 | task, to-do (TASK is the trace ID of `10-wbs`) |
| TERM-070 | Review finding | A check that a person or an agent recorded after reading the sources, such as a spec that contradicts its requirement | CTX-007 | comment |
| TERM-071 | Status file | The file on a device with a project's recorded stage states, checkpoints, next actions and review findings, outside every repository | CTX-007 | progress file |
| TERM-072 | Records | The project's place for meetings, decisions and progress notes, set as `records` in the project settings, such as a Notion database | CTX-007, CTX-008 | log, notes |
| TERM-073 | Hub page | The one page with every registered project's stages, checks and items: built on a device, or served by the NEXUS server | CTX-008 | dashboard, site |
| TERM-074 | Trace view | The part of the hub page that shows, for one ID, what it comes from and what it leads to through the stages | CTX-008 | graph, map |
| TERM-075 | Viewer | A person who opens the hub page: on a device, the user; on the server, anyone that Cloudflare Access lets in | CTX-008, CTX-009 | visitor |
| TERM-076 | NEXUS server | The user's own server that keeps pushed snapshots and serves the hub page behind Cloudflare Access; in phase 1 a Cloudflare Worker with a D1 database, deployed by the user | CTX-009, CTX-010, CTX-011 | cloud, backend, sync remote (TERM-033) |
| TERM-077 | Push | Sending saved snapshots from a device to the NEXUS server | CTX-009 | sync (memory's CTX-004), upload |
| TERM-078 | Push list | The projects that a device may push, listed in the profile | CTX-009 | allowlist |
| TERM-079 | Dry run | Showing what a push would send, without sending it | CTX-009 | test push |
| TERM-080 | Removal | Deleting a project and its snapshot from the NEXUS server; the project's sources and the device's files stay | CTX-009 | purge (TERM-036) |
| TERM-081 | Server revision | How many snapshots of a project the NEXUS server has stored | CTX-009 | version |
| TERM-082 | Cloudflare Access | The sign-in in front of the NEXUS server; the server answers only the requests that it checked | CTX-009, CTX-011 | login, auth |
| TERM-083 | Service token | The Cloudflare Access credential that a push uses, read from environment variables | CTX-009 | API key, password |
| TERM-084 | Allowed people | The people that an Access policy lets open the NEXUS server; for one person, their own account | CTX-009 | users, members |
| TERM-085 | Structure diagram | A diagram whose every node is a trace item, such as the screens of the sitemap or the steps of a user flow | CTX-010 | canvas, whiteboard, drawing |
| TERM-086 | User board | The version of a structure diagram that the user edits on the page | CTX-010 | human canvas |
| TERM-087 | Proposal board | The version of a structure diagram where agents put the changes they propose | CTX-010 | AI canvas |
| TERM-088 | Proposal | One change on the proposal board, with the agent's reason | CTX-010 | suggestion |
| TERM-089 | Import | The user's moving a proposal to the user board | CTX-010 | accept, merge |
| TERM-090 | Board revision | The number of a board's saved version. It differs from the server revision (TERM-081), which counts pushed snapshots | CTX-010 | version |
| TERM-091 | Edit conflict | An edit based on a board revision that is no longer the latest | CTX-010 | |
| TERM-092 | Apply | An agent's writing an imported change into the stage source, on a device | CTX-010 | sync, publish, deploy |
| TERM-093 | Team project | A project that several people work on, with `team: true` in its settings | CTX-009, CTX-010 | shared project |
| TERM-094 | MCP server (NEXUS) | The part of the NEXUS server that assistants would call through the Model Context Protocol | CTX-011 | API, plugin |
| TERM-095 | Chat client | An app where the user talks with an assistant outside a host, such as the Claude apps on a phone or a desktop, or ChatGPT, and that can connect MCP servers | CTX-011 | host (TERM-001) |
| TERM-096 | In-chat view | A small page that an MCP server shows inside a conversation of a chat client (MCP Apps); Claude Code shows such views as text only | CTX-011 | widget, card |
| TERM-097 | Phase | One step of the design draft's plan for NEXUS: 1 the hub and the server (built), 2 structure editing and an MCP server, 3 in-chat views | all | stage (TERM-053), release |
