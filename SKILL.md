---
name: open_custom_visuals
description: Build Claude-style inline custom visuals in Open WebUI using Open-Custom Visuals. Use for diagrams, charts, timelines, architecture maps, CSV/data explainers, and side-by-side comparisons when a visual is materially clearer than prose.
---

# Open-Custom Visuals

Use this skill when the user explicitly asks for a chart, diagram, dashboard, flow, map, timeline, comparison, or visualization, and also when a visual would materially improve clarity for:

- processes and workflows
- systems and architecture
- change over time
- side-by-side decisions
- uploaded tabular data
- multi-part explanations with strong spatial or relational structure

Do **not** use a visual when the request is best served by short prose, direct debugging, or a simple factual answer.

## Claude parity

Treat each custom visual as a small web application built with HTML, CSS, SVG, and JavaScript.

- Do not approach the task as image generation, illustration, poster design, or “make a picture”.
- The output should be specific to the user’s exact question, with structure and controls that help inspection.
- Prefer interactive behavior when it materially improves understanding: toggles, tabs, filters, sliders, sorting, or click-to-drill-down.
- Keep the interface purposeful and restrained. Professional product UI is the target, not decorative art.

## Default workflow

1. Call `start_visual(title="...", goal="...")`.
2. Write one short lead-in sentence.
3. Emit exactly one plain-text block using:

```text
@@@OCV-START
...HTML or SVG fragment only...
@@@OCV-END
```

4. Write one short follow-up sentence about what the visual shows.

If the user wants compatibility over live rendering, or if you are likely to fail the streaming protocol, use:

`render_static_visual(title="...", html_code="...", goal="...")`

## Hard protocol rules

- The markers must be exactly `@@@OCV-START` and `@@@OCV-END`.
- Put each marker on its own line.
- Emit exactly one marker pair per `start_visual` call.
- Emit the **fragment only** between markers.
- Never emit `<!DOCTYPE>`, `<html>`, `<head>`, or `<body>` inside the block.
- Do not wrap the visual in Markdown code fences.
- Do not describe the raw HTML source to the user.

## Attached data

When the tool says tabular data is available, use:

- `window.OpenCustomVisuals.dataset`
- `window.OpenCustomVisuals.datasetSummary`

Expect canonical tables at:

- `window.OpenCustomVisuals.dataset.tables`

Each table usually includes:

- `name`
- `columns`
- `rows`
- `sample_rows`
- `row_count`
- `truncated`

Prefer:

- bar charts for categories
- line charts for trends over time
- scatter charts for two-variable relationships
- compact comparison cards for small decision tables

If a dataset is truncated, say so in your prose.

## Helper APIs inside the iframe

Available helpers:

- `sendPrompt(text)`
- `openLink(url)`
- `copyText(text)`
- `copyImage()`
- `downloadHTML()`
- `downloadSVG()`
- `enterFullscreen()`
- `saveState(key, value)`
- `loadState(key, fallback)`

`window.OpenCustomVisuals.helpers` also exposes these.

Use local JS for:

- tabs
- toggles
- sorting
- filtering
- sliders
- view switching

Use `sendPrompt(...)` for:

- drill-down into a node or step
- asking the model to compare branches
- requesting a deeper sub-diagram
- turning a clicked choice into a conversational follow-up

## Visual quality bar

The output must feel like a polished embedded product surface, not a screenshot.

Design rules:

- Use the injected CSS variables, not hardcoded theme colors.
- Prefer 2-3 semantic colors, not rainbow palettes.
- Keep labels concise.
- Minimum readable font size is 11px.
- Use sentence case.
- Avoid gradients, glows, heavy shadows, and emoji.
- Keep the first view clean; expose extra detail through controls or progressive disclosure.

SVG rules:

- Use `viewBox="0 0 680 H"` for custom SVG diagrams.
- Keep content inside the safe area.
- Use `dominant-baseline="central"` for vertically centered text.
- Use the injected classes `.t`, `.ts`, `.th`, `.box`, `.node`, `.arr`, `.leader`.
- Use ramp classes like `.c-blue`, `.c-teal`, `.c-amber`, `.c-red`.

HTML rules:

- Build responsive layouts that work at narrow chat widths.
- Wrap canvases in a fixed-height container.
- Read theme colors from CSS variables.
- Use `button.active` or clear state styling for selected controls.
- Prefer semantic UI structure over screenshot-like compositions.

## Chart.js / library usage

Chart.js is appropriate for most common charts. Example loader:

```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
```

Minimal pattern:

```html
<div style="position:relative;height:280px">
  <canvas id="chart"></canvas>
</div>
<script>
const s = getComputedStyle(document.documentElement);
const seriesColor = s.getPropertyValue('--ramp-teal-stroke').trim() || '#0F6E56';
new Chart(document.getElementById('chart').getContext('2d'), {
  type: 'bar',
  data: {
    labels: ['A','B','C'],
    datasets: [{
      label: 'Value',
      data: [12, 19, 7],
      backgroundColor: seriesColor,
      borderColor: seriesColor,
      borderRadius: 4,
      borderSkipped: false
    }]
  },
  options: {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: s.getPropertyValue('--color-text-secondary').trim() } }
    }
  }
});
</script>
```

Use D3 or Vega only when the chart shape is unusual enough to justify the extra complexity.

## Interaction patterns

Good:

- click a node to ask a specific follow-up with `sendPrompt`
- local toggle for “overview / detailed”
- slider that updates a formula or simulation in place
- comparison cards with a “go deeper” button

Bad:

- a static picture when the user asked to explore
- a poster-like illustration that could have been an image instead of a web-native visual
- sending vague prompts like `"Tell me more"`
- packing paragraphs of explanation inside the visual
- overusing animation

## Persistence guidance

Custom visuals are for inline thinking and exploration.

If the user clearly wants something persistent or shareable from the start, say that Open WebUI Artifacts are a better fit and offer to create an artifact instead of, or after, the inline visual.

## Example

```text
I mapped the flow so you can inspect each stage.

@@@OCV-START
<svg width="100%" viewBox="0 0 680 220">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </marker>
  </defs>
  <g class="node c-blue" onclick="sendPrompt('Explain the intake stage in more detail.')">
    <rect x="40" y="70" width="180" height="44" rx="8"/>
    <text class="th" x="130" y="92" text-anchor="middle" dominant-baseline="central">Intake</text>
  </g>
  <path class="arr" d="M220 92H310" marker-end="url(#arrow)"/>
  <g class="node c-teal" onclick="sendPrompt('Break down the validation stage and common failure cases.')">
    <rect x="310" y="70" width="180" height="44" rx="8"/>
    <text class="th" x="400" y="92" text-anchor="middle" dominant-baseline="central">Validation</text>
  </g>
  <path class="arr" d="M490 92H580" marker-end="url(#arrow)"/>
  <g class="node c-amber" onclick="sendPrompt('What happens after routing, and what are the tradeoffs?')">
    <rect x="580" y="70" width="60" height="44" rx="8"/>
    <text class="th" x="610" y="92" text-anchor="middle" dominant-baseline="central">Route</text>
  </g>
</svg>
@@@OCV-END

Each stage is clickable if you want a deeper explanation.
```

## Common failure cases

- Missing one of the OCV markers.
- Emitting document wrapper tags inside the fragment.
- Using hardcoded colors that break dark mode.
- Creating a canvas with no explicit height.
- Making a diagram wider than the chat column.
- Using `sendPrompt` text that is too vague to be useful.
