# Checklist

Measure on a real render before showing anything. Write "not measured" for what you could not measure, never "passed". If you measured the numbers but did not look or listen, write "measured only".

- The two scripts only help. Even when their results are clean, a person still looks once (and, for video, watches and listens).
- Where the scripts cannot run, measure the same criteria by hand and say how you measured.

## 1. Screens (web, app, HTML slides)

Measure each width on its own: the widths the project supports come first; otherwise 390, 768 and 1440, plus 320 for reflow `[default]`. Add 1280 when many users are on laptops.

| Check | Pass | How |
| --- | --- | --- |
| Korean line breaks | Korean blocks have `word-break: keep-all` and `overflow-wrap: break-word`; no `break-all`; no word split at a line end | page-check: `hangul-keepall`, `hangul-breakall`, `hangul-split`; vertical or turned text by hand |
| Overflow and clipping | No text outside its box, and none cut off without an ellipsis | page-check: `text-overflow`, `text-clipped`; turned text by hand |
| Sideways scrolling | None; readable at 320 without scrolling sideways (WCAG 1.4.10) | page-check: `page-overflow`, which names the likely causes |
| Orphans | No heading, button or short text ends with one short word on its last line | page-check: `orphan` (headings warn; body text is only counted) |
| Text contrast | Text 4.5:1; large text (24 px, or 18.7 px bold, at the size drawn) 3:1 | page-check: `contrast`. Text over images, gradients or other boxes (`contrast-image`): measure the worst spot by hand |
| Contrast of controls and states | Field borders, check marks, focus indicators and essential graphics 3:1 against their neighbours (1.4.11) | By hand: pick both colours and compute the ratio the same way |
| Target size | 24×24 px floor (with the spacing, in-sentence link and browser-sized control exceptions); aim for 44 pt on iOS and 48 dp on Android | page-check: `target-size`, `target-goal` |
| Keyboard | Every control works with Tab; focus is visible (2.4.7), never hidden by something else (2.4.11), and follows the visual order | By hand, with Tab and Shift+Tab |
| States | Default, hover, pressed, focus, disabled, loading, selected and error, plus the screen's empty, loading and error states | By hand, against the list |
| Forms | Every field has a label; errors say in text what is wrong and how to fix it (3.3.1, 3.3.3); a placeholder is not a label | page-check: `label`; the wording by hand |
| Content on hover or focus | It can be dismissed, stays while the pointer moves onto it, and does not vanish by itself (1.4.13) | By hand |
| Text spacing | No clipping or overlap at line height 1.5, 2em after paragraphs, letter spacing 0.12em and word spacing 0.16em (1.4.12) | Add the snippet below and run page-check again |
| Motion | Only `transform` and `opacity` move; no `transition: all`; reduced motion drops changes of position and size; anything that moves on its own for more than 5 s can be paused (2.2.2) | page-check: `transition-all`, `transition-layout`, `reduced-motion`; then by hand with reduced motion on |
| Flashes | No more than three a second | Record the screen and run media-check on the recording |
| Basic accessibility | Meaningful images have alt text, decorative ones `alt=""`; `html` has `lang` | page-check: `img-alt`, `lang` |

Text spacing test (1.4.12): paste this into the console and run page-check again. Reloading the page undoes it.

```js
document.head.insertAdjacentHTML("beforeend", "<style>*{line-height:1.5!important;letter-spacing:.12em!important;word-spacing:.16em!important}p{margin-bottom:2em!important}</style>")
```

Reduced motion: in the developer tools, Rendering → Emulate CSS media feature `prefers-reduced-motion: reduce`. In Playwright, `page.emulateMedia({ reducedMotion: "reduce" })` (Node) or `page.emulate_media(reduced_motion="reduce")` (Python).

## 2. Video

The last gate of [video.md](video.md) section 3. Never drop the human gates: the scene table is approved, and a person watches and listens after the render.

| Check | Pass | How |
| --- | --- | --- |
| Contact sheet | Each scene just after its start, in the middle and at the end, and the frames either side of each cut. No overlap, clipping or font swap; text readable at phone width (360 px) | HyperFrames `snapshot --review`, or frames from FFmpeg on one sheet (below) |
| Korean line breaks | No split words or overflow in the scene HTML | page-check with the window at the video's size |
| Text size and time on screen | At least 28 px at 1080. A line to read holds 0.5 s plus 0.3 s per word; the last line at least 2 s; Korean captions at most 12 characters per second | Against the scene table. HyperFrames `check` warns with `line_unread` and `text_below_floor` |
| Freezes | Any stretch of more than 3 s without change is an intended hold, written in the scene table | media-check: `freeze`. HyperFrames: `dead_stretch` |
| First frame | Not empty (it becomes the thumbnail on social platforms) | media-check: `first-frame` |
| Same t, same frame | Capturing the same time twice gives the same pixels; a loop's end joins its start | Render twice and compare the frame hashes (below) |
| Sound and picture in sync | An effect peaks with its cause on screen, or one frame after it | By hand, stepping frame by frame |
| Flashes | In no one second more than three general flashes, or more than three red flashes. Above that, the flashing area is at most 25% of a 10° field | media-check: `flash`, `flash-area`, `flash-extended` |
| Loudness | Within the target's tolerance (±1 LU; ±0.5 for EBU), with the true peak under its limit | media-check: `loudness`, `true-peak` |
| File | Length, resolution, fps and frame count as intended; sound at 48 kHz; H.264 in `yuv420p` | media-check with `--expect-size`, `--expect-fps`, `--expect-duration`; `pix-fmt`, `sample-rate` |
| What not to do | Where a default look from [video.md](video.md) section 8 is used, this video has a reason | Against the list |
| Copy | Every line on screen has its source in the design documents; no made-up numbers or reviews | Against the documents |
| Embedded on the web | Anything that plays on its own for more than 5 s can be paused; reduced motion gets a still or a reduced version | By hand |
| A person watches and listens | On earphones, laptop speakers and the venue's screen | The person asking |

A contact sheet from FFmpeg, one frame every 0.5 s, twelve to a sheet:

```sh
ffmpeg -i out.mp4 -vf "fps=2,scale=320:-1,tile=4x3" -frames:v 1 sheet.png
```

Same t, same frame: the frame hash lists of two renders must match.

```sh
ffmpeg -v error -i a.mp4 -map 0:v -f framemd5 a.txt
ffmpeg -v error -i b.mp4 -map 0:v -f framemd5 b.txt
# pass when every line matches (diff on macOS and Linux, fc on Windows)
```

Write review notes instead of scores: `t=4.2s · where · problem → change · keep`. Sort them into P0 (breaks reading or a promise), P1 (weakens the video) and P2 (polish), and fix every P0 `[default]`.

## 3. Flashes in detail (WCAG 2.3.1)

- **One flash** is a pair of opposing changes in brightness (brighter, then darker). So a light that turns on and off three times a second (3 Hz) makes three flashes and passes; from 4 Hz it fails. EA IRIS also counts four transitions as two flashes.
- **General flash**: the relative luminance changes by 0.1 (10% of the maximum) or more, and the darker of the two states is below 0.8.
- **Red flash**: one state is saturated red (R ÷ (R + G + B) ≥ 0.8 in linear RGB), and the two colours are more than 0.2 apart in the CIE 1976 u′v′ chromaticity diagram. A red ↔ grey flicker of similar brightness counts too.
- **Area exception**: it passes when the area flashing together is at most 25% of any 10° field of view. A 10° field is about 341×256 px on a 1024×768 screen; media-check takes a 4:3 box one third of the frame's width. Sitting closer makes the real field cover more of the screen, so this estimate errs on the strict side.
- **Extended flashing**: two or three flashes a second kept up for five seconds is reported as a warning even within the limit, as IRIS does. Tone it down when it is decoration.
- **Not measured**: media-check does not measure pattern flashing (stripes, checkerboards) or HDR video. For HDR, use a tool built on ITU-R BT.1702.
- **Analysis tools**: when a result touches the limit or passes by the area exception, check once more. [EA IRIS](https://github.com/electronicarts/IRIS) is free (BSD 3-clause); Harding FPA is paid. The W3C's Understanding document also names PEAT, which is reported to be no longer supported.
- **Fixes (common cause → change)**: a white frame on every beat → at most three a second, or a brightness difference under 10% / a flickering red warning screen → turn it on once and keep it / fast black-and-white cuts → a mid-brightness scene between the cuts / a full-screen strobe → only a small part of the screen.

## 4. Loudness

| Where it plays | media-check `--target` | Integrated loudness | True peak |
| --- | --- | --- | --- |
| Online and presentation video `[default]` | `online` | −14 LUFS ±1 | Below −1 dBTP (below −2 recommended when mastered louder than −14) |
| Social video (HyperFrames' guidance) | `social` | −16 to −14 LUFS | Below −1 dBTP |
| South Korean TV | `tv-kr` | −24 LKFS ±2 | Not judged |
| European broadcast (EBU R 128) | `ebu` | −23 LUFS ±0.5 (±1 for live) | −1 dBTP |
| US broadcast (ATSC A/85) | `atsc` | −24 LKFS ±2 | Not judged; follow the broadcaster's delivery rules |

The commands to measure and to match are in [video.md](video.md) section 6. After matching, measure again and write the numbers down.

## 5. Running the scripts

### page-check.js (in the browser; changes nothing on the page)

- **Console**: paste the file's contents into the developer tools console and press Enter. A summary is printed, and the full result stays in `window.__pageCheckReport`. Change the window width and paste it again.
- **Automation**: pass the file's contents as a string to `evaluate` (Playwright, Puppeteer or a browser tool) and the report object comes back. In Node: `await page.evaluate(fs.readFileSync("scripts/page-check.js", "utf8"))`.
- **Options**: before running, `window.__pageCheckOptions = { maxIssues: 300, maxChars: 40000 }`. With more text than that, only part is measured and the report says `truncated: true`.

```python
# Python. Once: pip install playwright && playwright install chromium
import pathlib
from playwright.sync_api import sync_playwright

src = pathlib.Path("scripts/page-check.js").read_text(encoding="utf-8")
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("http://localhost:3000/")  # the page to check
    for w in (320, 390, 768, 1440):
        page.set_viewport_size({"width": w, "height": 900})
        r = page.evaluate(src)
        print(w, "pass" if r["pass"] else "fail", r["counts"])
        for i in r["issues"]:
            if i["level"] != "info":
                print("  ", i["level"], i["check"], i["msg"], i["where"])
    browser.close()
```

- **Result**: `pass` (true when there are no errors), `counts` (errors, warnings, info), `byCheck`, `issues` (level, check name, message, a selector for where, the start of the text), `notMeasured`, `viewport` and `env` (reduced motion and dark mode).
- **Levels**: an `error` must be fixed to pass; a `warn` is fixed or given a reason; `info` is for reference.
- **Check names**: `hangul-keepall`, `hangul-breakall`, `hangul-overflowwrap`, `hangul-split`, `latin-split`, `text-overflow`, `text-clipped`, `orphan`, `orphan-body`, `page-overflow`, `contrast`, `contrast-image`, `contrast-opacity`, `target-size`, `target-size-spacing`, `target-goal`, `img-alt`, `label`, `lang`, `transition-all`, `transition-layout`, `transition-long`, `reduced-motion`.

### media-check.py (only measures the file)

It needs Python 3.8 or later and FFmpeg (`ffmpeg` and `ffprobe`), and uses the standard library only. It opens local files only, so a playlist that points elsewhere cannot reach the network, and it takes `ffmpeg` and `ffprobe` from the absolute folders on PATH, never from the current folder, unless you give their paths.

```sh
python3 scripts/media-check.py out.mp4                       # loudness (online, -14) + flashes + file
python3 scripts/media-check.py out.mp4 --target tv-kr        # South Korean broadcast
python3 scripts/media-check.py out.mp4 --expect-size 1920x1080 --expect-fps 30 --expect-duration 60
python3 scripts/media-check.py out.mp4 --json                # a result other tools can read
# on Windows, py instead of python3
```

- **Options**: `--lufs`, `--lu-tol` and `--tp` (set the target yourself); `--grid` (cells across for counting flashes, 48 by default; 32 is faster for long videos); `--freeze` (seconds without change to report, 3 by default); `--no-video`, `--no-audio`; `--ffmpeg`, `--ffprobe` (paths).
- **Exit code**: 0 pass (there may be warnings), 1 fail, 2 could not measure.
- **Check names**: `loudness`, `true-peak`, `true-peak-loud`, `silent-track`, `silence`, `sample-rate`, `audio-streams`, `no-audio`, `flash`, `flash-area`, `flash-edge`, `flash-extended`, `first-frame`, `freeze`, `black`, `size`, `fps`, `duration`, `frames`, `pix-fmt`, `vfr`, `hdr`, `alpha`, `decode`.
- **Speed**: a 60 s video at 1920×1080 and 30 fps took about 5 s on a 4-core Linux machine.
- **Limits**: the flash count averages the frame down to a grid, so it is an approximation. Measure flashes on a web page from a screen recording of it.

## 6. Report template

```text
Made: [screen or video name, file or address]
References used: [name, link] · likeness [50]% · what was taken (layout, rhythm, curves)
Defaults used: widths 390, 768, 1440 + 320, sound −14 LUFS … (the person asking did not set them)
Check results: page-check at 320, 390, 768, 1440: 0 errors, 2 warnings (reasons) / flashes at most 1 a second / −14.1 LUFS, −1.6 dBTP
Not measured: [keyboard order, contrast of text over images …]
Measured only: [the sound was measured, not listened to …]
Review notes (video): t=4.2s · title · gone before it can be read → hold 0.8 s longer · keep the entrance curve (P0)
```
