#!/usr/bin/env python3
"""Build the documentation site from the repository's own markdown.

The rule this exists to enforce: **the site is not a second copy of the docs.**
Every page except the landing page is rendered from a file that already lives in
the repo, so a doc edit ships to the site and a stale site becomes impossible.

    python site/build.py                # → site/_build, links rooted at /
    SITE_BASE=/agent-arena python site/build.py

Two dependencies, both build-time only (see site/requirements.txt). Nothing here
is imported by the package, so `pip install agent-arena` is unaffected.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import markdown
except ImportError:  # pragma: no cover - the message is the whole point
    sys.exit(
        "The site build needs Markdown and Pygments:\n"
        "    pip install -r site/requirements.txt"
    )

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
OUT = SITE / "_build"

#: Project pages live under /<repo>/, so every internal link needs the prefix.
#: Empty for a local preview served from the root.
BASE = os.environ.get("SITE_BASE", "").rstrip("/")

REPO = "https://github.com/adityamhaske/agent-arena"
BLOB = f"{REPO}/blob/main"

SITE_TITLE = "Agent Arena"
SITE_TAGLINE = "Pick the model — or the pipeline — your project should actually ship."


@dataclass
class Page:
    """One rendered page. ``source`` is None for the hand-written landing page."""

    url: str
    title: str
    source: str | None = None
    nav: str = ""
    blurb: str = ""
    hide_toc: bool = False
    html: str = ""
    toc: str = ""
    headings: list = field(default_factory=list)

    @property
    def out_path(self) -> Path:
        return OUT / self.url.strip("/") / "index.html" if self.url != "/" else OUT / "index.html"

    @property
    def href(self) -> str:
        return f"{BASE}/" if self.url == "/" else f"{BASE}{self.url}"


# The whole site, in reading order. Adding a doc is one line here.
PAGES: list[Page] = [
    Page("/", SITE_TITLE, None, hide_toc=True),

    Page("/guide/", "Universal Arena guide", "docs/UNIVERSAL_ARENA.md", "Universal Arena",
         "The full reference: projects, scorers, metrics, constraints, targets, the UI."),
    Page("/demo/", "Demo walkthrough", "demo.md", "Universal Arena",
         "End-to-end with local models, and the real output at each step."),
    Page("/example-report/", "Sample report", "docs/EXAMPLE_REPORT.md", "Universal Arena",
         "What a finished run actually produces."),

    Page("/study/", "Multi-agent handoff study", "studies/multi_agent_handoff/README.md",
         "Multi-agent study",
         "Does splitting a task across agents lose information at the handoff?"),
    Page("/study/architecture/", "The four architectures",
         "studies/multi_agent_handoff/docs/ARCHITECTURE.md", "Multi-agent study",
         "Single agent, peer-to-peer, supervisor-worker, debate-critic."),
    Page("/study/tasks/", "Tasks and evals",
         "studies/multi_agent_handoff/docs/TASKS_AND_EVALS.md", "Multi-agent study",
         "The trap task, and how a run is graded into a failure category."),
    Page("/study/trace-schema/", "Trace schema",
         "studies/multi_agent_handoff/docs/TRACE_SCHEMA.md", "Multi-agent study",
         "The append-only event format every architecture emits."),
    Page("/study/report/", "Sweep report",
         "studies/multi_agent_handoff/results/sweep_20260627/report.md", "Multi-agent study",
         "The committed 28-run sweep the finding rests on."),

    Page("/roadmap/", "Roadmap", "docs/ROADMAP_10X.md", "Project",
         "Where this goes next — and what it deliberately will not become."),
    Page("/decisions/", "Decisions (ADRs)", "docs/DECISIONS.md", "Project",
         "Why the trace format, retry strategy and config-driven design are what they are."),
]

# Every ADR becomes a page, so DECISIONS.md's links resolve on the site.
for adr in sorted((ROOT / "docs" / "adr").glob("*.md")):
    number, _, rest = adr.stem.partition("-")
    PAGES.append(
        Page(
            f"/decisions/{adr.stem}/",
            f"ADR {number}: {rest.replace('-', ' ')}",
            f"docs/adr/{adr.name}",
            "Decisions",
        )
    )

BY_SOURCE = {page.source: page for page in PAGES if page.source}

#: Repo files that are worth linking but are not pages — sent to GitHub instead
#: of 404ing. Any path not listed and not a page gets the same treatment.
NAV_GROUPS = ["Universal Arena", "Multi-agent study", "Project", "Decisions"]


# ---------------------------------------------------------------------------
# markdown → html
# ---------------------------------------------------------------------------


def make_converter() -> "markdown.Markdown":
    return markdown.Markdown(
        extensions=[
            "fenced_code",
            "codehilite",
            "tables",
            "toc",
            "sane_lists",
            "attr_list",
            "md_in_html",
        ],
        extension_configs={
            "codehilite": {"css_class": "highlight", "guess_lang": False},
            "toc": {"permalink": "", "toc_depth": "2-3"},
        },
    )


LINK = re.compile(r'(href|src)="([^"]+)"')

#: A doc that opens with its own "Contents" list is duplicating the table of
#: contents this site renders beside it. Drop the list, keep the document.
INLINE_TOC = re.compile(
    r'<h2 id="contents">Contents.*?</h2>\s*<ol>.*?</ol>', re.DOTALL | re.IGNORECASE
)


def drop_inline_contents(html: str) -> str:
    return INLINE_TOC.sub("", html)


def rewrite_links(html: str, source: str) -> str:
    """Point repo-relative links at the right place.

    A link to a file that became a page goes to that page; a link to any other
    repo file goes to GitHub. The alternative — leaving `../docs/FOO.md` in the
    HTML — is a guaranteed 404 on every page that cross-references another.
    """
    source_dir = Path(source).parent

    def replace(match: re.Match) -> str:
        attribute, target = match.group(1), match.group(2)
        if target.startswith(("http://", "https://", "mailto:", "#", "data:")):
            return match.group(0)

        path, _, anchor = target.partition("#")
        anchor = f"#{anchor}" if anchor else ""
        if not path:
            return match.group(0)

        # Resolve relative to the file that contains the link.
        resolved = os.path.normpath(str(source_dir / path)) if not path.startswith("/") else path.lstrip("/")

        page = BY_SOURCE.get(resolved)
        if page is not None:
            return f'{attribute}="{page.href}{anchor}"'
        if (ROOT / resolved).exists():
            return f'{attribute}="{BLOB}/{resolved}{anchor}"'
        # Unknown target: send it to the repo root rather than nowhere.
        return f'{attribute}="{REPO}{anchor}"'

    return LINK.sub(replace, html)


def external_targets(html: str) -> str:
    """Open off-site links in a new tab; keep same-site navigation in place."""
    return re.sub(
        r'<a href="(https?://[^"]+)"',
        r'<a href="\1" target="_blank" rel="noopener"',
        html,
    )


# ---------------------------------------------------------------------------
# templating
# ---------------------------------------------------------------------------


def render(template: str, **values: str) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{{" + key + "}}", value)
    return out


def build_nav(current: Page) -> str:
    """The sidebar. Grouped, with the current page marked for both eye and AT."""
    parts = []
    for group in NAV_GROUPS:
        items = [p for p in PAGES if p.nav == group]
        if not items:
            continue
        links = []
        for page in items:
            active = ' class="active" aria-current="page"' if page.url == current.url else ""
            links.append(f'<li><a href="{page.href}"{active}>{page.title}</a></li>')
        parts.append(
            f'<div class="nav-group"><h4>{group}</h4><ul>{"".join(links)}</ul></div>'
        )
    return "".join(parts)


def build_footer_links(current: Page) -> str:
    """Previous/next, so the docs can be read straight through."""
    ordered = [p for p in PAGES if p.source]
    try:
        index = ordered.index(current)
    except ValueError:
        return ""
    previous = ordered[index - 1] if index > 0 else None
    following = ordered[index + 1] if index + 1 < len(ordered) else None
    left = (
        f'<a class="pager prev" href="{previous.href}"><span>Previous</span>{previous.title}</a>'
        if previous else "<span></span>"
    )
    right = (
        f'<a class="pager next" href="{following.href}"><span>Next</span>{following.title}</a>'
        if following else "<span></span>"
    )
    return f'<nav class="pager-row">{left}{right}</nav>'


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def build() -> int:
    page_template = (SITE / "templates" / "page.html").read_text(encoding="utf-8")
    home_template = (SITE / "templates" / "home.html").read_text(encoding="utf-8")

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    # Render the markdown pages first so the landing page can link to them.
    for page in PAGES:
        if not page.source:
            continue
        source_path = ROOT / page.source
        if not source_path.is_file():
            print(f"  ! missing source, skipping: {page.source}")
            continue
        converter = make_converter()
        html = converter.convert(source_path.read_text(encoding="utf-8"))
        page.html = external_targets(
            drop_inline_contents(rewrite_links(html, page.source))
        )
        page.toc = getattr(converter, "toc", "")

    written = 0
    for page in PAGES:
        if page.source:
            body = render(
                page_template,
                title=page.title,
                blurb=page.blurb,
                content=page.html,
                toc=page.toc if page.toc.strip() else "",
                toc_class="" if page.toc.strip() else "empty",
                nav=build_nav(page),
                pager=build_footer_links(page),
                source=page.source,
                source_url=f"{BLOB}/{page.source}",
                base=BASE,
                site_title=SITE_TITLE,
                page_title=f"{page.title} · {SITE_TITLE}",
                description=page.blurb or SITE_TAGLINE,
                canonical=page.href,
            )
        else:
            body = render(
                home_template,
                base=BASE,
                site_title=SITE_TITLE,
                page_title=f"{SITE_TITLE} — {SITE_TAGLINE}",
                description=SITE_TAGLINE,
                repo=REPO,
                canonical=page.href,
            )

        page.out_path.parent.mkdir(parents=True, exist_ok=True)
        page.out_path.write_text(body, encoding="utf-8")
        written += 1

    shutil.copytree(SITE / "assets", OUT / "assets")
    # Tell GitHub Pages not to run Jekyll over the artifact.
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    write_extras()

    print(f"Built {written} pages into {OUT.relative_to(ROOT)} (base={BASE or '/'})")
    return 0


def write_extras() -> None:
    """A 404, a sitemap and a robots.txt — cheap, and their absence is noticed."""
    not_found = render(
        (SITE / "templates" / "page.html").read_text(encoding="utf-8"),
        title="Page not found",
        blurb="",
        content=(
            "<h1>Page not found</h1>"
            "<p>That page does not exist on this site. It may have moved, or it "
            "may only exist in the repository.</p>"
            f'<p><a href="{BASE}/">Back to the front page</a> · '
            f'<a href="{REPO}">Browse the repository</a></p>'
        ),
        toc="",
        toc_class="empty",
        nav=build_nav(Page("/404/", "")),
        pager="",
        source="",
        source_url=REPO,
        base=BASE,
        site_title=SITE_TITLE,
        page_title=f"Not found · {SITE_TITLE}",
        description="Page not found",
        canonical="",
    )
    (OUT / "404.html").write_text(not_found, encoding="utf-8")

    origin = "https://adityamhaske.github.io"
    urls = "\n".join(
        f"  <url><loc>{origin}{page.href}</loc></url>" for page in PAGES
    )
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n</urlset>\n",
        encoding="utf-8",
    )
    (OUT / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {origin}{BASE}/sitemap.xml\n", encoding="utf-8"
    )


if __name__ == "__main__":
    raise SystemExit(build())
