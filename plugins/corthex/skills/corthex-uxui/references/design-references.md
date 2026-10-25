# Choosing references

References decide **how** to make something. **What** to make, the features, screens and copy, comes from the request and the project's documents: requirements, user flows and screen definitions.

## 1. Rules

- Never add a feature, a screen or copy that the documents do not have because a reference has it.
- Take the structure only: layout, order, proportions, and the timing and curves of motion. Captures, copy, logos, numbers and photos never go into the result.
- Settle the likeness first (section 3).
- When comparing what one tool does, do not mix in references. Bring references in to refine a direction already chosen, and to give feedback on a screen with shared names.
- Put the references you used in the report, on one line. Without that record nobody can tell later what helped.
- Some sites do not open from every working environment. A person can pick three to five per screen on their own computer and collect the links and captures on one page, so "something like this" can be matched by picture.
- To settle structure before colour takes over, draw grayscale wireframes without colours or fonts first and agree on them. In a CORTHEX project these are stage 08's wireframes.

## 2. Galleries

Collections of real product screens. The captures belong to each site and to the products shown. Some have paid sections.

| Site | What it collects | Open it for | Instruct like this |
| --- | --- | --- | --- |
| [navbar.gallery](https://navbar.gallery) | Navigation bars: sticky, dropdown, mega menu, sidebar, search | The frame of the whole screen; menu on top or at the side | "Take only the layout of these two captures, a sticky top bar and a side menu, for two candidates with five menu items. Colours, fonts and logo are ours" |
| [unsection.com](https://unsection.com) | Page sections: hero, testimonials, features, CTA, pricing, FAQ | The order of sections on a landing page, an about page or a deck | "Grayscale skeleton first, in this order: first screen, problem, features, how it works, FAQ, start button" |
| [bentogrids.com](https://bentogrids.com) | Layouts of cells of different sizes | Summing up several features; the last scene of a video | "Six features as a bento grid, only the main one in a 2×2 cell, and one line on why bento" (a layout AI often picks, so give the reason) |
| [60fps.design](https://60fps.design) | Short recordings of app and web motion: loading, done, empty, chat | Finding a motion by name before setting its time and curve | "The done check draws itself within 0.4 s, curve cubic-bezier(0.23, 1, 0.32, 1)" |
| [cta.gallery](https://cta.gallery) | Buttons, forms and pop-ups that lead to an action | The main button, the screen that explains a permission before asking, empty-state prompts | "Before the notification permission prompt, a panel that explains why. One button, 'Turn on notifications'; 'Later' as a text button" |
| [404s.design](https://404s.design) | 404 pages | The tone and pictures of error, empty and failure screens | "Instead of a big number, one line of help and one home button, like the minimal ones" (services that depend on trust avoid the playful ones) |
| [jiro.build](https://jiro.build) | Design prompts for AI site builders: landing pages and sections | How a section prompt is put together | "Write our pricing section's prompt anew in the order name, purpose, elements, states" (take the structure, never the sentences) |
| [footer.design](https://footer.design) | Website footers | The last area of a page; the notices, sources and team on a deck's last slide | "Last slide: three small lines with the data sources, the notices and the team" |

## 3. Likeness dial

When you get a reference, ask first. Without an answer, 50% `[default]`. "Not too different" starts at 70%.

| Likeness | Keep | Change | Instruct like this |
| --- | --- | --- | --- |
| 30% · distant inspiration | Principles only: mood, density, contrast | Everything else | "Take only the calm density of this screen (30% likeness). New colours, layout and fonts" |
| 50% · visible influence | The medium and the grain of the emotion | Colours, composition, subject, type system | "Keep the warm feel (50% likeness), with our own colours, composition and fonts" |
| 70% · neighbouring brand | The logic of the composition, texture, colour relations, how much people appear, the size of the name | Subject, action, layout, letterforms | "Composition logic and colour relations like this reference (70%), with a different subject, layout and letterforms" |
| 85% · close neighbour | Most of the visual grammar | Four or more signature elements. A real company's identity is never rebuilt | "Nearly the same visual grammar (85%), change four or more signature elements, and use none of its logo, copy or photos" |

- The number conveys intent; it is not a score anyone measures.
- When overlap worries someone, list what was taken over as is (copy, numbers, images, composition, motion) with evidence from both sides, and tell it apart from visual grammar everyone uses. Looking alike is not proof of copying.

## 4. Getting away from the same answer

When neither the documents nor the request set colours and fonts, screens made in different ways come out in the same colours and the same fonts. Instead of growing a list of things to avoid, use devices that move away from the first answer that comes to mind. They make the same answer less likely; they do not prevent it.

1. **One scene sentence**: who looks at this screen, where, under what light, to do what. That sentence decides between a light and a dark screen, not a default.
2. **Materials**: 8–12 real objects, places, documents and printed things from the product's world. When four or more share one material (all paper, all screens), look further until there are at least three families.
3. **Five paths**: one candidate each from the material world, the emotion, the audience, the common answer turned around and an unfamiliar format, then narrow them to the two you show, or more only when the person asks. At least one of the two should be one that would not come to mind first. Candidates with the same layout of large elements count as one.
4. **Colour strategy first**: pick one and start from it.
   - Restrained: neutrals and one accent
   - Committed: one colour over 30–60% of the screen
   - Full: three or four colours by role
   - Drenched: the screen is that colour
   - Spend colour on states, data and selection rather than scattered decoration.
5. **The field-guess test**: when a colour or font is what anyone would guess from the field's name alone, or from "the field, but avoid colour X", choose again or write why this product needs it.

## 5. Ask with values

Naming only what to avoid moves the result to the next most common answer. Name what you want, as values.

- ✗ "Avoid greens"
- ✓ "Background #F6F1E7, text #1E2A2F, one accent #B4532A, used only on the primary button and the selected state"
- Fonts as values too: "Headings [font] 700, 40 px, letter-spacing −0.02em; body [font] 400, 16 px, line-height 1.6"

## 6. Choosing a diagram for a slide

Write each slide's one-sentence message first, then pick the one diagram that shows it best.

| What you want to say | Diagram | How to choose between them |
| --- | --- | --- |
| Steps follow one another | Process chevrons, flowchart, swimlanes, cycle (such as PDCA) | 3–5 steps without branches / branches on conditions / who does each step matters / the end leads back to the start |
| What happens when | Roadmap timeline, Gantt chart | Major milestones / overlapping work periods |
| What a user goes through | Customer journey map | Actions, thoughts and feelings at each step |
| What belongs to what | Hierarchy, issue tree, pyramid | Organisation or menu / a problem broken into causes / the base carries the top, or there is less towards the top |
| Layers that work together | Layered architecture, house (roof, pillars, foundation) | Technical layers / goal, strategies and foundations |
| One centre joins many | Hub and spoke | One centre, many connections |
| Value added step by step | Value chain | The order of activities and what each adds |
| Comparing two or more | Comparison table, Harvey balls, radar chart, before and after | Many criteria / degree in each cell / the shape over 5–8 axes / before and after a change |
| What to choose | Decision tree, trade-off, 2×2 matrix | Follow conditions down / what two options trade / four cells from two criteria (name both axes) |
| Something overlaps | Venn diagram | Only when things really overlap |
| Size, change, share | Bar, line, donut, waterfall, funnel, one big number | Comparing sizes / change over time / share of a whole (few slices) / adding and subtracting to a result / shrinking step by step / one number is the point |
| The situation, the business | SWOT, business model canvas | Strengths and weaknesses, inside and out / the business in nine boxes |

- Use a chart only with real data, and give its source. Without data, write "no data".
- Instruct like this: "This slide's message is 'only the second of three steps has a person check it'. Three process chevrons, with the accent colour and a 'person checks' mark on the second only."
- Chart types and slide rules are in [video.md](video.md) section 10.

## 7. What to open first, by task

| Task | Order |
| --- | --- |
| Web app screens | Whole frame: navbar.gallery → empty and error states: 404s.design, cta.gallery → motion: 60fps.design → names: [ui-terms.md](ui-terms.md) → motion values: [motion-values.md](motion-values.md) → checks: [checklist.md](checklist.md) |
| Motion graphic for a talk | Story and scene table: [video.md](video.md) → names of scenes and motions: [motion-terms.md](motion-terms.md) → same t, same frame → gates → last scene: bentogrids.com |
| About page or deck | Section order: unsection.com, jiro.build (structure only) → diagrams (section 6) → last slide: footer.design |
| Comparing what one tool does | That tool only. Do not look at results made another way either |
