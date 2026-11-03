# NEXUS: mockups

[한국어](README.ko.md)

Stage 09 of CORTHEX's own project, for NEXUS 0.2: the design tokens in [design/nexus/](../../../design/nexus/base.tokens.json), and the mockups of direction A, Hub pages, on one page, [mockup.html](mockup.html): every state of the five new screens, SCR-105 to SCR-109, and of the hub page and its stage detail, SCR-101 and SCR-104, with what 0.2 adds to them, drawn for the phone first, at 320 pixels. Status: the maintainer chose direction A on 2026-11-03, the stage's first checkpoint, and the states were then drawn in it. The maintainer passed the second checkpoint, frozen tokens, the same day at 11:39 KST, together with the joint checkpoint of stages 03 to 08, whose recommendations the mockups follow: the tokens are frozen for NEXUS 0.2 before development uses them, and a later change needs the maintainer's decision. The maintainer's choice of 2026-11-03 to hold stage 01's event storming in NEXUS added the step control of a DDD board above the picture and five frames of its steps, drawn with the frozen tokens, which wait for the maintainer's check ([For the checkpoint](#for-the-checkpoint)). When a file and its Korean translation differ, the English file is the source.

Inputs: the screen definitions of [stage 08](../../08-screens/nexus/README.md), [SCR-101](../../08-screens/nexus/SCR-101-hub-page.md), [SCR-104](../../08-screens/nexus/SCR-104-stage-detail.md) and [SCR-105](../../08-screens/nexus/SCR-105-picture-view.md) to [SCR-109](../../08-screens/nexus/SCR-109-stage-overview.md), with their states, their layouts at 320 and 1440 pixels, the final words of the messages and the [notes for stage 09](../../08-screens/nexus/README.md#stage-09-mockups); the hub page's rows of the [functional spec](../../04-functional-spec/nexus.md), SPEC-122 to SPEC-125; phase 1's hub page as it runs, [hub.html](../../../plugins/corthex-nexus/skills/corthex-hub/assets/hub.html), whose colours, type, spacing, cards and words the tokens and the hub's frames take; and the event storming board of [stage 01](../../01-domain/nexus.md), drawn in the frames as the sample picture, with its timeline for the steps of SPEC-141. No brand assets or liked references were given: NEXUS has no logo of its own, so the mockups keep phase 1's look.

The stage's default human view is Figma or Claude Design. Here it is one page drawn from the tokens by a script, [mockup.html](mockup.html), with every frame in light and dark and in English and Korean, which a browser can measure: line breaks, contrast, target sizes and overflow. Figma is not connected to this project, and a page drawn from the tokens keeps a token name in every value. People look at it as a private published page whose link is in the project's records, as the repository is public. `.corthex/project.json` records the choice.

## The choice

- Question: “09 목업은 어느 방향으로 그릴까요?” (which direction should the 09 mockups take?), asked in the project's thread on 2026-11-03 at 08:34 KST, after the draft with two candidates (pull request #70).
- Options: “A · 허브와 같은 쪽” (A, Hub pages, recommended), “B · 그림이 먼저” (B, Picture first), “A에 B의 절반 높이 패널” (A with B's half-height panel) and “먼저 이야기하기” (talk first).
- Answer: the maintainer picked “A · 허브와 같은 쪽” on 2026-11-03 at 09:00 KST.
- What followed: the states not drawn yet were drawn in A, together with what 0.2 adds to the hub page; B's frames left with its tokens `size.tab` and `layout.sheet-peek`, which the option named, and `shadow.float`, which only B's floating buttons used; the words that the frames need joined [stage 08's messages](../../08-screens/nexus/README.md#words-the-mockups-added); and each screen definition links its mockups. The draft with both candidates stays in Git: [candidates.html at commit e1d9956](https://github.com/kodonghui/corthex/blob/e1d9956c30339a0ca78c5a2a4a0c79063410636a/docs/09-mockup/nexus/candidates.html).

## Direction A · Hub pages

The picture view and the stage overview read like phase 1's hub page: the same top lines, cards and rows. The picture sits in a card inside the page's 16-pixel margins, 286 pixels wide on a phone. Each kind of entry has its own small pin on the item's corner, 24 pixels drawn and 44 to touch: a dark circle for comments, a blue square for proposals and an amber diamond for discrepancies, with a hollow diamond when a discrepancy waits for a current picture. An accepted proposal not yet reflected outlines its item with blue dashes and a ✓ pin. Apart, Items as a list and the legend are rows under the picture. Panels rise from the bottom to their content's height, up to 85 per cent, over a dimmed picture; at 1,440 pixels they open beside it.

- For: one look with the hub page, which NEXUS 0.2 keeps from phase 1; corner pins cover little of a full board; each kind has its own shape, so colour is not the only cue; stage 08's layout stays as it is.
- Against, and still true: the shapes need the legend at first, and the words of a waiting or accepted item show only in the legend, the list and the panel; the picture is narrower on a phone, and a tall panel covers it.

### Across the screens

- The opening view of a picture shows the context with the most marks at a zoom where the board's text is about 10 pixels high on a phone; at 1,440 pixels the whole picture fits.
- Marks keep their size at every zoom. At the whole picture on a phone, the marks of each context merge into a 32-pixel circle with their count, which zooms in. A mark that counts one entry opens that entry's panel, and a count of several opens the item's panel.
- On a DDD board, the step control above the picture opens at the last step, 8-b–9, the whole board. A step is laid out from the board's timeline and context tables, the same way each time: a lane for each flow, its places from left to right, with the events of one place stacked; from step 2 the external systems, and from step 4 the hotspots, in a column beside the first event of their context; from step 3 each command left of its events, from step 5 its actors below it as small stickies, and from step 6 its aggregate above it; from step 7 each sticky of a context with the context's ID; and at step 8-a the policy and the read model left of the command. A place widens when a step gives it a column. On a phone a step opens at the start of its first lane, at the zoom of the opening view; at 1,440 pixels the whole step fits.
- The list of items puts the items with marks first, then the rest, and names a part without an ID as such.
- A refusal or an error shows its message above the box or the buttons it concerns, with its trace ID, and what the user wrote stays. While something loads, still grey shapes stand where its content will be.
- Korean text breaks between words, dates never break inside, and long IDs break rather than widen the page. Under reduced motion, sheets fade instead of moving.

### The hub page and the stage detail

SCR-101 and SCR-104 are drawn as phase 1's hub.html draws them, with its words, and with what 0.2 adds in the same style:

- Each part's Now and Next, the open comments, proposals and discrepancies, and a mark on each stage that has a picture, which the legend explains (SPEC-123).
- The checkpoints passed in NEXUS that wait for their records, each with a link to its stage overview. On a page built earlier, the rows under "In NEXUS" also hold a picture that is not current and a withdrawn checkpoint that a record names (SPEC-140).
- The actions that the agent asks about first: up to 10 entries, where the list comes from, the profile's entries that the project's list leaves out, and that anything that cannot be undone is asked in any case (SPEC-125).
- On an empty server, the four steps that push a project (SPEC-124). On a device, a line that says that the pictures, comments and stage overviews are on the server.
- In the stage detail, each part's state, last checkpoint and next action, with Picture and Stage overview beside the state at 1,440 pixels and on their own line at 320.

Where the frames differ from phase 1, as the checkpoint accepted them:

- The search field's border takes `color.control-line`, 3:1 against the page, where phase 1's line is lighter.
- The stages keep phase 1's borders, under 3:1 against the card. Each stage is a button that its text names, so its border carries nothing that the text does not; WCAG 1.4.11 asks 3:1 of what is needed to identify a control.

## Tokens

Format 2025.10 of the Design Tokens Community Group, with the modes of the Resolver Module 2025.10. The source is these files; the page and, later, the code take the tokens from them.

| File | Holds |
| --- | --- |
| [base.tokens.json](../../../design/nexus/base.tokens.json) | 46 tokens that every theme shares: `font` (families, five sizes, three weights, three line heights), `space` (2 to 32 pixels), `radius`, `border`, `size` (targets, marks, boxes, the side panel, the overview's column and the hub's stages), `opacity`, `layout` (shares of the screen's height), `breakpoint`, `duration` and `easing` |
| [theme/light.tokens.json](../../../design/nexus/theme/light.tokens.json) | The light theme's 32 colours and shadows |
| [theme/dark.tokens.json](../../../design/nexus/theme/dark.tokens.json) | The dark theme's 32, under the same names |
| [tokens.resolver.json](../../../design/nexus/tokens.resolver.json) | Base first, then the theme: `light` by default, or `dark` |

- From phase 1's hub page: the system fonts with the Korean ones, body text of 15 pixels, the page's and the cards' colours, the accent, the colours of the stages done, in progress and not started, a stage's least size, and the corners of 6, 8 and 12 pixels and the pill.
- New for 0.2: `color.control-line` for the border of a field, a chip or a check box, which needs 3:1 against the page and a surface (WCAG 1.4.11) where phase 1's line is lighter; `color.mark.*` for the marks and the halo that keeps them apart from the picture's colours; `color.scrim` and `color.picture-ground`; `color.warn` and `color.info` with their grounds; the sheet's shadow; `size.target`, 44 pixels, the least width and height of anything a finger selects; the sizes of marks, boxes and panels; and the shares of the phone's height for the picture and the sheets.
- Since the choice: added `color.progress-bg`, `color.progress-fg`, `color.progress-line`, `color.todo-line` and `size.stage`, phase 1's values for the hub's stages, which the frames of SCR-101 and SCR-104 draw; removed B's `size.tab`, `layout.sheet-peek` and `shadow.float`.
- At the freeze: added `color.skipped-fg` and `color.unknown-line`, phase 1's colours of a skipped stage's text and of a stage not recorded's dashed border, which the second sample project's stages now draw on SCR-101 and SCR-104. A skipped stage keeps `color.sunken` with a dotted `color.todo-line` border, and one not recorded `color.surface` with `color.muted` text, as in phase 1. A skipped stage's text in the light theme is darkened from phase 1's 4.13:1 on its ground to 4.63:1; in the dark theme it keeps 4.89:1.
- In the page, each token is a custom property named by its path, such as `--nx-color-mark-ink`. Outside the drawing inside the picture, the mockups' styles use no colour or length but these names, and every token is used, apart from `breakpoint.side-panel`: the frames are drawn at fixed widths, and the views will use it in their media query.

## Frames

Fifty-five frames, each in light and dark and in English and Korean: every state of the seven screens at 320 pixels, with the steps of a DDD board, and the normal state of five of them at 1,440, with one step. The sample data is made up for them: two projects, the board of stage 01 with its timeline, five comments, two proposals, two discrepancies, commits, times and a trace ID. The words of NEXUS itself are stage 08's.

| Screen | At 320 pixels | At 1,440 |
| --- | --- | --- |
| SCR-101 Hub page | normal, on the server and on a device; empty; stale; error, data that could not be read; permission, `access_missing` | normal |
| SCR-104 Stage detail | normal; empty; stale; error, a project not on the page | normal |
| SCR-105 Picture view | loading, before the view's code runs and while it draws; normal, opened, as the whole picture, at the steps 1-b, 6 and 8-a, and on a board without a timeline; large; empty; stale; error; code-failed; permission, a sign-in that expired | normal; step 3 |
| SCR-106 Item | normal; empty; loading; error, `comment_limit`; permission, `no_kind`; gone | normal |
| SCR-107 Comment | loading; normal; stale; error, `reply_limit`; permission, a sign-in that expired; gone | none |
| SCR-108 Proposal | loading; normal, open and accepted; stale; error, `reflection_limit`; permission, `user_only`; gone | none |
| SCR-109 Stage overview | loading, before the overview's code runs; normal; empty; stale; error, `internal` when passing; permission, `user_only` | normal |

SCR-102 and SCR-103, the search results and the trace view, keep phase 1's design and are not drawn.

## Words

The words that the frames need and stage 08 had not written joined stage 08's messages as [Words the mockups added](../../08-screens/nexus/README.md#words-the-mockups-added): the hub page's open counts, waiting checkpoints and actions to ask about first; the names of the zoom buttons, the merged marks and the legend; the headings of the list of items, the panels and the stage overview; the loading lines for screen readers; "New" on a reply; and "Back to the picture". B's own words, such as its tabs and filter chips, left with it. The step control's words, "Steps" and "No timeline", came with stage 08's change of 2026-11-03 (SPEC-141).

## Checks run

On 2026-11-03, on the tokens, the page and its 50 frames, and again after the freeze:

- The tokens: each of the 46 base tokens and the 32 of each theme has one `$value` and a type, its own or its group's; colours are sRGB objects whose `hex` matches their components, and dimensions are objects in `px` or `rem`; both themes hold the same 32 names, and none of them is in the base file; the resolver lists the three files.
- The mockups' styles: no colour or length outside the token names, only 0, whole shares such as 50 per cent and the picture's height in container units; every token used apart from `breakpoint.side-panel`.
- Contrast, computed from the tokens for each pair the frames draw, 42 in each theme: text at least 4.5:1, and the borders of fields, focus rings, outlines, marks and error icons at least 3:1 against what is behind them.
- `corthex-uxui`'s page check on each frame on its own, at 320 × 640 or 1440 × 900, in both themes: 200 runs. No sideways scrolling, no split word, no text past its box, no missing label and no target under 24 pixels. What it reports is the drawing inside the picture cut off by its frame, which is how a picture larger than its frame moves (stage 08's rule 1), and the numbers on the marks, which sit on shapes that the check cannot see and were computed from the token pairs instead. Its 44-pixel goal is met everywhere but by the check box, 24 pixels in a row of 44, and two links inside a sentence: phase 1's "open" for a human view and a pull request's number.
- The page in Chromium at 320, 390, 1,280 and 1,440 pixels, in light and dark and in both languages, 16 runs: no sideways scrolling, no element past its frame's edge, no console error; the page check on it reports only the drawing inside the pictures and a few short last lines, which it counts as information or a warning.
- Looked at as images: every frame at 320 pixels in English and light and in Korean and dark, and the five at 1,440 pixels in English and light, with the stage detail's in Korean and dark as well. What looking changed: the stage detail's stale frame counts both waiting checkpoints, the comment's loading frame shows its last reply whole, the actions to ask about first follow SPEC-125, the Close button of the stage detail keeps its width, and a long variable name in the empty server's steps no longer splits a Korean word.
- Looked at as images after the freeze: the hub page's and the stage detail's normal frames at 320 and 1,440 pixels, in English and light and in Korean and dark, with the skipped and not-recorded stages.
- The hub's snapshot of this repository finds `design/nexus/` as the stage's source and adds no check result.
- The repository's checks with these files pass: `python -m unittest discover -s tests`, `claude plugin validate --strict` for the marketplace and its three plugins, `node --test nexus/test/*.test.js` and `git diff --check`.
- Again on 2026-11-03, after the step view: the mockups' styles hold only token names, and the 42 contrast pairs of each theme are unchanged, since the step control uses only the frozen tokens. The page check on each of the 55 frames in both themes, 220 runs, reports nothing new, only the drawing inside the picture cut off by its frame and the numbers on the marks, and the step control's buttons are 44 pixels. The page in Chromium at 320, 390, 1,280 and 1,440 pixels, 16 runs, has no sideways scrolling, no element past its frame's edge and no console error. Looked at as images: the five new frames, in English and light and in Korean and dark; and of the frames that the control moved, the opened picture in Korean and light, the stale picture and a proposal's sheet in English and light, and the picture at 1,440 pixels in English and light, with the item beside it in Korean and dark.

## For the checkpoint

The maintainer's choice of 2026-11-03, to hold stage 01's event storming in NEXUS, waits for the maintainer's check: the step control above a DDD board, with stage 08's words, and the five frames of the steps, which show how a step is laid out from the timeline ([Across the screens](#across-the-screens)). The tokens stay frozen: the control uses only them, and the steps' stickies keep the editor's colours, with pink for external systems and pale yellow for actors, as stage 01's legend has them.

Passed on 2026-11-03 at 11:39 KST, together with the joint checkpoint of stages 03 to 08: on a decision card in the project's thread the maintainer chose all the recommendations ("모두 추천대로", all as recommended), so the tokens are frozen for NEXUS 0.2 as recommended below. The checkpoint covered:

1. The states drawn after the choice, above all the hub page's additions on SCR-101 and SCR-104 and the panels' loading, stale and gone states.
2. The words the mockups added to stage 08's messages.
3. The two differences from phase 1 above, and the skipped and not-recorded stages, which joined the tokens with a skipped stage's text darkened to 4.5:1.

## Notes for later stages

### Stage 10: work breakdown

- One task builds the custom properties from the resolver, the base and each theme, in the order that it gives, for the views and for 0.2's parts of the hub page; the frames' styles show the names in use.

### Stage 11: development

- The views take every colour and length from the tokens; the picture's own drawing keeps the editor's colours, inverted in dark mode as the editor does.
- Marks are buttons with names that say what they count, as the frames name them; they keep their size at every zoom and merge for each context at the whole picture.
- In the frames an item's ID is text with the look of phase 1's button; the hub page keeps the button, which opens the trace view.
- The step view lays each step out from the picture source's timeline and context tables, as the five frames show, and keeps no layout (SPEC-141).

### Stage 12: QA

- Each state at 320 and 1440 pixels, in both themes and languages, measured with the page check and looked at as images, with the contrast pairs above computed again from the frozen tokens.
- The step control at the first and the last step, on a board without a timeline, and with an address that holds `step=` (SPEC-141).
