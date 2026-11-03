# Making video

The method here builds each scene as a web page (HTML), has a headless browser capture it frame by frame, and joins the frames into an MP4 with FFmpeg. Whatever the engine, the rule is **the same time t always gives the same frame**. For UI motion such as buttons and menus, see sections 1–5 of [motion-values.md](motion-values.md).

## 1. The brief: what to write before making anything

| Layer | What to decide |
| --- | --- |
| 0 · Story | The message in one sentence ("This video tells [whom] [what]"), the emotion that changes in each scene, the order of the scenes |
| 1 · What | The name of the graphic in each scene |
| 2 · How | Motion names, with seconds and frames at the video's fps and curve values ([motion-terms.md](motion-terms.md)) |
| 3 · Quality | The output format, the sound (once), what not to do, how it will be reviewed |
| 4 · Gates | What is checked before moving on, and where a person approves |

- **Decide the sound once for the whole video.** Sound instructions on every scene's sentence clash with each other (section 6).
- Turn adjectives into numbers: colours as hex, type as font, weight and px, motion as curve values and frames, layout as columns and gaps in px. A list of things to avoid works only together with the values you want.
- Match the tone of captions and on-screen text to the audience. A video that teaches how something works speaks as to someone learning it for the first time; a talk or product video introduces as to someone seeing it for the first time `[default]`.
- On a first try, it already changes the result a lot to pick names only in layer 1, two or three motions with their seconds in layer 2, and five quality lines in layer 3.

## 2. The five slots of a request

**① call the tool + ② what (the graphic's name) + ③ materials (on-screen text, files) + ④ when and how long (start and length) + ⑤ look (colours, aspect ratio)**

- Use ① only when the HyperFrames skill is installed (`/hyperframes` in Claude Code, `$hyperframes` in Codex). Without it, leave ① out and write the scene in HTML yourself.
- Copy logos, photos and footage into the working folder first, and refer to them by file name.
- Results vary a little each time. Change one thing at a time: "bigger", "slower", "only the colour".

```txt
/hyperframes Make one scene of a talk video.
[What] A step-by-step diagram 1→2→3. The steps are "Sign up", "Verify", "First booking".
[How]  The three circles enter with a 0.12 s stagger (cubic-bezier(0.23, 1, 0.32, 1), 0.4 s);
       the arrows between them are a 0.3 s line draw; only the last circle overshoots to 105% and settles at 100%.
       When everything is in, a 1.5 s moving hold.
[Look] 4 s, 30 fps, 16:9 (1920×1080). Background #FFFFFF, text #1B2A4A, one accent #E8590C.
       The quoted text exactly as written, inside 5% of the edges, no arrow crossing a circle.
       No sound (the whole video's sound comes later). No more than three flashes in any second.
       Fonts from the files in assets/fonts/ with @font-face; Korean blocks with word-break: keep-all.
       Before the full render, show a contact sheet of stills every 0.5 s.
```

## 3. Steps and gates

| Step | Do | Move on when |
| --- | --- | --- |
| Plan | One-sentence message → scene table (section 4) | **The person asking approves the scene table** |
| Frame | Scene shells that seek to t; fix the versions | Capturing the same t twice gives the same pixels |
| Sketch | The key moment of each scene with the real fonts, colours and copy → a contact sheet. The layout is settled here | No overlap, clipping or font swap; readable at phone size |
| Timing | An animatic (grey boxes, only the timing and the sound) | The beats and lengths fit |
| Production | Render from start to end → review notes | No P0 left |
| Polish | Remove the default look; sharpen the focus | None of the banned defaults (section 8) |
| Sound | Find the beats → place the effects → duck → match the loudness | Within ±1 LU of the target; sound and picture within one frame |
| Final check | Final render → file checks → **a person watches and listens** | The video table in [checklist.md](checklist.md) passes |

- Even when not every gate can be kept, keep the **two human gates: the scene table is approved, and a person watches and listens after the render**. A score the making AI gave itself is never enough to pass.
- Review in notes, not scores: `t=4.2s · where · problem → change · keep`. Sort them into P0 (breaks reading or a promise), P1 (weakens the video) and P2 (polish), and fix every P0 `[default]`. While writing notes, scan seven things: the hook, readability at phone size, motion, variety, composition, brand accuracy and sound sync.
- Fix only the failed scenes and watch those scenes again. Never change a length to hide a fault.

## 4. Message, story and the scene table

**Message and order**

- The first scene says, in the viewer's words, why to watch: what they gain, what they avoid, what they finally understand. Never open with internal terms, a feature list or file names.
- The message comes by the second scene at the latest; what follows is its evidence. Use numbers only when they carry weight ("a check that took 3 minutes now takes 10 seconds" works; "23 features" does not).
- Take the props on screen from real sources: design documents, real screens, real numbers. If a prop could appear unchanged in another product's video, look again.
- Put the core in the first 3 s and the hook within the first 6 s.

**Story craft**

- The emotion changes in every scene (from + to −, or from − to +). Cut a scene whose change you cannot name.
- Enter late and leave early. Never open a scene with an explanation.
- Turn the story once or twice, and keep one motif that comes back a little changed.

**Scene table** (shown to the person asking in the plan step, before anything is made)

| # | Time (s · frames) | Picture (graphic name) | Why (its link to the message) | Motion and curve | Transition | Sound |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 0–3 s · 0–90 | One key word filling the screen (kinetic typography) | Hook: the problem in one word | Punch in (1.0 → 1.3× at the cut) | Cut | None |
| 2 | 3–8 s · 90–240 | … | … | … | … | … |

- In a CORTHEX project, stage 13's scene table is this table: keep its SCENE IDs and columns, and add the columns above that it lacks.
- One script sentence per scene (3–6 s). In the hook and in short videos, change the picture every 2–4 s `[default]`.
- Do not use the same kind of scene twice in a row; mix 4–6 kinds in one video and close with a summary scene.
- Inside one scene: build (0–30%, elements enter one after another) → hold (30–70%, one quiet motion) → close (70–100%, exits faster than entrances).
- An information card is complete within about 2.5 s and then stays still, so that any paused frame reads as a finished poster.

**Seven scenes for short explainers**

| When | Scene | Names to use |
| --- | --- | --- |
| Tools or services are named | Logo cards side by side | Pop-in, stagger |
| A feature is explained | A real screen tilted back, zooming in on the point | Perspective tilt, dolly, zoom |
| A number comes up | The number counting up, filling the screen | Count-up |
| An input, a command or a process is described | Typed in one character at a time | Type-on |
| One word should land | Only the key word, filling the screen | Punch in |
| A is compared with B | The screen split in two, side by side | Split screen |
| The video sums up | Each line ticked, with a stamp at the end | Line draw, pop-in |

## 5. The same t gives the same frame

Build each scene as "a function that, given t, draws the screen at that moment". Then one scene can be fixed and captured again, sound effects can sit on exact frames, and the last frame can match the first to the pixel.

- No clock time, network requests, timers, endless repeats (`repeat: -1`) or random numbers without a seed. Attach every motion to one paused timeline; motion outside the timeline shows in the preview and goes missing from the render.
- Scenes driven by rules, such as particles, use seeded random numbers and a fixed time step, and compute a frame by running from 0 to that frame at the same step.
- Compute springs as a function of t instead of accumulating them frame by frame.
- Keep fonts as local files and capture after they have loaded (`document.fonts.ready`). Load the fonts of later scenes in advance too.

**What breaks in GSAP**

- Do not stack several `transform` tweens on one element. Merge them into one tween, or split them between a parent and a child.
- Inside a scene, use `fromTo()` rather than `from()`. A `from()` records whatever state the element is in when it is created, so when two tweens touch the same property, seeking out of order starts from the wrong state.
- Attach even quiet loops to the timeline (`tl.to(...)`). A separate `gsap.to()` does not appear in the render.
- Turn off elements that should vanish at a scene boundary with `tl.set()`.
- An iframe cannot be seeked in time; replace it with a captured image.

**With HyperFrames** (from its documentation in October 2026; it changes often, so check with `npx hyperframes docs`)

- Each scene builds one paused GSAP timeline, attaches all its tweens, and then registers it: `window.__timelines["<data-composition-id>"] = tl`. The scene's `data-composition-id` and the registered name match.
- Timed elements have `class="clip"` with `data-start` and `data-duration` in seconds, and show over [start, start + duration), so land an end state just before the end. The video's length is the root's `data-duration`.
- Never tween `display`, `visibility` or `autoAlpha` on a `.clip`; animate a child. Give no CSS `transform` to an element GSAP transforms. Never call `play()`.
- **No Korean font is bundled.** Put a font file (such as Pretendard, under the SIL Open Font License) in `assets/fonts/` and connect it with `@font-face`.
- New videos default to 1920×1080 at 30 fps. The loop: `npx hyperframes lint` while writing → `check --json` with no errors → `snapshot` to look at stills → `preview` → `render --quality draft` while fixing, `delivery` for the final, with `--output out.mp4`.
- When the sound is not decided, the HyperFrames skill adds music and sound effects to story videos longer than about 15 s. Write the sound decision into the request.

**Capturing it yourself, without an engine**

```html
<script>
  const tl = gsap.timeline({ paused: true });
  tl.fromTo("#title", { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: 0.4, ease: "power3.out" }, 0.2);
  window.renderAt = (t) => { tl.seek(t); }; // same t, same picture; returns nothing
</script>
```

- The capture tool (Playwright or another) calls `renderAt(i / fps)` for every frame i and saves a PNG once the fonts and images are ready. Keep `renderAt` returning nothing: when it returned the timeline, the capture tool stalled while taking over that large object (seen while the first draft of this skill was tested). Capturing the frames in shuffled order and getting the same frame hashes also passes the determinism test ([checklist.md](checklist.md) section 2). Then join the frames:

```sh
ffmpeg -framerate 30 -i frames/%05d.png -c:v libx264 -pix_fmt yuv420p -crf 18 -movflags +faststart out.mp4
```

- For fast motion, motion blur from several samples per frame (such as four, blended) is optional.
- Pin the versions (engine, GSAP, browser) in `package.json`, and write the render command, the seed and how the sound was made in the README.

## 6. Sound

- **First pick one**: ① no sound (safe when the venue's speakers are unknown), ② music and sound effects, ③ narration first. Write the choice once, in layer 3 of the brief. Whichever you pick, the video is understandable without sound, with captions (Korean at no more than 12 characters per second).
- Music the person gave you, or music with a clear license, comes first. Use sound synthesised in code only after a person has listened and approved `[default]`. Record each file's source, license and how it was made.
- With the HyperFrames skill, its own sound defaults apply (music and sound effects in story videos over about 15 s). Write your sound choice into the request.
- Beats: one beat = 60 ÷ BPM seconds. Put cuts and sound effects on the beat grid ([motion-values.md](motion-values.md) section 7).
- Music sits about 6 dB under the sound effects, and dips about 3 dB more while an effect plays (ducking). Lower the music under narration too.
- Sound effects only where something on screen causes them, 3–6 dB above the music bed, peaking one frame after the picture. Rotate two or three variants of the same effect.

| Where it plays | Integrated loudness | True peak |
| --- | --- | --- |
| Online and presentation video `[default]` | −14 LUFS ±1 | Below −1 dBTP (below −2 dBTP when mastered louder than −14) |
| Social video (HyperFrames' guidance) | −16 to −14 LUFS | Below −1 dBTP |
| South Korean TV | −24 LKFS ±2 | — |
| European broadcast (EBU R 128) | −23 LUFS ±0.5 (±1 for live) | −1 dBTP |
| US broadcast (ATSC A/85) | −24 LKFS | — |

```sh
# Measure: read Integrated loudness (I) and True peak (Peak) in the Summary at the end
ffmpeg -hide_banner -nostats -i in.mp4 -af ebur128=peak=true -f null -
# Match (one pass): the video is copied, only the sound is encoded again
ffmpeg -i in.mp4 -af loudnorm=I=-14:TP=-1:LRA=11 -ar 48000 -c:v copy -c:a aac -b:a 192k out.mp4
```

- Without `-ar 48000` the output comes out at 96 kHz. After matching, measure again with the first command and write the numbers down. To keep the music's dynamics, run two passes with the measured values (`loudnorm` in the FFmpeg documentation).
- `scripts/media-check.py` does the measurement above and the flash count in one run.
- Numbers can pass and still grate. If you did not listen, write "measured only". Listen once on earphones and once on laptop speakers, and set the volume at the venue's rehearsal.

## 7. Output format and safe areas

- Where it plays sets the aspect ratio: talks and YouTube 16:9 (1920×1080), shorts and reels 9:16 (1080×1920) `[default]`. When a kit comes in another ratio, lay the scenes out again.
- One fps per video: 30 by default; 60 when the motion is fast or there is a lot of moving text.
- Safe area: text, logos and captions stay 5% in from the edges (the EBU R 95 graphics safe area) `[default]`. When working in HyperFrames, keep inside its guides (content in the 90% action-safe box, captions and key text in the 80% title-safe box). For shorts and reels, the app's buttons and descriptions cover the top and bottom; check the platform's current guidance.
- Choose the poster frame, the one still most people see: the thumbnail, the view under reduced motion, a screenshot. Pick a moment that tells the story by itself, with the result on screen, never a frame in the middle of a change, such as a number mid-roll or a half-done fade. Test it: from the still alone, can someone tell what happened? If not, choose another moment.
- A video to lay over other video or slides goes out as WebM (VP9) with a transparent background. The frame PNGs need transparency (capture without a background), encoded as below. Turning transparent PNGs straight into MP4 shows the hidden colours behind the transparent areas.

```sh
ffmpeg -framerate 30 -i frames/%05d.png -c:v libvpx-vp9 -pix_fmt yuva420p -b:v 0 -crf 30 out.webm
```

- File check: the length, resolution, fps and frame count match what was intended.

```sh
ffprobe -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate,nb_frames:format=duration -of default=nw=1 out.mp4
```

## 8. What not to do

- Made-up figures, customers, results or reviews. Only numbers with a source; mark example names as fictional.
- Imitating a real service's logo, name or screens; captures that show personal data.
- Copying someone else's prompts, cards or scene source as they are. Write the names and methods in your own words.
- Generated fake photographs on topics where trust matters, such as health.
- The defaults generated video falls into when nothing is decided. To use one, write why this video needs it:
  - A small element in the middle of an empty dark background; a centred title on a gradient
  - Glow, neon and decorative particles; purple-to-blue gradients; glass cards
  - The same slow zoom in every scene; the same bottom-up entrance on every element; everything fading in at once; a crossfade on every transition
  - Text that moves while it is being read; titles that keep floating after they land
  - Decorative corner labels, frames and gauge numbers

## 9. Lines worth adding to a request

```txt
- Write every motion's length in seconds, with its frame count at this video's fps.
- No more than three flashes in any one-second window.
- List every piece of music and every sound effect in a table: where it came from and on what terms it may be used.
- Name each transition (such as whip pan, match cut, iris, zoom-through). Several elements enter 0.08 s apart.
- Fictional names only; numbers and statistics only with a source.
- Only the features and copy that are in the design documents.
- Before the full render, show a contact sheet of stills, and mark the stretches that are meant to stand still.
```

## 10. One slide

When slides go with the video, decide what each slide draws before designing it. The look follows the video's direction.

- Write each slide's judgement sentence first: "On this slide the audience decides ___". Choose the layout, chart or diagram that helps that judgement, and keep one line on why.
- Choose a chart by what it should say: deviation from a reference (diverging bar), correlation (scatter), ranking (ordered bar, slope), distribution (histogram, box plot), change over time (line), magnitude (column, bar), part-to-whole (stacked bar, treemap, waterfall), spatial (choropleth), flow (Sankey). The categories follow the FT Visual Vocabulary.
- Choose a diagram by the relation: an unordered set is a list; when one step must end before the next, a process; when the end leads back to the start, a cycle; when the top decides the bottom, a hierarchy (up to four levels); four cells from two axes, a matrix (name both axes). More diagrams are in [design-references.md](design-references.md) section 6.
- Without data behind it, draw no chart and write "no data".
- Write titles as conclusions. Check that the titles alone tell the story and that each slide's point reads within 3 s. Close the last slide with the conclusion in one sentence and the next action.
- One emphasis per slide. On a comparison slide, mark the one option you recommend, and put the meaning beside each result number.
- Avoid: 3D charts, dual Y axes, bars that do not start at zero, pies with more than six slices, rainbow colours for ordered data, heavy grid lines, Venn diagrams for things that do not overlap, titles that only name a framework ("SWOT analysis"), and the same layout on every slide.
- In a CORTHEX project, the slides follow stage 13: the scene table first, then the slides.
