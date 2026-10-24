# FL-010 Check the memory status

[한국어](FL-010-check-the-status.ko.md)

Serves: REQ-024, REQ-050, REQ-051, REQ-052, REQ-053

Context: CTX-005 Control. Starts when the user asks for the memory status. It is also where the user resumes a curation that the fault guard stopped.

```mermaid
flowchart TD
  A(["User asks for the memory status"]) --> B["Show the enabled projects, the last curation,<br/>the unprocessed turns, this month's usage from the<br/>usage log and the recent failures of recording and curation<br/>REQ-053, REQ-052"]
  B --> C{"Does any step wait for<br/>consent or a memory key?<br/>REQ-050"}
  C -->|yes| C1["Name what is missing and where to set it,<br/>never asking for a key in the conversation<br/>REQ-050, REQ-051"]
  C -->|no| D{"Has the fault guard stopped<br/>a project's curation?<br/>REQ-024"}
  C1 --> D
  D -->|no| Z(["End"])
  D -->|yes| E["Show the failures on the same turns,<br/>and how to resume"]
  E --> F{"Does the user resume it?"}
  F -->|no| Z
  F -->|yes| G["Clear the fault guard for that project;<br/>the next trigger curates it, FL-005<br/>REQ-024"]
  G --> Z
```
