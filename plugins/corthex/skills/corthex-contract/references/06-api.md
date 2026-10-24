# Stage 06 · API

| Slot | This stage |
| --- | --- |
| Inputs | The functional spec (SPEC), the schema (TBL), and the sitemap (SCR) when screens exist |
| Outputs | `openapi.yaml`, by default `api/openapi.yaml`: an OpenAPI contract in which each operation carries an API ID and the SPEC IDs it implements, and lists every response it can return, each with an example |
| Human view | A contract viewer such as Swagger UI, as set in `human` |
| Sync | Contract first: change the contract, then the code. The front end builds against a mock server made from the contract, contract tests check the back end against it, and test cases come from its responses |
| Human checkpoints | Contract review before implementation, response by response, and every breaking change |
| Trace IDs | API-001…, with a response written as `API-001#401` |

## Steps

1. Use OpenAPI 3.1 unless the project's generators and tools already support a newer version.
2. Write one operation per behaviour the screens or clients need, with an `operationId` for code and an `x-corthex` extension for the trace IDs.
3. Define request and response schemas from the schema and the glossary, one shared error schema, and the security rule of each operation.
4. Write each operation's responses before any code, from the table below. Give every response at least one named example; the mock server, the front end and the tests use them.
5. Compare with the previous contract and list breaking changes: removed operations, fields or responses, changed types, new required inputs, changed meanings.
6. Hand the contract over: the front end works against the mock server, the back end against the contract tests (stage 11), and QA writes a test case for each response (stage 12).

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
| `default` | Always, for any other error, with the shared error schema |

Add 429 where the project limits request rates, and any other code a SPEC row needs.

## Mock server and contract tests

These tools read the contract file in the repository. The ones named here are suggestions; the project may use others that do the same.

- **Mock server**, so the front end and QA can start before the back end: for example Prism, `prism mock api/openapi.yaml`. A request gets the success response. The header `Prefer: code=401` returns the 401 response, and `Prefer: code=422, example=card-declined` one named example of the 422 response. A request without credentials or with invalid input gets the documented 401 or validation response.
- **Contract tests**, run in stage 11 against a development or staging server, never production: for example Schemathesis, `schemathesis run api/openapi.yaml --url <server>`. It generates requests from the contract and fails on status codes the contract does not list, responses that break their schema, invalid input or missing credentials the server accepts, and server errors. A mock server passes most of these checks by design, so only a real server proves the contract.
- **Traffic check**, between the front end and a real server: `prism proxy api/openapi.yaml <server>` reports requests and responses that break the contract.

## Checks

- Every operation has an API ID and at least one SPEC ID.
- Every SPEC row that needs the server has an operation.
- Every operation accounts for each response in the table, and every response has an example that matches its schema.
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
            application/json:
              schema:
                $ref: "#/components/schemas/Error"
              examples:
                no-token:
                  value: {code: unauthenticated, message: Sign in to order}
        "422":
          description: Order rejected
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Error"
              examples:
                card-declined:
                  value: {code: payment_failed, message: The card was declined}
                empty-cart:
                  value: {code: invalid_order, message: The cart is empty}
        default:
          description: Unexpected error
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Error"
              examples:
                server-error:
                  value: {code: internal, message: Something went wrong}
```
