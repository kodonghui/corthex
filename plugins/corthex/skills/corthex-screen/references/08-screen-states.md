# Stage 08 · Screen states

| Slot | This stage |
| --- | --- |
| Inputs | The sitemap (SCR), the functional spec (SPEC) and the API contract (API) |
| Outputs | One screen definition per screen in the stage's `source` folder, by default `docs/08-screens/SCR-001.md`: its purpose, the data it shows and the API it comes from, its states, the state each API response leads to, its actions and its rules |
| Human view | By default grayscale wireframes drawn from the screen definitions, as set in `human`. See Wireframes below |
| Sync | The definition is written or updated before the screen's code changes |
| Human checkpoints | The screen definition is approved before implementation |
| Trace IDs | SCR IDs, with states written as `SCR-001#empty` |

## States

Cover each state that can happen on the screen, and say why any of these does not apply:

| State | What it covers |
| --- | --- |
| normal | The data is there and the user can act |
| loading | The data is on its way |
| empty | There is nothing to show yet |
| error | Loading or an action failed |
| permission | The user may not see or do this |
| stale | The data shown may be out of date |

## Responses and states

Every response the API contract lists for an operation the screen calls (stage 06) leads to a state. Start from these defaults and write down where a screen differs:

| Response | State | What the user sees by default |
| --- | --- | --- |
| Success with data | normal | The data |
| Success with nothing to show | empty | What will appear here and how to add it |
| 400 or 422 | error | The message beside the input it concerns; the input is kept |
| 401 | permission | A sign-in prompt, then back to this screen. On the sign-in screen itself, an error: the message beside the form |
| 403 | permission | Why this is not allowed, and a way back |
| 404 | error | That the item no longer exists, and a link to where it was listed |
| 409 | stale | That the data changed; reload, then try again |
| 429, 503, `default`, a timeout or no network | error | A short message and a retry |

By default the screen shows the message of the error code in the API contract's list (stage 06); write down where it says more. A screen can add states of its own, such as rate-limited or expired, with the responses that lead to them. The mock server returns any listed response on request, so each state can be built and checked before the back end is ready.

## Steps

1. Write the screen's purpose in one sentence, from the flows that pass through it.
2. List the data it shows and the API operation each piece comes from.
3. List the actions, each with its result and its failure.
4. Describe each state: what the user sees and what they can do, and which responses lead to it, such as `API-002#404`, starting from the defaults above.

## Checks

- Every piece of data names its API operation.
- Every response of every operation the screen calls leads to a described state.
- Every action has a result and a failure.
- Every applicable state is described; long text and narrow screens are considered.
- Every described state has a wireframe.

## Wireframes

Wireframes show structure and states, not looks, so the review stays on what each screen does.

- Draw them from the screen definitions, one frame per state, labelled with the state's ID, such as `SCR-002#empty`. Use greys, the system font and placeholder text only; design tokens come in stage 09.
- Show each frame at the narrowest and the widest width the project supports, such as 360 and 1280 pixels.
- Put all the frames on one page, by default `docs/08-screens/wireframes.html`, and draw it again in the same change as the definitions. Where the host can publish a page, such as an artifact in Claude Code, publish it and put its link in `link`.
- A team that sketches in a design tool, such as Figma, names it in `human`; the definitions stay the source.

## Output template

```markdown
# SCR-002 Order detail

Purpose: the customer checks one order and can cancel it while it is unpaid. (FL-002)

| Data | Source |
| --- | --- |
| Order items, total, status | API-002 |

| Action | Result | Failure |
| --- | --- | --- |
| Cancel order | Status becomes cancelled (SPEC-005) | Already paid → explain and keep the order |

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-002#loading | Placeholder rows; no actions | |
| SCR-002#error | "This order no longer exists" and a link to the orders (404); otherwise a message and a retry button | API-002#404, API-002#default |
| SCR-002#permission | A sign-in prompt, then back here (401); "This order belongs to another account" and a link home (403) | API-002#401, API-002#403 |
```
