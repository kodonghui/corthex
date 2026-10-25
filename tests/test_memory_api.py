"""Checks the corthex-memory interfaces of stage 06: the JSON Schemas, their examples and the
contract that docs/06-api/memory.md states about them."""

import json
import re
import unittest

from _common import ROOT, load_json, read_text

API = ROOT / "docs" / "06-api"
DOC = API / "memory.md"
MODEL_SCHEMAS = ["memory-curate.schema.json", "memory-merge.schema.json", "memory-state.schema.json"]
SCHEMAS = ["memory-configuration.schema.json", "memory-result.schema.json"] + MODEL_SCHEMAS

# What the validator below understands. A schema that uses anything else fails, so that no
# keyword is silently skipped.
KEYWORDS = {
    "$schema", "title", "description", "default", "$defs", "$ref", "type", "enum", "const",
    "properties", "required", "additionalProperties", "propertyNames", "minProperties",
    "items", "minItems", "maxItems", "uniqueItems", "minimum", "maximum", "minLength", "maxLength",
    "pattern", "anyOf", "allOf", "not", "if", "then", "else",
}
# What the structured outputs page lists as supported, less what the answer schemas need not use.
MODEL_KEYWORDS = {
    "type", "properties", "required", "additionalProperties", "items", "enum", "$ref", "$defs",
    "pattern", "minItems", "description",
}
TYPES = {
    "object": lambda value: isinstance(value, dict),
    "array": lambda value: isinstance(value, list),
    "string": lambda value: isinstance(value, str),
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "null": lambda value: value is None,
}
OUTCOMES = ("done", "confirm", "nothing", "refused", "failed")


def same(a, b):
    """JSON equality: true and 1 differ, 1 and 1.0 do not."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[key], b[key]) for key in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


def pattern(text):
    # JSON Schema patterns are ECMA-262, where `$` matches only at the end of the text. Python's
    # `$` also matches before a final line break, so it is read as `\Z`; the schemas use `$` only
    # as an anchor.
    return re.compile(text.replace("$", r"\Z"))


def errors(schema, value, root, path="$"):
    """Where value fails schema, as a list of messages; empty when it fits."""
    if schema is True:
        return []
    if schema is False:
        return [path + ": not allowed"]
    unknown = set(schema) - KEYWORDS
    if unknown:
        raise AssertionError("%s: the validator does not know %s" % (path, sorted(unknown)))
    found = []
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            raise AssertionError("%s: only local references are used, not %s" % (path, ref))
        found += errors(root["$defs"][ref[len("#/$defs/"):]], value, root, path)
    if "type" in schema and not TYPES[schema["type"]](value):
        return found + ["%s: not a %s" % (path, schema["type"])]
    if "enum" in schema and not any(same(value, option) for option in schema["enum"]):
        found.append("%s: %r is not one of %r" % (path, value, schema["enum"]))
    if "const" in schema and not same(value, schema["const"]):
        found.append("%s: %r is not %r" % (path, value, schema["const"]))
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                found.append("%s: %s is missing" % (path, key))
        for key, item in value.items():
            where = "%s.%s" % (path, key)
            if key in properties:
                found += errors(properties[key], item, root, where)
            elif "additionalProperties" in schema:
                found += errors(schema["additionalProperties"], item, root, where)
            if "propertyNames" in schema:
                found += errors(schema["propertyNames"], key, root, where + " (name)")
        if len(value) < schema.get("minProperties", 0):
            found.append("%s: fewer than %d fields" % (path, schema["minProperties"]))
    if isinstance(value, list):
        if "items" in schema:
            for number, item in enumerate(value):
                found += errors(schema["items"], item, root, "%s[%d]" % (path, number))
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", len(value)):
            found.append("%s: %d items" % (path, len(value)))
        if schema.get("uniqueItems") and any(same(a, b) for i, a in enumerate(value) for b in value[i + 1:]):
            found.append("%s: items repeat" % path)
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", len(value)):
            found.append("%s: %d characters" % (path, len(value)))
        if "pattern" in schema and not pattern(schema["pattern"]).search(value):
            found.append("%s: %r does not match %s" % (path, value, schema["pattern"]))
    if TYPES["number"](value):
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            found.append("%s: %r is out of range" % (path, value))
    for part in schema.get("allOf", []):
        found += errors(part, value, root, path)
    if "anyOf" in schema and all(errors(part, value, root, path) for part in schema["anyOf"]):
        found.append("%s: fits none of %d choices" % (path, len(schema["anyOf"])))
    if "not" in schema and not errors(schema["not"], value, root, path):
        found.append("%s: fits what is not allowed" % path)
    if "if" in schema:
        branch = "then" if not errors(schema["if"], value, root, path) else "else"
        if branch in schema:
            found += errors(schema[branch], value, root, path)
    return found


def fits(schema, value):
    return errors(schema, value, schema)


def section(text, heading):
    """From heading to the next heading of the same level or above."""
    start = text.index("\n" + heading + "\n") + 1
    level = heading.split(" ", 1)[0]
    ends = [text.find("\n" + "#" * size + " ", start + len(heading)) for size in range(1, len(level) + 1)]
    ends = [end for end in ends if end != -1]
    return text[start:min(ends)] if ends else text[start:]


def table(text):
    """The body rows of the first Markdown table in text, as lists of cells."""
    lines = []
    for line in text.splitlines():
        if line.startswith("|"):
            lines.append(line)
        elif lines:
            break
    return [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in lines[2:]]


def code_block(text, after, lang):
    start = text.index(after)
    begin = text.index("```" + lang + "\n", start) + len("```" + lang + "\n")
    return text[begin:text.index("```", begin)]


def ticked(cell):
    return re.findall(r"`([^`]+)`", cell)


def number(text):
    return float(text.replace(",", "")) if "." in text else int(text.replace(",", ""))


class SchemaTest(unittest.TestCase):
    def setUp(self):
        self.doc = read_text(DOC)
        self.schemas = {name: load_json(API / name) for name in SCHEMAS}
        self.examples = load_json(API / "memory-examples.json")

    def test_examples_fit_their_schemas(self):
        names = set()
        for part, group in self.examples.items():
            if part == "description":
                continue
            schema = self.schemas[group["schema"]]
            names.add(group["schema"])
            self.assertTrue(group["valid"] and group["invalid"], part)
            for name, example in group["valid"].items():
                with self.subTest(example=part + "/" + name):
                    self.assertEqual(fits(schema, example), [])
            for name, example in group["invalid"].items():
                with self.subTest(example=part + "/" + name, invalid=True):
                    self.assertNotEqual(fits(schema, example), [])
        self.assertEqual(names, set(SCHEMAS))

    def test_the_documents_examples_are_among_them(self):
        config = json.loads(code_block(self.doc, "Example, with consent, one enabled project and sync on:", "json"))
        self.assertEqual(self.examples["configuration"]["valid"]["with-sync"], config)
        result = json.loads(code_block(self.doc, "### The result", "json"))
        self.assertEqual(self.examples["result"]["valid"]["pin-no-room"], result)
        consent = code_block(self.doc, "### Consent text, version 1", "text").rstrip("\n")
        self.assertEqual(self.examples["result"]["valid"]["on-asks"]["data"]["consent"]["text"], consent)

    def test_no_field_is_named_id(self):
        # The project hub reads a JSON field named id as the definition of a trace ID.
        def keys(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    yield key
                    yield from keys(value)
            elif isinstance(node, list):
                for value in node:
                    yield from keys(value)

        for path in sorted(API.glob("*.json")):
            with self.subTest(file=path.name):
                self.assertNotIn("id", set(keys(load_json(path))))


class ModelSchemaTest(unittest.TestCase):
    """The answer schemas stay within what structured outputs accept (memory.md, Requests to the
    curator model)."""

    def check(self, node, where, defs):
        self.assertLessEqual(set(node), MODEL_KEYWORDS, where)
        if "properties" in node or node.get("type") == "object":
            self.assertEqual(node.get("type"), "object", where)
            self.assertIs(node.get("additionalProperties"), False, where)
            self.assertEqual(node.get("required"), list(node.get("properties", {})), where + ": every property required")
        if "minItems" in node:
            self.assertIn(node["minItems"], (0, 1), where)
        if "pattern" in node:
            text = node["pattern"]
            self.assertTrue(text.startswith("^") and text.endswith("$"), where)
            for banned in ("|", "(?", "\\b", "\\B"):
                self.assertNotIn(banned, text, where)
            self.assertIsNone(re.search(r"\\[1-9]", text), where)
            for low, high in re.findall(r"\{(\d+)(?:,(\d+))?\}", text):
                self.assertLessEqual(int(high or low), 64, where)
        if "enum" in node:
            self.assertTrue(all(isinstance(value, str) for value in node["enum"]), where)
            self.assertEqual(len({value.lower() for value in node["enum"]}), len(node["enum"]), where)
        if "$ref" in node:
            self.assertTrue(node["$ref"].startswith("#/$defs/"), where)
            self.assertIn(node["$ref"][len("#/$defs/"):], defs, where)
        for key, child in node.get("properties", {}).items():
            self.check(child, where + "." + key, defs)
        if "items" in node:
            self.check(node["items"], where + "[]", defs)

    def test_answer_schemas_keep_to_structured_outputs(self):
        for name in MODEL_SCHEMAS:
            with self.subTest(schema=name):
                schema = load_json(API / name)
                defs = schema.get("$defs", {})
                self.assertEqual(schema["type"], "object")
                self.check({key: value for key, value in schema.items() if key != "$defs"}, name, defs)
                for key, child in defs.items():
                    self.check(child, name + "#" + key, defs)
                # No definition reaches itself: the page does not accept recursive schemas.
                refs = {key: set(re.findall(r'"#/\$defs/([^"]+)"', json.dumps(child))) for key, child in defs.items()}
                for key in defs:
                    seen, todo = set(), set(refs[key])
                    while todo:
                        ref = todo.pop()
                        self.assertNotEqual(ref, key, name + ": " + key + " is recursive")
                        if ref not in seen:
                            seen.add(ref)
                            todo |= refs[ref]

    def test_state_answers_share_the_curate_answers_lines(self):
        curate = load_json(API / "memory-curate.schema.json")["$defs"]
        state = load_json(API / "memory-state.schema.json")["$defs"]
        self.assertEqual(set(state), {"state", "line"})
        for key in state:
            self.assertEqual(state[key], curate[key], key)


class ResultContractTest(unittest.TestCase):
    def setUp(self):
        self.doc = read_text(DOC)
        self.schema = load_json(API / "memory-result.schema.json")
        self.defs = self.schema["$defs"]
        self.results = table(section(self.doc, "### Command results"))
        self.commands = table(section(self.doc, "### Commands"))

    def branches(self):
        """{command: (codes, data definition)} from the result schema."""
        found = {}
        for branch in self.defs["data-of-each-command"]["else"]["anyOf"]:
            properties = branch["properties"]
            code = properties["code"]
            codes = set(code["enum"]) if "enum" in code else {code["const"]}
            command = properties["command"]["const"]
            self.assertNotIn(command, found)
            found[command] = (codes, properties["data"]["$ref"])
        return found

    def test_commands_match_the_document(self):
        documented = [ticked(row[0])[0] for row in self.commands]
        self.assertEqual(len(documented), len(set(documented)))
        self.assertEqual(self.schema["properties"]["command"]["enum"], documented + ["none"])
        self.assertEqual(set(self.branches()), set(documented))

    def test_codes_match_the_document(self):
        documented = [ticked(row[0])[0] for row in self.results]
        self.assertEqual(len(documented), len(set(documented)))
        self.assertEqual(self.schema["properties"]["code"]["enum"], ["ok"] + documented)

    def test_each_code_has_its_documented_outcomes(self):
        allowed = {}
        for choice in self.defs["outcome-of-each-code"]["anyOf"]:
            code, outcome = choice["properties"]["code"], choice["properties"]["outcome"]
            outcomes = set(outcome["enum"]) if "enum" in outcome else {outcome["const"]}
            for name in code["enum"] if "enum" in code else [code["const"]]:
                self.assertNotIn(name, allowed)
                allowed[name] = outcomes
        self.assertEqual(allowed.pop("ok"), {"done", "confirm", "nothing"})
        for row in self.results:
            code = ticked(row[0])[0]
            with self.subTest(code=code):
                self.assertEqual(allowed.pop(code), set(re.findall(r"\b(%s)\b" % "|".join(OUTCOMES), row[1])))
        self.assertEqual(allowed, {})

    def test_each_command_has_its_documented_codes(self):
        branches = self.branches()
        any_command = set(self.defs["any-command-codes"]["enum"])
        asks_first = {ticked(row[0])[0] for row in self.commands if row[3] != "no"}
        for row in self.results:
            code, cell = ticked(row[0])[0], row[2]
            with self.subTest(code=code):
                having = {command for command, (codes, _) in branches.items() if code in codes}
                if code in any_command:
                    self.assertEqual(having, set())
                    self.assertTrue(cell.startswith(("all", "the commands for a project", "the commands that change")), cell)
                elif cell == "the commands that ask first":
                    self.assertEqual(having, asks_first)
                else:
                    self.assertEqual(having, {name.split(" ")[0] for name in ticked(cell)})
        for command, (codes, _) in branches.items():
            self.assertIn("ok", codes, command)

    def test_each_command_has_its_interface(self):
        interfaces = {row[0]: row for row in table(section(self.doc, "## Interfaces"))}
        for row in self.commands:
            command, interface = ticked(row[0])[0], row[1]
            with self.subTest(command=command):
                self.assertEqual(interfaces[interface][1], "`%s`" % command)
                self.assertEqual(interfaces[interface][2], "command")


class InterfacesTest(unittest.TestCase):
    def setUp(self):
        self.doc = read_text(DOC)

    def test_every_behaviour_is_served(self):
        rows = table(section(self.doc, "## Interfaces"))
        self.assertEqual([row[0] for row in rows], ["API-%03d" % n for n in range(1, len(rows) + 1)])
        served = set()
        for row in rows:
            with self.subTest(interface=row[0]):
                listed = [item.strip() for item in row[3].split(",")]
                self.assertTrue(all(re.fullmatch(r"SPEC-0[0-3][0-9]", item) for item in listed), row[3])
                served |= set(listed)
                self.assertRegex(row[4], r"^(active|proposed|open \(D[1-4]\))$")
        self.assertEqual(served, {"SPEC-%03d" % n for n in range(1, 40)})

    def test_configuration_matches_the_document(self):
        schema = load_json(API / "memory-configuration.schema.json")
        rows = table(section(self.doc, "## Memory configuration"))
        for field, value, default, _ in rows:
            name = ticked(field)[0]
            if "." not in name:
                continue
            outer, inner = name.split(".")
            node = schema["properties"][outer]["properties"][inner]
            node = dict(schema["$defs"][node["$ref"][len("#/$defs/"):]], **node) if "$ref" in node else node
            with self.subTest(field=name):
                limits = re.match(r"^([\d,.]+) to ([\d,.]+)", value)
                if limits:
                    self.assertEqual((node["minimum"], node["maximum"]), (number(limits.group(1)), number(limits.group(2))))
                elif len(ticked(value)) > 1:
                    self.assertEqual(node["enum"], ticked(value))
                if re.fullmatch(r"[\d,.]+", default):
                    self.assertEqual(node["default"], number(default))
                elif re.fullmatch(r"`[^`]+`", default):
                    self.assertEqual(node["default"], ticked(default)[0])
                else:
                    self.assertNotIn("default", node)
        self.assertEqual(schema["properties"]["sync"]["properties"]["branch"]["default"], "main")

    def test_the_first_price_list_is_the_default(self):
        text = section(self.doc, "### The first price list")
        default = load_json(API / "memory-configuration.schema.json")["properties"]["prices"]["default"]
        self.assertEqual(default["taken"], re.search(r"Taken on (\d{4}-\d{2}-\d{2})", text).group(1))
        self.assertEqual(default["from"], re.findall(r"\]\((https://[^)]+)\)", text.split("\n\n")[1]))
        above = number(re.search(r"Prompts above ([\d,]+) tokens", text).group(1))
        models = {}
        for model, given, output, write, read, higher in table(text):
            prices = {"input": number(given), "output": number(output)}
            if write != "none":
                prices["cache_write"] = number(write)
            if read != "none":
                prices["cache_read"] = number(read)
            if higher != "none":
                found = dict(re.findall(r"(input|output) ([\d.]+)", higher))
                prices["above"] = {"tokens": above, "input": number(found["input"]), "output": number(found["output"])}
            models[ticked(model)[0]] = prices
        self.assertEqual(default["models"], models)

    def test_hooks_json_follows_the_events_table(self):
        config = json.loads(code_block(self.doc, "`hooks/hooks.json` of release 0.2.0:", "json"))
        rows = table(section(self.doc, "### Events and hooks.json"))
        self.assertEqual(set(config["hooks"]), {row[2] for row in rows})
        for _, claude, event, command, timeout, _ in rows:
            argument = ticked(command)[0].split(" ")[1]
            with self.subTest(event=event):
                (group,) = config["hooks"][event]
                (handler,) = group["hooks"]
                script = '"${CLAUDE_PLUGIN_ROOT}/scripts/hook.py" ' + argument
                self.assertEqual(handler["command"], " || ".join(python + " " + script for python in ("python3", "python", "py -3")))
                windows = '"$env:CLAUDE_PLUGIN_ROOT/scripts/hook.py" ' + argument
                self.assertEqual(handler["commandWindows"], "python %s; if ($LASTEXITCODE -ne 0) { py -3 %s }" % (windows, windows))
                self.assertEqual(handler["timeout"], int(timeout.split(" ")[0]))
                self.assertEqual(group.get("matcher", ""), "|".join(ticked(claude)))
        limits = {event: group[0]["hooks"][0].get("additionalContextLimit") for event, group in config["hooks"].items()}
        self.assertEqual(limits, {"SessionStart": 8000, "UserPromptSubmit": 2000, "Stop": None, "SessionEnd": None})


if __name__ == "__main__":
    unittest.main()
