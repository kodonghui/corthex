# NEXUS: user flows

[한국어](README.ko.md)

Stage 03 of CORTHEX's own project, for NEXUS: the `corthex-nexus` plugin and the NEXUS server. Status: draft of 2026-11-02, waiting for the stage's checkpoint. The maintainer chose on 2026-11-02 to design NEXUS from this stage on while the memory plugin is being built, and to decide when to build NEXUS after memory's first release. When a file here and its Korean translation differ, the English file is the source.

Inputs: the requirements in [docs/02-prd/nexus.md](../../02-prd/nexus.md) (REQ-066 to REQ-193, with the scope and D8 to D13 approved on 2026-10-25, and REQ-197 and REQ-198, added with R4 on 2026-11-02), and the contexts and glossary in [docs/01-domain/nexus.md](../../01-domain/nexus.md), whose meanings the words here keep. The IDs of these flows start at FL-101, apart from memory's FL-001 to FL-012, so that both parts can add flows at the same time without taking the same number.

Each flow has its own file with a Mermaid flowchart, and each step names the requirements it serves. The flows draw NEXUS 0.2, which is phase ①: the hub and the server built in phase 1 are drawn as they run now, with the steps that 0.2 adds, and FL-115 draws the editing of phase ②, so that the data of 0.2 leaves room for it. The tool links of phase ③ have no flow yet.

| ID | Flow | Context | Release | Starts when |
| --- | --- | --- | --- | --- |
| FL-101 | [Read a project into a snapshot](FL-101-read-a-project.md) | CTX-006 | phase 1, changed in 0.2 | The agent or the user takes a snapshot, or the hub refreshes one |
| FL-102 | [Push a project to the NEXUS server](FL-102-push-a-project.md) | CTX-009 | phase 1, changed in 0.2 | Stage work is merged, a checkpoint is recorded, the agent starts its work, or the user asks |
| FL-103 | [Draw a project's pictures](FL-103-draw-the-pictures.md) | CTX-012 | 0.2 | The NEXUS server stores a snapshot |
| FL-104 | [Cross-check the pictures](FL-104-cross-check-the-pictures.md) | CTX-013 | 0.2 | A picture is drawn or drawn again |
| FL-105 | [See where the projects stand](FL-105-see-the-hub-page.md) | CTX-008 | phase 1, changed in 0.2 | The user opens the hub page |
| FL-106 | [Look at a picture](FL-106-look-at-a-picture.md) | CTX-012 | 0.2 | The user opens a stage's picture from the hub page |
| FL-107 | [Leave a comment on a picture](FL-107-leave-a-comment.md) | CTX-014 | 0.2 | The user selects a part of a picture to comment on |
| FL-108 | [Start the agent's work on a project](FL-108-start-the-agents-work.md) | CTX-007 | 0.2 | The agent starts its work on a project, following a stage skill |
| FL-109 | [Answer a comment](FL-109-answer-a-comment.md) | CTX-014 | 0.2 | The agent takes an open comment from its agent to-do |
| FL-110 | [Accept or dismiss a proposal](FL-110-accept-or-dismiss-a-proposal.md) | CTX-014 | 0.2 | The user opens a proposal on a picture |
| FL-111 | [Reflect by pull request](FL-111-reflect-by-pull-request.md) | CTX-010 | 0.2 | The agent to-do holds pending reflections |
| FL-112 | [Finish a unit of stage work](FL-112-finish-stage-work.md) | CTX-007 | 0.2 | The agent finishes a unit of stage work |
| FL-113 | [Pass a stage's checkpoint](FL-113-pass-a-checkpoint.md) | CTX-007 | 0.2 | The user looks at whether a stage is ready |
| FL-114 | [Remove a project from the NEXUS server](FL-114-remove-a-project.md) | CTX-009 | phase 1, changed in 0.2 | The user asks to remove a project |
| FL-115 | [Edit a picture on a PC](FL-115-edit-a-picture.md) | CTX-010 | phase ② | The user opens a picture to edit it |

## Where the flows run

| Where | Flows |
| --- | --- |
| On a device, in the hub | FL-101, FL-102 and FL-114, and FL-105 when the hub page is built there |
| On the NEXUS server, when it stores a snapshot | FL-103, then FL-104 |
| In a browser, on a phone or a PC | FL-105 on the server, FL-106, FL-107, FL-110 and the stage overview of FL-113; FL-115 on a PC only |
| In a session, where the agent works | FL-108, which leads to FL-109, FL-111, FL-112 and the agent's part of FL-113 |

The agent reaches NEXUS only through the hub, with the service token, and NEXUS never calls the agent: what the user leaves in NEXUS waits for the agent's next work (FL-108).

## Requirements that no flow uses

REQ-082 (Python 3.8 and its standard library), REQ-083 (Linux, macOS and Windows), REQ-121 (no AI model on the server), REQ-122 (no rights on any repository), REQ-123 (the database code in one module), REQ-124 (the free plans) and REQ-126 (the guide to deploying a server) hold for the whole hub or server rather than for one flow; the functional spec states them, and QA checks them. REQ-186 to REQ-188, the tool links of phase ③, wait for that phase, where hotspot 12 is decided. Every other requirement appears in at least one flow.

## Points for the functional spec

Drawing the flows raised these questions, which the requirements leave open. The functional spec of stage 04 answers them; points 2 and 4 come first to the maintainer, under the checkpoint below.

1. **Where the drawing runs.** The Workers Free plan gives each request 10 ms of CPU time ([Cloudflare's limits](https://developers.cloudflare.com/workers/platform/limits/), read on 2026-11-02), and the server stays on the free plans (REQ-124). Laying out a picture of 300 elements (REQ-143, REQ-149) may therefore have to run in the picture view, while the cross-check, whose discrepancies keep a state, runs where snapshots are stored (REQ-137, REQ-151).
2. **Which checkout gives the pictures.** The hub reads a checkout as it is, and the snapshot records each repository's commit, its branch and whether it has uncommitted changes. A push from a work branch, or with uncommitted text, would draw pictures of work that is not merged (REQ-137, REQ-139).
3. **Which snapshot is newer.** The server keeps the snapshot that was made last, by its `generated_at` (`nexus/src/store.js`), not the one with the newest commit, so a device with an older checkout that pushes later would draw older pictures (REQ-115, REQ-137).
4. **One project, several parts.** This repository has two parts: its stage 03 is confirmed for memory and drafted for NEXUS, and its stage 01 has a document for each. In the requirements a stage has one record and one picture (REQ-086, REQ-140, REQ-173). The spec also sets the file and the format of the stage records in the repository.
5. **The DDD board and the stage 01 template.** The board needs each context's command rows, policies, dependencies and hotspots (REQ-140), and the cross-check needs each aggregate's and each read model's glossary term (REQ-152, REQ-153). The current template lists aggregates and read models by name, without their TERM IDs; whether it names them is part of the open choice of 2026-11-02 about changing the stage 01 template.
6. **Tables and screens with no term.** A table that stands for no aggregate, such as a join table or a log, and a screen that stands for no read model would each open a discrepancy for a missing pair (REQ-154, REQ-155). The spec decides how a table or a screen says that it stands for none, so that these are not false leads; the success measures allow one false lead in three.
7. **What disagreeing means** for each pair, and how serious each discrepancy is (REQ-155), as stage 02 left it for the spec.
8. **A picture left out.** When the hub leaves a picture out for size (REQ-192), or its source is in another repository (REQ-144), the spec decides whether the space keeps the last picture, marked as old, or shows none.
9. **Answers and replies.** The requirements speak of comments and their answers, not of replies. The spec decides whether a comment holds replies, so that the user can answer the agent on a phone and settle a comment there (FL-109), and whether the user can open again a comment that the agent marked answered (REQ-166).
10. **Proposals on the picture.** A picture's content comes only from the stage sources (REQ-138), yet an accepted proposal edits the picture as proposed (TERM-089). FL-110 shows it marked as not yet reflected, and the spec decides how. It also decides whether a dismissed proposal leaves its comment open, as FL-110 draws, so that the agent learns of the dismissal.
11. **Reflections that do not go through.** An accepted proposal whose stage source changed before the agent reflects it (REQ-130 covers only edits in the picture view), and a pull request that is closed without being merged (REQ-170): the spec decides when the agent asks the user again, and when a reflection stays pending or closes.
12. **Two agents at once.** Two sessions that start work on one project read the same agent to-do, and could answer the same comment or open two pull requests for one reflection (REQ-131, REQ-181). The spec decides whether an agent claims what it takes, and for how long. This repository has two agents working on it now.
13. **The start of the agent's work.** The core plugin has skills only, so the agent to-do is read in a step of the stage skills (REQ-181); a session-start hook would need a plugin with hooks, under this repository's rules for them. A device without the service token, such as a cloud session, cannot read the agent to-do and only says so (REQ-185). The spec also decides how the agent to-do meets what the user asked in the session: FL-108 tells the user what is waiting before it starts on it.
14. **Writes that fail.** When the hub cannot send what the agent writes (REQ-184), or the server cannot save a comment from a phone (FL-107), the spec decides what is kept and when it is sent again.
15. **A checkpoint before its record.** Between the user's passing a checkpoint in NEXUS (REQ-178) and the agent's writing it into the repository (REQ-180), the hub page shows the stage as recorded (REQ-084). The spec decides how the stage overview shows the passed checkpoint meanwhile.
16. **Telling the user from the agent.** The server marks authors by the kind of Cloudflare Access sign-in (REQ-163): the agent's service token, or the user's own sign-in in a browser. The server of phase 1 checks only that Access checked a request for its application (`nexus/src/app.js`), so the spec states which sign-in each write needs (REQ-129, REQ-179).
17. **Removal.** Removing a project deletes its open comments, proposals and pending reflections with its space (REQ-120). FL-114 lists them before the user confirms, so that the agent can reflect or record them first.
18. **The actions to ask about first.** Under R4, a project's settings may set their own `ask_before`, which replaces the profile's for that project, while anything that cannot be undone is still asked; the core plugin's project settings define the field. NEXUS only shows the list that applies (REQ-197, REQ-198) and enforces nothing. The spec decides what the snapshot holds when a list is not a list of strings, or when neither the settings nor the profile set one, so that the profile's default list applies; what the page shows for an empty list; and how many entries it shows. A change to the profile reaches the server only with each project's next push. Project settings come from the repository and are read as data (TERM-041), so a change to the repository can shorten the list: the page names where the list comes from, so that the user sees when a project asks about less than the profile. R4 also suggested showing a level beside the list, from proposals only to deploys; the settings hold no level now, so the page shows the list alone, and a level would first need a field in the core plugin's settings.

## For the checkpoint

Waiting. The maintainer reviews each flow's main path and its main failure paths, as stage 03 asks. Two points need the maintainer's choice; the AI's recommendation comes first:

1. **Which version the pictures show** (point 2). Recommended: only the merged commit of the default branch, from a checkout without uncommitted changes, since D8 pushes after each merge and this repository merges drafts before their checkpoints. The other choice: a pull request's version too, as a second version of the picture, so that a draft can be discussed before it is merged; that needs comments for each version and more on the server.
2. **A project with several parts** (point 4). Recommended: one picture for each document of a pictured stage, such as one DDD board for memory and one for NEXUS, and one stage record for each part, so that the hub can show that stage 03 is confirmed for memory and drafted for NEXUS. The other choice: one picture and one record for each stage, as the requirements say now; the stage contract stays as it is, but this repository's two parts then share one state.

The other points go to the functional spec with the AI's answers, which the maintainer checks together with it.
