"""Run with the externally pinned contract environment, not plugin Python.

python nexus/test/contract_hooks_check.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

import jsonschema
import requests
import schemathesis
from click.testing import CliRunner
from schemathesis import experimental
from schemathesis.cli import schemathesis as command
from schemathesis.sanitization import sanitize_case

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from nexus.test.contract_hooks import process_call_kwargs, response_schema_by_media_type

experimental.OPEN_API_3_1.enable()
schema = schemathesis.from_path(str(Path(__file__).resolve().parents[2] / "docs/06-api/nexus.openapi.yaml"))
case = schema["/pictures/{project}/{part}/{stage}"]["GET"].make_case()
case.path_parameters = {"project": "qa-nexus-contract", "part": "nexus", "stage": "05-erd"}
response = requests.Response()
response.status_code = 404
response.headers["Content-Type"] = "application/problem+json; charset=utf-8"
valid = {"title": "No such project", "status": 404, "detail": "no such project",
         "code": "project_not_found", "traceId": "0123456789abcdef", "error": "no such project"}
response._content = json.dumps(valid).encode("utf8")
response_schema_by_media_type(None, response, case)
for invalid in ({**valid, "status": "404"}, {**valid, "title": 123}, {}):
    response._content = json.dumps(invalid).encode("utf8")
    try:
        response_schema_by_media_type(None, response, case)
    except jsonschema.ValidationError:
        continue
    raise AssertionError("the media-type schema check accepted an invalid Problem")
print("media-type response check: valid Problem accepted; three invalid Problems rejected")

# Run the real pinned CLI/transport through an offline adapter. A 302 must be
# returned to the checker without preparing a second credential-bearing hop.
class OfflineRedirect(requests.adapters.BaseAdapter):
    def __init__(self):
        self.requests = []

    def send(self, request, **kwargs):
        self.requests.append(request)
        response = requests.Response()
        response.request, response.status_code = request, 302
        response.headers.update({"Location": "https://other.example.invalid/blocked", "Content-Type": "application/json"})
        response._content = b"{}"
        return response

    def close(self):
        pass

adapter = OfflineRedirect()
original_session = requests.Session
def offline_session(*args, **kwargs):
    session = original_session(*args, **kwargs)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

selected = "https://selected.example.invalid"
synthetic_id, synthetic_secret = "synthetic-client-identifier-marker", "synthetic-service-secret-marker"
with tempfile.TemporaryDirectory() as folder:
    minimal = Path(folder) / "schema.json"
    minimal.write_text(json.dumps({"openapi": "3.1.0", "info": {"title": "offline", "version": "1"},
        "paths": {"/api/snapshots/qa-nexus-contract/held": {"get": {"responses": {"302": {"description": "offline redirect"}}}}}}), encoding="utf8")
    environment = {"SCHEMATHESIS_HOOKS": "nexus.test.contract_hooks", "NEXUS_CONTRACT_LIVE": "1",
        "NEXUS_CONTRACT_URL": selected, "NEXUS_CONTRACT_CLIENT_ID": synthetic_id,
        "NEXUS_CONTRACT_CLIENT_SECRET": synthetic_secret}
    with patch.dict(os.environ, environment), patch("requests.Session", offline_session):
        result = CliRunner().invoke(command, ["run", str(minimal), "--base-url", selected,
            "--experimental=openapi-3.1", "--hypothesis-max-examples=1", "--checks=not_a_server_error"])
    assert result.exit_code == 0, "the offline CLI control failed"
    credential_requests = [r for r in adapter.requests if "CF-Access-Client-Id" in r.headers]
    assert credential_requests, "the offline adapter did not see the authorized first request"
    assert all(urlsplit(r.url).hostname == "selected.example.invalid" for r in credential_requests), "credentials followed a redirect"
    case.headers = {"CF-Access-Client-Id": synthetic_id, "CF-Access-Client-Secret": synthetic_secret}
    diagnostic = case.partial_deepcopy()
    sanitize_case(diagnostic)
    rendered = diagnostic.as_curl_command()
    assert synthetic_id not in rendered and synthetic_secret not in rendered, "sanitized reproduction exposed a credential component"
    assert synthetic_id not in result.output and synthetic_secret not in result.output, "CLI diagnostic exposed a credential component"

    # An earlier synthetic CLI call must not authorize a later direct live
    # call that has no freshly bound no-redirect transport arguments.
    reused = schemathesis.from_path(str(minimal), base_url=selected)["/api/snapshots/qa-nexus-contract/held"]["GET"].make_case()
    session = offline_session()
    kwargs = {"session": session}
    process_call_kwargs(None, reused, kwargs)
    with patch.dict(os.environ, {"NEXUS_CONTRACT_LIVE": "0"}):
        reused.call(**kwargs)
    before = len(adapter.requests)
    with patch.dict(os.environ, environment):
        try:
            reused.call(session=session)
        except RuntimeError:
            pass
        else:
            raise AssertionError("a reused synthetic Case authorized an unguarded live call")
    assert len(adapter.requests) == before, "the rejected reused Case reached transport"
print("offline CLI: redirects stopped; both authentication components absent from diagnostics")
