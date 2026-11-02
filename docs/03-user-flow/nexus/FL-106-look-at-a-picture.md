# FL-106 Look at a picture

[한국어](FL-106-look-at-a-picture.ko.md)

Serves: REQ-113, REQ-139, REQ-143, REQ-144, REQ-145, REQ-146, REQ-147, REQ-148, REQ-149, REQ-150, REQ-162, REQ-192

Context: CTX-012 Pictures, with the discussion of CTX-014 on them. Starts when the user opens a stage's picture from the hub page on the NEXUS server (FL-105), on a phone or a PC. New in NEXUS 0.2.

```mermaid
flowchart TD
  A(["The user opens a stage's picture from the hub page<br/>on the NEXUS server, FL-105, on a phone or a PC"]) --> B{"Did Cloudflare Access let the user in?<br/>REQ-113"}
  B -->|no| B1["The request is refused"]
  B1 --> Z(["End"])
  B -->|yes| C["Load the picture view's code, styles<br/>and fonts from the NEXUS server only<br/>REQ-147 · SCR-105"]
  C --> D{"Is the picture in the space?"}
  D -->|no| D1["Say which picture was left out and why:<br/>for size, or because its source<br/>is in another repository<br/>REQ-144, REQ-192 · SCR-105"]
  D1 --> Z
  D -->|yes| E["Show the picture as it was laid out, within<br/>3 seconds for up to 300 elements<br/>REQ-143, REQ-149 · SCR-105"]
  E --> F["Show its document version:<br/>the commit and the commit's time<br/>REQ-139 · SCR-105"]
  F --> G["Show the open comments, proposals and discrepancies<br/>on their items, and apart the open comments<br/>whose item is no longer in the picture<br/>REQ-145, REQ-162 · SCR-105"]
  G --> I{"What does the user do?"}
  I -->|selects an item| J["Show the item with its comments,<br/>proposals and discrepancies<br/>REQ-145 · SCR-106"]
  J --> I
  I -->|leaves a comment| K["Leave a comment, FL-107"]
  I -->|opens a proposal| L["Accept or dismiss it, FL-110"]
  I -->|opens the stage overview| M["Pass the checkpoint, FL-113"]
  I -->|edits on a PC| P["Edit the picture where<br/>editing is included, FL-115"]
  I -->|leaves| Z
  K --> Z
  L --> Z
  M --> Z
  P --> Z
```

The view shows the projects' text and the comments only as text, follows the profile's language, and works at every width from 320 to 1440 pixels without sideways scrolling of the page (REQ-146, REQ-148, REQ-150); a picture larger than the screen moves inside its own frame.
