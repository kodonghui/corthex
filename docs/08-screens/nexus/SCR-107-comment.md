# SCR-107 Comment

[한국어](SCR-107-comment.ko.md)

Purpose: the user reads one comment with all its replies, its decisions and the proposals that answer it, and replies, settles it, marks it answered or opens it again. (FL-109)

Path `/pictures/{project}/{part}/{stage}#comment={comment}`, a panel of the picture view (SCR-105), on the NEXUS server only, opened from its mark, from the item's panel, from the stage overview or from a link in a session. Who can see it: anyone Cloudflare Access lets in. New in NEXUS 0.2 (SPEC-127, SPEC-132). The rules of [every screen](README.md#every-screen) apply. With change 2 of stage 07, FL-107 shows its replies here too.

## Data

| Data | Source |
| --- | --- |
| The comment: its item and quote, the discrepancy that it names, the commit that it was made on, its author's kind, text and time, whether it is open or closed and how it closed, whom it waits for, whether the user settled it, and whether its last proposal was dismissed | API-111 (`comments`) at once, then API-114 |
| All its replies in order, up to 200, each with its author's kind, text and time and whether it settles the comment | API-114 (`replies`) |
| Its decisions, each with its link and words | API-114 (`decisions`) |
| The proposals that answer it, with their states | API-114 (`proposals`) |
| The reply being written, whether it settles the comment, and its write ID | The reply box and the browser's storage for that comment ([rule 5](README.md#every-screen)) |

## Actions

| Action | Result | Failure |
| --- | --- | --- |
| Reply | The reply at the end, by "User"; the comment waits for the agent (SPEC-127) | Not saved: SCR-107#error or SCR-107#permission, with the text kept |
| Reply that settles the comment, with "This settles it" ticked | The comment stays open: "Settled by the user, waiting for the agent's record" (SPEC-127, SPEC-132) | as above |
| Reply to a closed comment, with "Reply and open again" | The comment opens again and waits for the agent | as above |
| Mark answered, on an open comment | The comment closes as answered (REQ-166) | Closed meanwhile: SCR-107#stale; otherwise SCR-107#error |
| Open a proposal, or a decision's link | The proposal's panel, SCR-108, or the place where the decision was written | SCR-108#gone |
| Leave a new comment, after `reply_limit` | The item's panel, SCR-106, with the reply's text moved into its box | as for SCR-106 |
| Close, Escape or the browser's back button | The picture, at its address without `#comment=` | none |

## States

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-107#loading | The comment as the picture's data holds it, its text, author, state and last reply, or for a closed comment its item and how it closed, with grey lines in place of the other replies; the reply box is ready, and Reply and Mark answered wait for the comment | API-114 sent, before its answer |
| SCR-107#normal | The item's ID and the comment's state as the heading, which takes the focus, with Close: "Waiting for the agent", "Waiting for the user", "Settled by the user, waiting for the agent's record", "A proposal was dismissed", "Closed as answered" or "Closed with a decision". Then the comment, its replies in order with "Settles it" on the one that does, its decisions with their links, the proposals that answer it, each with its state and Open, and the reply box with "This settles it", Reply, or "Reply and open again" on a closed comment, and Mark answered on an open one. Without replies: "No replies yet." A comment on another picture of the project shows with a link to that picture | API-114#200, API-119#201, API-120#200 with `changed: true` |
| SCR-107#stale | The answer of a write, or the comment read again, shows that it changed meanwhile: "This comment was already closed." after Mark answered, and replies of the agent's that are new since the panel opened, marked as new. The panel then shows the comment as it is now | API-120#200 with `changed: false` |
| SCR-107#error | Reading: "Could not load this comment." with Try again, and the comment as the picture's data holds it. Writing: the message above the box, with the text kept and Send again, which sends with the same write ID: `invalid_request` by the field that it names; `cross_site` with a link to this page at the server's own address; `reply_limit`, "This comment holds as many replies as it may (200). Leave a new comment.", with Leave a new comment; `space_full`; `write_id_reused`, whose Send again makes a new write ID; `text_too_long` by the box, with its limit, and `body_too_large`; `json_required`, `internal` and `method_not_allowed`. `comment_closed` and `claimed` refuse only the agent's writes and never reach the panel. No connection, no answer in 30 seconds, `429` or `503`: rule 8 | API-114#default (`internal`, `method_not_allowed`), API-119#400 (`invalid_request`), API-119#403 (`cross_site`), API-119#409 (`reply_limit`, `space_full`, `write_id_reused`, `comment_closed`, `claimed`), API-119#413 (`text_too_long`, `body_too_large`), API-119#415 (`json_required`), API-119#default (`internal`, `method_not_allowed`), API-120#400 (`invalid_request`), API-120#403 (`cross_site`), API-120#409 (`write_id_reused`, `claimed`), API-120#default (`internal`, `method_not_allowed`) |
| SCR-107#permission | The code's message, with the text kept: `access_missing`, `access_other_app` and `no_kind`; `user_only` refuses a settling reply that comes from the agent's sign-in. A sign-in that expired: [rule 7](README.md#every-screen) | API-114#403 (`access_missing`, `access_other_app`), API-119#403 (`access_missing`, `access_other_app`, `no_kind`, `user_only`), API-120#403 (`access_missing`, `access_other_app`, `no_kind`), an `opaqueredirect` reply or a `401` |
| SCR-107#gone | "This comment is not on the server." with a link back to the picture, which is read again; a reply being written stays in the box to copy | API-114#404 (`comment_not_found`, `project_not_found`), API-119#404 (`comment_not_found`, `project_not_found`, `space_not_found`), API-120#404 (`comment_not_found`, `project_not_found`, `space_not_found`) |

Does not apply:

- Empty: a comment always holds its text, and one without replies says "No replies yet." in SCR-107#normal.

## Kinds of cases

| Kind | What the user sees |
| --- | --- |
| Access | Either sign-in may reply and mark answered (API-119, API-120); `no_kind`, `user_only` and a sign-in that expired: SCR-107#permission |
| Input | Empty text or spaces only: Reply waits. Over 4,000 characters: the box counts down and Reply waits; the server's `413` shows by the box. The text is kept |
| Target | A comment that is not on the server, or an address that names one: SCR-107#gone |
| State changes | Closed meanwhile: SCR-107#stale. A reply to a closed comment opens it again, which the button says before it is sent |
| Repeats | Reply and Mark answered are disabled while they run; a try after a lost reply carries the same write ID and leaves one reply |
| Concurrency | The agent's replies and decisions show when the panel reads again; the user and the agent marking it at once: the second gets `changed: false`, SCR-107#stale (SPEC-127) |
| Limits | 4,000 characters for a reply, 200 replies for a comment: `reply_limit` moves the text into a new comment; the space's 8 MiB: `space_full` |
| Outside services | A decision's link opens where it was written, on its own; the rest of the panel is unchanged |
| Data exposure | Only the comment's entries, each with its author's kind, never a name or an email address (REQ-163) |
| Empty and streamed answers | No replies: "No replies yet." in SCR-107#normal. No stream |
| Screen states | Every state at 320 and 1440 pixels, in the [wireframes](wireframes.html#scr-107); as stage 09 drew them in direction A, in the [mockups](../../09-mockup/nexus/mockup.html#scr-107) |
| AI answers | None: NEXUS calls no AI model (REQ-121); the agent's replies are text written through the hub |

## Layout

| Region | At 320 pixels | At 1440 pixels |
| --- | --- | --- |
| The panel | A bottom sheet over the picture, up to 85 per cent of the height, with a handle, the heading and Close at its top | The side panel, 400 pixels wide, beside the picture, whose item stays marked |
| The thread | The comment, then its replies, decisions and proposals, scrolling inside the sheet | The same, scrolling inside the side panel |
| The box | At the foot of the sheet, above the keyboard: the box, "This settles it", the characters left, Reply and Mark answered | At the foot of the side panel |
