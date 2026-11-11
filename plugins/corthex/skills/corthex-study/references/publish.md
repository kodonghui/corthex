# Checks, publishing and records

## Checks

Before the page goes out:

- Every number in the text, the tables and the figures comes from a named output or source. Rebuild the tables from the saved results and compare them. Check the numbers in sentences too; they drift the most.
- Every link opens and says what the page claims it says. Every code block runs on the stated versions.
- Look at the page itself, in light and dark, at 1440, 390 and 320 pixels wide: no sideways scrolling of the page, no cut-off controls, no overlapping labels, and wide tables and figures scrolling inside their own box.
- Interactive parts respond, and the page shows no script errors.
- A screenshot or a check script is evidence only of what it saw. Report the widths, themes and states you actually looked at.

## The page

- One self-contained HTML file: styles, scripts and data inline, figures as inline SVG, and libraries only from sources the host allows.
- Colours as theme tokens, with a dark theme. Running text about 65 characters wide. Korean text with `word-break: keep-all` and `overflow-wrap: break-word`.
- Code and long tables behind toggles or in their own scroll box.
- Publish with the host's page tool when it has one, and keep the same address for revisions, with a short label for each version. Without one, deliver the file.
- With a page tool that keeps pages private, a published page is private until it is shared, and then one link away from anyone. When the tool cannot keep a page private, ask before the first publish. On the page, cite the learner's files by paths relative to their material, never by home paths, and leave out other people's names and contact details. Keep course captures, an instructor's own words, the learner's personal questions, names, email addresses, local paths and private links out of anything meant to be shared. When the learner wants a public version, make it separately, with new examples and the real API names, and ask before publishing it.

## Records

The record makes the study document findable later. Write it where the profile's `records.study` points, else `records.hub`, else ask once. Keep one row per study document, and reuse the row for the same question.

- Attach the page as a standalone HTML file. When the host wraps the published page in its own document, add what the wrapper adds: `<!doctype html>`, `<meta charset="utf-8">`, the viewport tag and the host's base styles. Open the file in a browser before attaching it.
- After each content change, update last changed and what changed, and uncheck read where the record has a read mark. Formatting fixes or moves alone are not a new version.
- If a write fails, tell the user that the record is missing and what is needed to write it.

### Notion

- Read the database's schema before writing, and use its properties as they are. Do not add or rename properties without asking.
- Common properties: title, date, last changed (with the time), what changed, a one-line summary, a one-line lesson, tags, the related project and a read checkbox. Fill them from the page, in the document's language.
- The body mirrors the page in native blocks and in the page's order: a callout that links the published page, the summary, each section with its tables as inline databases in their place, as `corthex-record` makes them, formulas as equation blocks, figures as uploaded images at twice their size, flows as Mermaid code blocks, code as code blocks, the source list and the study log in toggles, and the check question in a callout.
- Upload the standalone HTML file and embed it in a toggle at the end, named for the original, so that the page itself stays with the record.
- Escape `~` and `*` that should stay literal, write math only in equation blocks, and use backticks for code.
- Before you replace the body, look for blocks and comments the learner added, and keep them or ask first. Keep the existing image and file blocks' sources instead of uploading them again. A search-and-replace edit may not find media blocks; to swap one, replace the body.
- Keep a file that holds an upload header or token in the session's scratch folder, readable by its owner only. Never print it, and delete it right after the upload.

### A folder

When the record goes to a folder, save the HTML with the date and a short name, such as `<date>-<slug>.html`, the figures beside it, and a short text summary with the same name.
