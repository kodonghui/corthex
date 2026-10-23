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

## Source of truth

- `truth: source`: change the text source first, then update the human view.
- `truth: human`: people edit in the human view. Refresh the text copy from it and do not edit the copy directly. Start each copied file or item with where it came from and when: its link, the human view's last edit time if the tool shows one, and the refresh time.
- When the two sides differ, list the differences and ask before changing either side.
- When the copy is older than the human view's last edit, say so before you rely on it, and offer to refresh it.
