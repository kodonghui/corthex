# FL-006 Consolidate a project

[한국어](FL-006-consolidate-a-project.ko.md)

Serves: REQ-014, REQ-015, REQ-017, REQ-019, REQ-021, REQ-022, REQ-023, REQ-024, REQ-026, REQ-049, REQ-050, REQ-052

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
  F -->|yes| G["Merge duplicate items into one that keeps every<br/>quote passing the quote check; mark the others<br/>superseded, never delete them<br/>REQ-017, REQ-019"]
  G --> H["Shorten the current state,<br/>keeping each line's provenance<br/>REQ-015"]
  H --> I["Update the item list and the search index,<br/>and record the consolidation date"]
  I --> Z
```
