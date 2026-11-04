# Core AI guidance and first-project checks · 2026-11-04

[한국어](2026-11-04-core-ai-guidance.ko.md)

This checks the approved documentation/AI-server guidance work, not MEMORY recording, a real provider or a production service. The complete runnable source is the two Python blocks and pinned requirements in [the FastAPI reference](../../../plugins/corthex/skills/corthex-build/references/fastapi-example.md). Package pins belong to that product example; the core plugin still has no SDK/runtime dependencies.

## Extracted example

All three environments ran the same files extracted from the Markdown, with an explicit lifespan and ASGI client. The SDK retry test used a local `MockTransport` and a synthetic key; other tests used injected scripted resources. No paid model was called.

| Actual environment | Python | Result |
| --- | --- | --- |
| Windows 11 native, PowerShell | 3.13.14 | 10 tests passed, 0 failed, 0 skipped |
| Linux 6.8 x86_64 | 3.12.3 | 10 tests passed, 0 failed, 0 skipped |
| macOS 13.7.8 Intel | 3.13.15 | 10 tests passed, 0 failed, 0 skipped |

The checks cover client creation/reuse/closure; missing-key production startup and AI-only 503 with zero SDK construction; separate lifecycle and request overrides; responsiveness while a delayed fake is pending; cancellation at the whole-operation deadline; actual SDK retry/backoff within that deadline; specific SDK exception mapping; typed completed/refused/incomplete/empty/malformed output; real framework validation/404/405/fault-500 responses and safe diagnostics; and effective fake-mode/target/source preflight without a model probe.

Three separate mutated copies failed their existing guards as expected: constructing a client per request, allowing a 30-second outer wait instead of the configured one-second deadline around SDK retry, and returning the framework's default validation response. The unmodified source passed. The failed copies are controls, not alternate passing implementations.

Extracted file SHA-256 values:

```text
example_app.py   74b82396a78afca243d1e84ee3cceb074492c1bf306880dda2828778d891a687
test_example.py  135cc2c18d3c999b2b5884a6ca32fbd9948fb5c556038195434178174edad575
requirements.txt 22c4314bfeb3ed1a6dcf9907e1ce1733eb19cc8a98af6ca10d6912594f420e34
```

## First-project installation and discovery

Fresh disposable homes installed only the candidate core plugin from the local candidate marketplace. Every marketplace add, install, list and new-session command exited 0. The host's model request exposed the entry skill's description; all nine installed skill files matched the candidate. No original account profile was copied and no MEMORY store was created.

| Actual environment | Installed host | Result |
| --- | --- | --- |
| Windows 11 native | Claude Code 2.1.310 | installation and fresh-session discovery passed |
| Windows 11 native | Codex CLI 0.164.0 | installation and fresh-session discovery passed |
| macOS 13.7.8 Intel | Claude Code 2.1.310 | installation and fresh-session discovery passed |

This used a fixed local model response, not a real agent completing profile setup or the requirement checkpoint. The public GitHub marketplace route, existing-registration update path, Codex on macOS, complete reader walkthrough and human learning were not verified here. The [tutorial](../../first-project.md) keeps those interactive steps and explicit approval; a fixed reply cannot supply that approval. These command/discovery checks must not be reported as a successful first-reader study.

## Boundaries

The example is non-streaming, stateless and unauthenticated, with no write tools or real sensitive input. Passing local tests does not establish real-provider availability, semantic answer quality, endpoint retention terms, zero retention, cancellation of remote effects, production performance or load-test calibration. F04's blank starter and F13's load-tool calibration remain deferred. No release tag or real-user MEMORY activation is part of this work.
