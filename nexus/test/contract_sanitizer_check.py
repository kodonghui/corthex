"""Force failing two-worker CLI diagnostics with synthetic auth, offline."""
import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

import requests
from click.testing import CliRunner
from schemathesis.cli import schemathesis

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import nexus.test.contract_hooks  # Register before invoking the pinned CLI.

selected = "https://selected.example.invalid"
client, secret = "synthetic-worker-client-marker", "synthetic-worker-secret-marker"
seen, workers, mutex, barrier = [], set(), threading.Lock(), threading.Barrier(2)


class OfflineFailure(requests.adapters.BaseAdapter):
    def send(self, request, **kwargs):
        if request.headers.get("CF-Access-Client-Id") == client:
            with mutex:
                seen.append(request)
                workers.add(threading.get_ident())
                first_pair = len(seen) <= 2
            if first_pair:
                barrier.wait(timeout=10)
        response = requests.Response()
        response.request, response.status_code = request, 500
        response.headers["Content-Type"] = "application/json"
        response._content = b"{}"
        return response

    def close(self):
        pass


original = requests.Session
def offline_session(*args, **kwargs):
    session = original(*args, **kwargs)
    session.mount("http://", OfflineFailure())
    session.mount("https://", OfflineFailure())
    return session


with tempfile.TemporaryDirectory() as folder:
    path = Path(folder) / "schema.json"
    path.write_text(json.dumps({"openapi": "3.1.0", "info": {"title": "offline", "version": "1"},
        "paths": {"/api/snapshots/qa-nexus-contract/check-" + str(i): {"get": {"responses": {"500": {"description": "intentional diagnostic"}}}} for i in range(4)}}), encoding="utf8")
    env = {"SCHEMATHESIS_HOOKS": "nexus.test.contract_hooks", "NEXUS_CONTRACT_LIVE": "1", "NEXUS_CONTRACT_URL": selected,
           "NEXUS_CONTRACT_CLIENT_ID": client, "NEXUS_CONTRACT_CLIENT_SECRET": secret}
    with patch.dict(os.environ, env), patch("requests.Session", offline_session):
        result = CliRunner().invoke(schemathesis, ["run", str(path), "--base-url", selected, "--experimental=openapi-3.1",
            "--workers=2", "--hypothesis-max-examples=1", "--checks=not_a_server_error"])
    assert result.exit_code == 1, "the deliberate diagnostic failure was not observed"
    assert len(workers) >= 2 and len(seen) >= 4, "the two-worker control did not run"
    assert all(urlsplit(request.url).hostname == "selected.example.invalid" for request in seen), "the offline boundary changed origin"
    assert client not in result.output and secret not in result.output, "CLI diagnostics exposed an authentication component"
print("offline two-worker failure diagnostics: both authentication components redacted")
