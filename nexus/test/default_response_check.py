"""Pinned external QA: every named default's actual handler/header/schema.

Prism's example-body checks and these offline actual-handler controls are
separate from live development faults, persisted effects and screen acceptance.
"""
import json
import os
import subprocess
from pathlib import Path

import jsonschema
import yaml

root = Path(__file__).resolve().parents[2]
api = yaml.safe_load((root / "docs/06-api/nexus.openapi.yaml").read_text(encoding="utf8"))


def deref(value):
    while "$ref" in value:
        ref = value["$ref"]
        if not ref.startswith("#/"):
            raise SystemExit("external references are not allowed in this fixture")
        value = api
        for segment in ref[2:].split("/"):
            value = value[segment.replace("~1", "/").replace("~0", "~")]
    return value


manifest, schemas = [], []
methods = ("get", "post", "put", "patch", "delete", "head")
for path, item in api["paths"].items():
    allowed = {method.upper() for method in item if method in methods}
    if "GET" in allowed:
        allowed.add("HEAD")
    allow = ", ".join(method for method in ("GET", "HEAD", "POST", "DELETE") if method in allowed)
    for method, operation in item.items():
        if method not in methods or "default" not in operation["responses"]:
            continue
        for media, definition in deref(operation["responses"]["default"])["content"].items():
            for example, value in definition["examples"].items():
                value = deref(value)["value"]
                status = value["status"] if isinstance(value, dict) else {"internal": 500, "method-not-allowed": 405}[example]
                manifest.append({"operation": operation["operationId"], "method": method, "path": path,
                                 "status": status, "media": media, "example": example, "allow": allow})
                schemas.append(definition["schema"])
if len(manifest) != 70:
    raise SystemExit("the named-default inventory changed; review the intended coverage")
program = None
for folder in os.environ.get("PATH", "").split(os.pathsep):
    folder = folder.strip('"')
    if not os.path.isabs(folder) or Path(folder).resolve() == Path.cwd().resolve():
        continue
    candidate = Path(folder) / ("node.exe" if os.name == "nt" else "node")
    if candidate.is_file() and os.access(candidate, os.X_OK):
        program = str(candidate)
        break
if program is None:
    raise SystemExit("Node 22.13 or later must be installed on an absolute PATH entry")
env = {key: value for key, value in os.environ.items() if not key.startswith(("CORTHEX_NEXUS_", "NEXUS_DEV_"))}
run = subprocess.run([program, str(Path(__file__).with_name("default-response-corpus.mjs"))],
                     input=json.dumps(manifest).encode("utf8"), cwd=str(root), env=env, capture_output=True, timeout=60)
if run.returncode:
    raise SystemExit("the offline default/header controls failed; inspect the synthetic assertion locally")
records = json.loads(run.stdout.decode("utf8"))
if len(records) != len(manifest):
    raise SystemExit("incomplete default-response controls")
for expected, schema, record in zip(manifest, schemas, records):
    if any(record[key] != expected[key] for key in ("operation", "media", "example")):
        raise SystemExit("the default-response corpus order differs from its manifest")
    validator = jsonschema.Draft202012Validator(schema, resolver=jsonschema.RefResolver.from_schema(api),
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)
    if list(validator.iter_errors(record["value"])):
        raise SystemExit("an actual default response does not match its full OpenAPI schema")
print("offline default controls: 70/70 actual statuses, media, common headers, CSP, Allow, trace/log and full schemas passed")
