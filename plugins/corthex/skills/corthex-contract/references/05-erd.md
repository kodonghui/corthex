# Stage 05 · ERD

| Slot | This stage |
| --- | --- |
| Inputs | The functional spec (SPEC) for the data each behaviour needs, the domain design's aggregate rules (CTX), and the glossary (TERM) for names |
| Outputs | `schema.sql`, by default `db/schema.sql`, with a TBL ID comment on each table, plus the migrations; optionally a Mermaid `erDiagram` in `docs/05-erd/` |
| Human view | An ERD tool, as set in `human`: by default ERD Editor for a new project; see "ERD Editor" below. A team that already uses another tool, such as ERD Cloud, keeps it unless the team decides to move |
| Sync | Compare the DDL in the repository with the tool's latest SQL export and name the export's date. Report the differences table by table and column by column, then apply them in the direction `truth` gives. If the AI cannot reach the tool, a person exports and imports the SQL, as step 5 in [SKILL.md](../SKILL.md) says |
| Human checkpoints | Schema freeze before the API contract is written, and every later breaking change |
| Trace IDs | TBL-001… |

## Steps

1. List the data each SPEC row reads or writes.
2. Group it into tables named with the glossary's words and one naming convention.
3. Write keys, foreign keys with their on-delete behaviour, unique rules and indexes for the reads the spec needs. Translate aggregate rules the database can enforce into unique, foreign-key or check constraints, and name each rule in a comment.
4. Write a migration for every change; never edit a migration that has been applied somewhere.
5. When the product calls an AI model (see the AI call entries in stage 04), add a table that records each call: when it was sent, the model and the prompt version, the token counts, the time to the first token and to the end, the result (success, failure or a reached limit) and the request's trace ID. Keep personal data and secrets out of it, and keep the prompt and the answer only when the product needs them. Record also why the model stopped (the provider's stop reason), the cached tokens read and written, the reasoning settings, such as effort or thinking, each tool call with its name, result, conversation ID and target ID and its arguments with personal data masked, and why a fallback answer was used. The same personal-data and secret exclusions apply to all these fields.

## Checks

- Every data need in the spec maps to a table and a column.
- Every table has a primary key and a TBL ID, and no table is unused.
- The migrations rebuild the schema from an empty database.
- The repository and the ERD tool's latest export agree, or their differences are listed with the export's date.

## ERD Editor

[ERD Editor](https://github.com/dineug/erd-editor) (MIT) keeps the diagram in a file in the repository and has an MCP server, so people and the AI edit the same diagram.

- Keep the diagram next to the DDL. For a new project, set the stage to `"human": "erd-editor"`, `"link": "db/schema.erd.json"`, `"source": "db/schema.sql"` and `"truth": "human"`; for an existing schema, start with the import check below.
- People open the file with the ERD Editor extension for VS Code, 4.0.0 or later, or its plugin for a JetBrains IDE or Obsidian, 1.0.0 or later, and share it through Git like any other file. Earlier releases speak an older protocol, and the current MCP server refuses every call that reaches them (`protocolMismatch`). Update the server and the extension or plugin together.
- Register the MCP server in the project folder. For Claude Code, run `claude mcp add --transport stdio erd-editor -- npx -y @dineug/erd-editor-mcp`, adding `--scope project` to share it with the team in `.mcp.json`. For Codex, run `codex mcp add erd-editor -- npx -y @dineug/erd-editor-mcp`. The server needs Node.js 22.12 or later.
- Change the diagram through the MCP tools, never by writing its JSON. Each edit's result names its mode. In `live` mode an editor whose workspace holds the file applies the edit, opening the file if it is not open yet, and VS Code keeps the change unsaved until it is saved, so call `erd_save` before you read the file, sync or commit. In `headless` mode the server writes the file itself.
- Set the diagram's database to the project's database. Column types are kept as written, not converted. Start each table's comment with its TBL ID; the DDL carries the comment.
- The tables have no place for some SQL, and an import skips it: among others, `CHECK` constraints, columns added by `ALTER TABLE … ADD COLUMN`, `CREATE TYPE`, `CREATE DOMAIN`, `CREATE EXTENSION`, sequence statements and MySQL's `ON UPDATE CURRENT_TIMESTAMP`. With SQLite, table comments, which carry the TBL IDs, do not survive an export and import. See the [import notes](https://docs.erd-editor.io/docs/guide/guides/file-import-export/#schema-sql).
- Statements that stand apart from the tables, such as `CREATE EXTENSION`, `CREATE SCHEMA`, `CREATE TYPE`, sequences, views and grants, go in the diagram's two scripts with `erd_set_ddl_script`: one `before` the tables and one `after` them, each up to 10,000 characters and written for the diagram's database. The DDL of the whole document from `erd_read` includes them; the DDL of chosen tables does not. See the [tools reference](https://docs.erd-editor.io/docs/mcp/tools/).
- Build the first diagram from an existing `schema.sql` with `erd_import_sql`. Add what the import skipped, columns to their tables with `erd_add_column` and other statements to the scripts, then read the whole diagram back with `erd_read` and `format: "sql"` and compare it with the original. Switch the stage to `truth: human` only when the comparison loses nothing the project needs. Otherwise keep `truth: source`: change the DDL first, then make the same change in the diagram with the edit tools. After the first import, change the diagram only with the edit tools, because an import, by default, replaces the diagram and its layout.
- To sync with `truth: human`, read the whole diagram as DDL with `erd_read` and `format: "sql"`, and refresh `schema.sql` from it, starting the file with the diagram's path and the refresh time. Keep in `schema.sql` only what neither the tables nor the scripts can hold, such as a `CHECK` constraint in a SQLite table, with a comment saying it is kept outside the diagram. Add a migration for the difference and report the changes table by table.

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
