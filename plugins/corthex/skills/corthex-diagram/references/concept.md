# Concept figures

A concept figure shows how something works inside: a search index, a data structure, an algorithm. In these pictures a node's position means something. The reader remembers where a node sits and follows it from layer to layer and from step to step. Mermaid places boxes by itself and moves them when anything changes, so it cannot keep a node in one place. Draw a concept figure as SVG with fixed positions, using `scripts/concept-figure.py` where it fits.

Use the flowchart grammar in [grammar.md](grammar.md) for pipelines and the flow of data, and a concept figure for the mechanism inside one box.

## 1. Which figure

| The reader asks | Figure | How |
| --- | --- | --- |
| How is it built, layer by layer? An HNSW index, a skip list, a cache hierarchy | Stacked layers. Each node keeps one place on every layer | The script, `view: stack` |
| What is near what? Vectors, nearest neighbours, clusters | One flat plane of points, with the question as a point | The script, `view: flat` |
| How does a walk go? A search, a graph expansion by hops, a traversal | A series of frames on the same picture, one per step | The script's `frames` |
| What does it hold? An array, table rows with pointers, a tree of pages | Boxes drawn by hand | Section 6 |
| How much, and how does it change? | A chart drawn from the data | Not a concept figure |

## 2. What makes a concept figure teach

These rules come from the maintainer's retrospective of 2026-11-19, where HNSW was learned from pictures.

- **Draw layers as layers.** Put one plane per level, from the top level down, and keep every node in the same place on every level, joined by dotted lines. A label such as "layer 2" on a box does not show the structure.
- **Keep one example through the series.** Use the same nodes, positions and question in every picture. A new example in each picture makes the reader start again.
- **Draw one frame per step.** Draw the frame's layer large and the other layers small and faded, so the reader keeps the whole picture in view.
- **Put a step column beside the picture.** It holds one line for every step, the current step's reason in a sentence or two, and the list the algorithm keeps, nearest first.
- **Show what distances are measured from.** The question is a point in the same place on every layer. Draw a distance as a line from the question, with its value.
- **Say which numbers are made up.** The script measures distances in the figure's own coordinates and says so under the picture. Use the source's numbers, and name the source, wherever it has them.
- **Show the comparison that makes the point,** such as a search that keeps one candidate beside one that keeps three.
- **Name links that look alike but mean different things.** HNSW keeps links for fast search, and a knowledge graph keeps relations that carry meaning. Draw them in different styles and say what each one is in the legend, with `labels`.
- **Run the algorithm before you draw it.** Write a few lines of code that run the real algorithm on the example, and copy each frame's states from its result. The script checks that the picture holds together, not that the algorithm is right.
- **Use an example from the reader's domain,** with names from it where a letter would not do.

## 3. The script

`scripts/concept-figure.py` reads a JSON spec, checks it, and writes SVG. Standard library only, Python 3.8 or later. It writes only the path given with `-o`, or standard output.

```text
python3 '<skill>/scripts/concept-figure.py' --check -- '<spec.json>'
python3 '<skill>/scripts/concept-figure.py' -o '<out.svg>' -- '<spec.json>'
python3 '<skill>/scripts/concept-figure.py' --structure -o '<out.svg>' -- '<spec.json>'
python3 '<skill>/scripts/concept-figure.py' --sheet 5,6 -o '<out.svg>' -- '<spec.json>'
```

- With frames, `-o figure.svg` writes `figure-1.svg`, `figure-2.svg` and so on, one per frame. `--frame N` writes one frame, `--structure` the picture with no frame, and `--sheet` several frames side by side, two to a row.
- [assets/hnsw-search.json](../assets/hnsw-search.json) is a worked example: an HNSW search over three layers, with a comparison of `ef=3` and `ef=1`. Its frames were copied from a run of the HNSW search algorithm on the same points.

### The spec

| Field | What it holds |
| --- | --- |
| `title`, `caption` | The SVG's title and description, for readers who cannot see the picture. Show the caption under the picture as well |
| `lang` | `en` or `ko`: the language of the words the script writes itself, such as the legend |
| `labels` | Your words for legend items, such as `{"link": "Link kept for search (no meaning)"}` |
| `view` | `stack` for layers (the default when there are two or more), `flat` for one plane |
| `layers` | `[{"id": "L2", "label": "Layer 2"}, ...]`, from the top layer down |
| `nodes` | `[{"id": "E", "x": 10, "y": 25, "layer": "L2", "label": "E"}]`. `x` runs left to right and `y` back to front, both from 0 to 100. `layer` is the highest layer the node reaches; it is on every layer below as well. Without `layer` a node is on the lowest layer only |
| `links` | Links kept for search, by layer: `{"L0": [["E", "A"], ...]}` |
| `relations` | Links that carry meaning, by layer, with an optional label: `{"L0": [["A", "B", "contains"]]}` |
| `query` | The question as a point: `{"x": 86, "y": 72, "label": "Question"}` |
| `marks` | Short words beside a node, on its highest layer, such as `{"E": "Entry point"}` |
| `frames` | The steps, in order (below) |
| `size` | Optional sizes in px: `width`, `depth`, `focus_depth`, `context_depth`, `skew`, `gap` |

A frame holds:

| Field | What it holds |
| --- | --- |
| `title` | One line for the step column |
| `note` | The step's reason, shown only while the step is current |
| `layer` | The layer the step happens on, drawn large |
| `current`, `candidates`, `visited`, `dropped`, `result` | Node states on that layer |
| `path` | Moves along links: `[["M", "J"], ["J", "N"]]` |
| `descend` | The node the walk goes down from, to the same node one layer below |
| `distances` | Nodes to draw a distance line to from the question |
| `list` | The list the algorithm keeps, nearest first; the step column shows each node with its distance |
| `marks` | Words beside nodes in this frame only |
| `greedy` | `true` when every move must get closer to the question |

### What it draws

| Item | Drawn as |
| --- | --- |
| Question | Red star, in the same place on every layer |
| Node being checked (`current`) | Solid blue circle |
| Kept in the list (`candidates`) | Light blue circle with a thick blue border |
| Checked (`visited`) | Grey circle |
| Dropped | Dotted circle with a cross |
| Result | Solid green circle |
| Move (`path`) | Thick blue arrow along a link |
| Down one layer (`descend`) | Dashed blue arrow to the same node below |
| Link kept for search | Thin grey line |
| Relation | Purple line, with its label |
| Same node on another layer | Dotted grey line |
| Distance from the question | Dashed red line with the value |

The legend shows only what the picture uses. The picture is a white card with fixed colours, so it reads the same on a dark page.

### What it checks

| Code | Level | Finding |
| --- | --- | --- |
| F1 | error, warn | The spec cannot be read or has no nodes; unknown keys are ignored with a warning |
| F2 | error | A link, frame or mark names an unknown node or layer, or a frame measures distances with no question |
| F3 | error | A node or the question is outside 0 to 100 |
| F4 | error | A link or relation is on a layer that one of its nodes does not reach |
| F5 | error | A move follows no link on the frame's layer |
| F6 | error | A frame shows a node on a layer it does not reach, or marks nodes without naming a layer |
| F7 | error | In a greedy frame, a move does not get closer to the question |
| F8 | warn | Two nodes overlap on a layer |
| F9 | warn | A frame has no title |
| F10 | warn | More than about 20 nodes on a layer, or more than 8 frames |
| F11 | error | `descend` from the lowest layer, or to a node that is not on the layer below |
| F12 | warn | The list is not nearest first |

It does not check that the algorithm is right, that a label stays clear of every line, or that the picture tells the truth about the source.

## 4. Fit the target

- **Notion:** attach a PNG rendered at twice the size (scale 2), and keep the spec and the SVG next to the document in the repository or the project's files. Notion does not draw the SVG source.
- **GitHub and Markdown:** commit the SVG next to the document and show it as an image, with the caption as its alternative text.
- **A page you publish, such as an artifact:** put the SVG in the page.
- **Rendering a PNG:** use a browser or a tool the user installed. Open the SVG in a browser and take a screenshot at twice the size, or run `rsvg-convert -z 2 -o figure.png figure.svg`. The SVG asks for IBM Plex Sans KR, Noto Sans KR, Apple SD Gothic Neo or Malgun Gothic, so Korean text needs one of them installed where it is rendered.

## 5. Check

1. Run the script with `--check`. Fix every error, and fix each warning or say why it stays.
2. Render every frame and look at it at the size it will be shown: labels on lines, a crowded corner, a node hidden under the star. Move nodes in the spec to fix it, and keep the new positions in every frame.
3. Compare each frame's states with the run of the algorithm.
4. Say what you looked at and what you did not.

## 6. Other concept figures

For a structure the script does not draw, such as an array, table rows with pointers or a tree of pages, write SVG by hand by the same rules: fixed positions, one example through the series, a white card with fixed colours, text of at least 12 px, a legend for every colour and a step column for a walk. Then render it and look at it, as in section 5.
