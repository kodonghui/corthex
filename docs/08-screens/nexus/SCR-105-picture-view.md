# SCR-105 Picture view

[한국어](SCR-105-picture-view.ko.md)

Purpose: the user looks at one part's picture of a stage, the DDD board, the ERD or the sitemap, with its document version and the open comments, proposals and discrepancies on its items, on a phone or a PC, and opens an item, a comment or a proposal from it. (FL-106, FL-110, FL-115)

Path `/pictures/{project}/{part}/{stage}`, on the NEXUS server only (API-102), linked from the stage detail (SCR-104) and the stage overview (SCR-109). Who can see it: anyone Cloudflare Access lets in. New in NEXUS 0.2 (SPEC-119). The rules of [every screen](README.md#every-screen) apply.

## Data

| Data | Source |
| --- | --- |
| The page: the project, part and stage, and in `view-data` the answer of API-111 or the problem `picture_not_found` | API-102 (`corthex-view-page/0.2`) |
| The view's code: its core file, and the read-only editor of the picture's kind, Excalidraw for the DDD board and the sitemap or ERD Editor for the ERD (D11 of stage 02) | API-104 |
| The picture's source, its document version, the commit and the commit's time, when it was drawn, and whether it is current, with why | API-111 (`picture`), first from the page's data |
| The open comments, the most recently active first, each with its count of replies and its last reply, and the closed comments by ID | API-111 (`comments`, `closed_comments`) |
| The open proposals, without their stage source text, and the reflections that are not closed | API-111 (`proposals`, `reflections`) |
| The open discrepancies of the part that concern the picture, each marked when it waits for a current picture | API-111 (`discrepancies`) |
| The comments, proposals and discrepancies whose item the picture no longer holds, and the comments on the picture itself whose part it no longer draws | Found by the view from API-111's entries and the picture's items (SPEC-119) |
| The panel to open | The page's address after `#`: `item=`, `comment=` or `proposal=` |

## Actions

| Action | Result | Failure |
| --- | --- | --- |
| Select an item, or open an address with `#item=` | The item's panel, SCR-106 | An ID that the picture does not hold: SCR-106#gone |
| Select a part drawn without an ID | The item panel, SCR-106, for the picture itself, with the part's name ([choice 12](README.md#choices-this-stage-made)) | none |
| Select a comment's mark, or open `#comment=` | The comment's panel, SCR-107 | SCR-107#gone |
| Select a proposal's mark, or open `#proposal=` | The proposal's panel, SCR-108 | SCR-108#gone |
| Move or zoom the picture | The picture moves inside its frame, and the page does not scroll sideways (REQ-146) | none |
| Show the items as a list | Every item of the picture, and each part drawn without an ID by its name, in a list with its marks, from which the panels open; a screen reader reads the same list | none |
| Show a newer version | The picture drawn again from the newer data | The read fails: SCR-105#error |
| Open the stage overview, or the hub page | SCR-109 for the part and stage, or SCR-101 | Their own refusals |
| Load again | The page from the server | SCR-105#error |

## States

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-105#loading | The top bar with the project, part and stage, and in the picture's frame a grey placeholder with "Drawing the picture…"; the marks and the panels wait for the drawing. Before the view's code runs, the page shows only its static line, "Loading the picture view. If it does not appear, load the page again.", with a link that loads it again | API-102#200, API-104#200 |
| SCR-105#normal | The top bar: Hub page, the project, part and stage, and Stage overview. Under it the document version, "Commit {commit} of {time}". The picture, read-only and laid out the same way each time (SPEC-119), moving inside its frame; on each item that has them, marks with the counts of its open comments, proposals and discrepancies; on each part drawn without an ID whose name open comments on the picture itself quote, a mark with their count; and "Accepted, not yet reflected" on the items of an accepted proposal whose reflection is not closed (SPEC-131). Under the picture, or beside it from 1,024 pixels: "Apart: comments whose item is gone ({n})", Items as a list and the legend of the marks | API-102#200, API-111#200 |
| SCR-105#large | As SCR-105#normal, with "This picture is large ({n} elements), so drawing it may take longer." above the frame; it is drawn without the 3-second target (SPEC-119) | API-111#200 with more than 300 elements |
| SCR-105#empty | No picture: the message of `picture_not_found` for its `why`, not drawn yet, left out for its size, or its source in another repository ([Messages](README.md#messages)), with links to the stage overview and the hub page | API-102#200 with the problem `picture_not_found`, API-111#404 (`picture_not_found`) |
| SCR-105#stale | A picture that is not current: a notice above the frame with the commit that it shows and why, from `not_current`: its newest source is larger than a snapshot may hold, gone from the repository, or in another repository; the picture stays usable. A discrepancy that waits for a current picture: its mark says so (`waiting`). After a write or a reading again, a picture of a newer commit than the one drawn: "A newer version of this picture is on the server." with Show it, while the drawn picture stays ([choice 6](README.md#choices-this-stage-made)) | API-111#200 |
| SCR-105#error | The page's request: the message page of [rule 9](README.md#every-screen) with the code's message, the trace ID and a link to the hub page; for `internal`, Load again. A page's problem other than `picture_not_found`: its message, the same way. Reading again (rule 6): the same messages in a bar above the picture, which stays as drawn, or "Could not update" with Try again. No connection, no answer in 30 seconds, `429` or `503`: rule 8 | API-102#404 (`project_not_found`, `space_not_found`, `part_not_found`, `not_found`), API-102#default (`internal`, `method_not_allowed`), API-111#404 (`project_not_found`, `space_not_found`, `part_not_found`, `not_found`), API-111#default (`internal`, `method_not_allowed`) |
| SCR-105#code-failed | The editor's code does not load or fails: "The picture could not be drawn here, so its items are listed instead." and the list of items with their marks, from which the panels open as usual (SPEC-119). The core file does not load: only the page's static line stays, with its link. The browser does not tell the page why a file of code did not load, so every failure of API-104 leads here | API-104#403 (`access_missing`, `access_other_app`), API-104#404 (`not_found`), API-104#default (`internal`, `method_not_allowed`) |
| SCR-105#permission | The page's request: the message page with the code's message. Reading again: the code's message in the bar above the picture. A sign-in that expired while the view was open: [rule 7](README.md#every-screen), "Sign in again", with what the panels hold kept | API-102#403 (`access_missing`, `access_other_app`), API-111#403 (`access_missing`, `access_other_app`), an `opaqueredirect` reply or a `401` |

Every state of the stage applies, with two of the screen's own, large and code-failed. Phase ② adds editing on a PC at widths of 1,024 pixels and more (SPEC-134, FL-115); NEXUS 0.2 draws the picture read-only, with no edit button.

## Kinds of cases

| Kind | What the user sees |
| --- | --- |
| Access | Access's own login page or refusal comes before the page; the Worker's `403` and a sign-in that expired: SCR-105#permission |
| Input | Does not reach the view itself: its panels take the input (SCR-106 to SCR-108) |
| Target | A project, space, part or stage that the server does not hold: SCR-105#error. No picture: SCR-105#empty. An address whose item, comment or proposal the picture does not hold: SCR-106#gone, SCR-107#gone, SCR-108#gone |
| State changes | A picture that is not current, a discrepancy that waits, a newer picture after a write: SCR-105#stale. An accepted proposal not yet reflected: its mark in SCR-105#normal |
| Repeats | Show it and Load again are disabled while they run |
| Concurrency | Another tab's or the agent's writes show when the view reads again (rule 6) or after Load again |
| Limits | More than 300 elements: SCR-105#large. The lists stop at 500 of each and 1,000 discrepancies, with their totals, as "500 of 612" |
| Outside services | None: the view loads its code, styles and fonts only from the server (REQ-147) and sends its requests only to it |
| Data exposure | Only the picture and its entries; a proposal's stage source text only in its panel (API-115); no identity but the author's kind |
| Empty and streamed answers | No picture: SCR-105#empty. A picture without entries shows no marks and no "Apart". No stream |
| Screen states | Every state at 320 and 1440 pixels, in the [wireframes](wireframes.html#scr-105); as stage 09 drew them in direction A, in the [mockups](../../09-mockup/nexus/mockup.html#scr-105) |
| AI answers | None: NEXUS calls no AI model (REQ-121) |

## Layout

| Region | At 320 pixels | At 1440 pixels |
| --- | --- | --- |
| The top bar | Hub page, then the project · part · stage on a line of its own, which wraps, and Stage overview | One line: Hub page, the project · part · stage, the document version and Stage overview |
| The notices | Each notice of a state as a bar under the top bar, across the width | The same, above the picture |
| The picture | Its frame takes the width and about 60 per cent of the height; the picture moves and zooms inside it | Its frame takes the width left of the side panel and the height under the top bar |
| Apart and the list | Under the frame: "Apart ({n})", Items as a list and the legend | In the side panel, 400 pixels wide, while no panel is open |
| The panels | A bottom sheet of up to 85 per cent of the height, over the picture | The side panel, 400 pixels wide, beside the picture |
