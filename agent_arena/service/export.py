"""Getting your own data out.

A leaderboard is usually shown to someone who was not in the terminal when it
ran — the person who owns the budget, the reviewer on a pull request, a ticket.
The HTML format exists for exactly that: a single self-contained file that opens
on a locked-down laptop with no network, no CDN and no JavaScript.

Markdown and JSON come from :mod:`agent_arena.core.report`, which already
renders them for every run. Duplicating that here would let the file you export
and the file the run wrote drift apart.
"""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any

from ..core.config import ProjectConfig, load_config
from ..core.store import ResultStore
from .errors import NotFoundError, ServiceError
from .paths import resolve_within, safe_name

FORMATS = ("csv", "json", "markdown", "html")


def _config(projects_dir: str | Path, project: str) -> ProjectConfig:
    root = resolve_within(projects_dir, project, "project name")
    if not root.is_dir():
        raise NotFoundError(f"no project named {project!r}")
    return load_config(root)


def _target(dest: str | Path, default_name: str) -> Path:
    path = Path(dest)
    if path.is_dir() or str(dest).endswith(("/", "\\")):
        path = path / default_name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def export_run(
    projects_dir: str | Path,
    project: str,
    run_id: str | None,
    fmt: str = "markdown",
    dest: str | Path = ".",
) -> Path:
    """Write one run to ``dest``. Returns the path actually written."""
    fmt = str(fmt).lower().strip()
    if fmt not in FORMATS:
        raise ServiceError(f"unknown format {fmt!r}; use one of {', '.join(FORMATS)}")

    config = _config(projects_dir, project)
    if not config.database.exists():
        raise NotFoundError(f"{project!r} has no results database yet")

    with ResultStore(config.database) as store:
        if run_id is None:
            recent = store.runs(project=config.project, limit=1)
            if not recent:
                raise NotFoundError(f"{project!r} has no runs yet")
            run_id = recent[0]["run_id"]
        else:
            safe_name(run_id, "run id")
        run = store.run(run_id)
        if run is None:
            raise NotFoundError(f"no run {run_id!r} in project {project!r}")
        rankings = store.rankings(run_id)
        results = store.results(run_id=run_id, limit=1_000_000)

    path = _target(dest, f"{run_id}.{'md' if fmt == 'markdown' else fmt}")

    if fmt == "csv":
        _write_csv(path, results)
    elif fmt == "json":
        path.write_text(
            json.dumps(
                {"schema_version": 1, "run": _safe_run(run),
                 "rankings": rankings, "results": results},
                indent=2, default=str,
            ),
            encoding="utf-8",
        )
    elif fmt == "markdown":
        path.write_text(_markdown(run, rankings, results), encoding="utf-8")
    else:
        path.write_text(_html(run, rankings, results), encoding="utf-8")
    return path


def export_all(projects_dir: str | Path, project: str, dest: str | Path = ".") -> Path:
    """Every run for a project, as one JSON document."""
    config = _config(projects_dir, project)
    if not config.database.exists():
        raise NotFoundError(f"{project!r} has no results database yet")
    with ResultStore(config.database) as store:
        runs = store.runs(project=config.project, limit=100_000)
        payload = {
            "schema_version": 1,
            "project": config.project,
            "runs": [
                {
                    "run": _safe_run(run),
                    "rankings": store.rankings(run["run_id"]),
                }
                for run in runs
            ],
        }
    path = _target(dest, f"{config.project}-export.json")
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _safe_run(run: dict[str, Any]) -> dict[str, Any]:
    """A run row with its config snapshot scrubbed of anything key-shaped.

    Every run stores the config it ran under, which is exactly where a literal
    credential hides if someone pasted one instead of using a reference.
    """
    row = dict(run)
    raw = row.get("config_json")
    if not raw:
        return row
    try:
        config = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return row
    row["config_json"] = json.dumps(_scrub(config))
    return row


_SECRET_KEYS = ("api_key", "apikey", "key", "token", "secret", "password", "authorization")


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in _SECRET_KEYS):
                text = str(item)
                # A ${...} reference is not a secret — it is the whole point of
                # using one, and blanking it would lose real information.
                out[key] = item if text.startswith("${") else "***"
            else:
                out[key] = _scrub(item)
        return out
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


def _write_csv(path: Path, results: list[dict[str, Any]]) -> None:
    if not results:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)


def _markdown(run: dict, rankings: list[dict], results: list[dict]) -> str:
    lines = [
        f"# {run.get('project')} — {run.get('run_id')}",
        "",
        f"- Started: {run.get('started_at')}",
        f"- Models: {run.get('n_models')} · Tests: {run.get('n_tests')} · "
        f"Results: {run.get('n_results')}",
        f"- Total cost: ${run.get('total_cost_usd') or 0:.4f}",
        f"- Arena {run.get('arena_version')} · git {str(run.get('git_sha') or '')[:8]}",
        "",
        "## Leaderboard",
        "",
        "| # | model | status | composite |",
        "|---|---|---|---|",
    ]
    for entry in rankings:
        rank = entry.get("rank")
        composite = entry.get("composite")
        lines.append(
            f"| {rank if rank is not None else '—'} | {entry.get('model_key')} | "
            f"{entry.get('status')} | "
            f"{f'{composite:.3f}' if composite is not None else '—'} |"
        )
    lines += ["", f"## Results ({len(results)} calls)", ""]
    return "\n".join(lines) + "\n"


def _html(run: dict, rankings: list[dict], results: list[dict]) -> str:
    """A single self-contained file. No CDN, no script, readable offline.

    Everything is escaped: model output is untrusted text full of angle
    brackets, and an evaluation report that executed its own contents would be
    a genuinely bad look.
    """
    e = html.escape

    def number(value: Any, places: int = 3) -> str:
        return "—" if value is None else f"{float(value):.{places}f}"

    def cell(value: Any, limit: int | None = None) -> str:
        text = "" if value is None else str(value)
        return e(text[:limit] if limit else text)

    rows = "".join(
        "<tr>"
        f"<td>{cell(entry.get('rank') if entry.get('rank') is not None else '—')}</td>"
        f"<td>{cell(entry.get('model_key'))}</td>"
        f"<td>{cell(entry.get('model'))}</td>"
        f"<td class='s-{cell(str(entry.get('status') or '').lower())}'>"
        f"{cell(entry.get('status'))}</td>"
        f"<td class='n'>{number(entry.get('composite'))}</td>"
        f"<td>{cell(entry.get('failures'))}</td>"
        "</tr>"
        for entry in rankings
    )

    case_rows = "".join(
        "<tr>"
        f"<td>{cell(r.get('model_key'))}</td>"
        f"<td>{cell(r.get('test_id'))}</td>"
        f"<td class='n'>{cell(r.get('trial'))}</td>"
        f"<td class='n'>{number(r.get('score'), 2)}</td>"
        f"<td>{cell(r.get('output'), 300)}</td>"
        f"<td>{cell(r.get('reference'), 120)}</td>"
        f"<td>{cell(r.get('reason'), 160)}</td>"
        "</tr>"
        for r in results[:2000]
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(str(run.get('project')))} — {e(str(run.get('run_id')))}</title>
<style>
:root {{ --bg:#fff; --fg:#16191d; --dim:#5b6572; --rule:#dfe3e8; --soft:#f6f7f9;
        --good:#147a45; --bad:#b3261e; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#101317; --fg:#e8ecf1; --dim:#a3adba; --rule:#2a313a; --soft:#171b21;
          --good:#4ec98a; --bad:#ff8a80; }}
}}
* {{ box-sizing:border-box }}
body {{ margin:0; padding:2rem 1.25rem 4rem; background:var(--bg); color:var(--fg);
  font:15px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width:1100px; margin:0 auto }}
h1 {{ font-size:1.5rem; margin:0 0 .25rem }}
h2 {{ font-size:1.05rem; margin:2rem 0 .75rem; padding-bottom:.4rem;
  border-bottom:1px solid var(--rule) }}
.meta {{ color:var(--dim); font-size:13px; margin-bottom:1.5rem }}
.scroll {{ overflow-x:auto; border:1px solid var(--rule); border-radius:6px }}
table {{ border-collapse:collapse; width:100%; font-size:13px; min-width:640px }}
th,td {{ text-align:left; padding:.5rem .7rem; border-bottom:1px solid var(--rule);
  vertical-align:top }}
th {{ background:var(--soft); font-size:11px; text-transform:uppercase;
  letter-spacing:.06em; color:var(--dim); white-space:nowrap }}
tr:last-child td {{ border-bottom:0 }}
td.n {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap }}
.s-ranked {{ color:var(--good) }}
.s-disqualified {{ color:var(--bad); font-weight:600 }}
footer {{ margin-top:2.5rem; color:var(--dim); font-size:12px }}
</style></head><body><main>
<h1>{e(str(run.get('project')))}</h1>
<p class="meta">
  {e(str(run.get('run_id')))} · started {e(str(run.get('started_at')))}<br>
  {e(str(run.get('n_models')))} models · {e(str(run.get('n_tests')))} tests ·
  {e(str(run.get('n_results')))} calls · total ${run.get('total_cost_usd') or 0:.4f}<br>
  arena {e(str(run.get('arena_version')))} · git {e(str(run.get('git_sha') or '')[:8])}
</p>

<h2>Leaderboard</h2>
<div class="scroll"><table>
<thead><tr><th>#</th><th>key</th><th>model</th><th>status</th><th>composite</th>
<th>notes</th></tr></thead><tbody>{rows}</tbody></table></div>

<h2>Per-case results</h2>
<div class="scroll"><table>
<thead><tr><th>model</th><th>test</th><th>trial</th><th>score</th><th>output</th>
<th>reference</th><th>why</th></tr></thead><tbody>{case_rows}</tbody></table></div>

<footer>Generated by Agent Arena. A model with no rank was disqualified; the
reason is in the notes column.</footer>
</main></body></html>
"""
