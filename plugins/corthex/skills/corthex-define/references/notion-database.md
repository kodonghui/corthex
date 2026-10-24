# Notion database

How stages 02 to 04 keep a Notion database and their text source in line. The stage's `truth` says which side wins.

## Connect

Notion's hosted MCP server lets the AI read and write what the signed-in person can open in one workspace.

- Connect it once per host. In Claude Code: `claude mcp add --transport http notion https://mcp.notion.com/mcp`, then run `/mcp` and sign in; add `--scope project` to share the server with the team in `.mcp.json`. In Codex: `codex mcp add notion --url https://mcp.notion.com/mcp`, then `codex mcp login notion`.
- Sign-in uses OAuth, and only members of the workspace can connect, not guests. The server acts as the signed-in person, so what the AI writes shows that person's name. Start the AI's comments with "AI:".
- Some tools depend on the workspace's plan, and `notion-get-tool-access` says what this one allows. Reading rows through a saved view works on every plan, SQL queries are metered below the Business plan, and resolving a discussion needs Business or Enterprise.

## Set up the database

- One database per stage, one row per item. The title holds the item's trace ID, alone or followed by a short name, such as "FL-001 Place an order".
- One property per column of the stage's output template, with the same names, such as Type, Priority and Status as selects. Add a `Last edited time` property, so each row shows when it last changed.
- For stage 03, each row's page holds the flow's Mermaid code, as Diagrams in [03-user-flow.md](03-user-flow.md) says.
- Put the database's link in the stage's `link`. Ask before creating a database in a shared workspace.
- Never renumber or delete a row. Mark a removed item as removed in its Status, with the date, and keep its ID.
- A database in another language than the source is a translation: it keeps the source's IDs, and the original holds where the two differ.

## Database to source

With `truth: human`, people edit the database and the repository holds a read-only copy.

1. Fetch the database to find its data source and its properties.
2. Read every row through a saved view, page by page. If the plan stops the queries, say how many rows you read and ask a person for a CSV export of the database to finish from.
3. Write the copy in the stage's output template, sorted by ID. Start it with the database's link, the newest `Last edited time` among its rows, the refresh time and a line saying the copy is read-only.
4. Report what changed since the last copy, item by item: added, changed with the properties that changed, and removed. A row that went away is marked removed in the copy, with the date; its ID is never reused.
5. List the rows without an ID, or with an ID used twice, and propose the fix. Change the database only after the user agrees.

## Source to database

With `truth: source`, the text changes first and the database follows.

1. Read the database first. If people changed rows since the last sync, list the differences and ask before you overwrite them.
2. Create a row for each new item, with the data source as the parent, and update the properties that changed. Mark removed items as removed; never delete a row.
3. Read the rows back and compare them with the source. Report what you changed, by ID.

## Comments

People review the stage by commenting on its rows.

- Before each checkpoint, read the open discussions on the rows, including those on a block or a piece of text. In a large database, start with the rows edited since the last sync and the rows the user names.
- Answer each discussion in its thread. Carry the answer into the source, or with `truth: human` into a change people apply, and say in the thread where it went, such as "AI: changed in REQ-003 (commit abc1234)".
- A comment is the commenter's words, with where and when they wrote it: a request, a question or an answer. It is approval only when it says so; an edit, a reaction or a resolved thread is not.
- Resolve a discussion only when its change is in. When the plan does not let the AI resolve discussions, list the ones a person can resolve.
