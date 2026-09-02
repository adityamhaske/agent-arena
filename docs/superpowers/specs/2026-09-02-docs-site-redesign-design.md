# Design Specification: Docs Site Modern Minimalist Redesign

**Date:** 2026-09-02  
**Topic:** Modern, Consistent, and Minimalist Documentation Site UI  
**Status:** Approved

## 1. Goal & Principles

Transform the Agent Arena documentation site (`https://adityamhaske.github.io/agent-arena`) into a sleek, modern, consistent, and minimalist developer portal optimized for all viewport sizes (mobile, tablet, desktop, ultra-wide) while ruthlessly pruning redundant marketing fluff and unwanted information.

### Guiding Principles

1. **Minimalist & High-Signal**: Delete bloated marketing sections, stat cards, and repetitive bullet points. Keep high-signal technical content.
2. **Modern Visual Polish**: Soft rounded corners (`6-14px`), subtle hairline borders, glassmorphic header, refined zinc palette, and subtle micro-interactions.
3. **Consistent UI**: Identical topbar, branding, navigation, and footer across both the landing page (`home.html`) and documentation pages (`page.html`).
4. **Fluid Responsiveness**: Seamless experience on 360px phones up to 4K displays. Replace static accordion toggle with a smooth off-canvas navigation drawer and backdrop overlay.
5. **Zero External Dependencies**: Maintain the repository invariant — 100% vanilla CSS and progressive vanilla JS with zero npm, build tools, or runtime web frameworks.

---

## 2. Content Pruning & Information Architecture

### Homepage (`site/templates/home.html`)

- **Remove**:
  - The 5-metric `.stat-row` (`1 runtime dependency`, `10 built-in scorers`, `282 tests`, `4 example projects`, `$0 to try it offline`).
  - The verbose "Not just for developers" section containing the blockquote and repetitive feature list.
  - Redundant explanatory text in "Why this" and "The finding" that duplicates the Universal Arena guide.
- **Keep & Refine**:
  - **Hero**: Crisp headline, lede, primary action buttons (`Read the guide`, `GitHub`), copyable install snippet (`pip install agent-arena`), and a refined terminal simulation card.
  - **Why this**: 3 clear value-prop cards ("You define what 'best' means", "Unusable models are disqualified", "Admits when it cannot tell").
  - **Two systems, one repository**: Clear comparison between Universal Arena (varying models) and Multi-agent handoff study (varying coordination).
  - **Quickstart**: Fast CLI commands to evaluate immediately offline.
  - **Documentation Hub**: Clean grid of cards linking directly to the Guide, Study, Demo Walkthrough, Sample Report, Roadmap, and Decisions.

### Documentation Shell (`site/templates/page.html`)

- Clean up doc header with streamlined breadcrumbs, document title, and concise blurb.
- Add `#nav-backdrop` overlay container for mobile drawer navigation.
- Simplify the document footer with a minimalist source link and previous/next navigation cards.

---

## 3. Design System & Styling (`site/assets/style.css`)

### Color Tokens & Palette

- **Light Mode**:
  - `--ground`: `#fafafa`
  - `--surface`: `#ffffff`
  - `--surface-2`: `#f4f4f5`
  - `--surface-3`: `#e4e4e7`
  - `--ink`: `#09090b`
  - `--ink-2`: `#52525b`
  - `--ink-3`: `#71717a`
  - `--line`: `#e4e4e7`
  - `--line-strong`: `#d4d4d8`
  - `--accent`: `#3b66f5`
  - `--accent-soft`: `#eff3ff`
- **Dark Mode**:
  - `--ground`: `#09090b`
  - `--surface`: `#121215`
  - `--surface-2`: `#18181b`
  - `--surface-3`: `#27272a`
  - `--ink`: `#f4f4f5`
  - `--ink-2`: `#a1a1aa`
  - `--ink-3`: `#71717a`
  - `--line`: `#27272a`
  - `--line-strong`: `#3f3f46`
  - `--accent`: `#60a5fa`
  - `--accent-soft`: `#172554`

### Geometry & Depth

- `--radius-sm`: `6px` (badges, tags, buttons)
- `--radius`: `10px` (cards, terminal, code blocks)
- `--radius-lg`: `14px` (drawers, panels)
- Soft subtle ambient elevation:
  - `--shadow-sm`: `0 1px 3px rgba(0, 0, 0, 0.05)`
  - `--shadow-md`: `0 4px 14px rgba(0, 0, 0, 0.07)`
  - `--shadow-lg`: `0 10px 28px rgba(0, 0, 0, 0.12)`

### Typography & Spacing

- Clean Inter typography with `-0.025em` letter tracking on headings.
- Inline `<code>` styled with subtle rounded background pill and padding.
- Code blocks styled with soft rounded container, syntax highlighting with balanced contrast, and copy buttons that appear cleanly on hover.

---

## 4. Responsive Layout & Mobile Drawer (`site/assets/site.js` & `style.css`)

- **Mobile (<768px)**:
  - Sidebar transforms into a slide-over off-canvas drawer (`transform: translateX(-100%)` -> `translateX(0)`).
  - Darkened backdrop overlay (`.nav-backdrop`) fades in.
  - Tapping backdrop, pressing ESC, or clicking any navigation link smoothly closes the drawer.
  - Body scroll is locked when drawer is active.
  - All touch targets adhere to a minimum 44px height.
- **Tablets (768px - 1080px)**:
  - 2-column layout (Sidebar + Doc), right TOC collapsed, content width constrained to `70ch` for optimal reading.
- **Desktop (1080px - 1440px)**:
  - 3-column layout: Sticky Left Nav, Center Markdown Content, Sticky Right "On this page" TOC with live scrollspy highlight.
- **Ultra-wide (>1440px)**:
  - Container centered with maximum width of `1240px`.

---

## 5. Verification Plan

1. **Site Build**: Run `python3 site/build.py` to ensure all 22+ pages compile with zero template errors.
2. **Link Verification**: Run `python3 site/check_links.py` to verify all internal links, anchors, and redirects resolve cleanly.
3. **Automated Tests**: Run `pytest -q` to confirm all repo tests pass and no invariants are broken.
4. **Browser Testing**: Use browser subagent to visually verify mobile (375px), tablet (768px), and desktop (1280px) viewports in both light and dark modes.
