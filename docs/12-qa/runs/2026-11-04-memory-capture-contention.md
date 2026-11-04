# C1 recording contention follow-up

2026-11-04 · TASK-030, TASK-066, TASK-067 · SPEC-008, SPEC-009 · API-005 · TC-336, TC-337 · issue #101. Base main `fd115097f5a4034b2641228edc3de0e9f52ce5f2`; candidate `raw_rewrite.py` SHA256 `2b9d42ae89ec100c4e25832a8bf1167b6217ab9f5262bc0e07c249cbb5b92511`.

The maintainer chose to fix recording loss before tagging 0.2.0. The release remains no-go until the fix, reviews, checks and new-main release qualification finish. No tag is established by this report. TASK-028 and TASK-057 remain completed; this follow-up adds no acceptance-case or task completion count.

## Reproduction and scope

[Shared evidence](2026-11-04-memory-capture-contention.evidence.json) binds all 45 original MEMORY files and retains the three old/candidate results, native exits, safe failure metadata and raw-lease intervals. Only `raw_rewrite.py` changes among those original files. These are disposable made-up stores, real hook/worker subprocesses and QA trace wrappers; there is no real-model or user-store claim and no network/model request.

A prestarted prompt hook pauses before redaction. The actual worker opens its scheduling gate after acquiring raw, then continues without an artificial hold. The hook resumes with its original post-redaction 50ms recording wait. Delegating entry/method wrappers add observation overhead: these intervals are not pristine performance samples and do not identify the holder of the earlier administrative/compact/Linux failures.

| Aligned trial | Old prompt retained | Candidate prompt retained | Hook / worker exit |
| --- | --- | --- | --- |
| 1 | no; lock-busy | yes; no failure | 0 / 0 in both |
| 2 | no; lock-busy | yes; no failure | 0 / 0 in both |
| 3 | no; lock-busy | yes; no failure | 0 / 0 in both |

This establishes one reproducible internal contention path, rather than the cause of every historical #101 observation. The unchanged old entry points are delegated by the wrappers; original input and worker logic are used. The source map does not describe the QA shims themselves as pristine installed files.

## Change and regression boundaries

Previously even a wholly fresh log was rebuilt, fsynced and replaced, and curation progress was rewritten under raw. Now snapshot staging and fsync precede raw. A needed conservative progress write occurs between two raw validations, with raw released for durability; a later refusal may only cause re-curation. Already equal progress and unchanged raw files are preserved. The marker callback still holds raw. Deleted-file progress-key cleanup follows raw release, preserving a new append and its marker in that interval.

Late bytes retain the original atomic suffix rule: a real rewrite carries and fsyncs them while holding raw. Moving that durability outside raw and repeatedly deferring on growth could starve retention under continuous appends; that experiment was rejected. The 50ms total maintenance acquisition-wait budget is shared across at most two raw acquisitions; exhausted budgets use a nonblocking attempt. The existing phase deadline and hook's own 50ms wait do not change. This does not promise lossless capture under every foreign lock, large-file scan, slow suffix/backup operation, OS scheduling delay or filesystem failure.

An independent source review also found that the final backup/commit interval needed its own staging-stamp guard. Both primary unlink and each replace retry now revalidate it. Two regressions change a staging file in place during backup or deletion cleanup; frozen v1 fails both before this correction.

Regression tests hand a real append process the snapshot and progress durability intervals, for fresh and expired data. Separate cases retain orphan-marker repair, second-acquisition refusal, staging FD/identity checks, and a new seq=1 append between deletion and progress cleanup. The continuous-append stress now adds an expired seed on every attempt and checks raw inode replacement on success, so its 100 successes are actual rewrites. Its 500-attempt, 120-second and 10ms writer bounds remain unchanged; acknowledged appends must all survive. Intentional 50ms lock skips remain separately reported.

The historical missing optional Codex SessionEnd receipt (#113), active-recording purge (#112), performance and platform issues remain open. A fresh passing capture does not close those original observations. This patch adds no fabricated End entry, recording spool, extra retry of a host measurement or relaxed performance threshold.
