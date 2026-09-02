# Docs Site Modern Minimalist Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the Agent Arena docs site into a modern, consistent, minimalist, and fully responsive documentation experience with all unwanted marketing clutter removed.

**Architecture:** Update HTML templates (`home.html`, `page.html`), modern design tokens and component styling in `style.css`, and drawer interaction handling in `site.js`. Zero external runtime or build dependencies.

**Tech Stack:** HTML5, Vanilla CSS3, Vanilla ES6 JavaScript, Python 3 static site generator (`site/build.py`).

## Global Constraints

- Zero new runtime or build dependencies (engine is stdlib-only, site is vanilla CSS/JS).
- Single `<h1>` per page.
- Progressive enhancement only: site must be completely readable and lay out correctly even if JavaScript is disabled or blocked.
- Responsive containment: no horizontal scroll on mobile viewports (360px+).
- Every internal link must pass `python3 site/check_links.py`.
- Full test suite `pytest -q` must remain 100% green.

---

### Task 1: Streamline and Prune Landing Page (`site/templates/home.html`)

**Files:**
- Modify: `site/templates/home.html`

**Interfaces:**
- Consumes: Template variables (`{{base}}`, `{{repo}}`, `{{site_title}}`, `{{page_title}}`, `{{description}}`, `{{canonical}}`, `{{image}}`, `{{jsonld}}`).
- Produces: Clean, minimalist HTML for the landing page without `.stat-row`, without "Not just for developers", with a modern hero and aligned topbar/footer.

- [ ] **Step 1: Unify topbar and remove hamburger mismatch**
Update the topbar in `site/templates/home.html` so it includes the nav toggle button matching `page.html`:
```html
<header class="topbar">
  <div class="topbar-inner">
    <a class="brand" href="{{base}}/"><span class="brand-mark" aria-hidden="true"></span>{{site_title}}</a>
    <nav class="top-links">
      <a href="{{base}}/guide/">Guide</a>
      <a href="{{base}}/study/">Study</a>
      <a href="{{base}}/releases/">Releases</a>
      <a href="{{base}}/roadmap/">Roadmap</a>
      <a href="{{repo}}">GitHub</a>
    </nav>
    <button class="icon-btn nav-toggle" type="button" data-nav-toggle aria-expanded="false" aria-label="Toggle navigation">☰</button>
    <button class="icon-btn" type="button" data-theme-toggle aria-label="Switch colour theme" title="Switch colour theme">◐</button>
  </div>
</header>
```

- [ ] **Step 2: Prune unwanted marketing sections**
Remove:
1. The `.stat-row` section (lines with `1 runtime dependency`, `10 built-in scorers`, etc.).
2. The entire section "Not just for developers" (`<section class="section">... The people who set the budget do not write YAML ...</section>`).
3. Streamline "Why this" and "Two systems" into punchy, high-signal cards.

- [ ] **Step 3: Unify footer**
Match `page.html`'s footer structure cleanly:
```html
<footer class="footer">
  <div class="wrap footer-inner">
    <span>Agent Arena — MIT licensed.</span>
    <a href="{{repo}}">Source</a>
    <a href="{{base}}/guide/">Docs</a>
    <a href="https://adityamhaske.github.io/">More projects</a>
    <span class="spacer"></span>
    <span>Built by <a href="https://github.com/adityamhaske">Aditya Mhaske</a></span>
  </div>
</footer>
```

- [ ] **Step 4: Verify build with python3 site/build.py**
Run: `python3 site/build.py`
Expected: `Built 22 pages into site/_build (base=/)`

- [ ] **Step 5: Commit changes**
```bash
git add site/templates/home.html
git commit -m "refactor(site): prune unwanted marketing sections from landing page"
```

---

### Task 2: Refine Documentation Shell (`site/templates/page.html`)

**Files:**
- Modify: `site/templates/page.html`

**Interfaces:**
- Consumes: Template variables (`{{nav}}`, `{{crumbs}}`, `{{title}}`, `{{blurb}}`, `{{content}}`, `{{source}}`, `{{source_url}}`, `{{pager}}`, `{{toc}}`, `{{toc_class}}`).
- Produces: Accessible, clean documentation layout with backdrop container for mobile drawer navigation.

- [ ] **Step 1: Add mobile drawer backdrop container**
Insert `<div class="nav-backdrop" id="nav-backdrop" aria-hidden="true"></div>` before `<div class="shell">`.

- [ ] **Step 2: Unify topbar links & footer**
Ensure topbar navigation links match `home.html` perfectly and footer includes the same author credit.

- [ ] **Step 3: Refine doc-foot layout**
Streamline the `.edit-link` notice to a minimalist source indicator:
```html
<p class="edit-link">Source: <a href="{{source_url}}"><code>{{source}}</code></a></p>
```

- [ ] **Step 4: Verify build & links**
Run: `python3 site/build.py && python3 site/check_links.py`
Expected: 0 errors, 0 broken links.

- [ ] **Step 5: Commit changes**
```bash
git add site/templates/page.html
git commit -m "refactor(site): refine documentation page shell and add drawer backdrop"
```

---

### Task 3: Modernize Design System & Responsive CSS (`site/assets/style.css`)

**Files:**
- Modify: `site/assets/style.css`

**Interfaces:**
- Consumes: CSS variables and class selectors used across `home.html`, `page.html`, and generated Markdown.
- Produces: Modern zinc color tokens, smooth border radius (`6-14px`), subtle elevation, clean typography, off-canvas mobile drawer, and responsive layouts across all device widths.

- [ ] **Step 1: Update design tokens for light and dark modes**
Replace harsh greys with clean zinc neutrals and modern border radii:
```css
:root {
  --ground: #fafafa;
  --surface: #ffffff;
  --surface-2: #f4f4f5;
  --surface-3: #e4e4e7;

  --ink: #09090b;
  --ink-2: #52525b;
  --ink-3: #71717a;

  --line: #e4e4e7;
  --line-strong: #d4d4d8;

  --accent: #3b66f5;
  --accent-ink: #2548c7;
  --accent-soft: #eff3ff;
  --accent-line: #c7d6fc;
  --on-accent: #ffffff;

  --radius-sm: 6px;
  --radius: 10px;
  --radius-lg: 14px;
  --radius-full: 9999px;

  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
  --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.06);
  --shadow-lg: 0 12px 28px -6px rgba(0, 0, 0, 0.1);
  ...
}
```
And mirror in `@media (prefers-color-scheme: dark)` and `:root[data-theme="dark"]`.

- [ ] **Step 2: Apply modern radii, subtle elevation, and hover transitions**
Update `.btn`, `.card`, `.panel`, `.term`, `.pager`, `pre`, and `:not(pre) > code` to use `--radius-sm` and `--radius`. Add smooth `translateY(-2px)` and shadow micro-transitions to interactive cards.

- [ ] **Step 3: Implement off-canvas mobile navigation drawer**
Update `.sidebar` on mobile (`@media (max-width: 820px)`):
- Fixed position, off-canvas (`left: 0; top: 0; bottom: 0; width: min(300px, 80vw); transform: translateX(-100%); transition: transform 0.24s cubic-bezier(0.16, 1, 0.3, 1); z-index: 60;`).
- When open: `transform: translateX(0);`.
- Backdrop `.nav-backdrop`: `position: fixed; inset: 0; background: rgba(0, 0, 0, 0.45); backdrop-filter: blur(2px); z-index: 50; opacity: 0; pointer-events: none; transition: opacity 0.2s;`.
- When drawer is open: `.nav-backdrop.open { opacity: 1; pointer-events: auto; }`.

- [ ] **Step 4: Verify responsive containment and typography scaling**
Ensure all screen widths from 360px to 2560px lay out gracefully without overflow.

- [ ] **Step 5: Verify build & links**
Run: `python3 site/build.py && python3 site/check_links.py`

- [ ] **Step 6: Commit changes**
```bash
git add site/assets/style.css
git commit -m "style(site): modernize design system, border radii, and responsive drawer navigation"
```

---

### Task 4: Enhance Mobile Drawer JavaScript (`site/assets/site.js`)

**Files:**
- Modify: `site/assets/site.js`

**Interfaces:**
- Consumes: `[data-nav-toggle]`, `#sidebar`, `#nav-backdrop`.
- Produces: Smooth mobile navigation with backdrop click-to-close, ESC key dismiss, and body scroll lock.

- [ ] **Step 1: Enhance mobileNav function**
Bind event listeners:
- Toggle click toggles `.open` on `#sidebar` and `#nav-backdrop`, updates `aria-expanded`, and toggles `overflow: hidden` on `document.body`.
- Click on `#nav-backdrop` closes drawer.
- Pressing `Escape` closes drawer.
- Clicking any link inside `#sidebar` closes drawer and unlocks scroll.

- [ ] **Step 2: Test script in build**
Run: `python3 site/build.py`

- [ ] **Step 3: Commit changes**
```bash
git add site/assets/site.js
git commit -m "feat(site): enhance mobile drawer interaction with backdrop dismiss and scroll lock"
```

---

### Task 5: End-to-End Verification

**Files:**
- Test suite and site verification

- [ ] **Step 1: Run site build and link check**
Run: `python3 site/build.py && python3 site/check_links.py`
Expected: 0 broken links across all 22+ pages.

- [ ] **Step 2: Run offline test suite**
Run: `pytest -q`
Expected: All tests pass cleanly.

- [ ] **Step 3: Visual inspection via browser subagent**
Serve site locally with `python3 -m http.server 8000 --directory site/_build` and inspect:
- Homepage at desktop (1280px) and mobile (375px)
- Documentation page at desktop (1280px), tablet (768px), and mobile (375px)
- Dark and light mode toggle.

- [ ] **Step 4: Final commit and summary**
Commit any polish and update walkthrough.
