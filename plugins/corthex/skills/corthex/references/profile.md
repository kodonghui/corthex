# Profile

The profile holds the values that differ from person to person. It lives on the user's machine, outside any repository:

- macOS and Linux: `~/.corthex/profile.json`
- Windows: `%USERPROFILE%\.corthex\profile.json`

Claude Code and Codex read the same file. The file never holds secrets.

## Fields

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `address_as` | string | `사용자님` when `language` is `ko`, otherwise unset | How to address the user |
| `language` | string | the language the user writes in | Language for replies and new documents, as a BCP 47 tag such as `ko` or `en` |
| `records.default` | string | unset | Where records go by default, such as `notion`, `git` or `none` |
| `records.hub` | string | unset | Link or path to the records hub, such as a Notion database or a folder |
| `records.study` | string | unset | Link or path to where study documents go, such as a Notion database or a folder. When unset, `corthex-study` uses `records.hub` |
| `ask_before` | array of strings | the list in the example | Kinds of actions to ask about first, in addition to anything that cannot be undone. A project's own valid `ask_before` replaces this list for that project |
| `nexus` | object | unset | Settings of the optional `corthex-nexus` plugin: `url`, the address of your own NEXUS server, and `push`, the projects that may be sent there |

Unknown fields are kept and ignored, so a newer version can add fields without breaking an older one.

## Example

The same file is in this skill's folder at `assets/profile.example.json`:

```json
{
  "address_as": "사용자님",
  "language": "ko",
  "records": { "default": "notion", "hub": "<link to your records database or folder>" },
  "ask_before": ["external messages", "deploys", "payments", "deletions", "publishing"]
}
```

## Creating the profile

1. Ask only for the values you cannot infer. Offer the defaults above.
2. Show the whole file and where it will be written.
3. Write it after the user agrees. Create the `.corthex` folder if it does not exist, and leave every other file in that folder alone.
