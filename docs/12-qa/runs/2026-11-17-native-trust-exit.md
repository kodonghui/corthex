# Native hook-trust review exit

[한국어](2026-11-17-native-trust-exit.ko.md)

The macOS hook job of [PR 215, run 771](https://github.com/kodonghui/corthex/actions/runs/44041313478) failed after the old plugin's trust review. The artifact's terminal transcript shows that the hook became active, the Hooks panel stayed open, and startup work returned to idle. The review then called terminal cleanup, whose Ctrl-C inputs are cancellation/panel actions rather than a reliable normal application exit; the process did not produce the zero status that the review requires. The artifact contains synthetic fixture data, not an operator account or real model call.

The review now closes the panel with Escape, sends the native `/quit` command and waits for process exit before cleanup. The existing zero-exit assertion and every trust, pre-retrust preservation and capture check remain in force. This follows the explicit quit path already used by the native lifecycle walk. It does not turn a forced kill or cancellation into a pass.

The regression uses a real Unix PTY peer that exits normally only after Escape and `/quit`; Ctrl-C produces a failed/cancelled exit. Local results are recorded in the PR. Native macOS success still requires the updated GitHub job; Linux PTY evidence alone is not macOS evidence.
