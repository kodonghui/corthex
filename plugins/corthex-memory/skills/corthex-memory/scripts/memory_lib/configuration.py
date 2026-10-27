"""Strict, offline configuration validation and separate effective defaults."""

import copy
import functools
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

KEYWORDS = {"$schema", "title", "description", "$defs", "$ref", "type", "properties",
            "additionalProperties", "required", "propertyNames", "minimum", "maximum",
            "default", "enum", "minLength", "maxLength", "pattern", "minItems",
            "maxItems", "uniqueItems", "items", "minProperties"}
MISSING = object()


class ConfigurationInvalid(RuntimeError):
    def __init__(self, field):
        self.code, self.field = "configuration-invalid", field or "$"
        super().__init__(self.code)


def number(value):
    return (isinstance(value, int) and not isinstance(value, bool) or
            isinstance(value, float) and math.isfinite(value))


def integer(value):
    return number(value) and (isinstance(value, int) or value.is_integer())


@functools.lru_cache(maxsize=1)
def schema():
    data = json.loads(Path(__file__).with_name("configuration.schema.json").read_text(encoding="utf-8"))
    def audit(node):
        if isinstance(node, bool):
            return
        if set(node) - KEYWORDS:
            raise RuntimeError("unsupported configuration schema keyword")
        for group in ("properties", "$defs"):
            for child in node.get(group, {}).values():
                audit(child)
        for name in ("additionalProperties", "propertyNames", "items"):
            if name in node:
                audit(node[name])
    audit(data)
    return data


def resolve(node):
    if "$ref" in node:
        ref = node["$ref"]
        if not ref.startswith("#/$defs/") or ref[8:] not in schema()["$defs"]:
            raise RuntimeError("unsupported configuration reference")
        return dict(schema()["$defs"][ref[8:]], **{k: v for k, v in node.items() if k != "$ref"})
    return node


def field_at(parent, key):
    return parent + "." + key if parent else key


def validate(document):
    """First schema field in schema order; never echo values or map keys."""
    def visit(value, node, field):
        if node is False:
            raise ConfigurationInvalid(field)
        if node is True:
            return
        node = resolve(node)
        types = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
                 "string": lambda v: isinstance(v, str), "boolean": lambda v: isinstance(v, bool),
                 "integer": integer, "number": number}
        if "type" in node and not types[node["type"]](value):
            raise ConfigurationInvalid(field)
        if "enum" in node and value not in node["enum"]:
            raise ConfigurationInvalid(field)
        if isinstance(value, dict):
            if not all(isinstance(key, str) for key in value):
                raise ConfigurationInvalid(field)
            properties = node.get("properties", {})
            for key in node.get("required", []):
                if key not in value:
                    raise ConfigurationInvalid(field_at(field, key))
            for key, child in properties.items():
                if key in value:
                    visit(value[key], child, field_at(field, key))
            if len(value) < node.get("minProperties", 0):
                raise ConfigurationInvalid(field)
            for key in sorted(value):
                if "propertyNames" in node:
                    visit(key, node["propertyNames"], field)
                if key not in properties:
                    child = node.get("additionalProperties", True)
                    visit(value[key], child, field_at(field, "*" if child is not False else "<unknown>"))
        if isinstance(value, str):
            if not node.get("minLength", 0) <= len(value) <= node.get("maxLength", len(value)):
                raise ConfigurationInvalid(field)
            if "pattern" in node and not re.search(node["pattern"].replace("$", r"\Z"), value):
                raise ConfigurationInvalid(field)
        if number(value) and (value < node.get("minimum", value) or value > node.get("maximum", value)):
            raise ConfigurationInvalid(field)
        if isinstance(value, list):
            if not node.get("minItems", 0) <= len(value) <= node.get("maxItems", len(value)):
                raise ConfigurationInvalid(field)
            for index, item in enumerate(value):
                visit(item, node.get("items", True), field + "[%d]" % index)
            if node.get("uniqueItems") and any(a == b for i, a in enumerate(value) for b in value[i + 1:]):
                raise ConfigurationInvalid(field)
    visit(document, schema(), "")


def defaults(value, node):
    node = resolve(node)
    if value is MISSING:
        if "default" in node:
            value = copy.deepcopy(node["default"])
        elif node.get("type") == "object" and node.get("properties") and not node.get("required"):
            value = {}
        else:
            return MISSING
    if isinstance(value, dict):
        properties = node.get("properties", {})
        result = {}
        for key, child in properties.items():
            item = defaults(value.get(key, MISSING), child)
            if item is not MISSING:
                result[key] = item
        for key, item in value.items():
            if key not in properties:
                child = node.get("additionalProperties", True)
                result[key] = defaults(item, child) if isinstance(child, dict) else copy.deepcopy(item)
        return result
    if isinstance(value, list):
        return [defaults(item, node["items"]) if isinstance(node.get("items"), dict) else copy.deepcopy(item)
                for item in value]
    return int(value) if node.get("type") == "integer" else copy.deepcopy(value)


@dataclass(frozen=True)
class Configuration:
    document: dict
    values: dict

    def consented(self):
        return self.values.get("consent", {}).get("version") == 1

    def enabled(self, project):
        return self.consented() and self.values["projects"].get(project, {}).get("enabled", False)


def prepare(document, temporary=None):
    validate(document)
    if temporary is not None and not isinstance(temporary, bool):
        raise ValueError("invalid temporary flag")
    values = defaults(document, schema())
    values.setdefault("projects", {})
    if "temporary" not in values:
        values["temporary"] = os.environ.get("CLAUDE_CODE_REMOTE") == "true" if temporary is None else temporary
    return Configuration(copy.deepcopy(document), values)
