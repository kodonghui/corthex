# Targets

Where a diagram will be shown decides which Mermaid it meets. The facts below were measured on 2026-11-20; measure again when a target behaves differently.

## 1. Mermaid versions

| Target | Mermaid | How it was measured | Not verified |
| --- | --- | --- | --- |
| Notion, a code block whose language is Mermaid | 12.1.0 | The version string in the Mermaid script that Notion's web app loads | Whether Notion honours frontmatter `config` or `%%{init}%%`, and which theme it uses in dark mode |
| GitHub, a `mermaid` fence in Markdown, issues and pull requests | 12.3.0 | The version string in the script of GitHub's diagram viewer | Whether it honours frontmatter `config` |
| A page you publish, such as an artifact | The version the page loads | Pin an exact version in the script's address | |

- To measure a target again, draw a block that holds only `info`; Mermaid draws its own version, such as `v12.1.0`.
- Use no syntax newer than the oldest target that will show the source. `@{ shape: ... }` needs 11.3, line IDs and classes need 11.10; both targets above have them. Read the release notes before using anything added after 12.1 in a diagram that Notion shows.
- Mermaid also wraps text, and lays out, differently from version to version: render in the target, or in the target's version, before you call a diagram done.

## 2. Limits found in Mermaid 12.1 and 12.3

| Limit | What to do |
| --- | --- |
| `id@{ ... }:::class` does not parse | Put the class on a `class` line; the lint reports this as G0 |
| A Markdown string, a label in backticks, inside `@{ label: ... }` shows its backticks; the bracket form renders it | Do not use Markdown strings `[default]`; use `<br/>` for a line break |
| No double-bordered box | `fr-rect` stands in for the LLM; D2 draws the double border |
| No built-in legend | A legend `subgraph`, as [grammar.md](grammar.md) shows |
| A dark theme turns default text light but keeps a fixed fill | Set `color` in every class that sets `fill` |
| `linkStyle` counts lines by position | Give lines IDs and classes |

## 3. Korean line breaks

- With the default settings, Mermaid 12.1 broke Korean labels at about 115 px, roughly six syllables with their spaces, and sometimes inside a word even where a space was near: "출처 페이지 적중" came out as "출처 페이지 적" and "중". English labels broke only at spaces.
- Keep each line of a Korean label to about six syllables, and break longer labels with `<br/>` between words. Each line must be clearly short: "문서 참조 단서가<br/>있는 질문인가?" still broke inside its first line.
- Add `wrappingWidth: 240` to the frontmatter as a second safeguard:

  ```text
  ---
  config:
    flowchart:
      wrappingWidth: 240
  ---
  ```

  Mermaid 12.1 then kept "문서 참조 단서가 있는 질문인가?" on one line. Whether Notion and GitHub honour it is not verified, so the lint measures against 120 px whatever the frontmatter says; pass `--wrap 240` for a target where it is verified.
- The lint's G6 estimates a line's width at 16 px for each Korean, Japanese or Chinese character, 8.5 px for other characters and 4 px for a space, and warns above the limit minus 5 px.

## 4. Dark mode

- Rendered in Mermaid 12.3's dark theme: fills set in a class stay light, and text with its colour set stays dark on them. The orange and blue lines and the red key border stay clear; the grey borders of the process, grading and not-in-the-source boxes fade.
- Check a diagram with colours that matter in both themes. In Notion the theme used in dark mode is not verified.

## 5. Notion

- Put the Mermaid code in a code block with the language set to Mermaid. The block can show the code, the diagram or both. Copy the code from the repository file unchanged.
- Notion shows the diagram from the source each time, so a fix in the source needs only the block replaced.
- For a figure that must look the same in every theme and in exports, such as a study page's main figure, also attach an image rendered locally at twice the size (scale 2), and keep the source block beside it.

## 6. Images

- Render on the user's machine. Use a Mermaid command-line tool or a browser the user has installed, at scale 2, and keep the source next to the image under the same name.
- **D2 with the TALA layout** draws every shape of the grammar exactly, including the LLM's double border, and adds a legend titled "Legend". TALA became open source, under MPL-2.0, in D2 v0.9.0. Use it only when the user has `d2` installed, from a path they gave or an absolute folder on PATH. Its default font has no Korean, so pass a Korean font file: `d2 --layout tala --font-regular '<regular .ttf>' --font-bold '<bold .ttf>' '<in.d2>' '<out.svg>'`. A test on 2026-11-20 used a build of the source that reports itself as v0.8.1-HEAD.
- **Graphviz** measures Korean text too narrow: labels ran out of their boxes and branch labels overlapped. Do not use it for Korean labels.

## 7. Tools for editing by hand

Use these only when a person wants to move boxes by hand, and ask before one sends the diagram away from the user's machine:

| Tool | What it does | Where the diagram goes |
| --- | --- | --- |
| draw.io's MCP server (`@drawio/mcp`, Apache-2.0) | Turns Mermaid into an editable `.drawio` file | The tool server runs locally; opening the diagram in draw.io's own app server sends it out |
| Excalidraw's MCP server | Draws a hand-drawn style whiteboard | A remote server, so the diagram leaves the machine |
| Miro, through its MCP server | The project's board, as stage 01 sets it up in `corthex-discover` | The user's Miro account |
| Kroki | One API that renders many diagram languages | The public kroki.io receives the source; use only a server the user runs |

None of these checks the grammar. Bring the result back to the Mermaid source, which stays the source.
