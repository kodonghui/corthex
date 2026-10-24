# Event storming board

How the board of stage 01 is laid out, and how the AI reads and writes it. The steps are in [01-domain.md](01-domain.md).

## Legend

| Element | On the board | Miro colour | Where |
| --- | --- | --- | --- |
| Domain event | sticky, past tense | `orange` | on the timeline, left to right in time |
| External system | sticky | `pink` | next to the event it sends or receives |
| Command | sticky, imperative | `blue` | left of the event it causes |
| Hotspot | sticky | `red` | next to the sticky it concerns |
| Actor | small sticky | `light_yellow` | below the command it gives |
| Aggregate | large sticky | `yellow` | above the events it owns |
| Policy | sticky, `When <event>, <command>` | `violet` | between the event and the command it triggers |
| Read model | sticky | `light_green` | next to the command whose actor reads it |

A bounded context is a boundary drawn around its aggregates, commands and events, with the context's name on it. A team that already uses another legend keeps it; put it in the legend frame, which is what the AI follows.

## Layout

- One board per project. A project with several parts gives each part a column of its own, side by side.
- At the top of each column, a legend frame and a scope note: what is in, what is out, the inputs and the way of working.
- One frame per step, titled with the step, such as "Step 1-b Timeline". Each step starts as a copy of the previous step's frame, placed below it. The earlier frames stay as they were, so the board shows how the model grew.
- In draft and correct, the AI makes the copy, so the copy's items are the AI's and it may tidy and merge them there.
- Inside a frame, time runs from left to right, with one lane per flow.
- Step 8 adds the context map: one box per context, with arrows between them. Step 9 adds one table per context.

## Context map

- A solid arrow is a synchronous call and a dashed arrow an asynchronous event. The arrow points from the context that calls or sends to the context that receives, and its label names the data.
- When the relationship matters for the design, such as a context that translates the model of an outside system, add the pattern to the label: customer and supplier, conformist, anticorruption layer, open host service, published language, shared kernel, partnership or separate ways.

## Miro

Miro's official MCP server lets the AI read and write boards.

- Connect it once per host. In Claude Code: `claude mcp add --transport http miro https://mcp.miro.com/`. In Codex: `codex mcp add miro --url https://mcp.miro.com/`, then `codex mcp login miro`. Miro also publishes a plugin for both in its [miro-ai](https://github.com/miroapp/miro-ai) repository.
- Sign-in uses OAuth, and the server reaches only the boards of the team chosen at sign-in. On an Enterprise plan, an administrator may have to allow it first.
- Ask before creating a board: the tool cannot undo it. Then put the board's link in the stage's `link`.
- Search the board for the frame you need, then read only that area. Do not read the whole board.
- Write each step's stickies in the step's frame, with the legend's colours, in the project's language.
- To copy a frame, read it and create the copy from what you read, without the board's item IDs.
- The server acts as the signed-in person, so what the AI adds shows that person's name. Keep the AI's proposals in a strip labelled as AI proposals until people accept them, and start the AI's comments with "AI:".
- Ask questions as comments on the sticky concerned. Before the next step, read the replies, carry each answer into the document, and resolve the comment.
- Never delete what people made. The AI can delete only items it created, and only after the user agrees to the list of items. Leave locked items alone.
- Link a frame or an item with the board's link followed by `?moveToWidget=<item id>`, in the conversation and in the document.

## Other boards and photos

A board the AI cannot reach, such as a board of another team, a board in another tool or a photo of a whiteboard, is a human view without an API. Work from a person's export, such as a PDF, an image or a list of the stickies, as step 5 of the procedure in [SKILL.md](../SKILL.md) says. Read the kinds from the colours and the order from the positions, give the export's date when you report, and hand back each change as a list a person can apply on the board.
