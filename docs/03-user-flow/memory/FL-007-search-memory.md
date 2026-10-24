# FL-007 Search memory

[한국어](FL-007-search-memory.ko.md)

Serves: REQ-008, REQ-036, REQ-037, REQ-038, REQ-040, REQ-041

Context: CTX-003 Recall. Starts when the user asks the agent to look something up in memory, and the agent follows the memory skill.

```mermaid
flowchart TD
  A(["User asks the agent to look something up<br/>in memory; the agent follows the memory skill"]) --> B{"Is the session's<br/>project enabled?"}
  B -->|no| B1["Say that memory is off for this project,<br/>and how to turn it on, FL-001"]
  B1 --> Z(["End"])
  B -->|yes| C["Read the project's item list first,<br/>one line per current item<br/>REQ-041, REQ-036"]
  C --> D{"Does the list show<br/>the items needed?"}
  D -->|no| E["Search the project's search index<br/>by words and by meaning<br/>REQ-040, REQ-036"]
  E --> F{"Anything found?"}
  F -->|no| F1["Say that memory holds nothing on it"]
  F1 --> Z
  F -->|yes| G["Open only the chosen items;<br/>a superseded or withdrawn one<br/>is shown as such<br/>REQ-037"]
  D -->|yes| G
  G --> H{"Do the exact words matter?"}
  H -->|yes| H1["Read around the quote in the raw log,<br/>when this device wrote it<br/>REQ-008, REQ-038"]
  H -->|no| I["Answer with each item's provenance,<br/>as reference material<br/>REQ-038"]
  H1 --> I
  I --> Z
```

Search runs through the memory skill, not a hook, so it may show a superseded or withdrawn item when the user asks about it; the item is marked, and it is never injected (REQ-037).
