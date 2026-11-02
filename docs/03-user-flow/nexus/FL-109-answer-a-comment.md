# FL-109 Answer a comment

[한국어](FL-109-answer-a-comment.ko.md)

Serves: REQ-128, REQ-163, REQ-164, REQ-165, REQ-166, REQ-167, REQ-168, REQ-184

Context: CTX-014 Discussion. Starts when the agent takes an open comment from its agent to-do (FL-108); the user can also bring a comment up in the session. New in NEXUS 0.2.

```mermaid
flowchart TD
  A(["The agent takes the next open comment<br/>from its agent to-do, FL-108"]) --> B{"What does the comment need?"}
  B -->|an answer| C["Answer it on the comment through the hub;<br/>the server marks the agent as its author<br/>REQ-163, REQ-184 · SCR-107"]
  C --> C1["Mark the comment answered,<br/>and NEXUS closes it<br/>REQ-166"]
  C1 --> Z(["End"])
  B -->|a change to a picture| D["Make a proposal with its reason,<br/>through the hub<br/>REQ-128, REQ-184"]
  D --> D1{"Does the server take it as a proposal<br/>with its reason, from the agent?<br/>REQ-128"}
  D1 -->|no| D2["Tell the user in the session<br/>why it was refused"]
  D2 --> Z
  D1 -->|yes| D3["The proposal waits for the user,<br/>and the comment stays open, FL-110"]
  D3 --> Z
  B -->|the user's choice, or a long talk| E["Take it up with the user in the session"]
  E --> F{"Did the user settle it?"}
  F -->|not yet| F1["The comment stays open, and<br/>the talk goes on in the session"]
  F1 --> Z
  B -->|the user's reply settles it| G
  F -->|yes| G["Write the decision where the project's rules put it:<br/>changes to the stage sources by pull request,<br/>the user's choices in the project's records<br/>REQ-167"]
  G --> H["Record the decision on the comment,<br/>with a link to where it was written<br/>REQ-164, REQ-168 · SCR-107"]
  H --> I["NEXUS closes the comment<br/>REQ-165"]
  I --> Z
```

The agent's own comments, such as one that raises a question on a discrepancy, go through the hub the same way and carry the agent as their author. Replies on a comment, and whether the user can open again a comment that the agent marked answered, are point 9 of the [README](README.md#points-for-the-functional-spec).
