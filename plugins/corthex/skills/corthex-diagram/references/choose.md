# Choosing a diagram

## 1. Start from the reader's question

Write the one sentence the reader should see first, then pick the type that shows it.

| The reader asks | Diagram | Mermaid |
| --- | --- | --- |
| What happens, in what order, with which branches? | Flowchart | `flowchart` |
| Who sends what to whom, and when? | Sequence diagram | `sequenceDiagram` |
| Which states does it pass through, and what moves it on? | State diagram | `stateDiagram-v2` |
| What holds what, and how do the tables relate? | ERD or class diagram | `erDiagram`, `classDiagram` |
| What is built from what, layer by layer? | Layers or contexts as lanes | `flowchart` with `subgraph` |
| When, for how long, and what overlaps? | Timeline or Gantt chart | `timeline`, `gantt` |
| How does a topic divide? | Tree or mind map | `flowchart TB`, `mindmap` |
| How much, and how does it change? | A chart drawn from the data | `xychart-beta`, or a plot from the data |
| What changed? | Before and after, side by side | Two lanes in one `flowchart`, the changed boxes marked key |
| Where does the project stand? | Stage map | `flowchart LR` of the stages, the current one marked key |

- The grammar's shapes and lines apply in full to flowcharts of a flow: a pipeline, a request, a user flow. A flowchart of a structure, such as a context map or a screen tree, says `%% grammar: structure` and keeps the rest, as [grammar.md](grammar.md) section 1 says. Other types keep its colours, its legend, its captions and the rule of real names; the lint checks flowcharts only.
- A table shows many criteria side by side better than a diagram, and a list shows unordered items better.
- A diagram for a slide or a screen belongs to `corthex-uxui`, which picks a diagram from each slide's message.

## 2. Draw or not

- Draw when a reply or a document explains a flow, a structure, a comparison or a change with more than about three steps or parts, also when nobody asked for a picture `[default]`.
- Do not draw for a one-sentence answer, a single number or a small edit, nor when the user asked for no pictures.
- In a chat reply, draw the one diagram that answers the question; keep a series for a document.

## 3. A series

- When one picture would hold more than about 15 boxes, make a series: the whole map first, then one lane enlarged, then what changed.
- Number the steps of a walk-through in a column beside the picture, with one line of reason for each, such as why a candidate was dropped.
- Show the comparison that makes a point next to it: for example a search that keeps one candidate beside one that keeps several, to show how one candidate can take a wrong turn.
- Draw layers as layers. For a concept with levels, such as the layers of a search index, stack one lane per level from top to bottom, keep each node in the same place on every level, and join the same node across levels with dotted lines. A number such as "layer 2" on a box does not show the structure.

## 4. Examples and numbers

- Keep one example through a series: the same names, numbers, positions and paths in every picture. A new example in each picture makes the reader start again.
- Use an example that could really exist, in the reader's domain. An odd example takes attention from the mechanism.
- Use the real numbers from the source and name it, such as "11 Notion pages, 359 chunks". Mark a score made up for the explanation as made up, and say what it measures between what, such as "similarity between the question and each menu item".
- When the diagram shows distances or scores, show what they are measured from, such as the question.

## 5. Colour and words on the picture

- Colour carries meaning only: the kinds and lines of the grammar, or the categories of the one mechanism being explained. Every colour goes in the legend.
- When two kinds of link look alike but mean different things, such as links kept for fast search and relations that carry meaning, say so in words on the picture.
- Keep titles outside the drawing area and text off the lines. When a render shows text under a line, move the boxes.

## 6. Diagrams from project files

- Draw a diagram of code or data from the code or data, so it cannot drift from it: the ERD from the DDL, an API flow from the OpenAPI file, a stage map from the hub's data.
- Stage outputs keep their stage's rules for files and IDs: user flows in `corthex-define`, the sitemap board in `corthex-screen`, the ERD in `corthex-contract`, the context map in `corthex-discover`. This grammar adds the shapes and lines where they fit, such as the start, decision and process shapes of a user flow.
- When a pull request changes a flow, put the flow before and after in its description, with the changed boxes marked key.

## 7. Captions

- Give each diagram a one-sentence caption that says what to notice, then, where it helps, one or two sentences that read the diagram in words. The words also serve a reader who cannot see the picture.
- When the diagram goes into a record, name the grammar version beside the caption.
