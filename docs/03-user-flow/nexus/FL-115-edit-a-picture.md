# FL-115 Edit a picture on a PC

[한국어](FL-115-edit-a-picture.ko.md)

Serves: REQ-127, REQ-130, REQ-171, REQ-172

Context: CTX-010 Editing. Where editing is included, in phase ②; not in NEXUS 0.2. Starts when the user opens a picture to edit it in the picture view (FL-106).

```mermaid
flowchart TD
  A(["Where editing is included, the user opens<br/>a picture to edit it, FL-106<br/>REQ-127"]) --> B{"Is the window at least<br/>1024 pixels wide?<br/>REQ-171"}
  B -->|no| B1["Keep the picture read-only<br/>REQ-171 · SCR-105"]
  B1 --> Z(["End"])
  B -->|yes| C["Open it in the open-source editor:<br/>Excalidraw for the DDD board and the sitemap,<br/>ERD Editor for the ERD<br/>REQ-127 · SCR-105"]
  C --> D{"What does the user change?"}
  D -->|only positions| E["Keep the new positions in the project space,<br/>without changing the stage sources<br/>REQ-172"]
  E --> Z
  D -->|the content| F["Save the edit, bound to the document<br/>version that the picture was drawn from"]
  F --> G{"Is that document version<br/>still the latest?<br/>REQ-130"}
  G -->|no| H["Show the edit over the new picture<br/>as an edit conflict<br/>REQ-130 · SCR-105"]
  H --> I{"What does the user choose?"}
  I -->|keep the edit| J
  I -->|edit again| C
  I -->|drop it| I1["Close the edit"]
  I1 --> Z
  G -->|yes| J["Record it as a pending reflection,<br/>for the agent's next work, FL-111"]
  J --> Z
```

Phase ② turns on editing in the editors that phase ① uses read-only (D11 of stage 02). The flow is drawn now so that the data of NEXUS 0.2, such as positions and document versions, leaves room for it.
