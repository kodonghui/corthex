# FL-103 Draw a project's pictures

[한국어](FL-103-draw-the-pictures.ko.md)

Serves: REQ-136, REQ-137, REQ-138, REQ-139, REQ-140, REQ-141, REQ-142, REQ-143, REQ-144, REQ-151, REQ-160, REQ-162

Context: CTX-012 Pictures. Starts when the NEXUS server stores a project's snapshot (FL-102). New in NEXUS 0.2.

```mermaid
flowchart TD
  A(["The NEXUS server stores<br/>a project's snapshot, FL-102"]) --> B{"Is it the project's first snapshot?"}
  B -->|yes| B1["Create the project's space, bound to<br/>the repository that holds its settings<br/>REQ-136"]
  B -->|no| C
  B1 --> C["Take the next picture: the DDD board<br/>from stage 01, the ERD from stage 05<br/>or the sitemap from stage 07"]
  C --> D{"Does the snapshot hold<br/>the picture's stage source?"}
  D -->|no| D1["No picture for that stage yet"]
  D -->|yes| E{"Is the stage source in<br/>the space's repository?<br/>REQ-144"}
  E -->|no| E1["Leave the picture out,<br/>naming the source it left out<br/>REQ-144"]
  E -->|yes| F{"Did the stage source change since<br/>the picture was last drawn?<br/>REQ-137"}
  F -->|no| N{"Another picture left?"}
  F -->|yes| G["Draw the picture only from the stage source: the DDD<br/>board's contexts with command rows, policies, dependencies<br/>and hotspots; the ERD's tables with columns, keys and<br/>relations; the sitemap's screens with ID, name, path<br/>and who can see them, from each parent to each child<br/>REQ-138, REQ-140, REQ-141, REQ-142"]
  G --> H["Lay it out automatically<br/>REQ-143"]
  H --> I["Bind it to its document version:<br/>the commit and the commit's time<br/>REQ-139"]
  I --> J["Attach the open comments to their items by<br/>trace ID; a comment whose item is gone<br/>stays open, apart, with the item's ID<br/>REQ-160, REQ-162"]
  J --> K["Cross-check the pictures, FL-104<br/>REQ-151"]
  K --> N
  D1 --> N
  E1 --> N
  N -->|yes| C
  N -->|no| Z(["End"])
```

Only NEXUS draws: the agent never draws a picture by hand. Where the drawing and the layout run, on the server or in the picture view, is point 1 of the [README](README.md#points-for-the-functional-spec); what the board needs from the stage 01 template is point 5, and a picture left out for size is point 8. Where editing is included, the positions that the user moved stay in the space (FL-115).
