/*
 * corthex-uxui · page-check.js
 *
 * Measures the page that is open now, at the current window width. It changes nothing on the page.
 * Use: paste this file into the browser's developer tools console, or run it with the evaluate
 *      call of an automation tool (Playwright, Puppeteer, a browser tool).
 *      Resize the window for each width (such as 320, 390, 768 and 1440) and run it again.
 * Result: returns a report object and prints a summary to the console. pass is true when there are no errors.
 * Options: before running, set window.__pageCheckOptions = { maxIssues: 300, maxChars: 40000 }.
 *
 * What it measures
 *   Korean line breaks: missing keep-all or break-all, words split at a line end, orphans
 *   Overflow: text outside its box or clipped, the page scrolling sideways
 *   Contrast: text, field values and placeholders 4.5:1, large text 3:1, through any opacity
 *             (text over images, gradients or other boxes is flagged for a check by hand)
 *   Target size: 24×24 px (WCAG 2.5.8, with the spacing and in-sentence link exceptions)
 *   Basic accessibility: img alt, field labels, html lang
 *   Motion: transition: all, properties that trigger layout, prefers-reduced-motion rules
 */
(async (opts) => {
  const o = Object.assign({ maxIssues: 300, maxChars: 40000 }, opts || {});

  // Measure after the fonts and the layout have settled.
  if (document.fonts && document.fonts.ready) await document.fonts.ready;
  await new Promise((resolve) => {
    let done = false;
    const finish = () => { if (!done) { done = true; resolve(); } };
    requestAnimationFrame(() => requestAnimationFrame(finish));
    setTimeout(finish, 150);
  });

  const issues = [];
  const counts = { error: 0, warn: 0, info: 0 };
  const byCheck = {};
  const add = (level, check, msg, el, extra) => {
    counts[level]++;
    byCheck[check] = (byCheck[check] || 0) + 1;
    if (issues.length < o.maxIssues) {
      issues.push(Object.assign({ level, check, msg, where: el ? where(el) : "", text: el ? snippet(el.textContent) : "" }, extra || {}));
    }
  };

  // ---------- Helpers ----------
  const styleCache = new Map();
  const css = (el) => {
    let s = styleCache.get(el);
    if (!s) { s = getComputedStyle(el); styleCache.set(el, s); }
    return s;
  };
  const oneLine = (t) => (t || "").replace(/\s+/g, " ").trim();
  const snippet = (t) => oneLine(t).slice(0, 40);
  function where(el) {
    const parts = [];
    for (let e = el, d = 0; e && e.nodeType === 1 && d < 4; e = e.parentElement, d++) {
      let s = e.localName;
      if (e.id) { parts.unshift(s + "#" + CSS.escape(e.id)); break; }
      s += [...e.classList].slice(0, 2).map((c) => "." + CSS.escape(c)).join("");
      const p = e.parentElement;
      if (p) {
        const same = [...p.children].filter((c) => c.localName === e.localName);
        if (same.length > 1) s += ":nth-of-type(" + (same.indexOf(e) + 1) + ")";
      }
      parts.unshift(s);
    }
    return parts.join(" > ");
  }
  function shown(el) {
    if (!el || !el.isConnected) return false;
    if (el.checkVisibility && !el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) return false;
    const s = css(el);
    if (s.display === "none" || s.visibility === "hidden" || s.visibility === "collapse") return false;
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1; // leaves out 1 px text meant only for screen readers
  }
  // Character ranges are built from code points (invisible characters or escapes in the source can change when copied or passed through tools).
  const charClass = (ranges, prefix) => new RegExp("[" + (prefix || "") + ranges.map(([a, b]) => String.fromCharCode(a) + (b ? "-" + String.fromCharCode(b) : "")).join("") + "]");
  const HANGUL = charClass([[0x1100, 0x11ff], [0x3130, 0x318f], [0xa960, 0xa97f], [0xac00, 0xd7af], [0xd7b0, 0xd7ff]]);
  const LATIN_DIGIT = charClass([[0xc0, 0x24f]], "A-Za-z0-9");
  const BREAK_OK = charClass([[0xad], [0x200b]], /\s/.source); // spaces, soft hyphens and zero-width spaces are allowed break points
  const isWord = (c) => HANGUL.test(c) || LATIN_DIGIT.test(c);
  const SKIP = new Set(["script", "style", "noscript", "template", "svg", "math", "textarea", "select", "option", "iframe", "canvas", "video", "audio", "object", "head"]);
  const NO_SPLIT = new Set(["pre", "code", "kbd", "samp"]);

  function blockOf(el) {
    for (let e = el; e && e !== document.documentElement; e = e.parentElement) {
      const d = css(e).display;
      if (d !== "inline" && d !== "contents") return e;
    }
    return document.body;
  }
  // The edges inside a box's border (with pad, inside its padding too), in the units of getBoundingClientRect(r): a
  // transform such as scale() changes those units but not the computed widths, so the widths are scaled to match.
  function inner(e, r, pad) {
    const s = css(e);
    const kx = e.offsetWidth ? r.width / e.offsetWidth : 1, ky = e.offsetHeight ? r.height / e.offsetHeight : 1;
    const w = (side) => parseFloat(s["border" + side + "Width"]) + (pad ? parseFloat(s["padding" + side]) : 0);
    return { left: r.left + w("Left") * kx, right: r.right - w("Right") * kx, top: r.top + w("Top") * ky, bottom: r.bottom - w("Bottom") * ky };
  }
  // The box around a block that cuts its text off (t: where the text lies): overflow hidden or clip, with the text partly
  // inside it. Text wholly outside is hidden on purpose (a closed panel), and what a scrolling box holds can be reached.
  function clipperOf(block, t) {
    if (!(t.bottom > t.top && t.right > t.left)) return null;
    let escaping = false; // inside an absolutely positioned box, until its containing block
    let x = true, y = true; // whether a box further out may still cut the text at the sides, and at the top or bottom
    for (let e = block; ;) {
      const s = css(e);
      if (s.position === "fixed") return null;
      if (/auto|scroll/.test(s.overflowX)) x = false;
      if (/auto|scroll/.test(s.overflowY)) y = false;
      if (!x && !y) return null;
      if (s.position === "absolute") escaping = true;
      e = e.parentElement;
      if (!e || e === document.body || e === document.documentElement) return null;
      const p = css(e);
      if (escaping && p.position === "static" && p.transform === "none") continue; // it does not clip that box
      escaping = false;
      const cutX = x && /hidden|clip/.test(p.overflowX);
      const cutY = y && /hidden|clip/.test(p.overflowY) && p.getPropertyValue("-webkit-line-clamp") === "none";
      if (cutX || cutY) {
        const b = inner(e, e.getBoundingClientRect(), false);
        const partly = t.top < b.bottom && t.bottom > b.top && t.left < b.right && t.right > b.left;
        if (partly && ((cutX && (t.right > b.right + 2 || t.left < b.left - 2)) || (cutY && (t.bottom > b.bottom + 2 || t.top < b.top - 2)))) return e;
      }
    }
  }

  // Colour: a computed value may not be rgb() (oklch, color()), so a canvas turns it into sRGB.
  const cv = document.createElement("canvas");
  cv.width = cv.height = 1;
  const cx = cv.getContext("2d", { willReadFrequently: true });
  const colorCache = new Map();
  function rgba(str) {
    if (colorCache.has(str)) return colorCache.get(str);
    cx.clearRect(0, 0, 1, 1);
    cx.fillStyle = "rgba(0,0,0,0)";
    cx.fillStyle = str;
    cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data;
    const c = [d[0], d[1], d[2], d[3] / 255];
    colorCache.set(str, c);
    return c;
  }
  // Premultiplied colours ([r·a, g·a, b·a, a]) make painting one colour over another, and fading by opacity, plain arithmetic.
  const pre = (c) => [c[0] * c[3], c[1] * c[3], c[2] * c[3], c[3]];
  const over = (top, bottom) => top.map((v, i) => v + bottom[i] * (1 - top[3]));
  const lin = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const lum = (c) => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const hex = (c) => "#" + c.slice(0, 3).map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");

  // ---------- 1. Walking the text: Korean line breaks and overflow ----------
  const groups = new Map(); // block → [text nodes]
  const parents = new Set();
  // A line may start after any box that is not plain inline text: a block, an inline-block, an image, a field, a <br>
  // or a <wbr>. The first text after the end of each one is marked, wherever that text sits.
  const BOXES = new Set(["img", "svg", "video", "canvas", "iframe", "object", "embed", "input", "textarea", "select", "audio", "math", "br", "wbr"]);
  const markAfter = new Set();
  const within = []; // the boxes the walk is inside
  let breakNext = false;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (SKIP.has(n.parentNode.localName) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    while (within.length && !within[within.length - 1].contains(n)) { within.pop(); breakNext = true; }
    if (n.nodeType === 1) {
      const d = css(n).display;
      if (d !== "none" && d !== "contents" && (d !== "inline" || BOXES.has(n.localName))) { within.push(n); breakNext = true; }
      continue;
    }
    const p = n.parentElement;
    if (!p) continue;
    const b = blockOf(p);
    if (!n.data.trim()) {
      // A space between two elements, as in <span>a</span> <span>b</span>, is still a place where the line may break.
      if (groups.has(b) && shown(p)) groups.get(b).push(n);
      continue;
    }
    if (!shown(p)) continue;
    if (breakNext) { markAfter.add(n); breakNext = false; }
    parents.add(p);
    if (!groups.has(b)) groups.set(b, []);
    groups.get(b).push(n);
  }

  // keep-all and break-all: read from the style of each text node's parent.
  for (const p of parents) {
    const s = css(p);
    const t = [...p.childNodes].filter((c) => c.nodeType === 3).map((c) => c.data).join("").trim();
    if (!HANGUL.test(t) || !/\S\s+\S/.test(t)) continue; // a single word never breaks
    if (/^(nowrap|pre)$/.test(s.whiteSpace) || s.textWrapMode === "nowrap") continue;
    if (NO_SPLIT.has(p.localName)) continue;
    if (s.wordBreak === "break-all") add("error", "hangul-breakall", "word-break: break-all on Korean text", p);
    else if (s.wordBreak !== "keep-all") add("error", "hangul-keepall", "Korean block without word-break: keep-all (now " + s.wordBreak + ")", p);
    else if (s.overflowWrap !== "break-word" && s.overflowWrap !== "anywhere") add("info", "hangul-overflowwrap", "keep-all without overflow-wrap: break-word (a long word may overflow)", p);
  }

  const range = document.createRange();
  const rectOf = (node, i, len) => {
    range.setStart(node, i);
    range.setEnd(node, i + len);
    const rs = range.getClientRects();
    for (const r of rs) if (r.width > 0 || r.height > 0) return r;
    return null;
  };
  let charsUsed = 0;
  let truncated = false;
  let bodyOrphans = 0;
  const vw = document.documentElement.clientWidth;
  const pageOut = new Map(); // blocks whose text runs past the right edge of the screen (candidates for the sideways scroll)
  outer: for (const [block, nodes] of groups) {
    const bs = css(block);
    const br = block.getBoundingClientRect();
    const { left, right } = inner(block, br, true);
    const scrolls = /auto|scroll/.test(bs.overflowX);
    const clips = /hidden|clip/.test(bs.overflowX);
    const ellipsis = bs.textOverflow === "ellipsis";
    const noSplit = NO_SPLIT.has(block.localName) || !!block.closest("pre");
    let prev = null, opp = false, hard = false, lines = 1, line = "", allText = "", maxOut = 0;
    const ext = { top: Infinity, bottom: -Infinity, left: Infinity, right: -Infinity }; // where the text lies
    for (const node of nodes) {
      if (markAfter.has(node)) hard = true;
      const text = node.data;
      for (let i = 0; i < text.length;) {
        const cp = text.codePointAt(i);
        const len = cp > 0xffff ? 2 : 1;
        const ch = text.slice(i, i + len);
        if (BREAK_OK.test(ch)) { opp = true; line += " "; allText += " "; i += len; continue; }
        if (++charsUsed > o.maxChars) { truncated = true; break outer; }
        const r = rectOf(node, i, len);
        if (r) {
          if (prev && r.top >= prev.r.bottom - 1) {
            lines++;
            line = "";
            if (!opp && !hard && !noSplit && isWord(prev.ch) && isWord(ch)) {
              const ctxt = prev.tail + "|" + text.slice(i, i + 6);
              if (HANGUL.test(prev.ch) || HANGUL.test(ch)) add("error", "hangul-split", "Korean word split at a line end: " + ctxt, block, { at: ctxt });
              else if (LATIN_DIGIT.test(prev.ch) && LATIN_DIGIT.test(ch)) add("warn", "latin-split", "Latin or digit run split at a line end: " + ctxt, block, { at: ctxt });
            }
          }
          if (!scrolls && !(clips && ellipsis)) maxOut = Math.max(maxOut, r.right - right, left - r.left);
          ext.top = Math.min(ext.top, r.top);
          ext.bottom = Math.max(ext.bottom, r.bottom);
          ext.left = Math.min(ext.left, r.left);
          ext.right = Math.max(ext.right, r.right);
          if (r.right > vw + 1) pageOut.set(block, Math.max(pageOut.get(block) || 0, r.right - vw));
          prev = { ch, r, tail: (allText + ch).slice(-6) };
          opp = false;
          hard = false;
        }
        line += ch;
        allText += ch;
        i += len;
      }
    }
    if (maxOut > 2) {
      add("error", clips ? "text-clipped" : "text-overflow",
        (clips ? "Text clipped (overflow hidden, no ellipsis) by " : "Text overflows its box by ") + Math.round(maxOut) + "px", block);
    }
    if (/hidden|clip/.test(bs.overflowY) && block.scrollHeight > block.clientHeight + 2 && bs.getPropertyValue("-webkit-line-clamp") === "none") {
      add("error", "text-clipped", "Text clipped vertically (fixed height, overflow hidden)", block);
    } else {
      // What the block hides itself (behind an ellipsis or a line clamp) is not cut again by the boxes around it
      const own = inner(block, br, false);
      if (clips) { ext.left = Math.max(ext.left, own.left); ext.right = Math.min(ext.right, own.right); }
      if (/hidden|clip/.test(bs.overflowY)) { ext.top = Math.max(ext.top, own.top); ext.bottom = Math.min(ext.bottom, own.bottom); }
      const cut = clipperOf(block, ext);
      if (cut) add("error", "text-clipped", "Text cut off by a box around it (overflow hidden): " + where(cut), block);
    }
    // Orphan: text of more than one line whose last line holds one short word. A warning for heading-like text; body text is only counted
    const last = line.trim().split(/\s+/).filter(Boolean);
    if (lines >= 2 && allText.trim().length >= 15 && last.length === 1 && (last[0].match(/\p{L}|\p{N}/gu) || []).join("").length <= 3) {
      const titleLike = /^h[1-6]$/.test(block.localName) || block.getAttribute("role") === "heading" || parseFloat(bs.fontSize) >= 20 || allText.trim().length <= 30;
      if (titleLike) add("warn", "orphan", "Heading or short text ends with one short word on its last line (orphan): " + last[0], block);
      else bodyOrphans++;
    }
  }
  if (bodyOrphans) add("info", "orphan-body", bodyOrphans + " orphans in body text (reduce them with text-wrap: pretty)", null);

  // ---------- 2. The page scrolling sideways ----------
  const docW = document.documentElement.clientWidth;
  const scrollW = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
  if (scrollW > docW + 1) {
    const culprits = [];
    for (const el of document.body.querySelectorAll("*")) {
      if (culprits.length > 400) break;
      if (SKIP.has(el.localName)) continue;
      const r = el.getBoundingClientRect();
      if (r.width === 0 || (r.right <= docW + 1 && r.left >= -1)) continue;
      const pr = el.parentElement ? el.parentElement.getBoundingClientRect() : null;
      if (pr && (pr.right > docW + 1 || pr.left < -1)) continue; // only the outermost culprits
      culprits.push({ el, out: Math.max(r.right - docW, -r.left) });
    }
    if (!culprits.length) for (const [el, out] of pageOut) culprits.push({ el, out }); // the boxes fit but their text overflows
    culprits.sort((a, b) => b.out - a.out);
    add("error", "page-overflow", "The page scrolls sideways by " + (scrollW - docW) + "px" +
      (culprits.length ? ". Likely causes: " + culprits.slice(0, 3).map((c) => where(c.el) + " (" + Math.round(c.out) + "px)").join(", ") : ""),
      null, { culprits: culprits.slice(0, 5).map((c) => where(c.el)) });
  }

  // ---------- 3. Contrast ----------
  let underOpacity = 0;
  const imageTags = new Set(["img", "video", "canvas", "svg", "picture", "iframe"]);
  // The colours of the text and of the background beside it, painted as the browser paints them up the ancestors:
  // each box paints its background under its content, and its opacity fades the whole box, background included.
  function composite(el, colorStr) {
    let text = pre(rgba(colorStr)), back = [0, 0, 0, 0], faded = false;
    for (let e = el; e; e = e.parentElement) {
      const s = css(e);
      if (back[3] < 0.999) { // once the backdrop is opaque, the backgrounds behind it no longer show
        if (s.backgroundImage && s.backgroundImage !== "none") return { image: true };
        const b = pre(rgba(s.backgroundColor));
        text = over(text, b);
        back = over(back, b);
      }
      const a = parseFloat(s.opacity);
      if (a < 1) { faded = true; text = text.map((v) => v * a); back = back.map((v) => v * a); }
    }
    const canvas = [255, 255, 255, 1];
    return { text: over(text, canvas), base: over(back, canvas), faded, image: false };
  }
  // Whether something other than the text's ancestors is painted behind it, at one spot: an image, or a box from elsewhere
  // in the page with a background (a layer placed under the text). What is painted above the text does not count.
  function behindOther(el) {
    if (rgba(css(el).backgroundColor)[3] >= 1) return false; // its own opaque background hides whatever lies below
    const r = el.getBoundingClientRect();
    const x = r.left + r.width / 2, y = r.top + Math.min(r.height / 2, 12);
    if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return false;
    const stack = document.elementsFromPoint(x, y);
    for (const e of stack.slice(stack.indexOf(el) + 1)) { // the whole stack when the text's box is not hit (pointer-events: none)
      if (el.contains(e)) continue;
      if (e.contains(el)) return false; // from an ancestor on, composite() takes over
      if (imageTags.has(e.localName)) return true;
      const s = css(e);
      if (s.backgroundImage !== "none" || rgba(s.backgroundColor)[3] > 0) return true;
    }
    return false;
  }
  const checkContrast = (el, colorStr, label) => {
    const s = css(el);
    const size = parseFloat(s.fontSize);
    const weight = parseInt(s.fontWeight, 10) || (s.fontWeight === "bold" ? 700 : 400);
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    const need = large ? 3 : 4.5;
    const font = Math.round(size * 10) / 10 + "px " + weight;
    const bd = composite(el, colorStr);
    if (bd.image || behindOther(el)) {
      add("warn", "contrast-image", label + "Text over an image, a gradient or another box: check by hand at the worst spot", el, { need, font });
      return;
    }
    if (bd.faded) underOpacity++;
    const r = ratio(bd.text, bd.base);
    const detail = { ratio: Math.round(r * 100) / 100, need, fg: hex(bd.text), bg: hex(bd.base), font };
    if (r < need) add("error", "contrast", label + "Contrast " + detail.ratio + ":1 < " + need + ":1 (text " + detail.fg + " / background " + detail.bg + ", " + font + ")", el, detail);
  };
  for (const p of parents) {
    if (p.closest(":disabled, [aria-disabled='true'], [inert]")) continue; // disabled controls are exempt
    if (!p.closest("a, button, label, [role]") && [...p.childNodes].every((c) => c.nodeType !== 3 || !c.data.trim())) continue;
    checkContrast(p, css(p).color, "");
  }
  // A field's value and its placeholder are not text nodes, so they are measured here. The value itself never goes into the report.
  const FIELDS = "input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=range]):not([type=color]):not([type=file]):not([type=image]), textarea, select";
  for (const f of document.querySelectorAll(FIELDS)) {
    if (!shown(f) || f.closest(":disabled, [aria-disabled='true'], [inert]")) continue;
    const value = f.localName === "select" ? (f.selectedOptions[0] ? f.selectedOptions[0].text : "") : f.value;
    if (value.trim()) {
      checkContrast(f, css(f).color, "Field value: ");
    } else if (f.placeholder) {
      let ph;
      try { ph = getComputedStyle(f, "::placeholder").color; } catch (e) { ph = null; }
      if (ph) checkContrast(f, ph, "Placeholder: ");
    }
  }

  // ---------- 4. Target size ----------
  const TARGETS = "a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=link], [role=checkbox], [role=radio], [role=switch], [role=tab], [role=menuitem], [role=option], [tabindex]:not([tabindex='-1'])";
  const targets = [...document.querySelectorAll(TARGETS)].filter((t) => shown(t) && !t.closest(":disabled, [aria-disabled='true'], [inert]"));
  const boxes = targets.map((t) => ({ t, r: t.getBoundingClientRect() }));
  const small = boxes.filter((b) => b.r.width < 24 || b.r.height < 24);
  const center = (r) => [r.left + r.width / 2, r.top + r.height / 2];
  const distToRect = (p, r) => Math.hypot(Math.max(r.left - p[0], 0, p[0] - r.right), Math.max(r.top - p[1], 0, p[1] - r.bottom));
  let goalMiss = 0;
  for (const b of boxes) if (b.r.width < 44 || b.r.height < 44) goalMiss++;
  for (const b of small) {
    const t = b.t;
    const s = css(t);
    if ((t.localName === "a" || t.getAttribute("role") === "link") && s.display === "inline") {
      const blk = blockOf(t);
      if (oneLine(blk.textContent).length > oneLine(t.textContent).length + 3) continue; // exception: a link inside a sentence
    }
    if (t.localName === "input" && /^(checkbox|radio)$/.test(t.type) && s.appearance !== "none") continue; // exception: size set by the browser
    const c = center(b.r);
    const clash = boxes.some((o2) => {
      if (o2 === b || o2.t.contains(t) || t.contains(o2.t)) return false;
      const small2 = o2.r.width < 24 || o2.r.height < 24;
      return small2 ? Math.hypot(c[0] - center(o2.r)[0], c[1] - center(o2.r)[1]) < 24 : distToRect(c, o2.r) < 12;
    });
    if (clash) add("error", "target-size", "Target " + Math.round(b.r.width) + "×" + Math.round(b.r.height) + "px < 24px, and too close to its neighbours", t);
    else add("info", "target-size-spacing", "Target " + Math.round(b.r.width) + "×" + Math.round(b.r.height) + "px, passes by the spacing exception", t);
  }
  if (goalMiss) add("info", "target-goal", goalMiss + " targets smaller than 44px (the iOS 44pt and Android 48dp goals)", null);

  // ---------- 5. Basic accessibility ----------
  for (const img of document.querySelectorAll("img:not([alt])")) if (shown(img)) add("error", "img-alt", "img without alt (alt=\"\" if it is decorative)", img);
  for (const f of document.querySelectorAll("input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset]):not([type=image]), select, textarea")) {
    if (!shown(f)) continue;
    const named = (f.labels && f.labels.length) || f.getAttribute("aria-label") || f.getAttribute("aria-labelledby") || f.getAttribute("title");
    if (!named) add("error", "label", "Field without a label (a placeholder is not a label)", f);
  }
  if (!document.documentElement.lang) add("warn", "lang", "html without lang (such as lang=\"en\" or lang=\"ko\")", null);

  // ---------- 6. Motion ----------
  const LAYOUT = /^(width|height|top|left|right|bottom|inset|margin|padding|min-|max-)/;
  const secs = (v) => v.split(",").map((x) => (x.trim().endsWith("ms") ? parseFloat(x) / 1000 : parseFloat(x)));
  let moving = 0, scanned = 0;
  for (const el of document.body.querySelectorAll("*")) {
    if (++scanned > 5000) break;
    const s = css(el);
    const dur = secs(s.transitionDuration);
    const props = s.transitionProperty.split(",").map((x) => x.trim());
    if (dur.some((d) => d > 0)) {
      moving++;
      if (props.includes("all")) add("warn", "transition-all", "transition: all (name only the properties that move)", el);
      const lay = props.filter((p, i) => LAYOUT.test(p) && (dur[i % dur.length] || 0) > 0);
      if (lay.length) add("warn", "transition-layout", "Animates properties that trigger layout: " + lay.join(", ") + " (use transform and opacity)", el);
      if (Math.max(...dur) > 0.5) add("info", "transition-long", "Transition longer than 0.5 s: " + Math.max(...dur) + "s", el);
    }
    if (s.animationName !== "none" && secs(s.animationDuration).some((d) => d > 0)) moving++;
  }
  let reducedRule = false, unreadable = 0;
  const scan = (rules) => {
    for (const r of rules) {
      const cond = r.conditionText || (r.media && r.media.mediaText) || "";
      if (/prefers-reduced-motion/.test(cond)) { reducedRule = true; return; }
      if (r.styleSheet) { try { scan(r.styleSheet.cssRules); } catch (e) { unreadable++; } }
      if (r.cssRules) scan(r.cssRules);
    }
  };
  for (const sh of document.styleSheets) { try { scan(sh.cssRules); } catch (e) { unreadable++; } }
  if (moving && !reducedRule) {
    add(unreadable ? "info" : "warn", "reduced-motion",
      moving + " moving elements and no prefers-reduced-motion rule found" + (unreadable ? " (" + unreadable + " external style sheets could not be read)" : " (ignore this if script handles it)"), null);
  }

  // ---------- Report ----------
  if (underOpacity) add("info", "contrast-opacity", "Contrast of " + underOpacity + " texts under opacity worked out from their ancestors only (anything else showing through is not counted)", null);
  const report = {
    tool: "corthex-uxui page-check",
    version: "1.0",
    url: location.href,
    viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio },
    env: { reducedMotion: matchMedia("(prefers-reduced-motion: reduce)").matches, dark: matchMedia("(prefers-color-scheme: dark)").matches },
    pass: counts.error === 0,
    counts,
    byCheck,
    truncated,
    issues,
    notMeasured: [
      "Keyboard focus visibility and order (press Tab yourself)",
      "Contrast of text over images, gradients or other boxes (the places flagged contrast-image)",
      "3:1 contrast of control borders and state indicators (WCAG 1.4.11)",
      "The order and names a screen reader reads",
      "The real screen with reduced motion turned on",
      "Content inside Shadow DOM and iframes",
    ],
  };
  try { window.__pageCheckReport = report; } catch (e) { /* the result is still returned when the window is read-only */ }
  try {
    console.log("[page-check] width " + innerWidth + "px: " + (report.pass ? "pass" : "fail") + " · errors " + counts.error + " · warnings " + counts.warn + " · info " + counts.info + (truncated ? " · only part measured (too much text)" : ""));
    if (issues.length) console.table(issues.slice(0, 60).map((x) => ({ level: x.level, check: x.check, msg: x.msg, where: x.where })));
  } catch (e) { /* the result is still returned without a console */ }
  return report;
})(typeof window !== "undefined" ? window.__pageCheckOptions : undefined);
