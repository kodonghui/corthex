# FL-008 Pin or unpin an item

[한국어](FL-008-pin-an-item.ko.md)

Serves: REQ-028, REQ-030, REQ-037, REQ-065

Context: CTX-005 Control. Starts when the user asks to pin an item, so that every start summary of the project shows it, or to unpin one.

```mermaid
flowchart TD
  A(["User asks to pin or unpin an item"]) --> B{"Is it an item of<br/>the session's project?"}
  B -->|no| B1["Show the closest lines of the item list<br/>and ask which one is meant"]
  B1 --> Z(["End"])
  B -->|yes| C{"Pin or unpin?"}
  C -->|pin| D{"Is the item current?<br/>REQ-037"}
  D -->|no| D1["Say that it was superseded or withdrawn,<br/>and offer the current item instead"]
  D1 --> Z
  D -->|yes| E{"Does the start summary still fit<br/>under 8,000 bytes with it?<br/>REQ-030"}
  E -->|no| E1["Say so, and which pinned items<br/>could be unpinned first"]
  E1 --> Z
  E -->|yes| F["Add it to the project's pinned items;<br/>every start summary shows it<br/>REQ-065, REQ-028"]
  F --> Z
  C -->|unpin| G["Remove it from the pinned items<br/>REQ-065"]
  G --> Z
```
