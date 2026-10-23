# Stage 04 · Functional spec

| Slot | This stage |
| --- | --- |
| Inputs | Requirements (REQ) and user flows (FL); the glossary (TERM) for names |
| Outputs | `spec.md`, by default `docs/04-functional-spec/spec.md`: one SPEC row per behaviour, with its REQ and FL links, preconditions, main behaviour, exceptions and acceptance criteria |
| Human view | Usually a shared database such as Notion, as set in `human` |
| Sync | When the shared database is the truth, the repository copy is read-only. Refresh it and note the refresh time |
| Human checkpoints | Spec freeze for the release. A later change to a frozen row needs the user's decision |
| Trace IDs | SPEC-001… |

## Steps

1. Walk each flow step by step and write the behaviour the system needs at each step.
2. For every input, write the exceptions: empty, invalid, too long, duplicate, not allowed, failed on the server.
3. Write acceptance criteria as Given, When, Then.
4. Report behaviour that no requirement asks for; it is either a missing requirement or scope creep.

## Checks

- Each SPEC row links at least one REQ, and each Must REQ has at least one SPEC row.
- Each row has acceptance criteria and its exceptions.
- Names match the glossary.

## Output template

```markdown
| ID | Behaviour | From | Preconditions | Main behaviour | Exceptions | Acceptance criteria | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SPEC-001 | Place order | REQ-001, FL-001 | Signed in, cart not empty | Creates the order and sends a confirmation | Payment fails → cancel and explain (REQ-002) | Given a full cart, when the customer confirms, then an order exists and a confirmation is sent within one minute | active |
```
