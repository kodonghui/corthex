# FL-012 Sync memory between devices

[한국어](FL-012-sync-memory.ko.md)

Serves: REQ-015, REQ-040, REQ-042, REQ-043, REQ-044, REQ-045, REQ-046, REQ-049, REQ-050, REQ-052, REQ-054

Context: CTX-004 Sync. Starts at a sync point on a device, such as a session start or the end of a curation; the functional spec fixes the sync points. The flow follows the recommendation of decision D3: the sync remote is a private Git repository of the user's.

```mermaid
flowchart TD
  A(["A sync point is reached on a device"]) --> B{"Has the user turned sync on?<br/>REQ-043"}
  B -->|no| B1["Nothing leaves the device"]
  B1 --> Z(["End"])
  B -->|yes| C["Pull the curated layer from<br/>the user's private sync remote<br/>REQ-042"]
  C --> D{"Was the remote reached?"}
  D -->|no| D1["Go on with the local memory and note it<br/>for the status; the next sync point tries again"]
  D1 --> Z
  D -->|yes| E["Merge the changes of both sides<br/>without losing an item<br/>REQ-046"]
  E --> F["Apply the tombstones: remove forgotten items,<br/>their search index entries and the raw log text<br/>they quote on this device<br/>REQ-045, REQ-054"]
  F --> F1["Remove or rewrite the lines of the current state<br/>that cite a forgotten item, and update the item list,<br/>as FL-009 does<br/>REQ-015"]
  F1 --> G["Rebuild the search index entries of changed items<br/>on this device; with consent and an OpenAI memory key,<br/>embed them and append that call to the usage log<br/>REQ-044, REQ-040, REQ-049, REQ-050, REQ-052"]
  G --> H["Push the curated layer only,<br/>never raw logs or the search index<br/>REQ-044"]
  H --> I{"Was the push accepted?"}
  I -->|yes| Z
  I -->|no, the remote moved on| J{"Tried three times<br/>at this sync point?"}
  J -->|no| C
  J -->|yes| D1
```
