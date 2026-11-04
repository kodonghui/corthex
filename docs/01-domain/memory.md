# CORTHEX-MEMORY: domain

[한국어](memory.ko.md)

Stage 01 of CORTHEX's own project, for the `corthex-memory` plugin. Status: written on 2026-10-24. The maintainer checked the requirements built on it the same day (stage 02); later stages add their changes here with the date. When this file and its Korean translation differ, this file is the source. On 2026-11-03 the maintainer approved C2 line edits and line history, conflict candidates, and logged runs with undo; TERM-014 and TERM-017 changed and TERM-135 to TERM-138 were added.

This file holds both the contexts and the glossary of CORTHEX-MEMORY. Other parts of the project get their own files in this folder, and the translations beside them are not read as sources.

Sources read:

- The design draft for CORTHEX-MEMORY in the maintainer's records (2026-10-23), with its list of problems and the hook tests of 2026-10-23.
- The Windows hook check of 2026-10-24, [`.github/workflows/windows-hook-check.yml`](../../.github/workflows/windows-hook-check.yml).
- The session start hook in [`plugins/corthex-memory/`](../../plugins/corthex-memory/) and its description in [docs/architecture.md](../architecture.md#session-start-context).
- The maintainer's decision of 2026-10-24 to set no spending cap.

## Contexts

### CTX-001 Capture

Purpose: write what is said in the sessions of an enabled project to the raw log on the device, without slowing the session down.

- Events: Session started, Prompt submitted, Turn finished, Session ended, Turn recorded, Recording skipped
- Commands: Record turn
- Policies: Record only in enabled projects. Take the session's project from the project list on the device, never from settings found in the repository. Remove secrets and private spans before anything is written. Record prompts and final answers, not tool calls or tool results. Never block or fail the session; when recording fails, go on and note it.
- Actors: User, Agent, Host
- Open questions: Should the host's compaction summaries be recorded too? Do the turns of subagents count as turns of the session?

### CTX-002 Curation

Purpose: turn new raw turns into the project's current state and memory items, with their provenance, in the background.

- Events: Curation due, Curation started, Item added, Item superseded, Item withdrawn, Current state updated, Curation failed, Curation stopped, Consolidation finished
- Commands: Curate project, Consolidate project, Check quote
- Policies: One curation per project at a time. An item is saved only when its quote is found word for word in the raw log. Only the user's own words make a user decision. Items are superseded or withdrawn, never silently rewritten. When a model request fails, the raw turns wait for the next curation. After repeated failures on the same turns, curation stops until the user resumes it. Spending never stops curation.
- Actors: Curator, Anthropic API
- Answered on 2026-10-27: point 1 of stage 04 confirms SPEC-010: at turn end, 10 unprocessed turns or an unprocessed turn older than 30 minutes, whichever comes first; at session end, any unprocessed turn; at session start, turns left from earlier sessions.

### CTX-003 Recall

Purpose: give the agent the memory it needs, at session start and with each prompt, and nothing it does not need.

- Events: Start summary injected, Items recalled, Nothing recalled, Recall timed out
- Commands: Build start summary, Recall for prompt, Search memory
- Policies: Only the session's project. Only current items. Inject nothing when no item passes the recall threshold. Mark injected memory as reference material, not instructions. Stay within the size limits. When recall is late or an API fails, inject nothing. Show text from repository files only in fixed formats.
- Actors: Host, Agent, OpenAI API
- Answered on 2026-10-27: D2 in the [requirements](../02-prd/memory.md#decisions-in-force) chooses items per prompt with embeddings and rules; Claude Haiku 5.5 works only in background curation.

### CTX-004 Sync

Purpose: share the curated layer between the user's devices.

- Events: Changes pushed, Changes pulled, Changes merged, Tombstone applied
- Commands: Sync memory
- Policies: Off until the user turns it on. Only the curated layer goes to a private sync remote of the user's; raw logs and the search index stay on each device. A forgotten item never comes back through sync.
- Actors: User, Other device, Sync remote
- Answered on 2026-10-27: D3 in the [requirements](../02-prd/memory.md#decisions-in-force) shares the curated layer through a user-operated HTTPS gateway and Postgres server with pgvector. Devices do not connect to the database directly.

### CTX-005 Control

Purpose: let the user decide what is remembered, where it is sent and how it is paid for, and let them see and undo it.

- Events: Project enabled, Project disabled, Consent given, Item pinned, Item unpinned, Item forgotten, Store purged, Usage recorded
- Commands: Enable project, Disable project, Pin item, Unpin item, Forget item, Purge store, Show status
- Policies: Projects start disabled. Nothing is sent to an API before consent. Keys are read only from the memory key variables or the host's secure storage, and never written anywhere. Each model call is logged with its usage. No spending cap (the maintainer's decision of 2026-10-24); a user who wants a limit sets it in the model provider's console. Removing the plugin keeps the memory store.
- Actors: User
- Answered on 2026-10-27: D4 in the [requirements](../02-prd/memory.md#decisions-in-force) uses two memory-only keys: Anthropic in the Console organization linked to the maintainer's subscription, using its monthly API credit for curation, and a separate OpenAI key for embeddings.

## Glossary

| ID | Term | Definition | Context | Avoid |
| --- | --- | --- | --- | --- |
| TERM-001 | Host | The program that runs the agent and the hooks: Claude Code or Codex | all | client, app |
| TERM-002 | Agent | The AI model that works with the user in a host session | all | assistant, bot |
| TERM-003 | Session | One conversation in a host; a resumed or forked session keeps the history it started from | all | chat, thread |
| TERM-004 | Turn | One prompt of the user and the agent's final answer to it | CTX-001, CTX-002 | message, exchange |
| TERM-005 | Project | A repository in the project list of the device; memory is kept per project | all | workspace, folder |
| TERM-006 | Enabled project | A project for which the user turned memory on | CTX-001, CTX-005 | tracked project |
| TERM-007 | Memory store | The folder on the device where memory lives, shared by both hosts: `~/.corthex/corthex-memory/`, or the folder named by `CORTHEX_MEMORY_HOME` | all | database, cache |
| TERM-008 | Raw log | A project's append-only record of turns and session boundaries on one device, after redaction | CTX-001, CTX-002 | transcript, history |
| TERM-009 | Host transcript | The host's own file of a session, given to hooks as `transcript_path`; memory may read it but does not own it | CTX-001 | raw log |
| TERM-010 | Redaction | Removing secrets and private spans from text before it is written | CTX-001 | masking |
| TERM-011 | Private span | Text between `<private>` and `</private>`, which is never recorded | CTX-001 | |
| TERM-012 | Curation | The background step that reads new raw turns and updates the current state and the memory items | CTX-002 | summarizing |
| TERM-013 | Curator | The background process that runs one curation | CTX-002 | worker, daemon |
| TERM-014 | Current state | The project's goal, decisions in force, work in progress, blockers and next actions, each line with its provenance; the curator changes it line by line, and each changed or removed line's previous text is kept on the device | CTX-002, CTX-003 | summary, status |
| TERM-015 | Memory item | One lasting decision, preference, lesson, reference or fact, with its provenance and status | CTX-002, CTX-003 | note, memory |
| TERM-016 | Item kind | What an item is: decision, preference, lesson, reference or fact | CTX-002 | type, category |
| TERM-017 | Item status | `current`, `superseded` (replaced by a newer item), `withdrawn` (taken back by its speaker) or `undone` (reversed by an undo) | CTX-002, CTX-003 | deleted, archived |
| TERM-018 | Provenance | Where an item or a line comes from: its quote, the quote's place in the raw log, the speaker and the time it took effect | CTX-002 | source (a stage's text source in CORTHEX) |
| TERM-019 | Speaker | Who said a quote: the user, the agent or a tool | CTX-002 | author |
| TERM-020 | User decision | A decision item whose quote is the user's own words | CTX-002 | approval |
| TERM-021 | Quote check | The check in code that an item's quote appears word for word in the raw log | CTX-002 | |
| TERM-022 | Consolidation | A periodic curation that merges duplicate items and tidies old ones | CTX-002 | cleanup |
| TERM-023 | Fault guard | The rule that stops a project's curation after repeated failures on the same turns, until the user resumes it | CTX-002 | spending cap, budget |
| TERM-024 | Start summary | The context added when a session starts: principles, profile, project settings and, for an enabled project, its current state and pinned items | CTX-003 | session context |
| TERM-025 | Pinned item | An item the user wants in every start summary of its project | CTX-003 | favourite |
| TERM-026 | Recall | Choosing the items that matter for a session start or a prompt | CTX-003 | retrieval |
| TERM-027 | Injection | Adding recalled memory to the agent's context through a hook | CTX-003 | prompt stuffing |
| TERM-028 | Recall threshold | The lowest relevance an item needs to be injected; below it, nothing is injected | CTX-003 | |
| TERM-029 | Search index | The text and embedding index of the items, which can always be rebuilt from them | CTX-003 | database |
| TERM-030 | Embedding | A vector for a text from the OpenAI embeddings API, used to find items by meaning | CTX-003 | |
| TERM-031 | Item list | A short list of a project's current items, one line each, read before any item is opened | CTX-003 | index |
| TERM-032 | Curated layer | The current state, the items and their pins, the item list and the tombstones: what sync shares | CTX-004 | |
| TERM-033 | Sync remote | The private place that the curated layer is synced through: the user-operated Postgres server with pgvector chosen by D3 on 2026-10-27, reached by devices only through an HTTPS gateway | CTX-004 | cloud |
| TERM-034 | Tombstone | A record that an item was forgotten, so that sync does not bring it back | CTX-004, CTX-005 | |
| TERM-035 | Forget | Removing an item, its search index entries and the raw log text it quotes, and leaving a tombstone | CTX-005 | delete |
| TERM-036 | Purge | Deleting the whole memory store | CTX-005 | reset |
| TERM-037 | Consent | The user's confirmation that conversation text may be sent to the Anthropic and OpenAI APIs | CTX-005 | |
| TERM-038 | Memory key | An API key kept for memory alone, in `CORTHEX_MEMORY_ANTHROPIC_API_KEY` or `CORTHEX_MEMORY_OPENAI_API_KEY` | CTX-005 | API key, unqualified |
| TERM-039 | Usage log | One line per model call with the model, the token counts and the estimated cost | CTX-005 | bill |
| TERM-040 | Profile | `~/.corthex/profile.json`: how to address the user, their language and where records go | CTX-003 | settings |
| TERM-041 | Project settings | A project's `.corthex/project.json`, which comes from its repository and is read as data | CTX-001, CTX-003 | config |
| TERM-042 | Project list | `~/.corthex/projects.json`, the projects on the device and their folders | CTX-001, CTX-005 | registry |
| TERM-043 | Principles | The short form of the CORTHEX working principles, kept equal to the list in the entry skill | CTX-003 | rules |
| TERM-044 | Memory configuration | The memory plugin's own settings on the device, kept in the memory store: the enabled projects, the models, the retention period, what is left out of recording, and sync | CTX-002, CTX-005 | config, project settings |
| TERM-045 | Memory status | What the memory skill shows about memory on the device: the enabled projects, the last curation, the unprocessed turns, the usage and the recent failures | CTX-005 | dashboard |
| TERM-046 | Memory skill | The memory plugin's skill, which tells the agent how to search, pin, forget, show the memory status and change the memory configuration | CTX-003, CTX-005 | command |
| TERM-098 | Unprocessed turn | A turn in the raw log that no curation has processed yet | CTX-001, CTX-002 | new turn, pending turn |
| TERM-099 | Curation trigger | An event after which the unprocessed turns of an enabled project are curated, such as the tenth unprocessed turn at the end of a turn | CTX-002 | schedule |
| TERM-100 | Curation lock | The mark that a curation is running for a project, which keeps a second one from starting | CTX-002 | mutex |
| TERM-101 | Temporary device | A device whose files go when its session ends, such as the container of a cloud session | CTX-001, CTX-002, CTX-004 | cloud device |
| TERM-102 | Deciding quote | The first quote of an item, on which it rests; the deciding quote of a user decision is in the user's own words | CTX-002 | evidence |
| TERM-103 | Notice | A line of the start summary about something that needs the user, such as stopped curation or a missing memory key | CTX-003 | alert, warning |
| TERM-104 | Injection log | The record of which items were injected with which prompt or start summary, with recall's scores and without their text | CTX-003 | |
| TERM-105 | Failure log | The record of failures of recording, recall, curation and sync, without conversation text or keys | CTX-005 | error log |
| TERM-106 | Hook timings | How long each hook of the memory plugin ran, kept for the memory status | CTX-005 | |
| TERM-107 | Project tombstone | A record that a project's memory was deleted, so that sync does not bring it back; REQ-194, SPEC-037 | CTX-004, CTX-005 | |
| TERM-108 | Price list | The prices per token that the usage log's estimates use, with when and where they were taken | CTX-005 | bill, rate card |
| TERM-135 | Line history | The device's record of the previous text and provenance of each current state line that was changed or removed, kept for the retention period | CTX-002 | state log, diff |
| TERM-136 | Conflict candidate | Two current items that may not both hold, recorded for the user to settle; neither replaces the other until the user says which holds | CTX-002, CTX-003 | contradiction, conflict |
| TERM-137 | Run | One curation, consolidation or undo, logged on the device with the IDs of what it changed | CTX-002 | job, batch |
| TERM-138 | Undo | A run that reverses an earlier run's changes and keeps what later runs changed | CTX-005 | rollback, revert |

The functional spec ([docs/04-functional-spec/memory.md](../04-functional-spec/memory.md)) added TERM-098 to TERM-108 on 2026-10-24, and the pins to the curated layer (TERM-032). Their IDs continue after those of NEXUS in [nexus.md](nexus.md), which uses TERM-047 to TERM-097.
