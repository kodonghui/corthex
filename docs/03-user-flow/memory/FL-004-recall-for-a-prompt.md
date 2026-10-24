# FL-004 Recall memory for a prompt

[한국어](FL-004-recall-for-a-prompt.ko.md)

Serves: REQ-007, REQ-031, REQ-032, REQ-033, REQ-034, REQ-035, REQ-036, REQ-037, REQ-038, REQ-040, REQ-049, REQ-050

Context: CTX-003 Recall. Starts in the same prompt hook, after FL-002. The flow follows the recommendation of decision D2: embeddings and rules choose the items, and no model is asked for each prompt.

```mermaid
flowchart TD
  A(["User submits a prompt;<br/>FL-002 has recorded it"]) --> B{"Enabled project, consent given<br/>and an OpenAI memory key?<br/>REQ-049, REQ-050"}
  B -->|no| N["Inject nothing;<br/>the prompt goes on<br/>REQ-032"]
  N --> Z(["End"])
  B -->|yes| C["Embed the prompt, after redaction,<br/>with the OpenAI embeddings API<br/>REQ-040, REQ-007"]
  C --> D{"Back in time,<br/>without an API error?<br/>REQ-034, REQ-035"}
  D -->|no| T["Inject nothing and note it;<br/>the prompt goes on<br/>REQ-035"]
  T --> Z
  D -->|yes| E["Score the current items of this<br/>project in the search index<br/>REQ-036, REQ-037"]
  E --> F{"Is any item at or above<br/>the recall threshold?<br/>REQ-031, REQ-032"}
  F -->|no| N
  F -->|yes| G["Take five items at most,<br/>under 600 tokens<br/>REQ-031, REQ-033"]
  G --> H["Inject them as reference material,<br/>with where to read the original<br/>REQ-038"]
  H --> Z
```

The whole prompt hook, FL-002 and this flow together, finishes within 1 second at the 95th percentile (REQ-034).
