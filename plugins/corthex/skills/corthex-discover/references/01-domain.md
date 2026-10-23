# Stage 01 · Domain discovery

| Slot | This stage |
| --- | --- |
| Inputs | The product idea, interview and meeting notes, existing documents, and the workshop board as an export or photos |
| Outputs | `contexts.md` (bounded contexts with CTX IDs) and `glossary.md` (terms with TERM IDs) in the stage's `source` folder, by default `docs/01-domain/` |
| Human view | The workshop board, such as a Miro board, as set in `human` |
| Sync | Board to text after each workshop. The default `truth` is `source`: the board is a working surface, and the text is what later stages read |
| Human checkpoints | The user agrees on the context boundaries and on the glossary |
| Trace IDs | CTX-001…, TERM-001… |

## Steps

1. List the sources you read and where each one came from.
2. Group the domain events by the part of the business they belong to. Each group is a candidate bounded context: give it a CTX ID, a one-line purpose, and its events, commands, policies and actors.
3. Put every noun that matters into the glossary, with its definition, its context and the words to avoid.
4. Write the open questions under each context. Do not answer them yourself.

## Checks

- Every event belongs to exactly one context.
- A term that means different things in two contexts is listed for each context, with the difference stated.
- Screens, fields and other requirement-level details are not fixed here. Note them for stage 02.

## Output template

`contexts.md`:

```markdown
## CTX-001 Ordering

Purpose: customers place and cancel orders.

- Events: Order placed, Order cancelled
- Commands: Place order, Cancel order
- Policies: When a payment fails, cancel the order
- Actors: Customer, Store staff
- Open questions: Can staff cancel a paid order?
```

`glossary.md`:

```markdown
| ID | Term | Definition | Context | Avoid |
| --- | --- | --- | --- | --- |
| TERM-001 | Order | A customer's request to buy items, from placement to delivery | CTX-001 | purchase, booking |
```
