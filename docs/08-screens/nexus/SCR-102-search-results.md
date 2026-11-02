# SCR-102 Search results

[한국어](SCR-102-search-results.ko.md)

Purpose: the user finds the items that match an ID or the words of a title, across every project on the page, and opens one. (FL-105)

Path `/#q={words}`, a view of the hub page (SCR-101), on the server and on a device. Who can see it: anyone Cloudflare Access lets in, or the device's user. Built in phase 1, and NEXUS 0.2 leaves it as it is (SPEC-122). The rules of [every screen](README.md#every-screen) apply.

## Data

| Data | Source |
| --- | --- |
| The items that match the words: each one's ID, kind, title, project and stage | The hub page's data (API-101), searched in the page |
| The words searched | The page's address after `#q=` |

## Actions

| Action | Result | Failure |
| --- | --- | --- |
| Select a result | The trace view of that item, SCR-103 | none: the result comes from the page's data |
| Search for other words | The results for those words | Empty text closes the results |
| Close, Escape or the browser's back button | The hub page without the results, SCR-101 | none |

## States

| State | What the user sees and can do | From responses |
| --- | --- | --- |
| SCR-102#normal | "{n} matches for “{words}”" as the heading, which takes the focus, then one row for each match: the ID as a button, the kind, the title, and the project and stage. Close | The hub page's data (API-101#200) |
| SCR-102#empty | "Nothing matches “{words}”." with the search box still open for other words. Close | The hub page's data (API-101#200) |

Does not apply:

- Loading, error and permission: the search runs in the page on the data that the page holds, with no request, and every text is a valid search.
- Stale: no state of its own. The results come from the hub page's data, whose times SCR-101#stale shows.

## Kinds of cases

| Kind | What the user sees |
| --- | --- |
| Access | Does not reach the view: the hub page's access holds (SCR-101) |
| Input | Any text is a search; the words show only as text in the heading |
| Target | Does not reach the view: every result is an item of the page's data |
| State changes | Does not reach the view: the page's data does not change while it is open |
| Repeats | The same search shows the same results |
| Concurrency | Does not reach the view: it writes nothing |
| Limits | Every match shows, in the order of the page's data; a long title wraps |
| Outside services | None: the search sends nothing |
| Data exposure | Only the items that the hub page already holds |
| Empty and streamed answers | No match: SCR-102#empty. No stream |
| Screen states | Both states at 320 and 1440 pixels, in the [wireframes](wireframes.html#scr-102) |
| AI answers | None: NEXUS calls no AI model (REQ-121) |

## Layout

| Region | At 320 pixels | At 1440 pixels |
| --- | --- | --- |
| The results | A panel under the search box: the heading and Close above, then each match on two lines, the ID and kind over the title, project and stage | The same panel across the 1,200-pixel column, each match on one line |
