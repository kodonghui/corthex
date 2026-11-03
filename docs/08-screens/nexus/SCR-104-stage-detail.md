# SCR-104 Stage detail

[한국어](SCR-104-stage-detail.ko.md)

Purpose: the user sees one stage of a project, for each part its state, last checkpoint and next action, with its checks and items, and opens its human view, and on the server its picture views and its stage overviews. (FL-105, FL-113)

Path `/#p={project}&s={stage}`, a view of the hub page (SCR-101) inside the project's card, on the server and on a device. Who can see it: anyone Cloudflare Access lets in, or the device's user. Built in phase 1; NEXUS 0.2 shows it for each part and, on the server, links each part's picture view and stage overview (SPEC-123, SPEC-138). The rules of [every screen](README.md#every-screen) apply.

## Data

| Data | Source |
| --- | --- |
| The stage's state, last checkpoint and next action, for each part | The hub page's data (API-101) |
| Its settings: the human view and its link, which side is the truth, the text source with its files and its state, the time of a text copy, and the note | The hub page's data (API-101) |
| Its checks, by level, and its items, by kind | The hub page's data (API-101) |
| On the server, for each part: the stage's picture with its commit and whether it is current, for 01, 05 and 07, and the checkpoints passed in NEXUS that wait for their records or that a record names after their withdrawal | The hub page's data (API-101, `spaces`) |
| The project and the stage | The page's address after `#p=` and `&s=` |

## Actions

| Action | Result | Failure |
| --- | --- | --- |
| Open a part's picture view (server) | The picture view, SCR-105 | The page's own refusals (SCR-105#error, SCR-105#permission) |
| Open a part's stage overview (server) | The stage overview, SCR-109 | The page's own refusals (SCR-109#error, SCR-109#permission) |
| Open the human view | The stage's tool at the link that the settings give (REQ-095) | The tool's own |
| Select an item's ID | The trace view, SCR-103 | An ID that no item defines: SCR-103#error |
| Show all items | Every item of the stage, after the first ones | none |
| Close, Escape, another stage, or the browser's back button | The card without the detail, or the other stage | none |

## States

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-104#normal | Under the stage row of the card, the stage's name and state as the heading, which takes the focus, then for each part its state, last checkpoint and next action; the facts of its settings; its checks, "No checks found anything." when there are none; and its items by kind. On the server, each part of a pictured stage has "Picture" and each part "Stage overview". On a device, a line says that the pictures and overviews are on the server | The hub page's data (API-101#200) |
| SCR-104#empty | A stage without items: its state, checkpoint and next action, and why there is nothing, from its text source's state: not found, no text source, the repository not on the machine that made the snapshot, the stage skipped, or a setting that needs a fix. On the server, the stage overview link stays | The hub page's data (API-101#200) |
| SCR-104#stale | A part's picture that is not current: "Not current" by its link, and why: larger than a snapshot may hold, its source gone from the repository, or its source in another repository. A checkpoint passed in NEXUS that waits for its record: "Passed in NEXUS on {date}, waiting for its record" beside the recorded state. A `checkpoint-withdrawn` warning beside the recorded state that names it. A text copy of a human view shows when it was copied | The hub page's data (API-101#200) |
| SCR-104#error | An address whose project or stage the page does not hold: "This project is not on this page." or "This stage is not one of the 13." with a link to the projects, where phase 1 shows nothing ([choice 7](README.md#choices-this-stage-made)) | The hub page's data (API-101#200) |

Does not apply:

- Loading: the detail reads the data that the page holds, with no request.
- Permission: the detail shows what the hub page shows to whoever opened it. The picture views and overviews that it links check their own access (SCR-105#permission, SCR-109#permission).

## Kinds of cases

| Kind | What the user sees |
| --- | --- |
| Access | Does not reach the detail: the hub page's access holds (SCR-101), and its links lead to pages that check their own |
| Input | Does not reach the detail: an address in any form opens the stage or SCR-104#error |
| Target | A project or a stage that the page does not hold: SCR-104#error. A picture removed since the page was served: the picture view says so (SCR-105#error) |
| State changes | A picture that is not current and a checkpoint that waits for its record or was withdrawn: SCR-104#stale |
| Repeats | Selecting the same stage again shows the same detail |
| Concurrency | Does not reach the detail: it writes nothing |
| Limits | The first items show with "Show all {n}", as in phase 1; the checkpoints stop at the hub page's 100 for each project, with their total |
| Outside services | The human view is a link to its tool, which opens on its own; the rest of the detail is unchanged |
| Data exposure | Only what the hub page already holds; a picture's source is never in the hub page |
| Empty and streamed answers | A stage without items: SCR-104#empty. No stream |
| Screen states | Every state at 320 and 1440 pixels, in the [wireframes](wireframes.html#scr-104); as stage 09 drew them in direction A, in the [mockups](../../09-mockup/nexus/mockup.html#scr-104) |
| AI answers | None: NEXUS calls no AI model (REQ-121) |

## Layout

| Region | At 320 pixels | At 1440 pixels |
| --- | --- | --- |
| The detail | Inside the card, under the stage row: the heading and Close, then one block for each part with its state, checkpoint, next action and its links on a line of their own | The same inside the card, which is half of the 1,200-pixel column, with the links beside each part's state |
| The facts, checks and items | Each fact as label over value, then the checks and items as rows | Label beside value, then the checks and items as rows |
