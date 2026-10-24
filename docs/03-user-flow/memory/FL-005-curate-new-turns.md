# FL-005 Curate new turns

[한국어](FL-005-curate-new-turns.ko.md)

Serves: REQ-013, REQ-014, REQ-015, REQ-016, REQ-017, REQ-018, REQ-019, REQ-020, REQ-021, REQ-022, REQ-023, REQ-024, REQ-025, REQ-029, REQ-040, REQ-049, REQ-050, REQ-052

Context: CTX-002 Curation. Starts when an enabled project has unprocessed raw turns and a curation trigger is met; which events are triggers is left to the functional spec. The flow follows the recommendation of decision D4: the Anthropic memory key pays for the curator's requests.

```mermaid
flowchart TD
  A(["An enabled project has unprocessed raw turns<br/>and a curation trigger is met<br/>REQ-013"]) --> B{"Is a curation already running<br/>for this project?<br/>REQ-021"}
  B -->|yes| B1["Start nothing;<br/>the running curation takes the turns later"]
  B1 --> Z(["End"])
  B -->|no| C{"Has the fault guard<br/>stopped this project?<br/>REQ-024"}
  C -->|yes| C1["Start nothing; curation waits<br/>until the user resumes it, FL-010"]
  C1 --> Z
  C -->|no| D{"Consent given and<br/>an Anthropic memory key?<br/>REQ-049, REQ-050"}
  D -->|no| D1["Start nothing; the turns wait,<br/>and the next start summary says so<br/>REQ-029"]
  D1 --> Z
  D -->|yes| E["Start the curator in a background process<br/>that the host does not wait for<br/>REQ-013"]
  E --> F["Take the current state, the item list<br/>and the next unprocessed turns,<br/>under 100,000 input tokens<br/>REQ-022"]
  F --> G["Ask the curator model: Claude Haiku 5.5 at xhigh<br/>unless the memory configuration names another;<br/>no spending check<br/>REQ-014, REQ-025"]
  G --> H["Append the model, the token counts<br/>and the estimated cost to the usage log<br/>REQ-052"]
  H --> I{"Did the request succeed?"}
  I -->|no| I1["Keep the turns unprocessed<br/>for the next curation<br/>REQ-023"]
  I1 --> I2{"Third failure in a row<br/>on the same turns?<br/>REQ-024"}
  I2 -->|no| Z
  I2 -->|yes| I3["Stop curating this project and note it<br/>for the status and the start summary<br/>REQ-024, REQ-029"]
  I3 --> Z
  I -->|yes| J[["Apply the proposed changes one at a time,<br/>as the second chart shows<br/>REQ-016 to REQ-020"]]
  J --> P["Update the current state,<br/>each line with its provenance<br/>REQ-015"]
  P --> Q["Update the item list; embed the new items<br/>for the search index once an OpenAI memory key is there<br/>REQ-040, REQ-050"]
  Q --> R["Mark the turns processed"]
  R --> S{"More unprocessed turns?"}
  S -->|yes| F
  S -->|no| Z
```

## Applying one proposed change

The curator model's answer proposes changes to the item list. Each change goes through this chart before the next one.

```mermaid
flowchart TD
  A(["The next proposed change"]) --> J{"Does its quote appear<br/>word for word in the raw log?<br/>REQ-017"}
  J -->|no| J1["Drop the change"]
  J -->|yes| K{"What does the change do?"}
  K -->|adds an item| L{"A decision in the<br/>user's own words?<br/>REQ-018"}
  L -->|yes| L1["Save it as a user decision<br/>REQ-016, REQ-018"]
  L -->|no| L2["Save it with its speaker, kind,<br/>provenance and status<br/>REQ-016"]
  K -->|replaces an item| M["Save the new item and mark<br/>the earlier one superseded<br/>REQ-019"]
  K -->|takes an item back| N{"Taken back by the<br/>item's own speaker?<br/>REQ-020"}
  N -->|yes| N1["Mark the item withdrawn<br/>REQ-020"]
  N -->|no| N2["Keep the item and save the new<br/>statement as an item of its own<br/>REQ-016"]
  J1 --> Z(["On to the next change"])
  L1 --> Z
  L2 --> Z
  M --> Z
  N1 --> Z
  N2 --> Z
```

The curator changes nothing it cannot quote: a proposed change whose quote check fails is dropped, and items are superseded or withdrawn, never deleted. Forgetting is the user's own act (FL-009).
