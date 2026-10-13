---
name: data-viz
description: Rules for charts and dashboards that are honest and readable
triggers: chart, charts, graph, plot, diagram, visualization, visualisation, dashboard, histogram, heatmap, diagramm, grafik
---
# Charts

- **Pick the form from the question**: change over time → line; compare categories → horizontal bars sorted by value; parts of a whole (few parts) → stacked bar or a single number, rarely a pie; relationship of two numbers → scatter; distribution → histogram.
- **Honest axes**: bars start at zero; lines may not. Label units. Do not use dual axes.
- **Less ink**: no 3D, no gradients, no gridlines heavier than the data; direct labels instead of legends where possible.
- **Color**: one color for one series; use a sequential palette for magnitude, a diverging one around a meaningful midpoint; at most ~6 categorical hues; never rely on red/green alone. Check contrast.
- **One message per chart**: a title that states the finding ("Revenue doubled after March"), not just the topic.
- **Interaction**: tooltips with exact values, keyboard focus for marks, readable at 390px width.
- Small data: draw with inline SVG or canvas (no library). Always show the real numbers somewhere (table or labels).
