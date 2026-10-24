# CORTHEX-MEMORY: user flows

[한국어](README.ko.md)

Stage 03 of CORTHEX's own project, for the `corthex-memory` plugin. Status: draft of 2026-10-24. As chosen on 2026-10-24 for the depth of the design, the maintainer reviews these flows together with the functional spec (stage 04). When a file here and its Korean translation differ, the English file is the source.

Inputs: the requirements in [docs/02-prd/memory.md](../../02-prd/memory.md) (REQ-001 to REQ-065), and the contexts and glossary in [docs/01-domain/memory.md](../../01-domain/memory.md), whose meanings the words here keep. The flows assume the recommendations of decisions D1 to D4; FL-004 depends on D2 and FL-012 on D3.

Each flow has its own file with a Mermaid flowchart, and each step names the requirements it serves. To keep its first chart readable, FL-005 draws how one proposed change is applied as a second chart.

| ID | Flow | Context | Starts when |
| --- | --- | --- | --- |
| FL-001 | [Turn memory on for a project](FL-001-turn-memory-on.md) | CTX-005 | The user asks the memory skill to turn memory on |
| FL-002 | [Record a turn](FL-002-record-a-turn.md) | CTX-001 | The user submits a prompt |
| FL-003 | [Start a session with memory](FL-003-start-a-session.md) | CTX-003 | A session starts, resumes, forks, is cleared or is compacted |
| FL-004 | [Recall memory for a prompt](FL-004-recall-for-a-prompt.md) | CTX-003 | The prompt hook has recorded the prompt (FL-002) |
| FL-005 | [Curate new turns](FL-005-curate-new-turns.md) | CTX-002 | A curation trigger is met |
| FL-006 | [Consolidate a project](FL-006-consolidate-a-project.md) | CTX-002 | A session starts a week after the last consolidation |
| FL-007 | [Search memory](FL-007-search-memory.md) | CTX-003 | The user asks the agent to look something up in memory |
| FL-008 | [Pin or unpin an item](FL-008-pin-an-item.md) | CTX-005 | The user asks to pin or unpin an item |
| FL-009 | [Forget an item](FL-009-forget-an-item.md) | CTX-005 | The user asks to forget something |
| FL-010 | [Check the memory status](FL-010-check-the-status.md) | CTX-005 | The user asks for the memory status |
| FL-011 | [Turn memory off](FL-011-turn-memory-off.md) | CTX-005 | The user asks to turn memory off |
| FL-012 | [Sync memory between devices](FL-012-sync-memory.md) | CTX-004 | A sync point is reached |

## Where the flows run

| Moment | Flows |
| --- | --- |
| A session starts, resumes, forks, is cleared or is compacted | FL-003, which may start FL-006 |
| The user submits a prompt | FL-002, then FL-004 |
| A turn ends | the end of FL-002 |
| A session ends | a session boundary in the raw log, the same step as at the start in FL-003 (REQ-003) |
| The user asks the agent, which follows the memory skill | FL-001 and FL-007 to FL-011 |
| In the background, started from one of the moments above | FL-005, FL-006 and FL-012 |

Stage 06 fixes which hook of each host runs which step. The hook tests of 2026-10-23 saw the session start and prompt hooks run in both hosts; the end-of-turn hook has not been seen running yet, so the end of FL-002 rests on the hosts' documentation until stage 12 tests it.

## Requirements that no flow uses

REQ-060 (Linux, macOS and Windows), REQ-061 (Python 3.8 and its standard library), REQ-062 (no root `plugin.json`) and REQ-063 (the store's format version) hold for the whole plugin rather than for one flow. The functional spec states them, and QA checks them. Every other requirement appears in at least one flow.

## Points for the functional spec

Drawing the flows raised these questions, which the requirements leave open:

1. Curation triggers: after a number of turns, after some minutes or at the end of a session (the open question of CTX-002). FL-005 starts at any of them.
2. Devices that disappear: a cloud session runs in a container whose files go when it ends, so its raw log and unprocessed turns are lost unless curation and sync run before the end (REQ-008, REQ-012).
3. Two sessions of one project at once: their appends must not break the raw log (REQ-064), and only one of them curates (REQ-021).
4. A missing key: FL-003 says in the start summary that curation waits for a key, which REQ-029 does not name; it names only failed or stopped curation.
5. Taking an item back: FL-005 marks an item withdrawn only when its own speaker takes it back (REQ-020, TERM-017). The spec decides what happens when the user corrects something the agent said.
6. A tombstone must let the other devices find a forgotten item and the raw text it quotes, without holding that text itself (REQ-045, REQ-054).
7. Quotes shared by items: forgetting one item must not break the provenance of another item that quotes the same raw text (REQ-017, REQ-054).
8. Retention and stopped curation: raw turns that are not processed yet, for example while the fault guard has stopped curation, can reach the 30-day retention (REQ-009, REQ-024).
9. Deleting one project's memory: the requirements only disable a project (REQ-058) or purge the whole store (REQ-055).
10. Size: a single turn that does not fit in one request (REQ-022), and a consolidation with more items than one request holds.
11. A pinned item that is superseded or withdrawn leaves the start summary (REQ-037). Should the pin move to the newer item?
12. Hook timings: the success measures read the speed from the memory status, which REQ-053 does not list.
13. Turning sync on: how the user chooses the sync remote, and how the plugin checks that it is private (REQ-042).
