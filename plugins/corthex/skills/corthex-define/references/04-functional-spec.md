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
2. For every input, write the exceptions: empty, invalid, too long, duplicate, not allowed, failed on the server. Then go through the kinds of cases below and write what the behaviour does in each one that applies.
3. Write acceptance criteria as Given, When, Then.
4. Report behaviour that no requirement asks for; it is either a missing requirement or scope creep.
5. For a behaviour that calls an AI model, write its AI call entry (see AI calls below).

## Kinds of cases

Stages 06, 08 and 12 use the same kinds, so that every case written here gets a response, a screen state and a test.

| Kind | What the spec writes |
| --- | --- |
| Access | Who may do it, and what every other caller gets, such as someone signed out or another user |
| Input | The limits of each input, and what a value outside them gets |
| Target | What happens when the item does not exist, its ID is malformed or it was deleted |
| State changes | The changes each state allows, what a change it does not allow gets, and what the same state again does |
| Repeats | That a repeated request, such as after a lost response or a double click, leaves one result |
| Concurrency | Which change wins when two arrive at once, or that the second is refused |
| Limits | The request, use and cost limits, and what a refused request does and does not do |
| Outside services | What happens when a service it calls fails, is slow or has no key |
| Data exposure | What the result must never carry, such as personal data or internal details |
| Empty and streamed answers | What an empty result is, and what an interrupted stream leaves behind |
| Screen states | What the user must be told in each outcome; stage 08 decides how it looks |
| AI answers | The AI call entry, with the requests in scope, out of scope and forbidden. In a conversation, also what happens when more messages from the same person arrive while it answers, such as waiting and combining them, starting again before any write, or adding to the answer, with each write run once; and the other ways in, such as a photo with text, voice, or a button that sends the message to a human inbox instead of the AI |

## Checks

- Each SPEC row links at least one REQ, and each functional Must REQ has at least one SPEC row. Non-functional requirements are checked in QA (stage 12) instead.
- Each row has acceptance criteria and its exceptions, and its exceptions cover each kind of case that applies to it.
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
| Tools | The tools the model may call, as reads and writes. Before each write, such as a refund, a change or a message sent, what the server checks in code: who the user is, that the target is theirs, that the evidence matches the records, the amount and count limits, and the user's confirmation of what, on which item and how much |
| Untrusted input | Attachments, photos, voice, tool results and retrieved text, which reach the model as data with their source, never as instructions. A turn that carries them runs a write only after those checks. Each model call holds at most two of these: untrusted input, sensitive data, and a change of state or an outside message |
| Failure | What happens when the model fails, is too slow, the server has no key for it or a usage limit is reached, and what the user sees |
| Human decision | Where a person accepts or rejects the result before it counts |

Stage 05 records each call, stage 06 lists the failures as responses, and stage 12 tests questions inside and outside the behaviour's scope.

## Output template

```markdown
| ID | Behaviour | From | Preconditions | Main behaviour | Exceptions | Acceptance criteria | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| SPEC-001 | Place order | REQ-001, FL-001 | Signed in, cart not empty | Creates the order and sends a confirmation | Payment fails → cancel and explain (REQ-002) | Given a full cart, when the customer confirms, then an order exists and a confirmation is sent within one minute | active |
```
