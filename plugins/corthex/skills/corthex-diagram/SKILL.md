---
name: corthex-diagram
description: Diagrams that explain a flow, a structure, a comparison or a change, drawn in one visual grammar and checked before they go out. Use whenever a reply, a document, a record, a study page or a pull request explains how something flows, what holds what, how a state changes, how an index, data structure or algorithm works inside, or what changed, and when the user asks for a flowchart, a pipeline, a sequence, an architecture or a before-and-after picture. Draws Mermaid first so GitHub and Notion show the source, and fixed-position SVG for layers and step-by-step walks, and checks both before showing them. Not for screens, motion or slides.
license: Apache-2.0
metadata:
  author: kodonghui
  version: "0.18.0"
---

# Diagrams

A diagram earns its place when it shows a mechanism faster than text. This skill decides when to draw, draws in one grammar so that every picture reads the same way, fits the source to where it will be shown, and checks it before it goes out. It works on its own; inside a CORTHEX project it serves every stage, the records and the study documents.

- The user's own rules come first, then the project's, then this skill. A diagram rule the user set, for example in a retrospective, wins over the defaults here; record the change as a decision with `corthex-record`.
- `[default]` marks a choice this skill makes when nothing else decides it.

## When to draw

| Draw | Do not draw |
| --- | --- |
| How something flows: a pipeline, a request, a user flow, a build or a release | A one-sentence answer, one number or a small edit |
| What holds what: an architecture, contexts, a schema, a folder tree | A list with no order or relation; use a list |
| Who sends what to whom and when, and how a state changes | Many criteria compared side by side; use a table |
| What changed: before and after a pull request, a design or a decision | Screens, motion and slides; use `corthex-uxui` |
| How something works inside, layer by layer or step by step: a search index, a data structure, an algorithm | Numbers and how they change; draw a chart from the data |

When a reply or a document explains a flow, a structure, a comparison or a change with more than about three steps or parts, draw it without being asked `[default]`. Do not when the user asked for no pictures or the place it goes cannot show one; then say in one line that a diagram was left out.

## Steps

### 1. Choose

- Write the one sentence the reader should see in the diagram first. Pick the diagram type for it with [references/choose.md](references/choose.md).
- When the reader asks how something works inside, such as a search index, a data structure or an algorithm, draw a concept figure by [references/concept.md](references/concept.md): SVG with every node in a fixed place, layer by layer and step by step. Mermaid places boxes by itself, so it cannot keep a node in one place across layers or steps.
- When one picture would hold more than about 15 boxes, plan a series: the whole map first, then one lane enlarged, then before and after.
- Keep one example through a series: the same names, numbers and positions in every picture.

### 2. Draw by the grammar

Follow [references/grammar.md](references/grammar.md):

- The **shape** says what a box is: start or end, document, store, process, decision, LLM or grading. A thick red border marks the key step, a grey dotted box marks what the source does not say.
- The **line** says what happens to data: write into a store, read from a store, pass on without a store, or grade against the source.
- **Lanes** separate when or by whom things happen, and a **legend** names every shape, line and tag the diagram uses.
- A flowchart of a structure rather than a flow, such as a context map or a screen tree, uses no box kinds and says `%% grammar: structure` in its source.
- Use the real names and numbers from the source, with where they came from. Mark what the source does not say instead of filling it in.
- One box, one action. Two things that run apart are two branches side by side, never one chain.
- Put trace IDs such as REQ-, FL-, TBL- and API- in a box's label when it shows a stage item. Draw a diagram of code or data from the code or data, such as an ERD from the DDL, never from memory.
- A concept figure follows [references/concept.md](references/concept.md) instead of the box kinds: layers drawn as layers, one example through the series, one frame per step with a step column, and distances measured from the question. Run the algorithm on the example first and copy each frame from the run.

### 3. Fit the target

- Mermaid first, because GitHub, Notion and most editors draw its source `[default]`. Check the target's Mermaid version and its known limits in [references/targets.md](references/targets.md), and use no syntax newer than the target's.
- Keep the source in the repository next to the document it explains, and show the same code in every view.
- Make an image only where the source cannot be drawn, or for a figure that must look the same everywhere; keep the source beside it.
- Ask before sending a diagram to a service that draws it on a remote server, since the diagram then leaves the user's machine.

### 4. Check

- Run [scripts/diagram-check.py](scripts/diagram-check.py) on the file. Resolve it relative to this SKILL.md and call its absolute path, with every path in single quotes: `python3 '<absolute skill directory>/scripts/diagram-check.py' -- '<file>'`, on Windows `py -3`. It reads `.mmd` and `.mermaid` files and the `mermaid` blocks of Markdown files, and `-` reads standard input. Fix every error; fix each warning or say why it stays.
- For a concept figure, run [scripts/concept-figure.py](scripts/concept-figure.py) with `--check` on its spec the same way, then render every frame.
- Where you can render the diagram, look at it once: words broken mid-word, labels under lines, a crossing that reordering removes. Say what you looked at and what you did not.
- The lint checks the grammar, not the truth. Compare every box and line with the source.

### 5. Caption

- Give each diagram a one-sentence caption that says what to notice, and, where it helps, one or two sentences that read it in words. The caption also serves a reader who cannot see the picture.
- When a number in the diagram is made up for the explanation, say so in the caption.

## Changing the grammar

The grammar has a version. A new kind of box, line or rule comes from a real diagram that needed it. Record the change as a decision with `corthex-record`, raise the version in [references/grammar.md](references/grammar.md), and change the lint and its tests in the same change.

## Files

| File | What it holds |
| --- | --- |
| [references/grammar.md](references/grammar.md) | The visual grammar: boxes, lines, lanes, legend, tags and colours, with Mermaid and D2 forms and a worked example |
| [references/choose.md](references/choose.md) | Which diagram answers which question, series, examples and captions |
| [references/targets.md](references/targets.md) | Mermaid versions in Notion and GitHub, Korean line breaks, dark mode, images and other tools |
| [references/concept.md](references/concept.md) | Concept figures: layers, spaces of points and walks step by step, drawn with fixed positions |
| [scripts/diagram-check.py](scripts/diagram-check.py) | The grammar lint for Mermaid flowcharts |
| [scripts/concept-figure.py](scripts/concept-figure.py) | Draws and checks a concept figure from a JSON spec, as SVG |
| [assets/hnsw-search.json](assets/hnsw-search.json) | A worked concept figure: an HNSW search over three layers |
