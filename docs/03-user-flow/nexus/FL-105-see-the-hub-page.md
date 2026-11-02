# FL-105 See where the projects stand

[한국어](FL-105-see-the-hub-page.ko.md)

Serves: REQ-091, REQ-092, REQ-093, REQ-094, REQ-095, REQ-096, REQ-097, REQ-098, REQ-099, REQ-100, REQ-101, REQ-102, REQ-103, REQ-104, REQ-113, REQ-189, REQ-190, REQ-197

Context: CTX-008 Overview. Starts when the user opens the hub page, built on a device or served by the NEXUS server, on a phone or a PC. Built in phase 1; NEXUS 0.2 adds the explanation on an empty server and the pictures' links and counts (REQ-102, REQ-189, REQ-190), and R4 of 2026-11-02 adds each project's actions to ask about first (REQ-197).

```mermaid
flowchart TD
  A(["The user opens the hub page,<br/>on a phone or a PC"]) --> B{"Served by the NEXUS server?"}
  B -->|no, built on a device| C["Refresh the snapshots of the projects in<br/>the project list, FL-101, and leave off<br/>the projects that are no longer in it<br/>REQ-104"]
  B -->|yes| D{"Did Cloudflare Access let the viewer in?<br/>REQ-113"}
  D -->|no| D1["The request is refused"]
  D1 --> Z(["End"])
  D -->|yes| E{"Does the server hold a snapshot?"}
  E -->|no| E1["Say what the hub shows and<br/>how a project gets pushed to it<br/>REQ-102 · SCR-101"]
  E1 --> Z
  E -->|yes| F["Show each project's open comments, proposals<br/>and discrepancies, and link each stage that<br/>has a picture to its picture view<br/>REQ-189, REQ-190 · SCR-101, SCR-104"]
  C --> G
  F --> G["Show every project, its current stage and next action<br/>first, then its 13 stages with their states, item<br/>counts and checks, and when and from which<br/>commit each snapshot was made<br/>REQ-091, REQ-092, REQ-096 · SCR-101"]
  G --> G1["Show what the agent asks about first in each project,<br/>whether the list is the project's own or the profile's,<br/>and that anything that cannot be undone is asked in any case<br/>REQ-197 · SCR-101"]
  G1 --> H{"Has the project recorded progress?"}
  H -->|no| H1["Say how progress gets recorded<br/>REQ-103 · SCR-101"]
  H -->|yes| I
  H1 --> I{"What does the user do?"}
  I -->|selects an ID| J["Show what the item comes from and<br/>what it leads to, through all stages<br/>REQ-093 · SCR-103"]
  I -->|searches| K["List the items that match the ID<br/>or the words of a title<br/>REQ-094 · SCR-102"]
  I -->|opens a stage's tool| L["Open the stage's human view<br/>from its link in the settings<br/>REQ-095 · SCR-104"]
  I -->|opens a picture| M["Open the picture view, FL-106<br/>REQ-189"]
  I -->|leaves| Z
  J --> I
  K --> I
  L --> Z
  M --> Z
```

On every path the page loads nothing from the network, shows the projects' text only as text, follows the profile's language and the system's light or dark mode, and works at every width from 320 to 1440 pixels without sideways scrolling (REQ-097, REQ-098, REQ-099, REQ-100, REQ-101).

The actions to ask about first are shown as the snapshot holds them, and NEXUS enforces none of them; what the spec decides about them is point 18 of the [README](README.md#points-for-the-functional-spec).
