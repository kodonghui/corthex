"""Hooks for the externally pinned Schemathesis 3.39.16 QA tool.

These are not installed with the plugin or imported by its standard-library
runtime. Default credentials/cookies are synthetic. Live tests explicitly opt
in and pin their origin; they never acquire a person's browser cookie.
"""
import os
import secrets
from urllib.parse import urlsplit

import schemathesis


@schemathesis.check
def response_schema_by_media_type(context, response, case):
    """Keep 3.39.16's JSON checks, selecting the actual response media type.

    That pinned version takes the first documented content entry even when the
    response is JSON and that entry is HTML. Pages legitimately document both.
    Select one entry before using its resolver/JSON Schema 2020-12 validator;
    do not loosen the contract or turn schema checking off.
    """
    import jsonschema

    schema = case.operation.schema
    definitions = case.operation.definition.raw.get("responses", {})
    definition = definitions.get(str(response.status_code), definitions.get("default"))
    if definition is None:
        return
    scopes, resolved = schema.resolver.resolve_in_scope(definition, case.operation.definition.scope)
    media_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    documented = resolved.get("content", {})
    selected = next((value for name, value in documented.items() if name.lower() == media_type), None)
    # The separate built-in content_type_conformance check rejects an
    # undocumented or missing type. Preserve the pinned tool's non-JSON rule.
    if selected is None or not (media_type.endswith("+json") or media_type == "application/json"):
        return
    extra_scopes, response_schema = schema.get_response_schema({"content": {media_type: selected}}, case.operation.definition.scope)
    if response_schema is not None:
        with schema._validating_response(scopes + extra_scopes) as resolver:
            jsonschema.validate(response.json(), response_schema, cls=schema.validator_cls, resolver=resolver,
                                format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)


PATH_VALUES = {
    "project": "qa-nexus-contract", "part": "nexus", "stage": "05-erd",
    "pictureStage": "05-erd", "file": "missing.deadbeef.js",
    "comment": "nc_000000000000", "proposal": "np_000000000000",
    "edit": "ne_000000000000", "checkpoint": "nk_000000000000",
    "entry": "nc_000000000000",
}


@schemathesis.hook
def before_generate_path_parameters(context, strategy):
    return strategy.map(lambda values: {key: PATH_VALUES.get(key, value) for key, value in (values or {}).items()})


@schemathesis.hook
def before_generate_cookies(context, strategy):
    return strategy.map(lambda values: dict(values or {}, CF_Authorization="synthetic-access-cookie"))


@schemathesis.hook
def before_generate_headers(context, strategy):
    def stub(values):
        result = dict(values or {})
        result.update({"CF-Access-Client-Id": "synthetic-client-id",
                       "CF-Access-Client-Secret": "synthetic-client-secret",
                       "Nexus-Session": "qa-contract", "User-Agent": "corthex-nexus-contract/0.2"})
        return result
    return strategy.map(stub)


@schemathesis.hook
def before_call(context, case):
    # Even generated snapshot writes/removals stay in one synthetic namespace.
    case.path_parameters = {key: PATH_VALUES.get(key, value) for key, value in (case.path_parameters or {}).items()}
    if case.method.upper() == "POST" and case.path == "/api/snapshots" and isinstance(case.body, dict):
        project = case.body.get("project")
        if isinstance(project, dict):
            project["name"] = PATH_VALUES["project"]
    headers = dict(case.headers or {})
    alphabet = "0123456789abcdefghjkmnpqrstvwxyz"
    headers["Idempotency-Key"] = '"nw_' + "".join(secrets.choice(alphabet) for _ in range(12)) + '"'
    headers["Nexus-Session"] = "qa-contract"
    headers["User-Agent"] = "corthex-nexus-contract/0.2"
    if os.environ.get("NEXUS_CONTRACT_LIVE") == "1":
        target = urlsplit(os.environ.get("NEXUS_CONTRACT_URL", ""))
        actual = urlsplit(case.base_url or "")
        if target.scheme != "https" or not target.hostname or target.username or target.password or target.query or target.fragment:
            raise RuntimeError("NEXUS_CONTRACT_URL must be the explicitly selected development HTTPS origin")
        if (actual.scheme, actual.hostname, actual.port) != (target.scheme, target.hostname, target.port):
            raise RuntimeError("the contract request does not match the selected development origin")
        client = os.environ.get("NEXUS_CONTRACT_CLIENT_ID")
        secret = os.environ.get("NEXUS_CONTRACT_CLIENT_SECRET")
        if not client or not secret:
            raise RuntimeError("development service variables are missing")
        headers["CF-Access-Client-Id"] = client
        headers["CF-Access-Client-Secret"] = secret
        # The synthetic cookie generator is not a human login. Live runs use
        # only the development service token; Aside verifies the human role.
        case.cookies = {}
    case.headers = headers
