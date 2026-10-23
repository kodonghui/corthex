# Stage 05 · ERD

| Slot | This stage |
| --- | --- |
| Inputs | The functional spec (SPEC) for the data each behaviour needs, and the glossary (TERM) for names |
| Outputs | `schema.sql`, by default `db/schema.sql`, with a TBL ID comment on each table, plus the migrations; optionally a Mermaid `erDiagram` in `docs/05-erd/` |
| Human view | An ERD tool, as set in `human`. Suggest ERD Editor to a new project; see "ERD Editor" below. A team that already uses another tool, such as ERD Cloud, keeps it unless the team decides to move |
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

## ERD Editor

[ERD Editor](https://github.com/dineug/erd-editor) (MIT) keeps the diagram in a file in the repository and has an MCP server, so people and the AI edit the same diagram.

- Keep the diagram next to the DDL, and set the stage to `"human": "erd-editor"`, `"link": "db/schema.erd.json"`, `"source": "db/schema.sql"` and `"truth": "human"`.
- People open the file with the ERD Editor extension for VS Code, a JetBrains IDE or Obsidian, and share it through Git like any other file.
- Register the MCP server in the project folder. For Claude Code, run `claude mcp add --transport stdio erd-editor -- npx -y @dineug/erd-editor-mcp`, adding `--scope project` to share it with the team in `.mcp.json`. For Codex, run `codex mcp add erd-editor -- npx -y @dineug/erd-editor-mcp`. The server needs Node.js 22.12 or later.
- Change the diagram through the MCP tools, never by writing its JSON. When an editor has the file open, the change shows on its canvas at once; VS Code keeps it unsaved until someone saves it or the AI calls `erd_save`. Otherwise the server writes the file.
- Set the diagram's database to the project's database. Column types are kept as written, not converted. Start each table's comment with its TBL ID; the DDL carries the comment.
- To sync, read the diagram as DDL with `erd_read` and `format: "sql"`, refresh `schema.sql` from it as the `corthex` skill's stage contract says for `truth: human`, add a migration for the difference, and report the changes table by table.
- Build the first diagram from an existing `schema.sql` with `erd_import_sql`. After that, change it with the edit tools, because an import replaces the diagram and its layout.

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
