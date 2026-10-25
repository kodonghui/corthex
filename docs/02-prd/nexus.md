# NEXUS: requirements

[한국어](nexus.ko.md)

Stage 02 of CORTHEX's own project, for NEXUS: the `corthex-nexus` plugin and the NEXUS server. Status: rewritten on 2026-10-24 from the event storming board and the new stage 01. The maintainer checked the scope on 2026-10-25 and approved the recommendations of D8 to D13, without changes (the stage's first checkpoint). It replaces the draft of 2026-10-24, which planned the next release around the hub of phase 1. The draft's rows keep their IDs: the rows marked `built` describe phase 1 as it runs now, in `corthex-nexus` 0.1.0 and the server deployed on 2026-10-24, and the rows that the board changed or removed say so. When this file and its Korean translation differ, this file is the source.

Inputs: the contexts and the glossary in [docs/01-domain/nexus.md](../01-domain/nexus.md) (CTX-006 to CTX-015, TERM-047 to TERM-123), with the shared terms of [docs/01-domain/memory.md](../01-domain/memory.md). Words in this file have the meanings given there.

## Goal

Let the user and the AI discuss each project's pictures, the DDD board, the ERD and the sitemap, which NEXUS draws from the stage sources in Git and checks against each other, on a phone as on a PC. Later, let the user edit the pictures and link Notion records and Jira work items to them. The hub of phase 1 stays as each project's home, and NEXUS builds only what existing tools cannot do.

## Problems

Problems 8 to 12 come from the maintainer's words of 2026-10-24 and the board, and they are what the next release is for. Problems 1 to 7 came with the hub of phase 1 and still hold. Each requirement below names the problem or the decision it comes from.

1. A project's stage work sits in several repositories and tools, so seeing where every project stands means opening each of them or asking an agent.
2. Whether the stages connect, for example whether every Must requirement has a spec, is hard to see by hand.
3. A file that exists is not a finished stage, and the state of each stage is written in different places: in chats, in the records and in the hub's status files.
4. The user works from several devices, among them a phone and cloud sessions whose files are lost when they end, and needs the same page on each.
5. Project material must not leak through the hub: file contents, secrets, and protected data such as answer keys or student records.
6. Some stages, such as the sitemap and the user flows, have no tool where people and agents change the same diagram of trace items.
7. The deployed hub first showed no project at all, and did not say what it does or how a project gets onto it.
8. The user and the AI discuss a project's design in text, while what they discuss, the domain model, the ERD and the sitemap, are pictures: the user cannot point at a part of a picture and talk about it with the AI.
9. A picture drawn by hand or by an AI drifts from the stage sources that it shows, so the picture and the text disagree without anyone noticing.
10. Whether the pictures agree with each other, such as an ERD table with no aggregate behind it, is hard to see by hand.
11. The AI is not there between sessions, so what the user notes on a phone must wait for the agent's next work without getting lost.
12. Records and work items live in Notion and Jira, apart from the pictures that they concern.

## Scope

The next release, NEXUS 0.2, as decided in D13: phase ①, discussion over pictures, with the hub of phase 1 as each project's home. Building starts after the memory plugin.

- In: drawing the DDD board, the ERD and the sitemap from the stage sources, each once a project has its stage source (CTX-012); the picture view, on a phone for viewing and comments, and on a PC; cross-checking the pictures in the pairs of D10 (CTX-013); comments, proposals and decisions between the user and the agent (CTX-014); accepted proposals as pending reflections, which the agent reflects by pull request (CTX-010, without the editor); the stage overview, checkpoints passed in NEXUS and stage records in the repository (CTX-007, D12); the agent to-do through the hub (D9); pushes that carry what the pictures show (D8); this repository as the first project.
- Later: editing pictures on a PC with the embedded editor (phase ②, D11); links to Notion records and Jira work items (phase ③, CTX-015, hotspot 12); team members; earlier snapshots on the server; reading human views through their APIs; serving as memory's sync remote (memory's decision D3).
- Never built: a picture editor of NEXUS's own, since it embeds an open-source one; Notion or Jira again, since it links to them; an ERD editor, since new projects use ERD Editor; mockup or presentation tools; AI inside the server; writes to Git by NEXUS, since the agent reflects by pull request; memory, which is CORTHEX-MEMORY.
- Projects with protected data, such as answer keys or student records, and team projects whose members have not agreed, are not pushed.

## Decisions in force

| When | Decision | Affects |
| --- | --- | --- |
| 2026-10-23 | Start with the hub (phase 1) and decide each next phase on its own. Stage sources stay where they are; only snapshots go to the server. | REQ-070, REQ-105, REQ-118 |
| 2026-10-23 | Phase 1 uses Cloudflare D1, with all database code in one module, so that Postgres can replace it if that is needed later. | REQ-123 |
| 2026-10-24 | The server runs at the maintainer's own address behind Cloudflare Access. It was deployed and checked the same day. | REQ-113, REQ-114 |
| 2026-10-24 | NEXUS builds no ERD editor. New projects use ERD Editor, and the hub reads the table comments that it writes. | Scope, D11 |
| 2026-10-24 | NEXUS is defined again from stage 01 with the harness, keeping phase 1 as material. | This file |
| 2026-10-24 | Work goes to the harness itself and leaves the progress of other projects out. | Scope, success measures |
| 2026-10-24 | NEXUS is where the user and the AI discuss each project's pictures, such as the DDD board, the ERD and the sitemap. Editing them is wanted if possible, and Notion and Jira in the same place better still. | Goal, problems 8 to 12 |
| 2026-10-24 | NEXUS is built in stages: phase ① discussion over pictures, phase ② editing with an embedded open-source editor and phase ③ links to Notion and Jira. The hub stays as each project's home, and building comes after the memory plugin. | Scope, D13 |
| 2026-10-24 | Checkpoint 1 of the board: the DDD board, the ERD and the sitemap first; the user and the AI first; the pictures come from the stage sources in Git, and the AI reflects edits in them; discussion in comments and in the conversation; viewing on a phone too, and editing on a PC first; Notion and Jira linked, not moved. The server therefore keeps what the project spaces hold, besides the snapshots. | REQ-118, REQ-120, REQ-136 to REQ-150, REQ-158 to REQ-168, REQ-186 to REQ-190 |
| 2026-10-24 | Checkpoints 2 and 3 of the board: the six contexts; the answers to hotspots 1, 3, 5, 6, 7, 9, 10 and 11; the five policies and the command rows. Assistant access (CTX-011) is removed. | REQ-128 to REQ-131, REQ-133 to REQ-135, REQ-143 to REQ-185 |
| 2026-10-25 | The scope check, the stage's first checkpoint: the scope above, without changes, and D8 to D13 as recommended, as listed under the open decisions. | Scope; REQ-076, REQ-085 to REQ-087, REQ-089, REQ-105, REQ-125, REQ-127, REQ-130, REQ-141, REQ-142, REQ-152 to REQ-154, REQ-170 to REQ-175, REQ-180, REQ-183 to REQ-188, REQ-191 to REQ-193 |

The maintainer's own words and where they were said are in the maintainer's records, not in this repository.

## Open decisions

None of NEXUS's own decisions is open. At the scope check on 2026-10-25 the maintainer approved the recommendations of D8 to D13, so the requirements that depended on them are `active`; the table keeps each question with the other choices that were weighed. D1 to D4 are memory's decisions, in [memory.md](memory.md#open-decisions); D5 to D7, from the draft, were replaced on 2026-10-24 and are listed after the table.

| ID | Question | Recommendation | Other choices | Status |
| --- | --- | --- | --- | --- |
| D8 | How the stage sources reach NEXUS once they are merged (hotspot 2) | The hub on a device, as now: the agent pushes the snapshot, which then carries the parts of the stage sources that pictures show, after each merge of stage work and each checkpoint, and at the start of its work when the pushed sources are older than the checkout. It works for any project and Git host, needs no new secret, and the server still holds no rights on any repository | A CI job in each repository pushes after each merge: always current, but each repository needs the service token as a secret, and a job sees only its own repository; the server reads the repositories itself: current without a device, but it needs rights on every repository, against REQ-122, and the hub's reading code again in JavaScript | decided 2026-10-25 |
| D9 | Where the agent reads its to-do and writes its answers (hotspot 13) | Through the hub: it reads the to-do from the server's API and sends the agent's comments, proposals and decisions, with the same service token that pushes use. The stage skills have the agent read it at the start of its work. It works the same way in Claude Code and Codex and needs no new setup | An MCP server on NEXUS: tools inside the chat, but its sign-in through Cloudflare Access is untested, and checkpoint 3 removed assistant access (CTX-011); only in the conversation: nothing to build, but comments left on a phone wait until the user mentions them | decided 2026-10-25 |
| D10 | Which pairs the cross-check compares first (hotspot 4) | Two pairs, by glossary term: each aggregate on the DDD board with the ERD tables that name its term, and each read model with the sitemap screens that name its term. The stage 05 and 07 skills have the agent write those terms. Pairing by ID gives few false leads | Pairs by name: no new IDs, but different spellings make false leads; contexts only, matching each table's context: exact with today's IDs, but it finds few discrepancies; more pairs now, such as commands and API operations: more coverage, but commands have no IDs yet | decided 2026-10-25 |
| D11 | Which open-source editor NEXUS embeds (hotspot 8) | Excalidraw for the DDD board and the sitemap, and ERD Editor for the ERD. Both are MIT-licensed packages that the server can serve itself, and both have a read-only mode, for a phone. Excalidraw elements carry data of their own, where the trace IDs go, and new projects already use ERD Editor for stage 05. Phase ① draws with them read-only, so phase ② turns editing on. The rules of `nexus/` then allow the editors' packages in the page, and Excalidraw brings React | draw.io for all three: one editor, under the Apache License 2.0, but its embed mode is supported only on its own site, so pictures would load code from elsewhere, against REQ-147; decide at the start of phase ② after a trial: no commitment now, but phase ① needs drawing code of its own | decided 2026-10-25 |
| D12 | How the stage records in Git meet the status files of phase 1 | The stage records move into the project's repository: the agent writes them in its pull requests and the hub reads them, so every device, cloud session and the server see the same records. A status file is read only while a project has no records in its repository, with a check that says they should move, and the hub writes no new ones | Keep both: the status file on its device and the repository elsewhere, so the two can disagree; keep the status files only: against checkpoint 3, which put the stage state in Git, and a cloud session loses them | decided 2026-10-25 |
| D13 | What the next release holds | Phase ①: the three pictures, each drawn once a project has its stage source; cross-checking; comments, proposals and decisions; the stage overview and the agent to-do. Editing (phase ②) and tool links (phase ③) come after it. This repository is the first project: it has DDD boards now, and its ERD and sitemap come with its stages 05 and 07 | The DDD board only: a smaller release, but cross-checking waits for a second picture; phases ① and ② together: one release fewer, but a larger one, and the editor has to be tried first | decided 2026-10-25 |

Replaced, with their IDs kept:

| ID | Question | Status | Why |
| --- | --- | --- | --- |
| D5 | What this release adds | replaced 2026-10-24 | The plan in stages and the board answer it; D13 asks what the next release holds |
| D6 | Where progress is kept | replaced 2026-10-24 | Checkpoint 3 put the stage state in Git; D12 asks how that meets the status files |
| D7 | How the server's hub stays current | replaced 2026-10-24 | It is part of hotspot 2, which D8 asks |

## Requirements

Priorities: Must, Should, Could. Status: `active`, `built` (in phase 1 already) or `removed`, with its date. The rows that said `open (Dn)` became `active` when D8 to D13 were decided on 2026-10-25. Rows for phases ② and ③ start with "Where editing is included" or "Where tool links are included".

| ID | Requirement | Type | Priority | Context | Source | Status |
| --- | --- | --- | --- | --- | --- | --- |
| REQ-066 | The hub shall read only the projects in the project list. | functional | Must | CTX-006 | Problem 5 | built |
| REQ-067 | If a project's settings give a name other than its registered name, or an unregistered folder gives a registered name, then the hub shall read nothing for that project and say why. | functional | Must | CTX-006 | Review of the hub, 2026-10-24 (a repository's settings could save items under another project's name) | built |
| REQ-068 | The hub shall read stage sources as text, without running a project's code, Git hooks or Git filters. | non-functional | Must | CTX-006 | Review of the hub, 2026-10-24 | built |
| REQ-069 | The hub shall never write into a project's repository. | functional | Must | CTX-006 | Design draft 2026-10-23 | built |
| REQ-070 | When the hub reads a project, the hub shall save a snapshot of the items, links and checks that the project's stage sources define. | functional | Must | CTX-006 | Problems 1 and 2 | built |
| REQ-071 | The hub shall count an ID as defined only in the stage that creates its kind, and as a mention anywhere else. | functional | Must | CTX-006 | Stage contract | built |
| REQ-072 | The hub shall read each stage source from the checkout of the repository that the source names. | functional | Must | CTX-006 | Problem 1 | built |
| REQ-073 | If a stage is not read, then the hub shall say why: no text source, a missing source, no checkout, or settings that need a fix. | functional | Should | CTX-006 | Phase 1 | built |
| REQ-074 | The hub shall skip files whose names, or whose folders' names, look like secrets, also when a link leads to them. | functional | Must | CTX-006 | Problem 5 | built |
| REQ-075 | In a folder source, the hub shall skip a translation that defines only the IDs of its original. | functional | Must | CTX-006 | Hub change of 2026-10-24, before a second part of this project added its stage files | built |
| REQ-076 | The snapshot shall hold no file contents other than IDs, titles, the status, type, priority and link fields, and the parts of the stage sources that pictures show. | non-functional | Must | CTX-006 | Problem 5; decision D8 (pictures need their content) | active |
| REQ-077 | The snapshot shall hold no local paths. | non-functional | Must | CTX-006 | Problem 5 | built |
| REQ-078 | The hub shall replace secrets and email addresses in titles and fields with `[redacted]`. | functional | Must | CTX-006 | Problem 5 | built |
| REQ-079 | If a link holds a secret or an email address, then the hub shall leave the link out of the snapshot. | functional | Must | CTX-006 | Review of the hub, 2026-10-24 | built |
| REQ-080 | When stage sources break a check rule, the hub shall add a check with its level and the IDs concerned. | functional | Must | CTX-006 | Problem 2 | built |
| REQ-081 | If a snapshot would exceed 1,000,000 bytes, 3,000 items or 2,000 checks, then the hub shall cut it and add a check that says how much was kept. | functional | Should | CTX-006 | Phase 1 (the server's size limit) | built |
| REQ-082 | The hub shall need nothing but Python 3.8 or later with its standard library, and Git where it is installed. | non-functional | Must | none | Phase 1 | built |
| REQ-083 | The hub shall run on Linux, macOS and Windows. | non-functional | Must | none | Repository goal; only Linux has been run so far | active |
| REQ-084 | The hub shall show a stage's state only as it was recorded, never as inferred from the files. | functional | Must | CTX-007 | Problem 3 | built |
| REQ-085 | If a stage record says `done` without a checkpoint and its date, then the hub shall show the stage as `in_progress`, with a check that names what is missing. | functional | Must | CTX-007 | Stage contract; decision D12 | active |
| REQ-086 | When a stage's work ends or its checkpoint is passed, the stage skills shall have the agent write the stage's record into the project's repository. | functional | Must | CTX-007 | Problem 3; board checkpoint 3 (the agent writes the stage state to Git); decision D12 | active |
| REQ-087 | When a stage record holds a review finding, the hub shall add it to the stage's checks with its level and IDs. | functional | Should | CTX-007 | Phase 1 (the checks find structure, not meaning); decision D12 | active |
| REQ-089 | The hub shall show the same recorded progress of a project on every device and on the server. | functional | Must | CTX-007 | Problems 3 and 4; decision D12 | active |
| REQ-090 | When a checkpoint is recorded, the hub shall keep a reference to the record that holds the user's approval. | functional | Should | CTX-007 | Problem 3; the maintainer's working rules (decisions stay in the records and are linked) | active |
| REQ-091 | The hub page shall show every registered project with its 13 stages, their states, their item counts and their checks. | functional | Must | CTX-008 | Problem 1 | built |
| REQ-092 | The hub page shall show each project's current stage and next action before its stages. | functional | Must | CTX-008 | Problem 1 | built |
| REQ-093 | When a viewer selects an ID, the hub page shall show what the item comes from and what it leads to, through all stages. | functional | Must | CTX-008 | Problem 2 | built |
| REQ-094 | When a viewer searches for an ID or words of a title, the hub page shall list the matching items. | functional | Should | CTX-008 | Phase 1 | built |
| REQ-095 | Where the project settings give a link for a stage's human view, the hub page shall link the stage to it. | functional | Should | CTX-008 | Design draft 2026-10-23 (link to existing tools) | built |
| REQ-096 | The hub page shall show when each snapshot was made and from which commit. | functional | Should | CTX-008 | Phase 1 | built |
| REQ-097 | The hub page shall load nothing from the network. | non-functional | Must | CTX-008 | Problem 5 | built |
| REQ-098 | The hub page shall show text from the projects only as text. | non-functional | Must | CTX-008 | Problem 5 | built |
| REQ-099 | The hub page shall follow the profile's language, Korean or English. | functional | Should | CTX-008 | Phase 1 | built |
| REQ-100 | The hub page shall follow the system's light or dark mode. | functional | Could | CTX-008 | Phase 1 | built |
| REQ-101 | The hub page shall work at every width from 320 to 1440 pixels without sideways scrolling. | non-functional | Must | CTX-008 | Problem 4 | built |
| REQ-102 | While the NEXUS server holds no snapshot, the hub page shall say what the hub shows and how a project gets pushed to it. | functional | Must | CTX-008 | Problem 7; the maintainer's questions of 2026-10-24 | active |
| REQ-103 | While a project has no recorded progress, the hub page shall say how progress gets recorded. | functional | Should | CTX-008 | Phase 1 | built |
| REQ-104 | The hub page shall leave off the saved snapshots of projects that are no longer in the project list. | functional | Should | CTX-008 | Phase 1 | built |
| REQ-105 | The hub shall send nothing off the device except pushes, removals and what the agent writes to the NEXUS server. | functional | Must | CTX-009 | Problem 5; decision D9 | active |
| REQ-106 | The hub shall push only the projects in the push list. | functional | Must | CTX-009 | Problem 5 | built |
| REQ-107 | Before the first push of a project, the hub skill shall have the agent ask the user. | functional | Must | CTX-009 | Phase 1 | built |
| REQ-108 | Before a push, the hub skill shall have the agent show a dry run. | functional | Should | CTX-009 | Phase 1 | built |
| REQ-109 | The hub shall read the service token only from environment variables. | non-functional | Must | CTX-009 | Repository rules | built |
| REQ-110 | The hub shall never write the service token to a file, a log or a message. | non-functional | Must | CTX-009 | Repository rules | built |
| REQ-111 | If a push is answered with a redirect, then the hub shall report a refused token instead of following the redirect. | functional | Must | CTX-009 | Phase 1 (Cloudflare Access answers a refused token with its sign-in page) | built |
| REQ-112 | If the server refuses a snapshot, then the hub shall show the server's reason. | functional | Should | CTX-009 | Phase 1 | built |
| REQ-113 | The NEXUS server shall answer only requests that Cloudflare Access checked. | non-functional | Must | CTX-009 | Design draft 2026-10-23 | built |
| REQ-114 | The NEXUS server shall answer only at the address that the user set, with no `workers.dev` or preview addresses. | non-functional | Must | CTX-009 | Design draft 2026-10-23 | built |
| REQ-115 | When a snapshot arrives, the NEXUS server shall store it only if it is in the snapshot format and newer than the one it holds. | functional | Must | CTX-009 | Phase 1 | built |
| REQ-116 | The NEXUS server shall hold at most 30 projects, each in a snapshot of at most 1 MiB. | non-functional | Should | CTX-009 | Phase 1 (Workers CPU limit on the free plan) | built |
| REQ-117 | If a browser sends a change from another site, then the NEXUS server shall refuse it. | functional | Must | CTX-009 | Phase 1 | built |
| REQ-118 | The NEXUS server shall keep nothing but the pushed snapshots and what the project spaces hold: pictures, comments, proposals, edits, positions and passed checkpoints. | non-functional | Must | CTX-009 | Design draft 2026-10-23; board checkpoints 1 to 3 (discussion and positions stay in NEXUS) | active |
| REQ-119 | The NEXUS server shall log no stored text. | non-functional | Must | CTX-009 | Problem 5 | built |
| REQ-120 | When the user removes a project, the NEXUS server shall delete its snapshot and its project space. | functional | Must | CTX-009 | Phase 1; board checkpoint 1 | active |
| REQ-121 | The NEXUS server shall run no AI model. | non-functional | Must | CTX-009 | Design draft 2026-10-23 (judgement stays with the agents on the devices) | built |
| REQ-122 | The NEXUS server shall hold no rights on any repository. | non-functional | Must | CTX-009 | Design draft 2026-10-23 | built |
| REQ-123 | The NEXUS server shall keep its database code in one module, so that another database can replace D1. | non-functional | Should | CTX-009 | Decision 2026-10-23 | built |
| REQ-124 | The NEXUS server shall stay within the free plans of Cloudflare Workers, D1 and Access for one person's projects. | non-functional | Should | CTX-009 | Design draft 2026-10-23 (an estimate, not measured) | active |
| REQ-125 | While a project is in the push list, when a stage's work is merged or its checkpoint is recorded, the hub skill shall have the agent push the project's new snapshot. | functional | Should | CTX-009 | Problem 4; decision D8 | active |
| REQ-126 | The server's guide shall let a person deploy their own NEXUS server on their own Cloudflare account and domain. | non-functional | Should | CTX-009 | Design draft 2026-10-23 (a version for everyone); deployment of 2026-10-24 | built |
| REQ-127 | Where editing is included, the picture view shall let the user edit a picture on a PC with the open-source editor. | functional | Could | CTX-010 | Problem 6; board checkpoint 1 (editing on a PC first); decision D11 | active |
| REQ-128 | The NEXUS server shall accept a change to a picture from the agent only as a proposal with its reason. | functional | Must | CTX-014 | Design draft 2026-10-23; board step 9 (CTX-014) | active |
| REQ-129 | If a request to accept or dismiss a proposal does not come from the user, then the NEXUS server shall refuse it. | functional | Must | CTX-014 | Design draft 2026-10-23; board step 9 (only the user accepts or dismisses a proposal) | active |
| REQ-130 | Where editing is included, if an edit is based on a document version that is no longer the latest, then the picture view shall show the edit over the new picture as an edit conflict for the user to choose. | functional | Could | CTX-010 | Design draft 2026-10-23; hotspot 9 (checkpoint 2) | active |
| REQ-131 | When the agent starts its work on a project, the stage skills shall have the agent reflect each pending reflection in the stage sources by pull request. | functional | Must | CTX-010 | Design draft 2026-10-23; hotspot 10 (checkpoint 2) | active |
| REQ-136 | When a project's first snapshot is stored, the NEXUS server shall create the project's space, bound to the repository that holds the project's settings. | functional | Must | CTX-012 | Board step 9 (CTX-012 aggregate rules); hotspot 1 (checkpoint 2) | active |
| REQ-137 | When a stored snapshot changes the stage source of a picture, NEXUS shall draw the picture again. | functional | Must | CTX-012 | Board policy: when Stage source changed, Draw picture | active |
| REQ-138 | NEXUS shall draw the content of every picture only from the stage sources. | functional | Must | CTX-012 | Problem 9; board checkpoint 1 (the pictures come from the stage sources in Git) | active |
| REQ-139 | The picture view shall show the document version that a picture was drawn from, with its commit and the commit's time. | functional | Should | CTX-012 | Problem 9; board step 9 (one picture for each document version) | active |
| REQ-140 | The DDD board that NEXUS draws from the stage 01 source shall show each context with its command rows, policies, dependencies and hotspots. | functional | Must | CTX-012 | Problem 8; board checkpoint 1 (the DDD board, the ERD and the sitemap first) | active |
| REQ-141 | The ERD that NEXUS draws from the stage 05 source shall show the tables with their columns, keys and relations. | functional | Must | CTX-012 | Board checkpoint 1 | active |
| REQ-142 | The sitemap that NEXUS draws from the stage 07 source shall show each screen as a box with its ID, name, path and who can see it, and an arrow from each parent to each child. | functional | Must | CTX-012 | Board checkpoint 1; stage 07's board view | active |
| REQ-143 | NEXUS shall lay out each picture automatically. | functional | Must | CTX-012 | Hotspot 3 (checkpoint 2) | active |
| REQ-144 | If a project's pictured stage sources are in more than one repository, then NEXUS shall draw only those in the space's repository, naming the ones that it left out. | functional | Could | CTX-012 | Hotspot 1 (checkpoint 2: one repository for each space at first) | active |
| REQ-145 | The picture view shall show a picture with its open comments, proposals and discrepancies on the items that they concern. | functional | Must | CTX-012 | Board step 8-a (read model Picture view) | active |
| REQ-146 | The picture view shall work at every width from 320 to 1440 pixels without sideways scrolling of the page. | non-functional | Must | CTX-012 | Board checkpoint 1 (viewing on a phone too) | active |
| REQ-147 | The picture view shall load its code, styles and fonts only from the NEXUS server. | non-functional | Must | CTX-012 | Problem 5 | active |
| REQ-148 | The picture view shall show text from the projects and from comments only as text. | non-functional | Must | CTX-012 | Problem 5 | active |
| REQ-149 | The picture view shall draw a picture of up to 300 elements within 3 seconds at the 95th percentile of 20 openings, with one viewer on the NEXUS server, timed by the page from its request to the drawn picture in Chrome's mobile emulation with 4G throttling. | non-functional | Should | CTX-012 | Board checkpoint 1 (viewing on a phone too) | active |
| REQ-150 | The picture view shall follow the profile's language, Korean or English. | functional | Should | CTX-012 | Phase 1 (as the hub page does) | active |
| REQ-151 | When a picture is drawn or drawn again, NEXUS shall cross-check the pairs between it and the project's other pictures. | functional | Must | CTX-013 | Board policies: when Picture drawn or Picture redrawn, Cross-check pictures | active |
| REQ-152 | NEXUS shall pair each aggregate on the DDD board with the ERD tables that name its glossary term. | functional | Must | CTX-013 | Hotspot 4; decision D10 | active |
| REQ-153 | NEXUS shall pair each read model on the DDD board with the sitemap screens that name its glossary term. | functional | Should | CTX-013 | Hotspot 4; decision D10 | active |
| REQ-154 | The stage 05 and stage 07 skills shall have the agent name, for each table and each screen, the glossary terms of the aggregates or read models that it stands for. | functional | Must | CTX-013 | Hotspot 4; decision D10 | active |
| REQ-155 | When a cross-check finds a pair that disagrees, or an item whose pair is missing, such as an ERD table with no matching aggregate, NEXUS shall open a discrepancy with the IDs concerned. | functional | Must | CTX-013 | Problem 10; board step 9 (CTX-013) | active |
| REQ-156 | NEXUS shall keep at most one open discrepancy for each pair. | functional | Must | CTX-013 | Board step 9 (CTX-013 aggregate rules) | active |
| REQ-157 | When a cross-check no longer finds an open discrepancy, NEXUS shall mark the discrepancy resolved. | functional | Must | CTX-013 | Board step 9 (CTX-013 aggregate rules) | active |
| REQ-158 | The picture view shall let the user leave a comment on an item of a picture, on a phone as on a PC. | functional | Must | CTX-014 | Problem 8; board checkpoint 1 (discussion in comments); hotspot 5 | active |
| REQ-159 | The picture view shall let the user accept or dismiss a proposal. | functional | Must | CTX-014 | Board step 9 (CTX-014: only the user accepts or dismisses a proposal) | active |
| REQ-160 | When the user or the agent leaves a comment, NEXUS shall attach it to the item's trace ID, not to a position. | functional | Must | CTX-014 | Board step 9 (CTX-014 aggregate rules) | active |
| REQ-161 | When a comment is left on a part of a picture that has no trace ID of its own, such as an event on the DDD board, NEXUS shall attach the comment, with a quote of the part, to the item that holds the part. | functional | Should | CTX-014 | Board step 9 (a picture's nodes are items, TERM-085) | active |
| REQ-162 | If a commented item is no longer in its picture after a redraw, then the picture view shall show the comment apart, still open, with the item's ID. | functional | Should | CTX-014 | Board step 9 (a comment follows its item) | active |
| REQ-163 | The NEXUS server shall mark each comment and proposal with its author, the user or the agent, from the kind of Cloudflare Access sign-in that the request carries. | functional | Must | CTX-014 | Board checkpoint 1 (the user and the AI first) | active |
| REQ-164 | When the agent records a decision on a comment, the NEXUS server shall keep with it a link to where the decision was written. | functional | Must | CTX-014 | Hotspot 7 (checkpoint 2) | active |
| REQ-165 | When a decision is recorded on a comment, NEXUS shall close the comment. | functional | Must | CTX-014 | Board policy: when Decision recorded, Close comment | active |
| REQ-166 | When the user or the agent marks a comment as answered, NEXUS shall close the comment. | functional | Should | CTX-014 | Board step 9 (a comment closes when it is answered) | active |
| REQ-167 | When the user settles a comment, the stage skills shall have the agent write the decision where the project's rules put it: changes to the stage sources by pull request, and the user's choices in the project's records. | functional | Must | CTX-014 | Hotspot 7 (checkpoint 2) | active |
| REQ-168 | When the discussion of a comment continues in a session, the stage skills shall have the agent record its outcome on the comment. | functional | Should | CTX-014 | Board checkpoint 1 (long talks happen in the conversation) | active |
| REQ-169 | When the user accepts a proposal, NEXUS shall record the edit that it proposes as a pending reflection. | functional | Must | CTX-010 | Board policy: when Proposal accepted, Edit picture as proposed | active |
| REQ-170 | When the agent reports that a pending reflection is merged into the stage sources, the NEXUS server shall close the edit with a link to its pull request. | functional | Must | CTX-010 | Board step 9 (an edit closes once it is in the stage sources); decision D9 | active |
| REQ-171 | Where editing is included, the picture view shall keep pictures read-only at widths under 1024 pixels. | functional | Could | CTX-010 | Board checkpoint 1 (editing on a PC first) | active |
| REQ-172 | Where editing is included, when the user moves an element of a picture, NEXUS shall keep the new position in the project space without changing the stage sources. | functional | Could | CTX-010 | Hotspot 3 (checkpoint 2) | active |
| REQ-173 | The hub shall read each stage's record from the project's repository. | functional | Must | CTX-007 | Board checkpoint 3 (the agent writes the stage state to Git); decision D12 | active |
| REQ-174 | While a project has no stage records in its repository, the hub shall read them from the device's status file. | functional | Should | CTX-007 | Decision D12 | active |
| REQ-175 | While the hub reads a project's stage records from a status file, the hub shall add a check that says they should move to the repository. | functional | Should | CTX-007 | Decision D12 | active |
| REQ-176 | The stage overview shall show a stage's open discrepancies, open comments and pending reflections together. | functional | Must | CTX-007 | Board step 8-a (read model Stage overview); hotspot 11 | active |
| REQ-177 | While a stage has open discrepancies, comments or pending reflections, the stage overview shall still let the user pass its checkpoint. | functional | Should | CTX-007 | Hotspot 11 (checkpoint 2: the user decides) | active |
| REQ-178 | When the user passes a checkpoint in NEXUS, the NEXUS server shall record who passed it and when. | functional | Must | CTX-007 | Board step 9 (CTX-007) | active |
| REQ-179 | If a request to pass a checkpoint does not come from the user, then the NEXUS server shall refuse it. | functional | Must | CTX-007 | Board step 9 (only the user passes a checkpoint) | active |
| REQ-180 | The agent to-do shall list each checkpoint passed in NEXUS that the stage's record in the repository does not hold yet. | functional | Must | CTX-007 | Board checkpoint 3 (the agent writes the stage state to Git); decision D12 | active |
| REQ-181 | When the agent starts its work on a project, the stage skills shall have the agent read the project's agent to-do. | functional | Must | CTX-007 | Problem 11; hotspot 6 (checkpoint 2) | active |
| REQ-182 | The agent to-do shall list the open comments first, then the open discrepancies, then the pending reflections. | functional | Should | CTX-007 | Hotspot 6 (checkpoint 2: open comments first) | active |
| REQ-183 | The hub shall read the agent to-do from the NEXUS server with the service token. | functional | Must | CTX-007 | Hotspot 13; decision D9 | active |
| REQ-184 | The hub shall send what the agent writes, its comments, proposals, decisions and reports of reflections, to the NEXUS server with the service token. | functional | Must | CTX-014 | Hotspot 13; decision D9 | active |
| REQ-185 | If the hub cannot reach the NEXUS server for the agent to-do, then the hub shall say so without stopping the agent's work. | functional | Should | CTX-007 | Hotspot 13; decision D9 | active |
| REQ-186 | Where tool links are included, NEXUS shall let the user or the agent link an item to a Notion record or a Jira work item. | functional | Could | CTX-015 | Problem 12; board checkpoint 1 (linked, not moved) | active |
| REQ-187 | Where tool links are included, the picture view shall show the state of each linked record or work item next to its item. | functional | Could | CTX-015 | Board checkpoint 1 | active |
| REQ-188 | Where tool links are included, NEXUS shall never change a Notion record or a Jira work item. | functional | Could | CTX-015 | Board checkpoint 1 (each tool stays the source) | active |
| REQ-189 | The hub page that the NEXUS server serves shall link each stage that has a picture to its picture view. | functional | Should | CTX-008 | Stage 01, "Stage 02 also settles" (how the hub page leads to the pictures) | active |
| REQ-190 | The hub page that the NEXUS server serves shall show, for each project, how many comments, proposals and discrepancies are open. | functional | Should | CTX-008 | Board checkpoint 1 (viewing on a phone too); CTX-008's open question (the first screen on a phone) | active |
| REQ-191 | The hub shall replace secrets and email addresses in the parts of the stage sources that pictures show with `[redacted]`. | functional | Must | CTX-006 | Problem 5; decision D8 | active |
| REQ-192 | If the parts of the stage sources that pictures show would make a snapshot exceed its size limit, then the hub shall leave out whole pictures, with a check that names them. | functional | Should | CTX-006 | Phase 1 (the server's size limit); decision D8 | active |
| REQ-193 | While a project in the push list has a stage source newer than its pushed snapshot, when the agent starts its work on the project, the hub skill shall have the agent push the project's snapshot. | functional | Should | CTX-009 | Problem 4; hotspot 2; decision D8 | active |

Removed, with their IDs kept:

| ID | Requirement | Status | Why |
| --- | --- | --- | --- |
| REQ-088 | When the hub changes recorded progress, the hub shall keep the previous record as a backup. | removed 2026-10-24 | Under D12 the hub writes no progress, and Git keeps the earlier records. It comes back if D12 changes |
| REQ-132 | If an imported change belongs to a team project, then the agent shall not commit it straight to the project's repositories. | removed 2026-10-24 | Every reflection goes by pull request (REQ-131), in team projects too |
| REQ-133 | Where assistant access is included, the NEXUS server shall offer an MCP server that reads the same data as the hub page. | removed 2026-10-24 | Removed with CTX-011 at checkpoint 3 |
| REQ-134 | Where assistant access is included, the MCP server shall answer only chat clients that signed in through Cloudflare Access. | removed 2026-10-24 | As for REQ-133 |
| REQ-135 | Where assistant access is included, the MCP server shall show a project's stages as an in-chat view in chat clients that support MCP Apps. | removed 2026-10-24 | As for REQ-133 |

Changed with the board on 2026-10-24: REQ-076, REQ-085 to REQ-087, REQ-105, REQ-118, REQ-120 and REQ-127 to REQ-131 have new wording under the same IDs; REQ-089 and REQ-125 depend on D12 and D8 instead of D6 and D7; REQ-136 to REQ-193 are new.

## Success measures

For a two-week trial of phase ① with this repository on NEXUS:

| Measure | Target | How it is measured |
| --- | --- | --- |
| Talking over pictures | The maintainer settles questions about this repository's pictures with the agent through comments, without describing a picture in words | The maintainer's note at the end of the trial |
| Comments reach the agent | Every comment that the maintainer leaves is answered at the agent's next work on the project | Comment times against the times of the agent's answers and its session starts |
| Pictures current | A picture shows a merged stage source within a day of the merge | The pictures' document versions against merge times |
| Useful discrepancies | At most one discrepancy in three is a false lead, once the repository has a second picture | The maintainer's sample of the discrepancies raised |
| Same everywhere | No stage shows different records on two devices or on the server | Stage records read on different devices and on the server, compared |
| Nothing leaks | No pushed data holds a secret, an email address or a local path | Code check over the pushed data |
| Cost | The server stays on the free plans | Cloudflare's usage pages |

## For the checkpoint

Passed on 2026-10-25: the maintainer approved the scope and the recommendations of D8 to D13, without changes. The checkpoint covered:

1. Decisions D8 to D13 above.
2. What the server holds from now on: besides the snapshots, the parts of the stage sources that pictures show, such as the contexts, commands and policies of the DDD board, the tables and columns of the ERD and the screens of the sitemap, and the comments, proposals and decisions. It stays behind Cloudflare Access, and the hub redacts secrets and email addresses first (REQ-076, REQ-118, REQ-191).
3. The rows that the board changed and removed, listed under the requirements, and D5 to D7, replaced by D8, D12 and D13.
4. What is never built, at the end of the scope.
5. Building starts after the memory plugin. The first project is this repository, and its first push waits for the maintainer's go-ahead (REQ-107).

Conflicts, duplicates and open questions:

- Conflicts: REQ-076, REQ-105 and REQ-118 kept everything but snapshots off the server, and the pictures and the discussion need more, so they change under D8 and D9. REQ-088 had the hub write progress, which D12 ends, so it is removed. Under D12, REQ-069 still holds: the agent writes the stage records into the repository, and the hub only reads them.
- Duplicates: REQ-132 says what REQ-131 now says for every project, so it is removed. No other requirement repeats or contradicts another.
- Open questions, for later stages:
  - With what permissions NEXUS reads the state of Notion records and Jira work items (hotspot 12): decided when the links are built, in phase ③.
  - What disagreeing means for each pair, and how serious each discrepancy is: the functional spec settles it in stage 04.
  - From the draft, under CTX-006, CTX-008 and CTX-009: whether the hub reads a stage whose truth is a human view, such as a Notion database, from that tool, and results that are not stage sources, such as test runs or the state of tasks; which summaries of single stages the hub page shows, whether it shows what changed since the last visit, and memory's state of each project; whether the server keeps earlier snapshots, and how Cloudflare Access tells team members' projects apart. None of them is in this release. The first screen on a phone and the empty server are answered by REQ-190 and REQ-102, and an edit keeps the commit that it was based on, so edit conflicts need no earlier snapshot.
