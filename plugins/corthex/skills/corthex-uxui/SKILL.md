---
name: corthex-uxui
description: Craft for screens, motion and video. Use when making or reworking a web or app screen, a landing page, a dashboard or a mockup, when setting the timing and curves of UI motion such as a button, menu or modal, when making a motion graphic or explainer video built as HTML and rendered to MP4, or when deciding what each slide should draw. Turns vague design words into named parts and numbers, and measures line breaks (including Korean), contrast, target size, flashes and loudness before showing the result. Not for code unrelated to screens or for diagrams inside a document.
license: Apache-2.0
metadata:
  author: kodonghui
  version: "0.4.0"
---

# Screens, motion and video

Turn feeling words, such as "clean" or "make it pop", into the **names and numbers** of parts and motions, build from them, and **measure** before you show anything. The skill works on its own. Inside a CORTHEX project it serves the screen stages (08 screen states, 09 mockup) and the presentation (13).

- The project's own design contract comes first: its design tokens (stage 09, by default `design/base.tokens.json`), its screen definitions (stage 08) or a `DESIGN.md`. Their values win over the numbers in this skill.
- `[default]` marks a value this skill chose where sources disagree ([sources.md](references/sources.md)). `[proposal]` marks a rule of thumb with no source behind it; treat it as a starting point. When the person asking sets a value, use theirs.
- A small edit, such as one colour or one gap, does not go through every step below. Use the terms and checks it needs.

## When to use

| Use it | Do not use it |
| --- | --- |
| Making or reworking web or app screens, dashboards, landing pages and mockups | Code unrelated to screens: servers, data, builds |
| Setting the time and curve of UI motion: buttons, menus, modals | Diagrams inside a document only, such as Mermaid |
| Making a motion graphic, an explainer or a product video in code | Cutting filmed footage |
| Deciding what each slide of a talk should draw | |
| Requests that come as "something like this", a reference link or capture, or vague design words | |

## Steps: purpose, references, name it, build, check

### 1. Purpose

- Write it in one sentence. A screen: "[who] looks at this screen [where] to [do what]". A video: "This video tells [whom] [what]".
- What to build comes from the request and the project's documents: requirements, user flows, screen definitions. Never add a feature, a screen or copy because a reference has it.
- Ask what you do not know in one go. For a screen: the devices, the widths to check, the real copy and data. For a video: where it is shown (the aspect ratio), its length, its sound and the deadline. Without an answer, go on with the defaults below and say in the report which defaults you used.

### 2. Choose references: [design-references.md](references/design-references.md)

- References decide **how** to make something, never **what**. Take their structure only: layout, order, proportions, and the timing and curves of motion. Never put their captures, copy, logos or numbers into the result.
- Settle the likeness first: 30, 50, 70 or 85%. Ask when the request does not say; without an answer, 50% `[default]`. "Not too different" starts at 70%.
- Ask for colours and fonts as values. Naming only what to avoid, such as "not a dark background", moves the result to the next most common answer.
- When a new visual direction is needed, sketch one idea along each of five paths: the product's material world, emotion, audience, the common answer turned around, and an unfamiliar format. Show two of them as candidates, or more only when the person asks (stage 09's rule in CORTHEX). When a colour or font is what anyone would guess from the field's name alone, write why this product needs it.

### 3. Name it

Rewrite the request in the form below and build from that sentence. When the direction is open, show the sentence to the person first.

- Screen: **[which screen, where] + [part name] + [content] + [numbers and states]**. See [ui-terms.md](references/ui-terms.md).
- Motion: **[on what] + [motion name] + [time in seconds, and in frames at the video's fps] + [curve values and order]**. See [motion-terms.md](references/motion-terms.md), with the numbers in [motion-values.md](references/motion-values.md).
- Video: write the scene table before making anything: number, time, picture, why, motion, transition and sound. See [video.md](references/video.md). In a CORTHEX project, extend stage 13's scene table and keep its SCENE IDs.
- Write curves as `cubic-bezier` values, not names. "ease-out" is a different curve in different tools.
- Turn a feeling word into two candidates made of names and numbers, and ask which one (the tables at the top of ui-terms.md and motion-terms.md).

### 4. Build

- Screens: give each control its eight states (default, hover, pressed, focus, disabled, loading, selected and error), and give the screen its empty, loading and error states, with any others its screen definition lists. A loading state keeps the loaded layout, so nothing moves when the data arrives. For Korean text, set `word-break: keep-all` and `overflow-wrap: break-word`.
- UI motion: cut or shorten what people see dozens of times a day. Animate only `transform` and `opacity`. Under `prefers-reduced-motion`, drop changes of position and size and keep changes of opacity and colour.
- Video: build each scene in HTML so that **the same time t always gives the same frame**. Use no clock time, network, random numbers without a seed or motion outside the timeline. Engines and version pinning are in [tools.md](references/tools.md).
- Never make up numbers, reviews or customers, imitate a real service's logo, or copy someone else's cards or prompt text.

### 5. Check: [checklist.md](references/checklist.md)

Measure on a real render before showing anything. Always measure these four where they apply, and pick the rest from checklist.md.

| Check | Pass | How |
| --- | --- | --- |
| Line breaks | No word split at a line end, no overflow, no sideways scrolling of the page; Korean blocks have keep-all. At the project's widths, else 320, 390, 768 and 1440 `[default]` | `scripts/page-check.js` |
| Flashes | No more than three flashes in any one second, general and red flashes counted apart. Above that, check the flashing area with an analysis tool | `scripts/media-check.py`, then look once more |
| Contrast | Text 4.5:1; large text (18 pt ≈ 24 px, or 14 pt ≈ 18.7 px bold) 3:1; control borders, states and essential graphics 3:1 against their neighbours | page-check for text; borders and text over images by hand |
| Loudness | Online and presentation video −14 LUFS ±1 with the true peak below −1 dBTP; broadcast by its own rule | `scripts/media-check.py` |

- Write "not measured" for what you could not measure, never "passed". If you measured the numbers but did not look or listen, write "measured only".
- The report gives what you made, the references you used, the defaults you used, the results of the checks as numbers, and what you did not measure. The template is in checklist.md.

## Defaults (chosen where sources disagree)

| What | Default |
| --- | --- |
| Widths to check | The widths the project supports come first. Otherwise 390, 768 and 1440, plus 320 for reflow; add 1280 when many users are on laptops |
| Length of UI motion | Up to 300 ms. Only modals, drawers and page transitions go up to 500 ms, with the reason written down |
| Accelerating curve (ease-in) in UI | Only for exits that leave the screen completely |
| Spring bounce | 0.1–0.2 in product UI; 0.3–0.4 only for one moment of emphasis in a video |
| Target size | 24 px is the floor; aim for 44 pt on iOS and 48 dp on Android |
| Sound of a video | Understandable without sound, with captions; the sound is chosen once for the whole video. Music the person gave you, or music with a clear license, comes first; sound synthesised in code only after a person has listened and approved |
| Video review | P0–P2 notes instead of scores, and every P0 fixed. The two human gates stay: the scene table is approved, and a person watches and listens after the render |
| Aspect ratio and fps | Talks and YouTube 16:9 (1920×1080), short vertical video 9:16 (1080×1920). One fps per video: 30, or 60 for fast motion |
| Scene length | One script sentence per scene (3–6 s). In the hook and in short videos, change the picture every 2–4 s |
| Likeness to a reference | Ask first; without an answer, 50% |

## References (read only what you need)

| Task at hand | Read |
| --- | --- |
| Choosing references, the likeness, colours as values, diagrams for slides | [design-references.md](references/design-references.md) |
| Names and instructions for layout, spacing, type, parts and states; Korean text; loading without a jump; icons | [ui-terms.md](references/ui-terms.md) |
| Names and instructions for motion, camera and transitions; turning them into HTML | [motion-terms.md](references/motion-terms.md) |
| Time, curves and springs of UI motion, and its continuity; speed, frames and beats of video | [motion-values.md](references/motion-values.md) |
| The video brief, gates, scene table, same t same frame, sound, output, slides | [video.md](references/video.md) |
| Engines, libraries, an optional skill for promotional demos, version pinning and licenses | [tools.md](references/tools.md) |
| Every check, and how to run the two scripts | [checklist.md](references/checklist.md) |
| Sources, where they disagree, and why each default was chosen | [sources.md](references/sources.md) |

The two scripts only read. `scripts/page-check.js` runs inside the page under test and changes nothing on it. `scripts/media-check.py` needs Python 3.8 or later and FFmpeg, and changes no file.
