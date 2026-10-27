# FL-003 Start a session with memory

[한국어](FL-003-start-a-session.ko.md)

Serves: REQ-003, REQ-005, REQ-006, REQ-009, REQ-026, REQ-027, REQ-028, REQ-029, REQ-030, REQ-036, REQ-037, REQ-038, REQ-039, REQ-057, REQ-196

Context: CTX-003 Recall. Starts when a session starts, resumes, forks, is cleared or is compacted. The base of the start summary is built in 0.1.0; the memory part is new.

```mermaid
flowchart TD
  A(["A session starts, resumes, forks,<br/>is cleared or is compacted<br/>REQ-027"]) --> B["Build the base: principles, profile<br/>and project settings in fixed formats<br/>REQ-027, REQ-039"]
  B --> C{"Is the session's folder<br/>in an enabled project?<br/>REQ-005, REQ-006"}
  C -->|no| S["Inject the start summary"]
  S --> Z(["End"])
  C -->|yes| X{"Does the memory configuration leave out<br/>the session's folder or session boundaries?<br/>REQ-057"}
  X -->|yes| E
  X -->|no| D["Append a session boundary<br/>to the raw log<br/>REQ-003"]
  D --> E{"Is the memory store readable?"}
  E -->|no| E1["Leave memory out<br/>and say it could not be read"]
  E1 --> S
  E -->|yes| F["Add the current state and the pinned items,<br/>current items of this project only,<br/>marked as reference material<br/>REQ-028, REQ-036, REQ-037, REQ-038"]
  F --> G{"Since the last session, did curation<br/>fail, stop or wait for a key?"}
  G -->|yes| G1["Say so, and how to resume<br/>REQ-029"]
  G -->|no| H{"A week since the<br/>last consolidation?"}
  G1 --> H
  H -->|yes| H1["Start consolidation<br/>in the background, FL-006<br/>REQ-026"]
  H -->|no| I["In the background, delete raw log<br/>entries past the retention period<br/>REQ-009"]
  H1 --> I
  I --> J["Fit the summary under 8,000 bytes,<br/>shortening memory before the base<br/>REQ-030"]
  J --> S
```

When the start summary injects items, it logs where and which item IDs, without their text (REQ-196).
