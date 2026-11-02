# FL-112 Finish a unit of stage work

[한국어](FL-112-finish-stage-work.ko.md)

Serves: REQ-085, REQ-086, REQ-087, REQ-105, REQ-125, REQ-154

Context: CTX-007 Stage progress, with the terms that CTX-013 Cross-checking pairs by. Starts when the agent finishes a unit of stage work on a project, such as a draft or a change of a stage source, or a stage's work ends. New in NEXUS 0.2; in phase 1 the agent recorded progress in the device's status file instead.

```mermaid
flowchart TD
  A(["The agent finishes a unit of stage work,<br/>or a stage's work ends<br/>REQ-086"]) --> B{"Is it stage 05 or stage 07?"}
  B -->|yes| B1["Name, for each table or screen, the glossary<br/>terms of the aggregates or read models<br/>that it stands for<br/>REQ-154"]
  B -->|no| C
  B1 --> C["Write the stage's record into the repository in<br/>the same pull request: its state, its next action<br/>and any review findings<br/>REQ-086, REQ-087"]
  C --> D{"Is the stage's work done?"}
  D -->|yes, and its checkpoint is passed| D1["Record done, with the checkpoint<br/>and its date<br/>REQ-085"]
  D -->|yes, but its checkpoint is not passed| D2["Keep it in_progress until the user<br/>passes the checkpoint, FL-113<br/>REQ-085"]
  D -->|no| D3["Record in_progress"]
  D1 --> E{"Is the pull request merged,<br/>as the project's rules say?"}
  D2 --> E
  D3 --> E
  E -->|not yet| E1["Nothing changes in NEXUS"]
  E1 --> Z(["End"])
  E -->|yes| F{"Is the project in the push list?"}
  F -->|no| F1["Nothing leaves the device<br/>REQ-105"]
  F1 --> Z
  F -->|yes| G["Push the new snapshot, FL-102; the pictures<br/>whose stage sources changed are drawn again, FL-103<br/>REQ-125"]
  G --> Z
```

The record goes in the same pull request as the work, so that the record and the sources that it describes are merged together. Where the records live in the repository, and whether a project with several parts keeps one for each part, are point 4 of the [README](README.md#points-for-the-functional-spec).
