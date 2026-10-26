---
name: art-styles
description: How to execute a named art style (watercolor, papercut, linocut, risograph, blueprint, bauhaus, pixel, art deco ...) fully in CSS and SVG
triggers: art style, artstyle, art-style, kunststil, watercolor, aquarell, papercut, paper cut, papierschnitt, linocut, linolschnitt, risograph, blueprint, blaupause, bauhaus, swiss style, brutalist, brutalism, brutalismus, pixel art, pixelart, art deco, art déco, artdeco, memphis, chalkboard, kreidetafel, isometric, isometrisch, ink sketch, tusche, synthwave, neon, ukiyo-e, ukiyoe, halftone, halbton, mid-century, midcentury, letterpress, thermodruck, stained glass, bleiglas, origami, claymorphism, comic book, comic style, collage style, zine style, crt terminal
---

When the brief names one of these styles, execute it fully: texture, edges, shapes, type and color all follow the style, not just the palette. The style never excuses weak usability: contrast, focus, labels, responsiveness and readable body text still hold. A named style overrides the 'avoid' list of the web-design skill where they conflict.

# Art style cookbook (CSS + inline SVG only, no images)

Every style below must be visible in at least five places: background/texture, edges or borders, at least one illustration or ornament in SVG, the type, and the buttons/controls. A style that is only a palette is a fail.

Shared tools:
- Paper/grain texture: an inline SVG `<filter>` with `feTurbulence` (fractalNoise, baseFrequency 0.6 to 0.9, numOctaves 2 to 4) plus `feColorMatrix` to lower alpha, applied to a full-size absolutely positioned `<div>` with `pointer-events:none` and `mix-blend-mode:multiply` (light paper) or `screen` (dark).
- Rough edges: `filter: url(#rough)` with `feTurbulence` + `feDisplacementMap` (scale 2 to 6) on shapes, not on text.
- Torn paper: `clip-path: polygon(...)` with 20 to 40 irregular points along one edge.
- Hand-drawn wobble: SVG paths with slight irregularity, `stroke-linecap:round`, `stroke-linejoin:round`, and `filter:url(#rough)` at low scale.
- Halftone: `background-image: radial-gradient(circle, color 30%, transparent 32%)` with `background-size` 6 to 10px, optionally rotated via a pseudo-element with `transform:rotate(15deg)`.
- Misregistration: duplicate an element in `::before` / `::after` with `translate(2px,-1px)` in the second spot color and `mix-blend-mode:multiply`.
- Deboss/emboss: `text-shadow: 0 1px 0 rgba(255,255,255,.6), 0 -1px 0 rgba(0,0,0,.25)` on paper tones; `box-shadow: inset` pairs for pressed surfaces.
- Scanlines: `repeating-linear-gradient(0deg, rgba(0,0,0,.25) 0 1px, transparent 1px 3px)` overlay.
- Pixel: `image-rendering: pixelated`, SVG built from `<rect>` on an integer grid with `shape-rendering:crispEdges`, borders via `box-shadow` steps instead of `border-radius`.
- Isometric: build on a 2:1 grid; faces as three polygons with three tones (top light, left mid, right dark); use `transform: rotateX(60deg) rotateZ(45deg)` only for flat decorative grids, draw real objects as SVG polygons.
- Folded paper / low poly: adjacent triangles with lighter and darker fills of the same hue, crease lines at 1px with a slightly darker tone, a soft `drop-shadow` filter on the whole group.
- Lead lines (stained glass): SVG shapes with `stroke:#2a2320; stroke-width:6; stroke-linejoin:round`, fills as linear gradients with a lighter stop, overall `filter: drop-shadow`.
- Chalk: Google Fonts "Caveat", "Patrick Hand", "Gloria Hallelujah" or "Shadows Into Light"; text color #e8e4d8 at 85 to 95% opacity on #2b3a33 or #1f2a2a; a faint feTurbulence smudge overlay; SVG strokes with `stroke-dasharray` slightly irregular.
- Neon: `text-shadow` stacked 3 to 5 layers from tight white to wide saturated color; borders via `box-shadow: 0 0 4px color, 0 0 12px color, inset 0 0 4px color`; respect reduced motion for any flicker.
- Claymorphism: `border-radius: 24 to 40px`, `box-shadow: 8px 8px 16px rgba(0,0,0,.12), inset -6px -6px 12px rgba(0,0,0,.08), inset 6px 6px 12px rgba(255,255,255,.7)`, pastel fills, no 1px borders.

Style notes (what makes each one read as that style):
- watercolor: washes as large soft shapes with `filter: blur(18px)` behind content plus a sharper second layer at 60% opacity; edges darker than centers (radial-gradient with darker rim); paper grain on everything; type: a humanist serif or a light handwriting accent; buttons as painted blobs with a hand-drawn SVG outline.
- papercut: 4 to 6 stacked layers, each a polygon with `filter: drop-shadow(0 6px 10px rgba(0,0,0,.18))`, shadows get larger with depth; muted paper tones with one bright sheet; type set on its own "sheet"; no gradients inside a sheet.
- linocut: two colors only (ink + paper), thick irregular strokes, textured fills via hatching patterns (`<pattern>` of short lines), rough displacement on shapes; type: a heavy serif or a carved-looking display face (e.g. "Alfa Slab One", "Rye", "Ultra"); buttons as ink blocks with paper text.
- risograph: 2 to 3 spot colors (fluorescent pink #ff48b0, blue #0078bf, yellow #ffe800, green #00a95c, orange #ff6c2f) on off-white, multiply blend overlaps, grain, slight misregistration on headlines and shapes, flat illustration with no gradients.
- blueprint: background #0b3d91 to #1f4fa8 with a white 1px grid (`background-image` linear-gradients at 24px), all drawings as white strokes (`stroke:#fff; fill:none`), dimension lines with arrowheads via `<marker>`, labels in a monospace or drafting face ("Architects Daughter" sparingly), a title block in the corner.
- bauhaus: primary red, yellow, blue plus black and white, large circles/triangles/squares as composition, strict grid, geometric sans ("Jost", "Josefin Sans", "Outfit"), diagonal rules, no texture.
- swiss: 12-column grid shown via spacing, flush-left ragged-right, Helvetica-like ("Inter Tight" is acceptable here, "Archivo", "Instrument Sans"), black on white with one accent, big numerals, no rounded corners, no shadows, hairline rules.
- brutalist: system fonts (`font-family: Times, serif` or `monospace`), 2 to 4px black borders, default blue links, yellow highlight for hover, no border-radius, no shadows, raw layout with visible structure; still readable and responsive.
- pixel: "Press Start 2P" for headings only (it is huge), "Silkscreen" or "VT323" for body, 4px grid, stepped borders via box-shadow, SVG sprites from rects, dithering via checker pattern.
- terminal: #0c0c0c background, phosphor #33ff66 or #ffb000, "IBM Plex Mono" or "JetBrains Mono", box drawing characters for frames, a blinking block cursor (animation respecting reduced motion), scanlines overlay, slight `text-shadow` glow.
- artdeco: gold (#c9a227) on #0e1a14 or #111, symmetrical composition, sunburst (repeating-conic-gradient or SVG rays), chevrons and stepped forms, display face ("Poiret One", "Limelight", "Marcellus"), double rules, centered type.
- memphis: pastel + primary clash (#ff6f91, #ffd166, #06d6a0, #118ab2, #2b2d42), squiggles, zigzags, confetti and terrazzo as SVG patterns, thick black outlines on shapes, slightly rotated elements, chunky rounded sans ("Fredoka", "Baloo 2").
- chalkboard: see chalk tools; frames as hand-drawn rectangles, arrows and underlines drawn in SVG, one colored chalk (#f7d774 or #8fd3f4) as accent.
- collage: torn edges, tape strips (semi-transparent rotated rectangles with slight gradient), mixed fonts in headlines (serif + grotesk + typewriter, letters in spans with different rotation), photocopy noise, rotated stickers, off-white and black with one punk color.
- isometric: see isometric tools; scene in the hero as a single SVG with 10 to 20 objects; flat shading, no gradients; palette of 5 to 6 tones.
- inksketch: strokes #1c1a17 at 1.5 to 2.5px, cross-hatching patterns for shade, wobbly rectangles as frames (SVG `<rect>` replaced by a hand-drawn path), handwriting accents ("Kalam", "Caveat"), body in a readable serif.
- neon: see neon tools; dark purple (#1a0b2e) base, horizon grid in SVG with perspective lines, sunset gradient disc, "Orbitron" or "Audiowide" for display.
- ukiyoe: indigo #1f3a5f, vermilion #c8102e, washi off-white #f3eee4, flat stylized waves/clouds as SVG paths with repeating curls, thin outlines, seal-like red square stamps for labels, vertical text accents via `writing-mode: vertical-rl`, serif ("Noto Serif JP" or "Shippori Mincho").
- halftone: see halftone tools; 3 to 4px black outlines, speech bubbles as SVG with tails, "Bangers" for display, panel gutters, action lines as radial stripes.
- midcentury: mustard #d9a21b, teal #2a7f8f, walnut #6b4a2b, cream #f2e8d5; starbursts and boomerangs as SVG; "Lobster" or "Pacifico" for one script accent, "Josefin Sans" body; tapered shapes.
- letterpress: deboss text-shadow, cotton paper tone #efe9df with grain, ornaments (fleurons as SVG), hairline rules, "Playfair Display" / "Cormorant" / "Libre Caslon", restrained ink colors (#2f2a26, #8a2b2b).
- thermal: `max-width: 380px` column on a grey desk, "Courier Prime" or "Space Mono", dotted rules via `border-top: 2px dotted`, faded ink via slight opacity and a noise overlay, barcode as SVG rects, torn bottom edge via clip-path zigzag, print block that removes the desk.
- stainedglass: see lead-line tools; panels as window shapes (pointed arch), light-through gradients, deep jewel tones, dark lead between all shapes, "Cinzel" or "Uncial Antiqua" sparingly for display.
- origami: see folded paper tools; cranes/boats as faceted polygons, cards with a visible crease (two halves with slightly different lightness), paper tones.
- claymorphism: see clay tools; pastel (#ffd6e0, #c7e9ff, #d9f7d0, #fff3c4), chunky rounded buttons with a pressed `:active` state, soft illustration blobs.
