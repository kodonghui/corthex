# Stage 02 · PRD

| Slot | This stage |
| --- | --- |
| Inputs | Stage 01 contexts and glossary (CTX, TERM), and the product goals and constraints from the user |
| Outputs | `requirements.md`, by default `docs/02-prd/requirements.md`: one REQ ID per requirement in EARS wording, with its type (functional or non-functional), priority, source and context |
| Human view | By default a Notion database with one row per requirement, as set in `human`. See [notion-database.md](notion-database.md) |
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
3. Give each row its type (functional or non-functional), its context (CTX), its source (who asked, where and when) and a priority on the project's scale, such as Must, Should, Could.
4. Write each non-functional requirement so that a test can measure it. Give a performance target as a percentile with its load and the place it is measured, such as "within one second at the 95th percentile (P95) with 20 users at once, on the staging server".
5. List conflicts, duplicates and open questions separately for the user.

## Checks

- Each requirement uses one EARS shape and one "shall".
- Each requirement names its type, priority, context and source. List the ones without a priority: later checks on Must requirements cannot cover them.
- No two requirements say the same thing or contradict each other.
- Terms match the glossary.
- Each non-functional requirement says how it is measured, and each performance target names its percentile, its load and where it is measured.

## Scope freeze

Ask once what might be missing: compare the requirements with an independent list, such as similar services, regulations or stakeholders, and say which list you used. In a small project one short list is enough.

## Output template

```markdown
| ID | Requirement | Type | Priority | Context | Source | Status |
| --- | --- | --- | --- | --- | --- | --- |
| REQ-001 | When a customer places an order, the system shall send an order confirmation within one minute. | functional | Must | CTX-001 | Kickoff meeting, 2026-01-05 | active |
| REQ-002 | If a payment fails, then the system shall cancel the order and tell the customer why. | functional | Must | CTX-001 | Kickoff meeting, 2026-01-05 | active |
| REQ-003 | The system shall work in the latest two versions of the major desktop and mobile browsers. | non-functional | Must | none | Kickoff meeting, 2026-01-05 | active |
```
