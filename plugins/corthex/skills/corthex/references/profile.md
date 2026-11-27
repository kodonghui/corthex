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
| `checkpoints` | object | unset | Who answers each stage's human checkpoint: `user`, the stage keys that the user answers in person; `delegate`, who answers the others; and `decision`, the record of the user's own words that set this. Unset, or in any other form, the user answers every checkpoint. See Delegating checkpoints below |
| `ask_before` | array of strings | the list in the example | Kinds of actions to ask about first, in addition to anything that cannot be undone. A project's own valid `ask_before` replaces this list for that project |
| `nexus` | object | unset | Settings of the optional `corthex-nexus` plugin: `url`, the address of your own NEXUS server, and `push`, the projects that may be sent there. With a `url`, NEXUS is the default human view of the projects on it, and the entry skill asks once for each new project whether to put it there. The service token stays in environment variables |

Unknown fields are kept and ignored, so a newer version can add fields without breaking an older one.

Aside's agent may sign in to the sites a task needs, and sign up for the accounts it needs, through Aside Vault without asking first, as [computer-and-web.md](computer-and-web.md) says. Add `sign-ins` or `sign-ups` to `ask_before` to be asked first instead.

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

## Delegating checkpoints

By default the user answers every stage's checkpoint. The user can hand the checkpoints of some stages to a delegate, a person or an agent that they trust with them:

```json
"checkpoints": {
  "user": ["01-domain", "09-mockup"],
  "delegate": { "role": "the delegate", "reach": "<how a session asks them>" },
  "decision": "<link or ID of the record with your words>"
}
```

- `user` holds stage keys from [stage-contract.md](stage-contract.md): the stages whose checkpoints the user answers in person. The delegate answers every stage it leaves out, so it lists each stage that the user keeps.
- `delegate.role` is the word that records use for the delegate, never a personal name in a repository. `reach` is optional and says, in the user's words, how a session asks them.
- `decision` points to the user's own words, recorded as a decision with the `corthex-record` skill before this is written. Without it the setting does not count.
- The setting counts only whole. Without `user`, `delegate.role` or `decision`, or with an entry in `user` that is not a stage key, the user answers every checkpoint, and the session says what is wrong with the setting.
- Stage 12's checkpoint is the go/no-go at the release gate, which no delegation covers: the user answers it whether `user` lists `12-qa` or not. The rest of what a delegation never covers is in the stage contract, under Who answers a checkpoint.
- Write, widen or remove this setting only on the user's word, and show the change first. A delegate cannot change it, and a project's settings can only give the user more stages.

## Creating the profile

1. Ask only for the values you cannot infer. Offer the defaults above.
2. Show the whole file and where it will be written.
3. Write it after the user agrees. Create the `.corthex` folder if it does not exist, and leave every other file in that folder alone.
