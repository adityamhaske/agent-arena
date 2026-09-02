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

import html as html_lib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
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

#: Absolute origin, needed by canonical URLs, Open Graph and the sitemap —
#: crawlers resolve those against the origin, not the page.
ORIGIN = "https://adityamhaske.github.io"

#: GitHub renders a social card for every repository. Using it means link
#: previews work without committing a binary we would then have to maintain.
SOCIAL_IMAGE = "https://opengraph.githubassets.com/1/adityamhaske/agent-arena"

AUTHOR = "Aditya Mhaske"


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
    heading: str = ""
    """The document's own H1, used as the page heading so there is exactly one."""
    description: str = ""
    lastmod: str = ""
    headings: list = field(default_factory=list)

    @property
    def out_path(self) -> Path:
        return OUT / self.url.strip("/") / "index.html" if self.url != "/" else OUT / "index.html"

    @property
    def href(self) -> str:
        return f"{BASE}/" if self.url == "/" else f"{BASE}{self.url}"

    @property
    def absolute(self) -> str:
        return f"{ORIGIN}{self.href}"


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

    Page("/releases/", "Releases", "CHANGELOG.md", "Project",
         "What shipped in each version, and which interfaces are covered by semver."),
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


#: A rendered doc opens with its own `# Title`, and the page shell adds one too.
#: Two H1s is a real defect — it duplicates the headline and leaves crawlers with
#: an ambiguous document outline. The document's own title wins; the shell's
#: curated title stays as <title> and the nav label.
LEADING_H1 = re.compile(r'<h1[^>]*>(.*?)</h1>\s*', re.DOTALL | re.IGNORECASE)
FIRST_PARAGRAPH = re.compile(r'<p>(.*?)</p>', re.DOTALL)
TAGS = re.compile(r'<[^>]+>')


def take_heading(html: str) -> tuple[str, str]:
    """Pull the document's own H1 out of the body and return both.

    Searched rather than anchored: a doc may open with a lead-in line before its
    title (EXAMPLE_REPORT.md does), and that H1 is still the document's title.
    A well-formed document has at most one, so taking the first is safe.
    """
    match = LEADING_H1.search(html)
    if not match:
        return "", html
    heading = strip_tags(match.group(1))
    return heading, html[: match.start()] + html[match.end():]


def strip_tags(fragment: str) -> str:
    return " ".join(html_lib.unescape(TAGS.sub(" ", fragment)).split())


#: ADRs open with a `Date: … Status: …` block. That is metadata, not a summary,
#: and it makes a useless search snippet — skip past it to the real prose.
METADATA_LEAD = re.compile(r"^(date|status|updated|author|supersedes|deciders)\b", re.I)


def summarise(html: str, limit: int = 155) -> str:
    """A meta description taken from the page's own opening prose.

    Better than no description at all — which is what every ADR had — and better
    than a generic one, because a search result then describes the actual page.
    """
    for candidate in FIRST_PARAGRAPH.findall(html):
        text = strip_tags(candidate)
        if len(text) < 40:
            continue  # a one-line lead-in is not a summary
        if METADATA_LEAD.match(text):
            continue
        if len(text) <= limit:
            return text
        cut = text[:limit].rsplit(" ", 1)[0]
        return cut.rstrip(",;:—-") + "…"
    return ""


def git_lastmod(relative: str) -> str:
    """When this page's source last changed, for the sitemap.

    A sitemap without `lastmod` gives a crawler no reason to re-read a page it
    has already seen; taking it from git means it is always true.
    """
    try:
        stamp = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", relative],
            cwd=ROOT, capture_output=True, text=True, timeout=15,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        stamp = ""
    return stamp[:10] if stamp else datetime.now(timezone.utc).strftime("%Y-%m-%d")


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


def breadcrumb_trail(page: Page) -> list[tuple[str, str]]:
    """Home → section → page. Gives crawlers a hierarchy and readers a way up."""
    trail = [(SITE_TITLE, f"{BASE}/")]
    if page.nav == "Decisions" and page.url != "/decisions/":
        trail.append(("Decisions", f"{BASE}/decisions/"))
    elif page.nav == "Multi-agent study" and page.url != "/study/":
        trail.append(("Multi-agent study", f"{BASE}/study/"))
    trail.append((page.title, page.href))
    return trail


def breadcrumb_html(page: Page) -> str:
    parts = []
    for index, (label, href) in enumerate(breadcrumb_trail(page)):
        last = index == len(breadcrumb_trail(page)) - 1
        if last:
            parts.append(f'<span aria-current="page">{html_lib.escape(label)}</span>')
        else:
            parts.append(f'<a href="{href}">{html_lib.escape(label)}</a>')
    return (
        '<nav class="crumbs" aria-label="Breadcrumb">'
        + '<span class="sep" aria-hidden="true">/</span>'.join(parts)
        + "</nav>"
    )


def json_ld(page: Page) -> str:
    """Structured data, so a crawler is told what the page is rather than guessing."""
    graph: list[dict] = [
        {
            "@type": "WebSite",
            "@id": f"{ORIGIN}{BASE}/#website",
            "url": f"{ORIGIN}{BASE}/",
            "name": SITE_TITLE,
            "description": SITE_TAGLINE,
            "inLanguage": "en",
            "author": {"@type": "Person", "name": AUTHOR},
        }
    ]

    if page.source:
        graph.append(
            {
                "@type": "TechArticle",
                "@id": f"{page.absolute}#article",
                "headline": page.heading or page.title,
                "name": page.title,
                "description": page.description,
                "url": page.absolute,
                "dateModified": page.lastmod,
                "inLanguage": "en",
                "isPartOf": {"@id": f"{ORIGIN}{BASE}/#website"},
                "author": {"@type": "Person", "name": AUTHOR},
                "image": SOCIAL_IMAGE,
            }
        )
        graph.append(
            {
                "@type": "BreadcrumbList",
                "@id": f"{page.absolute}#breadcrumbs",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": index + 1,
                        "name": label,
                        "item": f"{ORIGIN}{href}",
                    }
                    for index, (label, href) in enumerate(breadcrumb_trail(page))
                ],
            }
        )
    else:
        graph.append(
            {
                "@type": "SoftwareSourceCode",
                "@id": f"{ORIGIN}{BASE}/#software",
                "name": SITE_TITLE,
                "description": SITE_TAGLINE,
                "url": f"{ORIGIN}{BASE}/",
                "codeRepository": REPO,
                "programmingLanguage": "Python",
                "license": "https://opensource.org/licenses/MIT",
                "author": {"@type": "Person", "name": AUTHOR},
            }
        )

    payload = {"@context": "https://schema.org", "@graph": graph}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


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
        html = external_targets(drop_inline_contents(rewrite_links(html, page.source)))
        # Exactly one H1 per page: the document's own, promoted into the shell.
        page.heading, page.html = take_heading(html)
        page.description = page.blurb or summarise(page.html)
        page.lastmod = git_lastmod(page.source)
        page.toc = getattr(converter, "toc", "")

    written = 0
    for page in PAGES:
        if page.source:
            body = render(
                page_template,
                title=page.heading or page.title,
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
                description=html_lib.escape(page.description or SITE_TAGLINE, quote=True),
                canonical=page.absolute,
                origin=ORIGIN,
                image=SOCIAL_IMAGE,
                crumbs=breadcrumb_html(page),
                jsonld=json_ld(page),
                lastmod=page.lastmod,
                robots="index,follow,max-image-preview:large,max-snippet:-1",
            )
        else:
            body = render(
                home_template,
                base=BASE,
                site_title=SITE_TITLE,
                page_title=f"{SITE_TITLE} — {SITE_TAGLINE}",
                description=html_lib.escape(SITE_TAGLINE, quote=True),
                repo=REPO,
                canonical=page.absolute,
                origin=ORIGIN,
                image=SOCIAL_IMAGE,
                jsonld=json_ld(page),
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
        description="This page does not exist on the Agent Arena documentation site.",
        canonical="",
        origin=ORIGIN,
        image=SOCIAL_IMAGE,
        crumbs="",
        # A 404 must never be indexed, or it competes with the real pages.
        jsonld="",
        lastmod="",
        robots="noindex,follow",
    )
    (OUT / "404.html").write_text(not_found, encoding="utf-8")

    # A sitemap without lastmod gives a crawler no reason to revisit; without
    # priority it cannot tell the landing page from an ADR. Both are cheap.
    entries = []
    for page in PAGES:
        if page.url == "/":
            priority, changefreq = "1.0", "weekly"
        elif page.nav == "Decisions":
            priority, changefreq = "0.4", "yearly"
        elif page.url in ("/guide/", "/study/"):
            priority, changefreq = "0.9", "monthly"
        elif page.url == "/releases/":
            priority, changefreq = "0.8", "weekly"
        else:
            priority, changefreq = "0.6", "monthly"
        lastmod = page.lastmod or git_lastmod("site")
        entries.append(
            "  <url>\n"
            f"    <loc>{page.absolute}</loc>\n"
            f"    <lastmod>{lastmod}</lastmod>\n"
            f"    <changefreq>{changefreq}</changefreq>\n"
            f"    <priority>{priority}</priority>\n"
            "  </url>"
        )
    (OUT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + "\n</urlset>\n",
        encoding="utf-8",
    )

    (OUT / "robots.txt").write_text(
        "# Agent Arena documentation — everything here is public and crawlable.\n"
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        f"Sitemap: {ORIGIN}{BASE}/sitemap.xml\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(build())
