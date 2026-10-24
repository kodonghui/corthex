# Stage 13 · Presentation

| Slot | This stage |
| --- | --- |
| Inputs | The records and decision log, test results, the working product or a demo recording, and the audience and time limit from the user |
| Outputs | `script.md`, by default `docs/13-presentation/script.md`, and a scene table: one SCENE per row with what is shown, the narration and the time |
| Human view | By default slides built from the scene table, or a video editor for a demo video, as set in `human`. See Slides below |
| Sync | Slides and video follow the scene table. Change the table first, then the slides |
| Human checkpoints | The script is approved, then one rehearsal at full length |
| Trace IDs | SCENE-001… |

## Steps

1. Ask for the audience, the time limit and the one thing they should remember.
2. Draft the story from the records: problem, users, what was built, evidence, what comes next.
3. Turn the story into scenes, each with one message, one thing on screen and a time.
4. Build the slides or the video from the scene table (see Slides below).

## Checks

- The total time fits the limit.
- Every claim traces to a record, a test result or the demo.
- Each scene has one message.
- Every scene is in the slides, in the table's order.

## Slides

Build the slides from the scene table, never the other way round: each scene becomes one slide or more, in the table's order, with its ID and narration in the speaker notes where the tool has them.

- In Claude Code, where artifacts are available, `/slides <brief>` makes the deck as a Claude Slides artifact; give it the scene table as the brief. The deck downloads as PPTX or PDF. Claude Design makes decks too, with the same exports.
- In any other host, such as Codex, write the deck as Markdown for Marp, by default `docs/13-presentation/slides.md`, and convert it with `npx @marp-team/marp-cli@latest slides.md`, which writes HTML; add `--pdf` or `--pptx` for those. Marp needs Node.js 18 or later, and PDF and PPTX also need Chrome, Edge or Firefox. Its PPTX slides are images; `--pptx-editable` makes editable ones, but it is experimental and needs LibreOffice.
- When the scene table changes, change the slides after it.

## Output template

```markdown
| ID | Message | On screen | Narration | Time |
| --- | --- | --- | --- | --- |
| SCENE-001 | Ordering takes three taps | Demo of FL-001 | "..." | 0:40 |
```
