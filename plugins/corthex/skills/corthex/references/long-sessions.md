# Long sessions, compaction and handoffs

When a conversation fills its context window, the host summarises it and carries on from the summary. This is compaction. A summary keeps the gist and loses exact values: numbers, paths, error text and the user's own words. These habits keep the work intact across compactions, sessions and agents.

## When to compact

- Leave automatic compaction on. In Claude Code it also runs during a break: a long conversation is summarised before its prompt cache expires, so the resumed session does not pay to read the whole conversation again.
- Compact by hand at the end of a step, once its records are written, not in the middle of one. A summary made mid-step loses the state that the step was holding.
- In Claude Code, `/compact` takes focus instructions, for example `/compact Keep a handoff: goal, facts, changes, checks, dead ends, next steps, done condition, pointers`. A project can also keep standing instructions under a `# Compact instructions` heading in its root `CLAUDE.md`. That file belongs to the project: suggest the lines and let the user add them.

## Before a planned compaction or a handoff

Write the handoff record from the `corthex-record` skill; its progress reference has the format. The work then survives even when the summary drops a detail, and the next session or agent starts from the handoff instead of asking again.

## After a compaction

- Treat the summary as a pointer, not as the source. When an exact value is needed, such as a number, a path, an error message or what the user said, and the summary does not hold it, read it again from its source: the file, the record, the command output or the session transcript.
- Claude Code gives hooks the transcript's location as `transcript_path`, a JSON Lines file under `~/.claude/projects/`. Search it for the word or ID you need and read only the matching lines. Only read it: do not copy tool output from it into records or messages, because it can hold private or sensitive output.
- When the value cannot be found, say so. Do not rebuild it from memory.

## Handing over large material

Do not paste whole files, long logs or earlier handoffs into a prompt or a handoff. Give the files to read, the words to search for and the line ranges, so the next session reads only what it needs.

## Codex compaction prompt (opt-in)

Codex can write its compaction summary in the same handoff slots. Its configuration has `compact_prompt`, the prompt text, and `experimental_compact_prompt_file`, a file that holds the prompt; the second is experimental and may change between versions. Show this example when the user asks for it. Do not change the user's global configuration yourself.

```toml
# ~/.codex/config.toml
compact_prompt = """
Summarise the conversation so far as a handoff for the next context window, in at most 60 lines:
- Goal: the result asked for, in one line, with the requester's own words
- Facts: exact paths, commands, values and errors that were confirmed, each with its source; label guesses
- Changed: each file or setting that was changed, and whether the change was verified
- Checks: the checks that ran and their results
- Dead ends: approaches that failed and should not be tried again
- Next: the remaining steps in order, starting with the very next action
- Done when: the condition that ends the work
- Pointers: file paths with line ranges, commit SHAs and words to search for
"""
```
