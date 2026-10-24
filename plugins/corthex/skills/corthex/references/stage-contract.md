# Stage contract

Every CORTHEX stage fills the same six slots. The slots make each stage's work traceable to the stage before it, and they separate what people look at from what the AI reads and writes.

| Slot | Meaning |
| --- | --- |
| Inputs | Outputs of earlier stages that this stage reads, with their trace IDs |
| Outputs | Text sources this stage writes in the product repository |
| Human view | Where people look at and edit the stage's work |
| Sync | How the human view and the text source are kept in line, and which side is the truth |
| Human checkpoints | Moments when the user fixes or approves the work before the next stage uses it |
| Trace IDs | IDs this stage creates and passes on |

The principle behind the split: the human view can change from team to team, but the text source the AI reads and writes stays in one place in the repository. Tools are joined to it through MCP servers or exports.

## Stages

| Key | Stage | Skill | Creates IDs | Default source |
| --- | --- | --- | --- | --- |
| `01-domain` | Domain discovery | `corthex-discover` | CTX, TERM | `docs/01-domain/` |
| `02-prd` | PRD | `corthex-define` | REQ | `docs/02-prd/requirements.md` |
| `03-user-flow` | User flow | `corthex-define` | FL | `docs/03-user-flow/` |
| `04-functional-spec` | Functional spec | `corthex-define` | SPEC | `docs/04-functional-spec/spec.md` |
| `05-erd` | ERD | `corthex-contract` | TBL | `db/schema.sql` |
| `06-api` | API | `corthex-contract` | API | `api/openapi.yaml` |
| `07-sitemap` | Sitemap | `corthex-screen` | SCR | `docs/07-sitemap/sitemap.yaml` |
| `08-screen-states` | Screen states | `corthex-screen` | screen states under SCR | `docs/08-screens/` |
| `09-mockup` | Mockup | `corthex-screen` | design tokens | `design/base.tokens.json` |
| `10-wbs` | WBS | `corthex-build` | TASK | `docs/10-wbs/wbs.md` |
| `11-development` | Development | `corthex-build` | none; links TASK and SPEC | the code and its tests |
| `12-qa` | QA | `corthex-build` | TC, BUG | `docs/12-qa/test-plan.md` |
| `13-presentation` | Presentation | `corthex-present` | SCENE | `docs/13-presentation/script.md` |
| `record` | Meetings, decisions, progress | `corthex-record` | DEC | the project's records location |

## Trace IDs

- Default format: a prefix, a hyphen and three digits, such as `REQ-001`.
- A project can set other prefixes, several prefixes for one kind (such as one per bounded context) and another number of digits in `.corthex/project.json` under `ids`, with these keys: `context`, `term`, `requirement`, `flow`, `spec`, `table`, `api`, `screen`, `task`, `test`, `bug`, `decision`, `scene`. See [project.md](project.md).
- Never reuse or renumber an ID. Mark a removed item as removed, with the date, and keep its ID.
- Each item names the IDs it comes from, such as `SPEC-014 ← REQ-003, FL-002`.
- A screen state or an API response is written after its ID with `#`: `SCR-002#empty`, `API-001#401`. Test cases name the responses and states they check.

## Source of truth

- `truth: source`: change the text source first, then update the human view.
- `truth: human`: people edit in the human view. Refresh the text copy from it and do not edit the copy directly. Start each copied file or item with where it came from and when: its link, the human view's last edit time if the tool shows one, and the refresh time.
- When the two sides differ, list the differences and ask before changing either side.
- When the copy is older than the human view's last edit, say so before you rely on it, and offer to refresh it.

## Translations

- A translation sits beside its original, with a language tag before the extension: `requirements.ko.md` beside `requirements.md`, or `spec.pt-BR.md` beside `spec.md`. The original is the source. Tools that read a folder source skip a translation that defines only its original's IDs, so they are not defined twice; a file with an ID of its own, such as `spec.ui.md`, is read like any other.
- Keep the original's IDs in the translation and change the original first. Where the two differ, the original holds.

## Default human views

When a project is registered, or a stage is set up for the first time, propose the human view in this table. Each one keeps the stage's text source in the repository, and the AI can reach it through an MCP server, a command-line tool or the files themselves. When the user or the team picks another tool, record the choice as a decision, with the user's words and the date, and say it in the stage's `note`. A team that already works in a tool keeps it unless the team decides to move.

| Stage | Default human view | How the AI reaches it | Default `truth` |
| --- | --- | --- | --- |
| 01 Domain discovery | An event storming board in Miro | Miro's MCP server | `source` once the last checkpoint is passed |
| 02 PRD | A Notion database, one row per requirement | Notion's MCP server | `human` in a team project, otherwise `source` |
| 03 User flow | A Notion database, one row per flow with its Mermaid diagram; a Miro board for a workshop | Notion's or Miro's MCP server | `source` |
| 04 Functional spec | A Notion database, one row per SPEC | Notion's MCP server | `human` in a team project, otherwise `source` |
| 05 ERD | ERD Editor, with the diagram in the repository | ERD Editor's MCP server | `human` |
| 06 API | Swagger UI, or another viewer of the contract file | The contract file | `source` |
| 07 Sitemap | A board, a list and slides, drawn from the YAML | The AI draws them from the file | `source` |
| 08 Screen states | Grayscale wireframes, drawn from the screen definitions | The AI draws them from the files | `source` |
| 09 Mockup | Figma or Claude Design | Figma's MCP server; Claude Design in Claude Code | `source` for the tokens |
| 10 WBS | GitHub Projects, or a Notion database | `gh project`, or Notion's MCP server | `human` |
| 11 Development | Pull requests | `gh` or the GitHub MCP server | `source` |
| 12 QA | The test plan, the test report and the bug tracker | The files; `gh` for issues | `source` |
| 13 Presentation | Slides built from the scene table | The AI builds them | `source` |

Each stage's reference file says how to work with its default tool.

## Human views the AI cannot reach

At the start of a stage, check whether this session can reach the human view through an MCP server, a connector or an API. Some tools offer none and only import and export files. For such a tool:

- The text copy is only as fresh as the last export a person made. Ask for a new export at the start of the stage and before each human checkpoint, and give the date of the copy you used when you report.
- With `truth: human`, give each change you propose as a list a person can apply in the tool, item by item, or as a file the tool can import. Until a newer export shows the change, report it as proposed, not as done.
- With `truth: source`, a change is done once it is in the source. Give the person the file to import and the steps to import it, and report the tool as not yet updated until a newer export shows the change.
- When a team is still choosing a tool, say which candidates keep their file in the repository or have an MCP server. The choice of a team's tool is the team's.
