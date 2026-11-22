#!/usr/bin/env python3
"""Design tokens for stage 09: start a project from the default base, write CSS and find off-token colours.

    tokens.py init DEST [--light THEME] [--dark THEME] [--update]
    tokens.py css RESOLVER [--input NAME=CONTEXT ...] [--prefix TEXT] [--selector TEXT] [--only PREFIXES]
    tokens.py check RESOLVER PATH [PATH ...]
    tokens.py verify [DIR]

`init` copies IBM Carbon's token files and the CORTHEX layer into DEST, by default a project's `design`
folder, and writes a resolver document and an empty `base.tokens.json` beside them when they are missing.
`css` resolves the tokens of one mode and prints them as CSS custom properties. `check` lists the colour
literals in source files that no token of any mode has. `verify` compares a copy of the Carbon files with
`source.json`. The script uses the Python standard library only, reads no network and writes only under DEST.
"""

import argparse
import colorsys
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
THEMES = ("white", "g10", "g90", "g100")
THEME_FILES = ("theme", "button", "tag", "notification", "status", "content-switcher")
FORMAT_SCHEMA = "https://www.designtokens.org/schemas/2025.10/format.json"
RESOLVER_SCHEMA = "https://www.designtokens.org/schemas/2025.10/resolver.json"
SOURCE_EXTENSIONS = (".css", ".scss", ".sass", ".less", ".html", ".htm", ".svg", ".js", ".jsx", ".mjs",
                     ".ts", ".tsx", ".vue", ".svelte")
SKIP_DIRS = {".git", "node_modules", "__pycache__"}
GENERIC_FONTS = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif",
                 "ui-sans-serif", "ui-monospace", "ui-rounded", "math", "emoji", "fangsong"}
CSS_SPACES = {"srgb-linear", "display-p3", "a98-rgb", "prophoto-rgb", "rec2020", "xyz-d50", "xyz-d65"}
ALIAS = re.compile(r"^\{([^{}]+)\}$")
IDENT = re.compile(r"^-?[A-Za-z_][A-Za-z0-9_-]*$")
KEEP = re.compile(r"off-token:\s*\S")


class TokenError(Exception):
    pass


# --- reading token files and resolvers -------------------------------------------------------------

def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as error:
        raise TokenError("cannot read %s: %s" % (path, error))


def merge(into, tree):
    """Merge a token tree into another: a token replaces what was there, groups merge."""
    for key, value in tree.items():
        if isinstance(value, dict) and "$value" not in value and isinstance(into.get(key), dict) \
                and "$value" not in into[key]:
            merge(into[key], value)
        else:
            into[key] = json.loads(json.dumps(value))
    return into


def load_sources(sources, base):
    tree = {}
    for source in sources:
        if isinstance(source, dict) and set(source) == {"$ref"}:
            ref = source["$ref"]
            if "#" in ref:
                raise TokenError("a source reference with a fragment is not supported: %s" % ref)
            merge(tree, read_json(base / ref))
        elif isinstance(source, dict):
            merge(tree, source)
        else:
            raise TokenError("a source must be an object")
    return tree


def load_resolver(path, inputs=None):
    """Merge the token trees a resolver document lists, for the given modifier inputs."""
    path = Path(path)
    doc = read_json(path)
    base = path.parent
    inputs = dict(inputs or {})
    modifiers = doc.get("modifiers", {})
    for name in inputs:
        if name not in modifiers:
            raise TokenError("the resolver has no modifier %r" % name)
    tree = {}
    for entry in doc.get("resolutionOrder", []):
        ref = entry.get("$ref", "") if isinstance(entry, dict) else ""
        if ref.startswith("#/sets/") and ref[len("#/sets/"):] in doc.get("sets", {}):
            merge(tree, load_sources(doc["sets"][ref[len("#/sets/"):]].get("sources", []), base))
        elif ref.startswith("#/modifiers/") and ref[len("#/modifiers/"):] in modifiers:
            name = ref[len("#/modifiers/"):]
            modifier = modifiers[name]
            context = inputs.get(name, modifier.get("default"))
            if context not in modifier.get("contexts", {}):
                raise TokenError("modifier %r has no context %r" % (name, context))
            merge(tree, load_sources(modifier["contexts"][context], base))
        else:
            raise TokenError("resolutionOrder entry not understood: %s" % json.dumps(entry))
    return tree


def mode_inputs(path):
    """Every input worth checking: each context of each modifier, the others at their default."""
    doc = read_json(Path(path))
    found = [{}]
    for name, modifier in doc.get("modifiers", {}).items():
        for context in modifier.get("contexts", {}):
            if context != modifier.get("default"):
                found.append({name: context})
    return found


class Tokens(object):
    def __init__(self, tree):
        self.tree = tree
        self.found = {}
        self.walk(tree, (), None)
        self.cache = {}

    def walk(self, node, path, inherited):
        kind = node.get("$type", inherited)
        if "$value" in node:
            self.found[path] = (node, kind)
            return
        for key, child in node.items():
            if not key.startswith("$") and isinstance(child, dict):
                self.walk(child, path + (key,), kind)

    def names(self):
        return sorted(self.found)

    def resolve(self, path, stack=()):
        """Return (type, value) of the token at path, with every alias and reference replaced."""
        if path in self.cache:
            return self.cache[path]
        if path not in self.found:
            raise TokenError("no token %s" % ".".join(path))
        if path in stack:
            raise TokenError("alias loop: %s" % " -> ".join(".".join(p) for p in stack + (path,)))
        node, kind = self.found[path]
        stack = stack + (path,)
        value = node["$value"]
        match = ALIAS.match(value) if isinstance(value, str) else None
        if match:
            target = tuple(match.group(1).split("."))
            kind_there, value = self.resolve(target, stack)
            kind = kind or kind_there
        else:
            value = self.expand(value, stack)
        self.cache[path] = (kind, value)
        return kind, value

    def expand(self, value, stack):
        if isinstance(value, dict) and set(value) == {"$ref"}:
            return self.expand(self.pointer(value["$ref"], stack), stack)
        if isinstance(value, dict):
            return {key: self.expand(item, stack) for key, item in value.items()}
        if isinstance(value, list):
            return [self.expand(item, stack) for item in value]
        if isinstance(value, str):
            match = ALIAS.match(value)
            if match:
                return self.resolve(tuple(match.group(1).split(".")), stack)[1]
        return value

    def pointer(self, ref, stack):
        if not ref.startswith("#/"):
            raise TokenError("only references inside the token set are supported: %s" % ref)
        node = self.tree
        path = ()
        parts = [part.replace("~1", "/").replace("~0", "~") for part in ref[2:].split("/")]
        for index, part in enumerate(parts):
            if part == "$value" and isinstance(node, dict) and path in self.found:
                node = self.resolve(path, stack)[1]
                continue
            if isinstance(node, dict) and part in node:
                node = node[part]
            elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
                node = node[int(part)]
            else:
                raise TokenError("reference not found: %s" % ref)
            if index == len(path):
                path = path + (part,)
        return node


# --- CSS values --------------------------------------------------------------------------------------

def number(value):
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, float):
        return ("%.6f" % value).rstrip("0").rstrip(".")
    return str(value)


def srgb(value):
    """(r, g, b, alpha) with 0-255 channels for an sRGB colour value, else None."""
    if isinstance(value, str):
        return parse_colour(value)
    if not isinstance(value, dict) or value.get("colorSpace") != "srgb":
        return None
    alpha = value.get("alpha", 1)
    alpha = 1 if alpha == "none" else alpha
    if isinstance(value.get("hex"), str) and alpha == 1:
        return parse_colour(value["hex"])
    channels = [0 if c == "none" else c for c in value.get("components", [])]
    if len(channels) != 3:
        return None
    return tuple(int(round(max(0.0, min(1.0, c)) * 255)) for c in channels) + (round(float(alpha), 4),)


def colour_css(value):
    rgba = srgb(value)
    if rgba:
        if rgba[3] >= 1:
            return "#%02x%02x%02x" % rgba[:3]
        return "rgba(%d, %d, %d, %s)" % (rgba[0], rgba[1], rgba[2], number(rgba[3]))
    if isinstance(value, dict):
        space = value.get("colorSpace")
        parts = " ".join(number(c) if c != "none" else "none" for c in value.get("components", []))
        alpha = value.get("alpha", 1)
        tail = "" if alpha in (1, "none") else " / %s" % number(alpha)
        if space in CSS_SPACES:
            return "color(%s %s%s)" % (space, parts, tail)
        if space in ("hsl", "hwb", "lab", "lch", "oklab", "oklch"):
            return "%s(%s%s)" % (space, parts, tail)
    return None


def dimension(value):
    if isinstance(value, dict) and "value" in value and "unit" in value:
        return number(value["value"]) + value["unit"]
    return str(value)


def family(value):
    names = value if isinstance(value, list) else [value]
    out = []
    for name in names:
        plain = IDENT.match(name) and name.lower() not in ("inherit", "initial", "unset", "default")
        out.append(name if plain or name.lower() in GENERIC_FONTS else '"%s"' % name.replace('"', '\\"'))
    return ", ".join(out)


def shadow(value):
    items = value if isinstance(value, list) else [value]
    out = []
    for item in items:
        text = " ".join(dimension(item.get(key, {"value": 0, "unit": "px"})) for key in ("offsetX", "offsetY", "blur", "spread"))
        out.append(("inset " if item.get("inset") else "") + text + " " + (colour_css(item.get("color")) or ""))
    return ", ".join(part.strip() for part in out)


def css_values(name, kind, value):
    """CSS custom properties for one resolved token, as (name, value) pairs; empty when it has no CSS form."""
    if kind == "color":
        text = colour_css(value)
        return [(name, text)] if text else []
    if kind in ("dimension", "duration"):
        return [(name, dimension(value))]
    if kind in ("number", "fontWeight"):
        return [(name, number(value) if not isinstance(value, str) else value)]
    if kind == "fontFamily":
        return [(name, family(value))]
    if kind == "cubicBezier" and isinstance(value, list):
        return [(name, "cubic-bezier(%s)" % ", ".join(number(v) for v in value))]
    if kind == "shadow":
        return [(name, shadow(value))]
    if kind == "typography" and isinstance(value, dict):
        weight = value.get("fontWeight", 400)
        height = value.get("lineHeight", 1)
        font = "%s %s/%s %s" % (weight if isinstance(weight, str) else number(weight), dimension(value.get("fontSize")),
                                dimension(height) if isinstance(height, dict) else number(height),
                                family(value.get("fontFamily", "sans-serif")))
        pairs = [(name, font)]
        if "letterSpacing" in value:
            pairs.append((name + "-letter-spacing", dimension(value["letterSpacing"])))
        return pairs
    return []


def css_name(path, prefix):
    parts = [path[0]]
    for part in path[1:]:
        if part.startswith(parts[-1] + "-"):
            parts[-1] = part
        else:
            parts.append(part)
    return "--" + prefix + "-".join(parts)


def css_text(resolver, inputs, prefix="", selector=":root", only=None):
    tokens = Tokens(load_resolver(resolver, inputs))
    lines, seen, skipped = [], {}, []
    for path in tokens.names():
        kind, value = tokens.resolve(path)
        name = css_name(path, prefix)
        if only and not any(name[2 + len(prefix):].startswith(item) for item in only):
            continue
        pairs = css_values(name, kind, value)
        if not pairs:
            skipped.append(".".join(path))
        for key, text in pairs:
            if key in seen:
                raise TokenError("two tokens give the CSS name %s: %s and %s" % (key, seen[key], ".".join(path)))
            seen[key] = ".".join(path)
            lines.append("  %s: %s;" % (key, text))
    mode = ", ".join("%s=%s" % item for item in sorted(inputs.items())) or "defaults"
    head = "/* Written by tokens.py css from %s (%s). Change the token files, not this text. */" % (Path(resolver).name, mode)
    out = [head, selector + " {"] + lines + ["}"]
    if skipped:
        out.append("/* Not written, no CSS form: %s */" % ", ".join(skipped))
    return "\n".join(out) + "\n"


# --- off-token colours ------------------------------------------------------------------------------

HEX = re.compile(r"(?<![\w&#/.])#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![\w(-])")
FUNC = re.compile(r"\b(rgba?|hsla?)\(\s*([^()]*?)\s*\)", re.I)
URL = re.compile(r"url\(\s*['\"]?#[^)]*\)", re.I)
LINK_ATTR = re.compile(r"""\b(?:href|xlink:href|src|action|id|for|name)\s*=\s*("[^"]*"|'[^']*')""", re.I)


def channel(text, scale):
    text = text.strip()
    if text.endswith("%"):
        return float(text[:-1]) * scale / 100.0
    return float(text)


def parse_colour(text):
    """(r, g, b, alpha) for a hex, rgb(), rgba(), hsl() or hsla() literal, else None."""
    text = text.strip()
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) in (3, 4):
            digits = "".join(c * 2 for c in digits)
        if len(digits) not in (6, 8) or not re.match(r"^[0-9a-fA-F]+$", digits):
            return None
        alpha = int(digits[6:8], 16) / 255.0 if len(digits) == 8 else 1.0
        return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16), round(alpha, 4))
    match = FUNC.match(text)
    if not match:
        return None
    kind = match.group(1).lower()
    body = match.group(2).replace("/", " / ")
    parts = [p for p in re.split(r"[\s,]+", body) if p]
    alpha = 1.0
    if "/" in parts:
        index = parts.index("/")
        parts, alpha_parts = parts[:index], parts[index + 1:]
        if len(alpha_parts) != 1:
            return None
        alpha = channel(alpha_parts[0], 1)
    elif len(parts) == 4:
        alpha = channel(parts[3], 1)
        parts = parts[:3]
    if len(parts) != 3:
        return None
    try:
        if kind.startswith("rgb"):
            rgb = [channel(p, 255) for p in parts]
        else:
            hue = float(parts[0][:-3] if parts[0].endswith("deg") else parts[0]) / 360.0
            light, saturation = (float(part.rstrip("%")) / 100.0 for part in (parts[2], parts[1]))
            rgb = [c * 255 for c in colorsys.hls_to_rgb(hue % 1.0, light, saturation)]
        alpha = float(alpha)
    except ValueError:
        return None
    return tuple(int(round(max(0, min(255, c)))) for c in rgb) + (round(max(0.0, min(1.0, alpha)), 4),)


def token_colours(resolver):
    """Every sRGB colour any mode of the tokens gives, with one token name for each."""
    colours = {}
    for inputs in mode_inputs(resolver):
        tokens = Tokens(load_resolver(resolver, inputs))
        mode = ", ".join("%s=%s" % item for item in sorted(inputs.items())) or "default"
        for path in tokens.names():
            kind, value = tokens.resolve(path)
            if kind == "color":
                rgba = srgb(value)
                if rgba:
                    colours.setdefault(rgba, "%s (%s)" % (".".join(path), mode))
    return colours


def same(one, two):
    return one[:3] == two[:3] and abs(one[3] - two[3]) <= 0.005


def nearest(rgba, colours):
    best = min(colours, key=lambda c: math.sqrt(sum((a - b) ** 2 for a, b in zip(c[:3], rgba[:3]))) + abs(c[3] - rgba[3]) * 255)
    return best, colours[best]


def literals(text, suffix):
    if suffix in (".html", ".htm", ".svg", ".vue", ".svelte", ".jsx", ".tsx"):
        text = LINK_ATTR.sub(lambda m: " " * len(m.group(0)), text)
    text = URL.sub(lambda m: " " * len(m.group(0)), text)
    for number_, line in enumerate(text.splitlines(), 1):
        found = [(m.start(), m.group(0)) for m in HEX.finditer(line)]
        found += [(m.start(), m.group(0)) for m in FUNC.finditer(line)]
        for column, literal in sorted(found):
            yield number_, column + 1, literal, bool(KEEP.search(line))


def source_files(paths):
    for path in paths:
        path = Path(path)
        if path.is_dir():
            for root, dirs, files in os.walk(str(path)):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                for name in sorted(files):
                    if name.lower().endswith(SOURCE_EXTENSIONS):
                        yield Path(root) / name
        elif path.is_file():
            yield path
        else:
            raise TokenError("no such file or folder: %s" % path)


def check(resolver, paths, out):
    colours = token_colours(resolver)
    if not colours:
        raise TokenError("the tokens give no sRGB colours to compare with")
    counted = off = kept = 0
    for path in source_files(paths):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            out.write("%s: not read: %s\n" % (path, error))
            continue
        for line, column, literal, keep in literals(text, path.suffix.lower()):
            rgba = parse_colour(literal)
            if rgba is None:
                continue
            counted += 1
            if any(same(rgba, colour) for colour in colours):
                continue
            if keep:
                kept += 1
                continue
            off += 1
            close, name = nearest(rgba, colours)
            out.write("%s:%d:%d: %s is not a token colour; nearest %s is %s\n"
                      % (path, line, column, literal, name, colour_css({"colorSpace": "srgb",
                         "components": [c / 255.0 for c in close[:3]], "alpha": close[3]})))
    out.write("%d colour literals, %d off the tokens, %d kept with an off-token reason\n" % (counted, off, kept))
    return 1 if off else 0


# --- init and verify --------------------------------------------------------------------------------

def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def verify(folder, out):
    folder = Path(folder)
    manifest = read_json(ASSETS / "carbon" / "source.json")
    listed = {}
    for package in manifest["packages"]:
        for name, entry in package["files"].items():
            listed[name] = entry["sha256"]
    problems = []
    for name, digest in sorted(listed.items()):
        path = folder / name
        if not path.is_file():
            problems.append("missing: %s" % name)
        elif file_digest(path) != digest:
            problems.append("changed: %s" % name)
    for path in sorted(folder.rglob("*")):
        name = path.relative_to(folder).as_posix()
        if path.is_file() and name not in listed and name != "source.json":
            problems.append("not in source.json: %s" % name)
    for problem in problems:
        out.write(problem + "\n")
    out.write("%d Carbon files checked against source.json, %d problems\n" % (len(listed), len(problems)))
    return 1 if problems else 0


def resolver_document(light, dark):
    def theme(name, mode):
        return [{"$ref": "carbon/themes/%s/%s.tokens.json" % (name, part)} for part in THEME_FILES] + \
               [{"$ref": "corthex/%s.tokens.json" % mode}]
    return {
        "$schema": RESOLVER_SCHEMA,
        "version": "2025.10",
        "sets": {
            "carbon": {"sources": [{"$ref": "carbon/colors.tokens.json"}, {"$ref": "carbon/layout.tokens.json"}]},
            "corthex": {"sources": [{"$ref": "corthex/base.tokens.json"}]},
            "base": {"sources": [{"$ref": "base.tokens.json"}]},
        },
        "modifiers": {
            "theme": {"contexts": {"light": theme(light, "light"), "dark": theme(dark, "dark")}, "default": "light"},
        },
        "resolutionOrder": [{"$ref": "#/sets/carbon"}, {"$ref": "#/sets/corthex"}, {"$ref": "#/modifiers/theme"},
                            {"$ref": "#/sets/base"}],
    }


def as_json(data):
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def init(dest, light, dark, update, out):
    dest = Path(dest)
    if dest.exists() and not dest.is_dir():
        raise TokenError("%s is not a folder" % dest)
    plan, conflicts = [], []
    for kind in ("carbon", "corthex"):
        for source in sorted((ASSETS / kind).rglob("*")):
            if source.is_file():
                target = dest / kind / source.relative_to(ASSETS / kind)
                data = source.read_bytes()
                if not target.exists():
                    plan.append((target, data, "copied"))
                elif target.read_bytes().replace(b"\r\n", b"\n") == data.replace(b"\r\n", b"\n"):
                    plan.append((target, None, "same"))
                elif update:
                    plan.append((target, data, "updated"))
                else:
                    conflicts.append(target)
    if conflicts:
        for target in conflicts:
            out.write("differs: %s\n" % target)
        out.write("Nothing written. These files differ from this version's; run again with --update to replace them.\n")
        return 1
    extra = [(dest / "tokens.resolver.json", as_json(resolver_document(light, dark))),
             (dest / "base.tokens.json", as_json({"$schema": FORMAT_SCHEMA, "$description":
                 "This project's own tokens. A token here replaces a Carbon or CORTHEX token of the same name."}))]
    for target, data in extra:
        plan.append((target, None, "kept") if target.exists() else (target, data, "written"))
    counts = {}
    for target, data, state in plan:
        if data is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        counts[state] = counts.get(state, 0) + 1
        if target.parent == dest:
            out.write("%s %s\n" % (state, target))
    out.write(", ".join("%s %d" % (state, counts[state]) for state in sorted(counts)) + "\n")
    return 0


# --- command line -----------------------------------------------------------------------------------

def pair(text):
    if "=" not in text:
        raise argparse.ArgumentTypeError("expected NAME=CONTEXT")
    return tuple(text.split("=", 1))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command")
    commands.required = True
    one = commands.add_parser("init", help="copy the default base into a project's design folder")
    one.add_argument("dest")
    one.add_argument("--light", choices=THEMES, default="g10")
    one.add_argument("--dark", choices=THEMES, default="g100")
    one.add_argument("--update", action="store_true", help="replace copied files that differ from this version")
    two = commands.add_parser("css", help="print one mode's tokens as CSS custom properties")
    two.add_argument("resolver")
    two.add_argument("--input", type=pair, action="append", default=[], help="a modifier input, such as theme=dark")
    two.add_argument("--prefix", default="")
    two.add_argument("--selector", default=":root")
    two.add_argument("--only", default="", help="comma-separated starts of the names to print, such as corthex-,background")
    three = commands.add_parser("check", help="list colour literals that no token has")
    three.add_argument("resolver")
    three.add_argument("paths", nargs="+")
    four = commands.add_parser("verify", help="compare a copy of the Carbon files with source.json")
    four.add_argument("folder", nargs="?", default=str(ASSETS / "carbon"))
    args = parser.parse_args(argv)
    out = sys.stdout
    try:
        if args.command == "init":
            return init(args.dest, args.light, args.dark, args.update, out)
        if args.command == "css":
            only = [item for item in args.only.split(",") if item]
            out.write(css_text(args.resolver, dict(args.input), args.prefix, args.selector, only))
            return 0
        if args.command == "check":
            return check(args.resolver, args.paths, out)
        return verify(args.folder, out)
    except TokenError as error:
        sys.stderr.write("tokens.py: %s\n" % error)
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    sys.exit(main())
