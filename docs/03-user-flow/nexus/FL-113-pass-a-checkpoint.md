# FL-113 Pass a stage's checkpoint

[한국어](FL-113-pass-a-checkpoint.ko.md)

Serves: REQ-084, REQ-086, REQ-089, REQ-090, REQ-117, REQ-125, REQ-173, REQ-176, REQ-177, REQ-178, REQ-179, REQ-180

Context: CTX-007 Stage progress. Starts when the user looks at whether a stage is ready, in the stage overview of NEXUS or in the session with the agent. New in NEXUS 0.2.

```mermaid
flowchart TD
  A(["The user looks at whether a stage is ready"]) --> B{"Where?"}
  B -->|in NEXUS| C["Open the stage overview: the stage's open<br/>discrepancies, comments and pending<br/>reflections, together<br/>REQ-176"]
  C --> D{"Does the user pass the checkpoint,<br/>with or without what is left?<br/>REQ-177"}
  D -->|no| D1["The stage stays as it is, and the user<br/>may leave a comment, FL-107"]
  D1 --> Z(["End"])
  D -->|yes| E{"Does the request come from the user's own<br/>sign-in, and not from another site?<br/>REQ-117, REQ-179"}
  E -->|no| E1["Refuse it<br/>REQ-179"]
  E1 --> Z
  E -->|yes| F["Record who passed it and when<br/>REQ-178"]
  F --> G["List it in the agent to-do until<br/>the stage record holds it<br/>REQ-180"]
  G --> H["At its next work, FL-108, the agent writes the<br/>checkpoint into the stage record, with a reference<br/>to the checkpoint recorded in NEXUS<br/>REQ-086, REQ-090"]
  B -->|in the session| I["The agent writes the checkpoint into the<br/>stage record, with a reference to the record<br/>that holds the user's approval<br/>REQ-086, REQ-090"]
  H --> J["The pull request is merged, and the agent<br/>pushes the new snapshot, FL-102<br/>REQ-125"]
  I --> J
  J --> K["The hub reads the record from the repository and<br/>shows the stage as recorded, the same on<br/>every device and on the server<br/>REQ-084, REQ-089, REQ-173"]
  K --> Z
```

Only the user passes a checkpoint; an AI recommendation, a read receipt or an edit time is not one. How the stage overview shows a checkpoint passed in NEXUS before the agent records it is point 15 of the [README](README.md#points-for-the-functional-spec).
