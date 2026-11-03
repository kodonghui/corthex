# A native tool turn on Windows

[한국어](2026-11-04-memory-tool-turn.ko.md)

The actual installed Claude Code and Codex executables completed a tool call and a Korean final answer against a fixed loopback protocol server. The raw memory logs contain the Korean prompt and final answer, with matching start/end boundaries, and the tool-only marker appears in zero memory-store files. This covers the Windows native-tool portion of TC-043; it is not the complete three-system case or an agent walk.

The product is the unchanged MEMORY package from main commit `2fc4b871873659249e4c43c8b6139c7f5748e186` (PR #88). The helper snapshot is `task028-v3-snapshot.json`. Each host uses a disposable home, project, plugin installation and memory store. Synthetic `on` consent, fake keys and a loopback model are used. Codex hook trust is bypassed only for this isolated tool-turn probe; the separate TC-107 update observation uses no trust bypass.

| Host | Native tool and observed output | Memory result |
| --- | --- | --- |
| Claude Code 2.1.310 | The real `Read` tool reads a synthetic file whose name and content contain `TOOL_ONLY_FIXTURE_938107`; the tool result contains that marker and is not an error. | Four expected raw entries, intact Korean, same host/session/turn and successful timings; marker in zero store files. |
| Codex CLI 0.164.0 | A real `functions.exec` custom-tool call runs only `text("TOOL_ONLY_FIXTURE_938107");`; its successful native result contains that marker. | Four expected raw entries, intact Korean, same host/session/turn and successful timings; marker in zero store files. |

Each host makes two requests to the fixed protocol server, one before and one after the tool result. The controller verified the actual native tool output before qualifying the result; a requested tool call alone was not counted as an executed tool call.

Claude's actual transcript also contains the marker: 177,626 bytes, SHA256 `9b2e3dede87fd3e15d2be38385f3a352bc07f39e0bf5ca29ac1a4ecd0523d2d5`. It is kept privately with the disposable QA evidence. The initial ordinary read failed because its Windows path is 296 characters long; reading that owned path with the Windows extended-path prefix succeeded, without changing OS settings. The failed reads are retained.

Codex provides `transcript_path: null` at this pinned version. Its successful tool call and exclusion are observed, while the unreadable-transcript guard remains a separate API fixture. Neither host emitted a task/team notification prefix in this turn. Linux/macOS tool turns remain to be run; they are not inferred from Windows or from sessions without tools.

The qualified receipt is `task028-toolturn-v1/qualified.json`; it pins the original probe SHA256 `ed52d225b7ac63344560143079ed05ded52672687003a8a4371043045a24f4e1` and result SHA256 `00b06b4adff305f3cbf1235e9b8604b18dd877005673b28d170acff683faa1b9`. The original unqualified result, the failed transcript reads and the later qualification are preserved separately. No real provider call, account login, global host installation or real-user memory activation was performed. Whole-case and coverage promotion wait for the remaining evidence and review.
