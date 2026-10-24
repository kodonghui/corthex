# FL-001 Turn memory on for a project

[한국어](FL-001-turn-memory-on.ko.md)

Serves: REQ-005, REQ-009, REQ-043, REQ-047, REQ-048, REQ-049, REQ-050, REQ-051, REQ-057

Context: CTX-005 Control. Starts when the user asks the memory skill to turn memory on.

```mermaid
flowchart TD
  A(["User asks to turn memory on<br/>for the session's folder"]) --> B{"Is the folder in a project<br/>of the project list?<br/>REQ-005"}
  B -->|no| B1["Say that the folder is not a project,<br/>and how to add it with the corthex skill"]
  B1 --> Z(["End"])
  B -->|yes| C{"Consent already given<br/>on this device?<br/>REQ-048"}
  C -->|no| D["Show what goes to which API:<br/>turns to Anthropic for curation,<br/>prompts and items to OpenAI for embeddings<br/>REQ-048"]
  D --> E{"Does the user consent?"}
  E -->|no| E1["Keep the project disabled<br/>and send nothing<br/>REQ-047, REQ-049"]
  E1 --> Z
  E -->|yes| F["Record the consent and its date"]
  C -->|yes| G["Enable the project in the memory<br/>configuration; sync stays off<br/>REQ-047, REQ-043"]
  F --> G
  G --> H{"Both memory keys found in the memory<br/>key variables or the secure storage?<br/>REQ-050"}
  H -->|yes| I["Say what is recorded, for how long,<br/>and how to leave folders out<br/>REQ-009, REQ-057"]
  H -->|no| J["Name the missing key and where to set it,<br/>never asking for it in the conversation;<br/>recording starts, the steps that need<br/>the key wait<br/>REQ-050, REQ-051"]
  I --> Z
  J --> Z
```

A key pasted into the conversation reaches the host transcript and the model request, whatever memory removes from its own raw log, so the skill never asks for one there.
