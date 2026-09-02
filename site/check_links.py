#!/usr/bin/env python3
"""Fail the build when an internal link points at nothing.

The site renders markdown that was written for GitHub, where `../docs/FOO.md`
resolves fine and on a website does not. `build.py` rewrites those, but a
rewrite rule is only as good as its coverage — so this walks every generated
page and checks that every internal href actually exists in the output.

External links are not fetched: a docs build that fails because someone else's
site is down is a worse problem than the one it detects.

    python site/check_links.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "_build"

HREF = re.compile(r'(?:href|src)="([^"]+)"')
EXTERNAL = ("http://", "https://", "mailto:", "data:", "#", "//")

#: Every page links the stylesheet at `<base>/assets/style.css`, so the prefix
#: in front of that is the base path the site was built with.
BASE_MARKER = re.compile(r'href="([^"]*)/assets/style\.css"')


def detect_base() -> str:
    """Read the base path back out of the build rather than being told it.

    Passing SITE_BASE to the build and forgetting it here silently marks every
    prefixed link broken — which is exactly how this checker first failed. The
    output knows what it was built with, so ask it.
    """
    index = OUT / "index.html"
    if index.is_file():
        match = BASE_MARKER.search(index.read_text(encoding="utf-8"))
        if match:
            return match.group(1).rstrip("/")
    return os.environ.get("SITE_BASE", "").rstrip("/")


def target_exists(link: str, base: str) -> bool:
    """Does this path resolve to something the deploy will actually serve?"""
    path = link.split("#")[0].split("?")[0]
    if not path:
        return True

    # Links are absolute from the site root and carry the SITE_BASE prefix.
    relative = path[len(base):] if base and path.startswith(base) else path
    relative = relative.lstrip("/")

    candidate = OUT / relative
    if candidate.is_file():
        return True
    if candidate.is_dir() and (candidate / "index.html").is_file():
        return True
    # A directory URL written without its trailing slash.
    return (OUT / f"{relative}.html").is_file() or (
        (OUT / relative / "index.html").is_file()
    )


def main() -> int:
    if not OUT.is_dir():
        print(f"error: {OUT} does not exist — run `python site/build.py` first.")
        return 2

    base = detect_base()
    pages = sorted(OUT.rglob("*.html"))
    if not pages:
        print(f"error: no pages found in {OUT}")
        return 2

    broken: list[tuple[str, str]] = []
    checked = 0
    for page in pages:
        html = page.read_text(encoding="utf-8")
        for link in HREF.findall(html):
            if link.startswith(EXTERNAL):
                continue
            checked += 1
            if not target_exists(link, base):
                broken.append((str(page.relative_to(OUT)), link))

    print(f"Checked {checked} internal links across {len(pages)} pages (base={base or '/'}).")
    if broken:
        print(f"\n{len(broken)} broken link(s):")
        for page, link in broken:
            print(f"  {page}: {link}")
        return 1

    print("No broken internal links.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
