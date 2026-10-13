"""Measured visual audit of the page in the browser. It finds defects by geometry and computed style,
so it does not depend on a model's eyes: overflow, contrast, holes in grids, huge empty boxes,
duplicated controls, tiny targets and icons, overlaps, missing basics.
"""

AUDIT_JS = r"""
(() => {
  const vw = innerWidth, vh = innerHeight, F = [];
  const cv = document.createElement("canvas"); cv.width = cv.height = 1;
  const cx = cv.getContext("2d", { willReadFrequently: true });
  const rgba = css => { try { cx.clearRect(0, 0, 1, 1); cx.fillStyle = "#000"; cx.fillStyle = css; cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; } catch { return [0, 0, 0, 1]; } };
  const lum = ([r, g, b]) => { const f = v => { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }; return .2126 * f(r) + .7152 * f(g) + .0722 * f(b); };
  const over = (fg, bg) => [0, 1, 2].map(i => fg[i] * fg[3] + bg[i] * (1 - fg[3]));
  const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); return (Math.max(l1, l2) + .05) / (Math.min(l1, l2) + .05); };
  const R = e => e.getBoundingClientRect();
  const vis = e => { const r = R(e), c = getComputedStyle(e); return r.width > 0 && r.height > 0 && c.visibility !== "hidden" && c.display !== "none" && +c.opacity > .05; };
  const sel = e => { let s = e.tagName.toLowerCase(); if (e.id) return s + "#" + e.id; const c = [...e.classList].slice(0, 2).join("."); if (c) s += "." + c;
    const t = (e.textContent || "").trim().replace(/\s+/g, " ").slice(0, 22); return s + (t ? ` "${t}"` : ""); };
  const box = e => { const r = R(e); return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; };
  const add = (sev, kind, msg, e) => F.push({ sev, kind, msg, at: e ? sel(e) : "", box: e ? box(e) : null });
  const els = [...document.body.querySelectorAll("*")].filter(vis);
  const isSkip = e => ["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "META", "LINK"].includes(e.tagName);

  // 1. horizontal overflow
  const sw = document.documentElement.scrollWidth;
  if (sw > vw + 1) {
    const off = els.filter(e => R(e).right > vw + 1 && !isSkip(e)).slice(0, 3);
    add("high", "overflow", `page scrolls horizontally: content is ${sw}px wide in a ${vw}px viewport`, off[0] || null);
  }

  // 2. contrast of text
  const bgOf = e => { let bg = [255, 255, 255, 1]; const stack = [];
    for (let n = e; n; n = n.parentElement) { const c = getComputedStyle(n); if (c.backgroundImage !== "none") return null;
      const b = rgba(c.backgroundColor); if (b[3] > 0) { stack.push(b); if (b[3] >= .99) break; } }
    for (const b of stack.reverse()) bg = [...over(b, bg), 1];
    return bg; };
  const seen = new Set(), low = [];
  for (const e of els) {
    if (isSkip(e)) continue;
    const own = [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 0);
    if (!own) continue;
    const c = getComputedStyle(e), bg = bgOf(e); if (!bg) continue;
    let fg = rgba(c.color); fg[3] *= +c.opacity;
    const fgc = over(fg, bg), size = parseFloat(c.fontSize), bold = parseInt(c.fontWeight) >= 600;
    const need = (size >= 24 || (size >= 18.66 && bold)) ? 3 : 4.5, r = ratio(fgc, bg);
    if (r < need) { const k = c.color + "|" + bg.join(","); if (!seen.has(k)) { seen.add(k); low.push({ e, r, need, size }); } }
  }
  low.sort((a, b) => a.r - b.r).slice(0, 5).forEach(x => add(x.r < 3 ? "high" : "medium", "contrast",
    `text contrast ${x.r.toFixed(1)}:1 (needs ${x.need}:1) at ${Math.round(x.size)}px`, x.e));

  // 3. text size
  const small = els.filter(e => !isSkip(e) && [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 1) && parseFloat(getComputedStyle(e).fontSize) < 12);
  if (small.length) add("medium", "text-size", `${small.length} text element(s) under 12px (smallest ${Math.min(...small.map(e => parseFloat(getComputedStyle(e).fontSize)))}px)`, small[0]);

  // 4. tap targets and icons
  const inter = els.filter(e => e.matches("button, a[href], input:not([type=hidden]), select, textarea, [role=button], summary"));
  const tiny = inter.filter(e => { const r = R(e); if (e.matches("a[href]") && getComputedStyle(e).display === "inline") return false; return Math.min(r.width, r.height) < 32 && !e.matches("input[type=checkbox],input[type=radio]"); });
  if (tiny.length) add(vw < 600 ? "high" : "medium", "target-size", `${tiny.length} interactive element(s) smaller than 32px (smallest ${Math.round(Math.min(...tiny.map(e => Math.min(R(e).width, R(e).height))))}px)`, tiny[0]);
  for (const b of inter.filter(e => e.matches("button, [role=button]"))) {
    const t = (b.textContent || "").trim();
    const hasSvg = b.querySelector("svg, img");
    if (hasSvg || (t.length <= 2 && !/^[\p{L}\p{N}]+$/u.test(t) && t.length > 0)) {
      let r;
      if (hasSvg) r = R(b.querySelector("svg, img")); else { const rg = document.createRange(); rg.selectNodeContents(b); r = rg.getBoundingClientRect(); }
      const br = R(b);
      if (r.width > 0 && Math.max(r.width, r.height) < 15 && Math.min(br.width, br.height) >= 28)
        add("medium", "icon-size", `icon is only ${Math.round(Math.max(r.width, r.height))}px inside a ${Math.round(br.width)}x${Math.round(br.height)} button; it reads as a smudge`, b);
    }
  }

  // 5. holes in grids
  for (const g of els.filter(e => getComputedStyle(e).display === "grid")) {
    const kids = [...g.children].filter(vis); if (kids.length < 4) continue;
    const c = getComputedStyle(g), cols = c.gridTemplateColumns.split(" ").map(parseFloat).filter(n => !isNaN(n)), rows = c.gridTemplateRows.split(" ").map(parseFloat).filter(n => !isNaN(n));
    if (cols.length < 2 || rows.length < 2) continue;
    const gr = R(g), gx = parseFloat(c.columnGap) || 0, gy = parseFloat(c.rowGap) || 0;
    const pl = parseFloat(c.paddingLeft) + parseFloat(c.borderLeftWidth), pt = parseFloat(c.paddingTop) + parseFloat(c.borderTopWidth);
    const occ = rows.map(() => cols.map(() => false));
    let y = gr.top + pt;
    rows.forEach((rh, ri) => { let x = gr.left + pl;
      cols.forEach((cw, ci) => { for (const k of kids) { const r = R(k), ox = Math.min(r.right, x + cw) - Math.max(r.left, x), oy = Math.min(r.bottom, y + rh) - Math.max(r.top, y);
          if (ox > cw * .3 && oy > rh * .3) { occ[ri][ci] = true; break; } } x += cw + gx; }); y += rh + gy; });
    const holes = []; occ.forEach((row, ri) => row.forEach((o, ci) => { if (!o) holes.push([ri + 1, ci + 1]); }));
    if (holes.length && holes.length < cols.length * rows.length / 2) add("medium", "grid-hole", `grid ${cols.length}x${rows.length} has ${holes.length} empty cell(s) at (row,col) ${holes.slice(0, 5).map(h => h.join(",")).join(" ")}. Fix the layout (columns x rows must match the item count, or let an item span): never add placeholder items`, g);
  }

  // 6. big empty boxes
  const contentSel = "img, svg, canvas, video, iframe, input, textarea, select, button, a, picture";
  for (const e of els) {
    if (isSkip(e) || e.matches(contentSel)) continue;
    const r = R(e), area = r.width * r.height; if (area < vw * vh * .09 || r.width > vw * .98 && r.height > vh * .9) continue;
    if ((e.textContent || "").trim().length || e.querySelector(contentSel)) continue;
    const c = getComputedStyle(e), looksLikeBox = rgba(c.backgroundColor)[3] > .05 || parseFloat(c.borderTopWidth) > 0;
    if (looksLikeBox) add("medium", "empty-area", `empty box ${Math.round(r.width)}x${Math.round(r.height)} (${Math.round(area / (vw * vh) * 100)}% of the viewport) carries no content`, e);
  }

  // 6b. controls without any content or name (also catches placeholder items used to fill holes)
  const nameless = inter.filter(e => e.matches("button, [role=button], a[href]") && !(e.textContent || "").trim() && !e.getAttribute("aria-label")
    && !e.getAttribute("title") && !e.querySelector("svg, img, canvas") && !e.getAttribute("aria-labelledby"));
  if (nameless.length) add("high", "empty-control", `${nameless.length} button/link(s) have no label, text or icon (empty placeholder items?)`, nameless[0]);

  // 7. duplicate controls inside one group
  const labels = new Map();
  for (const b of inter.filter(e => e.matches("button, [role=button]"))) {
    const t = ((b.getAttribute("aria-label") || b.textContent || "").trim().replace(/\s+/g, " ")).toLowerCase(); if (!t) continue;
    (labels.get(t) || labels.set(t, []).get(t)).push(b);
  }
  for (const [t, list] of labels) {
    if (list.length < 2) continue;
    let a = list[0]; while (a && !list.every(x => a.contains(x))) a = a.parentElement;
    if (a && [...a.querySelectorAll("button, [role=button]")].length >= 6) add("medium", "duplicate", `control "${t}" appears ${list.length} times in the same group`, list[1]);
  }

  // 8. overlapping text
  const leaves = els.filter(e => !isSkip(e) && ![...e.children].some(vis) && (e.textContent || "").trim().length > 0).slice(0, 300);
  let ov = 0, ovEl = null;
  for (let i = 0; i < leaves.length && ov < 3; i++) for (let j = i + 1; j < leaves.length; j++) {
    const a = R(leaves[i]), b = R(leaves[j]); if (leaves[i].contains(leaves[j]) || leaves[j].contains(leaves[i])) continue;
    const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left), oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    if (ox > 4 && oy > 4 && ox * oy > .25 * Math.min(a.width * a.height, b.width * b.height)) { ov++; ovEl = ovEl || leaves[i]; }
  }
  if (ov) add("high", "overlap", `${ov} pair(s) of text elements overlap each other`, ovEl);

  // 9. clipped text
  const clipped = els.filter(e => !isSkip(e) && e.scrollWidth > e.clientWidth + 2 && R(e).width > 8 && /hidden|clip/.test(getComputedStyle(e).overflowX) && (e.textContent || "").trim().length);
  if (clipped.length) add("low", "clipped", `${clipped.length} element(s) cut their text off`, clipped[0]);

  // 10. basics
  if (!document.querySelector('meta[name="viewport"]')) add("high", "viewport", "no <meta name=viewport>; the page will not scale on phones", null);
  if (!document.documentElement.lang) add("low", "lang", "missing lang attribute on <html>", null);
  const noAlt = els.filter(e => e.tagName === "IMG" && !e.hasAttribute("alt"));
  if (noAlt.length) add("medium", "alt", `${noAlt.length} image(s) without alt text`, noAlt[0]);
  const broken = els.filter(e => e.tagName === "IMG" && e.complete && e.naturalWidth === 0);
  if (broken.length) add("high", "broken-image", `${broken.length} image(s) failed to load`, broken[0]);
  const unlabeled = inter.filter(e => e.matches("input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select, textarea") && !(e.labels && e.labels.length) && !e.getAttribute("aria-label") && !e.getAttribute("aria-labelledby"));
  if (unlabeled.length) add("low", "label", `${unlabeled.length} field(s) without a label (placeholder is not a label)`, unlabeled[0]);

  // 11. discipline
  const fam = new Set(els.filter(e => (e.textContent || "").trim()).map(e => getComputedStyle(e).fontFamily.split(",")[0].trim().replace(/["']/g, "")));
  if (fam.size > 3) add("low", "fonts", `${fam.size} font families in use (${[...fam].slice(0, 4).join(", ")})`, null);
  const body = document.body, bw = Math.max(...[...body.children].filter(vis).map(c => R(c).width), 0);
  if (vw >= 1000 && bw && bw < vw * .4) add("low", "narrow", `content is a ${Math.round(bw)}px column in a ${vw}px viewport`, null);

  // 12. card soup: a site-like page where most content sits in identical bordered, rounded, filled boxes
  const siteLike = !!document.querySelector("footer") && (() => { const h = document.querySelector("h1"); return h && parseFloat(getComputedStyle(h).fontSize) >= 32; })();
  if (siteLike) {
    const boxes = els.filter(e => {
      if (isSkip(e) || !vis(e)) return false;
      const s = getComputedStyle(e), r = R(e);
      return r.width > 140 && r.height > 60 && r.width < vw * .98 && parseFloat(s.borderTopWidth) >= 1 && s.borderTopStyle !== "none" && parseFloat(s.borderTopLeftRadius) >= 4
        && e.textContent.trim().length > 12 && !/^(INPUT|BUTTON|SELECT|TEXTAREA|TABLE|A)$/.test(e.tagName);
    });
    const sig = e => { const s = getComputedStyle(e); return [s.borderTopWidth, s.borderTopColor, s.borderTopLeftRadius].join("|"); };
    const groups = {};
    boxes.forEach(e => (groups[sig(e)] = groups[sig(e)] || []).push(e));
    const biggest = Object.values(groups).sort((a, b) => b.length - a.length)[0] || [];
    if (biggest.length >= 5) add("medium", "card-soup", `${biggest.length} content blocks share one bordered, rounded box style; the page reads as a template. Use ruled lists, tables, full-bleed bands or large type instead of boxing everything`, biggest[0]);
  }

  return { vw, vh, findings: F };
})()
"""

ORDER = {"high": 0, "medium": 1, "low": 2}


def format_report(results: list[dict]) -> str:
    """results: [{'vw','vh','findings'}] one per audited size."""
    lines, total = [], 0
    for r in results:
        fs = sorted(r["findings"], key=lambda f: ORDER.get(f["sev"], 3))
        total += len(fs)
        lines.append(f"== {r['vw']}x{r['vh']}: " + (f"{len(fs)} finding(s)" if fs else "no findings"))
        for f in fs:
            at = f" [{f['at']}]" if f.get("at") else ""
            box = f" @ x{f['box'][0]} y{f['box'][1]} {f['box'][2]}x{f['box'][3]}" if f.get("box") else ""
            lines.append(f"  {f['sev'].upper():<6} {f['kind']}: {f['msg']}{at}{box}")
    if not total:
        lines.append("Audit clean at all sizes. (It checks geometry and contrast, not taste: also look at the screenshots.)")
    return "\n".join(lines)
