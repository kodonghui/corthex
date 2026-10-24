# Stage 09 · Mockup

| Slot | This stage |
| --- | --- |
| Inputs | Screen definitions from stage 08, brand assets, and references the user likes |
| Outputs | Design tokens in the Design Tokens Community Group format, by default `design/base.tokens.json`, and the chosen mockup for each screen, linked from its screen definition |
| Human view | By default Figma or Claude Design, as set in `human`. See [design-tools.md](design-tools.md) |
| Sync | Tokens are the shared language: the design tool and the code use the same token names. By default the token file is the source and the tool takes the tokens from it; when the design tool is the truth, export the tokens from it |
| Human checkpoints | One direction is chosen before more screens are drawn, and the tokens are frozen before development uses them |
| Trace IDs | SCR IDs for mockups; token names for tokens |

## Rules for candidates

- Make two candidates per screen by default. Make more only when the user asks.
- Once the user picks a direction, later screens follow it. Record the choice with the user's words.
- Show each candidate in the states and at the widths that matter, and say which ones you showed.

## Steps

1. Read the screen definitions; mock up their states, not just the normal one.
2. Start tokens small: colour, type, space and radius that the candidates actually use.
3. Present the candidates side by side with what differs between them.
4. After the choice, update the tokens and link the mockup from the screen definition.
5. For light, dark, high-contrast or other modes, put each mode's tokens in a file of its own and list the files in a resolver document (see Modes below).

## Checks

- Every mockup uses token names, not one-off values.
- The token file follows the format: groups are objects without `$value`, tokens have `$value` and a `$type`.
- Every token has one value. Each mode's values are in that mode's file, and the resolver document lists every token file.
- The chosen direction and the user's words are recorded.

## Modes

Modes, such as light, dark and high contrast, follow the Design Tokens Resolver Module 2025.10. Never put several modes' values inside one token's `$value`. Keep the tokens every mode shares in the base file, put the tokens that change in one file per mode under the same names, and choose between them with a resolver document, by default `design/tokens.resolver.json`:

```json
{
  "$schema": "https://www.designtokens.org/schemas/2025.10/resolver.json",
  "version": "2025.10",
  "sets": {
    "base": { "sources": [{ "$ref": "base.tokens.json" }] }
  },
  "modifiers": {
    "theme": {
      "contexts": {
        "light": [{ "$ref": "theme/light.tokens.json" }],
        "dark": [{ "$ref": "theme/dark.tokens.json" }]
      },
      "default": "light"
    }
  },
  "resolutionOrder": [{ "$ref": "#/sets/base" }, { "$ref": "#/modifiers/theme" }]
}
```

Paths in `$ref` are relative to the resolver document. Later entries in `resolutionOrder` win, so a mode's value replaces the base value with the same name. A tool builds one token set per mode from an input such as `{ "theme": "dark" }`; without one, it uses the `default`. The module's own text is inconsistent about the `version` string; its JSON schema and current tools use `2025.10`.

## Output template

The format is the Design Tokens Community Group report of 2025.10. Colours are objects with a colour space and components, and dimensions are objects with a value and a unit (`px` or `rem`).

```json
{
  "color": {
    "$type": "color",
    "primary": { "$value": { "colorSpace": "srgb", "components": [0.12, 0.44, 0.92] } }
  },
  "space": {
    "$type": "dimension",
    "md": { "$value": { "value": 16, "unit": "px" } }
  }
}
```
