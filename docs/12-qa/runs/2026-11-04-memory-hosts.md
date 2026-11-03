# C1 installed-host QA: the merged baseline

[한국어](2026-11-04-memory-hosts.ko.md)

The results below are observed on PR #90 head `24cc42c5bbb8fe181160528b578ec3d4ebf2e7b8`, merged as `15ea32cb52510cd2bf684b28ac30202820536d07`. The MEMORY product remains byte-identical to PR #88 (`2fc4b871873659249e4c43c8b6139c7f5748e186`). This report records completed baseline evidence, not future checks on this report's commit. Actual native Claude Code 2.1.310 and Codex CLI 0.164.0 use disposable homes/stores, synthetic consent and a fixed loopback model. No real-provider or real-user-store trial is claimed.

## Six Python cells

| OS | Python | Passed / skipped | Seconds | Retention successes / attempts / skips |
| --- | --- | ---: | ---: | --- |
| [Linux](https://github.com/kodonghui/corthex/actions/runs/41680581067/job/126072841711) | 3.8.18 | 840 / 13 | 200.315 | 100 / 100 / 0 |
| [Linux](https://github.com/kodonghui/corthex/actions/runs/41680581067/job/126072842344) | 3.15.1 | 841 / 12 | 195.359 | 100 / 100 / 0 |
| [Windows](https://github.com/kodonghui/corthex/actions/runs/41680581067/job/126072841746) | 3.8.10 | 847 / 6 | 363.693 | 100 / 100 / 0 |
| [Windows](https://github.com/kodonghui/corthex/actions/runs/41680581067/job/126072842293) | 3.15.2 | 848 / 5 | 305.106 | 100 / 100 / 0 |
| [macOS](https://github.com/kodonghui/corthex/actions/runs/41680581067/job/126072842061) | 3.8.18 | 832 / 21 | 368.126 | 100 / 101 / 1 |
| [macOS](https://github.com/kodonghui/corthex/actions/runs/41680581067/job/126072841737) | 3.15.2 | 833 / 20 | 274.846 | 100 / 100 / 0 |

Each cell discovered 853 tests with zero failures and passed all 15 Node tests. The strict validations of the marketplace and all three plugins passed; all 16 current-head check runs, including required `all-checks` from Actions app 15368, succeeded. The original retention test stays at 100 successes, at most 500 attempts, 120 seconds and a 10-ms writer delay. One macOS 3.8 lease skip is reported; it is not a changed test condition.

TC-104's import inventory statically lists all imports in 35 packaged MEMORY Python files, including platform-specific imports. The internal package is `memory_lib`; the external top-level modules are all standard library: `argparse`, `builtins`, `collections`, `contextlib`, `copy`, `ctypes`, `dataclasses`, `datetime`, `fcntl`, `functools`, `hashlib`, `itertools`, `json`, `math`, `msvcrt`, `os`, `pathlib`, `re`, `secrets`, `shutil`, `stat`, `subprocess`, `sys`, `tempfile`, `threading`, `time`, `unicodedata`, `urllib`. This is a static dependency check alongside actual execution in the six cells, not a claim that every platform-specific branch ran on each platform.

## Installed hosts, worker lifetime and retained data

Native job logs: [Linux](https://github.com/kodonghui/corthex/actions/runs/41680581067/job/126072841698) · [Windows](https://github.com/kodonghui/corthex/actions/runs/41680581067/job/126072841933) · [macOS](https://github.com/kodonghui/corthex/actions/runs/41680581067/job/126072842101).

All three systems run both hosts and all four hooks with intact Korean prompt/final answer, matching native session and turn, metadata-only start/end boundaries, successful hook timing outcomes and no memory failure logs. Windows additionally passes both hosts without Git Bash, and Codex with only PowerShell 5.1. These are 15 host/variant rows: four ordinary Unix rows, five Windows ordinary/alternate rows and six controlled rows.

For the controlled six host/system pairs, the original worker entry and product libraries are byte-identical. A test-only call barrier inside retention connects one actual worker PID/nonce to entry, native host and all-hook exit, a later heartbeat, resume, return, expired raw removal and fresh raw preservation. The 20-second barrier and 6/12-second observer deadlines stay unchanged. This establishes TC-103's process lifetime using declared instrumentation; it is not an uninstrumented performance measurement.

TC-101 removes and reinstalls the actual installed plugin in each pair. Configuration, store header and raw-log SHA256 maps match before removal, after removal and after installation. TC-108's positive-controlled dedicated MEMORY HTTP(S) proxy observes zero requests in all six pairs. Codex host metadata attempts are blocked and recorded in a separate proxy; the claim is configured proxy observation, not OS-wide packet capture. A single outer clock per hook includes original product interpreter startup and excludes host/wrapper startup, and makes no p95 claim.

## Redaction on each system

TC-028 uses one excluded warmup and ten measured runs for each input below; external environment redaction values are disabled in this synthetic fixture. Native job Python: Linux 3.15.1, Windows 3.12.10, macOS 3.15.2. These redaction-only times do not establish the whole capture-hook 100-ms goal.

| Input (524,288 bytes each) | Linux median / max ms | Windows median / max ms | macOS median / max ms |
| --- | ---: | ---: | ---: |
| prose | 107.798 / 109.869 | 106.299 / 121.217 | 94.29 / 110.359 |
| password-repeat | 258.983 / 264.686 | 235.861 / 242.07 | 205.431 / 293.068 |
| private-openers | 12.375 / 12.93 | 16.521 / 16.936 | 10.629 / 14.511 |
| pem-header-without-key | 107.929 / 109.771 | 114.043 / 119.79 | 122.308 / 132.471 |
| token-digits | 107.527 / 108.02 | 106.618 / 110.542 | 102.974 / 129.417 |
| url-without-at | 107.668 / 108.414 | 106.773 / 110.937 | 121.295 / 154.195 |
| pem-begin-name-repeat | 103.062 / 103.938 | 102.23 / 105.814 | 101.594 / 117.328 |
| pem-end-name-repeat | 17.869 / 18.507 | 20.323 / 21.13 | 19.764 / 26.074 |
| jwt-no-dots | 100.955 / 102.389 | 98.113 / 103.313 | 110.365 / 168.636 |
| jwt-base64-json | 100.516 / 101.37 | 99.753 / 106.846 | 130.448 / 334.937 |
| token-repeat | 341.247 / 351.433 | 299.144 / 316.23 | 342.163 / 592.402 |
| passwd-repeat | 309.331 / 321.206 | 275.042 / 281.647 | 314.089 / 380.829 |
| secret-repeat | 302.341 / 308.349 | 267.694 / 282.693 | 304.045 / 430.445 |
| apikey-repeat | 310.504 / 317.364 | 274.12 / 289.832 | 297.896 / 312.308 |
| jwt-percent-repeat | 101.791 / 102.366 | 99.015 / 105.491 | 100.943 / 108.969 |

## Scope and retained failures

This evidence supports whole-case results for TC-028, TC-101, TC-102, TC-103, TC-104 and TC-108. Actual tool turns and update trust observed only on Windows have their own reports: [tool turn](2026-11-04-memory-tool-turn.md), [update trust](2026-11-04-memory-trust-update.md), [native task notification](2026-11-04-memory-native-prefix.md). They do not establish other systems, all notification forms, recursive Stop or all session-start variants. TC-105 remains incomplete: the [local replay baseline](https://github.com/kodonghui/corthex/issues/95) misses the unchanged 100-ms p95 goal, and is not 100 native sessions in CI.

The earlier Windows launcher classification, controlled-host diagnostic delay and macOS 3.8 cross-process clock failures are retained with PR #90's correction. Local errors whose causes remain unknown and invalid operator attempts are not recast as product fixes. TASK-028 stays in progress; the agent walk, maintainer week and go/no-go, actual tag and later PR C remain separate.

Canonical privately retained receipts: `task028-v7-ci-summary.json`, SHA256 `341086294c2fae55026e6c80c49850414ab6f9b0dda323794122d52fbaab0f68`; `task028-v7-native-ci-summary.json`, SHA256 `0aa7afd6c79338a7a2bed3e667216ce0dc0d221cac1b35fa116cce7bbc98eb8f`; `task028-followup-import-inventory.json`, SHA256 `73645ab30d99d2f538c2805c18b31953b4def29e5ae878a63186a45bcdeb875d`. The public job logs above bind their actual native output and matrix results. Store paths and disposable transcripts are omitted from this public report.
