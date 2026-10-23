# Stage 08 · Screen states

| Slot | This stage |
| --- | --- |
| Inputs | The sitemap (SCR), the functional spec (SPEC) and the API contract (API) |
| Outputs | One screen definition per screen in the stage's `source` folder, by default `docs/08-screens/SCR-001.md`: its purpose, the data it shows and the API it comes from, its states, its actions and its rules |
| Human view | Grayscale wireframes, as set in `human` |
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

## Steps

1. Write the screen's purpose in one sentence, from the flows that pass through it.
2. List the data it shows and the API operation each piece comes from.
3. List the actions, each with its result and its failure.
4. Describe each state: what the user sees and what they can do.

## Checks

- Every piece of data names its API operation.
- Every action has a result and a failure.
- Every applicable state is described; long text and narrow screens are considered.

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

| State | What the user sees and can do |
| --- | --- |
| SCR-002#loading | Placeholder rows; no actions |
| SCR-002#error | Message and a retry button |
| SCR-002#permission | "This order belongs to another account" and a link home |
```
