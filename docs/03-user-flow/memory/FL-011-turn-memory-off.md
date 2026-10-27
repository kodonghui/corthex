# FL-011 Turn memory off

[한국어](FL-011-turn-memory-off.ko.md)

Serves: REQ-045, REQ-055, REQ-056, REQ-058, REQ-194

Context: CTX-005 Control. Starts when the user asks to turn memory off for a project, to remove the plugin, or to delete all memory on the device.

```mermaid
flowchart TD
  A(["User asks to turn memory off"]) --> B{"For what?"}
  B -->|delete this project memory| P["Show this project memory and whether sync is on<br/>REQ-194"]
  P --> Q{"Does the user confirm?"}
  Q -->|no| Z
  Q -->|yes| R["Delete the project memory on this device and disable it;<br/>with sync on leave a project tombstone<br/>REQ-194, REQ-045"]
  R --> Z
  B -->|this project| C["Disable the project: recording and recall stop,<br/>and its memory stays on the device<br/>REQ-058"]
  C --> Z(["End"])
  B -->|the plugin| D["The user removes the plugin through the host;<br/>the memory store stays, because it lives<br/>outside the hosts' plugin data folders<br/>REQ-056"]
  D --> D1["Say where the store is,<br/>and that purging deletes it"]
  D1 --> Z
  B -->|all memory| E["Show what the memory store on this device holds:<br/>projects, items, raw logs and the usage log"]
  E --> F{"Does the user confirm?<br/>REQ-055"}
  F -->|no| F1["Change nothing"]
  F1 --> Z
  F -->|yes| G["Delete the memory store on this device<br/>REQ-055"]
  G --> H{"Was sync on?"}
  H -->|no| Z
  H -->|yes| I["Say that the sync remote and the other devices<br/>keep their copies until they are deleted there"]
  I --> Z
```
