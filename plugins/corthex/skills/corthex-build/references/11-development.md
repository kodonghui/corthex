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
5. When the product calls an AI model's API itself, such as OpenAI's or Anthropic's, keep the key and build the client as Keys for AI model APIs below says.
6. Front end: build each screen against the mock server first (stage 06), show each response the way the screen definition says, then switch to the real server.
7. Write tests for each acceptance criterion the change touches.
8. Open a pull request that names the TASK and SPEC IDs and says what was tested and what was not.

## Keys for AI model APIs

- **Where the key lives.** In an environment variable of the operating system: set by the developer on their machine, and from the deployment's secret store on a server. Use the name the provider's SDK reads, such as `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`. Never in code, in a committed file or in `.env`.
- **Only the back end calls the model.** A key never reaches a browser or a mobile app, so it is never in a variable that the front-end build writes into the bundle, such as `VITE_*` or `NEXT_PUBLIC_*`.
- **`.env` holds no secrets.** It holds only settings that are not secret, such as the model name and timeouts, and `.gitignore` lists it. Commit a `.env.example` with those settings and no values that are secret, and say in the README which environment variables hold keys.
- **One settings class reads the key.** In Python, a pydantic-settings class reads it into a `SecretStr` field, so printing or logging the settings shows `**********`, and an environment variable wins over a value in `.env`. Call `get_secret_value()` only where the client is built. In another language, one settings module reads the environment at start and keeps the key out of its text form, logs and errors.
- **One function builds the client**, and the code that calls the model receives it, in FastAPI through `Depends`. With a key, it builds the real client. Without one, in local development it returns a fake client that gives fixed answers in the format of the AI call entry (stage 04).
- **Tests use the fake client.** The test setup removes the key from the environment and overrides the function, so a key set on a developer's machine never makes the test suite call the paid API. Tests that call the real model carry a marker: the setup leaves them the key and the real client, the default run leaves them out, and they run only when asked, with a key set (stage 12).
- **A deployed server never uses the fake client.** Without a key, its AI operations return the contract's error for an unavailable model, such as 503 `ai_unavailable`, the rest keeps working, and its log at start names the missing variable, never a value. So the setting that names the environment defaults to production, and only a developer's `.env` sets development.
- **Never in logs or commits.** Never write the key, a request header that carries it or settings with it revealed into logs, error messages, responses, records or commits. If a key was ever committed, pasted or logged, revoke it at the provider and make a new one first; deleting the commit or the log does not undo the leak.
- **One key per product and environment**, such as development and production, so that one can be revoked without stopping the others.

For example, in a FastAPI back end:

```python
# app/settings.py
from functools import lru_cache
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # .env sets only values that are not secret, such as APP_ENV=development on a developer's machine.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "production"
    openai_model: str = "<model>"
    openai_api_key: SecretStr | None = None  # from the environment variable OPENAI_API_KEY

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

```python
# app/ai.py
from typing import Annotated
from fastapi import Depends
from openai import OpenAI
from pydantic import SecretStr
from .errors import AIUnavailable  # the error handler sends the contract's 503 ai_unavailable
from .settings import Settings, get_settings

class FakeAIClient:
    def answer(self, question: str) -> str:
        return '{"answer": "A fixed answer for tests.", "sources": []}'

class OpenAIClient:
    def __init__(self, key: SecretStr, model: str):
        self.client = OpenAI(api_key=key.get_secret_value())
        self.model = model

    def answer(self, question: str) -> str:
        ...  # the call the AI call entry describes

def get_ai_client(settings: Annotated[Settings, Depends(get_settings)]):
    if settings.openai_api_key is not None:
        return OpenAIClient(settings.openai_api_key, settings.openai_model)
    if settings.app_env == "development":
        return FakeAIClient()
    raise AIUnavailable()
```

```python
# tests/conftest.py
import pytest
from app.ai import FakeAIClient, get_ai_client
from app.main import app
from app.settings import get_settings

@pytest.fixture(autouse=True)
def fake_ai(request, monkeypatch):
    if request.node.get_closest_marker("real_model") is None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        app.dependency_overrides[get_ai_client] = FakeAIClient
    get_settings.cache_clear()
    yield
    app.dependency_overrides.clear()
    get_settings.cache_clear()
```

```toml
# pyproject.toml
[tool.pytest.ini_options]
markers = ["real_model: calls the real AI model and costs money"]
addopts = "-m 'not real_model'"  # run them with OPENAI_API_KEY set: pytest -m real_model
```

## Checks

- The tests for the touched acceptance criteria pass.
- The contract tests pass for every operation the change touches, and the report names the tool, the server and the commit.
- Every response a touched operation lists has a passing test.
- Each touched operation is reported in two steps that do not imply each other: provided, when the back end passes its contract tests and a test for each response, and accepted, when the front end works against the real server and its screens pass.
- The diff holds only the intended files and no secrets.
- When the product calls an AI model's API, Git ignores `.env` (`git check-ignore -q .env`), neither `.env` nor `.env.example` sets a key and no front-end variable holds one (look at the names only and never print the values), and the tests pass with no key in the environment.
- Screen changes match their screen definitions, including the state each response leads to.

## Output template

```markdown
TASK-001 Create order endpoint (SPEC-001)

- Implements API-001 as in api/openapi.yaml
- Contract tests: Schemathesis against staging, all checks passed for API-001 (commit abc1234)
- Tests: payment failure path (REQ-002)
- API-001: provided; not yet accepted, the checkout screen still uses the mock server
- Not tested: load
```
