# NEXUS core integration draft, 2026-11-04

TASK-244/245/247 draft under the maintainer's 2026-11-04 instruction. This branch starts at integration commit d4f4e998, containing main20f8725. Main is unchanged. The MEMORY owner handles the0.2.0 tag and PR C; TASK-246 and the final version choice follow that merge.

The portable skill-local workflow covers one to-do read per session/project, explicit user work first, unavailable tokens, claims/PR holds, decisions, accepted reflections, repository records, checkpoint withdrawal and first-send confirmation. Existing stage procedure steps and the eight principles are unchanged. Source annotations are drafted against the hub's existing0.2 parser; no new stage key or snapshot schema is introduced.

Before completion: integrate the MEMORY0.2.0/PR C main, finish TASK-246, choose the next core minor version from that actual main and update both manifests/all nine skill versions together. Run actual-model workflow checks, full Python and strict plugin checks, all three CI operating systems, and independent Code/Security review. Draft content alone does not close a QA case or authorize main merge. Product hub pin changes require their own exact compatibility check.

The hub stays0.2.0. Server-first rollout, after-body processing<1s, Access-protected same-origin hashed-code caching and migration/recovery are described in the product repository. Release is conditional on all authorized gates; first real repository upload and deletion of the retained Worker/D1 remain separate confirmations.

After the repository split, this repository declares only `parts: ["memory"]`; the product repository already declares `parts: ["nexus"]`. NEXUS source/records are not recreated here. The latest main's four project approval categories and all MEMORY stage notes remain intact. No existing MEMORY machine stage file was found in the checkout, reachable Git history or retained hub fixtures; those fixtures are synthetic, not MEMORY progress evidence. No `done` record is invented. The confirmed MEMORY source states remain in its own WBS/QA/flow checkpoint records. Missing machine records mean unknown/not recorded and may be populated only from verified approval evidence. TASK-246's former two-part monorepo wording follows the approved source split rather than duplicating another product's records.


## Base refresh after PR C

The MEMORY0.2.0 tag targets c98306b; PR C#116 merged to main1bec07c. This work integrates that main above NEXUS integration PR117 merge d765a539, then reapplies the preserved draft. The sole project.json conflict retains both the latest project approval categories and NEXUS source-extraction notes. The actual main core0.6.0 makes this the next minor0.7.0; both manifests/all nine skill versions move together. Hub0.2.0 and the MEMORY0.2.1 package are unchanged. TASK246 documentation/examples connect part records, explicit terms:none and approval categories without inventing completed states or approval evidence. Full checks, actual-model walks, independent reviews and CI are still pending on this final combined tree.
