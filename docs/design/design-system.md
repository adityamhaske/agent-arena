# Design system

`agent_arena/web/static/app.css` — hand-written CSS with no build step
(invariant 2). Light is the default; dark is a token swap under
`prefers-color-scheme`, plus an explicit `[data-theme]` so the in-app toggle
beats the OS in both directions.

The palette follows the AWS console: a light neutral page, white containers,
console blue for action, and a single dark navy rail. Amazon orange is present
but rationed — it marks progress and nothing else, because an accent that
appears everywhere stops meaning anything.

## Colour tokens

Defined on `:root`, redefined under `@media (prefers-color-scheme: dark)`.

| Token | Light | Dark | Role |
|---|---|---|---|
| `--bg` | `#f6f7f9` | `#101317` | Page ground |
| `--surface` | `#ffffff` | `#171b21` | Cards, panels, table rows |
| `--border` | `#dfe3e8` | `#2a313a` | Default rules |
| `--border-strong` | `#c3cad3` | `#3b444f` | Emphasised edges |
| `--text` | `#16191d` | `#e8ecf1` | Body |
| `--text-dim` | `#5b6572` | `#a3adba` | Secondary |
| `--text-faint` | `#8b95a3` | `#78828f` | Tertiary, captions |
| `--accent` | `#2b5cdb` | `#6c9bff` | Primary actions, links |
| `--accent-soft` | `#e8eefc` | `#1b2740` | Accent backgrounds |

### Semantic colours

Separate from the accent, and paired so text and background always come from the
same set:

| Token | Light | Dark | Means |
|---|---|---|---|
| `--good` / `--good-soft` | `#147a45` / `#e3f5ec` | `#4ec98a` / `#14301f` | Passed, ranked, healthy |
| `--warn` / `--warn-soft` | `#9a6400` / `#fdf2dc` | `#e0ac4b` / `#302512` | Resolution warnings, near a limit |
| `--bad` / `--bad-soft` | `#b3261e` / `#fdeceb` | `#ff8a80` / `#331b19` | Errors, `DISQUALIFIED` |

The dark values are re-chosen rather than inverted. `--bad` goes from a deep red
to a light coral because a saturated red on a dark ground reads as a glow rather
than as text.

**Colour is never the only signal.** A `DISQUALIFIED` row carries the word
`DISQUALIFIED` and its reason. See [accessibility.md](accessibility.md).

## Type

| Token | Stack |
|---|---|
| `--sans` | `system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif` |
| `--mono` | `ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace` |

System fonts only — no webfont, because there is no CDN to load one from and
inlining a face would bloat a page served off a local socket. The mono stack
carries model ids, run ids, and any column where digits should align.

## Surface tokens

| Token | Value |
|---|---|
| `--radius` | `10px` |
| `--shadow` | `0 1px 2px rgba(16,24,40,.05), 0 4px 14px rgba(16,24,40,.05)` |

The dark shadow is re-specified at higher opacity, since a light shadow is
invisible on a dark ground.

## Responsive

One breakpoint, at `max-width: 760px`. Below it the layout goes single-column and
the topbar wraps. There is no tablet tier — the UI is a form and a table, and
those two states cover it.

Wide content scrolls inside its own container rather than the page.

## Motion

```css
@media (prefers-reduced-motion: reduce) { /* transitions removed */ }
```

Motion in this UI is functional only — progress, and state transitions on
buttons. There is nothing decorative to disable.

## Working within it

- **Use the tokens.** A literal hex in a rule will be wrong in one of the two
  themes. Every colour must come from the same token set as the surface behind it.
- **Never define a colour only inside the dark block.** It then has no light
  value and renders one theme's text on the other theme's ground.
- **No build step.** No preprocessor, no PostCSS, no utility framework. If a
  pattern repeats, add a class.
- **Progressive enhancement.** The page must lay out correctly with JavaScript
  blocked; `app.js` adds interactivity, not structure.

## Planned

The v2 design calls for a sidenav shell, a command palette, and a denser
information design for tables and per-case grids. That work is specified in the
v2 plan and not started. If it lands as the approved React bundle, this token set
is the input to its theme — the palette is the part worth carrying forward.
