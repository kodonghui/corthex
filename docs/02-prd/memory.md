# CORTHEX-MEMORY: requirements

[한국어](memory.ko.md)

Stage 02 of CORTHEX's own project, for the `corthex-memory` plugin. Status: the maintainer checked the scope on 2026-10-24, without changes (the stage's first checkpoint). On 2026-10-27 the maintainer confirmed D1, D2 and D4 as recommended and chose the new server sync option for D3 below. The default raw retention period is 100 days. When this file and its Korean translation differ, this file is the source. On 2026-11-03 the maintainer approved three C2 additions, extending REQ-037 and REQ-054 and adding REQ-219 to REQ-225.

Inputs: the contexts and the glossary in [docs/01-domain/memory.md](../01-domain/memory.md) (CTX-001 to CTX-005, TERM-001 to TERM-046). Words in this file have the meanings given there.

## Goal

Keep the user's working context across sessions, devices and the two hosts, so that the agent starts each session and answers each prompt with the project's current state and the decisions that matter, without the user explaining it again and without spending the main model's limits on it.

## Problems

The maintainer's records list these problems with long-running AI work. Each requirement below names the problem or the decision it comes from.

1. In a long session the earlier context fades, and each prompt needs the memory that fits it.
2. A new session, another device or the other host needs the context set up and explained again, which costs time and usage limits.
3. The contexts of different projects get mixed.
4. Records in Notion, Jira or Git are read again and again, using the large model's limits.
5. Summaries lose details, decisions that were taken back come back, and who said what becomes unclear.
6. When a session is cut off, what was said in it is lost.

## Scope

This release, the M1 plan of the design draft in three steps: C1 capture and the start summary, C2 curation and recall, C3 sync between devices.

- In: capture, curation, the start summary, per-prompt recall, search, forget, status, purge, optional sync through a user-operated HTTPS gateway and server, the usage log.
- Out: pages or other screens; memory shared between different people; recording tool calls or tool results; direct database connections from devices; folders that are not in the project list.
- Projects with protected data, such as answer keys or student records, are not enabled in the first trial.

## Decisions in force

| When | Decision | Affects |
| --- | --- | --- |
| 2026-10-23 | Memory works through the hosts' hooks. Embeddings come from OpenAI; every other model call uses Claude Haiku 5.5 at xhigh effort. | REQ-001, REQ-002, REQ-014, REQ-040 |
| 2026-10-24 | No spending cap. The maintainer's plan includes a monthly API credit, so curation is never limited by spending. | REQ-025, REQ-052 |
| 2026-10-24 | Work goes to the harness itself and leaves the progress of other projects out. The draft therefore proposes this repository for the first trial. | Success measures |
| 2026-10-27 | **D1.** Adopt M1 as recommended: build `corthex-memory` directly to this spec. | REQ-001, REQ-059 |
| 2026-10-27 | **D2.** As recommended, embeddings and rules choose items per prompt; Claude Haiku 5.5 is used only for background curation. | REQ-014, REQ-031, REQ-033, REQ-034 |
| 2026-10-27 | **D3.** Each device keeps files and a SQLite search index. A user-operated Postgres server with pgvector syncs the curated layer. Devices use only an HTTPS sync gateway, accessible with the Python standard library, and never connect to the database directly. Each device has its own separately revocable token. Raw logs and search indexes stay on their devices; sync remains off by default. The private Git repository option was not chosen. | REQ-008, REQ-042, REQ-043, REQ-044, REQ-046, REQ-061 |
| 2026-10-27 | **D4.** As recommended, use two memory-only keys. The Anthropic key is created in the Console organization linked to the maintainer's subscription, whose monthly API credit pays for curation; the separate OpenAI key is for embeddings. | REQ-050, REQ-051, REQ-052 |
| 2026-10-27 | Set default raw retention to 100 days, keeping its configurable range of 1 to 3,650 days. | REQ-009 |
| 2026-11-03 | Three additions to C2, from the maintainer's review of recent memory research: the curator changes the current state line by line, and the device keeps each changed or removed line's previous text for the retention period; possible disagreements between current items become conflict candidates that the user settles, never replacements that the curator makes on its own reading; and each curation, consolidation and undo is logged as a run that the user can undo. | REQ-015, REQ-037, REQ-054, REQ-219 to REQ-225 |

The maintainer's own words and where they were said are in the maintainer's records, not in this repository.

## Open decisions

None of memory's decisions is open. The maintainer answered D1 to D4 on 2026-10-27: D1, D2 and D4 as recommended, and D3 as a new option. The table retains the questions and the other choices considered.

| ID | Question | Recommendation | Other choices | Status |
| --- | --- | --- | --- | --- |
| D1 | How to build memory | M1: build `corthex-memory` as planned in this file | Adopt an existing memory plugin, which chooses its own models and runs a local server; build on NEXUS first, which needs the server before memory works; rely on the hosts' own memory, which does not cross hosts or devices | decided 2026-10-27 |
| D2 | How items are chosen for each prompt | Embeddings and rules choose; Claude Haiku 5.5 works only in the background | Haiku 5.5 at xhigh chooses for every prompt: slower and costlier for each prompt (an estimate, not measured); no per-prompt recall: the start summary and searches only | decided 2026-10-27 |
| D3 | How devices share memory | A private Git repository of the user's; off by default for everyone else | Each device keeps its own memory until NEXUS can sync it; no sharing; one Postgres database for all devices, which keeps conversation-derived memory in an outside database and needs its secret on every device | new option chosen 2026-10-27 (see Decisions in force); the recommended Git repository was not chosen |
| D4 | How model calls are paid for | Two memory keys, one for Anthropic and one for OpenAI. The Anthropic key is made in the Console organization linked to the maintainer's subscription, so that its monthly API credit pays for curation | Run curation with `claude -p` on the subscription login, which uses the plan's limits rather than the API credit, needs a guard against the plugin's own hooks, and does not work for Codex-only users | decided 2026-10-27 |

D1, D2 and D4 were confirmed as recommended on 2026-10-27; D3 is a new choice. D3 preserves the device store and standard-library client while sharing only the curated layer and allowing one device's access to be revoked without giving database credentials to devices. The server sync design will be specified separately before C3. The retained Git designs in later stages have the common status `superseded (D3, 2026-10-27)`.

## Requirements

Priorities: Must, Should, Could. Status: `active`, `built` (in 0.1.0 already), with D1 to D4 answered on 2026-10-27.

| ID | Requirement | Type | Priority | Context | Source | Status |
| --- | --- | --- | --- | --- | --- | --- |
| REQ-001 | While the session's project is enabled, when the user submits a prompt, the memory plugin shall append the prompt to the project's raw log. | functional | Must | CTX-001 | Decision 2026-10-23; problem 6 | active |
| REQ-002 | While the session's project is enabled, when the agent finishes a turn, the memory plugin shall append the agent's final answer to the project's raw log. | functional | Must | CTX-001 | Decision 2026-10-23; problem 6 | active |
| REQ-003 | While the session's project is enabled, when a session starts or ends, the memory plugin shall append a session boundary to the project's raw log. | functional | Should | CTX-001 | Design draft 2026-10-23 | active |
| REQ-004 | The memory plugin shall not record tool calls or tool results. | functional | Must | CTX-001 | Design draft 2026-10-23 | active |
| REQ-005 | The memory plugin shall take the session's project from the project list on the device, never from project settings found in the repository. | functional | Must | CTX-001 | Problem 3; review of the hub, 2026-10-24, where a repository's settings could name another project | active |
| REQ-006 | If the session's folder is not in an enabled project, then the memory plugin shall record nothing. | functional | Must | CTX-001 | Problem 3 | active |
| REQ-007 | The memory plugin shall remove secrets and private spans from any text before writing it. | functional | Must | CTX-001 | Design draft 2026-10-23 | active |
| REQ-008 | The memory plugin shall keep each raw log only on the device that wrote it. | non-functional | Must | CTX-001 | Design draft 2026-10-23 | active |
| REQ-009 | When a raw log entry is older than the retention period, 100 days unless the user sets another, the memory plugin shall delete the entry. | functional | Should | CTX-001 | Design draft 2026-10-23; 2026-10-27 | active |
| REQ-010 | If recording fails, then the memory plugin shall let the session go on. | functional | Must | CTX-001 | Hook tests 2026-10-23 | active |
| REQ-011 | The capture hooks shall finish within 100 ms at the 95th percentile on the CI runners of all three systems. | non-functional | Should | CTX-001 | Design draft 2026-10-23 | active |
| REQ-012 | If a session ends without its end event, then the raw log shall still hold every turn recorded before the end. | non-functional | Must | CTX-001 | Problem 6 | active |
| REQ-013 | When an enabled project has unprocessed raw turns and a curation trigger is met, the memory plugin shall start curation in a background process that the host does not wait for. | functional | Must | CTX-002 | Decision 2026-10-23; hook tests 2026-10-23 (session end hooks get 1.5 s) | active |
| REQ-014 | The curator shall use the model set in the memory configuration, by default Claude Haiku 5.5 at xhigh effort. | functional | Must | CTX-002 | Decision 2026-10-23 | active |
| REQ-015 | When the curator processes new raw turns, the curator shall update the project's current state, giving each line its provenance. | functional | Must | CTX-002 | Problems 1, 2 and 5 | active |
| REQ-016 | When the curator finds a lasting decision, preference, lesson, reference or fact in new raw turns, the curator shall save it as a memory item with its kind, provenance and status. | functional | Must | CTX-002 | Problems 1, 2 and 4 | active |
| REQ-017 | If an item's quote does not appear word for word in the raw log, then the curator shall not save the item. | functional | Must | CTX-002 | Problem 5 | active |
| REQ-018 | The curator shall save a decision as a user decision only when its quote is the user's own words. | functional | Must | CTX-002 | Problem 5 | active |
| REQ-019 | When a new item replaces an earlier one, the curator shall mark the earlier item as superseded instead of deleting it. | functional | Must | CTX-002 | Problem 5 | active |
| REQ-020 | When a speaker takes back an earlier decision or statement, the curator shall mark its item as withdrawn instead of deleting it. | functional | Must | CTX-002 | Problem 5 | active |
| REQ-021 | While a curation runs for a project, the memory plugin shall not start another curation for that project. | functional | Must | CTX-002 | Design draft 2026-10-23 | active |
| REQ-022 | The curator shall keep each model request under 100,000 input tokens. | non-functional | Should | CTX-002 | Design draft 2026-10-23 (the higher price tier starts above 100,000 prompt tokens) | active |
| REQ-023 | If a curation request fails, then the memory plugin shall keep the unprocessed raw turns for the next curation. | functional | Must | CTX-002 | Design draft 2026-10-23 | active |
| REQ-024 | If curation fails three times in a row on the same raw turns, then the memory plugin shall stop curating that project until the user resumes it. | functional | Must | CTX-002 | Fault guard proposed with the decision of 2026-10-24 | active |
| REQ-025 | The memory plugin shall not cap, pause or slow curation because of spending. | functional | Must | CTX-002 | Decision 2026-10-24 | active |
| REQ-026 | When a week has passed since a project's last consolidation, the memory plugin shall consolidate the project in the background at its next session start. | functional | Should | CTX-002 | Design draft 2026-10-23 | active |
| REQ-027 | When a session starts, resumes, forks, is cleared or is compacted, the memory plugin shall inject a start summary. | functional | Must | CTX-003 | Problem 2 | built |
| REQ-028 | While the session's project is enabled, the start summary shall include the project's current state and its pinned items. | functional | Must | CTX-003 | Problems 1 and 2 | active |
| REQ-029 | If curation failed, stopped or is waiting for consent or a memory key since the project's last session, then the start summary shall say so. | functional | Must | CTX-003 | Design draft 2026-10-23; 2026-10-27 | active |
| REQ-030 | The start summary shall stay under 8,000 bytes of UTF-8. | non-functional | Must | CTX-003 | Hook tests 2026-10-23 (hosts move larger hook context into a file) | built |
| REQ-031 | When the user submits a prompt in an enabled project, the memory plugin shall inject the project's current items whose relevance passes the recall threshold, five at most. | functional | Must | CTX-003 | Problem 1; decision D2 | active |
| REQ-032 | If no item passes the recall threshold, then the memory plugin shall inject nothing. | functional | Must | CTX-003 | Design draft 2026-10-23 | active |
| REQ-033 | The memory injected with one prompt shall stay under 600 tokens. | non-functional | Should | CTX-003 | Design draft 2026-10-23 | active |
| REQ-034 | The per-prompt hook shall finish within 1 second at the 95th percentile. | non-functional | Must | CTX-003 | Design draft 2026-10-23 | active |
| REQ-035 | If recall does not finish in time or an API fails, then the memory plugin shall let the prompt go on without injecting anything. | functional | Must | CTX-003 | Design draft 2026-10-23 | active |
| REQ-036 | The memory plugin shall inject only items of the session's project. | functional | Must | CTX-003 | Problem 3 | active |
| REQ-037 | The memory plugin shall never inject a superseded, withdrawn or undone item. | functional | Must | CTX-003 | Problem 5 | active |
| REQ-038 | The memory plugin shall mark injected memory as reference material, not instructions, with a note to read the original when it matters. | functional | Must | CTX-003 | Design draft 2026-10-23 | active |
| REQ-039 | The memory plugin shall show text from repository files only in fixed formats. | functional | Must | CTX-003 | Review of 0.1.0, 2026-10-24 | built |
| REQ-040 | The memory plugin shall compute embeddings with the OpenAI embeddings API. | functional | Must | CTX-003 | Decision 2026-10-23 | active |
| REQ-041 | When the user asks to search memory, the memory skill shall have the agent choose from the item list before it opens any item. | functional | Should | CTX-003 | Problem 4 | active |
| REQ-042 | Where sync is turned on, the memory plugin shall sync the curated layer with a user-operated Postgres server with pgvector, using only an HTTPS sync gateway accessible with the Python standard library and a separately revocable token for each device, with no direct device-to-database connection. | functional | Should | CTX-004 | Problem 2; decision D3; 2026-10-27 | active |
| REQ-043 | The memory plugin shall leave sync off until the user turns it on. | functional | Must | CTX-004 | Design draft 2026-10-23 | active |
| REQ-044 | The memory plugin shall never sync raw logs or the search index. | functional | Must | CTX-004 | Design draft 2026-10-23 | active |
| REQ-045 | When an item is forgotten on one device, the memory plugin shall leave a tombstone that keeps sync from bringing the item back on any device. | functional | Must | CTX-004 | Design draft 2026-10-23 | active |
| REQ-046 | When two devices change the curated layer at the same time, the memory plugin shall merge the changes without losing an item. | functional | Should | CTX-004 | Design draft 2026-10-23 | active |
| REQ-047 | The memory plugin shall keep each project disabled until the user enables it. | functional | Must | CTX-005 | Problem 3 | active |
| REQ-048 | When the user enables memory for the first time, the memory plugin shall ask for consent, showing what is sent to which API. | functional | Must | CTX-005 | Design draft 2026-10-23 | active |
| REQ-049 | If the user has not given consent, then the memory plugin shall send nothing to any API. | functional | Must | CTX-005 | Design draft 2026-10-23 | active |
| REQ-050 | The memory plugin shall read API keys only from the memory key variables or the host's secure storage. | functional | Must | CTX-005 | Hook tests 2026-10-23 (a plain `ANTHROPIC_API_KEY` outranks the subscription login); decision D4 | active |
| REQ-051 | The memory plugin shall never write an API key to a file, a log or the memory store. | functional | Must | CTX-005 | Repository rules | active |
| REQ-052 | When the memory plugin calls a model API, the memory plugin shall append the model, the token counts and the estimated cost to the usage log. | functional | Must | CTX-005 | Decision 2026-10-24 | active |
| REQ-053 | When the user asks for the memory status, the memory skill shall show the enabled projects, the last curation, the unprocessed turns, this month's usage and the recent failures of recording and curation. It shall also show the median and the 95th percentile of hook timings. | functional | Should | CTX-005 | Design draft 2026-10-23; 2026-10-27 | active |
| REQ-054 | When the user forgets an item, the memory plugin shall remove the item, its search index entries, the raw log text that it quotes and the kept previous texts of current state lines that cite either. Raw log text that an item which stays also quotes shall be kept. | functional | Must | CTX-005 | Design draft 2026-10-23; 2026-10-27 | active |
| REQ-055 | When the user asks to purge memory and confirms it, the memory plugin shall delete the memory store. | functional | Should | CTX-005 | Design draft 2026-10-23 | active |
| REQ-056 | The memory plugin shall keep the memory store outside the hosts' plugin data folders. | non-functional | Must | CTX-005 | Hook tests 2026-10-23 (Claude Code deletes a plugin's data folder with the plugin) | active |
| REQ-057 | Where the memory configuration excludes folders of a project or kinds of raw log entries, the memory plugin shall not record them. | functional | Should | CTX-005 | Design draft 2026-10-23 (projects with protected data) | active |
| REQ-058 | When the user disables a project, the memory plugin shall stop recording and recalling for the project without deleting its memory. | functional | Should | CTX-005 | Design draft 2026-10-23 | active |
| REQ-059 | The memory plugin shall work in Claude Code and in Codex CLI with one memory store per device. | functional | Must | none | Problem 2 | active |
| REQ-060 | The memory plugin shall run on Linux, macOS and Windows. | non-functional | Must | none | Repository goal; Windows hook check 2026-10-24 | active |
| REQ-061 | The memory plugin's hooks and sync gateway client shall need nothing but Python 3.8 or later and its standard library. | non-functional | Must | none | 0.1.0; 2026-10-27 | active |
| REQ-062 | The memory plugin shall ship without a root `plugin.json`. | non-functional | Must | none | Hook tests 2026-10-23 (Codex then skips the plugin's hooks) | built |
| REQ-063 | The memory store shall record its format version, so that a later release can migrate it. | non-functional | Must | none | Design depth note 2026-10-24 (the store is hard to change later) | active |
| REQ-064 | If the device stops during a write, then the memory store shall still be readable afterwards. | non-functional | Must | none | Repository rules (owned writes need a backup and a restore path) | active |
| REQ-065 | When the user asks to pin or unpin an item, the memory skill shall add the item to the project's pinned items or remove it from them. When a pinned item is superseded, the memory plugin shall move the pin to the item that superseded it. | functional | Could | CTX-005 | Design draft, update of 2026-10-24 (pinned memory in the start summary); 2026-10-27 | active |
| REQ-194 | When the user asks to delete one project's memory and confirms it, the memory plugin shall delete that project's memory on the device and, where sync is turned on, leave a project tombstone. | functional | Should | CTX-005 | Spec confirmed 2026-10-27; SPEC-037 | active |
| REQ-195 | While the device is a temporary device, the memory plugin shall curate after every turn and, where sync is turned on, sync after every curation. | functional | Should | CTX-002 | Spec confirmed 2026-10-27; SPEC-011 | active |
| REQ-196 | When the memory plugin injects items into a prompt or a start summary, it shall log where and which items, without their text. | functional | Should | CTX-003 | Spec confirmed 2026-10-27; SPEC-021, SPEC-023 | active |
| REQ-219 | When the curator updates the current state, the curator shall change only the lines that the new turns affect, and every line that its answer does not name shall stay as it is. | functional | Should | CTX-002 | Decision 2026-11-03 (I-03; problems 1 and 5) | active |
| REQ-220 | When a current state line is changed or removed, the memory plugin shall keep the line's previous text and provenance on the device for the retention period. | functional | Should | CTX-002 | Decision 2026-11-03 (I-03; problem 5) | active |
| REQ-221 | When the curator finds that an item may disagree with a current item that it does not replace, the memory plugin shall record a conflict candidate and keep both items current. | functional | Should | CTX-002 | Decision 2026-11-03 (I-04; problem 5) | active |
| REQ-222 | While a project has open conflict candidates, the memory plugin shall tell the user in the start summary, a limited number of times for each candidate. | functional | Should | CTX-003 | Decision 2026-11-03 (I-04; problem 5) | active |
| REQ-223 | When the user asks to dismiss a conflict candidate, the memory skill shall close it and leave both items as they are. | functional | Could | CTX-005 | Decision 2026-11-03 (I-04) | active |
| REQ-224 | When a curation, consolidation or undo changes a project's memory, the memory plugin shall log the run on the device, with the IDs of what it changed, for the retention period. | functional | Should | CTX-002 | Decision 2026-11-03 (I-05; problem 5) | active |
| REQ-225 | When the user asks to undo a run and confirms, the memory plugin shall reverse that run's changes as a new run, keep what later runs changed, and say what it kept. | functional | Should | CTX-005 | Decision 2026-11-03 (I-05; problem 5) | active |

For REQ-195, consent reaches a temporary device only through the user's own environment setup. REQ-061 extends the constraint already built for 0.1.0 hooks to the sync gateway client; it does not claim the new client is built.

## Success measures

These are the success measures originally approved for the repository's one-week trial. On 2026-11-04 the maintainer removed the C1 trial (TASK-029/TC-114) and chose to proceed with development. After TASK-028, TASK-057 and the checks/reviews, TASK-030 records go/no and known issues, then tags 0.2.0 without another question unless the walks found new recording loss. Curation/recall quality targets remain; on 2026-11-05 the maintainer chose an agent-run short real-conversation sample evaluation for C2 and deferred C3 evaluation to its D3 server design:

| Measure | Target | How it is measured |
| --- | --- | --- |
| Explaining again | At most once a day, something said in an earlier session of the project had to be explained again | The agent classifies cases in short sample replays and records the observed temporal/sample scope and unmeasured limits |
| Useless injection | At most one prompt in five gets an item that does not matter for it | The agent judges at least 30 real prompts with what was injected, recording rationales/ambiguous cases separately from automatic metrics |
| Taken-back memory | No superseded or withdrawn item is ever injected | Code check over the injection log |
| Wrong attribution | No user decision quotes anyone but the user | Code check over the items, and the sample above |
| Speed | REQ-011 and REQ-034 are met | Hook timings in the status |
| Cost | Usage is visible for every call; the estimate is about 3 dollars a month | The usage log |
| Interruptions | Memory never stops or blocks a session | Failures in the status |

## For the checkpoint

Passed on 2026-10-27: D1, D2 and D4 as recommended, and D3 as the new option above; 100-day default raw retention (REQ-009); recording only prompts and final answers (REQ-004); the one-week trial on this repository and its success measures; and the seven requirement changes of the functional spec. Consent version 1 was to cover C2's external sending; the maintainer replaced this on 2026-11-06, and 0.3.0 asks again with version 2 (stage 06). Curation keeps Haiku 5.5 xhigh, compared with medium in the trial. The Git sync details are superseded; the server sync design needs its own confirmation before C3.

2026-11-04 amendment: the 2026-10-27 approval above remains a historical record. C1's one-week trial is removed; the maintainer's 12:26 decision to proceed and 12:44 approval to tag immediately after passing checks now govern C1. This does not remove the C2/C3 trial plans.

2026-11-05 decision: the maintainer chose a short C2 real-conversation sample evaluation instead of a one-week trial and delegated the tests to the agent. The agent selects and locally redacts representative samples, records automatic measurements separately from agent quality judgements, and does not label those judgements as human acceptance. TASK-048 retains at least 30 judged prompts. TASK-050 reports all seven measures after implementation/verification, with observed scope, sample size, costs and explicit unmeasured limits; a short replay is not proof of a week of live use or a measured month of billing. Existing quality targets remain: an unobserved time-based target is recorded as unmeasured, never silently passed. C3 evaluation is set with the D3 server design, while TASK-055 remains superseded Git history. The agent prepares go/no evidence and a recommendation; the existing release decision/tag authorization remains separate. Optional 4/9-week checks are not enabled by this decision.
