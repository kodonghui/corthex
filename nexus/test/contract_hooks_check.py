"""Run with the externally pinned contract environment, not plugin Python.

python nexus/test/contract_hooks_check.py
"""
import json
import sys
from pathlib import Path

import jsonschema
import requests
import schemathesis
from schemathesis import experimental

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from nexus.test.contract_hooks import response_schema_by_media_type

experimental.OPEN_API_3_1.enable()
schema = schemathesis.from_path(str(Path(__file__).resolve().parents[2] / "docs/06-api/nexus.openapi.yaml"))
case = schema["/pictures/{project}/{part}/{stage}"]["GET"].make_case()
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
