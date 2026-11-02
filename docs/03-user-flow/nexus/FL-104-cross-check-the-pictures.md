# FL-104 Cross-check the pictures

[한국어](FL-104-cross-check-the-pictures.ko.md)

Serves: REQ-151, REQ-152, REQ-153, REQ-155, REQ-156, REQ-157

Context: CTX-013 Cross-checking. Starts when a picture is drawn or drawn again (FL-103). New in NEXUS 0.2.

```mermaid
flowchart TD
  A(["A picture is drawn or drawn again, FL-103<br/>REQ-151"]) --> B{"Has the project another picture<br/>to pair it with?"}
  B -->|no| Z(["End"])
  B -->|yes| C["Pair each aggregate on the DDD board with the ERD<br/>tables that name its glossary term, and each read model<br/>with the sitemap screens that name its glossary term<br/>REQ-152, REQ-153"]
  C --> E["Take the next pair, or the next item<br/>whose other half is missing"]
  E --> F{"Does the pair disagree, or is its other half<br/>missing, such as an ERD table with<br/>no matching aggregate?<br/>REQ-155"}
  F -->|no| N{"Another pair left?"}
  F -->|yes| G{"Is a discrepancy already open<br/>for this pair?<br/>REQ-156"}
  G -->|no| G1["Open a discrepancy<br/>with the IDs concerned<br/>REQ-155"]
  G -->|yes| G2["Keep the open one, since only one<br/>is open for each pair<br/>REQ-156"]
  G1 --> N
  G2 --> N
  N -->|yes| E
  N -->|no| R["Mark resolved each open discrepancy<br/>that this cross-check no longer finds<br/>REQ-157"]
  R --> Z
```

The tables and the screens name their terms because the stage 05 and 07 skills have the agent write them (FL-112). The tables and screens that stand for no term, and what disagreeing means for each pair and how serious a discrepancy is, are points 6 and 7 of the [README](README.md#points-for-the-functional-spec).
