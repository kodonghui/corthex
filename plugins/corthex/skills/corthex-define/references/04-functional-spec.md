# Stage 04 · Functional spec

| Slot | This stage |
| --- | --- |
| Inputs | Requirements (REQ) and user flows (FL); the glossary (TERM) for names |
| Outputs | `spec.md`, by default `docs/04-functional-spec/spec.md`: one SPEC row per behaviour, with its REQ and FL links, preconditions, main behaviour, exceptions and acceptance criteria |
| Human view | By default a Notion database with one row per SPEC, as set in `human`. See [notion-database.md](notion-database.md) |
| Sync | When the shared database is the truth, the repository copy is read-only. Refresh it at each checkpoint and before a later stage reads it, and note the refresh time |
| Human checkpoints | Spec freeze for the release. A later change to a frozen row needs the user's decision |
| Trace IDs | SPEC-001… |

## Steps

1. Walk each flow step by step and write the behaviour the system needs at each step.
2. For every input, write the exceptions: empty, invalid, too long, duplicate, not allowed, failed on the server.
3. Write acceptance criteria as Given, When, Then.
4. Report behaviour that no requirement asks for; it is either a missing requirement or scope creep.
5. For a behaviour that calls an AI model, write its AI call entry (see AI calls below).

## Checks

- Each SPEC row links at least one REQ, and each functional Must REQ has at least one SPEC row. Non-functional requirements are checked in QA (stage 12) instead.
- Each row has acceptance criteria and its exceptions.
- Names match the glossary.
- Every behaviour that calls an AI model has an AI call entry.

## AI calls

A behaviour that calls an AI model gets an AI call entry, below the table or in a section of its own, named after its SPEC row:

| Field | What it says |
| --- | --- |
| Input | What the server sends to the model, and from which data |
| Not sent | Data that must never reach the model, such as personal data, secrets or answer keys |
| Output | The format the model must return, such as a JSON schema |
| Checked by the server | What the server checks before it uses the output, such as that every source the answer cites exists |
| Failure | What happens when the model fails, is too slow or a usage limit is reached, and what the user sees |
| Human decision | Where a person accepts or rejects the result before it counts |

Stage 05 records each call, stage 06 lists the failures as responses, and stage 12 tests questions inside and outside the behaviour's scope.

## Output template

```markdown
| ID | Behaviour | From | Preconditions | Main behaviour | Exceptions | Acceptance criteria | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SPEC-001 | Place order | REQ-001, FL-001 | Signed in, cart not empty | Creates the order and sends a confirmation | Payment fails → cancel and explain (REQ-002) | Given a full cart, when the customer confirms, then an order exists and a confirmation is sent within one minute | active |
```
