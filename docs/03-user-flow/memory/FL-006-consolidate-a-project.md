# FL-006 Consolidate a project

[한국어](FL-006-consolidate-a-project.ko.md)

Serves: REQ-014, REQ-015, REQ-017, REQ-019, REQ-021, REQ-022, REQ-023, REQ-024, REQ-026, REQ-040, REQ-049, REQ-050, REQ-052, REQ-220, REQ-221, REQ-224

Context: CTX-002 Curation. Starts from FL-003 when a session starts and a week has passed since the project's last consolidation. A consolidation is a curation, so the rules of FL-005 on running, failing and paying hold here too.

```mermaid
flowchart TD
  A(["A session starts and a week has passed<br/>since the project's last consolidation, FL-003<br/>REQ-026"]) --> B{"Is a curation running<br/>for this project?<br/>REQ-021"}
  B -->|yes| B1["Start nothing;<br/>a later session start tries again"]
  B1 --> Z(["End"])
  B -->|no| C{"Consent given, an Anthropic memory key,<br/>and curation not stopped by the fault guard?<br/>REQ-049, REQ-050, REQ-024"}
  C -->|no| B1
  C -->|yes| D["In a background process, ask the curator model<br/>with the current items and the current state,<br/>under 100,000 input tokens<br/>REQ-014, REQ-022"]
  D --> E["Append the call to the usage log<br/>REQ-052"]
  E --> F{"Did the request succeed?"}
  F -->|no| F1["Change nothing, and count the failure<br/>as a failed curation<br/>REQ-023, REQ-024"]
  F1 --> Z
  F -->|yes| M{"Is a proposed merge left?"}
  M -->|yes| G{"Is each of its quotes copied word for word,<br/>with its provenance, from the items it merges?<br/>REQ-017"}
  G -->|no| G1["Drop the merge;<br/>its items stay current"]
  G1 --> M
  G -->|yes| G2["Save the merged item, and mark the items<br/>it merges superseded, never deleted<br/>REQ-019"]
  G2 --> M
  M -->|no| CF["Record disagreement pairs not merged by this answer<br/>as conflict candidates<br/>REQ-221"]
  CF --> H["Use the last state-1 request to shorten state;<br/>first keep previous text of changed/omitted lines<br/>REQ-015, REQ-220"]
  H --> I["Update the item list; once an OpenAI memory key<br/>is there, embed the merged items for the search index<br/>and append that call to the usage log<br/>REQ-040, REQ-050, REQ-052"]
  I --> RL["Log the actual changed IDs of the run<br/>REQ-224"]
  RL --> K["Record the consolidation date<br/>REQ-026"]
  K --> Z
```

Consolidation reads items, not raw turns, so a merged item can carry only quotes that the items it merges already have. Those quotes passed the quote check when they were first saved, perhaps on another device or from raw log entries deleted since (REQ-008, REQ-009), so they keep their provenance and are not checked against this device's raw log again.
