# Screen terms and instructions

Write a screen instruction in four slots: **[which screen, where] + [part name] + [content] + [numbers and states]**. A part's name picks the right part, and a fix changes one thing at a time: "card gap 12 px → 20 px" gets fixed in one go, "more space" does not. The numbers in the examples are starting points; the project's design contract wins.

## Turning feeling words into candidates [proposal]

When the request uses a feeling word, show two candidates made of names and numbers, and let the person pick.

| Feeling word | Candidate A | Candidate B |
| --- | --- | --- |
| Clean | Spacing only in multiples of 8, one accent colour, two weights (400 and 700) | No dividers, groups made by spacing alone; cards without borders, one step of background colour |
| Premium | 128 px above and below each section, large headings at −0.02em, neutrals and one accent | Motion decelerating over 0.5–0.8 s, one large photo, half the words |
| Make it stand out | Only the primary button filled with the accent colour, everything else secondary | The key number as large as the screen allows, its unit small |
| Dense but easy to read | A 12-column grid; table numbers right-aligned with `tabular-nums`; sticky header row | Grouped in cards, each with one title line, one number and at most two lines of text |
| Friendly | Corners rounded 12–16 px, plain conversational copy, an empty state with a short line and one button | One illustration and a warm background colour given as a value, such as #F6F1E7 |
| Easy on a phone | The key action as a sticky bottom button, 52 px tall, raised clear of the home indicator | Targets 48 px or more, at most three inputs per screen |

## 1. Page frame, layout and position

| Name | What it is | Instruct like this |
| --- | --- | --- |
| Header | The band across the top with the brand and the main ways to move around | "Header: logo on the left; 'Sign in' and 'Start free' on the right" |
| Navigation | The links that lead elsewhere in the site | "Three navigation items, Features, Pricing and Contact; the current page in bold" |
| Sticky header | A header that stays at the top while the page scrolls | "Sticky header, 64 px tall, 56 px once the page scrolls" |
| Hero section | The introduction that fills the first screen | "Hero: one H1 line, at most two lines of description, one primary button" |
| Section | A part of the page that tells one thing | "Four sections: problem, solution, how it works, FAQ" |
| CTA (call to action) | The button or line that asks for the next step you want | "One CTA, 'Try it free for 14 days', at most twice on the page" |
| Footer | The end of the page: company details, policies, contact | "Company details and links to the terms and the privacy policy, on two lines" |
| Anchor link | A link that jumps to a point on the same page | "'Pricing' jumps to the pricing section, its heading not hidden under the sticky header" |
| Sidebar | A vertical menu or table of contents that stays at the side | "Left sidebar, 240 px on desktop; below 768 px a hamburger menu" |
| Breadcrumb | A line that shows where you are: Home › Category › This page | "Above the product detail: 'Home › Laptops › [product name]'" |
| Hamburger menu | The three-line icon; the panel it opens is a drawer | "At 390 px the menu becomes a hamburger that opens a drawer from the right" |
| Grid | Rows and columns laid out first, with things placed on them | "Nine cards: three columns at 1280 px, two at 768 px, one at 390 px" |
| Column | A vertical division of the screen | "Body in two columns, 8 and 4 of 12" |
| Flexbox | Items in one line, with their gaps and alignment | "Two buttons side by side, 12 px apart, aligned right" |
| `flex-wrap` | Sends items that do not fit to the next line | "Tag chips wrap to the next line, 8 px apart" |
| Split layout | One area split in two, text beside a picture | "Text 55% on the left, the product screen 45% on the right; at 390 px the text goes on top" |
| Gallery | Many images in a grid to browse | "Eight case photos as a gallery; a click opens one large" |
| Card | A box that holds one thing's picture, text and actions | "Three plan cards of equal height; only the recommended one gets a stronger border" |
| `aspect-ratio` | Fixes a box's ratio of width to height | "Thumbnails fixed at 16:9, cropped with `object-fit: cover`" |
| Bento grid | Cells of different sizes fitted together like a lunch box. AI picks it by default, so give the reason when you choose it | "Six features as a bento grid, only the main one in a 2×2 cell" |
| Breakpoint | A screen width where the layout changes | "Only two breakpoints, 768 px and 1280 px" |
| `position: absolute` | Placed by coordinates from a corner of its containing box; out of the flow | "Close (X) 16 px in from the modal's top right corner" |
| `position: fixed` | Stuck to the screen; does not move when the page scrolls | "Chat button fixed at the bottom right, raised by the home indicator's height" |
| `position: sticky` | Sticks once it reaches a set point, only inside its parent | "Table header row sticky" |
| `z-index` | The layer number that decides what is in front | "Layers: content 0, fixed buttons 10, scrim 20, modal 30, toast 40" |
| Overlay, scrim | A translucent layer that covers or darkens what is underneath | "Black 50% scrim behind the modal; a tap on it closes the modal" |
| Badge | A small mark on a corner that shows a state or a count | "Count badge at the notification icon's top right; above 99, '99+'" |
| Back to top | A button that returns to the start of a long page at once | "Appears at the bottom right after two screens of scrolling" |
| Safe area | The area clear of the notch and the home indicator | "Below the sticky bottom button, a gap of `env(safe-area-inset-bottom)`" |

- With a sticky header and anchor links, give `scroll-padding-top` the header's height. A focused control must not be entirely hidden by a sticky header or a sticky bottom button (WCAG 2.4.11).
- A layout instruction is complete only with the widths it applies to.

## 2. Spacing and size

| Name | What it is | Instruct like this |
| --- | --- | --- |
| Padding | Space inside a box | "Card padding 20 px on every side" |
| Margin | Space outside a box; the distance it keeps from its neighbours | "96 px above and below each section, 56 px at 390 px" |
| Gap | One space given between all the items in a row or grid | "Card gap 16 px → 24 px" |
| Container | The outer frame with a maximum width | "Content at most 1120 px wide, 24 px at the sides, centred" |
| Width, height | The horizontal and vertical size | "Bottom button width 100%, height 52 px" |
| Divider | A thin line that shows where a group ends | "1 px light grey line between list items, none under the last" |
| Spacing scale | The agreement to pick spacing only from multiples of 4 or 8 | "Spacing only 8, 12, 16, 24 and 32" |

**Target size**: WCAG 2.5.8 (AA) sets 24×24 CSS px as the floor, with exceptions such as enough spacing around the target or a link inside a sentence; 2.5.5 (AAA) asks for 44×44. Apple asks for 44×44 pt, and Material for 48×48 dp (about 9 mm) with 8 dp between targets. Aim for the platform's convention.

**Alignment by eye**: the eye judges letters and edges, not boxes.

- A line box leaves room below the letters, so capitals beside an icon, in a pill or in a button look low. Centre the capital height instead: `text-box: trim-both cap alphabetic`, where the browser supports it.
- Nested rounded shapes, such as an icon in a button or a pill in a field, sit at an even distance from every edge, with outer radius = inner radius + that distance.
- Two edges that almost meet, 1–3 px apart, look accidental: make them meet exactly, or separate them by the layout's gap and by no less than 8 px.
- When an amount is centred, centre its digits and let the currency sign sit outside that box.

## 3. Type

| Name | What it is | Instruct like this |
| --- | --- | --- |
| `font-weight` | The thickness of the strokes, 100–900 | "Headings 700, body 400, buttons 600. No weight the font does not have" |
| `line-height` | The distance between lines, as a multiple of the font size | "Body 1.6, headings 1.3" |
| `letter-spacing` | Tightens or opens the space between letters | "Large headings only at −0.02em, body 0" |
| Heading hierarchy | Steps of size and weight that show importance and grouping | "One H1 per page, H2 for sections; 40, 28 and 16 px" |
| `text-align` | Which side the lines align to | "Long paragraphs left-aligned; centred only for headings of two lines or fewer" |
| `text-overflow`, `line-clamp` | Hides what overflows and shows "…" | "Descriptions clamped at two lines; product names and prices never cut" |
| `word-break: keep-all` | Breaks Korean lines only at spaces, so no word is split | "keep-all on Korean headings and body text; if it overflows, fix the box" |
| `text-wrap: balance`, `pretty` | `balance` evens out the lines of a heading; `pretty` avoids a lone word on the last line | "Headings balance, body pretty" |
| `tabular-nums` | Gives every digit the same width, so columns line up and numbers do not jitter | "Price tables and count-up numbers in tabular-nums" |
| Chunks that stay together (`nowrap`, `&nbsp;`, `<wbr>`) | Keep a short chunk on one line, or mark where a long word may break | "'$9.90/month' nowrap; a `<wbr>` where a long compound may break" |
| Font family | The design of the letters | "Body [chosen font] 400 and 600; fallback `system-ui, 'Apple SD Gothic Neo', 'Malgun Gothic', sans-serif`" |

### Korean text

- Korean blocks: `word-break: keep-all` with `overflow-wrap: break-word`. Headings `text-wrap: balance`, body `text-wrap: pretty`, code and URLs `overflow-wrap: anywhere`.
- When a narrow box (a table cell, a badge, a button, a tag) overflows, keep `keep-all`: widen the box, clamp the text, or shorten the copy. Give `nowrap` only to short chunks that must not break.
- Do not: put `word-break: break-all` on Korean, put `nowrap` on large areas, put `keep-all` on text mixed with Chinese or Japanese, or call it done after looking at one width.
- Not every browser supports `text-wrap: pretty` yet. A browser that does not know it ignores the line, so leave it in.
- Body line spacing 1.5 or more (WCAG 1.4.8; the W3C's Korean layout requirements give 160% as an example). Do not fix the height of text boxes, so text does not get cut off when a user increases the spacing (1.4.12).
- Keep numbers with their units, and use one format for dates, times and money across the product. Right-align numbers in tables.
- On fixed-width surfaces, such as video and slides, you may break lines by hand at units of meaning.
- Measure at several widths after the real fonts have loaded (`document.fonts.ready`). If you did not measure, write "not measured".

**Contrast**: text 4.5:1; large text (18 pt ≈ 24 px, or 14 pt ≈ 18.7 px bold) 3:1 (WCAG 1.4.3). The unit is the point: reading it as "18 px, or 14 px bold" loosens the rule. The borders and states of controls, and graphics needed to understand the content, need 3:1 against their neighbours (1.4.11). Disabled controls, decoration and text in logos are exempt. Measure translucent backgrounds by the colour that actually results, and text on photos at the worst spot.

**Time to read**: Netflix's Korean timed-text style guide allows up to 12 characters per second for adult programmes and 9 for children's; for other languages, use that language's guide. Hold a key Korean sentence on screen for its number of characters ÷ 10 seconds, plus 0.5 s [proposal].

## 4. Parts and states

### Buttons and choices

| Name | What it is | Instruct like this |
| --- | --- | --- |
| Primary, secondary button | The most wanted action is filled; the next one is outlined | "'Pay' primary, 'Add to cart' secondary. One primary per screen" |
| Ghost, text button | The lightest button: text with no background or border | "'Cancel' as a ghost button, left of the primary" |
| Icon button | A button with only a picture; it needs an `aria-label` | "X icon button, aria-label 'Close', 44 px target" |
| Destructive button | Does something that cannot be undone; paired with a confirmation | "'Delete account' as a red button that asks for confirmation first" |
| Sticky CTA | The key action's button, stuck to the bottom while the page scrolls | "At 390 px, 'Apply' sticky at the bottom, 52 px tall" |
| FAB (floating action button) | A round button floating over the screen for the one most frequent action | "'+ New post' at the bottom right of the list" |
| `border-radius` | How much the corners are rounded | "Buttons 8 px, cards 12 px, chips 9999 px (a pill)" |
| Link | Going somewhere is a link; doing something is a button | "'View terms' is a link; 'Agree and continue' is a button" |
| Segmented control | A few joined buttons, one of which picks the view | "'Day · Week · Month' above the chart, 'Week' by default" |
| Tabs | Swap the content shown in the same place | "Three tabs, 'Profile · Notifications · Billing'; the selected one underlined" |
| Chip, tag | A small pill-shaped label for filters or categories | "Filter chips 'All · In progress · Done', several selectable" |
| Switch | Turns something on or off at once | "'Email notifications' switch, applied at once with no save button" |

**Eight states to decide together** for each control: default; hover (none on touch devices); pressed (`:active`, such as `scale(0.97)` over 160 ms); focus (`:focus-visible`, a 2 px outline at 3:1 against the background); disabled (with the reason in words); loading (no second submit); selected; and error (a red border and the cause). Before disabling a control, consider letting it be pressed and saying what is missing [proposal]. These are the states of a control; the states of a whole screen (normal, loading, empty, error, permission, stale) come from its screen definition, stage 08 in CORTHEX.

### Forms

| Name | What it is | Instruct like this |
| --- | --- | --- |
| Input | A one-line text field | "Phone number field with `inputmode="numeric"`" |
| Textarea | A large field for long text | "Message field five lines tall, with a 0/500 counter" |
| Label | The name that says what a field takes | "Labels always visible above the field, never replaced by grey text inside it" |
| Placeholder | Faint example text in an empty field; never a replacement for the label | "Format examples only: 'e.g. 2026-01-31'" |
| Helper text | One line under the field with a condition or a tip | "'At least 8 characters, including a number'" |
| Select | Opens a list to pick one value | "Country select, defaulting to the account's country" |
| Checkbox, radio | Pick several independently / only one of a group | "Notifications as a checkbox; billing cycle as radios" |
| Consent checkbox | Consent items split into required and optional, each with 'View details' | "Required consent and marketing consent kept apart" |
| Inline error | Under the wrong field: what is wrong and how to fix it | "Checked when the field loses focus; one line that says how to fix it" |
| Submit | The last button, which sends the input | "On success a toast, 'Received'; on failure an error summary above the form" |
| Search, combobox | A field with a magnifier / a list of candidates while typing | "Filter 300 ms after typing stops; arrow keys pick a candidate" |
| Date picker | A field that opens a calendar | "Past dates cannot be picked" |
| Stepper | Shows where you are among several steps | "Three steps, 'Shipping · Payment · Confirm'" |
| OTP input | One digit per cell | "Six cells; typing moves to the next; pasting works" |
| Dropzone | Pick a file, or drag one in | "PDF only, up to 10 MB, with progress while uploading" |

- Fields need labels or instructions (WCAG 3.3.2). Errors are described in text (3.3.1) and come with a suggested fix (3.3.3). Do not block pasting or password managers (3.3.8).

### Overlays, loading and navigation

| Name | What it is | Instruct like this |
| --- | --- | --- |
| Modal, dialog | A window on top; what is behind cannot be used until it closes | "Closes with Esc; focus stays inside; on close, focus returns to the button that opened it" |
| Alert dialog | Asks once more before an action that cannot be undone | "Default focus on 'Cancel'" |
| Bottom sheet | A panel that rises from the bottom | "Share as a bottom sheet, closed by dragging its handle down" |
| Drawer | A panel that slides in from a side | "280 px from the left, with a scrim behind" |
| Dropdown menu | A list of actions or destinations that opens on a click | "Each row's '⋯' holds Edit, Duplicate and Delete" |
| Popover | A small panel opened by a click | "Filter button → a list of checkboxes and 'Apply'" |
| Tooltip | A short explanation that appears on hover or focus | "Also appears on keyboard focus; Esc closes it" |
| Toast, snackbar | A notice that appears in a corner for a moment and goes | "'Saved', 4 s, with 'Undo'. Errors go in an alert, not a toast" |
| Alert, banner | A notice that stays in place | "A failed payment as a red alert above the form" |
| Skeleton | Grey shapes of the content, drawn before it arrives | "Three card-shaped skeletons" |
| Spinner, progress bar | The end is unknown / how much is done is known | "A spinner only when it takes over 1 s" |
| Empty state | What shows when there is nothing to show; complete only with a button for the next step | "'No results', a suggestion to change the search, and 'Clear filters'" |
| Accordion | Headings that open and close their content | "FAQ, several open at once" |
| Pagination, load more | Numbered pages / a button that appends more | "The product list uses 'Load more', so the footer stays reachable" |
| Carousel | A list you move through sideways | "No autoplay; arrows and dots" |
| Bottom navigation | The fixed main menu at the bottom of a phone screen | "Four items, icon and text together" |
| Table | Data in rows and columns | "Sticky header row; number columns aligned right" |
| Stat card | A dashboard unit with one number and its change | "'+12% from last week' under the big number" |

- Content that appears on hover or focus can be dismissed, and stays while the pointer moves onto it (WCAG 1.4.13).
- Anything that moves on its own for more than 5 s, such as an auto-advancing carousel or a scrolling ticker, needs a way to pause it (2.2.2).

### Icons and marks

- One icon family per product, with one stroke weight and one size per screen. Compare the strokes, not the boxes: at the same size, a filled icon looks heavier than an outlined one.
- An AI feature shows what it does: the question, the answer and its sources. A sparkle, a wand or a star, or purple as "the AI colour", says nothing about it. If the product's own icon happens to be a sparkle, it stays.
- Emoji belong in messages and reactions, not in place of icons.
- Do not invent a logo, such as an initial on a coloured tile, for a name that has none.

## 5. Pairs people mix up

| If it | It is a | If it | It is a |
| --- | --- | --- | --- |
| Always stays at the side | Sidebar | Slides in from the side on a click | Drawer |
| Rises from the bottom | Bottom sheet | Slides in from a side | Drawer |
| Lists actions or destinations | Dropdown menu | Picks a value in a form | Select |
| Appears in the middle and blocks what is behind | Modal | Appears in a corner for a moment | Toast |
| Appears on hover | Tooltip | Opens on a click | Popover |
| Goes away by itself | Toast | Stays in place | Alert, banner |
| Has no known end | Spinner | Knows its progress / draws the content's shape first | Progress bar / skeleton |
| Is a number or dot on an icon's corner | Badge | Is a pill label standing alone | Chip |
| Swaps content in one place | Tabs | Opens several sections at once | Accordion |
| Goes somewhere else | Link | Does something | Button |
| Is the dark layer itself | Overlay | Is the window on top of it | Modal |

## 6. Parts by screen (a starting point, in shadcn/ui names)

| Screen | Parts |
| --- | --- |
| Settings | Tabs for the areas, a Card per area, Field for inputs, Switch for on and off |
| Dashboard | Sidebar on the left, Card for metrics, Chart for trends, Table for lists, Badge for states |
| Sign-in, sign-up | A centred Card, Field, InputGroup for inputs with icons, Separator before social sign-in |
| List and detail | Table; a click on a row opens a Sheet on the right; DropdownMenu for row actions |
| Checkout | A step indicator on top, a Card per step, RadioGroup for shipping and payment |
| Dangerous actions | AlertDialog (with a title), Alert for warnings that stay |
| Search and filters | InputGroup with a magnifier, Combobox for suggestions, filter chips, ToggleGroup for sorting |
| Empty and loading | Empty (icon, message and action), Skeleton, Spinner for short waits |

With another library, keep the structure and use its names. The project's own component library comes first.
