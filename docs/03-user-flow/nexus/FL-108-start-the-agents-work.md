# FL-108 Start the agent's work on a project

[한국어](FL-108-start-the-agents-work.ko.md)

Serves: REQ-131, REQ-180, REQ-181, REQ-182, REQ-183, REQ-185, REQ-193

Context: CTX-007 Stage progress, which serves the agent to-do, with CTX-014 Discussion and CTX-010 Editing. Starts when the agent starts its work on a project in a session, following a stage skill. New in NEXUS 0.2.

```mermaid
flowchart TD
  A(["The agent starts its work on a project<br/>in a session, following a stage skill<br/>REQ-181"]) --> B{"Is the project in the push list, with a stage<br/>source newer than the pushed snapshot?<br/>REQ-193"}
  B -->|yes| B1["Push the project's snapshot, FL-102<br/>REQ-193"]
  B -->|no| D
  B1 --> D["Read the agent to-do through the hub,<br/>with the service token<br/>REQ-183"]
  D --> E{"Could the hub read it?"}
  E -->|no, no token here or no answer from the server| E1["Say so, and go on with the work<br/>REQ-185"]
  E1 --> Z(["End"])
  E -->|yes| F["List the open comments first, then the open<br/>discrepancies, then the pending reflections, and<br/>the checkpoints passed in NEXUS that the stage<br/>records do not hold yet<br/>REQ-180, REQ-182"]
  F --> G{"Is anything waiting?"}
  G -->|no| Z
  G -->|yes| H["Tell the user in the session what is waiting"]
  H --> I["Answer the open comments, FL-109"]
  I --> J["Look into the open discrepancies: fix the stage<br/>source by stage work, FL-112, or take it up<br/>on the discrepancy, FL-109"]
  J --> K["Reflect the pending reflections<br/>by pull request, FL-111<br/>REQ-131"]
  K --> L["Write the passed checkpoints into<br/>the stage records, FL-113"]
  L --> Z
```

A project that is not on the NEXUS server has no agent to-do, and a device without the service token, such as a cloud session, cannot read it. Two agents that start on one project at once, and what counts as the start of the agent's work and how the to-do meets what the user asked in the session, are points 12 and 13 of the [README](README.md#points-for-the-functional-spec).
