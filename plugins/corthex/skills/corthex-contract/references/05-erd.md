# Stage 05 · ERD

| Slot | This stage |
| --- | --- |
| Inputs | The functional spec (SPEC) for the data each behaviour needs, and the glossary (TERM) for names |
| Outputs | `schema.sql`, by default `db/schema.sql`, with a TBL ID comment on each table, plus the migrations; optionally a Mermaid `erDiagram` in `docs/05-erd/` |
| Human view | An ERD tool such as ERD Cloud, as set in `human` |
| Sync | Compare the DDL in the repository with the tool's latest SQL export and name the export's date. Report the differences table by table and column by column, then apply them in the direction `truth` gives. If the AI cannot reach the tool, a person exports and imports the SQL; see "Human views the AI cannot reach" in the `corthex` skill's stage contract |
| Human checkpoints | Schema freeze before the API contract is written, and every later breaking change |
| Trace IDs | TBL-001… |

## Steps

1. List the data each SPEC row reads or writes.
2. Group it into tables named with the glossary's words and one naming convention.
3. Write keys, foreign keys with their on-delete behaviour, unique rules and indexes for the reads the spec needs.
4. Write a migration for every change; never edit a migration that has been applied somewhere.

## Checks

- Every data need in the spec maps to a table and a column.
- Every table has a primary key and a TBL ID, and no table is unused.
- The migrations rebuild the schema from an empty database.
- The repository and the ERD tool's latest export agree, or their differences are listed with the export's date.

## Output template

```sql
-- TBL-001 orders (CTX-001) ← SPEC-001, SPEC-002
CREATE TABLE orders (
  id          BIGINT PRIMARY KEY,
  customer_id BIGINT NOT NULL REFERENCES customers (id) ON DELETE RESTRICT,
  status      VARCHAR(20) NOT NULL,
  created_at  TIMESTAMP NOT NULL
);
```
