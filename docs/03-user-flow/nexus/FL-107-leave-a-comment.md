# FL-107 Leave a comment on a picture

[한국어](FL-107-leave-a-comment.ko.md)

Serves: REQ-117, REQ-145, REQ-158, REQ-160, REQ-161, REQ-163, REQ-182

Context: CTX-014 Discussion. Starts when the user selects a part of a picture in the picture view (FL-106) to comment on it, on a phone or a PC. The agent leaves its comments through the hub (FL-109). New in NEXUS 0.2.

```mermaid
flowchart TD
  A(["The user selects a part of a picture to<br/>comment on, on a phone or a PC, FL-106<br/>REQ-158"]) --> B{"Has the part a trace ID of its own?"}
  B -->|yes| C["Attach the comment to the item's<br/>trace ID, not to a position<br/>REQ-160"]
  B -->|no, such as an event on the DDD board| D["Attach it to the item that holds the part,<br/>with a quote of the part<br/>REQ-161"]
  C --> E["The user writes the comment and sends it<br/>SCR-106"]
  D --> E
  E --> F{"Does the NEXUS server take it: checked<br/>by Cloudflare Access, and not<br/>sent from another site?<br/>REQ-117"}
  F -->|no| F1["Say that the comment was not saved,<br/>and keep its text in the page<br/>SCR-106"]
  F1 --> Z(["End"])
  F -->|yes| G["Mark the user as its author, from the kind<br/>of Cloudflare Access sign-in<br/>REQ-163"]
  G --> H["Show it open on its item<br/>REQ-145 · SCR-106"]
  H --> I["It waits in the agent to-do, where open comments<br/>come first, until the agent's next work, FL-108<br/>REQ-182"]
  I --> Z
```

The agent reads comments only when its work starts, so anything urgent goes in the conversation instead (hotspot 6 of stage 01). What is kept when a comment cannot be saved is point 14 of the [README](README.md#points-for-the-functional-spec).
