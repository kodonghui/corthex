"""External pinned QA only: validate real hub outputs against stage 06.

PyYAML/jsonschema belong in the external contract environment, never the
plugin runtime. No network or real-account data is used or uploaded here.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import yaml

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "tests"))
from test_hub02 import GitSourcesFixture, NOW, hub

api = yaml.safe_load((root / "docs/06-api/nexus.openapi.yaml").read_text(encoding="utf8"))
schemas = api["components"]["schemas"]
copied = (root / "nexus/src/input-schemas.js").read_text(encoding="utf8")
copied = json.loads(copied.split("Object.freeze(", 1)[1].rsplit(");", 1)[0])
if any(value != schemas[name] for name, value in copied.items()):
    raise SystemExit("the server input schemas differ from stage 06")


def validate(name, schema, value):
    validator = jsonschema.Draft202012Validator(schemas[schema],
        resolver=jsonschema.RefResolver.from_schema(api),
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)
    errors = list(validator.iter_errors(value))
    if errors:
        # Report shape and rule, never text or credential-shaped values.
        print(json.dumps({"case": name, "schema": schema,
                          "errors": [{"path": list(e.absolute_path), "rule": e.validator} for e in errors[:10]]}))
        raise SystemExit(1)


fixture = GitSourcesFixture()
fixture.setUp()
try:
    snapshot = fixture.snapshot()
    validate("fetched Git objects and optional checkpoint link", "Snapshot02", snapshot)
    validate("repository records", "StageRecords", fixture.record)
    args = hub.parser().parse_args(["status", "acme-shop", "05-erd", "--state", "done", "--checkpoint", "Approved",
                                   "--by", "the maintainer", "--date", "2026-11-03", "--repository"])
    project = hub.select_projects(fixture.home, ["acme-shop"])[0][1]
    _, path = hub.companion("records").write(project, fixture.home, args, vars(hub), NOW)
    validate("written repository checkpoint without optional where", "StageRecords", json.loads(path.read_text(encoding="utf8")))
    helper = SimpleNamespace(**vars(hub), picture_ids=hub.IdFormat({}))
    for language in ("md", "ko.md"):
        checks = []
        file = "docs/01-domain/nexus." + language
        data = hub.companion("domain").parse([(file, (root / file).read_text(encoding="utf8"))], checks, helper, "nexus")
        validate("NEXUS domain " + language, "DomainSource", data)
        if len(data.get("timeline", [])) != 5:
            raise SystemExit("the NEXUS domain fixture must retain all five timeline lanes")
    checks = []
    row = "| Given by | Read model | Command | Aggregate | Events |\n| --- | --- | --- | --- | --- |\n| User | Summary | Save | Order | Saved |\n"
    data = hub.companion("domain").parse([("fixture.md", row + "\n## CTX-001 Shop\n## Other section\n" + row)], checks, helper, "nexus")
    validate("orphan commands with anonymous and preceding contexts", "DomainSource", data)
    for check in checks:
        validate("orphan command diagnostics", "Check", check)
    for name, file, schema in (("erd", "docs/05-erd/nexus.sql", "ErdSource"),
                               ("sitemap", "docs/07-sitemap/nexus.yaml", "SitemapSource")):
        checks = []
        data = hub.companion(name).parse([(file, (root / file).read_text(encoding="utf8"))], checks, helper, "nexus")
        validate("NEXUS " + name, schema, data)
    box = hub.companion("outbox").Outbox(fixture.home, "acme-shop")
    queued = box.make("reply", "/api/spaces/acme-shop/comments/nc_aaaaaaaaaaaa/replies", "test-session", {"text": "Synthetic reply"})
    validate("unsent original-ID write", "OutboxFile", queued)
finally:
    fixture.tearDown()

print("hub contracts: real Git-object snapshot, repository records, English/Korean NEXUS pictures and outbox passed")
