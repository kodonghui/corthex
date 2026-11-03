# FL-116 Hold a workshop on a work board

[한국어](FL-116-hold-a-workshop.ko.md)

Serves: REQ-213, REQ-214, REQ-215, REQ-216, REQ-217, REQ-218

Context: CTX-010 Editing, until phase ② draws the work board's own steps (hotspot 14 of stage 01). Where editing is included, in phase ②; not in NEXUS 0.2. Starts when the user and the agent start a part's stage 01 event storming in NEXUS, on a PC. Drawn with the maintainer's choice of 2026-11-03.

```mermaid
flowchart TD
  A(["Where editing is included, the user and the agent<br/>start a part's stage 01 event storming in NEXUS<br/>REQ-213"]) --> B{"Is the window at least<br/>1024 pixels wide?<br/>REQ-213"}
  B -->|no| B1["Show the work board read-only,<br/>and say that a workshop needs a PC<br/>REQ-213 · SCR-105"]
  B1 --> Z(["End"])
  B -->|yes| C["Show the part's work board in Excalidraw,<br/>apart from the DDD board, which is still drawn<br/>only from the stage 01 source<br/>REQ-216 · SCR-105"]
  C --> D["Open the next step's frame,<br/>as a copy of the previous step's frame<br/>REQ-213 · SCR-105"]
  D --> E["The user places stickies in the legend's colours,<br/>arrows, groups and comments in the frame;<br/>the agent places its own through the hub<br/>REQ-214"]
  E --> F["Mark each sticky with its author, the user<br/>or the agent, from the kind of sign-in<br/>REQ-215"]
  F --> G{"Does the step end at a checkpoint:<br/>after step 1-b, 7 or 9?"}
  G -->|no| D
  G -->|yes| H["The user answers the checkpoint,<br/>in the session or in NEXUS, FL-113"]
  H --> I["The agent reads the work board through the hub<br/>and writes the stage 01 source from it<br/>by pull request, with the board's version<br/>REQ-217"]
  I --> J{"Was it the last checkpoint?"}
  J -->|no| D
  J -->|yes| K["Keep the work board read-only, as material;<br/>from now on the stage 01 source leads<br/>REQ-218 · SCR-105"]
  K --> Z
```

The agent works in the session with the user and reaches the work board only through the hub, as everywhere in NEXUS. NEXUS never calls the agent, so the agent reads what the user placed when the user tells it in the session, or at its next work (FL-108). Once a checkpoint's pull request is merged and pushed, FL-103 draws the DDD board again from the stage 01 source, so the DDD board catches up with the work board at each checkpoint.

The flow is drawn now so that the data of NEXUS 0.2 leaves room for it, as FL-115 is. Phase ② draws the work board's own steps in new frames, as stage 01's rule for adding to an existing product asks, and decides there whether the work board is a context of its own (hotspot 14 of stage 01). Team members' real-time work on a work board comes with team members; until then, team workshops stay on Miro.
