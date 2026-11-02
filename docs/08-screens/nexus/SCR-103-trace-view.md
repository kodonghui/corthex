# SCR-103 Trace view

[한국어](SCR-103-trace-view.ko.md)

Purpose: the user sees what one item comes from and what it leads to, through all stages, and follows the chain item by item. (FL-105)

Path `/#p={project}&id={id}`, a view of the hub page (SCR-101), on the server and on a device. Who can see it: anyone Cloudflare Access lets in, or the device's user. Built in phase 1; NEXUS 0.2 adds the note for a project that the page does not hold (SPEC-122). The rules of [every screen](README.md#every-screen) apply.

## Data

| Data | Source |
| --- | --- |
| The item: its ID, title, kind, project, stage, where it is defined, its status, type and priority, and for a screen its states and screen definition | The hub page's data (API-101) |
| What it comes from and what it leads to, by stage, the earlier and later stages that the chain reaches, the items of the same kind that it names, and its decisions | The hub page's data (API-101) |
| Where an ID that no item defines is mentioned | The hub page's data (API-101) |
| The project and the ID | The page's address after `#p=` and `&id=` |

## Actions

| Action | Result | Failure |
| --- | --- | --- |
| Select a linked ID | The trace view of that item | An ID that no item defines: SCR-103#error |
| Open the item's place in its source, or a screen's definition | Its link where the snapshot gives one | none: without a link the place shows as text |
| Close, Escape or the browser's back button | The hub page, SCR-101 | none |

## States

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-103#normal | The ID and title as the heading, which takes the focus, the item's facts, then "Comes from" and "Leads to" with the linked items grouped by stage, "Earlier stages reached" and "Later stages reached", "Same kind" and "Decisions". A screen also shows its states, such as `#empty`, and where its screen definition is. An item without links says "none" there. Close | The hub page's data (API-101#200) |
| SCR-103#error | An ID that no item defines: "{id} is not defined in the sources that were read." with "Mentioned with it" and the places where it is mentioned. An address whose project the page does not hold: "This project is not on this page." with a link to the projects, where phase 1 shows nothing ([choice 7](README.md#choices-this-stage-made)). Close | The hub page's data (API-101#200) |

Does not apply:

- Loading and permission: the view reads the data that the page holds, with no request, and shows it to whoever opened the page.
- Empty: an item always shows itself; an item without links shows "none" in SCR-103#normal.
- Stale: no state of its own. The view comes from the hub page's data, whose times SCR-101#stale shows.

## Kinds of cases

| Kind | What the user sees |
| --- | --- |
| Access | Does not reach the view: the hub page's access holds (SCR-101) |
| Input | Does not reach the view: an address in any form opens SCR-103#error or the item |
| Target | An ID that no item defines, or a project that the page does not hold: SCR-103#error |
| State changes | Does not reach the view: the page's data does not change while it is open |
| Repeats | Selecting the same ID again shows the same view |
| Concurrency | Does not reach the view: it writes nothing |
| Limits | Every link shows; a long list wraps, and an ID of many characters breaks rather than widening the page |
| Outside services | None: the view sends nothing |
| Data exposure | Only what the hub page already holds |
| Empty and streamed answers | An item without links: "none" in SCR-103#normal. No stream |
| Screen states | Both states at 320 and 1440 pixels, in the [wireframes](wireframes.html#scr-103) |
| AI answers | None: NEXUS calls no AI model (REQ-121) |

## Layout

| Region | At 320 pixels | At 1440 pixels |
| --- | --- | --- |
| The item | A panel under the search box: the heading and Close, then the facts as label over value | The same panel across the column, with the facts as label beside value |
| The chain | "Comes from", then "Leads to", one under the other, each grouped by stage | "Comes from" and "Leads to" side by side |
