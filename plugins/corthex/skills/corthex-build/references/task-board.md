# Task board

How stage 10 keeps the tasks on a board and the WBS file in line. With `truth: human`, the board leads and `wbs.md` is a refreshed list.

## GitHub Projects

- Each TASK is an issue in the product repository, titled with its ID first, such as "TASK-001 Create order endpoint". Its body names the SPEC, API and screen IDs it comes from and its done condition, so the links survive outside the board.
- The project's fields hold the rest: Status (Todo, In progress, Done), the assignee as the owner, Estimate as a number and Depends on as a list of TASK IDs.
- The AI uses `gh`, whose token needs the `project` scope: `gh auth refresh -s project`. The GitHub MCP server can do the same where its `projects` toolset is turned on; it is not on by default.
- List the issues you are about to create, and ask before you create many at once or assign people, since assignees and watchers are notified.

| To | Command |
| --- | --- |
| Find the field and option IDs | `gh project field-list <number> --owner <owner> --format json` |
| Find the project's ID | `gh project view <number> --owner <owner> --format json` |
| Add an issue to the project | `gh project item-add <number> --owner <owner> --url <issue URL> --format json`, which returns the item's ID |
| Set one field of an item | `gh project item-edit --id <item> --project-id <project> --field-id <field>` with `--single-select-option-id`, `--number`, `--text` or `--date` |
| Read the board | `gh project item-list <number> --owner <owner> --format json --limit 1000` |

`item-edit` sets one field per call.

## Notion database

- One row per TASK, with the template's columns as properties and Status as a select, and a board view grouped by Status.
- Connect Notion's MCP server once per host. In Claude Code: `claude mcp add --transport http notion https://mcp.notion.com/mcp`, then run `/mcp` and sign in. In Codex: `codex mcp add notion --url https://mcp.notion.com/mcp`, then `codex mcp login notion`.
- Never renumber or delete a row; mark a removed task as removed in its Status, with the date.

## Board and file

- With `truth: human`, refresh `wbs.md` from the board at each checkpoint: one row per task in the template's format, sorted by ID, starting with the board's link and the refresh time.
- A task is done only when its done condition is met; for a task that touches an API operation, when every response the operation lists has a passing test. A card moved to Done by hand is a claim to check, not a result.
- With `truth: source`, change `wbs.md` first, then the board, and report the board as updated only after you have read it back.
