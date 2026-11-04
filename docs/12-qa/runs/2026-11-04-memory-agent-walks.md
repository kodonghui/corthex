# C1 actual-model walks on Windows

2026-11-04 · TASK-057 · base main `70128f321dacaf53002c569023e9e904cb422cb8`. Claude Code 2.1.310 and Codex 0.164.0, Korean and English. All conversations, projects and memory stores are disposable made-up data.

## Qualification

The hosts used their own real models/accounts. C1 memory did not call curation, embedding or sync APIs; real-user memory was not enabled. No authentication file was copied between devices and none is included in the shared evidence.

Observations span the base commit and working SKILL fixes. Per-profile original45 digests and recorded installed46 maps are retained. The initial four sets have installation/observation evidence, not a retrospectively verified full installed-byte map. All44 original files other than SKILL match the final candidate. Consent/exclusion guidance was rewalked in four fresh installations with final SKILL `4d4332063472d52230a5ce88b3ff5d3bb4d9354e069fc7ec40e6270b4391f2e1`. This report does not claim a release-commit rewalk or a completed tag.

[Shared evidence](2026-11-04-memory-agent-walks.evidence.json) contains sent prompts, actual replies, original-hook input/output, raw changes, protected-file digests and independent reviews. Locate each R number and profile/label key. Only fixture paths and the made-up key shape are normalized; original artifact SHA256s remain distinct from the shared representation.

The integration base is `20f8725e8611946806fdd4685999696b29668331`. It includes core guide changes merged during the walks; the 44 non-SKILL MEMORY files remain unchanged. Most cells have one scripted scenario per host/language; retries and before/after guidance variants are separate evidence. No statistical model-quality rate is estimated.

## Run list

All 28 rows have four host/language verdicts. Works qualifies only the stated evidence, not a whole flow or C2. Blocked reasons are in the evidence. R27 retains the active-recording purge failure; success after an explicitly requested off is a separate workaround.

| ID | Flow / path | Codex KO | Claude KO | Codex EN | Claude EN |
| --- | --- | --- | --- | --- | --- |
| R01 | FL-001 · The folder is in a project, and the user consents with both memory keys set | works | works | works | works |
| R02 | FL-001 · The folder is in no project | works | works | works | works |
| R03 | FL-001 · The user does not consent | works | works | works | works |
| R04 | FL-001 · A memory key is missing, or set only under another name | works | works | works | works |
| R05 | FL-001 · A temporary device, set up by a script | blocked | blocked | blocked | blocked |
| R06 | FL-002 · A prompt and its final answer are recorded | works | works | works | works |
| R07 | FL-002 · The folder is in no enabled project | works | works | works | works |
| R08 | FL-002 · The folder, the prompts or the final answers are left out | works | works | works | works |
| R09 | FL-002 · An entry cannot be written | works | works | works | works |
| R10 | FL-002 · The turn ends without a final answer | works | works | works | works |
| R11 | FL-002 · The session is cut off | works | works | works | works |
| R12 | FL-003 · The start summary gets memory's part | works | works | works | works |
| R13 | FL-003 · The folder is in no enabled project | works | works | works | works |
| R14 | FL-003 · Session boundaries are left out | works | works | works | works |
| R15 | FL-003 · The memory store cannot be read, or not in time | blocked | blocked | blocked | blocked |
| R16 | FL-003 · Curation failed, stopped, or waits for consent or a key | blocked | blocked | blocked | blocked |
| R17 | FL-003 · Consolidation is due | blocked | blocked | blocked | blocked |
| R18 | FL-003 · Retention deletes old entries in the background | works | works | works | works |
| R19 | FL-010 · The memory status is shown | works | works | works | works |
| R20 | FL-010 · A step waits for consent or a memory key | blocked | blocked | blocked | blocked |
| R21 | FL-010 · The fault guard stopped a project, and the user resumes it | blocked | blocked | blocked | blocked |
| R22 | FL-010 · The user does not resume, or confirms too late | blocked | blocked | blocked | blocked |
| R23 | FL-011 · Memory is turned off for the project | works | works | works | works |
| R24 | FL-011 · The plugin is removed | works | works | works | works |
| R25 | FL-011 · All memory is deleted after the user's yes | works | works | works | works |
| R26 | FL-011 · The user does not confirm | works | works | works | works |
| R27 | FL-011 · Sync was on | fails | fails | fails | fails |
| R28 | FL-011 · One project's memory is deleted | blocked | blocked | blocked | blocked |

## Retained failures and exceptions

- #110: Initial consent controls/project deletion and missing-key setup location were omitted. Four fresh fixed-guidance sets passed independent review.
- #111: Missing both-text-excluded warning and incorrect off-to-record advice. Four fresh fixed-guidance sets passed independent review.
- #112: Active recording changes a purge proposal from e.g.23 to27 entries; all four confirmations honestly return confirm-stale. Explicit off followed by a fresh proposal/Yes succeeds, and all four installed hooks leave no store. An earlier malformed sync:true fixture is a separate setup mistake, not sync-on proof.
- #113: The English on-state Codex terminal run has no observed End/raw End after normal /quit/exit0, including later observations/snapshots. Cause is unresolved; all three prompt/final pairs and start summaries are present. Both clean cancellations retain start/prompt only, so no End is claimed there. A separate quiet fresh-session success does not resolve the earlier gap.
- Two later administrative prompts were skipped with explicit lock-busy: codex-en-keys-present/sync-purge-yes(476ms) and claude-en-keys-present/purge-off-preview(543ms). Raw/diagnostics are retained; the lease holder and maintenance cause are not established. Track alongside #101, without assigning the cause of #98.
- An unmatched private tag in one enable reply causes the specified redaction of its remaining text; it is not unexplained normal-answer loss. File-sharing denial, max-turns and forced owned-session interruption are intentional controls, kept distinct from ordinary write failures.

## Start summaries and finalization

The 48 cells cover startup/resume/clear/compact × on/no-consent/unreadable × both hosts/languages. Each profile retains the exact base; UTF8 lengths are2110–2119 on,2241–2250 no-consent,2022–2031 unreadable, all below8000. The initial on-yes resume precedes activation; the on/resume evidence is the later sync-purge-preview. Codex KO’s initial update-modal attempt(exit1/0hooks) is retained; only retry qualifies. Passing start summaries do not close #113’s End gap.

## CI replays and limits

New walk_replay.py runs nine native turns per installed host/language profile(36 total) against fixed loopback replies: withheld consent, no project, key presence, private spans, folder/kind/boundary exclusions, status, off, confirmed purge and the installed no-store gate. The four Windows and four Linux sets pass. It does not certify real-model translation/consent semantics. Existing native tool/lifecycle checks remain; exceptional writes/retention/incomplete turns/interruption/redaction and qualification guards also run as real subprocess API regressions in the same hook job.
Replay pacing declares lifecycle_prompt.py’s completed-start/quiet-lease precondition and leaves original product children unchanged. It proves neither timing nor a race fix. The first two replay attempts incorrectly required every file unchanged after off; they remain failed. Real SessionStart maintenance can refresh curation.json. The final check preserves current header/config/raw/layer and records auxiliary changes. The 100-sample,50ms append-wait and retention-stress bounds are unchanged.

## Impressions and release status

The long consent explanation preserves required disclosures; readability is a separate impression. Windows python3 launcher fallback noise appears in host hook_response; clean original-child stderr is not whole-launcher silence. Reusing the local package after uninstall is explicitly authorized in the later prompt.
No tag exists yet. TASK-029/TC-114 become removed history under the2026-11-04 decision; TASK-030 owns go/no. Final checks/reviews and the one pretag maintainer answer about the new recording/finalization findings remain. PR C then the C2 specification are authorized while waiting. Ask once at the C2 split about TASK-047/048 data and TASK-050/055 trials.

Shared evidence SHA256: `61e69c82e014da5fa56da4764b3cd9baf408141c83ab67ae18934a98b49c781d`.
