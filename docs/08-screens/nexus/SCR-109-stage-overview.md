# SCR-109 Stage overview

[한국어](SCR-109-stage-overview.ko.md)

Purpose: the user sees what is left in one part's stage, its open discrepancies, comments and pending reflections together, with its recorded state, checkpoints and checks, and passes the stage's checkpoint, or withdraws one passed in NEXUS before it is recorded. (FL-113)

Path `/overview/{project}/{part}/{stage}`, on the NEXUS server only (API-103), linked from the stage detail (SCR-104), the hub page (SCR-101) and the picture view (SCR-105). Who can see it: anyone Cloudflare Access lets in; passing and withdrawing need a person's own sign-in. New in NEXUS 0.2 (SPEC-138, SPEC-139). The rules of [every screen](README.md#every-screen) apply.

## Data

| Data | Source |
| --- | --- |
| The page: the project, part and stage, and in `view-data` the answer of API-112 | API-103 (`corthex-view-page/0.2`) |
| The view's core file, the same as the picture view's | API-104 |
| The stage's record for the part: its state, checkpoints, next action, when it was updated, and whether it came from the repository or the device's status file | API-112 (`record`), first from the page's data |
| Whether the project reads the stage, and the state of its text source | API-112 (`read`, `source_state`) |
| Its checks | API-112 (`checks`) |
| The pictures that its discrepancies concern, each with its commit and whether it is current | API-112 (`pictures`) |
| Its open discrepancies, open comments and pending reflections, up to 50 of each with their totals, and how many discrepancies the last cross-check could not open | API-112 (`discrepancies`, `comments`, `reflections`, `not_opened`) |
| Its checkpoints passed in NEXUS that no record names yet, and the withdrawn ones that a record names, with their `checkpoint-withdrawn` warnings | API-112 (`checkpoints`, `warnings`) |
| The words being written and their write ID | The words box and the browser's storage for that part and stage ([rule 5](README.md#every-screen)) |

## Actions

| Action | Result | Failure |
| --- | --- | --- |
| Pass the checkpoint, with or without words | "Passed in NEXUS on {date}, waiting for its record" beside the recorded state; the agent to-do lists it (SPEC-139) | Not passed: SCR-109#error or SCR-109#permission, with the words kept |
| Withdraw a checkpoint passed in NEXUS | "Withdrawn on {date}", and it leaves the to-do, unless a reported pull request writes it (SPEC-139) | Recorded meanwhile: SCR-109#stale; otherwise SCR-109#error or SCR-109#permission |
| Open an entry | The picture view at its panel: `#comment=`, `#proposal=`, or `#item=` with a discrepancy's item | SCR-106#gone, SCR-107#gone, SCR-108#gone |
| Open a picture, or the hub page | SCR-105 for the part and stage, or SCR-101 | Their own refusals |
| Load again | The page from the server | SCR-109#error |

## States

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-109#loading | Before the view's code runs, the page shows only its static line, "Loading the stage overview. If it does not appear, load the page again.", with a link that loads it again; the page's data then draws at once | API-103#200, API-104#200 |
| SCR-109#normal | The top bar: Hub page, the project, part and stage, and Picture for a pictured stage. The recorded state with its checkpoints and next action, when it was updated, and "from the repository" or "from the device's status file". "What is left": the open discrepancies, the open comments and the pending reflections, each with its total, each entry linking to its panel. The checks, or "No checks found anything.". "Pass the checkpoint": the words box, optional, up to 2,000 characters, and Pass. A stage that the project does not read says why, from the state of its text source, and still offers Pass (SPEC-138); a stage without pictures shows its record and checks only | API-103#200, API-112#200, API-128#201, API-129#200 with `changed: true` |
| SCR-109#empty | Nothing open: "Nothing is left in this stage." in place of the lists, with the record, the checks and Pass | API-112#200 with no entries |
| SCR-109#stale | A checkpoint passed in NEXUS that no record names: "Passed in NEXUS on {date}, waiting for its record" beside the recorded state, with its words, its pull request once the agent reports one, and Withdraw; Pass then says "Pass again", since a second pass makes a second checkpoint. A `checkpoint-withdrawn` warning: "The record names a checkpoint that was withdrawn in NEXUS. The agent corrects the record." beside the recorded state (SPEC-140). Withdraw on a checkpoint recorded meanwhile: "This checkpoint is recorded, so it cannot be withdrawn here. Changing it is a new decision.", and the overview reads again to show the record. Withdraw on one withdrawn already: "This checkpoint was already withdrawn." A picture that is not current: "Not current" by its link, and why | API-112#200, API-129#409 (`checkpoint_recorded`), API-129#200 with `changed: false` |
| SCR-109#error | The page's request: the message page of [rule 9](README.md#every-screen) with the code's message, the trace ID and a link to the hub page; for `internal`, Load again. The core file does not load: only the page's static line stays, with its link. Reading again: the same messages in a bar above the overview, which stays as it is, or "Could not update" with Try again. Passing: the message above the words box, with the words kept and Pass again, which sends with the same write ID: `invalid_request` by the field; `cross_site` with a link to this page at the server's own address; `part_not_found` and `space_not_found`; `write_id_reused`, whose Pass again makes a new write ID; `text_too_long` by the box, and `body_too_large`; `json_required`, `internal` and `method_not_allowed`. Withdrawing: `invalid_request`; `cross_site`; `checkpoint_not_found` and `project_not_found`, after which the overview reads again; `write_id_reused`; `internal` and `method_not_allowed`. No connection, no answer in 30 seconds, `429` or `503`: rule 8 | API-103#404 (`part_not_found`, `project_not_found`, `not_found`), API-103#default (`internal`, `method_not_allowed`), API-104#403 (`access_missing`, `access_other_app`), API-104#404 (`not_found`), API-104#default (`internal`, `method_not_allowed`), API-112#404 (`part_not_found`, `project_not_found`, `not_found`), API-112#default (`internal`, `method_not_allowed`), API-128#400 (`invalid_request`), API-128#403 (`cross_site`), API-128#404 (`part_not_found`, `space_not_found`), API-128#409 (`write_id_reused`), API-128#413 (`text_too_long`, `body_too_large`), API-128#415 (`json_required`), API-128#default (`internal`, `method_not_allowed`), API-129#400 (`invalid_request`), API-129#403 (`cross_site`), API-129#404 (`checkpoint_not_found`, `project_not_found`), API-129#409 (`write_id_reused`), API-129#default (`internal`, `method_not_allowed`) |
| SCR-109#permission | The page's request: the message page with the code's message. Reading again, passing or withdrawing: the code's message, with the words kept: `user_only`, "Only you can do this, signed in yourself.", since only a person's own sign-in passes or withdraws a checkpoint (SPEC-139); `access_missing` and `access_other_app`. A sign-in that expired: [rule 7](README.md#every-screen) | API-103#403 (`access_missing`, `access_other_app`), API-112#403 (`access_missing`, `access_other_app`), API-128#403 (`user_only`, `access_missing`, `access_other_app`), API-129#403 (`user_only`, `access_missing`, `access_other_app`), an `opaqueredirect` reply or a `401` |

Every state of the stage applies. The overview has no editor, so a failed core file is an error here, not a state of its own as on the picture view.

## Kinds of cases

| Kind | What the user sees |
| --- | --- |
| Access | Only a person's own sign-in passes or withdraws (SPEC-139): `user_only`, the Worker's `403` and a sign-in that expired: SCR-109#permission |
| Input | The words are optional, up to 2,000 characters: words that are empty or only spaces are left out, and the checkpoint passes without words; past the limit the box counts down and Pass waits; `invalid_request` and `text_too_long` show by the box. The words are kept |
| Target | A project or part that the snapshot does not hold, or a stage that is not one of the 13: SCR-109#error. An entry gone since the overview was read: its panel says so (SCR-106#gone, SCR-107#gone, SCR-108#gone) |
| State changes | A checkpoint that waits for its record, or one recorded or withdrawn meanwhile: SCR-109#stale |
| Repeats | Pass and Withdraw are disabled while they run; a pass sent again with its write ID leaves one checkpoint, while Pass again later makes a second one, and both show (SPEC-139) |
| Concurrency | A record pushed, or a checkpoint withdrawn in another tab, shows when the overview reads again; a withdrawal that a record overtook: `checkpoint_recorded`, SCR-109#stale |
| Limits | 50 of each list, with its total, and the picture view lists 500; the words' 2,000 characters; "{n} discrepancies could not be opened" when the space held 1,000 open ones (`not_opened`) |
| Outside services | None: the overview sends its requests only to the server; a pull request's link opens on its own |
| Data exposure | Only the stage's record, checks and entries; a checkpoint shows that the user passed it, never who by name |
| Empty and streamed answers | Nothing left: SCR-109#empty. No checks: "No checks found anything.". No stream |
| Screen states | Every state at 320 and 1440 pixels, in the [wireframes](wireframes.html#scr-109) |
| AI answers | None: NEXUS calls no AI model (REQ-121) |

## Layout

| Region | At 320 pixels | At 1440 pixels |
| --- | --- | --- |
| The top bar | Hub page, then the project · part · stage on a line of its own, and Picture | One line in a column 1,200 pixels wide in the middle |
| The record | First: the recorded state, its checkpoints and next action, then the checkpoints passed in NEXUS with Withdraw | The right column, 400 pixels wide |
| What is left | After the record: discrepancies, comments and pending reflections, each a list with its total | The left column |
| Passing | After what is left: the words box and Pass | In the right column, under the record |
| The checks | Last, as rows | In the right column, under passing |
