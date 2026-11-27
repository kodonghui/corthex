# AI model calls in the product

Read this in stage 11 when the product itself calls an AI model's API, such as OpenAI's or Anthropic's. The stage's steps and checks are in [11-development.md](11-development.md).

## Reading a response

Read each response by the type of its blocks, not by taking the first block, and handle each stop reason the provider documents: an answer that hit the output limit is a failure, and that limit leaves room for reasoning tokens; a refusal gets the fallback of the AI call entry; an empty end of turn right after a tool result is checked on its own. Take the names and values from the provider's current documentation.

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

## Changing a live AI service

When an AI feature is already serving people:

- Keep the prompts, knowledge and tool definitions apart from the code, each with a version, a hash per file and a copy to roll back to.
- The deployment command checks that the live version is the one it expects, and stops when it is not.
- Change one thing at a time: the change, a quick regression run, a record, then the next change. Turn new behaviour on and off with a setting.
- Before a deadline, agree on a freeze time and on what may still go in, for example from 30 minutes before only changes that passed the quick regression run, and from 10 minutes before only rollbacks. During the freeze, only read except for the changes or rollbacks that agreement allows.
- The day before, run the access, deployment and approval paths once from start to end.
