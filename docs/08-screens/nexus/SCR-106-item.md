# SCR-106 Item

[한국어](SCR-106-item.ko.md)

Purpose: the user sees one item of the picture with its comments, proposals and discrepancies, and leaves a comment on it, on a phone or a PC. (FL-106, FL-107)

Path `/pictures/{project}/{part}/{stage}#item={id}`, a panel of the picture view (SCR-105), on the NEXUS server only. Who can see it: anyone Cloudflare Access lets in. New in NEXUS 0.2 (SPEC-119, SPEC-126). A part that no item holds, such as a table or a screen drawn without an ID, opens this panel for the picture itself, without an address of its own ([choice 12](README.md#choices-this-stage-made)). The rules of [every screen](README.md#every-screen) apply.

## Data

| Data | Source |
| --- | --- |
| The item: its trace ID, kind and title, and the quote of the selected part, up to 300 characters, when the part has no ID of its own (SPEC-126) | The picture's source, from API-111 (`picture.source`) |
| For a part that no item holds: its name, and the open comments on the picture itself that quote it | The picture's source and API-111 (`comments` whose item is `""`) |
| Its open comments, each with its author's kind, time, text, count of replies and last reply, and its closed comments by ID with how they closed | API-111 (`comments`, `closed_comments`) |
| Its open proposals with their reasons, and the reflections of its accepted proposals that are not closed | API-111 (`proposals`, `reflections`) |
| Its open discrepancies, each with its reasons and level, and whether it waits for a current picture | API-111 (`discrepancies`) |
| The comment being written and its write ID | The comment box and the browser's storage for that picture and item, or for that part's name on the picture itself ([rule 5](README.md#every-screen)) |

## Actions

| Action | Result | Failure |
| --- | --- | --- |
| Leave a comment on the item | The comment open at the top of its comments, by "User"; the picture's marks count it, and it waits in the agent to-do (SPEC-126) | Not saved: SCR-106#error or SCR-106#permission, with the text kept |
| Leave a comment on a discrepancy | The comment on the discrepancy's first item, naming the discrepancy | as above |
| Leave a comment on a part that no item holds | The comment on the picture itself, with the part's name as its quote (SPEC-126), at the top of the panel's comments | as above |
| Open a comment or a proposal | Its panel, SCR-107 or SCR-108 | SCR-107#gone, SCR-108#gone |
| Close, Escape or the browser's back button | The picture, at its address without `#item=` | none |

## States

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-106#normal | The item's ID and title as the heading, which takes the focus, with Close; the quote of the selected part; its discrepancies; its open proposals, each with Open; its open comments, the most recently active first, each with its author, "User" or "Agent", its time, its text, its count of replies and its last reply; its closed comments, "Closed as answered" or "Closed with a decision"; then the box, "Comment on {id}", with the characters left near its limit, and Send. After a comment is sent, it shows at the top, and the box is empty. A part that no item holds: its name as the heading, with Close; "No ID: comments on it are kept on the picture, with its name as the quote."; the open comments that quote it; and the box, "Comment on {name}" | The picture's data (API-111#200), API-118#201 |
| SCR-106#empty | "No comments on {id} yet." above the box, which is ready, with the part's name in place of {id} for a part that no item holds; no proposal and no discrepancy show | The picture's data (API-111#200) with no entry on the item |
| SCR-106#loading | While the comment is sent: Send disabled as "Sending…", the text kept in the box, and the rest of the panel usable | API-118 sent, before its answer |
| SCR-106#error | The message above the box, with the text kept and Send again, which sends with the same write ID: `invalid_request` by the field that it names; `cross_site` with a link to this page at the server's own address; `picture_not_found`, `discrepancy_not_found`, `project_not_found` or `space_not_found`, after which the view reads the picture again; `comment_limit` and `space_full`, which keep the text for later; `write_id_reused`, whose Send again makes a new write ID; `text_too_long` by the box, with its limit, and `body_too_large`; `json_required`, `internal` and `method_not_allowed`. `claimed` refuses only the agent's writes and never reaches the panel. No connection, no answer in 30 seconds, `429` or `503`: rule 8 | API-118#400 (`invalid_request`), API-118#403 (`cross_site`), API-118#404 (`picture_not_found`, `discrepancy_not_found`, `project_not_found`, `space_not_found`), API-118#409 (`comment_limit`, `space_full`, `write_id_reused`, `claimed`), API-118#413 (`text_too_long`, `body_too_large`), API-118#415 (`json_required`), API-118#default (`internal`, `method_not_allowed`) |
| SCR-106#permission | The code's message above the box, with the text kept: `access_missing`, `access_other_app`, or `no_kind`, "This sign-in cannot write here. Check the Access policy." A sign-in that expired: [rule 7](README.md#every-screen); after signing in, the text comes back from the browser's storage with its write ID | API-118#403 (`access_missing`, `access_other_app`, `no_kind`), an `opaqueredirect` reply or a `401` |
| SCR-106#gone | An item that the picture no longer holds, or an address that names one: "{id} is not in this picture." When the item still has open comments, they show with the box, since a comment is saved on the item's ID and shown apart (SPEC-126); without any, only the way back to the picture. A part that no item holds has no address, so it is never gone here: once the picture no longer draws it, its open comments show apart on the picture view | The picture's data (API-111#200) without the item |

Stale has no state of its own here: the panel shows the picture's data, and SCR-105#stale says when it is not current. The panel's data comes from the picture view, whose responses lead to its states (SCR-105).

## Kinds of cases

| Kind | What the user sees |
| --- | --- |
| Access | Either sign-in may comment (API-118); `no_kind` and a sign-in that expired: SCR-106#permission |
| Input | Empty text or spaces only: Send waits. Over 4,000 characters: the box counts down and Send waits, and the server's `413` shows by the box. The text is kept (SPEC-126) |
| Target | The item gone from the picture: SCR-106#gone. A discrepancy resolved meanwhile: `discrepancy_not_found`, SCR-106#error, and the picture is read again. A part that no item holds: the comment goes on the picture itself, with the part's name as the quote (SPEC-126), and shows on that part while the picture draws it |
| State changes | A newer picture after the comment: SCR-105#stale offers it |
| Repeats | Send is disabled while it runs; a try after a lost reply carries the same write ID and leaves one comment (SPEC-126) |
| Concurrency | The agent's comments and replies show when the view reads again; the user's writes are never refused for an agent's claim |
| Limits | 4,000 characters, 300 for a quote; 2,000 comments in a space and its 8 MiB of text: `comment_limit` and `space_full`, with the text kept |
| Outside services | None: the comment goes only to the server |
| Data exposure | Only the item's entries; a comment shows its author's kind, never a name or an email address (REQ-163) |
| Empty and streamed answers | No entry on the item: SCR-106#empty. No stream |
| Screen states | Every state at 320 and 1440 pixels, in the [wireframes](wireframes.html#scr-106) |
| AI answers | None: NEXUS calls no AI model (REQ-121); the agent's comments are text written through the hub |

## Layout

| Region | At 320 pixels | At 1440 pixels |
| --- | --- | --- |
| The panel | A bottom sheet over the picture, up to 85 per cent of the height, with a handle, the heading and Close at its top | The side panel, 400 pixels wide, beside the picture, whose item stays marked |
| The entries | Discrepancies, proposals and comments, one under another, scrolling inside the sheet | The same, scrolling inside the side panel |
| The box | At the foot of the sheet, above the keyboard: the box, the characters left and Send | At the foot of the side panel |
