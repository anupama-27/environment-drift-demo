# DriftAudit design system

For engineers adding views to the workbench. The look is a calibration bench: flat signal colours, DIN-style
lettering, tables first. A live reference of every component is at `tests/e2e/styleguide.html` (serve the repository
root and open it; it is not linked from the site).

## Files and layers

`assets/css/tokens.css` (fonts, custom properties), `base.css` (reset, elements, text styles, layout helpers),
`components.css`, `views.css` (shell, run bar, Summary). The four files declare the cascade layers
`reset, base, components, views`. A later layer wins whatever the selector specificity, so put view rules inside
`@layer views { ... }` in `views.css`, as plain single-class selectors named after the view (`.rounds__detail`).
Do not restyle a component class from a view; add a class of your own next to it.

Markup carries no `style` attributes and no inline handlers. Geometry that depends on data is set by `DA.ui.bind`.

## Tokens

Colours (`var(--name)`), with the contrast of the pairs in use:

| Token | Value | Use | Contrast |
|---|---|---|---|
| `--paper` | #FFFFFF | content background | |
| `--bench` | #F1F3F4 | panels that group controls, table heads | ink 15.84, graphite 5.56 |
| `--bench-2` | #E6EAED | hover, selected row, "both right" cells | ink 14.57, graphite 5.11 |
| `--ink` | #16191D | text, selected controls, rules that matter | on paper 17.63 |
| `--graphite` | #5A626B | secondary text, control borders | on paper 6.19 |
| `--steel` | #7C8894 | rerun marks, disabled text. Never small text | on paper 3.62, on bench 3.25, on bench-2 2.99 (avoid) |
| `--rule` | #D5D9DD | hairlines only | 1.42 |
| `--signal-blue` / `-tint` | #00539F / #E3EEF8 | stored reading, links, primary button, focus ring | on paper 7.67, on tint 6.52 |
| `--signal-yellow` / `-tint` | #F2A900 / #FDF3D6 | stale reference, environment changed | ink on yellow 8.78, ink on tint 15.93 |
| `--signal-red` / `-tint` | #B3261E / #FBE9E7 | false accept, false reject, errors | on paper 6.54, on tint 5.58 |

Yellow is a fill with ink text on it and an ink keyline round it (yellow on paper is 2.01). It is never a text colour.
In the plate, "candidate only" (blue) and "reference only" (ink) differ by lightness only (2.30); the legend and the
reading line carry the meaning in words.

Type: `--font-sans` Barlow 400/500/600 for UI and prose; `--font-cond` Barlow Semi Condensed 500/600 for headings,
table heads, chart labels, tags; `--font-mono` IBM Plex Mono 400/500 for literal strings only (fingerprints, hashes,
commands). The fonts have no arrows and no less-or-equal signs: write "to". U+2212 (minus), the plus-minus sign and
the non-breaking space are available.

Space: `--space-05` 4px, `--space-1` 8, `--space-15` 12, `--space-2` 16, `--space-3` 24, `--space-4` 32, `--space-6` 48,
`--space-8` 64. Layout: `--content` 1240px, `--gutter` 32/24/16px, `--col-gap` 24px, `--measure` 68ch.
Radii: `--radius` 3px and `--radius-s` 2px, on controls only. A border goes all the way round or is absent.

## Text styles

Elements: `h1` 24/32, `h2` 18/24, `h3` 16/24, `h4` 14/20, all Semi Condensed 600; body 16/24. Classes for when element
and look differ: `.t-display` (40/44, the verdict size; 32 below 900px, 27 below 600px), `.t-title`, `.t-heading`,
`.t-label`, `.t-body`, `.t-small` (14/20), `.t-micro` (12/16), `.t-mono`. Helpers: `.num` (tabular figures; tables,
readouts and charts have them already), `.muted` (graphite), `.nowrap`, `.visually-hidden`.
Give every view one `h1` (Summary uses `<h1 class="verdict">`) and `h2` for its sections.

## Layout

`.wrap` centres content at 1240px with the gutters (the frame already wraps your view in one). `.grid` is 12 columns;
children take `.span-3 .span-4 .span-5 .span-6 .span-7 .span-8 .span-9 .span-12` and all become full width at 1000px.
`.stack` spaces children 16px apart (`.stack--1` 8, `--3` 24, `--4` 32, `--6` 48). `.cluster` is a wrapping row with
gaps. `.measure` limits a paragraph to 68 characters. Bench grey is for panels that hold controls; content sits on
white. Wide tables scroll inside `.ledger-wrap`; nothing else may make the page scroll sideways (check at 360px).

## Writing a view

```js
DA.views.rounds = {
  id: "rounds", title: "Rounds",
  render: function (ctx) { return DA.ui.html`<h1>Rounds</h1>${DA.ui.ledger({ ... })}`; },
  bind: function (rootEl, ctx) { DA.ui.on(rootEl, "cell", function (detail) { ... }); }
};
```

Add its `<script>` tag to `index.html` in the order of `contracts-web.md` section 1 (before `boot.js`). The tab and the
route already exist. `render` must return `DA.ui.html` markup; a plain string is refused. It runs on every state
change, and `bind` runs after every render with a fresh root element, so listeners added to `rootEl` do not pile up.
The frame has already called `DA.ui.bind` on it.

`ctx`: `state` (the store's value), `route`, `mode` (`"run"` or `"study"`, the latter when all runs are selected),
`run` (the loaded v1 run log, null in a study), `runs` (loaded run logs of the group), `audit`, `study`, `policyId`,
`policy` (`audit.policies[policyId]` or null), `round` (selected round or null). The frame only calls a workbench view
when `audit` exists (run mode) or `study` exists (study mode); `study` can still be null in run mode while the other
runs load.

Keys and focus: `DA.ui.mount` keeps focus, scroll offsets and open disclosures for elements whose `data-key` is the
same before and after. Give every control that changes state a stable `data-key`. The components do this themselves.

Hooks handled by the frame, usable on any element: `data-pick-round="5"` selects a round, `data-clear-round` clears
it, `data-pick-policy="frozen"` selects a policy, `data-pick-run="<entry id>"` selects a run of the current group.
A `DA.ui.policySwitcher` needs no wiring. To change anything else call `DA.state.set({ options: { ... } })`; the
audit and the study are recomputed inside the same update.

## DA.ui

Escaping: `` html`<p>${value}</p>` `` escapes every interpolation. Results of `html`, of components and of `raw()` pass
through unescaped; arrays are joined; `null`, `undefined`, `true`, `false` print nothing. Never call `.join("")` on a
list of fragments (that makes a plain string, which is then escaped): interpolate the array, or use
`join(parts, ", ")`. `raw(str)` is for markup you wrote yourself, never for anything from a run log.
`attrs({ class: c, disabled: flag, "data-x": v })` writes attributes, leaving out null and false.
`mount(el, markup)` replaces the content of `el`. `bind(rootEl)` wires the components inside it.
`on(rootEl, name, fn)` listens for a component event and calls `fn(detail, event)`.

Events (bubbling `CustomEvent`s named `da:<name>`): `select` `{ name, value }` from segmented controls and button
tabs; `round` `{ round }` (number or null) from the ruler; `cell` `{ index, stored, rerun, which }` from the plate;
`dim` `{ on }` from the plate's checkbox; `dismiss` `{ name }` from a notice.

`fmt`: `int(4411)` "4,411"; `num(x, digits)`; `pct(0.708)` "70.8%" (takes a fraction); `pp(1.3125)` "+1.31",
`pp(-0.5875)` "−0.59" with U+2212 (takes percentage points; third argument `true` appends " pp");
`ppOf(0.015)` "+1.50" (takes a fraction, as the engine returns `inflation`); `count(4, 8)` "4 of 8";
`plural(2, "win")`, `plural(2, "loss", "losses")`; `list(["a", "b", "c"])` "a, b and c"; `rounds([4, 5, 6, 8])`
"4 to 6, 8"; `interval(lo, hi)` "+0.65 to +1.98"; `meanSd(70.8, 2.0, 1)` "70.8 ± 2.0"; `policy(id, k)` gives Frozen,
Stored incumbent, Per-batch, Environment-triggered, Every 3 rounds, As run; `policyPhrase(id, k)` "the frozen policy";
`cause(id)` "stale reference", "would have been accepted anyway", "no environment change"; `causeSentence(id)`;
`source(s)`; `prompt(run, id)` "p3" (uses `DA.schema.promptLabel` when present).

Components, each returning markup:

| Function | Notes and example |
|---|---|
| `tag(text, kind)` | kind: none, `"quiet"`, `"info"`, `"warning"`, `"error"`. `ui.tag("false accept", "error")` |
| `sourceTag(source)` | "measured", or a yellow "synthetic". Put it wherever a run is named. |
| `mark(kind)` | decision mark: `"improved"`, `"false-accept"`, `"false-reject"`, `"rejected"`. `markOf(decision)` gives the kind. |
| `legend(items)` | `[{ mark: "improved", label }, { swatch: "stored", label }]`. Swatches: `stored win rerun loss both neither stale changed band band-plain line line-steel`. |
| `readouts(items)` | one ruled strip. `[{ label, value, unit, note, state }]`, state `"alert"` (red value) or `"empty"`. |
| `notice({ kind, title, body, actions, dismiss, key })` | kind `"info" "warning" "error" "quiet"`. Say what failed and what to do. `dismiss: true` adds the button. |
| `ledger({ columns, rows, key, caption, empty, dense, rowClass, rowAttrs, label })` | columns: `{ label, key }` or `{ label, cell(row, i) }`, plus `num` (right aligned), `mono`, `tight`, `head` (row header), `className(row)`. Row classes: `is-selected`, `is-stale`, `is-error`. Cell classes: `is-changed` (yellow tint), `is-alert` (red figure). Class `.empty` is the empty-state box outside tables. |
| `kv(rows)` | `[{ key, value, mono, copy }]`, `copy: true` adds a copy button. |
| `copyable(text, { label, done, key, ariaLabel })` | a literal string with a copy button. `copyButton({ text, label, done, key })` is the button alone. |
| `code(text, { label, done })` | `ui.code("driftaudit audit run.json", { label: "Copy command", done: "Command copied" })` |
| `disclosure({ summary, body, open, key })` | a `<details>`; give it a key so it stays open across renders. |
| `segmented({ name, label, value, options })` | options `[{ value, label, unavailable, disabled, title }]`; emits `select`. |
| `policySwitcher(policies, selectedId)` | pass `audit.policies` or `study.policies`. Shows the four replayed policies, "As run" when available, and the selected one. |
| `tabs({ name, label, value, items, plain })` | items `[{ id, label, href }]`. With `href` it is navigation (`aria-current`); without, buttons that emit `select`. `plain: true` inside a view. |
| `select({ name, label, value, options, key })` | a labelled native select; listen for `change` yourself. |
| `ruler(model)` and `rulerModel(audit, policyId, selectedRound)` | the frame draws the ruler in the run bar; you rarely need it. `rulerLegend()` is its legend. `reading(decision, roundRow, envNames)` is the sentence for one decision; `envNames(audit)` maps id to name. |
| `plate({ cells, key, itemLabel, dim, storedTitle, rerunTitle })` | `cells` is `DA.engine.itemCells(run, decision)`. Emits `cell` on click, Enter or Space. `itemLabel(i)` names an item (default "Item 12"). |
| `dropOverlay()`, `toast(message, { kind, timeout })`, `announce(message)` | the frame owns the overlay. `ui.toast("Opened my-run.json.")`; kind `"error"` stays until dismissed. |

Controls without a function: `<button class="btn">`, `.btn--primary` (one per screen at most), `.btn--small`,
`<button class="linklike">`, `<label class="check"><input type="checkbox"> ...</label>`, `<input class="input">`,
`<textarea class="textarea">`, `<label class="field"><span class="field__label">Margin</span>...</label>`
(`.field--stack` puts the label above). Button text says what happens: "Open run log", "Copy command".

## DA.charts

Each builder returns a `<figure class="chart">` with a legend, the drawing at two widths (a container query shows the
one that fits), and a visually hidden table with the numbers. The `<svg>` has `role="img"` and an `aria-label` that
states the numbers. Options for all: `width` (draw once at that width), `legend: false`, `caption`.

- `netGain(data, opts)`; `netGainData(audit, policyId, selectedRound)` builds `data`:
  `{ rounds: [{ round, env, stored, rerun, mark }], flags: [{ round, name }], first, selected }`, values in pp.
  `DA.charts.netGain(DA.charts.netGainData(ctx.audit, ctx.policyId, ctx.round))`
- `intervals(rows, { unit, caption })`, rows `[{ label, mean, lo, hi, values }]`. The dot is filled when the interval
  excludes zero. `study.probe.by_env[e]` maps to `{ label, mean, lo, hi, values: per_run }`.
- `ageLines(series, { xLabel, unit, caption })`, series `[{ label, plain, points: [{ x, mean, lo, hi }] }]`. Mark the
  control series `plain: true` (steel, hollow). `study.age.by_env[e]` maps point by point (`x: age`).
- `bars(rows, { max, format, caption })`, rows `[{ label, value, sd, tone, text }]`, tone `"blue" "steel" "red"`.

## State, routes, runs

`DA.state.get()`, `set(patch)` (shallow merge, subscribers told once per tick), `subscribe(fn)`. Shape as in
`contracts-web.md` section 3; `error` is `{ title, message }`. `DA.router.href({ page: "workbench", view: "rounds" })`
gives `"#/workbench/rounds"`; `DA.router.go(route)` navigates.
`DA.library.run()`, `.runs()`, `.group()`, `.select(groupId, runId)` (`"*"` for all runs), `.openFiles(fileList)`,
`.sidecar(entryId)` (the `.outputs.jsonl` file dropped beside a run log, for `DA.outputs`).

## Do not

All-caps labels, a small label above a heading, meta strings joined with middle dots, arrows on links or buttons, one
accented word in a headline, emoji, icon fonts, gradients, shadows, blur, rounded cards, a border on one side only
(table row rules are fine), green, exclamation marks, mono for anything that is not a literal string, hype words.
Sentence case everywhere. Never state a number the audit did not produce, and tag synthetic runs wherever they are
named. No motion except the plate settling in; nothing moves under `prefers-reduced-motion`.

## Not finished

No print stylesheet yet. The styleguide shows each component once, not every state. The favicon is a first version.
