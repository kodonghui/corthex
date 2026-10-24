# FL-002 Record a turn

[한국어](FL-002-record-a-turn.ko.md)

Serves: REQ-001, REQ-002, REQ-004, REQ-005, REQ-006, REQ-007, REQ-008, REQ-010, REQ-011, REQ-012, REQ-053, REQ-057, REQ-059, REQ-064

Context: CTX-001 Capture. Starts when the user submits a prompt; the prompt hook then goes on to FL-004.

```mermaid
flowchart TD
  A(["User submits a prompt<br/>in Claude Code or Codex<br/>REQ-059"]) --> B{"Is the session's folder in an<br/>enabled project of the project list?<br/>REQ-005, REQ-006"}
  B -->|no| N["Record nothing"]
  N --> Z(["End"])
  B -->|yes| C{"Is the folder or the entry kind<br/>left out in the memory configuration?<br/>REQ-057"}
  C -->|yes| N
  C -->|no| D["Remove secrets and private spans<br/>REQ-007"]
  D --> E["Append the prompt to the project's<br/>raw log on this device<br/>REQ-001, REQ-008"]
  E --> F{"Written?"}
  F -->|no| G["Note the failure for the memory status;<br/>the prompt goes on<br/>REQ-010, REQ-053"]
  F -->|yes| H["The agent works; tool calls and<br/>tool results are not recorded<br/>REQ-004"]
  G --> H
  H --> I{"Does the turn end<br/>with a final answer?"}
  I -->|yes| J["Remove secrets and private spans,<br/>then append the final answer<br/>REQ-002, REQ-007"]
  I -->|no, the session was cut off| K["The raw log keeps every entry<br/>appended before the cut<br/>REQ-012, REQ-064"]
  J --> L{"Written?"}
  L -->|no| G2["Note the failure;<br/>the session goes on<br/>REQ-010"]
  L -->|yes| Z
  G2 --> Z
  K --> Z
```

Each hook step in this flow finishes within 100 ms at the 95th percentile (REQ-011).
