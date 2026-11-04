# Non-streaming FastAPI AI example

This complete product example illustrates [Stage 11](11-development.md), not a production starter or a CORTHEX runtime dependency. It has no authentication, persistence, tools, streaming or provider-quality evaluation. Adapt its error catalog and schemas to the product's API contract before use.

## Starting state and files

Use Python 3.11+ in a new, disposable directory, with network access only to install the pinned packages below. The implementation was developed against OpenAI Python 3.45.0 and FastAPI 0.162.0 on 2026-11-04. These are example pins, not an instruction to upgrade an existing product. Its `httpx2` test transport matches this SDK; do not substitute an older `httpx` transport without checking compatibility.

Save the three complete blocks below as `requirements.txt`, `example_app.py` and `test_example.py` in that directory. No key is needed for the tests; they explicitly select settings and inject factories. The one SDK retry test uses only `httpx2.MockTransport` with a synthetic key and never contacts a provider.

In PowerShell, from that directory, run each line:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest -v test_example
```

In macOS/Linux bash or zsh, from that directory:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest -v test_example
```

Expect `Ran 10 tests` and `OK`. Stop on a failed assertion; keep the log and package versions before changing a timeout or fixture. These tests exercise the ASGI app in process with its lifespan. They do not prove deployment, provider availability, a reader's understanding or production latency.

## What to inspect

- The lifespan owns one client per worker/event loop and closes it. `get_ai` only retrieves it. Tests replace the lifecycle factory independently of request dependency overrides.
- Production without a key starts normally: `/health` returns 200, `/answer` returns 503 `ai_unavailable`, and the SDK constructor is never called. Only explicit development without a key selects the fixed fake. A key with no configured model disables AI instead of guessing a model.
- The outer deadline includes SDK retry and backoff; the SDK owns retries. The retry test observes one local transport attempt before the total deadline cancels its long backoff. This is not a guarantee that cancellation undoes remote work, a thread, charges or a write. The sample performs no writes.
- Only a completed response with permitted typed blocks and a validated `Answer` is accepted. Refusal, incomplete, malformed and empty output have explicit failures. This sample permits reasoning and answer text but no tools.
- The adapter maps provider errors to application codes. The renderer returns Problem Details for validation, 404, 405, application and unexpected errors, preserves `Allow`, and logs only safe codes/trace IDs. Its small HTTP catalog covers this app; other framework/auth statuses need their own contract mappings.
- `/ai/status` exists only outside production and reports effective mode/environment plus this source file's hash. The preflight test verifies this report against the actual target before an ordinary run, without a model probe. A deployed product needs a trusted build/deployment identity rather than treating an arbitrary status response as authenticity.
- `store=False` is explicit; it does not establish zero retention. Check current provider terms for the actual endpoint/model/features/account, approval and data sent. Keep SDK request dumps off and review proxy/host logging separately.

## Complete files

### requirements.txt

```text
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.16.0
asgi-lifespan==2.1.0
fastapi==0.162.0
h11==0.16.0
httpcore2==2.16.0
httpx2==2.16.0
idna==3.20
jiter==0.18.0
openai==3.45.0
opentelemetry-api==1.45.2
pydantic==2.14.2
pydantic-core==2.50.2
pydantic-settings==2.16.2
python-dotenv==1.2.4
sniffio==1.3.1
starlette==1.10.0
truststore==0.10.5
typing-extensions==4.16.0
typing-inspection==0.4.4
```

### example_app.py

```python
"""Non-streaming product example. This module is not a CORTHEX runtime dependency."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
from http import HTTPStatus
import logging
from pathlib import Path
from typing import Annotated, Callable, Literal, Protocol
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from openai import (
    APIConnectionError, APIResponseValidationError, APIStatusError,
    APITimeoutError, AsyncOpenAI, AuthenticationError, OpenAIError,
    PermissionDeniedError, RateLimitError, Timeout,
)
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.exceptions import HTTPException

log = logging.getLogger("example.ai")
# The SDK's debug request dumps are not this application's safe diagnostics.
logging.getLogger("openai").setLevel(logging.WARNING)
ERRORS = {
    "invalid_input": (422, "Check the input fields."),
    "not_found": (404, "The resource was not found."),
    "method_not_allowed": (405, "This method is not allowed."),
    "internal_error": (500, "The operation failed."),
    "ai_unavailable": (503, "The AI feature is unavailable."),
    "ai_upstream_busy": (503, "The AI provider is busy. Try later."),
    "ai_upstream_error": (502, "The AI provider failed."),
    "ai_invalid_response": (502, "The AI response could not be accepted."),
    "ai_refused": (422, "The AI could not answer this request."),
    "ai_timeout": (504, "The AI operation took too long."),
}


class Settings(BaseSettings):
    # No .env loader here: keys come only from the process/secret store.
    model_config = SettingsConfigDict(extra="ignore")
    app_env: Literal["development", "staging", "production"] = "production"
    openai_model: str = ""
    openai_api_key: SecretStr | None = None
    ai_attempt_timeout: float = Field(default=10.0, gt=0)
    ai_deadline: float = Field(default=30.0, gt=0)
    ai_retries: int = Field(default=1, ge=0)


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=4000)


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=4000)
    sources: list[str] = Field(max_length=10)


class AIProblem(Exception):
    def __init__(self, code: str):
        assert code in ERRORS
        self.code = code
        super().__init__(code)


class AI(Protocol):
    mode: str
    async def answer(self, question: str) -> Answer: ...
    async def aclose(self) -> None: ...


class FakeAI:
    mode = "fake"

    async def answer(self, question: str) -> Answer:
        return Answer(answer="A fixed answer for the example.", sources=[])

    async def aclose(self) -> None:
        pass


class UnavailableAI(FakeAI):
    mode = "disabled"

    async def answer(self, question: str) -> Answer:
        raise AIProblem("ai_unavailable")


def checked_answer(response) -> Answer:
    if response.status != "completed":
        raise AIProblem("ai_invalid_response")
    texts = []
    for item in response.output:
        if item.type == "reasoning":
            continue
        if item.type != "message":  # this contract permits no tools
            raise AIProblem("ai_invalid_response")
        if item.status != "completed":
            raise AIProblem("ai_invalid_response")
        for block in item.content:
            if block.type == "refusal":
                raise AIProblem("ai_refused")
            if block.type != "output_text":
                raise AIProblem("ai_invalid_response")
            texts.append(block.text)
    try:
        return Answer.model_validate_json("".join(texts))
    except ValidationError:
        raise AIProblem("ai_invalid_response") from None


class OpenAIAdapter:
    mode = "real"

    def __init__(self, client, model: str):
        self.client, self.model = client, model

    async def answer(self, question: str) -> Answer:
        try:
            response = await self.client.responses.create(
                model=self.model,
                input=[{"role": "user", "content": question}],
                instructions='Return only a JSON object with answer (string) and sources (array of strings).',
                store=False,
            )
        except APITimeoutError:
            raise AIProblem("ai_timeout") from None
        except RateLimitError:
            # Provider capacity is distinct from this app's user quota.
            raise AIProblem("ai_upstream_busy") from None
        except (AuthenticationError, PermissionDeniedError, APIConnectionError):
            raise AIProblem("ai_unavailable") from None
        except APIResponseValidationError:
            raise AIProblem("ai_invalid_response") from None
        except (APIStatusError, OpenAIError):
            raise AIProblem("ai_upstream_error") from None
        return checked_answer(response)

    async def aclose(self) -> None:
        await self.client.close()


def build_ai(settings: Settings) -> AI:
    if settings.openai_api_key is not None and settings.openai_api_key.get_secret_value().strip():
        if not settings.openai_model:
            return UnavailableAI()
        return OpenAIAdapter(AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=Timeout(settings.ai_attempt_timeout, connect=min(2.0, settings.ai_attempt_timeout)),
            max_retries=settings.ai_retries,
        ), settings.openai_model)
    if settings.app_env == "development":
        return FakeAI()
    log.warning("ai_mode=disabled reason=missing_OPENAI_API_KEY")
    return UnavailableAI()  # no SDK constructor; ordinary routes still start


def get_ai(request: Request) -> AI:
    return request.app.state.ai


def problem(request: Request, code: str, *, fields=None, headers=None):
    status, detail = ERRORS[code]
    trace = request.state.trace_id
    body = {"type": "about:blank", "title": HTTPStatus(status).phrase,
            "status": status, "detail": detail, "instance": "urn:uuid:" + trace,
            "code": code, "traceId": trace}
    if fields is not None:
        body["fields"] = fields
    log.warning("code=%s traceId=%s", code, trace)
    return JSONResponse(body, status_code=status, media_type="application/problem+json", headers=headers)


def create_app(settings: Settings | None = None, client_factory: Callable[[Settings], AI] = build_ai) -> FastAPI:
    config = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resource = client_factory(config)
        app.state.ai = resource
        try:
            yield
        finally:
            await resource.aclose()

    app = FastAPI(lifespan=lifespan, debug=False)

    @app.middleware("http")
    async def trace_and_failures(request: Request, call_next):
        request.state.trace_id = str(uuid4())
        try:
            response = await call_next(request)
        except Exception:
            # No raw exception, chained message, body, header or prompt in logs.
            response = problem(request, "internal_error")
        response.headers["X-Trace-Id"] = request.state.trace_id
        return response

    @app.exception_handler(AIProblem)
    async def ai_failure(request: Request, error: AIProblem):
        return problem(request, error.code)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, error: RequestValidationError):
        # Public field names only; exclude input, ctx, messages and unknown keys.
        fields = [{"loc": ["body", "question"] if "question" in row["loc"] else ["body"],
                   "code": "invalid"} for row in error.errors()]
        return problem(request, "invalid_input", fields=fields)

    @app.exception_handler(HTTPException)
    async def framework_error(request: Request, error: HTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(error.status_code, "internal_error")
        headers = {"Allow": error.headers["Allow"]} if error.status_code == 405 and error.headers and "Allow" in error.headers else None
        return problem(request, code, headers=headers)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    if config.app_env != "production":
        @app.get("/ai/status")
        async def ai_status(ai: Annotated[AI, Depends(get_ai)]):
            return {"mode": ai.mode, "environment": config.app_env,
                    "example_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}

    @app.post("/answer", response_model=Answer)
    async def answer(payload: Question, ai: Annotated[AI, Depends(get_ai)]):
        # Includes the adapter's attempts and SDK backoff. Non-streaming only.
        deadline = asyncio.get_running_loop().time() + config.ai_deadline
        try:
            async with asyncio.timeout_at(deadline):
                return await ai.answer(payload.question)
        except TimeoutError:
            raise AIProblem("ai_timeout") from None

    return app


app = create_app()
```

### test_example.py

```python
import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace as Item
import unittest
from unittest.mock import patch

from asgi_lifespan import LifespanManager
import httpx2
from openai import (
    APIConnectionError, APITimeoutError, AsyncOpenAI, AuthenticationError,
    InternalServerError, RateLimitError,
)
from pydantic import SecretStr

import example_app as example

SENTINEL = "SYNTHETIC_PRIVATE_VALUE_NEVER_LOG"


def completion(text='{"answer":"checked","sources":[]}'):
    return Item(status="completed", output=[
        Item(type="reasoning"), Item(type="message", status="completed",
                                    content=[Item(type="output_text", text=text)])])


class SDKDouble:
    def __init__(self, response=None, error=None):
        self.responses, self.response, self.error = self, response or completion(), error
        self.calls, self.closed = [], 0

    async def create(self, **arguments):
        self.calls.append(arguments)
        if self.error:
            raise self.error
        return self.response

    async def close(self):
        self.closed += 1


class ScriptedAI(example.FakeAI):
    def __init__(self, failure=None, *, wait=False):
        self.failure, self.wait = failure, wait
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.calls, self.closed, self.cancelled = 0, 0, False

    async def answer(self, question):
        self.calls += 1
        self.entered.set()
        if self.failure:
            raise self.failure
        if self.wait:
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return await super().answer(question)

    async def aclose(self):
        self.closed += 1


@asynccontextmanager
async def session(resource=None, *, settings=None, factory=None):
    settings = settings or example.Settings(app_env="development", openai_api_key=None)
    app = example.create_app(settings, factory or (lambda _: resource))
    async with LifespanManager(app) as manager:
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=manager.app, raise_app_exceptions=False),
            base_url="http://example.test",
        ) as client:
            yield app, client


def require_fake(status, actual_target, expected_target, expected_source):
    if (actual_target != expected_target or status != {
            "mode": "fake", "environment": "development", "example_sha256": expected_source}):
        raise RuntimeError("The target has not passed fake-mode preflight")


class ExampleTest(unittest.IsolatedAsyncioTestCase):
    def assert_problem(self, response, status, code):
        body = response.json()
        self.assertEqual(response.status_code, status)
        self.assertEqual(response.headers["content-type"], "application/problem+json")
        self.assertEqual((body["status"], body["code"]), (status, code))
        self.assertTrue({"type", "title", "detail", "instance", "traceId"} <= body.keys())
        self.assertEqual(response.headers["x-trace-id"], body["traceId"])
        self.assertNotIn(SENTINEL, response.text)

    async def test_resource_is_created_once_reused_and_closed_per_lifespan(self):
        created = []
        def factory(_):
            resource = ScriptedAI(); created.append(resource); return resource
        for _ in range(2):
            async with session(factory=factory) as (_, client):
                for _ in range(2):
                    self.assertEqual((await client.post("/answer", json={"question": "fixture"})).status_code, 200)
                self.assertEqual(created[-1].closed, 0)
            self.assertEqual((created[-1].calls, created[-1].closed), (2, 1))
        self.assertEqual(len(created), 2)
        self.assertIsNot(created[0], created[1])

    async def test_production_without_key_starts_and_only_ai_is_unavailable(self):
        settings = example.Settings(app_env="production", openai_api_key=None)
        with patch.object(example, "AsyncOpenAI", side_effect=AssertionError("must not construct SDK")) as constructor:
            async with session(settings=settings, factory=example.build_ai) as (_, client):
                self.assertEqual((await client.get("/health")).json(), {"status": "ok"})
                self.assert_problem(await client.post("/answer", json={"question": "fixture"}), 503, "ai_unavailable")
                self.assertEqual((await client.get("/ai/status")).status_code, 404)
            constructor.assert_not_called()

    async def test_test_factories_and_dependencies_keep_a_present_key_off_the_network(self):
        settings = example.Settings(app_env="production", openai_api_key=SecretStr(SENTINEL), openai_model="fixture")
        lifecycle, request = ScriptedAI(), ScriptedAI()
        with patch.object(example, "AsyncOpenAI", side_effect=AssertionError("must not construct SDK")) as constructor:
            async with session(lifecycle, settings=settings) as (app, client):
                app.dependency_overrides[example.get_ai] = lambda: request
                self.assertEqual((await client.post("/answer", json={"question": "fixture"})).status_code, 200)
            constructor.assert_not_called()
        self.assertEqual((lifecycle.calls, lifecycle.closed, request.calls), (0, 1, 1))
        await request.aclose()  # the test owns this second resource

    async def test_slow_ai_leaves_the_health_route_responsive(self):
        resource = ScriptedAI(wait=True)
        async with session(resource) as (_, client):
            slow = asyncio.create_task(client.post("/answer", json={"question": "fixture"}))
            try:
                await asyncio.wait_for(resource.entered.wait(), 2)
                health = await asyncio.wait_for(client.get("/health"), 2)
                self.assertEqual(health.status_code, 200)
                self.assertFalse(slow.done())
            finally:
                resource.release.set()
                response = await slow
            self.assertEqual(response.status_code, 200)

    async def test_total_deadline_cancels_the_wait_and_does_not_report_success(self):
        resource = ScriptedAI(wait=True)
        settings = example.Settings(app_env="development", openai_api_key=None, ai_deadline=.03)
        async with session(resource, settings=settings) as (_, client):
            response = await client.post("/answer", json={"question": "fixture"})
            self.assert_problem(response, 504, "ai_timeout")
            self.assertTrue(resource.cancelled)
            self.assertEqual(resource.calls, 1)
        self.assertEqual(resource.closed, 1)

    async def test_real_sdk_retry_sleep_is_inside_the_application_deadline(self):
        attempts = []
        async def upstream(request):
            attempts.append(request)
            return httpx2.Response(503, request=request, headers={"retry-after-ms": "10000"},
                                   json={"error": {"message": SENTINEL}})
        transport = httpx2.AsyncClient(transport=httpx2.MockTransport(upstream))
        sdk = AsyncOpenAI(api_key="not-a-provider-key", base_url="http://provider.invalid/v1", http_client=transport, max_retries=1)
        adapter = example.OpenAIAdapter(sdk, "fixture")
        settings = example.Settings(app_env="development", openai_api_key=None, ai_deadline=1.0)
        async with session(adapter, settings=settings) as (_, client):
            self.assert_problem(await client.post("/answer", json={"question": "fixture"}), 504, "ai_timeout")
            await asyncio.sleep(.05)
            self.assertEqual(len(attempts), 1)
        self.assertTrue(transport.is_closed)

    async def test_actual_sdk_exception_subclasses_map_once_without_raw_messages(self):
        request = httpx2.Request("POST", "http://provider.invalid/v1/responses")
        response = lambda status: httpx2.Response(status, request=request)
        errors = [
            (APITimeoutError(request=request), 504, "ai_timeout"),
            (APIConnectionError(message=SENTINEL, request=request), 503, "ai_unavailable"),
            (AuthenticationError(SENTINEL, response=response(401), body={}), 503, "ai_unavailable"),
            (RateLimitError(SENTINEL, response=response(429), body={}), 503, "ai_upstream_busy"),
            (InternalServerError(SENTINEL, response=response(500), body={}), 502, "ai_upstream_error"),
        ]
        for error, status, code in errors:
            with self.subTest(error=type(error).__name__), self.assertLogs("example.ai", logging.WARNING) as captured:
                sdk = SDKDouble(error=error)
                async with session(example.OpenAIAdapter(sdk, "fixture")) as (_, client):
                    self.assert_problem(await client.post("/answer", json={"question": SENTINEL}), status, code)
                self.assertEqual(sdk.closed, 1)
                self.assertNotIn(SENTINEL, "\n".join(captured.output))
                self.assertTrue(all(call["store"] is False for call in sdk.calls))

    async def test_typed_completion_refusal_incomplete_empty_and_bad_schema(self):
        variants = [
            (completion(), 200, None),
            (Item(status="incomplete", output=[]), 502, "ai_invalid_response"),
            (Item(status="completed", output=[]), 502, "ai_invalid_response"),
            (completion("{}"), 502, "ai_invalid_response"),
            (completion("not json"), 502, "ai_invalid_response"),
            (Item(status="completed", output=[Item(type="message", status="completed", content=[Item(type="refusal", refusal=SENTINEL)])]), 422, "ai_refused"),
        ]
        for value, status, code in variants:
            with self.subTest(status=status, code=code):
                sdk = SDKDouble(response=value)
                async with session(example.OpenAIAdapter(sdk, "fixture")) as (_, client):
                    response = await client.post("/answer", json={"question": "fixture"})
                    if code: self.assert_problem(response, status, code)
                    else: self.assertEqual(response.json(), {"answer": "checked", "sources": []})

    async def test_real_framework_validation_404_405_and_fault_500_are_safe(self):
        resource = ScriptedAI(failure=RuntimeError(SENTINEL))
        with self.assertLogs("example.ai", logging.WARNING) as captured:
            async with session(resource) as (_, client):
                invalid = await client.post("/answer", json={"question": [], SENTINEL: SENTINEL})
                self.assert_problem(invalid, 422, "invalid_input")
                self.assertTrue(invalid.json()["fields"])
                self.assert_problem(await client.get("/absent"), 404, "not_found")
                wrong = await client.get("/answer")
                self.assert_problem(wrong, 405, "method_not_allowed")
                self.assertIn("POST", wrong.headers["allow"])
                self.assert_problem(await client.post("/answer", json={"question": SENTINEL}), 500, "internal_error")
        self.assertNotIn(SENTINEL, "\n".join(captured.output))

    async def test_fake_preflight_checks_live_mode_target_and_source_without_a_model_probe(self):
        resource = ScriptedAI()
        expected = hashlib.sha256(Path(example.__file__).read_bytes()).hexdigest()
        async with session(resource) as (_, client):
            status = (await client.get("/ai/status")).json()
            require_fake(status, str(client.base_url), "http://example.test", expected)
            self.assertEqual(resource.calls, 0)
            for change in ({"mode": "real"}, {"environment": "production"}, {"example_sha256": "old"}):
                with self.subTest(change=change), self.assertRaises(RuntimeError):
                    require_fake(dict(status, **change), str(client.base_url), "http://example.test", expected)
            with self.assertRaises(RuntimeError):
                require_fake(status, "http://other.test", "http://example.test", expected)
            self.assertEqual(resource.calls, 0)


if __name__ == "__main__":
    unittest.main()
```

## Primary sources

Checked 2026-11-04. Recheck against the product's pinned versions:

- [FastAPI async execution](https://fastapi.tiangolo.com/async/#very-technical-details), [lifespan](https://fastapi.tiangolo.com/advanced/events/), [ASGI lifespan](https://asgi.readthedocs.io/en/latest/specs/lifespan.html): ownership and blocking-call boundaries.
- [FastAPI dependency overrides](https://fastapi.tiangolo.com/advanced/testing-dependencies/), [lifespan testing](https://fastapi.tiangolo.com/advanced/testing-events/), [async testing](https://fastapi.tiangolo.com/advanced/async-tests/), [asgi-lifespan state](https://github.com/florimondmanca/asgi-lifespan#accessing-state): explicit startup/shutdown and transport choice.
- [OpenAI Python v3.45.0](https://github.com/openai/openai-python/tree/v3.45.0), [async client and retry implementation](https://github.com/openai/openai-python/blob/v3.45.0/src/openai/_base_client.py): public timeout type, exception hierarchy, async close, retries and cancellation.
- [Python total deadlines](https://docs.python.org/3/library/asyncio-task.html#asyncio.timeout_at): cancellation-based timeout semantics, requiring Python 3.11+.
- [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data), [text output](https://developers.openai.com/api/docs/guides/text): endpoint/feature-specific storage and typed output.
- [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457.html), [RFC 9110 section 15.5.6](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.6), [Starlette exceptions](https://www.starlette.io/exceptions/), [Pydantic error details](https://docs.pydantic.dev/latest/errors/errors/), [OWASP logging](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html): status/header semantics and safe diagnostic boundaries.
