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
3. Palette of 4 colors with hex, taken from that world: one dominant background, one ink, one strong accent, one supporting tone. Default is a light, warm or tinted background; dark only if the subject is about night or screens.
4. Type: one display face with character (system stacks: Georgia, "Iowan Old Style", Palatino for warmth; "Arial Black", Impact-like heavy sans with uppercase and letter-spacing for industrial; ui-monospace for labels and prices) over a plain body face. Make the display size really large (clamp(48px, 8vw, 120px)) on at least one element.
5. One signature move, repeated: oversized numerals, a stamped label or badge, a ruled ledger or price-board table, a big edge-to-edge color block, one strongly cropped shape.
6. One layout rule that breaks the default: asymmetric split, left-aligned over a visible grid, full-bleed color bands, content not centered.

Never: three identical rounded cards in a row; gradient rectangles standing in for photos; faint outline drawings in a box; a headline of the form "X. Y." (two short slogans); dark background with 1px-bordered cards as the default; icons-in-circles. Products go in a list or table with large price numerals, or as one colored block each carrying a typographic label. If you draw something, draw it in inline SVG with flat, full-contrast shapes at large scale, or let type and color blocks carry the page.

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
