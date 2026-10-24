# Stage 06 · API

| Slot | This stage |
| --- | --- |
| Inputs | The functional spec (SPEC), the schema (TBL), and the sitemap (SCR) when screens exist |
| Outputs | `openapi.yaml`, by default `api/openapi.yaml`: an OpenAPI contract in which each operation carries an API ID and the SPEC IDs it implements and lists every response it can return, each with an example, and which lists the API's error codes |
| Human view | A contract viewer such as Swagger UI, as set in `human` |
| Sync | Contract first: change the contract, then the code. The contract file is the source; a document generated from the code is for reference. The front end builds against a mock server made from the contract, contract tests check the back end against it, and test cases come from its responses |
| Human checkpoints | Contract review before implementation, response by response, and every breaking change |
| Trace IDs | API-001…, with a response written as `API-001#401` |

## Steps

1. Use OpenAPI 3.1 unless the project's generators and tools already support a newer version.
2. Write one operation per behaviour the screens or clients need, with an `operationId` for code and an `x-corthex` extension for the trace IDs.
3. Define request and response schemas from the schema (stage 05) and the glossary. Give each field the limits of the column it fills: length, range, format and allowed values (`maxLength`, `minimum`, `maximum`, `pattern`, `enum`). Contract tests try only the limits the contract states.
4. Define the error shape and the error codes once for the whole API (see Errors below), and the security rule of each operation.
5. Decide where errors end and successes begin, and record each decision (DEC): for example, whether a request that changes nothing succeeds, whether an ID that does not exist gets 404 and an ID in the wrong format 400, and whether a reached limit is an error or a success with a notice. Until a decision closes it, mark an open question, such as a token lifetime, with `Open:` in the description it concerns.
6. Write each operation's responses before any code, from the table below. Give every response at least one named example; the mock server, the front end and the tests use them.
7. Compare with the previous contract and list breaking changes: removed operations, fields, responses or error codes, changed types, new required inputs, changed meanings.
8. Hand the contract over: the front end works against the mock server, the back end against the contract tests (stage 11), and QA writes a test case for each response (stage 12). Guidance for the front end, including instructions for an AI, comes from the contract, the screen definitions and the design tokens, not from the back-end code.

## Responses

Every operation accounts for each response in this table: it lists the response, or names it under `x-corthex.omit` with the reason the operation cannot return it.

| Response | Needed when |
| --- | --- |
| 200, 201 or 204 | Always, for success |
| 400 or 422 | The server can reject the input. The project picks one of the two for validation errors and uses it in every operation |
| 401 | The operation needs a signed-in caller |
| 403 | Callers differ in what they may see or do |
| 404 | The path names a resource by ID |
| 409 | The request can clash with the current state, such as a duplicate or an outdated version |
| `default` | Always, for any other error, with the error shape |

Add 429 where the project limits request rates, and any other code a SPEC row needs.

## Errors

Every error response has one shape. By default it is Problem Details (RFC 9457), sent as `application/problem+json`, with the members `type`, `title`, `status`, `detail` and `instance` and two more: `code`, the error code, and `traceId`, the ID the server writes to its log for the request. `status` is always the HTTP status of the response. Many web frameworks produce this shape directly.

The error codes are listed once, under `components.x-corthex.errors`: for each code, its HTTP status, what it means, the message the user sees and what the client does. The `code` member allows only these codes, so the contract tests fail when the server sends another one. The back end returns these codes, the screens show their messages (stage 08), and test cases expect them (stage 12).

## Mock server and contract tests

These tools read the contract file in the repository. The ones named here are suggestions; the project may use others that do the same.

- **Mock server**, so the front end and QA can start before the back end: for example Prism, `prism mock api/openapi.yaml`. A request gets the success response. The header `Prefer: code=401` returns the 401 response, and `Prefer: code=422, example=card-declined` one named example of the 422 response. A request without credentials or with invalid input gets the documented 401 or validation response with its first example, so put a general example first.
- **Contract tests**, run in stage 11 against a development or staging server, never production: for example Schemathesis, `schemathesis run api/openapi.yaml --url <server>`. It generates requests from the contract and fails on status codes the contract does not list, responses that break their schema, invalid input or missing credentials the server accepts, and server errors. A mock server passes most of these checks by design, so only a real server proves the contract.
- **Traffic check**, between the front end and a real server: `prism proxy api/openapi.yaml <server>` reports requests and responses that break the contract.

## Checks

- Every operation has an API ID and at least one SPEC ID.
- Every SPEC row that needs the server has an operation.
- Every operation accounts for each response in the table, and every response has an example that matches its schema.
- Every error response uses the error shape, and every error code in an example is in the list with the same status.
- Every request field has the limits of its column.
- Security is defined for every operation, and every operation that needs a signed-in caller has a 401 response.
- The contract loads in the mock server and in the contract test tool.
- Breaking changes are listed and decided by the user before they ship.

## Output template

```yaml
paths:
  /orders:
    post:
      operationId: createOrder
      x-corthex:
        id: API-001
        spec: [SPEC-001]
        omit:
          "403": every signed-in customer may order
          "404": the path names no resource
          "409": a new order cannot clash with an existing one
      security:
        - bearerAuth: []
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/NewOrder"
      responses:
        "201":
          description: Order created
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Order"
              examples:
                created:
                  value: {id: ord_1, status: paid}
        "401":
          description: Not signed in
          content:
            application/problem+json:
              schema:
                $ref: "#/components/schemas/Problem"
              examples:
                no-token:
                  value: {title: Sign in to order, status: 401, code: unauthenticated, traceId: 0af7651916cd43dd}
        "422":
          description: Order rejected
          content:
            application/problem+json:
              schema:
                $ref: "#/components/schemas/Problem"
              examples:
                empty-cart:
                  value: {title: The cart is empty, status: 422, code: invalid_order, traceId: 00f067aa0ba902b7}
                card-declined:
                  value: {title: The card was declined, status: 422, code: payment_failed, traceId: 4bf92f3577b34da6}
        default:
          description: Unexpected error
          content:
            application/problem+json:
              schema:
                $ref: "#/components/schemas/Problem"
              examples:
                server-error:
                  value: {title: Something went wrong, status: 500, code: internal, traceId: 53995c3f42cd8ad8}
components:
  x-corthex:
    errors:
      unauthenticated: {status: 401, meaning: no valid sign-in, message: Sign in to continue, client: open sign-in and come back}
      forbidden: {status: 403, meaning: the caller may not do this, message: You cannot open this, client: explain and link home}
      not_found: {status: 404, meaning: no such item, message: This no longer exists, client: link to the list}
      payment_failed: {status: 422, meaning: the card was declined, message: Your card was declined. Try another card, client: keep the form and show the message by the card}
      invalid_order: {status: 422, meaning: the order is not valid, message: Check your cart, client: show the message by the field it names}
      internal: {status: 500, meaning: an unexpected server error, message: Something went wrong. Try again, client: offer a retry and show the trace ID}
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
  schemas:
    NewOrder:
      type: object
      required: [items]
      properties:
        items:
          type: array
          minItems: 1
          maxItems: 50
          items:
            type: object
            required: [sku, quantity]
            properties:
              sku: {type: string, minLength: 1, maxLength: 64}  # the column order_items.sku is VARCHAR(64)
              quantity: {type: integer, minimum: 1, maximum: 99}
    Order:
      type: object
      required: [id, status]
      properties:
        id: {type: string}
        status: {type: string, enum: [unpaid, paid, cancelled]}
    Problem:
      type: object
      required: [title, status, code, traceId]
      properties:
        type: {type: string, format: uri-reference}
        title: {type: string}
        status: {type: integer}
        detail: {type: string}
        instance: {type: string, format: uri-reference}
        code: {type: string, enum: [unauthenticated, forbidden, not_found, payment_failed, invalid_order, internal]}
        traceId: {type: string}
```
