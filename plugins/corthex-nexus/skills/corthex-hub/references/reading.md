# What the hub reads and checks

`hub.py` reads each project's stage sources as plain text. It does not run a project's code, and it does not need the tools of the human views.

## Stages and files

- A stage is read when it has a text source: its `source` in `.corthex/project.json`, or the default path of the stage contract when the stage has no entry. A stage with `skip: true`, or with an entry but no `source` (even an empty `{}`), is not read.
- `09-mockup` and `11-development` are never read for IDs, because their sources are design tokens and code. Their settings still show on the page.
- A source is a file or a folder. Folders are read with their subfolders.
- In a folder, a file whose name ends in a language tag, such as `spec.ko.md`, `spec.pt-BR.md` or `spec.zh-Hans.md`, is a translation when the same folder holds the name without the tag, `spec.md`, and that file defines all of its IDs. Only the original is read, so the IDs are not defined twice, and the translation is only counted, like files of other formats. A file with an ID of its own is read like any other: one that only looks like a translation, such as `spec.ui.md` for the screens, or a translation that is ahead of its original, whose shared IDs then show as duplicates. A translation without its original is read, and so is one that a stage's `source` names on its own.
- These files are read: `.md`, `.markdown`, `.mdx`, `.yaml`, `.yml`, `.json`, `.sql`, `.csv`, `.tsv`, `.txt`, `.mmd`, `.mermaid`, `.feature`, `.rst` and `.adoc`. Other files are only counted.
- These are skipped: hidden files and folders, `node_modules`, `__pycache__` and `venv`, files over 1 MB, files after the first 400 of a stage, files whose names look like secrets or that sit in a folder whose name does (such as `secrets.yaml`, `api-key.txt`, `*.pem` or anything under `credentials/`), also when a link leads to them, and links that lead outside the repository. The stage's `files-skipped` note says how many and why.

## Trace IDs

An ID is a prefix, a hyphen and one to six digits, not inside a longer word: `REQ-001`, `AUTH-012`. The prefixes come from `ids` in `.corthex/project.json`, or else the defaults: `CTX`, `TERM`, `REQ`, `FL`, `SPEC`, `TBL`, `API`, `SCR`, `TASK`, `TC`, `BUG`, `DEC` and `SCENE`.

An ID is defined only in the stage that creates its kind, as the stage contract says: `REQ` in `02-prd`, `FL` in `03-user-flow` and so on. Anywhere else it is a mention. A mention inside a defined item links the two items, and a link counts in both directions.

`08-screen-states` creates no new items. A screen ID there attaches the file to the screen as its definition, and a suffix such as `SCR-002#loading` adds a state to the screen.

## Forms that define items

| Form | Defines | Title | Links from the item |
| --- | --- | --- | --- |
| A Markdown file named by an ID, such as `REQ-023.md` or `REQ-023 Login.md`, or with `id: REQ-023` in its front matter | that ID | front matter `title` or `name`, else the first `#` heading without the ID | every other ID in the file |
| A Markdown heading that starts with an ID, such as `## CTX-001 Ordering` | that ID | the rest of the heading | IDs under the heading, up to the next heading of the same or a higher level |
| A Markdown table with an ID column | the ID in each row | the first title column, else the first other cell with words | the other IDs in the row |
| A Markdown table row whose first cell is an ID, in a table without an ID column | nothing | | the other IDs in the row |
| A YAML mapping with `id: SCR-001`, in any place among its keys | that ID | its `title` or `name` | the other IDs in the mapping; a nested mapping with its own `id` records this one as its `parent` |
| An OpenAPI operation with `x-corthex: { id: API-001 }`, in YAML or JSON | that ID | the method and the path, such as `POST /orders` | the other IDs in the `x-corthex` block, such as `spec: [SPEC-001]` |
| An SQL table comment that starts with an ID: a `--` comment such as `-- TBL-001 orders ← SPEC-001` before `CREATE TABLE`, or the comment the database keeps with the table, in the forms ERD Editor writes: `COMMENT 'TBL-001 …'` after the columns (MySQL, MariaDB, Snowflake, Databricks), `COMMENT ON TABLE orders IS 'TBL-001 …'` (PostgreSQL, Oracle) or an `MS_Description` property from `sp_addextendedproperty` (SQL Server) | that ID | the first words after the ID, else the table's name | IDs in the statements about that table: its `CREATE TABLE` with the column comments, `ALTER TABLE`, `CREATE INDEX … ON` and the comments on its columns. Other lines link from the ID defined last above them |
| A CSV or TSV file with an ID column | the ID in each row; a quoted cell may run over several lines, and the row's place is the line it starts on | as for tables | the other IDs in the row |

Any other text only mentions IDs. A file named by an ID links its mentions from that ID.

- **ID columns** are headed `ID`, `Key`, `아이디`, `번호` or `키`, or end in ` ID`.
- **Title columns** are headed `Title`, `Name`, `Requirement`, `Behaviour`, `Task`, `Case`, `Term`, `Message`, `Decision`, `Summary` or `Item`, or the Korean `제목`, `이름`, `항목`, `요구사항`, `기능명`, `화면명`, `용어`, `작업`, `케이스`, `장면`, `메시지` or `결정`. `Flow`, `Feature` and `내용` count when no other title column is there.
- **Fields** come from columns, front matter keys or two-column rows with these names: `Status`, `State` or `상태`; `Type`, `Category`, `유형`, `구분` or `종류`; `Priority`, `우선순위` or `중요도`; `Link`, `URL`, `Notion` or `링크`.
- **Copy time**: front matter `exported_at`, `refreshed_at`, `copied_at` or `synced_at` shows on the page as the time of the text copy.
- **Deleted text**: struck-through Markdown, `~~…~~`, is ignored, as in exports from Notion.
- **YAML comments**: text after ` #` is not part of a value, so `- id: SCR-001 # Home` defines `SCR-001`.
- **SQL**: a statement ends at `;`, at a `GO` line (SQL Server, also with a count such as `GO 2`) or at a `/` line (Oracle). A comment inside a column list, such as a column's comment in SQLite, and an ID in any other string only mention IDs, and `--` inside a string is not a comment.
- **Backslashes in SQL strings**: MySQL, MariaDB, Snowflake and Databricks read a backslash in a string as an escape, so `\'` is a quote there, while PostgreSQL (except in `E'…'`), Oracle, SQL Server and SQLite read it as a character. A file with `\'` in it is read the way that keeps its strings from running on over the code after them.
- **Schemas**: tables of the same name in different schemas, such as `sales.orders` and `archive.orders`, are told apart, and so are `orders` and `archive.orders`. A name whose schema matches no table the file creates, such as `ALTER TABLE orders` or a SQL Server property for `'schema', 'dbo'`, means the table of that name when the file creates only one, and no table when it creates more.
- **Listings**: a file named `index`, `README`, `list` or `목록`, or one whose name starts with `_`, only fills in what the items' own files leave out. It never counts as a second definition.
- **Removed items**: an item whose status says removed, deleted, dropped, cancelled, deprecated or obsolete (or `삭제`, `폐기`, `제외`, `취소`) is left out of the link checks: it is not checked, and a link to it does not count.

## Checks

| Rule | Level | Meaning |
| --- | --- | --- |
| `duplicate-id` | error | The ID is defined in more than one place. |
| `unknown-ref` | warn | The ID is mentioned but not defined, although the stage that creates its kind was read. |
| `missing-upstream` | warn | The item names none of the items it comes from, other than removed ones: `FL` and `SPEC` name a `REQ`; `TBL`, `API` and `TASK` a `SPEC`; `TC` a `REQ`, `FL` or `SPEC`; `BUG` a `TC`, `SCR` or `SPEC`. Checked only when the project has items of those kinds. |
| `req-without-spec` | warn | A Must requirement (`Must`, `required`, `P0` or `필수`) that is not non-functional has no `SPEC` linked to it that `04-functional-spec` defines and that is not removed. Checked when that stage was read. |
| `req-without-priority` | info | Requirements have no priority, while others have one. |
| `screen-not-in-sitemap` | warn | A screen has a file in `08-screen-states` but is not in the sitemap. |
| `screen-without-states` | info | Screens in the sitemap have no file in `08-screen-states` yet. |
| `id-format` | info | IDs have another number of digits than `ids` sets. |
| `id-config` | warn | One prefix is set for two kinds. It counts as the first. |
| `source-missing` | warn | A source set in `.corthex/project.json` does not exist. |
| `source-invalid` | error | A source is not a relative path with forward slashes. |
| `source-outside` | error | A source leads outside its repository. |
| `unknown-alias` | error | A source names a repository that is not in `repos`. |
| `no-checkout` | warn | The source's repository has no local checkout in `~/.corthex/projects.json`. |
| `files-skipped` | info | Some files of the stage were not read, and why. |
| `truncated` | warn | The snapshot was cut to stay under its size limit. |
| `review` | any | A finding recorded with `hub.py status --check`. |

The checks find structure, not meaning. Two items can link correctly and still contradict each other; that takes a review, recorded as a `review` finding.
