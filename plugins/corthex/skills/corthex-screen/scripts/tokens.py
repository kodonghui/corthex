#!/usr/bin/env python3
"""Design tokens for stage 09: start a project from the default base, write CSS and find off-token colours.

    tokens.py init DEST [--light THEME] [--dark THEME] [--update]
    tokens.py css RESOLVER [--input NAME=CONTEXT ...] [--prefix TEXT] [--selector TEXT] [--only PREFIXES]
    tokens.py check RESOLVER PATH [PATH ...]
    tokens.py verify [DIR]

`init` copies IBM Carbon's token files and the CORTHEX layer into DEST, by default a project's `design`
folder, and writes a resolver document and an empty `base.tokens.json` beside them when they are missing.
`css` resolves the tokens of one mode and prints them as CSS custom properties. `check` lists the colour
literals in source files that no token of any mode, or of any combination of modes, has. `verify` compares a copy of the Carbon files with
`source.json`. The script uses the Python standard library only, reads no network and writes only under DEST.
"""

import argparse
import colorsys
import hashlib
import itertools
import json
import math
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
THEMES = ("white", "g10", "g90", "g100")
DEFAULT_LIGHT, DEFAULT_DARK = "g10", "g100"
LIGHT_THEMES = ("white", "g10")
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
        with open(path, encoding="utf-8-sig") as handle:
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


def token_paths(node, path=()):
    if "$value" in node:
        yield path
        return
    for key, child in node.items():
        if not key.startswith("$") and isinstance(child, dict):
            for found in token_paths(child, path + (key,)):
                yield found


def ordered_modifiers(doc):
    """The names of the modifiers that resolutionOrder uses, in its order."""
    names = []
    for entry in doc.get("resolutionOrder", []):
        ref = entry.get("$ref", "") if isinstance(entry, dict) else ""
        if ref.startswith("#/modifiers/") and ref[len("#/modifiers/"):] not in names:
            names.append(ref[len("#/modifiers/"):])
    return names


def load_resolver(path, inputs=None, origin=None):
    """Merge the token trees a resolver document lists, for the given modifier inputs. When origin is a
    dict, it gets, for each token, the place of the source that last set it: (entry of resolutionOrder,
    source within that entry)."""
    path = Path(path)
    doc = read_json(path)
    base = path.parent
    inputs = dict(inputs or {})
    modifiers = doc.get("modifiers", {})
    for name in inputs:
        if name not in modifiers:
            raise TokenError("the resolver has no modifier %r" % name)
    tree = {}
    for index, entry in enumerate(doc.get("resolutionOrder", [])):
        ref = entry.get("$ref", "") if isinstance(entry, dict) else ""
        if ref.startswith("#/sets/") and ref[len("#/sets/"):] in doc.get("sets", {}):
            sources = doc["sets"][ref[len("#/sets/"):]].get("sources", [])
        elif ref.startswith("#/modifiers/") and ref[len("#/modifiers/"):] in modifiers:
            name = ref[len("#/modifiers/"):]
            modifier = modifiers[name]
            context = inputs.get(name, modifier.get("default"))
            if context is None:
                raise TokenError("modifier %r has no default; choose a context with --input %s=CONTEXT" % (name, name))
            if context not in modifier.get("contexts", {}):
                raise TokenError("modifier %r has no context %r" % (name, context))
            sources = modifier["contexts"][context]
        else:
            raise TokenError("resolutionOrder entry not understood: %s" % json.dumps(entry))
        if not isinstance(sources, list):
            raise TokenError("the sources of %s must be a list" % ref)
        for number, source in enumerate(sources):
            layer = load_sources([source], base)
            merge(tree, layer)
            if origin is not None:
                origin.update((found, (index, number)) for found in token_paths(layer))
    return tree


def mode_inputs(path, limit=256):
    """Every combination of the contexts of the modifiers the resolver uses, each modifier named."""
    doc = read_json(Path(path))
    names, choices, total = ordered_modifiers(doc), [], 1
    modifiers = doc.get("modifiers", {})
    for name in names:
        if not isinstance(modifiers.get(name), dict):
            raise TokenError("resolutionOrder names the modifier %r, which the resolver does not define" % name)
        contexts = list(modifiers[name].get("contexts", {}))
        if not contexts:
            raise TokenError("modifier %r has no contexts" % name)
        choices.append(contexts)
        total *= len(contexts)
    if total > limit:
        raise TokenError("the modifiers make %d combinations of contexts; check reads at most %d" % (total, limit))
    return [dict(zip(names, combination)) for combination in itertools.product(*choices)]


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
    if prefix and not prefix.endswith("-"):
        prefix += "-"
    return "--" + prefix + "-".join(parts)


def css_text(resolver, inputs, prefix="", selector=":root", only=None):
    """CSS custom properties for one mode. When two tokens give one CSS name, such as a project's
    text.primary and Carbon's text-primary, the token of the later source wins, as the resolver's order and
    each entry's list of sources say."""
    origin = {}
    tokens = Tokens(load_resolver(resolver, inputs, origin))
    start = len(css_name(("x",), prefix)) - 1
    chosen, skipped, replaced = {}, [], []
    for path in tokens.names():
        kind, value = tokens.resolve(path)
        name = css_name(path, prefix)
        if only and not any(name[start:].startswith(item) for item in only):
            continue
        pairs = css_values(name, kind, value)
        dotted, layer = ".".join(path), origin.get(path, (0, 0))
        if not pairs:
            skipped.append(dotted)
        for key, text in pairs:
            if key in chosen:
                other_layer, other = chosen[key][:2]
                if other_layer == layer:
                    raise TokenError("two tokens of one file give the CSS name %s: %s and %s" % (key, other, dotted))
                if layer < other_layer:
                    replaced.append("%s by %s" % (dotted, other))
                    continue
                replaced.append("%s by %s" % (other, dotted))
            chosen[key] = (layer, dotted, text)
    lines = ["  %s: %s;" % (key, text) for key, (_, _, text) in chosen.items()]
    mode = ", ".join("%s=%s" % item for item in sorted(inputs.items())) or "defaults"
    head = "/* Written by tokens.py css from %s (%s). Change the token files, not this text. */" % (Path(resolver).name, mode)
    out = [head, selector + " {"] + lines + ["}"]
    if replaced:
        out.append("/* Same CSS name, the later file's token written: %s */" % ", ".join(replaced))
    if skipped:
        out.append("/* Not written, no CSS form: %s */" % ", ".join(skipped))
    return "\n".join(out) + "\n"


# --- off-token colours ------------------------------------------------------------------------------

HEX = re.compile(r"(?<![\w&#/.])#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![\w(-])")
FUNC = re.compile(r"\b(rgba?|hsla?)\(\s*([^()]*?)\s*\)", re.I)
URL = re.compile(r"url\(\s*['\"]?#[^)]*\)", re.I)
LINK_ATTR = re.compile(r"""\b(?:href|xlink:href|src|action|id|for|name)\s*=\s*("[^"]*"|'[^']*')""", re.I)
# Colour functions the check cannot compare with the tokens' sRGB values: each one is reported.
OTHER_FUNC = re.compile(r"(?<![\w.$-])(?:oklch|oklab|lab|lch|hwb|color(?=\(\s*(?:srgb|srgb-linear|display-p3|a98-rgb|prophoto-rgb"
                        r"|rec2020|xyz|xyz-d50|xyz-d65)\b))\([^()]*\)", re.I)
# A declaration or attribute that takes a colour, in CSS, markup or a script's style object, with its value:
# a quoted string, or the text up to the end of the declaration, attribute or tag. It is a lookahead, so that
# declarations on one line overlap; a comparison such as `color === x` is not a declaration.
SIDE = r"(?:-?(?:top|right|bottom|left|block|inline)(?:-?(?:start|end))?)?"
PROPERTY = re.compile(r"(?=(?<![\w-])(?:(?:background|border" + SIDE + r"|outline|text-?decoration|caret|accent|column-?rule"
                      r"|stop|flood|lighting)-?color|color|background(?:-?image)?|border" + SIDE + r"|outline|fill|stroke"
                      r"|box-?shadow|text-?shadow|column-?rule|text-?decoration|--[\w-]+)\s*(?::|=(?!=))\s*"
                      r"(\"[^\"\n]*\"|'[^'\n]*'|[^;{}\n<>\"'`]*))", re.I)
COMMENT = re.compile(r"/\*.*?\*/", re.S)
LINE_COMMENT = re.compile(r"(?:^|(?<=[\s;{}(),]))//[^\n]*", re.M)
MARKUP_COMMENT = re.compile(r"<!--.*?-->", re.S)
RAW_BLOCK = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.I | re.S)
TEXT_NODE = re.compile(r">([^<>]*)(?=<)")
MARKUP_SUFFIXES = (".html", ".htm", ".svg", ".vue", ".svelte", ".jsx", ".tsx")
TEXT_SUFFIXES = (".html", ".htm", ".svg", ".vue", ".svelte")
LINE_COMMENT_SUFFIXES = (".scss", ".sass", ".less", ".js", ".jsx", ".mjs", ".ts", ".tsx", ".vue", ".svelte")
WORD = re.compile(r"(?<![\w$@.#-])([A-Za-z]+)(?![\w-])")
SELECTOR = re.compile(r"(^|[{};])([^{};]*)(?=\{)")
STYLE = re.compile(r"(<style\b[^>]*>)(.*?)(</style\s*>)", re.I | re.S)
INTERPOLATION = re.compile(r"#\{[^{}]*\}")
SASS_DECLARATION = re.compile(r"^\s*(?:[\w-]+\s*:|[$@+=:]|//|/\*|\*|$)")
CSS_SUFFIXES = (".css", ".scss", ".sass", ".less")
# The CSS named colours (CSS Color Module Level 4), as name and sRGB hex.
NAMED = dict(zip(*[iter((
    "aliceblue f0f8ff antiquewhite faebd7 aqua 00ffff aquamarine 7fffd4 azure f0ffff beige f5f5dc bisque ffe4c4 "
    "black 000000 blanchedalmond ffebcd blue 0000ff blueviolet 8a2be2 brown a52a2a burlywood deb887 cadetblue "
    "5f9ea0 chartreuse 7fff00 chocolate d2691e coral ff7f50 cornflowerblue 6495ed cornsilk fff8dc crimson dc143c "
    "cyan 00ffff darkblue 00008b darkcyan 008b8b darkgoldenrod b8860b darkgray a9a9a9 darkgreen 006400 darkgrey "
    "a9a9a9 darkkhaki bdb76b darkmagenta 8b008b darkolivegreen 556b2f darkorange ff8c00 darkorchid 9932cc darkred "
    "8b0000 darksalmon e9967a darkseagreen 8fbc8f darkslateblue 483d8b darkslategray 2f4f4f darkslategrey 2f4f4f "
    "darkturquoise 00ced1 darkviolet 9400d3 deeppink ff1493 deepskyblue 00bfff dimgray 696969 dimgrey 696969 "
    "dodgerblue 1e90ff firebrick b22222 floralwhite fffaf0 forestgreen 228b22 fuchsia ff00ff gainsboro dcdcdc "
    "ghostwhite f8f8ff gold ffd700 goldenrod daa520 gray 808080 green 008000 greenyellow adff2f grey 808080 "
    "honeydew f0fff0 hotpink ff69b4 indianred cd5c5c indigo 4b0082 ivory fffff0 khaki f0e68c lavender e6e6fa "
    "lavenderblush fff0f5 lawngreen 7cfc00 lemonchiffon fffacd lightblue add8e6 lightcoral f08080 lightcyan e0ffff "
    "lightgoldenrodyellow fafad2 lightgray d3d3d3 lightgreen 90ee90 lightgrey d3d3d3 lightpink ffb6c1 lightsalmon "
    "ffa07a lightseagreen 20b2aa lightskyblue 87cefa lightslategray 778899 lightslategrey 778899 lightsteelblue "
    "b0c4de lightyellow ffffe0 lime 00ff00 limegreen 32cd32 linen faf0e6 magenta ff00ff maroon 800000 "
    "mediumaquamarine 66cdaa mediumblue 0000cd mediumorchid ba55d3 mediumpurple 9370db mediumseagreen 3cb371 "
    "mediumslateblue 7b68ee mediumspringgreen 00fa9a mediumturquoise 48d1cc mediumvioletred c71585 midnightblue "
    "191970 mintcream f5fffa mistyrose ffe4e1 moccasin ffe4b5 navajowhite ffdead navy 000080 oldlace fdf5e6 olive "
    "808000 olivedrab 6b8e23 orange ffa500 orangered ff4500 orchid da70d6 palegoldenrod eee8aa palegreen 98fb98 "
    "paleturquoise afeeee palevioletred db7093 papayawhip ffefd5 peachpuff ffdab9 peru cd853f pink ffc0cb plum "
    "dda0dd powderblue b0e0e6 purple 800080 rebeccapurple 663399 red ff0000 rosybrown bc8f8f royalblue 4169e1 "
    "saddlebrown 8b4513 salmon fa8072 sandybrown f4a460 seagreen 2e8b57 seashell fff5ee sienna a0522d silver c0c0c0 "
    "skyblue 87ceeb slateblue 6a5acd slategray 708090 slategrey 708090 snow fffafa springgreen 00ff7f steelblue "
    "4682b4 tan d2b48c teal 008080 thistle d8bfd8 tomato ff6347 turquoise 40e0d0 violet ee82ee wheat f5deb3 white "
    "ffffff whitesmoke f5f5f5 yellow ffff00 yellowgreen 9acd32 "
).split())] * 2))


NUMBER = re.compile(r"^(?:[-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?(?:%|deg|rad|grad|turn)?|none|/)$", re.I)
TURNS = (("grad", 400.0), ("turn", 1.0), ("deg", 360.0), ("rad", 2 * math.pi))


def channel(text, scale):
    text = text.strip()
    if text.lower() == "none":
        return 0.0
    if text.endswith("%"):
        return float(text[:-1]) * scale / 100.0
    return float(text)


def hue_turns(text):
    text = text.strip().lower()
    if text == "none":
        return 0.0
    for unit, per_turn in TURNS:
        if text.endswith(unit):
            return float(text[:-len(unit)]) / per_turn
    return float(text) / 360.0


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
    alpha = "1"
    if "/" in parts:
        index = parts.index("/")
        parts, alpha_parts = parts[:index], parts[index + 1:]
        if len(alpha_parts) != 1:
            return None
        alpha = alpha_parts[0]
    elif len(parts) == 4:
        alpha = parts[3]
        parts = parts[:3]
    if len(parts) != 3:
        return None
    try:
        alpha = channel(alpha, 1)
        if kind.startswith("rgb"):
            rgb = [channel(p, 255) for p in parts]
        else:
            hue = hue_turns(parts[0])
            light, saturation = (channel(part.rstrip("%"), 1) / 100.0 for part in (parts[2], parts[1]))
            rgb = [c * 255 for c in colorsys.hls_to_rgb(hue % 1.0, light, saturation)]
    except ValueError:
        return None
    return tuple(int(round(max(0, min(255, c)))) for c in rgb) + (round(max(0.0, min(1.0, alpha)), 4),)


def token_colours(resolver):
    """Every sRGB colour any mode of the tokens gives, with one token name for each."""
    colours = {}
    for inputs in mode_inputs(resolver):
        tokens = Tokens(load_resolver(resolver, inputs))
        mode = ", ".join("%s=%s" % item for item in sorted(inputs.items())) or "no modifiers"
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


def blank(match, group=0):
    """The text with one match's group replaced by spaces, keeping line breaks and columns."""
    start, end = match.span(group)
    return re.sub(r"[^\n]", " ", match.string[start:end])


def selectors(css):
    """CSS with its selectors blanked, so that an ID such as #bad is not read as a colour. Only the text
    after the last comment before a brace is a selector; an at-rule's prelude, such as @include or @if,
    holds values and stays."""
    def one(match):
        span = match.group(2)
        cut = span.rfind("*/") + 2 if "*/" in span else 0
        head, selector = span[:cut], span[cut:]
        if selector.strip().startswith("@"):
            return match.group(1) + span
        return match.group(1) + head + re.sub(r"[^\n]", " ", selector)
    return SELECTOR.sub(one, css)


def sass_selectors(sass):
    """Indented Sass with its selector lines blanked: a line that is not a declaration, a variable, an
    at-rule, a mixin or a comment is a selector."""
    return "".join(line if SASS_DECLARATION.match(line) else re.sub(r"[^\n]", " ", line)
                   for line in sass.splitlines(True))


def text_nodes(markup):
    """Markup with the text between its tags blanked, outside script and style blocks: page text such as
    "fixed in #789" is not a colour."""
    parts, last = [], 0
    for block in list(RAW_BLOCK.finditer(markup)) + [None]:
        start = block.start() if block else len(markup)
        parts.append(TEXT_NODE.sub(lambda m: ">" + blank(m, 1), markup[last:start]))
        if block:
            parts.append(block.group(0))
            last = block.end()
    return "".join(parts)


def literals(text, suffix):
    """(line, column, literal, kind, kept) for each colour written in the text: kind is "value" when the
    literal can be compared with the tokens, "named" for a CSS colour name and "other" for a function the
    check cannot compare. Comments are skipped, but an off-token reason in one still keeps its line."""
    kept = [bool(KEEP.search(line)) for line in text.splitlines()]
    text = COMMENT.sub(blank, text)
    if suffix in LINE_COMMENT_SUFFIXES:
        text = LINE_COMMENT.sub(blank, text)
    if suffix in TEXT_SUFFIXES:
        text = text_nodes(MARKUP_COMMENT.sub(blank, text))
    if suffix in MARKUP_SUFFIXES:
        text = LINK_ATTR.sub(blank, text)
        text = STYLE.sub(lambda m: m.group(1) + selectors(m.group(2)) + m.group(3), text)
    if suffix in CSS_SUFFIXES:
        text = INTERPOLATION.sub(blank, text)
        text = sass_selectors(text) if suffix == ".sass" else selectors(text)
    text = URL.sub(blank, text)
    for number_, line in enumerate(text.splitlines(), 1):
        found = [(m.start(), m.group(0), "value") for m in HEX.finditer(line)]
        found += [(m.start(), m.group(0), "value") for m in FUNC.finditer(line)]
        found += [(m.start(), m.group(0), "other") for m in OTHER_FUNC.finditer(line)]
        seen = set()
        for declaration in PROPERTY.finditer(line):
            value = re.sub(r"url\([^)]*\)|var\([^)]*\)", lambda m: " " * len(m.group(0)), declaration.group(1))
            for word in WORD.finditer(value):
                column = declaration.start(1) + word.start(1)
                if word.group(1).lower() in NAMED and column not in seen:
                    seen.add(column)
                    found.append((column, word.group(1), "named"))
        for column, literal, kind in sorted(found):
            yield number_, column + 1, literal, kind, kept[number_ - 1]


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
    counted = off = kept = unread = 0
    for path in source_files(paths):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            out.write("%s: not read, so not checked: %s\n" % (path, error))
            unread += 1
            continue
        for line, column, literal, kind, keep in literals(text, path.suffix.lower()):
            if kind == "other":
                rgba, problem = None, "is a colour function this check cannot compare with the tokens"
            else:
                rgba = parse_colour("#" + NAMED[literal.lower()] if kind == "named" else literal)
                problem = "is not a token colour"
                if rgba is None:
                    inner = literal[literal.index("(") + 1:-1].replace("/", " / ")
                    if not all(NUMBER.match(part) for part in re.split(r"[\s,]+", inner.strip()) if part):
                        continue
                    problem = "is a colour this check cannot read"
            counted += 1
            if rgba is not None and any(same(rgba, colour) for colour in colours):
                continue
            if keep:
                kept += 1
                continue
            off += 1
            place = "%s:%d:%d: %s %s" % (path, line, column, literal, problem)
            if rgba is not None:
                close, name = nearest(rgba, colours)
                place += "; nearest %s is %s" % (name, colour_css({"colorSpace": "srgb",
                                                                  "components": [c / 255.0 for c in close[:3]],
                                                                  "alpha": close[3]}))
            out.write(place + "\n")
    out.write("%d colour literals, %d off the tokens, %d kept with an off-token reason%s\n"
              % (counted, off, kept, ", %d files not read" % unread if unread else ""))
    return 1 if off or unread else 0


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
        layer = "light" if name in LIGHT_THEMES else "dark"
        return [{"$ref": "carbon/themes/%s/%s.tokens.json" % (name, part)} for part in THEME_FILES] + \
               [{"$ref": "corthex/%s.tokens.json" % layer}]
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


def resolver_plan(target, light, dark):
    """What init does with the resolver document: (data to write or None, state, note). A theme left as
    None keeps the one an earlier init chose, else takes the default. The state is "kept" for a resolver
    init did not write, and "not applied" when the themes asked for could not be set in it."""
    requested = bool(light or dark)
    current, before, unreadable = None, None, None
    if target.exists():
        try:
            current = json.loads(target.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as error:
            unreadable = error
        before = next(((one, two) for one in THEMES for two in THEMES if current == resolver_document(one, two)), None)
    light = light or (before[0] if before else DEFAULT_LIGHT)
    dark = dark or (before[1] if before else DEFAULT_DARK)
    data = as_json(resolver_document(light, dark))
    if not target.exists():
        return data, "written", "light theme %s, dark theme %s" % (light, dark)
    if before == (light, dark):
        return None, "same", ""
    if before:
        return data, "updated", "the light theme is now %s and the dark theme %s" % (light, dark)
    if unreadable is not None:
        note = "it cannot be read as JSON (%s), so it was kept" % unreadable
    else:
        note = "it is not the one init writes, so it was kept"
        if "carbon/" not in json.dumps(current):
            note += "; it lists no Carbon file, so the default base is not used until its sets are added"
    state = "kept"
    if requested:
        state, note = "not applied", note + "; the themes asked for were not set, so change its theme lists by hand"
    return None, state, note + " (see Default base in references/09-mockup.md)"


def init(dest, light, dark, update, out):
    dest = Path(dest)
    if dest.exists() and not dest.is_dir():
        raise TokenError("%s is not a folder" % dest)
    plan, conflicts, stale = [], [], []
    for kind in ("carbon", "corthex"):
        shipped = set()
        for source in sorted((ASSETS / kind).rglob("*")):
            if source.is_file():
                shipped.add(source.relative_to(ASSETS / kind).as_posix())
                target = dest / kind / source.relative_to(ASSETS / kind)
                data = source.read_bytes()
                if not target.exists():
                    plan.append((target, data, "copied", ""))
                elif target.read_bytes().replace(b"\r\n", b"\n") == data.replace(b"\r\n", b"\n"):
                    plan.append((target, None, "same", ""))
                elif update:
                    plan.append((target, data, "updated", ""))
                else:
                    conflicts.append(target)
        if (dest / kind).is_dir():
            stale += [path for path in sorted((dest / kind).rglob("*"))
                      if path.is_file() and path.relative_to(dest / kind).as_posix() not in shipped]
    if conflicts:
        for target in conflicts:
            out.write("differs: %s\n" % target)
        out.write("Nothing written. These files differ from this version's; run again with --update to replace them.\n")
        return 1
    resolver = dest / "tokens.resolver.json"
    data, resolver_state, note = resolver_plan(resolver, light, dark)
    if resolver_state == "not applied":
        out.write("not applied %s: %s\n" % (resolver, note))
        out.write("Nothing written.\n")
        return 1
    plan.append((resolver, data, resolver_state, note))
    base = dest / "base.tokens.json"
    plan.append((base, None, "kept", "") if base.exists() else (base, as_json({"$schema": FORMAT_SCHEMA, "$description":
                "This project's own tokens. A token here replaces a Carbon or CORTHEX token of the same name."}), "written", ""))
    for target, data, _, _ in plan:
        for parent in target.parents:
            if parent == dest:
                break
            if parent.exists() and not parent.is_dir():
                raise TokenError("%s is not a folder, so nothing was written" % parent)
    counts = {}
    for target, data, state, note in plan:
        if data is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        counts[state] = counts.get(state, 0) + 1
        if target.parent == dest:
            out.write("%s %s%s\n" % (state, target, ": " + note if note else ""))
    for path in stale:
        out.write("not in this version: %s; the resolver init writes does not use it\n" % path)
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
    one.add_argument("--light", choices=THEMES, help="Carbon theme of the light mode; first time %s" % DEFAULT_LIGHT)
    one.add_argument("--dark", choices=THEMES, help="Carbon theme of the dark mode; first time %s" % DEFAULT_DARK)
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
    except (TokenError, OSError) as error:
        sys.stderr.write("tokens.py: %s\n" % error)
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    sys.exit(main())
