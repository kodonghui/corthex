# NEXUS: work breakdown

[한국어](nexus.ko.md)

Stage 10 of CORTHEX’s own project. Status: draft for the maintainer’s plan checkpoint, 2026-11-03. English is the source; the Notion databases follow it (`truth: source`). Implementation is authorized now on `codex/nexus-0.2`; the maintainer may adjust this plan while the first trials and migrations proceed. Main merge, production deployment and release tags wait for C1 0.2.0 and the maintainer’s release confirmation.

Inputs: [functional spec](../04-functional-spec/nexus.md), [schema](../05-erd/nexus.md), [API contract](../06-api/nexus.md), [screens](../08-screens/nexus/README.md), [mockups](../09-mockup/nexus/README.md) and their Notes for later stages. All 01–09 checkpoints passed on 2026-11-03. SPEC-134 and SPEC-142 stay phase ②; the tables retain their future fields.

## How to read this file

`ID` is permanent, starting at TASK-201. `Task` is one independently testable slice. `From` names its SPEC/REQ. `Touches` names its interfaces, data or screens. `Depends on` must finish first; named C1/PR gates are external prerequisites. `Owner: agent` means the implementing Codex, with account operations delegated to Aside on this host. `Estimate` is changed code plus meaningful tests: S about 300 lines, M about 800, L about 2,000; split a larger slice before starting it. `Done when` is evidence another reviewer can check. `Status` is todo, in progress, done (#N), or removed (date), preserving IDs.

A request task is done only when each response it lists has a passing test; development API evidence, mock UI evidence, automated page checks and visual review are reported separately. A task that awaits cross-OS/live evidence remains in progress. Every commit runs AGENTS.md checks. Each bundle targets the integration branch and merges only after all-checks and code/security reviews.

Current plan: 54 tasks (S 7, M 39, L 8). The [QA plan](../12-qa/nexus.md) lists 679 cases from acceptance criteria, named responses, command outcomes, screen states and cross-cutting scenarios.

## Server

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-201 | Trial both Access identities | SPEC-113, SPEC-116 | API-101–API-104 | none | agent | M | Real development Access returns presence/absence of ctx.access, aud, sub, email and common_name for both identities; document the selected verifier before authentication code. | done (#92) |
| TASK-202 | Preserve the phase-1 database as migration 1 | SPEC-114 | TBL-101, TBL-113 | none | agent | S | An empty and an existing phase-1 database acquire migration 1 atomically; existing snapshot bytes and revisions remain unchanged. | done (#91) |
| TASK-203 | Apply schema migration 2 | SPEC-114 | TBL-101–TBL-113 | TASK-202 | agent | M | Migration output and nexus.sql agree on tables, columns, primary/foreign keys, indexes and CHECK constraints; concurrent/failing migration retries leave no partial schema. | done (#91) |
| TASK-254 | Persist reflection report identity | SPEC-133 | TBL-109, API-126 | TASK-203 | agent | S | Migration 3 preserves schema-2 entries and stores only internal last-report metadata; a repeated closed report differs from an invalid first closed report, even after write IDs expire. | in progress |
| TASK-204 | Validate snapshot 0.2 and picture sources | SPEC-104, SPEC-105, SPEC-109, SPEC-110, SPEC-114 | API-105, TBL-114 | TASK-203 | agent | M | Both snapshot versions and every source shape meet the frozen contract, UTF-8 and limits; unknown snapshot fields survive and picture sources are separated from stored snapshots. | in progress |
| TASK-205 | Store guarded pushes and held commits | SPEC-111, SPEC-112, SPEC-114, SPEC-117, SPEC-118, SPEC-140 | API-105, API-109, TBL-101–TBL-104, TBL-110 | TASK-204, TASK-206 | agent | L | All API-105/API-109 responses pass, including interleaved push batches, repository binding, same/older times, unchanged pictures and recorded checkpoints; overtaken pushes write no rows. | in progress |
| TASK-206 | Pair pictures and reconcile discrepancies | SPEC-120, SPEC-121 | TBL-103, TBL-104 | TASK-204 | agent | M | All five mismatch kinds, removed terms, explicit none/exemptions, waiting pictures, reopening and 1,000-open limits match SPEC-120/121 with deterministic pair keys. | in progress |
| TASK-207 | Remove projects with a dry run | SPEC-115 | API-108, API-110, TBL-101–TBL-112 | TASK-205 | agent | S | Every response is checked; the dry run reports bounded IDs and totals; removal leaves no project row in any table. | in progress |
| TASK-208 | Read spaces, pictures, overviews and entries | SPEC-119, SPEC-123, SPEC-127, SPEC-130, SPEC-133, SPEC-138, SPEC-140 | API-106, API-107, API-111, API-112, API-114–API-117 | TASK-205 | agent | L | Each listed response and HEAD is tested; totals, ordering and limits match the contract, and full proposal text appears only in its own read. | in progress |
| TASK-209 | Verify Access and dispatch paths and roles | SPEC-113, SPEC-116 | API-101–API-132 | TASK-201 | agent | M | Use the real-trial decision; wrong app/kind, path/method/origin and session refusals follow the contract order and change no data. | in progress |
| TASK-210 | Return Problem Details and safe trace logs | SPEC-113 | API-101–API-132 | TASK-209 | agent | S | Every emitted error code exists in OpenAPI; status, fields, safe detail and traceId match; only error kind and traceId reach logs. | in progress |
| TASK-211 | Create item and picture comments | SPEC-126, SPEC-128 | API-118, TBL-105 | TASK-208, TASK-221 | agent | M | All API-118 responses and acceptance criteria pass, including missing items, quote requirement, picture version, quotas and UTF-8 text bytes. | in progress |
| TASK-212 | Reply, settle, mark answered and reopen | SPEC-127, SPEC-128, SPEC-132 | API-119, API-120, TBL-105, TBL-106 | TASK-211 | agent | M | All response variants pass; only a user reopens a closed comment and may settle it; waits, dismissed and claim renewal remain correct. | in progress |
| TASK-213 | Record a decision and close its comment | SPEC-132 | API-121, TBL-105, TBL-107 | TASK-212 | agent | S | Every response passes; an agent records the user's decision with a safe HTTPS link, closing an open comment atomically and preserving a closed comment's state. A session decision need not have a prior settling reply. | in progress |
| TASK-214 | Create and withdraw proposals | SPEC-130 | API-122, API-123, TBL-108 | TASK-211, TASK-221 | agent | M | All response variants cover targets, additions, source text, one answer target, limits, claims and idempotent withdrawal. | in progress |
| TASK-215 | Accept or dismiss proposals | SPEC-131 | API-124, API-125, TBL-108, TBL-109 | TASK-214 | agent | M | All responses pass; a user acceptance creates exactly one pending reflection, quotas are atomic and dismissing updates the waiting comment. | in progress |
| TASK-216 | Report or dismiss reflections | SPEC-133 | API-126, API-127, TBL-109 | TASK-215, TASK-254 | agent | M | Every state/event/PR combination and response is checked, including repeat reports, mismatched PR, needs-user and claim release. | in progress |
| TASK-217 | Read the ordered agent to-do | SPEC-135, SPEC-136, SPEC-140 | API-113 | TASK-208, TASK-216, TASK-220 | agent | M | Every response, group ordering, totals, waits, mine/taken and in-review holds match the contract for two sessions. | in progress |
| TASK-218 | Claim and release work for a session | SPEC-136 | API-131, API-132, TBL-111 | TASK-221 | agent | M | Every response passes for two sessions, expiry, renewal, closed entries and reported PR holds; a failed claim is never queued. | in progress |
| TASK-219 | Pass and withdraw stage checkpoints | SPEC-139 | API-128, API-129, TBL-110 | TASK-208, TASK-221 | agent | M | Every response passes, including no default commit, missing parts/stages, repeated withdrawal and recorded checkpoints. | in progress |
| TASK-220 | Report checkpoint record PRs and warnings | SPEC-140 | API-130, TBL-110 | TASK-219 | agent | M | Every report response passes; withdrawal during review remains actionable, and an incorrectly merged record creates checkpoint-withdrawn until corrected. | in progress |
| TASK-221 | Keep writes atomic and replay for seven days | SPEC-126–SPEC-133, SPEC-136, SPEC-139, SPEC-140 | TBL-102, TBL-111, TBL-112 | TASK-203, TASK-209, TASK-210 | agent | L | Each write batch gates mutations on a newly accepted ID, claim/state/quota checks; replay returns the original status/body; expiry and concurrent duplicate submissions change data once. | in progress |
| TASK-222 | Serve HTML refusal pages and code securely | SPEC-113, SPEC-119, SPEC-138 | API-101–API-104 | TASK-209, TASK-210 | agent | M | Browser Accept gets the localized one-message HTML page; APIs/code retain Problem Details; all headers, HEAD and content-digest code caching pass. | in progress |

## Trials

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-223 | Measure the largest development push | SPEC-114, SPEC-118, SPEC-121 | REQ-081, REQ-124, API-105 | TASK-205 | agent | M | Record synthetic 1,000,000-byte/3,000-item/2,000-check and three-picture load, CPU, D1 queries and rows on development; compare 10 ms/50 queries without changing frozen limits. | in progress |
| TASK-224 | Trial mobile editors, CSP and Worker size | SPEC-119 | REQ-146–REQ-149, API-104 | TASK-222 | agent | L | Pin editors/React and licenses; serve all code/fonts through Worker; record gzip/raw sizes, current free Worker limit, CSP and 20 mobile/4G openings, P95 <=3 seconds for 300 elements or seek the maintainer decision. | in progress |

## Hub

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-225 | Read default-branch Git objects and group parts | SPEC-104, SPEC-105 | API-133, TBL-114 | none | agent | M | Branch/uncommitted changes cannot enter pictures; canonical origin, default commit/time, longest part prefix and each omission/check are tested without executing hooks/filters. | todo |
| TASK-226 | Parse DDD boards and timelines | SPEC-106 | API-133, TBL-114 | TASK-225 | agent | M | English/Korean template fixtures and NEXUS itself yield contexts, rows/policies, aggregates/read models/terms, dependencies, hotspots and all five ordered timeline lanes. | todo |
| TASK-227 | Parse ERD SQL picture sources | SPEC-107 | API-133, TBL-114 | TASK-225 | agent | M | Template SQL and nexus.sql preserve column types/nullability, primary/unique/foreign keys, partial indexes, contexts/terms and without_table exemptions. | todo |
| TASK-228 | Parse nested sitemap picture sources | SPEC-108 | API-133, TBL-114 | TASK-225 | agent | M | Template YAML and nexus.yaml preserve parents, paths/access/flows/status, contexts/terms/none, without_screen and partial-source checks using standard-library Python. | todo |
| TASK-229 | Read stage records from default branch | SPEC-109 | API-133, TBL-115, TBL-116 | TASK-225 | agent | M | Part-specific records override device status, invalid records stay unknown with checks, fallback is explicit and done needs a dated checkpoint. | todo |
| TASK-230 | Apply settings, redaction and snapshot limits | SPEC-104, SPEC-110 | API-133, TBL-114 | TASK-226, TASK-227, TASK-228, TASK-229 | agent | M | Snapshot 0.2 and all five new check families pass; default ask_before equals the core example; largest-first whole-picture omission precedes item/check truncation; no paths/secrets leave fixtures. | todo |
| TASK-231 | Write repository stage records with status | SPEC-109, SPEC-137, SPEC-140 | API-134, TBL-115 | TASK-229 | agent | M | Every status outcome passes for parts/fallback, list checkpoints and NEXUS links; atomic LF JSON writes preserve another part and never commit or push. | todo |
| TASK-232 | Push by ancestry and remove after dry run | SPEC-111, SPEC-112, SPEC-115 | API-136, API-137 | TASK-230, TASK-233, TASK-234 | agent | M | All command outcomes pass for no held snapshot, same/child/ancestor/diverged/missing commits, equal parent-child times, replace-held and protocol 0.1 refusal. | todo |
| TASK-233 | Provide safe HTTP, session and JSON outcomes | SPEC-128, SPEC-135 | API-136–API-150 | none | agent | M | No redirect is followed, only configured URLs/projects receive tokens, session/text/file inputs are validated/redacted and outcomes/exit codes match the contract. | todo |
| TASK-234 | Persist and drain the seven-day outbox | SPEC-129 | API-150, TBL-117 | TASK-233 | agent | M | Each outcome, retry status, token/network failure, expiry, permanent refusal, oldest-first stop and two-hub exclusive lock is tested; queued files contain no credentials. | todo |
| TASK-235 | Implement the agent commands and references | SPEC-127–SPEC-133, SPEC-135, SPEC-136, SPEC-140 | API-138–API-149 | TASK-233, TASK-234 | agent | L | Every documented command/result has a test; OutboxFile request names agree with OpenAPI; snapshot.md, reading.md and hub skill describe 0.2. | todo |

## Views

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-236 | Generate CSS properties from frozen tokens | SPEC-119, SPEC-123, SPEC-138 | SCR-101, SCR-104–SCR-109 | none | agent | S | Resolver order applies base then selected theme; properties cover both themes and each color/length used by the new UI; recomputed contrast pairs are recorded. | todo |
| TASK-237 | Extend the hub page for NEXUS 0.2 | SPEC-123, SPEC-124, SPEC-125 | API-101, API-135, SCR-101, SCR-104 | TASK-236, TASK-208, TASK-230 | agent | M | Parts, pictures, counts, pending/withdrawn checkpoints, ask_before and empty-server guidance match every state; local page stays offline and copied HTML agrees. | todo |
| TASK-238 | Draw read-only pictures with fallback lists | SPEC-119 | API-102, API-104, API-111, SCR-105 | TASK-224, TASK-236 | agent | L | Prism-driven states render all three sources deterministically; editor failure preserves the accessible item list and size-stable named marks; pan/zoom remain within the frame. | todo |
| TASK-239 | Show the five DDD board steps | SPEC-141 | SCR-105 | TASK-238 | agent | M | Timeline/context-derived five layouts match mockups, first/last controls and absent timeline work, and step hash opens/restores without saving positions. | todo |
| TASK-240 | Build item and comment panels | SPEC-126, SPEC-127, SPEC-132 | API-114, API-118–API-120, SCR-106, SCR-107 | TASK-238, TASK-243 | agent | M | Each state follows its mock response, hashes open/close panels, reply/reopen/settled states work at both widths and full proposal text is not loaded early. | todo |
| TASK-241 | Build proposal and reflection panels | SPEC-130, SPEC-131, SPEC-133 | API-115, API-116, API-124, API-125, API-127, SCR-108 | TASK-238, TASK-243 | agent | M | All proposal/reflection states and stale races match Prism; accept/dismiss re-read data and display PR/reflection status with text safely. | todo |
| TASK-242 | Build the stage overview and checkpoints | SPEC-138, SPEC-139, SPEC-140 | API-103, API-112, API-128, API-129, SCR-109 | TASK-236, TASK-243 | agent | M | All overview states, recorded state plus unrecorded checkpoint, withdrawal and warning states follow the contract at both widths. | todo |
| TASK-243 | Keep drafts, IDs and request recovery | SPEC-126, SPEC-127, SPEC-131, SPEC-139 | SCR-105–SCR-109 | TASK-236 | agent | M | Requests use manual redirects and 30-second aborts; draft plus write ID survives reload, lost responses replay once, opaqueredirect/401 preserve text and stale writes reload safely. | todo |

## Core after C1

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-244 | Read agent work from entry and stage skills | SPEC-112, SPEC-135, SPEC-136 | REQ-181, REQ-185, plugins/corthex | C1 0.2.0 tag, PR C, PR D (#83), TASK-235 | agent | M | Merge latest main first; once/session/project to-do reads prioritize explicit user work, absent tokens do not stop work and claims/holds are respected. | todo |
| TASK-245 | Teach stage records, reflection and timeline steps | SPEC-106, SPEC-132, SPEC-133, SPEC-137, SPEC-140 | REQ-086, REQ-131, REQ-154, REQ-167, REQ-168, REQ-212 | TASK-244, TASK-231 | agent | M | Update stage references, stage-contract where needed, hub stage table and template-reading tests together; write work/checkpoints by PR and verify standing before merge. | todo |
| TASK-246 | Document project parts and ask_before | SPEC-110, SPEC-137 | plugins/corthex, .corthex/project.json, TBL-115 | TASK-244 | agent | S | After PR C, project reference/examples and sitemap terms/status agree; repository parts memory/nexus and both stage records preserve latest MEMORY source states. | todo |

## Integration

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-247 | Prepare versions, guides and architecture | SPEC-113, SPEC-137 | REQ-126, manifests, README pairs, NOTICE | TASK-245, TASK-246, TASK-237, TASK-242 | agent | M | NEXUS 0.2.0 and next main core version agree in both manifests/all skill metadata; bilingual guides describe dev, migrations and server-first upgrades; no production deploy/tag. | todo |
| TASK-253 | Reconcile main and hand over release evidence | SPEC-104–SPEC-141 | docs/10-wbs/nexus.md, docs/12-qa/nexus.md, draft PR | TASK-247, TASK-249, TASK-250, TASK-251, TASK-252 | agent | M | All source tasks/results and Notion copies agree; latest-main full checks name the exact tree; draft lists bundle PRs/design changes/untested work and waits for release, main merge, deploy and tag confirmation. | todo |

## QA

| ID | Task | From | Touches | Depends on | Owner | Estimate | Done when | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TASK-248 | Run pinned contract validation and mocks | SPEC-113–SPEC-140 | API-101–API-132 | TASK-222 | agent | M | External pinned validator 0.7.1, Prism 5.16.0 and Schemathesis 3.39.16 hooks cover Access cookie/path/header substitutions; live development contract run names commit and mock-only results separately. | todo |
| TASK-249 | Fire every named server response | SPEC-104–SPEC-140 | API-101–API-132 | TASK-217, TASK-218, TASK-220, TASK-248 | agent | L | Each named example is reproduced on development where feasible, with schema/code/effect checked; default/internal mock cases remain counted apart. | todo |
| TASK-250 | Verify hub commands on three operating systems | SPEC-104–SPEC-140 | API-133–API-150 | TASK-231, TASK-232, TASK-235 | agent | M | Python 3.8 and latest matrix on Windows/macOS/Linux passes all command outcomes and preserves no-network/no-token fixture isolation. | todo |
| TASK-251 | Walk flows and all screen states | SPEC-119, SPEC-123–SPEC-141 | FL-101–FL-114, SCR-101–SCR-109 | TASK-237, TASK-239, TASK-240, TASK-241, TASK-242, TASK-249 | agent | L | Browser testers record role/path/commit and evidence for 320/1440, both themes/languages; page checks and image review are separate; working browser paths become CI e2e tests. | todo |
| TASK-252 | Record performance and own-project cross-check | SPEC-106, SPEC-107, SPEC-108, SPEC-119, SPEC-120 | REQ-124, REQ-149 | TASK-223, TASK-224, TASK-251 | agent | M | Record raw 20-opening measurements/P95, Worker/editor code sizes and maximal push metrics; synthetic plus local NEXUS self-picture check passes without an unauthorized repository upload. | todo |

## Outcomes

The server rows name every declared response. The QA cases also distinguish the named examples of each response; mock-only internal failures are never counted as live passes.

| Interface | Request | Responses | Test-writing task |
| --- | --- | --- | --- |
| API-101 | GET / | 200, 403, default | TASK-237 |
| API-102 | GET /pictures/{project}/{part}/{stage} | 200, 403, 404, default | TASK-238 |
| API-103 | GET /overview/{project}/{part}/{stage} | 200, 403, 404, default | TASK-242 |
| API-104 | GET /code/{file} | 200, 403, 404, default | TASK-222 |
| API-105 | POST /api/snapshots | 200, 400, 403, 409, 413, 415, default | TASK-205 |
| API-106 | GET /api/snapshots | 200, 403, default | TASK-208 |
| API-107 | GET /api/snapshots/{project} | 200, 403, 404, default | TASK-208 |
| API-108 | DELETE /api/snapshots/{project} | 200, 403, 404, default | TASK-207 |
| API-109 | GET /api/snapshots/{project}/held | 200, 403, 404, default | TASK-205 |
| API-110 | GET /api/snapshots/{project}/removal | 200, 403, 404, default | TASK-207 |
| API-111 | GET /api/spaces/{project}/pictures/{part}/{stage} | 200, 403, 404, default | TASK-208 |
| API-112 | GET /api/spaces/{project}/overview/{part}/{stage} | 200, 403, 404, default | TASK-208 |
| API-113 | GET /api/spaces/{project}/todo | 200, 400, 403, 404, default | TASK-217 |
| API-118 | POST /api/spaces/{project}/comments | 201, 400, 403, 404, 409, 413, 415, default | TASK-211 |
| API-114 | GET /api/spaces/{project}/comments/{comment} | 200, 403, 404, default | TASK-208 |
| API-119 | POST /api/spaces/{project}/comments/{comment}/replies | 201, 400, 403, 404, 409, 413, 415, default | TASK-212 |
| API-120 | POST /api/spaces/{project}/comments/{comment}/answered | 200, 400, 403, 404, 409, default | TASK-212 |
| API-121 | POST /api/spaces/{project}/comments/{comment}/decisions | 201, 400, 403, 404, 409, 413, 415, default | TASK-213 |
| API-122 | POST /api/spaces/{project}/proposals | 201, 400, 403, 404, 409, 413, 415, default | TASK-214 |
| API-115 | GET /api/spaces/{project}/proposals/{proposal} | 200, 403, 404, default | TASK-208 |
| API-123 | POST /api/spaces/{project}/proposals/{proposal}/withdraw | 200, 400, 403, 404, 409, default | TASK-214 |
| API-124 | POST /api/spaces/{project}/proposals/{proposal}/accept | 200, 400, 403, 404, 409, default | TASK-215 |
| API-125 | POST /api/spaces/{project}/proposals/{proposal}/dismiss | 200, 400, 403, 404, 409, default | TASK-215 |
| API-116 | GET /api/spaces/{project}/edits/{edit} | 200, 403, 404, default | TASK-208 |
| API-126 | POST /api/spaces/{project}/edits/{edit}/report | 200, 400, 403, 404, 409, 413, 415, default | TASK-216 |
| API-127 | POST /api/spaces/{project}/edits/{edit}/dismiss | 200, 400, 403, 404, 409, default | TASK-216 |
| API-128 | POST /api/spaces/{project}/checkpoints | 201, 400, 403, 404, 409, 413, 415, default | TASK-219 |
| API-117 | GET /api/spaces/{project}/checkpoints/{checkpoint} | 200, 403, 404, default | TASK-208 |
| API-129 | POST /api/spaces/{project}/checkpoints/{checkpoint}/withdraw | 200, 400, 403, 404, 409, default | TASK-219 |
| API-130 | POST /api/spaces/{project}/checkpoints/{checkpoint}/report | 200, 400, 403, 404, 409, 413, 415, default | TASK-220 |
| API-131 | POST /api/spaces/{project}/claims/{entry} | 200, 400, 403, 404, 409, default | TASK-218 |
| API-132 | DELETE /api/spaces/{project}/claims/{entry} | 200, 400, 403, 404, 409, default | TASK-218 |

| Interface | Command | Outcomes | Test-writing task |
| --- | --- | --- | --- |
| API-133 | snapshot | done; invalid CLI; failed | TASK-230 |
| API-134 | status | done; invalid CLI; failed | TASK-231 |
| API-135 | build | done; invalid CLI; failed | TASK-237 |
| API-136 | push | done; invalid CLI; failed; refused | TASK-232 |
| API-137 | remove | done; invalid CLI; failed; refused | TASK-232 |
| API-138 | todo | done; invalid CLI; failed; refused | TASK-235 |
| API-139 | comment | done; invalid CLI; failed; refused; kept | TASK-235 |
| API-140 | reply | done; invalid CLI; failed; refused; kept | TASK-235 |
| API-141 | answered | done; invalid CLI; failed; refused; kept | TASK-235 |
| API-142 | decide | done; invalid CLI; failed; refused; kept | TASK-235 |
| API-143 | propose | done; invalid CLI; failed; refused; kept | TASK-235 |
| API-144 | withdraw | done; invalid CLI; failed; refused; kept | TASK-235 |
| API-145 | reflect | done; invalid CLI; failed; refused; kept | TASK-235 |
| API-146 | record | done; invalid CLI; failed; refused; kept | TASK-235 |
| API-147 | show | done; invalid CLI; failed; refused | TASK-235 |
| API-148 | claim | done; invalid CLI; failed; refused | TASK-235 |
| API-149 | release | done; invalid CLI; failed; refused | TASK-235 |
| API-150 | outbox | done; invalid CLI; failed; refused; kept | TASK-234 |

## Decisions the tasks wait for

- TASK-209 waits for TASK-201’s real Access identity trial. If neither ctx.access nor verified JWT fields distinguish both identities, take the alternatives to the maintainer.
- TASK-238 waits for TASK-224’s mobile/editor and code-size trial. A required additional development dependency, changed editor choice, frozen token change or breached performance limit goes to the maintainer; independent server/hub work continues.
- TASK-244–TASK-247 wait for `corthex-memory--v0.2.0`, PR C and PR D (#83) on main.
- TASK-253 waits for all QA evidence. Release, main merge, production deployment, tags and the first upload of this repository remain explicit maintainer decisions.

## Choices this stage made

1. Keep source-first bilingual files named nexus.md and nexus.ko.md, with Korean Notion reading copies and one database row per task/case.
2. Keep server, hub, views, delayed core and QA slices separate so reviews remain small. Large slices are split before implementation if their measured change exceeds the scale.
3. Use synthetic projects throughout development. NEXUS’s own pictures are compared locally; uploading this repository waits for REQ-107.
4. Keep credentials on this host in the secret store/environment; Aside handles authorized account steps. No key, cookie or authentication file is copied to another device.
5. Keep the frozen 04 rows, 05 schema, 06 contracts and 09 tokens. Meaning-preserving clarifications are documented in both languages before code; breaking changes wait for the maintainer.

## For the checkpoint

Plan awaiting the maintainer, 2026-11-03: 53 tasks, S 6/M 39/L 8. Order: trials and migrations → server → hub → views; core follows C1/PR C/PR D. Three measured trials are Access identities, maximal push CPU/queries, and 20 mobile openings. Aside is assigned the account steps, so no account action is currently requested from the maintainer. Show the Notion reading-copy links when created. The implementation instruction permits trials and migrations while this checkpoint is pending. No approval is inferred from silence.

## Notes for later stages

### Stage 11: development

Use a branch per bundle based on codex/nexus-0.2, identify TASK/SPEC and tests/untested work, and keep design changes in the bundle PR. First push the integration branch, then open its main draft once source changes exist. Every completed task changes here in its finishing PR before the Notion board follows. Merge commits preserve bundle review history. Merge origin/main before shared-file work and before handover.

### Stage 12: QA

Run the [plan](../12-qa/nexus.md) on development behind Access. Record commit, environment and evidence for each pass. Browser testers walk every applicable phase-① flow; pin working paths in e2e CI. Keep live response counts, mock-only counts, page-check measurements and visual review separate. Release decision remains pending.

## Current server implementation

TASK-204–TASK-224 and TASK-254 are in progress. The server router and transactions have local tests and a synthetic development smoke run, but complete per-response contracts, the editor trial and screens remain. See the QA evidence; neither API provision nor screen acceptance is inferred from a test count.
