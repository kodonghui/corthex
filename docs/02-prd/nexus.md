# NEXUS: requirements

[한국어](nexus.ko.md)

Stage 02 of CORTHEX's own project, for NEXUS: the `corthex-nexus` plugin and the NEXUS server. Status: draft of 2026-10-24, for the maintainer's scope check (the stage's first checkpoint). The rows marked `built` describe phase 1 as it runs now, in `corthex-nexus` 0.1.0 and the server deployed on 2026-10-24; later stages keep them unless the maintainer changes them. When this file and its Korean translation differ, this file is the source.

Inputs: the contexts and the glossary in [docs/01-domain/nexus.md](../01-domain/nexus.md) (CTX-006 to CTX-011, TERM-047 to TERM-097), with the shared terms of [docs/01-domain/memory.md](../01-domain/memory.md). Words in this file have the meanings given there.

## Goal

Let the user see on one page, on any device, where each of their projects stands in the 13 stages and whether the stages connect, from the sources that the projects already have; and build a tool for a stage only where the stage needs one and no existing tool does the job.

## Problems

The maintainer's goal, the design draft and the first use of the deployed hub show these problems. Each requirement below names the problem or the decision it comes from.

1. A project's stage work sits in several repositories and tools, so seeing where every project stands means opening each of them or asking an agent.
2. Whether the stages connect, for example whether every Must requirement has a spec, is hard to see by hand.
3. A file that exists is not a finished stage, and the state of each stage is written in different places: in chats, in the records and in the hub's status files.
4. The user works from several devices, among them a phone and cloud sessions whose files are lost when they end, and needs the same page on each.
5. Project material must not leak through the hub: file contents, secrets, and protected data such as answer keys or student records.
6. Some stages, such as the sitemap and the user flows, have no tool where people and agents change the same diagram of trace items.
7. The deployed hub first showed no project at all, and did not say what it does or how a project gets onto it.

## Scope

This release, NEXUS 0.2, as decision D5 recommends: keep phase 1 and make the hub useful for real work before anything new is built.

- In: reading the stage sources into snapshots and checks (CTX-006); progress that is the same on every device (CTX-007, D6); the hub page with the trace view and search, on a device and on the server, which explains itself while it is empty (CTX-008); the user's own server behind Cloudflare Access, kept current after stage work (CTX-009, D7); this repository as the first real project on the hub.
- Out of this release: structure editing (CTX-010) and assistant access (CTX-011), which come back with the first project that needs them (D5); reading human views through their APIs; projects that other people may see; earlier snapshots kept on the server; serving as memory's sync remote (memory's decision D3).
- Never built: a free canvas, since Miro and Excalidraw exist; an ERD editor, since new projects use ERD Editor; mockup or presentation tools; AI inside the server; writes straight into a team project's repositories.
- Projects with protected data, such as answer keys or student records, and team projects whose members have not agreed, are not pushed.

## Decisions in force

| When | Decision | Affects |
| --- | --- | --- |
| 2026-10-23 | Start with the hub (phase 1) and decide each next phase on its own. Stage sources stay where they are; only snapshots go to the server. | REQ-070, REQ-105, REQ-118 |
| 2026-10-23 | Phase 1 uses Cloudflare D1, with all database code in one module, so that Postgres can replace it if that is needed later. | REQ-123 |
| 2026-10-24 | The server runs at the maintainer's own address behind Cloudflare Access. It was deployed and checked the same day. | REQ-113, REQ-114 |
| 2026-10-24 | NEXUS builds no ERD editor. New projects use ERD Editor, and the hub reads the table comments that it writes. | Scope |
| 2026-10-24 | NEXUS is defined again from stage 01 with the harness, keeping phase 1 as material. | This file |
| 2026-10-24 | Work goes to the harness itself and leaves the progress of other projects out. | Scope, success measures |

The maintainer's own words and where they were said are in the maintainer's records, not in this repository.

## Open decisions

This file assumes the recommendations. The requirements whose status says `open` depend on the decision named. D1 to D4 are memory's decisions, in [memory.md](memory.md#open-decisions).

| ID | Question | Recommendation | Other choices |
| --- | --- | --- | --- |
| D5 | What this release adds | Make the hub useful first: keep phase 1, fix what its first use showed, keep progress and the server current (D6, D7), and put this repository on it. Structure editing and assistant access wait for the first project that needs them | Structure editing now: the editors of phase 2, although no current project has a sitemap or flows to edit; assistant access now: an MCP server for chat clients, whose sign-in through Cloudflare Access is not yet tested; nothing more: phase 1 stays as it is |
| D6 | Where progress is kept | In the project's repository, beside the stage sources: the stage skills write each stage's state, its date, the next action and where the approval is recorded, and the hub reads them. Git carries them to every device, cloud session and CI run. A public repository names the record without a private link. In a team project, the team agrees first | On the NEXUS server, recorded from the page or by agents: needs the server and a sign-in for every record, and a device's own page shows only its own records; on each device, as now: a cloud session starts empty and devices disagree; in the project's records, such as Notion: one place that people already read, but every device needs a connection and a key for the records |
| D7 | How the server's hub stays current | The agent pushes after each stage's work and each checkpoint, for the projects in the push list: it works for projects of any shape and needs no new secret | A CI job pushes after each merge: always current, but needs the service token as a secret in each repository and sees only that repository; on request only, as now |

## Requirements

Priorities: Must, Should, Could. Status: `active`, `built` (in phase 1 already), or `open (Dn)`.

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
| REQ-076 | The snapshot shall hold no file contents other than IDs, titles and the status, type, priority and link fields. | non-functional | Must | CTX-006 | Problem 5 | built |
| REQ-077 | The snapshot shall hold no local paths. | non-functional | Must | CTX-006 | Problem 5 | built |
| REQ-078 | The hub shall replace secrets and email addresses in titles and fields with `[redacted]`. | functional | Must | CTX-006 | Problem 5 | built |
| REQ-079 | If a link holds a secret or an email address, then the hub shall leave the link out of the snapshot. | functional | Must | CTX-006 | Review of the hub, 2026-10-24 | built |
| REQ-080 | When stage sources break a check rule, the hub shall add a check with its level and the IDs concerned. | functional | Must | CTX-006 | Problem 2 | built |
| REQ-081 | If a snapshot would exceed 1,000,000 bytes, 3,000 items or 2,000 checks, then the hub shall cut it and add a check that says how much was kept. | functional | Should | CTX-006 | Phase 1 (the server's size limit) | built |
| REQ-082 | The hub shall need nothing but Python 3.8 or later with its standard library, and Git where it is installed. | non-functional | Must | none | Phase 1 | built |
| REQ-083 | The hub shall run on Linux, macOS and Windows. | non-functional | Must | none | Repository goal; only Linux has been run so far | active |
| REQ-084 | The hub shall show a stage's state only as it was recorded, never as inferred from the files. | functional | Must | CTX-007 | Problem 3 | built |
| REQ-085 | If `done` is recorded for a stage without a checkpoint and its date, then the hub shall refuse the record. | functional | Must | CTX-007 | Stage contract | built |
| REQ-086 | Where the hub is installed, when a stage's work ends or its checkpoint is passed, the stage skills shall have the agent record the stage's state in the hub. | functional | Must | CTX-007 | Problem 3 | built |
| REQ-087 | When a person or an agent records a review finding, the hub shall add it to the stage's checks with its level and IDs. | functional | Should | CTX-007 | Phase 1 (the checks find structure, not meaning) | built |
| REQ-088 | When the hub changes recorded progress, the hub shall keep the previous record as a backup. | non-functional | Must | CTX-007 | Repository rules (owned writes need a backup and a restore path) | built |
| REQ-089 | The hub shall show the same recorded progress of a project on every device and on the server. | functional | Must | CTX-007 | Problems 3 and 4; decision D6 | open (D6) |
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
| REQ-105 | The hub shall send nothing off the device unless the user runs a push or a removal. | functional | Must | CTX-009 | Problem 5 | built |
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
| REQ-118 | The NEXUS server shall keep nothing but the pushed snapshots. | non-functional | Must | CTX-009 | Design draft 2026-10-23 | built |
| REQ-119 | The NEXUS server shall log no stored text. | non-functional | Must | CTX-009 | Problem 5 | built |
| REQ-120 | When the user removes a project, the NEXUS server shall delete its snapshot. | functional | Must | CTX-009 | Phase 1 | built |
| REQ-121 | The NEXUS server shall run no AI model. | non-functional | Must | CTX-009 | Design draft 2026-10-23 (judgement stays with the agents on the devices) | built |
| REQ-122 | The NEXUS server shall hold no rights on any repository. | non-functional | Must | CTX-009 | Design draft 2026-10-23 | built |
| REQ-123 | The NEXUS server shall keep its database code in one module, so that another database can replace D1. | non-functional | Should | CTX-009 | Decision 2026-10-23 | built |
| REQ-124 | The NEXUS server shall stay within the free plans of Cloudflare Workers, D1 and Access for one person's projects. | non-functional | Should | CTX-009 | Design draft 2026-10-23 (an estimate, not measured) | active |
| REQ-125 | While a project is in the push list, when a stage's work is merged or its checkpoint is recorded, the hub skill shall have the agent push the project's new snapshot. | functional | Should | CTX-009 | Problem 4; decision D7 | open (D7) |
| REQ-126 | The server's guide shall let a person deploy their own NEXUS server on their own Cloudflare account and domain. | non-functional | Should | CTX-009 | Design draft 2026-10-23 (a version for everyone); deployment of 2026-10-24 | built |
| REQ-127 | Where structure editing is included, the hub page shall let the user edit a structure diagram on its user board. | functional | Could | CTX-010 | Problem 6; design draft 2026-10-23 | open (D5) |
| REQ-128 | Where structure editing is included, the NEXUS server shall accept changes from agents only on the proposal board, each with its reason. | functional | Could | CTX-010 | Design draft 2026-10-23 | open (D5) |
| REQ-129 | Where structure editing is included, the NEXUS server shall move a proposal to the user board only when the user imports it. | functional | Could | CTX-010 | Design draft 2026-10-23 | open (D5) |
| REQ-130 | If an edit of a board is based on a board revision that is not the latest, then the NEXUS server shall refuse the edit as an edit conflict. | functional | Could | CTX-010 | Design draft 2026-10-23 | open (D5) |
| REQ-131 | Where structure editing is included, the NEXUS server shall leave every change to a stage source to an agent on a device. | functional | Could | CTX-010 | Design draft 2026-10-23 | open (D5) |
| REQ-132 | If an imported change belongs to a team project, then the agent shall not commit it straight to the project's repositories. | functional | Could | CTX-010 | Design draft 2026-10-23 | open (D5) |
| REQ-133 | Where assistant access is included, the NEXUS server shall offer an MCP server that reads the same data as the hub page. | functional | Could | CTX-011 | Design draft 2026-10-23 (phase 2) | open (D5) |
| REQ-134 | Where assistant access is included, the MCP server shall answer only chat clients that signed in through Cloudflare Access. | non-functional | Could | CTX-011 | Design draft 2026-10-23 | open (D5) |
| REQ-135 | Where assistant access is included, the MCP server shall show a project's stages as an in-chat view in chat clients that support MCP Apps. | functional | Could | CTX-011 | Design draft 2026-10-23 (phase 3) | open (D5) |

## Success measures

For a two-week trial with this repository on the hub, after this release:

| Measure | Target | How it is measured |
| --- | --- | --- |
| Where things stand | The maintainer can tell where each project on the hub stands, on a phone, without asking an agent | The maintainer's note at the end of the trial |
| Current | The server's hub shows a stage change within a day of its merge or checkpoint | Snapshot times against merge and checkpoint times |
| Same everywhere | No stage shows different states on two devices or on the server | Snapshots pushed from different devices, compared |
| Useful checks | At most one check in three is a false lead | The maintainer's sample of the checks raised on this repository |
| Nothing leaks | No pushed snapshot holds file contents, a secret, an email address or a local path | Code check over the pushed snapshots |
| Cost | The server stays on the free plans | Cloudflare's usage pages |

## For the checkpoint

1. Decisions D5 to D7 above.
2. The rows marked `built`: phase 1 stays as it runs now, unless something in it should change.
3. What is never built, at the end of the scope.
4. The first real project on the hub is this repository. Its first push waits for the maintainer's go-ahead (REQ-107).

No requirement repeats or contradicts another. REQ-089 depends on D6, REQ-125 on D7, and REQ-127 to REQ-135 on D5. Under D6's recommendation REQ-069 still holds: the stage skills write the progress into the repository, and the hub only reads it.
