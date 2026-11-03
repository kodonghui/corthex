# A native task notification on Windows

[한국어](2026-11-04-memory-native-prefix.ko.md)

Claude Code 2.1.310 generated a real background-agent completion notification in a disposable Windows profile. Its actual `UserPromptSubmit` hook input starts with `<task-notification>`. MEMORY reports `left-out` for it and preserves exactly the original four raw entries: start, human prompt, final answer (`kind: answer`) and end. No store file contains the notification prefix or the tool-only marker.

This is a fixed loopback-protocol QA probe, not a real-model agent walk or a whole TC-106 verdict. The controller requests the native `Agent` tool, checks the successful native launch result, and matches its task ID to the hook input's completed task. The hook's session ID matches the actual native CLI session. The original product worker remains unchanged. Only synthetic profiles, consent and conversations are used, with fake keys and a local model endpoint; no real provider billing, global install or user-store activation occurs.

The source is QA head `24cc42c5bbb8fe181160528b578ec3d4ebf2e7b8`, with the unchanged product from main `2fc4b871873659249e4c43c8b6139c7f5748e186`. The native session finishes in 2.8 seconds; its prompt timing outcomes are `ok` and `left-out`. This is one observation and no performance percentile.

The qualified receipt is `task028-prefix-v1/qualified.json`, SHA256 `205eb04537d06f3578e1463cb5c337d4de9a76374597329889d63515a7f42618`. The original probe result stays unqualified and unchanged: its model-message first-text collector saw no prefix, while the actual hook input did. Qualification reads the native launch and matching completion input directly. The first qualifier incorrectly expected raw `kind: final`; the real schema uses `answer`. That operator error is retained and corrected without rerunning the native session.

Cross-session and teammate prefixes, Codex notification behavior and Linux/macOS prefix execution are not inferred from this result. The native CLI's displayed cost is an estimate from synthetic usage fields returned by the fixed server; it is not actual provider spending. No task, case, coverage or release status is promoted by this observation alone.
