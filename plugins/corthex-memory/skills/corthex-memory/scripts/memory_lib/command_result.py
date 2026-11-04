"""TASK-064: offline whole-result checks and a nonrecursive failure boundary.

No runner, effects, logging or output live here. finalize() returns a detached
JSON document and its status; TASK-065 owns printing and the process exit. The
format-1 resource is read afresh, identified by its authoritative bytes, and
audited before any branch is evaluated. Configuration's cached schema/root is
deliberately separate. A future schema change must update the format pin and
review keyword support; it cannot silently relax this boundary.
"""

import hashlib
import json
import math
from pathlib import Path
import re

RESOURCE = Path(__file__).with_name("result.schema.json")
SCHEMA_SHA256 = "08e11a168ee1ff645d1c0234c814699980ef220cf773ca36fdcda9bfb1bbda93"
COMMANDS = tuple(("on off status resume list search open pin unpin forget "
                  "delete-project purge leave-out retention sync setup repair conflicts runs undo none").split())
KEYWORDS = frozenset(("$schema title description $defs $ref type properties required "
                      "additionalProperties propertyNames minimum maximum minLength maxLength "
                      "pattern minItems maxItems uniqueItems items enum const allOf anyOf "
                      "if then else not").split())
SAY = "Memory could not complete this command."
ERRORS = ((OSError, "OSError"), (PermissionError, "PermissionError"),
          (FileNotFoundError, "FileNotFoundError"), (ValueError, "ValueError"),
          (TypeError, "TypeError"), (RuntimeError, "RuntimeError"),
          (RecursionError, "RecursionError"), (OverflowError, "OverflowError"),
          (UnicodeError, "UnicodeError"), (MemoryError, "MemoryError"))


class ResultInvalid(ValueError):
    def __init__(self):
        super().__init__("invalid command result")


class SchemaInvalid(RuntimeError):
    def __init__(self):
        super().__init__("unusable command result schema")


def _number(value):
    return type(value) is int or type(value) is float and math.isfinite(value)


def _integer(value):
    return _number(value) and (type(value) is int or value.is_integer())


def _plain(value):
    """JSON types only, including finite numbers and string object keys."""
    if type(value) is dict:
        if not all(type(key) is str for key in value):
            raise ResultInvalid()
        for child in value.values():
            _plain(child)
    elif type(value) is list:
        for child in value:
            _plain(child)
    elif value is not None and type(value) not in (str, bool) and not _number(value):
        raise ResultInvalid()


def _same(a, b):
    if _number(a) and _number(b):
        return a == b
    if type(a) is not type(b):
        return False
    if type(a) is dict:
        return a.keys() == b.keys() and all(_same(a[key], b[key]) for key in a)
    if type(a) is list:
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


class _Validator:
    """Supported format-1 JSON Schema subset; no external or cached refs."""
    def __init__(self, root):
        self.root = root
        self.patterns = {}
        try:
            _plain(root)
            self._audit(root, set())
        except Exception:
            raise SchemaInvalid() from None

    def _ref(self, node):
        ref = node["$ref"]
        if type(ref) is not str or not ref.startswith("#/$defs/"):
            raise SchemaInvalid()
        name = ref[8:]
        if not name or "/" in name or "~" in name:
            raise SchemaInvalid()
        return self.root["$defs"][name]

    def _audit(self, node, active):
        if type(node) is bool:
            return
        if type(node) is not dict or set(node) - KEYWORDS or id(node) in active:
            raise SchemaInvalid()
        active = active | {id(node)}
        for key in ("title", "description"):
            if key in node and type(node[key]) is not str:
                raise SchemaInvalid()
        if "$schema" in node and node["$schema"] != "https://json-schema.org/draft/2020-12/schema":
            raise SchemaInvalid()
        if "type" in node and node["type"] not in ("object", "array", "string", "integer", "number", "boolean", "null"):
            raise SchemaInvalid()
        for key in ("minimum", "maximum"):
            if key in node and not _number(node[key]):
                raise SchemaInvalid()
        for key in ("minLength", "maxLength", "minItems", "maxItems"):
            if key in node and (not _integer(node[key]) or node[key] < 0):
                raise SchemaInvalid()
        if "uniqueItems" in node and type(node["uniqueItems"]) is not bool:
            raise SchemaInvalid()
        if "required" in node:
            names = node["required"]
            if type(names) is not list or any(type(x) is not str for x in names) or len(names) != len(set(names)):
                raise SchemaInvalid()
        if "enum" in node:
            choices = node["enum"]
            if type(choices) is not list or not choices or any(_same(a, b) for i, a in enumerate(choices) for b in choices[i + 1:]):
                raise SchemaInvalid()
        if "pattern" in node:
            pattern = node["pattern"]
            if type(pattern) is not str:
                raise SchemaInvalid()
            # The authoritative patterns use $ only as an end anchor.
            self.patterns[pattern] = re.compile(pattern.replace("$", r"\Z"))
        for key in ("properties", "$defs"):
            if key in node:
                if type(node[key]) is not dict:
                    raise SchemaInvalid()
                for child in node[key].values():
                    self._audit(child, active)
        for key in ("items", "additionalProperties", "propertyNames", "if", "then", "else", "not"):
            if key in node:
                self._audit(node[key], active)
        for key in ("anyOf", "allOf"):
            if key in node:
                if type(node[key]) is not list or not node[key]:
                    raise SchemaInvalid()
                for child in node[key]:
                    self._audit(child, active)
        if "$ref" in node:
            self._audit(self._ref(node), active)

    def matches(self, value, node=None):
        node = self.root if node is None else node
        if type(node) is bool:
            return node
        if "$ref" in node and not self.matches(value, self._ref(node)):
            return False
        types = {"object": lambda x: type(x) is dict, "array": lambda x: type(x) is list,
                 "string": lambda x: type(x) is str, "integer": _integer, "number": _number,
                 "boolean": lambda x: type(x) is bool, "null": lambda x: x is None}
        if "type" in node and not types[node["type"]](value):
            return False
        if "const" in node and not _same(value, node["const"]):
            return False
        if "enum" in node and not any(_same(value, x) for x in node["enum"]):
            return False
        if type(value) is dict:
            properties = node.get("properties", {})
            if any(key not in value for key in node.get("required", [])):
                return False
            for key, child in value.items():
                if not self.matches(child, properties.get(key, node.get("additionalProperties", True))):
                    return False
                if "propertyNames" in node and not self.matches(key, node["propertyNames"]):
                    return False
        if type(value) is list:
            if not node.get("minItems", 0) <= len(value) <= node.get("maxItems", len(value)):
                return False
            if any(not self.matches(child, node.get("items", True)) for child in value):
                return False
            if node.get("uniqueItems") and any(_same(a, b) for i, a in enumerate(value) for b in value[i + 1:]):
                return False
        if type(value) is str:
            if not node.get("minLength", 0) <= len(value) <= node.get("maxLength", len(value)):
                return False
            if "pattern" in node and not self.patterns[node["pattern"]].search(value):
                return False
        if _number(value) and (value < node.get("minimum", value) or value > node.get("maximum", value)):
            return False
        if any(not self.matches(value, child) for child in node.get("allOf", [])):
            return False
        if "anyOf" in node and not any(self.matches(value, child) for child in node["anyOf"]):
            return False
        if "not" in node and self.matches(value, node["not"]):
            return False
        if "if" in node:
            branch = "then" if self.matches(value, node["if"]) else "else"
            if branch in node and not self.matches(value, node[branch]):
                return False
        return True


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SchemaInvalid()
        result[key] = value
    return result


def _load():
    try:
        raw = RESOURCE.read_bytes()
        if hashlib.sha256(raw).hexdigest() != SCHEMA_SHA256:
            raise SchemaInvalid()
        schema = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        return _Validator(schema)
    except Exception:
        raise SchemaInvalid() from None


def validate(document):
    """Raise a fixed safe error; never expose a value, key or exception text."""
    try:
        _plain(document)
    except Exception:
        raise ResultInvalid() from None
    if not _load().matches(document):
        raise ResultInvalid()


def _known(command):
    return command if type(command) is str and command in COMMANDS else "none"


def _internal(command, error):
    name = next((name for cls, name in ERRORS if type(error) is cls), "RuntimeError")
    return {"command": _known(command), "outcome": "failed", "code": "internal",
            "say": SAY, "data": {"error": name}}


def finalize(command, candidate):
    """Return (detached result, status), including a schema-independent fallback.

    command is the runner's trusted parsed command; unknown input is the schema's
    none sentinel. TASK-065 must turn actual argument errors into usage first.
    No failure logger is called here, since it needs the readable-store gate.
    """
    try:
        _plain(candidate)
        document = json.loads(json.dumps(candidate, ensure_ascii=True, allow_nan=False))
        validate(document)
        if document["command"] != _known(command):
            raise ResultInvalid()
        status = 2 if document["code"] == "usage" else 0 if document["outcome"] in ("done", "confirm", "nothing") else 1
        return document, status
    except Exception as error:
        # This path calls neither the loader nor the validator again.
        return _internal(command, error), 1
