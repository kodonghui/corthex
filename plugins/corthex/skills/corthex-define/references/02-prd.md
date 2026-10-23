# Stage 02 · PRD

| Slot | This stage |
| --- | --- |
| Inputs | Stage 01 contexts and glossary (CTX, TERM), and the product goals and constraints from the user |
| Outputs | `requirements.md`, by default `docs/02-prd/requirements.md`: one REQ ID per requirement in EARS wording, with its priority, source and context |
| Human view | Often a shared database such as Notion, as set in `human` |
| Sync | In a team project the shared database is often the truth (`truth: human`), and the text is a refreshed copy. Otherwise edit the text and update the view |
| Human checkpoints | Scope freeze (what is in this release), then version freeze |
| Trace IDs | REQ-001… |

## EARS wording

EARS (Easy Approach to Requirements Syntax) keeps each requirement to one of five shapes:

| Shape | Pattern |
| --- | --- |
| Ubiquitous | The <system> shall <response>. |
| Event-driven | When <trigger>, the <system> shall <response>. |
| State-driven | While <state>, the <system> shall <response>. |
| Unwanted behaviour | If <condition>, then the <system> shall <response>. |
| Optional feature | Where <feature is included>, the <system> shall <response>. |

Write requirements in the project's language; keep the shape.

## Steps

1. Read the contexts and the glossary. Use the glossary's words.
2. Write one requirement per row in one EARS shape. Split a row that needs "and" to describe two behaviours.
3. Give each row its context (CTX), its source (who asked, where and when) and a priority on the project's scale, such as Must, Should, Could.
4. List conflicts, duplicates and open questions separately for the user.

## Checks

- Each requirement uses one EARS shape and one "shall".
- Each requirement names its context and its source.
- No two requirements say the same thing or contradict each other.
- Terms match the glossary.

## Output template

```markdown
| ID | Requirement | Priority | Context | Source | Status |
| --- | --- | --- | --- | --- | --- |
| REQ-001 | When a customer places an order, the system shall send an order confirmation within one minute. | Must | CTX-001 | Kickoff meeting, 2026-01-05 | active |
| REQ-002 | If a payment fails, then the system shall cancel the order and tell the customer why. | Must | CTX-001 | Kickoff meeting, 2026-01-05 | active |
```
