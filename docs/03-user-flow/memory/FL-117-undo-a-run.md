# FL-117 Undo a run

[한국어](FL-117-undo-a-run.ko.md)

Serves: REQ-037, REQ-224, REQ-225

Context: CTX-005 Control. Starts when the user asks to undo what a curation or consolidation did.

```mermaid
flowchart TD
  A(["The user asks to undo a run"]) --> B["List recent runs; the user chooses"]
  B --> C["Preview the inverse and what later changes stay<br/>REQ-225"]
  C --> D{"Does the user confirm?"}
  D -->|no| Z(["End"])
  D -->|yes| E["Take curation then layer locks;<br/>recheck the preview and revisions"]
  E --> F["Reverse as a new run, preserving forgotten content<br/>and later changes; restore lines from local history;<br/>processed turns stay processed<br/>REQ-225, REQ-037"]
  F --> G["Log IDs only<br/>REQ-224"]
  G --> H["Update item list, index and candidates;<br/>discard pre-undo request results"]
  H --> Z
```

A missing/expired run returns run-not-found with recent runs; busy curation returns lock-busy, and preview drift returns confirm-stale with a new confirmation. Preserve objects with unprovable or later revisions and lines whose history is missing, and say why. If everything stays, return nothing. An undo can itself be undone (SPEC-145).
