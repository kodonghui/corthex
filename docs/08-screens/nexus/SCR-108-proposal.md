# SCR-108 Proposal

[한국어](SCR-108-proposal.ko.md)

Purpose: the user reads one proposal, with its reason and the stage source text that it changes, and accepts or dismisses it; once it is accepted, the user follows its reflection and dismisses the reflection when it needs them. (FL-110)

Path `/pictures/{project}/{part}/{stage}#proposal={proposal}`, a panel of the picture view (SCR-105), on the NEXUS server only, opened from its mark, from an item's or a comment's panel, from the stage overview or from a link in a session. Who can see it: anyone Cloudflare Access lets in; accepting and dismissing need a person's own sign-in. New in NEXUS 0.2 (SPEC-131, SPEC-133). The rules of [every screen](README.md#every-screen) apply.

## Data

| Data | Source |
| --- | --- |
| The proposal: its items, reason and change, the comment or discrepancy that it answers, the commit of the picture that it was made on, whether it is open, accepted, dismissed or withdrawn, and when it closed | API-111 (`proposals`, or the proposal of a reflection) at once, then API-115 |
| The stage source text that it changes, up to 20,000 characters | API-115 (`source_text`) |
| The reflection of an accepted proposal: pending, in review with its pull request, needing the user, closed with its pull request and commit, closed with only the commit whose stage source already held the change, or dismissed | API-111 (`reflections`) while it is not closed; API-116 once the picture no longer lists it ([change 3](README.md#changes-to-earlier-stages)) |

## Actions

| Action | Result | Failure |
| --- | --- | --- |
| Accept | "Accepted, not yet reflected": a pending reflection, bound to the picture's document version, and the picture marks its items; the picture itself does not change (SPEC-131) | Not open any more: SCR-108#stale; otherwise SCR-108#error or SCR-108#permission |
| Dismiss | "Dismissed": the comment that it answered stays open, marked as having a dismissed proposal, with "Reply to say why" | as above |
| Reply to say why, after a dismissal | The comment's panel, SCR-107, with its box ready | as for SCR-107 |
| Dismiss the reflection, when it needs the user | "The reflection was dismissed." and it closes (SPEC-133) | In another state: SCR-108#stale; otherwise SCR-108#error or SCR-108#permission |
| Open the comment, the discrepancy's item or the pull request | SCR-107, SCR-106, or the pull request on its own | SCR-107#gone, SCR-106#gone |
| Close, Escape or the browser's back button | The picture, at its address without `#proposal=` | none |

## States

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-108#loading | The proposal as the picture's data holds it, its items, reason, change and state, with a grey box in place of the stage source text and its length; Accept and Dismiss wait for the proposal | API-115 sent, before its answer |
| SCR-108#normal | "Proposal on {items}" as the heading, which takes the focus, with Close; its reason, its change, the stage source text that it changes in a box that scrolls on its own, the commit that it was made on, and the comment or discrepancy that it answers. Open: Accept and Dismiss. Accepted: its reflection, "Accepted, not yet reflected", "In review: {pull request}", "The change no longer fits the stage source; the agent asks you on its comment." with Dismiss the reflection, "Reflected by {pull request}", "Reflected: already in the stage source at commit {commit}." when the agent found the change there without a pull request (SPEC-133), the commit as text, as the view shows every commit, or "The reflection was dismissed.". Dismissed: "Dismissed on {date}; its comment stays open." Withdrawn: "Withdrawn by the agent on {date}." | API-115#200, API-116#200, API-124#200, API-125#200, API-127#200 with `changed: true` |
| SCR-108#stale | What changed meanwhile, with the proposal read again: `proposal_not_open`, "This proposal is no longer open: it was {accepted, dismissed or withdrawn}."; `edit_state`, "This reflection changed meanwhile: it is now {state}."; "The reflection was already dismissed." after Dismiss the reflection. A proposal made on an earlier picture than the one drawn: "Made on the picture of commit {commit}; the stage source may have changed since." Accept stays, since the agent checks the change against the latest stage source (SPEC-133) | API-124#409 (`proposal_not_open`), API-125#409 (`proposal_not_open`), API-127#409 (`edit_state`), API-127#200 with `changed: false` |
| SCR-108#error | Reading: "Could not load this proposal." with Try again, and the proposal as the picture's data holds it. Writing: the message above the buttons, with Try again, which sends with the same write ID: `invalid_request`; `cross_site` with a link to this page at the server's own address; `reflection_limit`, "This project holds as many pending reflections as it may (500). The proposal stays open."; `write_id_reused`, whose Try again makes a new write ID; `internal` and `method_not_allowed`. No connection, no answer in 30 seconds, `429` or `503`: rule 8 | API-115#default (`internal`, `method_not_allowed`), API-116#default (`internal`, `method_not_allowed`), API-124#400 (`invalid_request`), API-124#403 (`cross_site`), API-124#409 (`reflection_limit`, `write_id_reused`), API-124#default (`internal`, `method_not_allowed`), API-125#400 (`invalid_request`), API-125#403 (`cross_site`), API-125#409 (`write_id_reused`), API-125#default (`internal`, `method_not_allowed`), API-127#400 (`invalid_request`), API-127#403 (`cross_site`), API-127#409 (`write_id_reused`), API-127#default (`internal`, `method_not_allowed`) |
| SCR-108#permission | The code's message above the buttons: `user_only`, "Only you can do this, signed in yourself.", since only a person's own sign-in accepts or dismisses (SPEC-116); `access_missing` and `access_other_app`. A sign-in that expired: [rule 7](README.md#every-screen) | API-115#403 (`access_missing`, `access_other_app`), API-116#403 (`access_missing`, `access_other_app`), API-124#403 (`user_only`, `access_missing`, `access_other_app`), API-125#403 (`user_only`, `access_missing`, `access_other_app`), API-127#403 (`user_only`, `access_missing`, `access_other_app`), an `opaqueredirect` reply or a `401` |
| SCR-108#gone | "This proposal is not on the server." or "This reflection is not on the server." with a link back to the picture, which is read again | API-115#404 (`proposal_not_found`, `project_not_found`), API-116#404 (`edit_not_found`, `project_not_found`), API-124#404 (`proposal_not_found`, `project_not_found`), API-125#404 (`proposal_not_found`, `project_not_found`), API-127#404 (`edit_not_found`, `project_not_found`) |

Does not apply:

- Empty: a proposal always holds its reason and its change.

## Kinds of cases

| Kind | What the user sees |
| --- | --- |
| Access | Only a person's own sign-in accepts or dismisses (SPEC-116): `user_only`, and a sign-in that expired: SCR-108#permission |
| Input | Does not reach the panel: its writes take no text, only the write ID |
| Target | A proposal or reflection that is not on the server, or an address that names one: SCR-108#gone |
| State changes | Accepted, dismissed or withdrawn in another tab or by the agent, or a reflection in another state: SCR-108#stale, read again (SPEC-131) |
| Repeats | Accept, Dismiss and Dismiss the reflection are disabled while they run; accepting twice with one write ID leaves one pending reflection (SPEC-131) |
| Concurrency | A proposal closed in another tab: `proposal_not_open`, SCR-108#stale; the agent's reports on the reflection show when the panel reads again |
| Limits | 500 pending reflections in a space: `reflection_limit`, and the proposal stays open; a stage source text of up to 20,000 characters scrolls inside its box |
| Outside services | A pull request's link opens on its own; the rest of the panel is unchanged |
| Data exposure | The stage source text shows only here, read on its own (API-115); no identity but the author's kind |
| Empty and streamed answers | Does not reach the panel: a proposal is never empty. No stream |
| Screen states | Every state at 320 and 1440 pixels, in the [wireframes](wireframes.html#scr-108); as stage 09 drew them in direction A, in the [mockups](../../09-mockup/nexus/mockup.html#scr-108) |
| AI answers | None: NEXUS calls no AI model (REQ-121); the agent's proposals are text written through the hub |

## Layout

| Region | At 320 pixels | At 1440 pixels |
| --- | --- | --- |
| The panel | A bottom sheet over the picture, up to 85 per cent of the height, with a handle, the heading and Close at its top | The side panel, 400 pixels wide, beside the picture, whose items stay marked |
| The proposal | The reason, the change and the stage source text in its own scrolling box, then what it answers | The same, inside the side panel |
| The buttons | At the foot of the sheet: Accept and Dismiss side by side, or the reflection's state with its button | At the foot of the side panel |
