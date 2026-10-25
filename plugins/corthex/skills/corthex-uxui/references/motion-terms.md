# Motion terms and instructions

Write a motion instruction as **[which scene, on what] + [motion name] + [time in seconds, and in frames at the video's fps] + [curve values and order]**. Give the sound (its BPM) and the safety limits once for the whole video. Feeling words such as "cool" or "natural" come out differently every time. The numbers for time, curves and springs are in [motion-values.md](motion-values.md).

- Sources file the same word under different headings (timing, staging, camera). Write the **name and its values**, not the heading.
- Pick two or three curves by role and reuse them. Keep bounce, elasticity and overshoot for the one place you want to stress.

## Turning feeling words into candidates [proposal]

| Feeling word | Candidate A | Candidate B |
| --- | --- | --- |
| Smooth | Decelerating `cubic-bezier(0.23, 1, 0.32, 1)` over 0.4 s, no bounce | A 0.4 s cross dissolve, with elements rising 12 px as they appear |
| Snappy, fast | A 0.3 s whip pan (9 frames at 30 fps), with horizontal blur only while it turns | A 4-frame snap zoom and a cut |
| Bouncy | Pop-in: from 0.9× through 105% to 100% in 0.35 s | A spring with duration 0.5 and bounce 0.3, at one point of emphasis only |
| Weighty | 0.6–0.8 s decelerating with no bounce; on landing an impact shake from 8 px to 0 in 0.25 s | 0.12 s of anticipation, then the main move, with 0.15 s of follow through |
| Cinematic | A slow 5 s push in (front layer to 110%, back layer to 103%) | A 0.8 s rack focus and a 0.3 s dip to black |
| Orderly | A 0.06 s stagger in order of importance; only two kinds of transition in the whole video | The same decelerating curve for every entrance; each scene builds, holds and closes |

## 1. Timing: speed and rhythm

| Name | What it is | Instruct like this |
| --- | --- | --- |
| Easing | The curve by which speed changes over time. A constant speed looks mechanical | "Entrance curve cubic-bezier(0.23, 1, 0.32, 1)" |
| Ease-out (decelerate) | Starts fast and slows to a stop. The default for entrances and UI responses | "The menu decelerates over 200 ms" |
| Ease-in (accelerate) | Starts slow and speeds up to the end. Only for exits that leave the screen | "In the last scene the cards accelerate off screen in 0.3 s" |
| Ease-in-out | Starts slow, speeds up, slows to a stop. For moving within the screen | "Moving to the next cell, ease-in-out over 0.5 s" |
| Linear | A constant speed. Only for things that keep going, such as progress bars and tickers | "Logo strip linear, one round every 20 s" |
| Overshoot | Goes slightly past the target and settles back | "The check grows to 110% and settles at 100%, 0.35 s" |
| Bounce | Hits a floor and bounces several times, lower each time | "Three bounces, each half as high" |
| Spring | Physical motion computed from damping and stiffness instead of a fixed time. It stays natural when interrupted | "The sheet dragged to close uses a spring, duration 0.5, bounce 0.2" |
| Speed ramp | Changes speed within one move | "Slow 0.4 s, fast 0.2 s, slow 0.4 s" |
| Slow motion, freeze frame | Stretch a moment / stop on one frame | "A 0.5 s freeze as the ball hits the net" |
| Hold, moving hold | Stop to give time to read; a moving hold still moves a tiny amount | "When the sentence is complete, a 1.5 s moving hold (growing 1% slowly)" |
| Beat sync | Cuts and accents on the music's beats; one beat = 60 ÷ BPM seconds | "120 BPM; a transition every 4 beats (2 s), on the first beat" |
| Seamless loop | The end joins the start, so the repeat has no seam | "A 6 s loop; the last frame matches the first" |
| Stagger | The same motion on several things, one after another at a fixed interval | "Four cards 0.06 s apart, in order of importance, not position" |

## 2. Principles: making it feel alive

These come from Disney's principles of animation. Unless the video explains the principles, four are enough: easing, anticipation, follow through and overlap `[default]`.

| Name | What it is | Instruct like this |
| --- | --- | --- |
| Anticipation | A small move the other way just before a big one; it leads the eye to what comes next | "A slight 0.12 s dip down before it jumps" |
| Squash and stretch | Squashes on impact and stretches with speed, keeping its volume | "On impact, 115% wide and 87% tall" |
| Arcs | Moving along a curve rather than a straight line | "A path that bends slightly upwards instead of a straight line" |
| Follow through | After the body stops, the parts attached to it travel a little further | "Only the speech bubble's tail stops 0.15 s later" |
| Overlapping action | Parts start and stop slightly apart; the next move starts early | "Icon, title and text, each 0.05 s later" |
| Secondary action | A smaller, shorter motion caused by the main one | "A little smoke below the rocket as it lifts off" |
| Exaggeration | Makes the key point a little bigger than life so it reads | "1.2× only at the moment the score rises" |
| Mass and weight | Heavy things start slowly and stop late; light things bounce | "The big box 0.6 s with no bounce; the small ball 0.3 s with two bounces" |
| Smear frame | One or two very fast frames with the shape itself stretched | "Only the one frame of the whoosh, stretched sideways" |

- Squash: 0% on text that must stay exact, such as names, numbers and prices; up to 3% on decorative text `[default]`.

## 3. Emphasis and entrances

| Name | What it is | Instruct like this |
| --- | --- | --- |
| Mask reveal | Revealed inside a clipping box (`clip-path`) | "Each heading line in its own mask, rising from below, 0.6 s per line, each line 0.1 s after the last" |
| Kinetic typography | The letters themselves move to carry meaning and rhythm | "Only the key words pop to 1.2× on the beat" |
| Type-on | Characters appear one at a time, as if typed | "0.04 s apart; the cursor blinks twice at the end" |
| Text reveal (stagger) | Words or lines appear one after another | "Three lines 0.12 s apart, rising 12 px" |
| Count-up | A number counts up to its value; its digits need a fixed width | "1.5 s decelerating, thousands separators, tabular-nums, the source small below" |
| Pop-in | Starts small, goes slightly past its size and settles | "0.9× and transparent → 105% → 100%" |
| Motion blur | The blurred trail of fast motion; film uses a 180° shutter angle | "Horizontal blur only during the fast part, none on still frames" |
| Motion trail | Several sharp copies follow behind | "Three copies, fainter towards the back" |
| Snap zoom, crash zoom | A zoom that lunges in over a few frames | "Snap zoom to the chosen card, 4 frames at 30 fps" |
| Punch in | Larger in one cut, with no zoom in between | "On the shutter sound's frame, straight to name-tag size" |
| Impact shake | The screen shakes briefly and settles as something heavy lands | "0.25 s, from 8 px to 0" |
| Line draw | A line is drawn from its start | "The graph line draws from the left over 1.2 s, its value at the end point" |
| Light sweep | A highlight slides across a surface | "One slanted light across the logo in 0.8 s" |
| Burst, particles | Pieces spread out from one point | "20 pieces at the moment of completion, once, gone within 1 s" |

- One well-built first entrance beats many small effects scattered around.
- For Korean kinetic type, also set keep-all, or break the lines by hand at units of meaning.
- Strobes, impact flashes and glitches must not flash more than three times in any one second ([checklist.md](checklist.md)).

## 4. Camera

Screen code has no real camera, so moving layers imitates one. One question tells the moves apart: **did the camera's body move?** When the body moves, near layers move more than far ones (parallax).

| Name | What it is | Instruct like this |
| --- | --- | --- |
| Pan | Turns left or right on the spot; every layer shifts by the same amount | "Pan across the three price cards, left to right, 2 s, ease-in-out" |
| Tilt | Turns up or down on the spot | "Tilt down a long receipt from top to bottom, 3 s" |
| Roll | Turns around the viewing axis, so the horizon tilts | "5° in the confused scene, 0° in the solved one" |
| Track, truck | The camera's body moves sideways | "Front, middle and back layers move sideways at 1×, 0.5× and 0.2×" |
| Pedestal | The camera's body moves straight up or down | "From below to above, until the sign on the roof shows" |
| Dolly, push in | The camera's body moves forwards or back; the front layer grows more | "Slowly towards the logo over 5 s, front layer to 110%, back layer to 103%" |
| Zoom | Only the field of view narrows; everything grows evenly | "1.0× → 1.2×, 2 s" |
| Orbit | Circles around the subject in the centre | "90° around the 3D model, 3 s" |
| Parallax | Layers move at different speeds to make depth | "Three background layers at 1, 0.5 and 0.2 times the movement" |
| 2.5D camera | Flat pictures stood at different depths and moved at different speeds | "Three captures floated front to back, turning slowly through 12°" |
| Perspective tilt | A plane laid back so its top recedes | "The app screen tilted back 20°, as if lying on a desk" |
| Rack focus | The sharp plane moves from a near subject to a far one, taking the eye along | "From the question bubble to the answer card, 0.8 s" |
| Dolly zoom | The field of view changes against the movement: the subject keeps its size and only the space behind changes | "The person stays the same size while the background recedes over 2 s" |
| Ken Burns effect | A still photo slowly zoomed and moved | "100% → 108% over 8 s, drifting towards the top right" |

- Strong effects, such as a dolly zoom, a roll or a speed ramp, once or twice per video, about 2 s each. Parallax, large zooms and rotation can cause motion sickness.

## 5. Transitions

| Name | What it is | Instruct like this |
| --- | --- | --- |
| Cut | Straight to the next scene with nothing in between: "it changes" | "Problem → solution as a hard cut" |
| Cross dissolve | One scene fades into the next: "it continues" | "0.4 s between steps, not on every transition" |
| Dip to black, dip to white | A brief fade to black (or white) and back; marks a chapter | "0.3 s of black at the end of part 1" |
| Wipe | A straight edge sweeps across and reveals the next scene | "A brand-coloured panel sweeps from left to right" |
| Push, slide | The new scene pushes the old one out, covers it, or the old one moves aside | "The next screen pushes in from the right, 0.5 s" |
| Match cut | A cut between similar shapes in the same place and size | "Round clock → round plate, same place, same size" |
| Zoom-through | Dives into one point on the screen, and what is inside becomes the next scene | "Into the laptop screen, 0.6 s" |
| Whip pan | A very fast pan; the next scene arrives inside the blur | "Whip pan right, 0.3 s, blur only while it turns" |
| Iris | A circular frame closes or opens on the scene | "Closes to a point in the centre in 0.5 s and opens from the same point" |
| Grid dissolve | The next scene arrives cell by cell | "8×8 cells in random order, 0.8 s" |
| Shape morph | One shape turns into another | "A square button becomes a check mark over 0.5 s" |
| Glitch, RGB split | A moment of digital breakage | "0.2 s, once, without flashing" |
| Split screen | The screen divided to show things side by side | "Before and after, left and right, on the same scale" |

- A transition carries meaning. Give each one a cause on screen (a moving object, a glance, a similar shape). For a video of about a minute, start with two or three kinds and reuse them `[default]`. Do not make every transition a cross dissolve.

## 6. Pairs people mix up

| Pair | What tells them apart |
| --- | --- |
| Pan, track | A pan turns on the spot, so every layer shifts together. A track moves the body sideways, so near layers move more |
| Tilt, pedestal | The same pair, vertically |
| Zoom, dolly | A zoom enlarges everything by the same ratio. A dolly enlarges the front more, and the background changes too |
| Snap zoom, punch in | Pulls in over a few frames / a cut with nothing in between |
| Push in, zoom-through | A camera slowly approaching / a transition diving into one point |
| Whip pan, motion blur | A transition that changes the scene / the blurred tail of a fast object |
| Motion blur, motion trail, smear | A blurred trail / sharp copies / the shape itself stretched for a frame or two |
| Match cut, zoom-through | Similar shapes joined in the same place / pulled into one point |
| Mask reveal, iris, wipe | One element's entrance / the whole scene through a circle / the whole scene behind a straight edge |
| Stagger, overlap | Several things one after another / one thing's parts or moves overlapping |
| Follow through, overlap, secondary action | What continues after the stop / parts out of step at the start and on the way / a different small motion the main one causes |
| Overshoot, anticipation | Goes past at the end / moves the other way before it starts |
| Overshoot, bounce, pop-in, spring | Goes past once / settles in several bounces / a whole entrance ending in an overshoot / computed from damping and stiffness, which may bounce several times |
| Hold, moving hold, freeze | Values stop / tiny movement while seeming to stop / the whole scene stops like a photo |
| Slow motion, speed ramp | Slows everything evenly / slow and fast within one move |
| Parallax, 2.5D | The same principle: mostly flat movement / depth placement and rotation as well |

## 7. Turning the names into HTML and GSAP

| Name | In code |
| --- | --- |
| Pan, tilt | `translateX` or `translateY` by the same amount on every layer |
| Track, pedestal, parallax | Each layer's movement times its own multiplier, such as 1, 0.5 and 0.2 |
| Zoom, dolly | A zoom scales every layer by the same ratio; a dolly scales nearer layers more |
| Roll | `rotate` the whole frame a few degrees |
| Orbit, 2.5D, perspective tilt | `perspective` on the parent, depth per layer with `translateZ`, then `rotateX` or `rotateY` on the parent |
| Dolly zoom | The subject in the centre keeps its size; only the back layers grow or shrink |
| Whip pan | A very fast pan, with horizontal blur during that stretch only |
| Snap zoom, punch in | `scale` over about 4 frames / all at once with `tl.set` at the cut |
| Speed ramp | A custom curve, or a tween of the timeline's `timeScale` |
| Rack focus | Over the same stretch, the front layer's `blur` 0 → 6 px and the back layer's 6 px → 0 |
| Anticipation | One 0.1–0.15 s tween the other way, just before the main move |
| Stagger | GSAP's `stagger` option |
| Motion blur | Blur along the axis of movement only (SVG `feGaussianBlur stdDeviation="8 0"`), or several samples blended per frame |
| Easing, overshoot | GSAP names (`power2.out`, `back.out(1.7)`) or `CustomEase` with an SVG path |
