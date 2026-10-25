# Motion values

UI motion and video motion use different curves and lengths. Sections 1–5 are for **UI**, such as buttons, menus and modals; sections 6–7 are for **video**. When the product has a design contract (tokens or a `DESIGN.md`), its values come first. `[default]` marks a value this skill chose where sources disagree (the table of choices in [sources.md](sources.md)).

## 1. Decide whether it moves at all (UI)

| How often people see it | Decide |
| --- | --- |
| More than 100 times a day (shortcuts, a command palette) | No motion, also for actions started from the keyboard |
| Dozens of times a day (hover, moving through a list) | Remove it or cut it right down |
| Now and then (modals, drawers, toasts) | Standard motion |
| Rarely, or once (onboarding, a first completion) | Delight is allowed |

- Motion needs a reason: it connects spaces, reports a state, explains, gives feedback, or softens a sudden change. If you cannot name the reason, remove it.
- Dashboards and work tools get no entrance effects, only motion that answers what the user does.
- Never carry information by motion alone, and never make people wait for a motion to finish.

## 2. Curves, as values rather than names

"ease-out" has different values in different tools. Write `cubic-bezier` values in requests and in code.

**This skill's UI curves** `[default]`

| Where | Value |
| --- | --- |
| Appearing and disappearing (most UI responses); when unsure, this one | `cubic-bezier(0.23, 1, 0.32, 1)` |
| Moving within the screen | `cubic-bezier(0.77, 0, 0.175, 1)` |
| Drawers and sheets (an iOS feel) | `cubic-bezier(0.32, 0.72, 0, 1)` |
| Hover and colour changes | `ease`, which is `cubic-bezier(0.25, 0.1, 0.25, 1)` |
| Things that keep going (progress bars, tickers) | `linear` |
| Only exits that leave the screen completely | `cubic-bezier(0.3, 0, 0.8, 0.15)` (M3 emphasized accelerate) |

- An accelerating curve (ease-in) looks sluggish in its first moment, so it is not for UI responses such as a press or an opening. Use it only for exits that leave the screen completely. Make the way out shorter than the way in (MUI's defaults, from the first Material guidelines: 225 ms in, 195 ms out).

**Same name, different values (for comparison)**

| Name | Value |
| --- | --- |
| CSS `ease-out`, `ease-in`, `ease-in-out` | (0, 0, 0.58, 1), (0.42, 0, 1, 1), (0.42, 0, 0.58, 1) |
| M3 emphasized decelerate, emphasized accelerate | (0.05, 0.7, 0.1, 1), (0.3, 0, 0.8, 0.15) |
| M3 standard, standard decelerate, standard accelerate | (0.2, 0, 0, 1), (0, 0, 0, 1), (0.3, 0, 1, 1) |
| M3 legacy (the first Material curves): standard, decelerate, accelerate | (0.4, 0, 0.2, 1), (0, 0, 0.2, 1), (0.4, 0, 1, 1) |
| GSAP | Names such as `power2.out` and `back.out(1.7)`. To match a value, give `CustomEase` a path such as `M0,0 C0.23,1 0.32,1 1,1` |

- For an entrance that "comes in strong and settles long", use M3 emphasized decelerate (0.05, 0.7, 0.1, 1). M3's curve named plain "emphasized" is drawn from two cubic segments; where a tool takes a single `cubic-bezier`, such as M3's web tokens, it is written as (0.2, 0, 0, 1), the same as standard. Do not pick a curve by its name.

## 3. Lengths (UI)

| Element | Length `[default]` | Material 3 duration tokens (for comparison) |
| --- | --- | --- |
| Press feedback | 100–160 ms | Short: 50, 100, 150, 200 |
| Tooltips, small popovers | 125–200 ms | |
| Dropdowns, select lists | 150–250 ms | Medium: 250, 300, 350, 400 |
| Modals, drawers, page transitions | 200–300 ms; up to 500 ms with the reason written down | Long: 450, 500, 550, 600 |
| Promotional and first-screen staging | Longer is allowed | Extra long: 700, 800, 900, 1000 |

- The cap is 300 ms. Only screen-sized panels (modals, drawers, pages) go up to 500 ms, with the reason written down.
- What the person controls is slow; what the system answers is fast. For example, press and hold to delete runs `linear` over 2 s while held, and springs back with a 200 ms deceleration on release.
- Delay only the first tooltip; tooltips that follow appear at once.
- A staggered entrance puts 30–80 ms between items, and never blocks input while it runs.

## 4. Springs

Motion computed from physics instead of a fixed time. It suits motion that can change direction midway, such as dragging.

- Start from `{ type: "spring", duration: 0.5, bounce: 0.2 }`. Most UI needs no bounce (bounce 0).
- Bounce `[default]`: 0.1–0.2 in product UI; 0.3–0.4 only for one moment of emphasis in a video.
- The conversion: for a bounce above 0, **damping ratio = 1 − bounce** (a damping ratio of 1 means no bounce; the smaller it is, the more it bounces). For a bounce of 0 or below, damping ratio = 1 ÷ (1 + bounce), so a negative bounce approaches more slowly without bouncing. Flutter's `SpringDescription.withDurationAndBounce` uses this formula; SwiftUI and Motion offer the same duration and bounce controls.
- Turning a duration into stiffness differs between tools (Motion alone computes `duration` and `visualDuration` differently). Do not convert by hand; use the tool's own parameters.

## 5. Starting shapes and implementation (UI)

- Never start from `scale(0)`. Start from `scale(0.9–0.97)` with `opacity: 0`.
- Popovers, dropdowns and tooltips grow from where they were opened: set `transform-origin`. Modals are the exception, because they sit in the centre of the screen.
- Pressable elements get `scale(0.97)` on `:active`, 160 ms decelerating. Keep blur under 20 px.
- Decide drag-to-dismiss by the speed at release, not by the distance dragged.
- Animate only `transform` and `opacity`. `width`, `height`, `margin`, `padding`, `top` and `left` make the browser lay the page out again.
- Name the properties to animate instead of `transition: all`.
- Fixed motion in CSS; motion that changes as it goes, such as dragging, in script or with a spring. For performance in script, `element.animate()` (the Web Animations API).
- Things that repeat quickly (toasts, toggles) use CSS transitions, which can reverse midway. For an entrance without script, `@starting-style`.
- Put hover motion inside `@media (hover: hover) and (pointer: fine)`. Touch screens fire a fake hover on a tap.
- Reduced motion (`prefers-reduced-motion: reduce`): reduce the motion, do not remove it. Drop changes of position and size, and keep the changes of opacity and colour that help understanding. Replace a live background drawn on a canvas with one still frame, and pause it when the tab is hidden.

```css
.sheet { transition: transform 300ms cubic-bezier(0.32, 0.72, 0, 1), opacity 200ms cubic-bezier(0.23, 1, 0.32, 1); }
@media (prefers-reduced-motion: reduce) {
  /* The position changes at once; only the opacity fades */
  .sheet { transition: opacity 200ms cubic-bezier(0.23, 1, 0.32, 1); }
}
```

## 6. Curves and speed in video

- Choose three curves by role and reuse them: decelerating entrances, ease-in-out moves, accelerating exits. Keep bounce, elasticity and overshoot for the one place you want to stress.
- Curves change the emotion. The same slide reads as confident with a strong deceleration, dreamy with a soft sine curve and playful with elasticity.
- Do not give every element the same curve, length and direction.
  - At most two independent tweens in one scene share a curve.
  - The slowest scene is about three times as slow as the fastest.
  - Rotate the way things enter: from the left, from the right, by scale, by opacity, by letter spacing.
- The first motion starts 0.1–0.3 s after the scene starts. Stagger in order of importance, not in DOM order, and finish the whole sequence within 0.5 s.
- Exits are 40–50% shorter than entrances. The next element starts when the one before it is 30–50% done; strictly one after another looks mechanical, and all at once looks cheap.
- One hero motion per shot. A secondary motion travels 50–70% of its distance and starts 100–200 ms later; everything else stays still.
- A line to read holds 0.5 s plus 0.3 s per word, and the video's last line holds at least 2 s. Text to read is at least 28 px at 1080 (2.6% of the short side). With a lot of text, cut words rather than shrinking the type. Text does not move while it is being read.

| Speed | Length | Feel |
| --- | --- | --- |
| Fast | 0.15–0.3 s | Power, urgency |
| Normal | 0.3–0.5 s | Most motion |
| Slow | 0.5–0.8 s | Weight, luxury |
| Very slow | 0.8–2 s | Cinematic, emotional |

## 7. Counting frames and beats

- One fps per video. In requests, give the seconds together with the frame count **at that video's fps**.
- 1 frame = 1000 ÷ fps ms: 33.3 ms at 30 fps, 16.7 ms at 60 fps. Frames = seconds × fps: 0.3 s is 9 frames at 30 fps and 18 at 60 fps.

| Motion | Length | 30 fps | 60 fps |
| --- | --- | --- | --- |
| Whip pan `[default]` | 0.25–0.37 s (down to 0.13 s in fast promotional video) | 8–11 frames (down to 4) | 15–22 frames (down to 8) |
| Snap zoom | About 0.13 s | 4 frames | 8 frames |
| Anticipation | 0.1–0.15 s | 3–5 frames | 6–9 frames |
| Stagger: words | 0.06–0.12 s | 2–4 frames | 4–7 frames |
| Stagger: list items | 0.04–0.08 s | 1–2 frames | 2–5 frames |
| Stagger: letters | 1 frame | 1 frame | 1–2 frames |

- Beats: one beat = 60 ÷ BPM seconds (0.5 s at 120 BPM, 0.6 s at 100 BPM), or fps × 60 ÷ BPM frames. Compute the frame of beat n straight from its number, `round(n × fps × 60 ÷ BPM)`. Adding up a rounded beat length drifts (by 2 frames after 32 beats at 128 BPM and 30 fps).
- Cut on beats, and change the layout on bars (4 beats). Check the beat positions by measuring them.
- Hold a key Korean sentence for its number of characters ÷ 10 seconds, plus 0.5 s, and split Korean captions so they never exceed 12 characters per second `[default]`. For other languages, use that language's caption guide.
