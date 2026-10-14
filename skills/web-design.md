---
name: web-design
description: How to make web pages and UIs look professional, and how to verify it
triggers: html, css, website, web site, webpage, web page, webseite, homepage, landing, frontend, front-end, ui, user interface, oberfläche, seite, dashboard, layout, design, redesign, calculator, rechner, widget, game, spiel, canvas, app, site, page, form, chart, visualization, animation, button
---
# Web design rules

## Concept first (sites, landing pages, anything with an identity)
Tools and dashboards follow the neutral rules below. A page for a real business, product or person needs a concept BEFORE code; without one the result is the same dark card grid every time. After your plan, write this brief in six short lines, then build exactly to it:
1. The real thing: name three concrete physical details of that world (materials, tools, places, smells, labels), e.g. for a roastery: jute sack, chalked price board, copper cooling tray. Use them for imagery and wording.
2. Mood in three words. Not "modern", "clean" or "minimal".
3. Palette of 4 to 6 named colors with hex, taken from that world: one dominant background, one ink, one strong accent, supporting tones. There is no default palette: cream background + terracotta accent + serif display, and near-black + neon green, are the two house styles of generated UI. If your first idea is one of them, throw it away and ask what the subject actually looks like.
4. Type: one display face with character (system stacks: Georgia, "Iowan Old Style", Palatino for warmth; "Arial Black", Impact-like heavy sans with uppercase and letter-spacing for industrial; ui-monospace for labels and prices) over a plain body face. Make the display size really large (clamp(48px, 8vw, 120px)) on at least one element.
5. One signature move, repeated: oversized numerals, a stamped label or badge, a ruled ledger or price-board table, a big edge-to-edge color block, one strongly cropped shape.
6. One layout rule that breaks the default: asymmetric split, left-aligned over a visible grid, full-bleed color bands, content not centered.

Never: three identical rounded cards in a row; gradient rectangles standing in for photos; faint outline drawings in a box; a headline of the form "X. Y." (two short slogans); dark background with 1px-bordered cards as the default; icons-in-circles. Products go in a list or table with large price numerals, or as one colored block each carrying a typographic label. If you draw something, draw it in inline SVG with flat, full-contrast shapes at large scale, or let type and color blocks carry the page.

## Every section carries the concept
The hero is rarely the problem; the lower half is where pages fall back to the template. Plan each section's component in your brief (one line per section) and keep to it:
- Boxes are not the default. Bordered, rounded, white-filled boxes may appear at most twice on a page. Information goes into one of these instead: a ruled list (hairline rows, label left, value right in the mono face), a table, a full-bleed band with its own background, a big-numeral column, a split with a large color block, a stamped label.
- Hours: a ruled list with the day left and the time right, the open days stronger than the closed ones. Address: set it large, as text, with a small note on how to find the place; no box.
- Offers and prices: the price is the largest thing in its row. Name, taste and price share one baseline grid.
- Rhythm: alternate the background tone between sections (paper, tinted, ink), use at least one full-bleed band, vary alignment (not every title centered above a grid).
- The footer is designed too: a large wordmark, a color band or a ruled list of links, not a gray strip with small print.
- The signature move from the brief appears in every section at least as an echo (same numeral style, same label shape, same rule weight).

## Copy
- Use only facts from the request: names, prices, hours, address, products. Do not invent numbers, years, origins, certifications, shipping times or promises. If a section needs a fact you do not have, write copy that does not need it and say so under "Assumptions".
- Check the language like an editor before you finish: article and ending agreement, singular and plural ("jede zweite Woche", "alle zwei Wochen"), compounds that really exist ("Abo-Bindung", not "Abo-Bindlichkeit"). Read the strings in the file once, slowly.
- Headlines state something specific and short. No two-slogan pattern ("Kaffee, der schmeckt. Direkt aus Altona.").

## Quality floor (always, without being asked)
- Semantic HTML (header, nav, main, section, article, footer, button, form, label, table where it is tabular). Every form control has a label, images have alt text, icon-only buttons have aria-label.
- Responsive down to 360px, no horizontal scroll, grid or flexbox rather than fixed pixel widths.
- Visible :focus-visible, subtle hover states, legible disabled states; respect prefers-reduced-motion and use motion only where it answers an action.
- Contrast at least 4.5:1 for body text and 3:1 for large text and UI borders. One spacing scale (4, 8, 12, 16, 24, 32, 48, 64) and a type scale with at most 5 sizes and 2 weights.
- Real-looking content: specific names, numbers and dates that fit the subject, in the language of the brief. Buttons say what happens ("Save changes", "Vorbestellen"), not "Submit". Empty, error and loading states are design, not afterthoughts.
- One `<style>` block with CSS custom properties; fonts only via Google Fonts `<link>`; images are CSS or inline SVG drawings. The file is complete: doctype, lang, viewport, title.

## Reference first
For a site or page brief, call `library_search` with the brief before you write the design brief: it returns design plans of similar solved briefs (palette, type, layout, the one bold point). Use them for direction and to see what "not the default" looks like; do not copy them.

## Process (always)
1. Before coding, decide what the page is for and its ONE primary action. Write real content: no lorem ipsum, no "Item 1".
2. Put colors, spacing and type in CSS custom properties first, then build.
3. Verify with measurements, not impressions. Open the page in the browser and run `browser_audit` (it checks desktop and phone width: overflow, contrast, holes in grids, huge empty boxes, duplicated controls, tiny targets and icons, overlaps). Fix every HIGH and MEDIUM finding, run it again, and repeat until it is clean (at most three rounds). Your own reading of a screenshot misses small defects; the audit does not.
4. Then take one screenshot at 1280x800 and one at 390x844 (`browser_resize`) and judge what measurements cannot: hierarchy (is the main thing the most prominent?), balance, whether it looks finished.

## Layout and space
- Spacing scale: 4, 8, 12, 16, 24, 32, 48, 64 px. Related things sit close, groups get more space between them than inside.
- Use the screen. Apps and sites: content width 1100-1200px max. Reading text: 60-70ch. Never leave one small column floating in an empty viewport: use a two-pane layout, a side panel, or a hero that fills the first screen.
- One clear primary action per view. Touch targets at least 40px high.

## Type
- One family: system-ui stack (or one pair at most). Sizes 12, 14, 16, 20, 28, 40. Body line-height 1.5, headings 1.2. Weights 400 and 600.
- Numbers that change: font-variant-numeric: tabular-nums. Hierarchy through size and weight, not only color. No text under 14px except captions.

## Color
- Neutrals from one hue: background, surface, border, text, muted text. Text contrast at least 4.5:1, muted text too. No gray on gray.
- One accent color for the primary action and focus. Status colors (red/green/amber) only for status.
- Dark theme: background about #0f1115, surfaces 4-8% lighter, never pure black or white, 1px subtle borders instead of heavy shadows. Light theme: off-white background, white surfaces.
- Use prefers-color-scheme when it is cheap.

## Components
- One corner radius (6-10px), 1px borders, shadows rare and soft.
- Every interactive element has hover, :focus-visible (2px outline, offset), active and disabled states. Inputs have visible labels, not only placeholders.
- Show real states: empty, loading, error, success, each with a useful message.
- Text labels on buttons. If you need icons, use small inline SVG, never emoji.

## Patterns
- Tool or app: header bar (name left, actions right), main work area using the full width, the result large and prominent, secondary things (history, settings) in a side panel or below and quieter.
- Landing page: hero with a headline of 8 words or fewer that states something specific, one supporting sentence and one action; then the offer as a list, table or colored blocks (not identical cards); then practical details (hours, address, price); footer. Vary section rhythm: not every section is a centered title over a grid.
- Dashboard: KPI row, one main chart or table, filters on top.

## Avoid (the generic AI look)
From a set of 300 solved design briefs, these are the tells of generated UI:
- Cream background plus terracotta accent plus serif display as a default; near-black plus neon green as a default.
- Identical rounded cards with the same soft shadow for everything. Not everything is a card.
- ALL-CAPS tracked eyebrow labels above every heading, "01 / 02 / 03" markers on non-sequences, "→" glued onto every link, meta strings joined with middle dots.
- Gradient blobs and glassmorphism as decoration. Fade-up animations on every section, hover-lift on every card.
- Coloring or italicizing a single word in a headline.
- Placeholder copy, generic icons with no meaning, stock-photo descriptions.
- Structure that does not encode anything: numbers only for real sequences, dividers only between real groups, badges only for real states.

Three identical rounded cards stacked; purple or blue gradients on navy; emoji as logo or icons; everything centered; a giant title over tiny content; glow shadows; placeholder-only fields; huge padding with little content; low-contrast gray text.

## Responsive and accessible
- <meta name="viewport" content="width=device-width, initial-scale=1">, mobile-first flex/grid, no horizontal scroll at 360px, panes stack.
- Semantic elements (header, main, nav, button, label), lang attribute, aria-live for changing results, everything keyboard operable.

## Starter tokens (neutral defaults for tools and apps; replace them with the concept's palette for sites)
```css
:root {
  --bg: #f6f7f9; --surface: #ffffff; --line: #e3e6ea; --text: #15181d; --muted: #5b6470; --accent: #2f6fed; --danger: #c93c37;
  --radius: 8px; --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 24px; --s6: 32px; --s7: 48px;
  --font: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; --mono: ui-monospace, "SF Mono", Menlo, monospace;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #0f1115; --surface: #171a20; --line: #262a32; --text: #e8eaee; --muted: #9aa3b0; --accent: #6f9bff; --danger: #ff7b72; }
}
```
