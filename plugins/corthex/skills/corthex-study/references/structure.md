# Page structure

One page per study question. Keep the sections below in this order, so the learner finds the same thing in the same place in every study document. Leave a section out only when it would be empty, and say so under scope and limits.

| # | Section | What goes in it |
| --- | --- | --- |
| 0 | Title | What the page is about, in the field's standard terms that a reader would search for, then `·`, then the material and what the page shows. The title names the topic; it is not a slogan, a metaphor or a coined word. For example: "Multi-intent routing and implicit rules in the chapter 10 LangGraph router · thresholds set from labeled examples" |
| 1 | Summary | One line per layer (①, ②, ③ …), each with its conclusion and its key number. A reader who stops here leaves with the answer. |
| 2 | Question | The question as a one-sentence quote. Where it came from: the class, section or file and line, and the date. Each follow-up with its date and the layer that answers it. Links to the study documents it builds on. |
| 3 | Why it matters here | Where the issue shows up in the learner's own material and projects, with the real names (a node, a field, a function). |
| 4 | What actually happens | One subsection per layer: what was run, the result table, the figure, and the tagged reading of the result. |
| 5 | Code and values | One running example traced step by step: each step's name, what it reads, what it writes and the actual value. Then the full code that produced those values. |
| 6 | Evidence | A table of sources: the key content with its numbers and conditions, and where the page uses it. |
| 7 | Sources | Numbered links. The learner's material with the date it was read. Links to earlier study documents. |
| 8 | Common misconceptions | Numbered. Each is the wrong belief as a short quote, then the correction and its evidence. |
| 9 | Terms | Each term with its plain meaning, the original term, and what an abbreviation stands for. |
| 10 | Check question | One question about the newest layer, answerable in two sentences. |
| 11 | Scope and limits | What was run (versions, number of calls, cost), what was assumed, what was not checked, how blocked sources were confirmed, and how keys were handled. |
| 12 | Study log | Earlier check questions, the learner's answers, what was right and what was corrected, with dates. |

## Layers

- A question with several parts gets one layer per part. A follow-up question adds the next layer to the same page.
- Each layer leads with its answer, then shows why. Link layers that depend on each other both ways, such as "② shows why ① cannot catch this case".
- When a later layer changes an earlier conclusion, fix the earlier layer too, and say what changed in the record.

## Figures and interaction

- Draw a figure when a picture shows the mechanism faster than text: a flow, a graph of nodes, a distribution, a comparison of designs. Make it from the data or the code, never from numbers typed by hand.
- Pick the figure by what it shows: a table for relations, arrows for an order, a sequence diagram for calls and returns, a state diagram for waiting, and a plot for numbers.
- Give each figure a legend for its colours, line styles and positions, a caption that says what to notice, and one or two sentences under it that read the figure in words.
- When an analogy explains something, say where it stops matching the real concept.
- Add an interactive part only when moving a value teaches something, such as a threshold slider or a switch between two prompt versions. Otherwise use a table.
- Keep both colour themes readable. A figure or table wider than a phone scrolls inside its own box.

## Code

- Full files that run as they are, with their imports and the output they print, behind a toggle. A short excerpt in the text points to its full file.
- For a learner new to the language, mark which names they chose and which the language or library fixes.
- State the versions the code ran on.

## Result tables

- Rows are the designs or setups compared, columns are the measures. Name the unit and the base in the header, such as "missed, of the 140 that needed the rule".
- Write each cell the same way across a table, such as `0.083 → 3.5% / 11.9%`, and explain that format above the table.
