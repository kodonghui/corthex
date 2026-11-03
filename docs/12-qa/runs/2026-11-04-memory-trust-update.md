# Codex hook trust after the C1 update

[한국어](2026-11-04-memory-trust-update.ko.md)

Observation for TC-107.

This is a qualified Windows observation in a disposable Codex profile, using Codex 0.164.0 and a fixed loopback protocol model. It establishes the trust/update behavior below. It is not a real-user consent, a real-model agent walk, CI performance, a release or a tag.

| Step | Observed result |
| --- | --- |
| Install old source `dfc6a2c68d01c840f41206074b6a498cbf06bf27` | Native `plugin add` reports 0.1.0. The Hooks UI shows one new SessionStart hook, inactive pending review. |
| Review and trust 0.1.0 in the temporary profile | SessionStart changes from Installed 1 / Active 0 / Review 1 to Active 1. A new `exec` without trust bypass sends the legacy CORTHEX context to the loopback model. Legacy 0.1.0 has no C1 raw recording. |
| Replace MEMORY source in the same local marketplace and add again | Native `codex plugin add corthex-memory@corthex --json` reports 0.2.0. All 45 cached product files match actual main commit `2fc4b871873659249e4c43c8b6139c7f5748e186` byte for byte. |
| Start a fresh session before trusting the update | `exec` exits 0 but the memory store gains zero raw entries and zero hook timing rows. No hook-trust bypass is used. |
| Open the native interactive UI | It asks “Hooks need review” and reports four new or changed hooks. SessionStart is labelled modified since last trusted and requiring review. |
| Trust the reviewed C1 hooks in this synthetic profile | The installed hooks become active. The TUI's later shutdown records one metadata-only end boundary after trust. |
| Run a separate Korean native session without trust bypass | The verified CLI session gains matching start, prompt, answer and end records; both boundaries contain no text. Host, session, same-turn Korean text, successful timings and no failure logs are checked. There are five total rows including the earlier post-trust TUI end. |
| Read actual `memory.py status` | Exit 0 / done. All four Codex hook kinds have a last-run timestamp and only ok outcomes. Those internal 1–2 sample timing summaries do not establish the 100-sample external performance requirement. |

The operator was the QA controller in this disposable profile. It did not grant consent for the user's profile or stores. Synthetic `on` consent was recorded separately. Fake keys and only a loopback model were used; provider calls, real account login and global host installation were absent. Host metadata connection attempts were blocked and retained separately from MEMORY egress claims.

The TUI used `--no-daemon`: the long fixture path exceeds Windows' Unix-socket SUN_LEN when starting the managed daemon. The Windows sandbox setup popup was dismissed; no administrator or sandbox installation action was taken. The earlier controller v1 attempts are retained as invalid evidence because of a wrong resumed demo path, daemon path failure and overwritten marketplace configuration. Qualified v2 preserves config across stages.

The canonical completion receipt is `task028-trust-update-v2/complete.json`, SHA256 `e8d255ef3f490c62e13d164eb66a9a08ed2e5776b695f78890af28392018ca26`. It binds native install/exec/status JSON, the captured TUI result chunks and the cached-source proof. The product source is actual merged PR #88. Linux/macOS trust-update execution and Git/Notion case promotion are separate remaining decisions; this report does not infer them from Windows.
