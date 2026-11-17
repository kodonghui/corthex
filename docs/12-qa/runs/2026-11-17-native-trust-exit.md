# Native hook-trust review exit

[한국어](2026-11-17-native-trust-exit.ko.md)

The macOS hook job of [PR 215, run 771](https://github.com/kodonghui/corthex/actions/runs/44041313478) failed after the old plugin's trust review. The artifact's terminal transcript shows that the hook became active, the Hooks panel stayed open, and startup work returned to idle. The review then called terminal cleanup, whose Ctrl-C inputs are cancellation/panel actions rather than a reliable normal application exit; the process did not produce the zero status that the review requires. The artifact contains synthetic fixture data, not an operator account or real model call.

The review now closes the panel with Escape, sends the native `/quit` command and waits for process exit before cleanup. The existing zero-exit assertion and every trust, pre-retrust preservation and capture check remain in force. This follows the explicit quit path already used by the native lifecycle walk. It does not turn a forced kill or cancellation into a pass.

The regression uses a real Unix PTY peer that exits normally only after Escape and `/quit`; Ctrl-C produces a failed/cancelled exit. The updated native macOS hook job passed in [run 772](https://github.com/kodonghui/corthex/actions/runs/44054666392), and all 39 checks passed on head `657e3f23bfac766a3fd852858df89723fdfbd95b` before PR 215 merged.

## Unit PTY isolation

During the hub CI-setup work, macOS Intel Python 3.8 shard 1 of [run 44063368622](https://github.com/kodonghui/corthex/actions/runs/44063368622) exceeded its 60-minute limit. GitHub returned 404 for that job's log, and its file was absent from the first attempt's log archive. The exact test at the timeout remains unknown.

That shard includes real PTY tests. The full unit runner has threads from earlier network tests, and Python warns that `forkpty` in a threaded process can deadlock. Each of the three real-terminal cases now runs in a fresh Python interpreter. The worker asserts a single active thread; the parent verifies that exactly one requested case ran without a skip. The original terminal, exit-status, trust and reaping assertions remain intact, with a 30-second worker limit.

This removes the shared unit runner's threaded-fork condition. The historical timeout's internal cause remains unverified. The repository suite and the full CI on the updated PR head validate the isolation change; the PR links their results.
