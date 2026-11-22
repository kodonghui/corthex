"""Checks stage 09's default design base: the copied IBM Carbon tokens, the CORTHEX layer and tokens.py."""

import ast
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _common import PLUGINS, load_json, read_text

SKILL = PLUGINS / "corthex" / "skills" / "corthex-screen"
SCRIPT = SKILL / "scripts" / "tokens.py"
ASSETS = SKILL / "assets"
CARBON = ASSETS / "carbon"
LAYER = ASSETS / "corthex"
MOCKUP = SKILL / "references" / "09-mockup.md"
STICKIES = ("event", "command", "actor", "aggregate", "policy", "read-model", "external-system", "hotspot",
            "hotspot-answered")
STAGES = ("done", "in-progress", "not-started", "skipped")


def load():
    spec = importlib.util.spec_from_file_location("corthex_tokens", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tokens = load()


def run(*args):
    return subprocess.run([sys.executable, str(SCRIPT)] + [str(arg) for arg in args], capture_output=True,
                          timeout=120, env=dict(os.environ, PYTHONIOENCODING="utf-8"))


def luminance(hex_colour):
    channels = [int(hex_colour[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(one, two):
    high, low = sorted((luminance(one), luminance(two)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class Project(object):
    """A scratch project whose design folder tokens.py init filled."""

    def __init__(self, light=None, dark=None):
        self.light, self.dark = light, dark

    def __enter__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.design = Path(self.temp.name) / "design"
        self.assertEqual(tokens.init(self.design, self.light, self.dark, False, io.StringIO()), 0)
        self.resolver = self.design / "tokens.resolver.json"
        return self

    def assertEqual(self, one, two):
        if one != two:
            raise AssertionError("%r != %r" % (one, two))

    def __exit__(self, *exc):
        self.temp.cleanup()

    def values(self, mode):
        found = Tokens(tokens.load_resolver(self.resolver, {"theme": mode}))
        return found


class Tokens(tokens.Tokens):
    def css(self, dotted):
        path = tuple(dotted.split("."))
        kind, value = self.resolve(path)
        return dict(tokens.css_values("x", kind, value))["x"]


class ScriptShapeTest(unittest.TestCase):
    def test_parses_as_python_3_8(self):
        ast.parse(read_text(SCRIPT), feature_version=(3, 8))

    def test_imports_only_the_standard_library(self):
        allowed = {"argparse", "colorsys", "hashlib", "itertools", "json", "math", "os", "re", "sys", "pathlib"}
        for node in ast.walk(ast.parse(read_text(SCRIPT))):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module.split(".")[0]]
            else:
                continue
            for name in names:
                with self.subTest(module=name):
                    self.assertIn(name, allowed)

    def test_only_init_writes(self):
        source = read_text(SCRIPT)
        self.assertNotRegex(source, r"open\([^)]*['\"][wax]")
        self.assertEqual(source.count("write_bytes("), 1)
        self.assertEqual(source.count("mkdir("), 1)
        self.assertIn("writes only under DEST", source)

    def test_the_reference_documents_each_command_with_quoted_paths(self):
        text = read_text(MOCKUP)
        for command in ("init", "css", "check"):
            with self.subTest(command=command):
                self.assertIn("`python3 '<absolute skill directory>/scripts/tokens.py' %s -- '" % command, text)


class CopiedFilesTest(unittest.TestCase):
    def test_source_json_names_every_file_its_hash_and_the_license(self):
        manifest = load_json(CARBON / "source.json")
        listed = {}
        for package in manifest["packages"]:
            with self.subTest(package=package["name"]):
                self.assertTrue(package["name"].startswith("@carbon/"))
                self.assertRegex(package["version"], r"^\d+\.\d+\.\d+$")
                self.assertEqual(package["license"], "Apache-2.0")
                self.assertTrue(package["tarball"].startswith("https://registry.npmjs.org/@carbon/"))
                self.assertTrue(package["integrity"].startswith("sha512-"))
                self.assertRegex(package["gitHead"], r"^[0-9a-f]{40}$")
            listed.update(package["files"])
        on_disk = sorted(p.relative_to(CARBON).as_posix() for p in CARBON.rglob("*") if p.is_file())
        self.assertEqual(sorted(list(listed) + ["source.json"]), on_disk)
        for name, entry in listed.items():
            with self.subTest(file=name):
                data = (CARBON / name).read_bytes().replace(b"\r\n", b"\n")
                self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"])
        self.assertIn("Apache License", read_text(CARBON / "LICENSE"))
        self.assertIn("Copyright 2015 IBM Corp.", manifest["description"])

    def test_verify_passes_on_the_copy_and_finds_a_change(self):
        self.assertEqual(tokens.verify(CARBON, io.StringIO()), 0)
        with tempfile.TemporaryDirectory() as temp:
            copy = Path(temp) / "carbon"
            for path in CARBON.rglob("*"):
                if path.is_file():
                    target = copy / path.relative_to(CARBON)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(path.read_bytes())
            (copy / "layout.tokens.json").write_text("{}\n", encoding="utf-8")
            (copy / "extra.tokens.json").write_text("{}\n", encoding="utf-8")
            out = io.StringIO()
            self.assertEqual(tokens.verify(copy, out), 1)
            self.assertIn("changed: layout.tokens.json", out.getvalue())
            self.assertIn("not in source.json: extra.tokens.json", out.getvalue())

    def test_the_plugin_notice_names_carbon_and_where_it_is(self):
        notice = " ".join(read_text(PLUGINS / "corthex" / "NOTICE").split())
        self.assertIn("The corthex plugin of this product includes design tokens from the IBM Carbon", notice)
        self.assertIn("Copyright 2015 IBM Corp.", notice)
        self.assertIn("The other plugins do not include them.", notice)

    def test_the_corthex_layer_aliases_tokens_that_exist(self):
        with Project() as project:
            for mode in ("light", "dark"):
                found = project.values(mode)
                for path in found.names():
                    if path[0] == "corthex":
                        with self.subTest(mode=mode, token=".".join(path)):
                            found.resolve(path)
        for name in ("base", "light", "dark"):
            with self.subTest(file=name):
                data = load_json(LAYER / ("%s.tokens.json" % name))
                self.assertEqual(set(data) - {"$schema", "$description"}, {"corthex"})


class InitTest(unittest.TestCase):
    def test_init_copies_writes_and_runs_again_without_change(self):
        with tempfile.TemporaryDirectory() as temp:
            design = Path(temp) / "design"
            out = io.StringIO()
            self.assertEqual(tokens.init(design, None, None, False, out), 0)
            self.assertIn("light theme g10, dark theme g100", out.getvalue())
            resolver = load_json(design / "tokens.resolver.json")
            self.assertEqual(resolver, tokens.resolver_document("g10", "g100"))
            self.assertEqual([item["$ref"] for item in resolver["resolutionOrder"]],
                             ["#/sets/carbon", "#/sets/corthex", "#/modifiers/theme", "#/sets/base"])
            self.assertEqual(load_json(design / "base.tokens.json")["$schema"], tokens.FORMAT_SCHEMA)
            for source in ("carbon", "corthex"):
                for path in (ASSETS / source).rglob("*"):
                    if path.is_file():
                        with self.subTest(file=path.relative_to(ASSETS).as_posix()):
                            self.assertEqual((design / path.relative_to(ASSETS)).read_bytes(), path.read_bytes())
            (design / "base.tokens.json").write_text('{"mine": {}}\n', encoding="utf-8")
            again = io.StringIO()
            self.assertEqual(tokens.init(design, None, None, False, again), 0)
            self.assertNotIn("copied", again.getvalue())
            self.assertIn("same 32", again.getvalue())
            self.assertEqual(read_text(design / "base.tokens.json"), '{"mine": {}}\n')
            self.assertEqual(load_json(design / "tokens.resolver.json"), resolver)

    def test_a_theme_choice_is_kept_and_a_project_resolver_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            design = Path(temp) / "design"
            tokens.init(design, None, None, False, io.StringIO())
            out = io.StringIO()
            tokens.init(design, "white", None, False, out)
            self.assertIn("the light theme is now white and the dark theme g100", out.getvalue())
            self.assertEqual(load_json(design / "tokens.resolver.json"), tokens.resolver_document("white", "g100"))
            tokens.init(design, None, None, True, io.StringIO())
            self.assertEqual(load_json(design / "tokens.resolver.json"), tokens.resolver_document("white", "g100"))
            own = tokens.resolver_document("white", "g100")
            own["modifiers"]["theme"]["contexts"]["light"].append({"$ref": "theme/light.tokens.json"})
            (design / "tokens.resolver.json").write_text(json.dumps(own), encoding="utf-8")
            kept = io.StringIO()
            self.assertEqual(tokens.init(design, None, None, False, kept), 0)
            self.assertIn("kept %s: it is not the one init writes, so it was kept" % (design / "tokens.resolver.json"),
                          kept.getvalue())
            asked = io.StringIO()
            self.assertEqual(tokens.init(design, "g90", None, False, asked), 1)
            self.assertIn("not applied %s" % (design / "tokens.resolver.json"), asked.getvalue())
            self.assertIn("the themes asked for were not set", asked.getvalue())
            self.assertIn("Nothing written.", asked.getvalue())
            self.assertEqual(load_json(design / "tokens.resolver.json"), own)
            (design / "tokens.resolver.json").write_text('{"sets": {}}', encoding="utf-8")
            plain = io.StringIO()
            tokens.init(design, None, None, False, plain)
            self.assertIn("it lists no Carbon file", plain.getvalue())
            (design / "tokens.resolver.json").write_text("bad", encoding="utf-8")
            broken = io.StringIO()
            tokens.init(design, None, None, False, broken)
            self.assertIn("it cannot be read as JSON (", broken.getvalue())
            self.assertNotIn("lists no Carbon file", broken.getvalue())
            self.assertEqual(read_text(design / "tokens.resolver.json"), "bad")

    def test_init_names_copies_this_version_no_longer_has(self):
        with tempfile.TemporaryDirectory() as temp:
            design = Path(temp) / "design"
            tokens.init(design, None, None, False, io.StringIO())
            old = design / "carbon" / "themes" / "g10" / "old.tokens.json"
            old.write_text("{}\n", encoding="utf-8")
            out = io.StringIO()
            self.assertEqual(tokens.init(design, None, None, True, out), 0)
            self.assertIn("not in this version: %s" % old, out.getvalue())
            self.assertTrue(old.exists())

    def test_init_refuses_a_changed_copy_unless_asked_to_update(self):
        with tempfile.TemporaryDirectory() as temp:
            design = Path(temp) / "design"
            tokens.init(design, None, None, False, io.StringIO())
            changed = design / "corthex" / "light.tokens.json"
            changed.write_text("{}\n", encoding="utf-8")
            out = io.StringIO()
            self.assertEqual(tokens.init(design, None, None, False, out), 1)
            self.assertIn("Nothing written", out.getvalue())
            self.assertEqual(read_text(changed), "{}\n")
            self.assertEqual(tokens.init(design, None, None, True, io.StringIO()), 0)
            self.assertEqual(changed.read_bytes(), (LAYER / "light.tokens.json").read_bytes())

    def test_themes_that_cannot_be_applied_stop_init_before_it_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            design = Path(temp) / "design"
            design.mkdir()
            (design / "tokens.resolver.json").write_text('{"sets": {}}', encoding="utf-8")
            out = io.StringIO()
            self.assertEqual(tokens.init(design, None, "g90", False, out), 1)
            self.assertIn("Nothing written.", out.getvalue())
            self.assertEqual(sorted(path.name for path in design.iterdir()), ["tokens.resolver.json"])
            self.assertIn('"not applied"', tokens.resolver_plan.__doc__)

    def test_a_file_where_a_folder_goes_stops_init_before_it_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            design = Path(temp) / "design"
            design.mkdir()
            (design / "carbon").write_text("not a folder\n", encoding="utf-8")
            with self.assertRaisesRegex(tokens.TokenError, "carbon is not a folder, so nothing was written"):
                tokens.init(design, None, None, False, io.StringIO())
            self.assertEqual(sorted(path.name for path in design.iterdir()), ["carbon"])
            result = run("init", "--", design)
            self.assertEqual(result.returncode, 2)
            self.assertIn(b"is not a folder", result.stderr)
            self.assertNotIn(b"Traceback", result.stderr)

    def test_the_command_line_rejects_an_unknown_theme(self):
        with tempfile.TemporaryDirectory() as temp:
            result = run("init", "--light", "g50", "--", Path(temp) / "design")
            self.assertEqual(result.returncode, 2)
            self.assertFalse((Path(temp) / "design").exists())


class ResolveTest(unittest.TestCase):
    def test_known_values_in_each_mode(self):
        expected = {
            "light": {"background": "#f4f4f4", "layer-01": "#ffffff", "corthex.sticky.event": "#ffd9be",
                      "corthex.ai.text": "#0043ce"},
            "dark": {"background": "#161616", "layer-01": "#262626", "corthex.sticky.event": "#5e2900",
                     "corthex.ai.text": "#a6c8ff"},
        }
        with Project() as project:
            for mode, values in expected.items():
                found = project.values(mode)
                for name, value in values.items():
                    with self.subTest(mode=mode, token=name):
                        self.assertEqual(found.css(name), value)
                with self.subTest(mode=mode, token="radius"):
                    self.assertEqual(found.css("corthex.radius.box"), "0.5rem")
                    self.assertEqual(found.css("corthex.radius.panel"), "1rem")
                    self.assertEqual(found.css("corthex.radius.pill"), "999999px")

    def test_css_names_values_and_a_project_override(self):
        with Project() as project:
            text = tokens.css_text(project.resolver, {"theme": "dark"})
            self.assertIn("  --background: #161616;\n", text)
            self.assertIn("  --spacing-05: 1rem;\n", text)
            self.assertIn("  --gray-10: #f4f4f4;\n", text)
            self.assertIn("  --border-radius-08: 0.5rem;\n", text)
            self.assertIn('  --corthex-type-body-01: 400 0.875rem/1.42857 "IBM Plex Sans KR", system-ui', text)
            self.assertIn("  --corthex-type-body-01-letter-spacing: 0.16px;\n", text)
            self.assertIn("rgba(141, 141, 141, 0.4)", text)
            self.assertNotIn("Not written", text)
            (project.design / "base.tokens.json").write_text(json.dumps({"corthex": {"radius": {"box": {
                "$type": "dimension", "$value": {"value": 4, "unit": "px"}}}}}), encoding="utf-8")
            for prefix in ("cds-", "cds"):
                prefixed = tokens.css_text(project.resolver, {}, prefix=prefix, only=["corthex-radius"])
                with self.subTest(prefix=prefix):
                    self.assertIn("  --cds-corthex-radius-box: 4px;\n", prefixed)
                    self.assertIn("  --cds-corthex-radius-panel: 1rem;\n", prefixed)
                    self.assertNotIn("--cds-background", prefixed)

    def test_a_later_layer_wins_a_shared_css_name(self):
        with Project() as project:
            (project.design / "base.tokens.json").write_text(json.dumps({"text": {"$type": "color", "primary": {
                "$value": {"colorSpace": "srgb", "components": [0.0, 0.0, 0.0]}}}}), encoding="utf-8")
            text = tokens.css_text(project.resolver, {}, only=["text-primary"])
            self.assertIn("  --text-primary: #000000;\n", text)
            self.assertEqual(text.count("--text-primary:"), 1)
            self.assertIn("the later file's token written: text-primary by text.primary", text)
        with Project() as project:
            own = load_json(project.resolver)
            own["modifiers"]["theme"]["contexts"]["light"].append({"$ref": "light.tokens.json"})
            project.resolver.write_text(json.dumps(own), encoding="utf-8")
            (project.design / "light.tokens.json").write_text(json.dumps({"text": {"$type": "color", "primary": {
                "$value": {"colorSpace": "srgb", "components": [1.0, 0.0, 0.0]}}}}), encoding="utf-8")
            light = tokens.css_text(project.resolver, {}, only=["text-primary"])
            self.assertIn("  --text-primary: #ff0000;\n", light)
            self.assertIn("text-primary by text.primary", light)
            self.assertIn("  --text-primary: #f4f4f4;\n", tokens.css_text(project.resolver, {"theme": "dark"},
                                                                          only=["text-primary"]))
        same = tokens.Tokens({"a": {"b": {"$type": "number", "$value": 1}}, "a-b": {"$type": "number", "$value": 2}})
        with tempfile.TemporaryDirectory() as temp:
            resolver = Path(temp) / "r.json"
            (Path(temp) / "t.json").write_text(json.dumps(same.tree), encoding="utf-8")
            resolver.write_text(json.dumps({"sets": {"t": {"sources": [{"$ref": "t.json"}]}},
                                            "resolutionOrder": [{"$ref": "#/sets/t"}]}), encoding="utf-8")
            with self.assertRaisesRegex(tokens.TokenError, "two tokens of one file give the CSS name --a-b"):
                tokens.css_text(resolver, {})

    def test_a_byte_order_mark_is_read(self):
        with Project() as project:
            (project.design / "base.tokens.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({"brand": {
                "$type": "color", "$value": {"colorSpace": "srgb", "components": [1.0, 0.0, 0.0]}}}).encode("utf-8"))
            self.assertIn("  --brand: #ff0000;\n", tokens.css_text(project.resolver, {}, only=["brand"]))
            project.resolver.write_bytes(b"\xef\xbb\xbf" + project.resolver.read_bytes())
            out = io.StringIO()
            self.assertEqual(tokens.init(project.design, None, None, False, out), 0)
            self.assertIn("same 32", out.getvalue())

    def test_the_documented_dark_mode_command_runs(self):
        text = read_text(MOCKUP)
        self.assertIn("tokens.py' css --input theme=dark -- '<project>/design/tokens.resolver.json'`", text)
        with Project() as project:
            result = run("css", "--input", "theme=dark", "--only", "background", "--", project.resolver)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(b"--background: #161616;", result.stdout)

    def test_the_resolver_and_aliases_fail_clearly(self):
        loop = tokens.Tokens({"a": {"$type": "color", "$value": "{b}"}, "b": {"$type": "color", "$value": "{a}"}})
        with self.assertRaisesRegex(tokens.TokenError, "alias loop"):
            loop.resolve(("a",))
        with self.assertRaisesRegex(tokens.TokenError, "no token"):
            tokens.Tokens({"a": {"$value": "{missing}"}}).resolve(("a",))
        with Project() as project:
            with self.assertRaisesRegex(tokens.TokenError, "no context"):
                tokens.load_resolver(project.resolver, {"theme": "sepia"})
            result = run("css", "--input", "mood=calm", "--", project.resolver)
            self.assertEqual(result.returncode, 2)
            self.assertIn(b"no modifier", result.stderr)


class ReadabilityTest(unittest.TestCase):
    """Every theme init can choose, in either mode, keeps the CORTHEX layer readable."""

    def each_theme(self):
        for theme in tokens.THEMES:
            with Project(theme, theme) as project:
                for mode in ("light", "dark"):
                    yield theme, mode, project.values(mode)

    def test_sticky_text_is_readable_on_every_sticky(self):
        for theme, mode, found in self.each_theme():
            text = found.css("corthex.sticky.text")
            for name in STICKIES:
                with self.subTest(theme=theme, mode=mode, sticky=name):
                    self.assertGreaterEqual(contrast(text, found.css("corthex.sticky." + name)), 4.5)

    def test_stage_marks_stand_out_from_the_background(self):
        for theme, mode, found in self.each_theme():
            for name in STAGES:
                with self.subTest(theme=theme, mode=mode, stage=name):
                    self.assertGreaterEqual(contrast(found.css("corthex.stage." + name), found.css("background")), 3)

    def test_ai_text_is_readable_on_the_layers(self):
        for theme, mode, found in self.each_theme():
            for layer in ("background", "layer-01"):
                with self.subTest(theme=theme, mode=mode, layer=layer):
                    self.assertGreaterEqual(contrast(found.css("corthex.ai.text"), found.css(layer)), 4.5)


def modes_resolver(folder, defaults=True):
    """Two modifiers whose colour #222222 shows only in the dark and high-contrast combination."""
    def colour(value):
        return {"$type": "color", "$value": {"colorSpace": "srgb", "components": [c / 255.0 for c in value]}}
    files = {"base.json": {"y": colour((0, 0, 0))}, "light.json": {"x": colour((255, 255, 255))},
             "dark.json": {"x": colour((34, 34, 34))}, "normal.json": {"x": {"$type": "color", "$value": "{y}"}},
             "high.json": {}}
    for name, tree in files.items():
        (folder / name).write_text(json.dumps(tree), encoding="utf-8")
    theme = {"contexts": {"light": [{"$ref": "light.json"}], "dark": [{"$ref": "dark.json"}]}}
    contrast = {"contexts": {"normal": [{"$ref": "normal.json"}], "high": [{"$ref": "high.json"}]}}
    if defaults:
        theme["default"], contrast["default"] = "light", "normal"
    resolver = folder / "r.json"
    resolver.write_text(json.dumps({"sets": {"base": {"sources": [{"$ref": "base.json"}]}},
                                    "modifiers": {"theme": theme, "contrast": contrast},
                                    "resolutionOrder": [{"$ref": "#/sets/base"}, {"$ref": "#/modifiers/theme"},
                                                        {"$ref": "#/modifiers/contrast"}]}), encoding="utf-8")
    return resolver


class ModifierTest(unittest.TestCase):
    def test_check_reads_every_combination_of_modifiers(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = modes_resolver(Path(temp))
            self.assertEqual(len(tokens.mode_inputs(resolver)), 4)
            page = Path(temp) / "page.css"
            page.write_text(".a { color: #222222; }\n", encoding="utf-8")
            out = io.StringIO()
            self.assertEqual(tokens.check(resolver, [page], out), 0, out.getvalue())

    def test_an_undefined_modifier_fails_clearly(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = Path(temp) / "r.json"
            resolver.write_text(json.dumps({"sets": {"a": {"sources": []}},
                                            "resolutionOrder": [{"$ref": "#/sets/a"}, {"$ref": "#/modifiers/theme"}]}),
                                encoding="utf-8")
            page = Path(temp) / "page.css"
            page.write_text(".a { color: #ffffff; }\n", encoding="utf-8")
            result = run("check", "--", resolver, page)
            self.assertEqual(result.returncode, 2)
            self.assertIn(b"names the modifier 'theme', which the resolver does not define", result.stderr)
            self.assertNotIn(b"Traceback", result.stderr)

    def test_a_modifier_without_a_default(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = modes_resolver(Path(temp), defaults=False)
            with self.assertRaisesRegex(tokens.TokenError, "modifier 'theme' has no default; choose a context with "
                                                           "--input theme=CONTEXT"):
                tokens.css_text(resolver, {})
            self.assertIn("--x: #222222;", tokens.css_text(resolver, {"theme": "dark", "contrast": "high"}))
            page = Path(temp) / "page.css"
            page.write_text(".a { color: #ffffff; }\n", encoding="utf-8")
            self.assertEqual(tokens.check(resolver, [page], io.StringIO()), 0)


class CheckTest(unittest.TestCase):
    def check(self, files):
        with Project() as project:
            folder = project.design.parent / "src"
            folder.mkdir()
            for name, text in files.items():
                (folder / name).write_text(text, encoding="utf-8")
            out = io.StringIO()
            code = tokens.check(project.resolver, [folder], out)
            return code, out.getvalue()

    def test_token_colours_pass_in_every_form(self):
        code, out = self.check({"a.css": ".a { color: #f4f4f4; background: #161616; border: 1px solid #FFF; }\n"
                                         ".b { color: rgb(15 98 254); fill: rgba(141, 141, 141, 0.5); }\n"
                                         ".c { color: hsl(0 0% 100%); outline-color: #8d8d8d80; background: white; }\n"})
        self.assertEqual(code, 0, out)
        self.assertIn("8 colour literals, 0 off the tokens", out)

    def test_names_and_functions_it_cannot_compare_are_found(self):
        code, out = self.check({"a.css": ".a { color: tomato; background: oklch(70% 0.1 200); }\n",
                                "b.svg": '<rect fill="red" stroke="var(--red)"/>\n',
                                "c.js": "const s = { backgroundColor: 'gold', color: theme.red }; d3.lab(1, 2, 3);\n"})
        self.assertEqual(code, 1)
        self.assertIn("a.css:1:13: tomato is not a token colour; nearest", out)
        self.assertIn("a.css:1:33: oklch(70% 0.1 200) is a colour function this check cannot compare", out)
        self.assertIn("b.svg:1:13: red is not a token colour", out)
        self.assertIn("c.js:1:31: gold is not a token colour", out)
        self.assertIn("4 colour literals, 4 off the tokens", out)

    def test_comments_nesting_and_at_rules_in_scss(self):
        code, out = self.check({"a.scss": ".logo {\n  color: #ab1234; /* off-token: a partner's logo */\n"
                                          "  &:hover { color: #0f62fe; }\n}\n"
                                          ".b { color: #ab1235; } /* off-token: a partner's logo */\n.c { x: 1; }\n"
                                          "@include frame($c: #ab1236) { a: b; }\n"})
        self.assertEqual(code, 1)
        self.assertIn("a.scss:7:20: #ab1236 is not a token colour", out)
        self.assertIn("4 colour literals, 1 off the tokens, 2 kept with an off-token reason", out)

    def test_comments_page_text_and_comparisons_are_not_colours(self):
        code, out = self.check({
            "a.css": "/* Workaround for issue #123, see PR #4567 */\n.a { color: #f4f4f4; }\n",
            "b.html": '<p style="color: var(--text-primary)">Red alert</p>\n<p>Fixed in #789 and #2024</p>'
                      "<!-- #abc -->\n<script>const c = a > b ? '#ab1234' : x;</script>\n",
            "c.js": 'const s = { color: "var(--x)", label: "Green team" }; // see #123\n'
                    'if (status.color === "orange") warn();\n',
        })
        self.assertEqual(code, 1)
        self.assertIn("b.html:3:28: #ab1234 is not a token colour", out)
        self.assertIn("2 colour literals, 1 off the tokens", out)

    def test_custom_properties_gradients_and_later_declarations(self):
        code, out = self.check({
            "a.css": ":root { --brand: tomato; }\n.a { background-image: linear-gradient(gold, white); }\n",
            "b.js": 'const q = { color: x, background: "red" };\n',
        })
        self.assertEqual(code, 1)
        self.assertIn("a.css:1:18: tomato is not a token colour", out)
        self.assertIn("a.css:2:40: gold is not a token colour", out)
        self.assertIn("b.js:1:36: red is not a token colour", out)
        self.assertIn("4 colour literals, 3 off the tokens", out)

    def test_indented_sass_selectors_and_interpolation(self):
        code, out = self.check({"a.sass": "#fade\n  color: #f4f4f4\n  &:hover, #bad\n    color: #ab1234\n"
                                          "  width: calc(1px + #{$x})\n",
                                "b.scss": ".a { color: mix(#ab1235, #{$c}); }\n"})
        self.assertEqual(code, 1)
        self.assertNotIn("#fade", out)
        self.assertNotIn("#bad", out)
        self.assertIn("a.sass:4:12: #ab1234 is not a token colour", out)
        self.assertIn("b.scss:1:17: #ab1235 is not a token colour", out)
        self.assertIn("3 colour literals, 2 off the tokens", out)

    def test_markup_style_blocks_and_other_hue_units(self):
        code, out = self.check({"b.html": "<style>#bad { color: #0f62fe; } #ace{}</style>\n"
                                          '<p style="color: hsl(0.5turn 50% 50%); fill: hsl(none 0% 100%)">x</p>\n'})
        self.assertEqual(code, 1)
        self.assertNotIn("#bad", out)
        self.assertNotIn("#ace", out)
        self.assertIn("hsl(0.5turn 50% 50%) is not a token colour", out)
        self.assertIn("3 colour literals, 1 off the tokens", out)
        self.assertEqual(tokens.parse_colour("hsl(3.14159265rad 50% 50%)"), tokens.parse_colour("hsl(180deg 50% 50%)"))
        self.assertEqual(tokens.parse_colour("hsl(200grad 50% 50%)"), tokens.parse_colour("hsl(180 50% 50%)"))

    def test_a_numeric_colour_it_cannot_read_is_reported(self):
        code, out = self.check({"a.css": ".a { color: rgb(1 2 3 4 5); }\n"})
        self.assertEqual(code, 1)
        self.assertIn("rgb(1 2 3 4 5) is a colour this check cannot read", out)

    def test_a_file_it_cannot_read_fails_the_check(self):
        with Project() as project:
            source = project.design.parent / "k.css"
            source.write_bytes(".a { color: #ab1234; } /* \xc7\xd1\xb1\xdb */\n".encode("latin-1"))
            out = io.StringIO()
            self.assertEqual(tokens.check(project.resolver, [source], out), 1)
            self.assertIn("not read, so not checked", out.getvalue())
            self.assertIn("0 colour literals, 0 off the tokens, 0 kept with an off-token reason, 1 files not read",
                          out.getvalue())

    def test_selectors_variables_and_unparsed_values_are_not_colours(self):
        code, out = self.check({
            "a.css": "#add, #bad:hover,\n#cafe > a { border: 1px solid #f4f4f4; background: url(red.png); fill: var(--red); }\n",
            "b.scss": ".a { color: $green; stroke: rgba($r, $g, $b, $a); }\n",
            "c.js": "const c = `rgba(${r}, ${g}, ${b}, ${a})`; const d = 'rgb(0 0 0 / x)';\n",
        })
        self.assertEqual(code, 0, out)
        self.assertIn("1 colour literals, 0 off the tokens", out)

    def test_an_off_token_colour_is_found_with_its_place_and_nearest_token(self):
        code, out = self.check({"a.css": ".a { color: #f4f4f4; }\n.b { color: #123456; }\n"})
        self.assertEqual(code, 1)
        self.assertRegex(out, r"a\.css:2:13: #123456 is not a token colour; nearest \S+ \(\S+\) is #[0-9a-f]{6}")

    def test_a_reason_keeps_a_colour_and_links_are_not_colours(self):
        code, out = self.check({
            "a.css": ".a { color: #abcdef; } /* off-token: a partner's logo colour */\n",
            "b.html": '<a href="#add">x</a><svg><path fill="url(#bad)"/></svg>\n',
            "c.js": "class A { #fade() {} run() { this.#fade(); } }\n",
            "d.txt": "#123456\n",
        })
        self.assertEqual(code, 0, out)
        self.assertIn("1 colour literals, 0 off the tokens, 1 kept with an off-token reason", out)

    def test_the_command_line_exit_codes(self):
        with Project() as project:
            source = project.design.parent / "page.css"
            source.write_text(".a { color: #f4f4f4; }\n", encoding="utf-8")
            self.assertEqual(run("check", "--", project.resolver, source).returncode, 0)
            source.write_text(".a { color: #010203; }\n", encoding="utf-8")
            self.assertEqual(run("check", "--", project.resolver, source).returncode, 1)
            self.assertEqual(run("check", "--", project.resolver, project.design / "missing").returncode, 2)


class StageReferenceTest(unittest.TestCase):
    def test_the_reference_names_the_default_base_and_its_layers(self):
        text = read_text(MOCKUP)
        inputs = next(line for line in text.splitlines() if line.startswith("| Inputs |"))
        self.assertIn("IBM Carbon", inputs)
        section = text[text.index("## Default base"):]
        section = section[:section.index("\n## ", 3)]
        for name in ("`carbon/`", "`corthex/`", "`base.tokens.json`", "Apache-2.0", "`corthex.radius.box`",
                     "`corthex.radius.panel`", "`corthex.radius.pill`", "IBM Plex Sans KR", "`--update`"):
            with self.subTest(name=name):
                self.assertIn(name, section)
        for theme in tokens.THEMES:
            with self.subTest(theme=theme):
                self.assertIn("`%s`" % theme, section)
        checks = text[text.index("## Checks"):]
        self.assertIn("off-token:", checks[:checks.index("\n## ", 3)])

    def test_the_layer_stickies_are_the_discovery_legend(self):
        board = read_text(PLUGINS / "corthex" / "skills" / "corthex-discover" / "references" / "event-storming-board.md")
        legend = board[board.index("## Legend"):board.index("## Layout")]
        elements = sorted(set(re.findall(r"^\| ([A-Z][a-z]+(?: [a-z]+)?) \|", legend, re.M)) - {"Element"})
        names = {"event": "Domain event", "hotspot-answered": "Answered hotspot"}
        self.assertEqual(sorted(names.get(key, key.replace("-", " ").capitalize()) for key in STICKIES), elements)
        for mode in ("light", "dark"):
            sticky = load_json(LAYER / ("%s.tokens.json" % mode))["corthex"]["sticky"]
            with self.subTest(mode=mode):
                self.assertEqual(sorted(k for k in sticky if not k.startswith("$")), sorted(STICKIES))


if __name__ == "__main__":
    unittest.main()
