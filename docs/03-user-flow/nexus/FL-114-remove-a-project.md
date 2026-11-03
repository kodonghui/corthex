# FL-114 Remove a project from the NEXUS server

[한국어](FL-114-remove-a-project.ko.md)

Serves: REQ-105, REQ-113, REQ-120, REQ-206

Context: CTX-009 Sharing. Starts when the user asks to remove a project from the NEXUS server. Built in phase 1 for snapshots; NEXUS 0.2 deletes the project space as well (REQ-120).

```mermaid
flowchart TD
  A(["The user asks to remove a project<br/>from the NEXUS server"]) --> B["Show a dry run of what the removal deletes:<br/>the snapshot and the project space, with its pictures,<br/>comments, proposals, pending reflections<br/>and passed checkpoints<br/>REQ-206"]
  B --> C{"Does the user confirm?"}
  C -->|no| C1["Send nothing"]
  C1 --> Z(["End"])
  C -->|yes| D["Send the removal to the NEXUS server,<br/>and nothing else off the device<br/>REQ-105"]
  D --> E{"Did Cloudflare Access check the request?<br/>REQ-113"}
  E -->|no| E1["The server refuses it, and<br/>the hub says why"]
  E1 --> Z
  E -->|yes| F["Delete the snapshot and the project space<br/>REQ-120"]
  F --> G["The project's sources and<br/>the device's files stay"]
  G --> H{"Is the project still in the push list?"}
  H -->|yes| H1["Say that the next push puts it back,<br/>and how to take it off the push list"]
  H -->|no| Z
  H1 --> Z
```

The decisions on its comments stay where the agent wrote them, in Git and in the project's records; open comments and pending reflections go with the space. Point 17 of the [README](README.md#points-for-the-functional-spec) lists them before the user confirms.
