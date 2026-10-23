# Stage 13 · Presentation

| Slot | This stage |
| --- | --- |
| Inputs | The records and decision log, test results, the working product or a demo recording, and the audience and time limit from the user |
| Outputs | `script.md`, by default `docs/13-presentation/script.md`, and a scene table: one SCENE per row with what is shown, the narration and the time |
| Human view | A slide tool or a video editor, as set in `human` |
| Sync | Slides and video follow the scene table. Change the table first, then the slides |
| Human checkpoints | The script is approved, then one rehearsal at full length |
| Trace IDs | SCENE-001… |

## Steps

1. Ask for the audience, the time limit and the one thing they should remember.
2. Draft the story from the records: problem, users, what was built, evidence, what comes next.
3. Turn the story into scenes, each with one message, one thing on screen and a time.
4. Build the slides or the video from the scene table.

## Checks

- The total time fits the limit.
- Every claim traces to a record, a test result or the demo.
- Each scene has one message.

## Output template

```markdown
| ID | Message | On screen | Narration | Time |
| --- | --- | --- | --- | --- |
| SCENE-001 | Ordering takes three taps | Demo of FL-001 | "..." | 0:40 |
```
