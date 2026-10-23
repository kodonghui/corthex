# Stage 06 · API

| Slot | This stage |
| --- | --- |
| Inputs | The functional spec (SPEC), the schema (TBL), and the sitemap (SCR) when screens exist |
| Outputs | `openapi.yaml`, by default `api/openapi.yaml`: an OpenAPI contract in which each operation carries an API ID and the SPEC IDs it implements |
| Human view | A contract viewer such as Swagger UI, as set in `human` |
| Sync | Contract first: change the contract, then the code. Generated code or contract tests check the code against the contract |
| Human checkpoints | Contract review before implementation, and every breaking change |
| Trace IDs | API-001… |

## Steps

1. Use OpenAPI 3.1 unless the project's generators and tools already support a newer version.
2. Write one operation per behaviour the screens or clients need, with an `operationId` for code and an `x-corthex` extension for the trace IDs.
3. Define request and response schemas from the schema and the glossary, one shared error schema, and the security rule of each operation.
4. Compare with the previous contract and list breaking changes: removed operations or fields, changed types, new required inputs, changed meanings.

## Checks

- Every operation has an API ID and at least one SPEC ID.
- Every SPEC row that needs the server has an operation.
- Error responses and security are defined for every operation.
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
      security:
        - bearerAuth: []
      responses:
        "201":
          description: Order created
        "422":
          description: Payment failed
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Error"
```
