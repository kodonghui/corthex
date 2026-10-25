# Sources and choices

Where this skill's numbers and rules come from, and what it chose where sources disagree. The skill was first drafted in Korean on 2026-10-24 from the maintainer's notes on public glossaries, guides and tools. It was rewritten in English for this repository on 2026-10-25, and the values that change over time were checked again against the sources below on that day. The terms, instructions and examples were written anew; no card, picture or sentence from another work was copied.

## 1. Primary sources

| What | Source |
| --- | --- |
| Accessibility criteria | [WCAG 2.2](https://www.w3.org/TR/WCAG22/) and its [Understanding documents](https://www.w3.org/WAI/WCAG22/Understanding/): target size 2.5.8 and 2.5.5, contrast 1.4.3 and 1.4.11, reflow 1.4.10, text spacing 1.4.12, content on hover or focus 1.4.13, line spacing 1.4.8, pause 2.2.2, focus 2.4.7 and 2.4.11, forms 3.3.1–3.3.3 and 3.3.8 |
| Flashes | [General and red flash thresholds](https://www.w3.org/TR/WCAG22/#dfn-general-flash-and-red-flash-thresholds), [Understanding 2.3.1](https://www.w3.org/WAI/WCAG22/Understanding/three-flashes-or-below-threshold.html), [ITU-R BT.1702](https://www.itu.int/rec/R-REC-BT.1702/) for HDR, [EA IRIS](https://github.com/electronicarts/IRIS) (BSD 3-clause; counts four transitions as two flashes and reports extended flashing) |
| Korean layout | [Requirements for Hangul Text Layout and Typography](https://www.w3.org/TR/klreq/) (the 160% line spacing example) |
| Loudness | [Spotify's loudness normalization](https://support.spotify.com/artists/article/loudness-normalization/) (−14 LUFS; true peak below −1 dBTP, below −2 when mastered louder than −14), [EBU R 128](https://tech.ebu.ch/docs/r/r128-2014.pdf) (−23 LUFS ±0.5, ±1 for live; −1 dBTP), the Korean notice on the loudness of digital television programmes (디지털 텔레비전 방송프로그램 음량 등에 관한 기준, on [law.go.kr](https://www.law.go.kr); −24 LKFS), ATSC A/85 (−24 LKFS), [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html) (`ebur128`, `loudnorm`) |
| Safe areas | [EBU R 95](https://tech.ebu.ch/publications/r095) (action safe 3.5% and graphics safe 5% from each edge) |
| Target size on platforms | [Apple HIG: Accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility) (44×44 pt), [Android accessibility help](https://support.google.com/accessibility/android/answer/7101858) (48×48 dp, 8 dp apart) |
| Caption reading speed | [Netflix Korean Timed Text Style Guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/216001127-Korean-Timed-Text-Style-Guide), section I: up to 12 characters per second for adult programmes, 9 for children's |
| Curves and durations | Material 3 motion tokens as published in [Material Web](https://github.com/material-components/material-web/blob/main/tokens/versions/v0_192/_md-sys-motion.scss) and in Flutter's [motion.dart](https://github.com/flutter/flutter/blob/master/packages/flutter/lib/src/material/motion.dart); MUI's [transitions](https://mui.com/material-ui/customization/transitions/) (225 ms in, 195 ms out) |
| Springs | Flutter's [`SpringDescription.withDurationAndBounce`](https://github.com/flutter/flutter/blob/master/packages/flutter/lib/src/physics/spring_simulation.dart): damping ratio 1 − bounce for a bounce above 0, 1 ÷ (1 + bounce) otherwise |
| Chart categories | The [FT Visual Vocabulary](https://github.com/Financial-Times/chart-doctor/tree/main/visual-vocabulary) (© The Financial Times; only its category names are used) |
| HTML to video | [HyperFrames](https://github.com/heygen-com/hyperframes): its README, its CLI's README and its `hyperframes` and `hyperframes-cli` skills, read on 2026-10-25 |
| Licenses | [GSAP standard license](https://gsap.com/community/standard-license/), [Remotion license](https://www.remotion.dev/docs/license), [HyperFrames license](https://github.com/heygen-com/hyperframes/blob/main/LICENSE) |

## 2. Where sources disagree, and this skill's choice

Most of these are `[default]`: when the person asking sets a value, theirs wins.

| What | Choice | Where |
| --- | --- | --- |
| Sound in a video (leave it out / put it in / synthesise it) | Decided once per video; understandable without sound, with captions | video.md section 6 |
| Several dictionaries of motion names | Merged into one | motion-terms.md |
| The accelerating curve (ease-in) | Only for exits that leave the screen completely | motion-values.md section 2 |
| Lengths (UI, whip pan) | UI up to 300 ms (modals, drawers and pages up to 500 ms with a reason); whip pan 0.25–0.37 s (down to 0.13 s in fast promotional video) | motion-values.md sections 3 and 7 |
| Spring bounce | 0.1–0.2 in product UI; 0.3–0.4 for one moment of emphasis in video | motion-values.md section 4 |
| Target size | 24 px floor; aim for 44 pt and 48 dp | checklist.md section 1 |
| The unit of large text | WCAG's points: 24 px, or 18.7 px bold | checklist.md section 1 |
| keep-all in narrow boxes | Keep it, and fix the box or the copy | ui-terms.md section 3 |
| Widths to check | The project's widths first; otherwise 390, 768 and 1440, plus 320 for reflow (1280 when many users are on laptops). Stage 08's 360 and 1280 are its example of a project's narrowest and widest widths | checklist.md section 1 |
| One curve name, different values | Write `cubic-bezier` values | motion-values.md section 2 |
| Ten principles of animation, or four | Four, unless the video explains the principles | motion-terms.md section 2 |
| The tone of captions | Matched to the audience | video.md section 1 |
| Squash on text | 0% on names, numbers and prices; up to 3% on decorative text | motion-terms.md section 2 |
| Aspect ratio, fps and safe area | Where it plays sets the ratio; one fps; 5% from the edges (HyperFrames' own guides when working in it) | video.md section 7 |
| M3's "emphasized" curve | Pick by value, not by name | motion-values.md section 2 |
| The same word under different headings | Name and values instead of headings | motion-terms.md |
| Scene length | One script sentence per scene (3–6 s); 2–4 s in hooks and short videos | video.md section 4 |
| Sound synthesised in code | Given or clearly licensed music first; synthesised sound only after a person has listened and approved | video.md section 6 |
| How many kinds of transition | Each transition needs a meaning and a cause; for about a minute, start with two or three kinds | motion-terms.md section 5 |
| Reviewing a video (scores or notes) | P0–P2 notes; the seven criteria are things to scan | video.md section 3 |
| Caption reading speed | 12 characters per second for Korean; the Netflix page also shows higher limits (14 and 11) in a later section that could not be placed, so the stricter value stays | ui-terms.md section 3 |

## 3. What to check again, and the limits of this check

- Tools change often. Check the current version and its documentation before relying on a command, especially HyperFrames (`npx hyperframes docs`).
- The Korean TV figure's tolerance of ±2 and ATSC A/85's ±2 (described as acceptable measurement variation) come from secondary sources; the texts themselves were not read.
- Some official pages (Netflix, Apple, Android, EBU, Spotify) could not be opened from the working environment and were checked through search results that quote them.
- Licenses are summaries of published terms, not legal advice. Read them again before a commercial use.
- The scripts were run on Linux: `media-check.py` with Python 3.8.20 and 3.13 and FFmpeg 6.1 on synthetic clips (general and red flashes, the area exception, extended flashing, loudness), giving the same results on both; `page-check.js` in Chromium through Playwright for Node and for Python, at 320, 390, 768 and 1440 px on a page with known faults and on a clean page. They have not been run on Windows or macOS.
