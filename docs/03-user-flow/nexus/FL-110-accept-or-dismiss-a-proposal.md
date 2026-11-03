# FL-110 Accept or dismiss a proposal

[한국어](FL-110-accept-or-dismiss-a-proposal.ko.md)

Serves: REQ-117, REQ-129, REQ-145, REQ-159, REQ-169

Context: CTX-014 Discussion, and CTX-010 Editing for an accepted proposal. Starts when the user opens a proposal in the picture view (FL-106), on a phone or a PC. New in NEXUS 0.2.

```mermaid
flowchart TD
  A(["The user opens a proposal on a picture,<br/>with its reason, FL-106<br/>REQ-145 · SCR-108"]) --> B["The user accepts or dismisses it<br/>REQ-159 · SCR-108"]
  B --> C{"Does the request come from the user's own<br/>sign-in, and not from another site?<br/>REQ-117, REQ-129"}
  C -->|no| R["Refuse it<br/>REQ-129"]
  R --> Z(["End"])
  C -->|yes, accepted| E["Record the edit that it proposes<br/>as a pending reflection<br/>REQ-169"]
  E --> F["Show the picture as proposed,<br/>marked as not yet reflected<br/>SCR-105"]
  F --> G["It waits in the agent to-do until<br/>the agent reflects it, FL-111"]
  G --> Z
  C -->|yes, dismissed| H["Close the proposal as dismissed;<br/>the comment that it answered stays open"]
  H --> Z
```

How an accepted proposal shows on a picture whose content comes only from the stage sources, and what a dismissal tells the agent, are point 10 of the [README](README.md#points-for-the-functional-spec).
