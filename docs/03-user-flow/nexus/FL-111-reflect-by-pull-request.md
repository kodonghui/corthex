# FL-111 Reflect by pull request

[한국어](FL-111-reflect-by-pull-request.ko.md)

Serves: REQ-125, REQ-131, REQ-170, REQ-184

Context: CTX-010 Editing. Starts when the agent's work on a project starts with pending reflections in its agent to-do (FL-108): accepted proposals, and the user's edits where editing is included. New in NEXUS 0.2.

```mermaid
flowchart TD
  A(["The agent to-do holds pending reflections, FL-108<br/>REQ-131"]) --> B["Take the next pending reflection: an accepted proposal,<br/>or an edit where editing is included"]
  B --> C{"Has its stage source changed since<br/>the document version it is bound to?"}
  C -->|yes, and the change no longer fits| C1["Ask the user again, on the comment<br/>or in the session, FL-109"]
  C1 --> N
  C -->|no, or it still fits| D["Write the change into the stage source<br/>in a pull request<br/>REQ-131"]
  D --> E{"Is the pull request merged,<br/>as the project's rules say?"}
  E -->|not yet| E1["The reflection stays pending, and the agent<br/>looks at it again at its next work"]
  E1 --> N
  E -->|yes| F["Report it merged through the hub; the server<br/>closes the edit with a link to the pull request<br/>REQ-170, REQ-184"]
  F --> N{"Another pending reflection?"}
  N -->|yes| B
  N -->|no| P{"Was a reflection merged, with the<br/>project in the push list?"}
  P -->|yes| P1["Push the new snapshot, FL-102; the pictures<br/>are drawn again from the stage sources<br/>REQ-125"]
  P -->|no| Z(["End"])
  P1 --> Z
```

NEXUS never writes to Git: the agent writes every reflection by pull request, in team projects too. A reflection whose stage source moved on, and a pull request closed without being merged, are point 11 of the [README](README.md#points-for-the-functional-spec).
