# SCR-101 Hub page

[한국어](SCR-101-hub-page.ko.md)

Purpose: the user sees where every project stands, each part's current stage and next action first, and from there searches, traces an item, opens a stage or goes on to a picture view or a stage overview. (FL-105, FL-113)

Path `/`, served by the NEXUS server (API-101) and built on a device as a file by the hub's `build` (API-135). Who can see it: anyone Cloudflare Access lets in, or the device's user. Built in phase 1; NEXUS 0.2 adds the parts, the picture marks, the counts of what is open, the checkpoints that wait for their records, the actions to ask about first and the explanation on an empty server (SPEC-122 to SPEC-125). The rules of [every screen](README.md#every-screen) apply.

## Data

| Data | Source |
| --- | --- |
| Every project with its current stage and next action, its 13 stages with their states, item counts and checks, and when and from which commit each snapshot was made | API-101: `projects` in the page data `corthex-hub-page/0.2`; on a device, the same data from API-135 |
| For each part, each stage's state, checkpoint and next action, and where the records came from: the repository's default branch at its commit and time, or the device's status file | API-101 (`projects`, snapshot 0.2) |
| For each project that has a space: its pictures, each with its commit and whether it is current; its open comments, proposals and discrepancies; its checkpoints passed in NEXUS that wait for their records; and its `checkpoint-withdrawn` warnings | API-101 (`spaces`): up to 150 pictures, 100 checkpoints and 100 warnings for each project, with their totals. None on a device |
| The actions that the agent asks about first: up to 10, how many more, and whether the list is the project's, the profile's or the default | API-101 (`projects`, SPEC-125) |
| The projects in the project list that are not on this machine | API-135 on a device (`missing`) |
| The page's language and whether it was served or built on a device | API-101 (`lang`, `origin`) |

## Actions

| Action | Result | Failure |
| --- | --- | --- |
| Search for an ID or words of a title | The search results, SCR-102, at `#q=` | Empty text: no search runs |
| Select an ID | The trace view, SCR-103, at `#p=…&id=` | An ID that no item defines: SCR-103#error |
| Select a stage of a project | The stage detail, SCR-104, at `#p=…&s=` | none: the page holds every stage |
| Open a checkpoint that waits for its record | The stage overview of its part and stage, SCR-109 | The overview's own refusals (SCR-109#error) |
| Load again | The page with the server's data as it is now; on a device, the file as the hub last built it | SCR-101#error |

## States

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-101#normal | Every project in a card: its name, team or personal, the time and commit of its snapshot, Now and Next for each part, the 13 stages with their states and marks for checks, and its counts of items, errors, warnings and notes. On the server a card adds the open comments, proposals and discrepancies, a mark on each stage that has a picture, the checkpoints that wait for their records with a link to their overview, and the actions to ask about first with where the list comes from. On a device it says that the pictures and counts are on the server. A project without recorded progress says how progress gets recorded, and a project without a snapshot is listed with its reason and no stages | API-101#200 |
| SCR-101#empty | On the server, with no snapshot: what the hub shows, every project's stages, checks and pictures, and the four steps that push a project: register it with the corthex skill, list it in `nexus.push` with the server's address in `nexus.url`, set the service token's two environment variables, `CORTHEX_NEXUS_CLIENT_ID` and `CORTHEX_NEXUS_CLIENT_SECRET`, and have the agent show a dry run and push (SPEC-124). No project section, no secret and no path. On a device with no project: "No projects yet. Register a project with the corthex skill, then build the hub again." | API-101#200 with no project |
| SCR-101#stale | What the data held when the page was served or built: "Built {time}" at the top, each snapshot's time and commit, and "with uncommitted changes" when its repository had them. On the server, a stage whose picture is not current says so and why; a checkpoint passed in NEXUS that waits for its record shows beside its stage's recorded state, with when it was passed; and a `checkpoint-withdrawn` warning shows beside the recorded state that names the checkpoint (SPEC-140). Load again shows newer data; on a device, the hub builds the page again | API-101#200 |
| SCR-101#error | The message page of [rule 9](README.md#every-screen), "Something went wrong on the server. Try again", with the trace ID and Load again. A page whose data is not JSON or not `corthex-hub-page/0.2` says "This page's data could not be read. Load the page again" on the server, or "build the hub again" on a device, in place of the empty page of phase 1 ([choice 8](README.md#choices-this-stage-made)) | API-101#default (`internal`, `method_not_allowed`) |
| SCR-101#permission | The message page with the code's message, which tells the server's owner to protect the server with Access or to check its Access settings, and the trace ID. Anyone whom Access refuses sees Access's own page, outside the sitemap; a `401` is Access's too | API-101#403 (`access_missing`, `access_other_app`) |

Does not apply:

- Loading: the page is one document that holds its data, and it draws at once; until the document arrives, the browser shows its own loading.

## Kinds of cases

| Kind | What the user sees |
| --- | --- |
| Access | On the server, Access's own login page or refusal comes before the page; the Worker's `403` is SCR-101#permission. On a device the file is its user's, with no sign-in |
| Input | The search box only: empty text runs no search, and any other text runs the search of SCR-102 |
| Target | An address that names a project or a stage that the page does not hold opens a note on SCR-103 or SCR-104 with a link to the projects |
| State changes | A picture that is not current, a checkpoint that waits for its record and a withdrawn checkpoint that a record names: SCR-101#stale |
| Repeats | Does not reach the screen: it sends nothing |
| Concurrency | Does not reach the screen: it writes nothing, and another device's push shows after Load again |
| Limits | Counts over 999 show as `999+` (SPEC-123); a project's lists stop at 150 pictures, 100 checkpoints and 100 warnings, with their totals; a snapshot that reached its size limit shows that check first (SPEC-122); the ask-first list shows 10 entries and how many more (SPEC-125) |
| Outside services | None: the page loads nothing from the network (REQ-097). A stage's human view is a link that opens its tool |
| Data exposure | Only what the snapshots hold: no picture source, no comment's text, no identity, no secret and no local path (SPEC-124). A page built on a device leaves off the projects that are no longer in the project list (REQ-104) |
| Empty and streamed answers | An empty server or device: SCR-101#empty. A project without recorded progress or without a snapshot: SCR-101#normal says why. No stream |
| Screen states | Every state at 320 and 1440 pixels, in the [wireframes](wireframes.html#scr-101) |
| AI answers | None: NEXUS calls no AI model (REQ-121) |

## Layout

| Region | At 320 pixels | At 1440 pixels |
| --- | --- | --- |
| The top | The title, "Built {time} · {n} projects" under it, the stages' legend, and the search box with its button | A column 1,200 pixels wide in the middle, with the same order |
| The views | SCR-102 and SCR-103 open under the search box, above the projects | The same, across the column |
| The projects | One card under another: the name, Now and Next for each part, the counts, and the 13 stages in rows of three | Two cards side by side, with the 13 stages in rows of seven |
| The footer | Whether the page was built from files on this machine or from the snapshots on the server | The same |
