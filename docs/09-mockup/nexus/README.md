# NEXUS: mockups

[한국어](README.ko.md)

Stage 09 of CORTHEX's own project, for NEXUS 0.2: the design tokens in [design/nexus/](../../../design/nexus/base.tokens.json), and two candidate directions for the five new screens, SCR-105 to SCR-109, drawn for the phone first, at 320 pixels, on one page, [candidates.html](candidates.html). Status: draft of 2026-11-03, drawn on the recommendations of stages 03 to 08, whose checkpoint is still open. The stage's own first checkpoint, the choice of one direction, waits for the maintainer; nothing more is drawn before it. When a file and its Korean translation differ, the English file is the source.

Inputs: the screen definitions of [stage 08](../../08-screens/nexus/README.md), above all [SCR-105](../../08-screens/nexus/SCR-105-picture-view.md) to [SCR-109](../../08-screens/nexus/SCR-109-stage-overview.md), with their states, their layouts at 320 and 1440 pixels, the final words of the messages and the [notes for stage 09](../../08-screens/nexus/README.md#stage-09-mockups); phase 1's hub page as it runs, [hub.html](../../../plugins/corthex-nexus/skills/corthex-hub/assets/hub.html), whose colours, type, spacing and cards the tokens take; and the event storming board of [stage 01](../../01-domain/nexus.md), drawn in the frames as the sample picture. No brand assets or liked references were given: NEXUS has no logo of its own, so both candidates keep phase 1's look and differ in structure and in the form of the marks.

The stage's default human view is Figma or Claude Design. Here it is one page drawn from the tokens by a script, [candidates.html](candidates.html), with every frame in light and dark and in English and Korean, which a browser can measure: line breaks, contrast, target sizes and overflow. Figma is not connected to this project, and a page drawn from the tokens keeps a token name in every value. People look at it as a private published page whose link is in the project's records, as the repository is public. `.corthex/project.json` records the choice.

## Tokens

Format 2025.10 of the Design Tokens Community Group, with the modes of the Resolver Module 2025.10. The source is these files; the page and, later, the code take the tokens from them.

| File | Holds |
| --- | --- |
| [base.tokens.json](../../../design/nexus/base.tokens.json) | 47 tokens that every theme shares: `font` (families, five sizes, three weights, three line heights), `space` (2 to 32 pixels), `radius`, `border`, `size` (targets, marks, boxes, the side panel and the overview's column), `opacity`, `layout` (shares of the screen's height), `breakpoint`, `duration` and `easing` |
| [theme/light.tokens.json](../../../design/nexus/theme/light.tokens.json) | The light theme's 27 colours and shadows |
| [theme/dark.tokens.json](../../../design/nexus/theme/dark.tokens.json) | The dark theme's 27, under the same names |
| [tokens.resolver.json](../../../design/nexus/tokens.resolver.json) | Base first, then the theme: `light` by default, or `dark` |

- From phase 1's hub page: the system fonts with the Korean ones, body text of 15 pixels, the page's and the cards' colours, the accent, the done stage's green, and the corners of 6, 8 and 12 pixels and the pill.
- New for 0.2: `color.control-line` for the border of a field, a chip or a check box, which needs 3:1 against the page and a surface (WCAG 1.4.11) where phase 1's line is lighter; `color.mark.*` for the marks and the halo that keeps them apart from the picture's colours; `color.scrim` and `color.picture-ground`; `color.warn` and `color.info` with their grounds; the two shadows; `size.target`, 44 pixels, the least width and height of anything a finger selects; the sizes of marks, boxes and panels; and the shares of the phone's height for the picture and the sheets.
- In the page, each token is a custom property named by its path, such as `--nx-color-mark-ink`. Outside the drawing inside the picture, the mockups' styles use no colour or length but these names, and every token is used, apart from `breakpoint.side-panel`: the frames are drawn at fixed widths, and the views will use it in their media query.
- Candidate tokens: `size.pin` belongs to A; `size.tab` and `layout.sheet-peek` to B. The one not chosen is removed with its direction.

## The candidates

Following the `corthex-uxui` skill, an idea was sketched along each of five paths, and two are shown:

1. The product's material world, the event storming board with its notes: marks as tabs stuck to the notes. Shown as B.
2. The feeling of a record rather than a chat, calm and the same as the hub page the user already knows. Shown as A.
3. The audience, one maintainer who reads mostly at a desk and answers on a phone: kept in both, which are drawn phone first.
4. The common answer turned around, a picture that shows nothing until an item is tapped: dropped, since stage 08 puts the counts on the picture so that open talk shows at a glance.
5. An unfamiliar format, the project as one chat in which pictures are messages: dropped, since it loses where on the picture each entry is, which is the point of the picture view.

### A · Hub pages (recommended)

The picture view and the stage overview read like phase 1's hub page: the same top lines, cards and rows. The picture sits in a card inside the page's 16-pixel margins, 286 pixels wide on a phone. Each kind of entry has its own small pin on the item's corner, 24 pixels drawn and 44 to touch: a dark circle for comments, a blue square for proposals and an amber diamond for discrepancies, with a hollow diamond when a discrepancy waits for a current picture. An accepted proposal not yet reflected outlines its item with blue dashes and a ✓ pin. Apart, Items as a list and the legend are rows under the picture. Panels rise from the bottom to their content's height, up to 85 per cent, over a dimmed picture; at 1,440 pixels they open beside it.

- For: one look with the hub page, which NEXUS 0.2 keeps from phase 1; corner pins cover little of a full board; each kind has its own shape, so colour is not the only cue; stage 08's layout stays as it is.
- Against: the shapes need the legend at first, and the words of a waiting or accepted item show only in the legend, the list and the panel; the picture is narrower on a phone, and a tall panel covers it.

### B · Picture first

The picture takes the whole width, 320 pixels on a phone, and the top is one bar of icons with a two-line heading; on a phone the version moves onto the picture as a chip. Each item with entries gets tabs that sit on its top edge, above its label: one dark tab with an icon and a count for each of comments and proposals, an amber tab for discrepancies, and a blue tab that says "Accepted, not yet reflected". Tabs that would leave the frame end at the item's right end instead. A tray under the picture holds Apart, the list of items and the legend. From a mark, panels first rise to 55 per cent of the height without dimming, with the picture moved so that the item stays in sight; from another panel they rise to 85 per cent. The talk shows as speech bubbles, and the stage overview puts everything left into one list with filters.

- For: a picture about 12 per cent wider on a phone; tabs that say what they count; the item stays in sight above a half-height panel.
- Against: on a full board the tabs cover the line above the item, such as a context's title, and a tab with words runs across its neighbours on a phone; it looks unlike the hub page, and it changes stage 08's layout of SCR-105 at 320 pixels.

### What differs

| | A · Hub pages | B · Picture first |
| --- | --- | --- |
| Top bar | Hub page and Stage overview as text links, the heading and the version line under it, as phase 1's hub | Icon buttons and a two-line heading; at 320 pixels the version is a chip on the picture |
| Picture | A card inside the margins, 286 pixels wide on a phone | The whole width, 320 pixels on a phone |
| Marks | A 24-pixel pin for each kind on the item's corner, each 44 × 44 to touch | 24-pixel tabs on the item's top edge with an icon and a count, each part 44 × 44 to touch |
| Accepted, not yet reflected | A blue dashed outline and a ✓ pin | A blue outline and a blue tab with the words |
| Whole picture | Each context's marks merge into a 32-pixel circle with the count | Each context's marks merge into a pill, "{n} marks" |
| Under the picture | Apart as a row, Items as a list as a button, then the legend | A tray of three tabs: Apart, Items and Legend |
| Panels at 320 pixels | To their content's height, up to 85 per cent, over a dimmed picture; entries as rows | 55 per cent first from a mark, without dimming; 85 per cent from another panel; speech bubbles |
| Stage overview | Hub cards: the recorded state, what is left in three lists, passing and the checks | A strip of the record, one list of what is left with filter chips, passing and the checks |
| Changes to stage 08 | None | SCR-105 at 320 pixels: the version on the picture, icons only in the top bar |

### What both keep

- The opening view of a picture shows the context with the most marks at a zoom where the board's text is about 10 pixels high on a phone; at 1,440 pixels the whole picture fits.
- Marks keep their size at every zoom. At the whole picture on a phone, the marks of each context merge into one with their count, which zooms in. A mark that counts one entry opens that entry's panel, and a count of several opens the item's panel.
- The list of items puts the items with marks first, then the rest, and names a part without an ID as such.
- Korean text breaks between words, dates never break inside, and long IDs break rather than widen the page. Under reduced motion, sheets fade instead of moving.

## Frames

Fourteen frames for each candidate, the same states for both, each in light and dark and in English and Korean, with sample data made up for them: the board of stage 01, five comments, two proposals, two discrepancies, commits and a trace ID. The words of NEXUS itself are stage 08's.

| Screen | Drawn | Not drawn yet |
| --- | --- | --- |
| SCR-105 Picture view | normal at 320, opened and as the whole picture; normal at 1440; stale and code-failed at 320 | loading, large, empty, error, permission |
| SCR-106 Item | normal at 320 and 1440; error at 320 (`comment_limit`, with the text kept) | empty, loading, permission, gone |
| SCR-107 Comment | normal at 320 | loading, stale, error, permission, gone |
| SCR-108 Proposal | normal at 320, open and accepted | loading, stale, error, permission, gone |
| SCR-109 Stage overview | normal and stale at 320, normal at 1440 | loading, empty, error, permission |

The states not drawn are drawn in the chosen direction, with the additions of 0.2 to the hub page on SCR-101 and SCR-104, once the direction is chosen.

## New words

Words that the frames need and stage 08 did not write, in English and Korean. They join stage 08's messages once a direction is chosen.

| Where | English | Korean |
| --- | --- | --- |
| Zoom buttons | Zoom out · Zoom in · Whole picture | 축소 · 확대 · 그림 전체 |
| Merged marks | "1 mark" or "{n} marks" (B), named "{n} marks in {context}: zoom in" | "표시 {n}개", 이름은 "{context}의 표시 {n}개: 확대하기" |
| Legend | Legend (B's tab), named "Legend of the marks" | 표시 설명, 이름은 "표시의 설명" |
| List of items | With marks ({n}) · The rest ({n}) · Part without an ID | 표시가 있는 것 ({n}) · 나머지 ({n}) · ID 없는 부분 |
| Item panel | Term · Proposals ({n}) · Comments ({n}) · Closed ({n}) · {n} replies | 용어 · 제안 ({n}) · 의견 ({n}) · 닫힌 의견 ({n}) · 답글 {n}개 |
| Proposal panel | Answers · Made on commit {commit} | 답하는 의견 · 커밋 {commit}에서 낸 제안 |
| Stage overview | Updated {time} · from the repository · Words (optional) · All {n} · Reflections {n} | 갱신 {time} · 저장소에서 · 남길 말 (선택) · 모두 {n} · 반영 대기 {n} |

## Recommendation

A, Hub pages. NEXUS 0.2 adds these screens beside a hub page that keeps phase 1's design, so A makes one product of them, and its corner pins keep a full DDD board readable. The main argument for B is the phone: a wider picture, marks that say what they count, and a panel that keeps the item in sight. If the phone matters most, B is the better choice; A could also take B's half-height panel later without changing its look.

## Checks run

On 2026-11-03, on the tokens, the page and its 56 frames:

- The tokens: each of the 47 base tokens and the 27 of each theme has one `$value` and a type, its own or its group's; colours are sRGB objects whose `hex` matches their components, and dimensions are objects in `px` or `rem`; both themes hold the same 27 names, and none of them is in the base file; the resolver lists the three files.
- The mockups' styles: no colour or length outside the token names, only 0, whole shares such as 50 per cent and the picture's height in container units; every token used apart from `breakpoint.side-panel`.
- Contrast, computed from the tokens for each pair the frames draw, 37 in each theme: text at least 4.5:1 and the borders of fields, focus rings, outlines and marks at least 3:1 against what is behind them. The light theme's field border was darkened once to reach 3:1 on the page.
- `corthex-uxui`'s page check on each frame on its own, at 320 × 640 or 1440 × 900, in both themes: 112 runs. No sideways scrolling, no split word, no missing label and no target under 24 pixels. What it reports is the drawing inside the picture cut off by its frame, which is how a picture larger than its frame moves (stage 08's rule 1), and the numbers on the diamond marks, which sit on a shape that the check cannot see and were computed by hand instead. Its 44-pixel goal is met everywhere but by the check box, 24 pixels in a row of 44, and a pull request's number inside a sentence.
- The page in Chromium at 320, 390, 1,280 and 1,440 pixels, in light and dark and in both languages, 16 runs: no sideways scrolling, no element past its frame's edge, no console error; the page check on it reports only the drawing inside the pictures, and four short last lines of Korean body text, which it counts only as information.
- Looked at as images: every frame at 320 pixels of both candidates, in English and light and in Korean and dark; the three frames at 1,440 pixels, A in English and light and B in Korean and dark. The frames that the fixes changed were looked at again.
- The hub's snapshot of this repository finds `design/nexus/` as the stage's source and adds no check result.
- The repository's checks with these files pass: `python -m unittest discover -s tests`, `claude plugin validate --strict` for the marketplace and its three plugins, `node --test nexus/test/*.test.js` and `git diff --check`.

## For the checkpoint

The stage's first checkpoint: one direction, A, B, or A with parts of B such as the half-height panel. Then the states not drawn are drawn in that direction, the candidate tokens of the other are removed, and each screen definition links its mockups. The second checkpoint, frozen tokens, comes before development uses them.

## Notes for later stages

### Stage 10: work breakdown

- One task builds the custom properties from the resolver, the base and each theme, in the order that it gives, for the hub page and the views; the frames' styles show the names in use.

### Stage 11: development

- The views take every colour and length from the tokens; the picture's own drawing keeps the editor's colours, inverted in dark mode as the editor does.
- Marks are buttons with names that say what they count, as the frames name them; they keep their size at every zoom and merge for each context at the whole picture.
- The opening view and the rule for marks that would leave the frame are written in "What both keep" and, for B, under B.

### Stage 12: QA

- Each state in the chosen direction at 320 and 1440 pixels, in both themes and languages, measured with the page check and looked at as images, with the contrast pairs above computed again from the frozen tokens.
