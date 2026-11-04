# Stage 11 · Development

| Slot | This stage |
| --- | --- |
| Inputs | Tasks (TASK), the functional spec (SPEC), the API contract (API), the schema (TBL) and the screen definitions (SCR) |
| Outputs | Code and tests on a branch, in a pull request whose title or description names the TASK and SPEC IDs |
| Human view | Pull request review on the code host, by default GitHub |
| Sync | The pull request moves the task's status. Merged counts as done only after the review and the checks pass |
| Human checkpoints | Review approval and the merge, under the repository's own rules |
| Trace IDs | No new IDs; pull requests and commits name TASK and SPEC IDs |

## Steps

1. Read the repository's own rules first, such as `AGENTS.md`, `CLAUDE.md` and `CONTRIBUTING.md`.
2. Check the real repository root, the branch, existing changes and work in progress by others.
3. Implement against the contracts. If the code needs a contract change, change the contract first (stage 05 or 06) and say so.
4. Back end: return exactly the responses the API contract lists, with their schemas, and every error in the contract's error shape with one of its error codes; log the `traceId` of each error response. If the framework also generates an OpenAPI document from the code, the contract file stays the source. Run the contract tests against a development or staging server, never production, with a test account: for example `schemathesis run api/openapi.yaml --url <server> -H "Authorization: Bearer <test token>"`.
5. When the product calls an AI model's API itself, such as OpenAI's or Anthropic's, keep the key and build the client as Keys for AI model APIs below says. Read each response by the type of its blocks, not by taking the first block, and handle each stop reason the provider documents: an answer that hit the output limit is a failure, and that limit leaves room for reasoning tokens; a refusal gets the fallback of the AI call entry; an empty end of turn right after a tool result is checked on its own. Take the names and values from the provider's current documentation.
6. Front end: build each screen against the mock server first (stage 06), show each response the way the screen definition says, then switch to the real server.
7. Write tests for each acceptance criterion the change touches.
8. Open a pull request that names the TASK and SPEC IDs and says what was tested and what was not.

## Keys for AI model APIs

- **Where the key lives.** In an environment variable of the operating system: set by the developer on their machine, and from the deployment's secret store on a server. Use the name the provider's SDK reads, such as `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`. Never in code, in a committed file or in `.env`.
- **Only the back end calls the model.** A key never reaches a browser or a mobile app, so it is never in a variable that the front-end build writes into the bundle, such as `VITE_*` or `NEXT_PUBLIC_*`.
- **`.env` holds no secrets.** It holds only settings that are not secret, such as the model name and timeouts, and `.gitignore` lists it. Commit a `.env.example` with those settings and no values that are secret, and say in the README which environment variables hold keys.
- **One settings class reads the key.** In Python, a pydantic-settings class reads it into a `SecretStr` field, so printing or logging the settings shows `**********`, and an environment variable wins over a value in `.env`. Call `get_secret_value()` only where the client is built. In another language, one settings module reads the environment at start and keeps the key out of its text form, logs and errors.
- **One owner builds and closes the client.** Reuse it within its owning worker/event loop lifetime. A request dependency retrieves that existing resource; it does not construct a client per request or share mutable user state. In an async handler, await an async SDK. A synchronous dependency does not move later blocking method calls into a thread pool: use a synchronous route or an explicit, bounded offload when a synchronous SDK is required.
- **Tests inject both lifetimes.** Replace the lifecycle client factory as well as request dependencies, even when a developer has a key set. A dependency override does not intercept a constructor called directly by startup code. Run startup and shutdown in tests, and check creation, reuse and closure. Ordinary tests use fixed or scripted fakes, with controllable delay and failure; a real-model marker selects tests but grants no permission to spend money or send data.
- **A deployed server never uses the fake client.** Without a key, its AI operations return the contract's error for an unavailable model, such as 503 `ai_unavailable`, the rest keeps working, and its log at start names the missing variable, never a value. So the setting that names the environment defaults to production, and only a developer's `.env` sets development.
- **Never in logs or commits.** Never write the key, a request header that carries it or settings with it revealed into logs, error messages, responses, records or commits. If a key was ever committed, pasted or logged, revoke it at the provider and make a new one first; deleting the commit or the log does not undo the leak.
- **One key per product and environment**, such as development and production, so that one can be revoked without stopping the others. Evaluations and comparison runs against the real model get a key or project of their own, with an enforced spending limit and an alert, so that a run that uses up its credit leaves the product running.

## AI operation boundaries

- Give the entire operation a deadline that includes SDK attempts and backoff. Transport connect/read/write/pool timeouts alone are not a total deadline. Pick one retry owner; do not multiply SDK retries with an independent outer retry loop. Specify idempotency and reconciliation before retrying writes.
- Cancellation is cooperative. Bound waiting, propagate cancellation and close resources; a cancelled await, disconnected caller or timed-out thread does not prove a remote write stopped or provider billing was reversed. Streams and background jobs need separate ownership and completion rules.
- Check response status, typed blocks, refusal, incomplete/empty output and the application schema before accepting an answer. Follow the pinned SDK and endpoint's current documentation; an output-text helper is not proof of success.
- Make provider storage options explicit and review the current policy for the endpoint, model, feature and account. `store=False` is not zero retention or a universal no-training/no-logging guarantee. Minimize sent data and redact application diagnostics separately.

The [complete non-streaming FastAPI example](fastapi-example.md) shows lifecycle ownership, AI-only 503 without a key, application error mapping, a whole-operation deadline, typed output checks and deterministic offline tests. It is a product example with its own pinned dependencies, not a CORTHEX runtime or a production starter.

## Optional learning and task guides

When the user asks for a learning guide, onboarding material or an operational HOWTO, use [Writing and checking a guide](howto.md). Choose a tutorial for a first learning path and a HOWTO for a specific task. Update affected use/build/test documentation when behaviour changes; do not require a new tutorial, documentation system or guide on every PR.

## Changing a live AI service

When an AI feature is already serving people:

- Keep the prompts, knowledge and tool definitions apart from the code, each with a version, a hash per file and a copy to roll back to.
- The deployment command checks that the live version is the one it expects, and stops when it is not.
- Change one thing at a time: the change, a quick regression run, a record, then the next change. Turn new behaviour on and off with a setting.
- Before a deadline, agree on a freeze time and on what may still go in, for example from 30 minutes before only changes that passed the quick regression run, and from 10 minutes before only rollbacks. During the freeze, only read except for the changes or rollbacks that agreement allows.
- The day before, run the access, deployment and approval paths once from start to end.

## Checks

- The tests for the touched acceptance criteria pass.
- The contract tests pass for every operation the change touches, and the report names the tool, the server and the commit.
- Every response a touched operation lists has a passing test.
- Each touched operation is reported in two steps that do not imply each other: provided, when the back end passes its contract tests and a test for each response, and accepted, when the front end works against the real server and its screens pass.
- The diff holds only the intended files and no secrets.
- When the product calls an AI model's API, Git ignores `.env` (`git check-ignore -q .env`), neither `.env` nor `.env.example` sets a key and no front-end variable holds one (look at the names only and never print the values), and the tests pass with no key in the environment.
- Screen changes match their screen definitions, including the state each response leads to.
- A change to a live AI service checked the live version first, and has its regression run and its record.

## Output template

```markdown
TASK-001 Create order endpoint (SPEC-001)

- Implements API-001 as in api/openapi.yaml
- Contract tests: Schemathesis against staging, all checks passed for API-001 (commit abc1234)
- Tests: payment failure path (REQ-002)
- API-001: provided; not yet accepted, the checkout screen still uses the mock server
- Not tested: load
```
