# Stage 09 · Mockup

| Slot | This stage |
| --- | --- |
| Inputs | Screen definitions from stage 08, brand assets, and references the user likes |
| Outputs | Design tokens in the Design Tokens Community Group format, by default `design/base.tokens.json`, and the chosen mockup for each screen, linked from its screen definition |
| Human view | A design tool such as Figma or Claude Design, as set in `human` |
| Sync | Tokens are the shared language: the design tool and the code use the same token names. When the design tool is the truth, export the tokens from it |
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

## Checks

- Every mockup uses token names, not one-off values.
- The token file follows the format: groups are objects without `$value`, tokens have `$value` and a `$type`.
- The chosen direction and the user's words are recorded.

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
