# Choosing tools

Tools and their terms change. Check the current version (`npm view <name> version`) and license when you start. The license notes below summarise published terms; they are not legal advice.

## 1. The common skeleton

**An AI coding tool writes each scene as HTML → a headless browser captures it frame by frame → FFmpeg joins the frames into an MP4.** In the records behind the first draft of this skill, six of seven motion graphics made for talks used this skeleton, and the differences between results came from the method and the review gates on top of it, not from the engine.

- The video stays as code files, so it is easy to fix, capture again and check.
- When on-screen copy must match the design documents to the letter, use a tool that controls the picture through code. Generative (diffusion) models give different results for the same request and struggle to place exact text.
- To see what one tool does, use only that tool. Do not mix several skills that do the same job.

## 2. Video engines

| Tool | What it does | License and cost | When |
| --- | --- | --- | --- |
| [HyperFrames](https://github.com/heygen-com/hyperframes) | Renders HTML scenes to MP4 with headless Chrome and FFmpeg; a CLI and agent skills | Apache-2.0, with no per-render fees for local renders. Needs Node.js 22 or later and FFmpeg | The first choice for talk and explainer videos |
| [GSAP](https://gsap.com) | Web animation: timelines, easing, morphing | The standard "no charge" license, which covers the formerly paid plugins. It excludes no-code visual animation builders that compete with Webflow | Motion inside a scene |
| [Playwright](https://playwright.dev) + [FFmpeg](https://ffmpeg.org) | Capture the page at each t with a browser, then join the frames | Playwright Apache-2.0; FFmpeg LGPL, or GPL depending on how it was built | Light work without an engine, with full control of determinism |
| [Remotion](https://www.remotion.dev) | React components to MP4 | Free for individuals, for-profit organisations with up to three employees, non-profits and evaluation; other companies need a company license. A license change was announced for version 5.0 | React teams, many videos generated from data |

- Pin the engine's version within one piece of work; engines such as HyperFrames release often.
- Generative models only for abstract background textures. Each set of model weights has its own license and use restrictions; read them for the version you use.

## 3. Screen (UI) parts

| Tool | What it does | When | License |
| --- | --- | --- | --- |
| [shadcn/ui](https://ui.shadcn.com) | Accessible React parts copied into the project and adapted there | Names and combinations of parts as a starting point ([ui-terms.md](ui-terms.md) section 6) | MIT |
| [Stageshow](https://github.com/benjitaylor/skills/tree/main/stageshow) | An agent skill with a small React kit for promotional "faux UI": product windows, phones and cursor walkthroughs with most text cut to grey bars, filmed frame by frame for review | Optional, for a looping product demo on a landing page, in a README or in a talk; never for stage 09 mockups or for building the product's own screens | MIT for its code; its app icons, and the product names and marks it shows, are not covered |

- The project's own component library and design contract come first. In a CORTHEX project, the tokens of stage 09.
- Stageshow is a skill, not a library. Install it only in the project that makes the demo, by running `npx skills add benjitaylor/skills --skill stageshow` there without `-g`. The `skills` CLI sends anonymous usage data unless `DISABLE_TELEMETRY=1` is set. The kit needs React 18 or later; filming its frames needs Node.js and a local Chrome.
- Its description asks to be used for any fake or mock UI, so where it is installed, say which skill you mean. A stage 09 mockup draws the real screen with its real copy, never faux UI.
- Stageshow's rules that hold for real screens are already in this skill: continuity in [motion-values.md](motion-values.md) section 5, alignment by eye in [ui-terms.md](ui-terms.md) section 2, icons and marks in its section 4, and the poster frame in [video.md](video.md) section 7.

## 4. Choosing by situation

| Situation | Choose | Why |
| --- | --- | --- |
| A talk video whose copy must match the design exactly | HyperFrames (or your own capture) + GSAP + a scene table + the two human gates | Deterministic renders are easy to fix, and the gates keep the quality |
| Out of ideas for scenes | The seven scenes in [video.md](video.md) section 4 and the names in [motion-terms.md](motion-terms.md) | Borrow proven scene grammar and change only the content |
| The video needs emotion and a story | Write the script first ([video.md](video.md) section 4) | A payoff works only when it is planned |
| Many Korean captions or large Korean text | `scripts/page-check.js` at the video's size | It checks Korean line breaks automatically |
| A photo-real image seems necessary | Generative images only for abstract textures | They hurt trust, are slow, and their weights' licenses need checking for each version |
| A React team, or many videos from data | Remotion | Components are reused; paid above a certain company size |
| UI transitions and small interactions | CSS, or the Web Animations API, with the values in [motion-values.md](motion-values.md) | Fixed values, reduced motion handled in one place |
| A looping product demo for a landing page, a README or a talk | Stageshow (optional, installed in that project), with this skill's checks | Promotional faux UI, built and reviewed frame by frame; it is not a mockup |

## 5. Pinning versions and reproducing a render

- Pin the engine and GSAP versions in `package.json`, and keep the render command, the seed and how the sound was made in the README. A fix made just before the talk then gives the same result.
- Do not mix versions within one piece of work.
- HyperFrames can render in a container (`render --docker --strict`), so different machines give the same result.
- Check first that installing and the network work where you build. Font CDNs, music sites and model stores can be blocked; keep fonts as files inside the project.

## 6. Licenses at a glance

| Group | Terms | What the result needs |
| --- | --- | --- |
| MIT tools (such as shadcn/ui and Stageshow's code) | MIT | Nothing when used only as tools. When their code goes into the product, keep the copyright notice with it |
| Apache-2.0 tools (such as HyperFrames, Playwright) | Apache-2.0 | When distributing changed code, include the license and mark the changes |
| GSAP | Standard no-charge license | No problem for videos and web pages |
| Remotion | Free below a company size | Check the team's size when you use it |
| Model weights | Differ by version (such as the OpenRAIL-M family) | Check the list of use restrictions |
| Fonts (such as Pretendard) | SIL Open Font License 1.1 | Fine to use in videos. When distributing the font files, include the license; never sell the files on their own |
| Icons | Each set's own license; for example, CC BY 4.0 requires credit | Give the credit the license asks for |
| Captures from design galleries | Belong to each site and the products shown | Take the structure only |
| FT Visual Vocabulary | © The Financial Times, all rights reserved | Use its category names only; never copy its pictures or text |
