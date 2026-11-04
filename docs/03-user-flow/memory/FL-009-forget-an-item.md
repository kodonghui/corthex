# FL-009 Forget an item

[한국어](FL-009-forget-an-item.ko.md)

Serves: REQ-015, REQ-045, REQ-054, REQ-220

Context: CTX-005 Control. Starts when the user asks to forget something that memory holds.

```mermaid
flowchart TD
  A(["User asks to forget an item"]) --> B{"Is the item found<br/>in the session's project?"}
  B -->|no| B1["Show the closest lines of the item list<br/>and ask which one is meant"]
  B1 --> Z(["End"])
  B -->|yes| C["Preview the item, index, quoted raw text,<br/>history records removed and candidates settled<br/>REQ-054"]
  C --> D{"Does the user confirm?"}
  D -->|no| D1["Change nothing"]
  D1 --> Z
  D -->|yes| E["Remove the item and<br/>its search index entries<br/>REQ-054"]
  E --> F["Remove the quoted text from<br/>the raw log on this device<br/>REQ-054"]
  F --> G["Leave a tombstone, so that sync<br/>does not bring the item back<br/>REQ-045"]
  G --> H["Remove citing state lines and their kept prior texts;<br/>settle candidates and update the item list<br/>REQ-015, REQ-054, REQ-220"]
  H --> Z
```

The raw text is removed on this device at once and on the user's other devices when sync applies the tombstone there (FL-012). Without sync, each device's raw log keeps its own copy until that device forgets the item too.
