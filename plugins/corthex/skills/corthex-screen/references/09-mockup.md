# Stage 09 · Mockup

| Slot | This stage |
| --- | --- |
| Inputs | Screen definitions from stage 08, brand assets, references the user likes, and the default base: IBM Carbon's tokens with the CORTHEX layer (see Default base below) |
| Outputs | Design tokens in the Design Tokens Community Group format, by default `design/base.tokens.json` over the default base, and the chosen mockup for each screen, linked from its screen definition |
| Human view | On a project on NEXUS, the stage's record, talk and checkpoint in NEXUS beside the design tool; the design tool by default Figma or Claude Design, as set in `human`. See [design-tools.md](design-tools.md) |
| Sync | Tokens are the shared language: the design tool and the code use the same token names. By default the token file is the source and the tool takes the tokens from it; when the design tool is the truth, export the tokens from it |
| Human checkpoints | One direction is chosen before more screens are drawn, and the tokens are frozen before development uses them |
| Trace IDs | SCR IDs for mockups; token names for tokens |

## Rules for candidates

- Make two candidates per screen by default. Make more only when the user asks.
- Once the user picks a direction, later screens follow it. Record the choice with the user's words.
- Show each candidate in the states and at the widths that matter, and say which ones you showed.
- A mockup draws the screen as it will ship: its real copy at its real size, in each state. Techniques of promotional "faux UI", such as cutting text to a few words and grey bars or cropping windows past the edge, are for product demos, never for mockups.

## Steps

1. Read the screen definitions; mock up their states, not just the normal one.
2. Start from the default base: copy it into the project's `design` folder with `python3 '<absolute skill directory>/scripts/tokens.py' init -- '<project>/design'` (on Windows `py -3`), with every path in single quotes. When the project or the user names another base, such as a brand's own design system, skip this, record the choice as a decision with the user's words, and keep the rest of this stage.
3. Add to `base.tokens.json` only what the candidates use and the base lacks, such as a brand colour, and override a base token there only when the user asks for a different value.
4. Present the candidates side by side with what differs between them. Give pages the tokens as CSS custom properties: `python3 '<absolute skill directory>/scripts/tokens.py' css -- '<project>/design/tokens.resolver.json'` prints the default mode; for another, put the input before `--`: `python3 '<absolute skill directory>/scripts/tokens.py' css --input theme=dark -- '<project>/design/tokens.resolver.json'`.
5. After the choice, update the tokens and link the mockup from the screen definition. When the chosen mockup is an HTML page in the repository and the project is on NEXUS, name the page, or its folder, in the stage's `page` setting in `.corthex/project.json`, as the `corthex` skill's project settings describe, so that NEXUS shows it beside the tokens it uses. The page's whole text is sent, so keep secrets and personal data out of it.
6. For light, dark, high-contrast or other modes, put each mode's tokens in a file of its own and list the files in a resolver document (see Modes below).
7. Before showing a mockup or handing it to development, find the colours that no token gives: `python3 '<absolute skill directory>/scripts/tokens.py' check -- '<project>/design/tokens.resolver.json' '<file or folder>'` lists each with its place and the nearest token. It compares them with the colours of every combination of the resolver's modes. It reads hex, `rgb()` and `hsl()` values, and CSS colour names in properties that take a colour, custom properties and gradients included, and skips comments and the text between HTML tags; it reports `oklch()`, `lab()`, `lch()`, `hwb()` and `color()` as colours it cannot compare. It does not see colours that code computes, colours inside images, or a colour name outside a colour property, so look at the render too. A file it cannot read as UTF-8 fails the check until it is converted or left out.

## Checks

- Every mockup uses token names, not one-off values. `tokens.py check` finds no colour outside the tokens, or each one left has a reason on its line in a comment that starts with `off-token:`, such as a partner's logo colour or an ID in a script that looks like a colour, such as `'#bad'`.
- The token file follows the format: groups are objects without `$value`, tokens have `$value` and a `$type`.
- Every token has one value. Each mode's values are in that mode's file, and the resolver document lists every token file.
- The chosen direction and the user's words are recorded.

## Default base: IBM Carbon

A project starts from IBM Carbon's design tokens, unchanged, with a thin CORTHEX layer over them. `tokens.py init` copies three layers into the `design` folder; a later layer wins over an earlier one for the same token name, and in `tokens.py css` for the same CSS name, such as a project's `text.primary` over Carbon's `text-primary`. Within one layer or mode, a later file in its list wins the same way. The output names each token it left out this way.

| Layer | Files in `design/` | What it holds | Who changes it |
| --- | --- | --- | --- |
| Carbon | `carbon/`: `colors.tokens.json`, `layout.tokens.json` and `themes/<theme>/` | The colour palette, spacing, sizes and radius scale, and the theme tokens such as `background`, `layer-01`, `text-primary`, `support-success` and the AI tokens | Nobody. A new Carbon version comes with a new version of this skill; `init` with `--update` replaces the copies and lists copied files the new version no longer has |
| CORTHEX | `corthex/`: `base.tokens.json`, `light.tokens.json` and `dark.tokens.json` | Rounded corners, fonts and type styles, the colours of AI proposals, stage states and event-storming stickies, all named from Carbon tokens | This skill, by a decision |
| Project | `base.tokens.json` | The project's own tokens. A token here replaces a Carbon or CORTHEX token of the same name in every mode | The project |

- **Themes.** The light mode uses Carbon's Gray 10 theme and the dark mode Gray 100. `init --light` and `--dark` choose among `white`, `g10`, `g90` and `g100`, and each mode takes the CORTHEX layer's light file with `white` or `g10` and its dark file with `g90` or `g100`; running `init` again keeps the themes chosen before unless they are given again. To give a token of the project's own a value per mode, add the project's mode file at the end of that mode's list in `tokens.resolver.json`. Once the resolver is no longer the one `init` wrote, `init` keeps it and says so, and writes nothing and fails when `--light` or `--dark` is given; change its theme lists by hand. A project that had its own resolver before keeps it too: add the `carbon` and `corthex` sets and the theme lists to it, in the order `init` writes them: `carbon`, `corthex`, the theme, then the project's `base`.
- **Rounded corners.** Carbon's components keep most corners square. The CORTHEX layer rounds them with Carbon's own radius scale: `corthex.radius.box` (8 px) for boxes, buttons, inputs and stickies, `corthex.radius.panel` (16 px) for panels and dialogs, and `corthex.radius.pill` for tags.
- **Type.** `corthex.font-family.sans` is IBM Plex Sans KR and `corthex.font-family.mono` IBM Plex Mono, each with system fonts after it. The `corthex.type` styles copy Carbon's type scale, such as `body-01` and `heading-03`. The token files name the fonts; a page that needs them loads them itself.
- **AI proposals, stages and stickies.** `corthex.ai` marks what the AI proposed and a person has not accepted. `corthex.stage` gives the colours of done, in progress, not started and skipped, always beside a word or an icon, never alone. `corthex.sticky` gives one colour to each element of the event-storming legend of stage 01, with `corthex.sticky.text` readable on all of them.
- **License.** Carbon's token files are Apache-2.0, Copyright 2015 IBM Corp. Keep `carbon/LICENSE` and `carbon/source.json` with the copies: `source.json` names each package, its version, its download address, its integrity hash, its Git commit and each file's SHA-256. `python3 '<absolute skill directory>/scripts/tokens.py' verify -- '<project>/design/carbon'` compares a copy with it.

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

Paths in `$ref` are relative to the resolver document. Later entries in `resolutionOrder` win, so a mode's value replaces the base value with the same name. A tool builds one token set per mode from an input such as `{ "theme": "dark" }`; without one, it uses the `default`, and `tokens.py css` asks for `--input` when a modifier has none. The module's own text is inconsistent about the `version` string; its JSON schema and current tools use `2025.10`.

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
