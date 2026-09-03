# Accessibility

## What the shipped UI does

| Practice | Where |
|---|---|
| Semantic HTML — real `<header>`, `<nav>`, `<main>`, `<table>`, `<button>` | `index.html`, `app.js` |
| `aria-live="polite"` on the main region | `index.html`, so route changes and results are announced |
| `role="status"` on the toast | `index.html` |
| `role="img"` with a label on the trend sparkline | `app.js` |
| `prefers-reduced-motion` honoured | `app.css` |
| `prefers-color-scheme` honoured, with a re-chosen dark palette | `app.css` |
| Responsive to 320 px without horizontal scroll | `app.css` |
| Status shown as a **word**, not only a colour | `DISQUALIFIED`, `ranked`, `no_data` |

That last one is the most important and the easiest to lose. A leaderboard where
disqualification is signalled by a red row is unreadable to a red-green colour
blind user — roughly 8% of men. The word is the signal; the colour reinforces it.

## The bar for new work

### Keyboard

- Every interactive element reachable by <kbd>Tab</kbd> in a sensible order.
- Visible focus on everything focusable. Never `outline: none` without a
  replacement.
- <kbd>Esc</kbd> closes any dialog; focus returns to what opened it.
- No keyboard trap.

Use a `<button>` for actions and an `<a>` for navigation. A `<div>` with a click
handler is invisible to a keyboard and to a screen reader, and it is the single
most common accessibility failure in a hand-written UI.

### Screen readers

- Every control has an accessible name. An icon-only button needs `aria-label`.
- Announce asynchronous results through the existing `aria-live` region rather
  than adding new ones — competing live regions interrupt each other.
- Tables use `<th>` with the right `scope`. The leaderboard is a real data table.
- Decorative marks carry `aria-hidden="true"` — the `◆` in the brand already does.

### Colour and contrast

- Body text at 4.5:1 minimum, large text at 3:1.
- Never encode meaning in colour alone. Pair it with a word, an icon, or a shape.
- Verify both themes. A pair that passes on white can fail on `#101317`.

### Motion

- Respect `prefers-reduced-motion`.
- Nothing auto-plays; nothing flashes more than three times a second.

### Forms

- A real `<label>` for every input, associated by `for`/`id`.
- Errors adjacent to the field, referenced with `aria-describedby`, and never
  signalled by a red border alone.
- The wizard's five steps announce position: "Step 3 of 5".

## Checking it

```bash
arena ui
```

Then, without a mouse:

1. <kbd>Tab</kbd> through a whole page. Can you see where you are, always?
2. Complete the wizard end to end using only the keyboard.
3. Force dark mode at the OS level and re-read every screen.
4. Narrow to 320 px. Nothing should scroll sideways.
5. Turn on VoiceOver or NVDA and start a run. Is the result announced?
6. Block JavaScript. The page must still render its structure — the UI is meant
   to be progressive enhancement, not a blank div.

There is no automated accessibility check in CI. Adding one (axe-core in a
Playwright run) would need a dev-only dependency, which is allowed under the
dependency policy for test tooling but has not been done. It is on the list in
[../roadmap/future-updates.md](../roadmap/future-updates.md).
