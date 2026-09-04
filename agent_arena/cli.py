"""``arena`` — the command line.

::

    arena evaluate --project projects/support_triage
    arena evaluate --project projects/support_triage --models claude-opus-5 --trials 3
    arena init projects/my_new_project
    arena models --project projects/support_triage
    arena history --project projects/support_triage
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any, Sequence

from .core.config import ProjectConfig, load_config
from .core.env import load_env
from .core.errors import ArenaError
from .core.report import Report, format_metric, text_table, write_reports
from .connectors.registry import resolve_provider
from .core.runner import ArenaRunner
from .core.store import ResultStore
from .core.testcase import load_test_cases

# Inside the package, not beside it: `projects/` is not part of the wheel,
# so a pip-installed `arena init` could never find a template out there.
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arena",
        description="Compare LLMs on your own project's criteria.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    sub = parser.add_subparsers(dest="command")

    def add_project(p: argparse.ArgumentParser, required: bool = True) -> None:
        p.add_argument(
            "--project",
            "-p",
            required=required,
            help="path to the project folder (or its config file)",
        )

    evaluate = sub.add_parser("evaluate", help="run the evaluation sweep", aliases=["run"])
    add_project(evaluate)
    evaluate.add_argument("--models", nargs="+", help="only these models (by key or id)")
    evaluate.add_argument("--trials", type=int, help="override run.trials")
    evaluate.add_argument("--concurrency", type=int, help="override run.concurrency")
    evaluate.add_argument("--tags", nargs="+", help="only test cases carrying any of these tags")
    evaluate.add_argument("--exclude-tags", nargs="+", help="skip test cases with these tags")
    evaluate.add_argument("--ids", nargs="+", help="only these test-case ids")
    evaluate.add_argument("--limit", type=int, help="cap the number of test cases")
    evaluate.add_argument("--output-dir", help="override output.dir")
    evaluate.add_argument("--dry-run", action="store_true", help="show the plan, call nothing")
    evaluate.add_argument("--no-report", action="store_true", help="skip writing report files")
    evaluate.add_argument("--fail-under", type=float, metavar="SCORE",
                          help="exit non-zero if the winner's composite is below this")
    evaluate.add_argument("--quiet", "-q", action="store_true", help="only print the summary")
    evaluate.add_argument("--json", action="store_true", help="print the run as JSON")

    report = sub.add_parser("report", help="show a stored run")
    add_project(report)
    report.add_argument("--run-id", help="which run (default: most recent)")

    history = sub.add_parser("history", help="list past runs and track regressions")
    add_project(history)
    history.add_argument("--model", help="show one model's trend across runs")
    history.add_argument("--limit", type=int, default=10)
    history.add_argument("--flaky", action="store_true", help="list tests with unstable outcomes")

    init = sub.add_parser("init", help="scaffold a new project folder")
    init.add_argument("path", help="where to create it")
    init.add_argument("--name", help="project name (defaults to the folder name)")
    init.add_argument("--force", action="store_true", help="write into a non-empty folder")

    models = sub.add_parser("models", help="show model cards: price, context, features")
    add_project(models, required=False)

    scorers = sub.add_parser("scorers", help="list available eval types")
    add_project(scorers, required=False)

    tests = sub.add_parser("tests", help="list the test cases a project will run")
    add_project(tests)
    tests.add_argument("--tags", nargs="+")
    tests.add_argument("--limit", type=int)

    ui = sub.add_parser("ui", help="open the point-and-click interface in a browser")
    ui.add_argument(
        "--projects-dir", default="projects",
        help="folder holding your project folders (default: projects)",
    )
    ui.add_argument("--port", type=int, default=8420)
    ui.add_argument(
        "--host", default="127.0.0.1",
        help="bind address. Anything but localhost exposes an unauthenticated UI",
    )
    ui.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    ui.add_argument("--verbose", action="store_true", help="log every request")

    projects_cmd = sub.add_parser("projects", help="list projects in the projects folder")
    projects_cmd.add_argument("--projects-dir", default="projects")
    projects_cmd.add_argument("--all", action="store_true", help="include archived projects")

    runs_cmd = sub.add_parser("runs", help="list past runs")
    add_project(runs_cmd)
    runs_cmd.add_argument("--limit", type=int, default=20)
    runs_cmd.add_argument("--all", action="store_true", help="include deleted runs")

    label = sub.add_parser("label", help="give a run a human name")
    add_project(label)
    label.add_argument("run_id")
    label.add_argument("--label")
    label.add_argument("--notes")

    archive = sub.add_parser("archive", help="hide a project or run from default listings")
    archive.add_argument("what", choices=["project", "run"])
    archive.add_argument("name", help="project name, or run id")
    archive.add_argument("--projects-dir", default="projects")
    archive.add_argument("--project", help="project the run belongs to")
    archive.add_argument("--undo", action="store_true", help="unarchive instead")

    duplicate = sub.add_parser("duplicate", help="copy a project, excluding its results")
    duplicate.add_argument("name")
    duplicate.add_argument("new_name")
    duplicate.add_argument("--projects-dir", default="projects")

    rm = sub.add_parser("rm", help="delete a project or a run")
    rm.add_argument("what", choices=["project", "run"])
    rm.add_argument("name", help="project name, or run id")
    rm.add_argument("--projects-dir", default="projects")
    rm.add_argument("--project", help="project the run belongs to")
    rm.add_argument("--keep-results", action="store_true",
                    help="delete the config but keep results/ and its database")
    rm.add_argument("--hard", action="store_true",
                    help="remove a run outright instead of soft-deleting it")
    rm.add_argument("--dry-run", action="store_true", help="show the plan, change nothing")
    rm.add_argument("--yes", "-y", action="store_true", help="do not ask for confirmation")

    vacuum = sub.add_parser("vacuum", help="permanently remove soft-deleted runs")
    add_project(vacuum)
    vacuum.add_argument("--dry-run", action="store_true")
    vacuum.add_argument("--yes", "-y", action="store_true")

    providers_cmd = sub.add_parser("providers", help="manage connection profiles")
    providers_sub = providers_cmd.add_subparsers(dest="action", metavar="action")
    providers_sub.add_parser("list", help="show configured profiles")
    p_add = providers_sub.add_parser("add", help="create or replace a profile")
    p_add.add_argument("id")
    p_add.add_argument("--kind", required=True)
    p_add.add_argument("--base-url")
    p_add.add_argument("--api-key", help="a ${...} reference, or a literal that goes to the keyring")
    p_add.add_argument("--header", action="append", default=[], metavar="K=V")
    p_add.add_argument("--model-prefix")
    p_test = providers_sub.add_parser("test", help="check a profile can be reached")
    p_test.add_argument("id")
    p_disc = providers_sub.add_parser("discover", help="list the models an endpoint serves")
    p_disc.add_argument("id")
    p_rm = providers_sub.add_parser("rm", help="delete a profile")
    p_rm.add_argument("id")
    p_rm.add_argument("--purge-key", action="store_true", help="also remove its keyring entry")
    p_rm.add_argument("--yes", "-y", action="store_true")

    secrets_cmd = sub.add_parser("secrets", help="manage stored credentials")
    secrets_sub = secrets_cmd.add_subparsers(dest="action", metavar="action")
    s_set = secrets_sub.add_parser("set", help="store a credential")
    s_set.add_argument("account")
    s_set.add_argument("--value", help="read from stdin when omitted")
    s_get = secrets_sub.add_parser("get", help="show a credential (masked by default)")
    s_get.add_argument("account")
    s_get.add_argument("--reveal", action="store_true", help="print the real value")
    s_rm = secrets_sub.add_parser("rm", help="delete a credential")
    s_rm.add_argument("account")

    config_cmd = sub.add_parser("config", help="read or change user settings")
    config_sub = config_cmd.add_subparsers(dest="action", metavar="action")
    config_sub.add_parser("get", help="show settings")
    c_set = config_sub.add_parser("set", help="change a setting")
    c_set.add_argument("key")
    c_set.add_argument("value")
    c_reset = config_sub.add_parser("reset", help="restore defaults")
    c_reset.add_argument("key", nargs="?")

    export = sub.add_parser("export", help="write a run to csv, json, markdown or html")
    add_project(export)
    export.add_argument("--run-id", help="which run (default: most recent)")
    export.add_argument("--format", "-f", default="html",
                        choices=["csv", "json", "markdown", "html"])
    export.add_argument("--out", "-o", default=".", help="file or directory to write to")
    export.add_argument("--all", action="store_true",
                        help="export every run as one JSON document instead")

    env_cmd = sub.add_parser("env", help="show which .env files were found (values redacted)")
    add_project(env_cmd)

    validate = sub.add_parser("validate", help="check a project's config and test files")
    add_project(validate)

    return parser


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_evaluate(args: argparse.Namespace) -> int:
    overrides: dict[str, Any] = {}
    for name in ("models", "trials", "concurrency", "tags", "exclude_tags", "ids", "limit"):
        value = getattr(args, name, None)
        if value is not None:
            overrides[name] = value
    if args.output_dir:
        overrides["output_dir"] = args.output_dir

    config = load_config(args.project, **overrides)
    progress = None if args.quiet else _progress_printer()
    runner = ArenaRunner(
        config, progress=progress, resume_run_id=getattr(args, "resume", None)
    )

    if args.dry_run:
        return _dry_run(runner)

    run = runner.run()
    report = Report(run)

    if args.json:
        print(report.json())
    else:
        print(report.console())

    if not args.no_report:
        written = write_reports(run)
        if written and not args.json:
            for kind, path in written.items():
                print(f"  {kind:<9} {path}")

    if args.fail_under is not None:
        winner = run.winner
        score = winner.composite if winner and winner.composite is not None else 0.0
        if score < args.fail_under:
            print(
                f"\nFAIL: best composite {score:.3f} < --fail-under {args.fail_under}",
                file=sys.stderr,
            )
            return 2
    return 0


def _dry_run(runner: ArenaRunner) -> int:
    config = runner.config
    skipped = runner.preflight()
    runnable = [s for s in config.enabled_models if s.key not in skipped]
    planned = len(runnable) * len(runner.test_cases) * config.run.trials

    print(f"\nProject : {config.project}")
    print(f"Root    : {config.root}")
    print(f"Tests   : {len(runner.test_cases)}")
    print(f"Trials  : {config.run.trials}")
    print(f"Calls   : {planned}")
    print(
        "Weights : "
        + ", ".join(f"{k} {v:.0%}" for k, v in config.metrics.normalized_weights().items())
    )
    print()

    rows = []
    estimated_total = 0.0
    for spec in config.enabled_models:
        card = runner.price_book.get(spec.model, provider=resolve_provider(spec))
        calls = 0 if spec.key in skipped else len(runner.test_cases) * config.run.trials
        # A rough forecast: charge the configured max_tokens as output, and a
        # nominal 500-token prompt. Deliberately pessimistic on output.
        max_out = config.defaults.get("max_tokens") or 512
        estimate = card.cost_usd(500, int(max_out))
        if estimate is not None:
            estimated_total += estimate * calls
        rows.append(
            [
                spec.key,
                spec.model,
                card.provider or (spec.provider or "?"),
                f"${estimate * calls:.4f}" if estimate is not None else "unknown",
                skipped.get(spec.key, "ready"),
            ]
        )
    print(text_table(["key", "model", "provider", "est. cost", "status"], rows))
    if estimated_total:
        print(f"  Rough upper bound: ${estimated_total:.4f}\n")
    print("  (dry run — nothing was called)")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    config = ProjectConfig.load(args.project)
    with ResultStore(config.database) as store:
        if args.run_id:
            # Look the id up directly — filtering a page of recent runs made
            # any older run report as missing when it was simply further back.
            record = store.run(args.run_id)
            if record is None:
                print(f"No run {args.run_id!r} in {config.database}", file=sys.stderr)
                return 1
        else:
            runs = store.runs(project=config.project, limit=1)
            if not runs:
                print(f"No runs recorded for {config.project} in {config.database}")
                return 1
            record = runs[0]

        rankings = store.rankings(record["run_id"])
        print(f"\n{config.project} — run {record['run_id']}")
        print(f"  started {record['started_at']}   status {record['status']}")
        if record.get("total_cost_usd"):
            print(f"  spend ${record['total_cost_usd']:.4f}")
        print()

        import json as _json  # noqa: PLC0415

        metric_names: list[str] = []
        for row in rankings:
            for name in _json.loads(row["metrics_json"] or "{}"):
                if name not in metric_names:
                    metric_names.append(name)

        rows = []
        for row in rankings:
            metrics = _json.loads(row["metrics_json"] or "{}")
            rows.append(
                [
                    row["rank"] or "-",
                    row["model_key"],
                    f"{row['composite']:.3f}" if row["composite"] is not None else "—",
                    *[format_metric(n, (metrics.get(n) or {}).get("raw")) for n in metric_names],
                    row["status"],
                ]
            )
        print(text_table(["#", "model", "composite", *metric_names, "status"], rows))

        for row in rankings:
            failures = _json.loads(row["failures"] or "[]")
            if failures:
                print(f"  ✗ {row['model_key']}: {'; '.join(failures)}")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    config = ProjectConfig.load(args.project)
    with ResultStore(config.database) as store:
        if args.flaky:
            flaky = store.flaky_tests(config.project)
            if not flaky:
                print("No flaky tests — every repeated case scored identically across trials.")
                return 0
            print("\nTests whose score varies across trials:\n")
            print(
                text_table(
                    ["test", "model", "trials", "mean", "min", "max"],
                    [
                        [
                            row["test_id"],
                            row["model_key"],
                            row["n"],
                            f"{row['mean_score']:.2f}",
                            f"{row['min_score']:.2f}",
                            f"{row['max_score']:.2f}",
                        ]
                        for row in flaky
                    ],
                )
            )
            return 0

        if args.model:
            history = store.model_history(config.project, args.model, limit=args.limit)
            if not history:
                print(f"No history for model {args.model!r} in {config.project}")
                return 1
            print(f"\n{config.project} — {args.model} over time\n")
            print(
                text_table(
                    ["started", "run", "rank", "composite", "accuracy", "cost", "latency"],
                    [
                        [
                            row["started_at"][:19],
                            row["run_id"],
                            row["rank"] or "-",
                            f"{row['composite']:.3f}" if row["composite"] is not None else "—",
                            format_metric("accuracy", row["accuracy"]),
                            format_metric("cost", row["cost"]),
                            format_metric("latency", row["latency"]),
                        ]
                        for row in history
                    ],
                )
            )
            return 0

        runs = store.runs(project=config.project, limit=args.limit)
        if not runs:
            print(f"No runs recorded for {config.project}")
            return 1
        print(f"\n{config.project} — recent runs\n")
        print(
            text_table(
                ["started", "run", "status", "models", "tests", "calls", "winner", "spend"],
                [
                    [
                        r["started_at"][:19],
                        r["run_id"],
                        r["status"],
                        r["n_models"],
                        r["n_tests"],
                        r["n_results"] or 0,
                        r["winner"] or "—",
                        f"${r['total_cost_usd']:.4f}" if r["total_cost_usd"] else "—",
                    ]
                    for r in runs
                ],
            )
        )
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.path)
    if target.exists() and any(target.iterdir()) and not args.force:
        print(f"{target} is not empty (use --force to write into it anyway)", file=sys.stderr)
        return 1
    if not TEMPLATE_DIR.is_dir():
        print(f"template folder is missing: {TEMPLATE_DIR}", file=sys.stderr)
        return 1

    shutil.copytree(TEMPLATE_DIR, target, dirs_exist_ok=True)

    name = args.name or target.name
    config_path = target / "config.yaml"
    if config_path.is_file():
        text = config_path.read_text(encoding="utf-8")
        config_path.write_text(
            text.replace("project: my_project", f"project: {name}"), encoding="utf-8"
        )

    print(f"Created project {name} at {target}\n")
    for path in sorted(target.rglob("*")):
        if path.is_file():
            print(f"  {path.relative_to(target)}")
    print("\nNext:")
    print(f"  1. edit {target/'config.yaml'} — models, weights, constraints")
    print(f"  2. write your cases into {target/'tests.yaml'}")
    print(f"  3. arena evaluate --project {target}")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    from .connectors.pricing import PriceBook, build_price_book  # noqa: PLC0415

    if args.project:
        config = ProjectConfig.load(args.project)
        book = build_price_book(config)
        wanted = [(spec.model, resolve_provider(spec)) for spec in config.models]
    else:
        book = PriceBook()
        wanted = [(model, None) for model in book.known_models()]

    rows = []
    unpriced = []
    for model, provider in wanted:
        card = book.get(model, provider=provider)
        if not card.has_pricing:
            unpriced.append(model)
        rows.append(
            [
                model,
                card.provider or provider or "?",
                f"${card.input_usd_per_mtok:g}" if card.input_usd_per_mtok is not None else "?",
                f"${card.output_usd_per_mtok:g}" if card.output_usd_per_mtok is not None else "?",
                f"{card.context_tokens:,}" if card.context_tokens else "?",
                ", ".join(sorted(card.features)[:4]) or "—",
            ]
        )
    print()
    print(text_table(
        ["model", "provider", "in $/Mtok", "out $/Mtok", "context", "features"], rows
    ))
    print(f"  Catalog as of {book.as_of}. Verify against your provider's price list.")
    if unpriced:
        print(
            "\n  No pricing for: "
            + ", ".join(unpriced)
            + "\n  Cost is left out of their composite rather than guessed. Add prices under"
            "\n  `pricing.models.<id>` in your project config to include them —"
            "\n  or, for a `run:` target, return a `cost_usd` from the callable."
        )
    return 0


def cmd_scorers(args: argparse.Namespace) -> int:
    from .scorers.registry import ScorerRegistry, build_registry  # noqa: PLC0415

    registry = build_registry(ProjectConfig.load(args.project)) if args.project else ScorerRegistry()
    print()
    print(
        text_table(
            ["eval_type", "source", "what it does"],
            [
                [row["name"], Path(row["source"]).name if row["source"] != "builtin" else "builtin",
                 row["description"]]
                for row in registry.describe()
            ],
        )
    )
    return 0


def cmd_tests(args: argparse.Namespace) -> int:
    config = ProjectConfig.load(args.project)
    if args.tags:
        config.test_filter["tags"] = args.tags
    if args.limit:
        config.test_filter["limit"] = args.limit

    files = config.discover_test_files()
    cases = load_test_cases(
        files, default_eval_type=config.default_eval_type, test_filter=config.test_filter
    )
    print(f"\n{config.project}: {len(cases)} test case(s) from {len(files)} file(s)\n")
    print(
        text_table(
            ["id", "eval_type", "tags", "weight", "input"],
            [
                [
                    case.id,
                    case.eval_type,
                    ",".join(case.tags) or "—",
                    f"{case.weight:g}",
                    _clip(str(case.input), 52),
                ]
                for case in cases
            ],
        )
    )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    config = ProjectConfig.load(args.project)
    runner = ArenaRunner(config)
    skipped = runner.preflight()

    print(f"\n✓ config      {config.config_path or config.root}")
    print(f"✓ test cases  {len(runner.test_cases)}")
    print(f"✓ eval types  {', '.join(sorted({c.eval_type for c in runner.test_cases}))}")
    print(f"✓ scorers     {len(runner.registry.names)} registered")
    print(f"✓ models      {len(config.enabled_models)} enabled")

    for spec in config.enabled_models:
        card = runner.price_book.get(spec.model, provider=resolve_provider(spec))
        status = skipped.get(spec.key)
        marker = "!" if status else "✓"
        detail = status or ("priced" if card.has_pricing else "no pricing")
        print(f"  {marker} {spec.key:<24} {spec.model:<28} {detail}")

    if skipped:
        print(
            f"\n{len(skipped)} model(s) would be skipped for the reasons above "
            "(missing credentials, or an endpoint that is not reachable). "
            "Everything else is ready to run."
        )
    else:
        print("\nProject is valid and ready: arena evaluate --project " + str(args.project))
    return 0


# ---------------------------------------------------------------------------
# plumbing
# ---------------------------------------------------------------------------


def cmd_ui(args: argparse.Namespace) -> int:
    from .web.server import serve  # noqa: PLC0415 — pulls in the static assets

    serve(
        projects_dir=args.projects_dir,
        host=args.host,
        port=args.port,
        open_browser=not args.no_browser,
        verbose=args.verbose,
    )
    return 0


def _progress_printer():
    state = {"last": 0}

    def report(event: dict[str, Any]) -> None:
        kind = event.get("event")
        if kind == "run_start":
            skipped = event.get("skipped") or {}
            print(
                f"Running {event['planned']} call(s): {len(event['models'])} model(s) × "
                f"{event['tests']} test(s) × {event['trials']} trial(s)"
            )
            for key, reason in skipped.items():
                print(f"  skipping {key}: {reason}")
        elif kind == "call_complete":
            done, planned = event["completed"], event["planned"]
            result = event["result"]
            mark = {"ok": "·", "error": "!"}.get(result.status, "?")
            if result.status == "ok" and result.passed is False:
                mark = "x"
            sys_write = sys.stdout.write
            sys_write(mark)
            if done % 50 == 0 or done == planned:
                sys_write(f" {done}/{planned}\n")
            sys.stdout.flush()
            state["last"] = done
        elif kind == "run_complete":
            if state["last"] % 50 != 0:
                sys.stdout.write("\n")

    return report


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _confirm(question: str, assume_yes: bool) -> bool:
    """Ask before destroying something.

    A non-interactive stdin without --yes REFUSES rather than assuming yes. A
    script that deletes a project because nobody was there to answer is the
    worst available default.
    """
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print(
            "error: refusing to delete without confirmation.\n"
            "       stdin is not a terminal — pass --yes to confirm, "
            "or --dry-run to see the plan.",
            file=sys.stderr,
        )
        return False
    return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")


def _print_plan(plan: dict[str, Any]) -> None:
    paths = plan.get("paths") or plan.get("report_files") or []
    print("\n  This will remove:")
    for path in paths[:10]:
        print(f"    {path}")
    if len(paths) > 10:
        print(f"    … and {len(paths) - 10} more")
    if plan.get("runs_removed"):
        print(f"    {plan['runs_removed']} run(s) of history")
    if plan.get("results_removed"):
        print(f"    {plan['results_removed']} recorded call(s)")
    if plan.get("bytes"):
        print(f"    {plan['bytes'] / 1024:.0f} KB")
    print()


def cmd_projects(args: argparse.Namespace) -> int:
    from .service import projects as svc  # noqa: PLC0415

    rows = svc.list_projects(args.projects_dir, include_archived=args.all)
    if not rows:
        print(f"No projects in {Path(args.projects_dir).resolve()}.")
        print("Create one:  arena init projects/my_project")
        return 0
    print(f"\n  {'name':22} {'models':>7} {'runs':>6}  status")
    print(f"  {'-' * 22} {'-' * 7:>7} {'-' * 6:>6}  ------")
    for row in rows:
        status = "error" if row.get("error") else ("archived" if row.get("archived") else "")
        print(f"  {row['name']:22} {row.get('models', 0):>7} {row.get('runs', 0):>6}  {status}")
    print()
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    from .service import runs as svc  # noqa: PLC0415

    root = Path(args.project)
    rows = svc.list_runs(
        root.parent, root.name, limit=args.limit, include_deleted=args.all
    )
    if not rows:
        print("No runs yet.")
        return 0
    print(f"\n  {'run id':34} {'when':20} {'winner':16} {'cost':>9}  status")
    for row in rows:
        state = "deleted" if row.get("deleted_at") else (
            "archived" if row.get("archived_at") else row.get("status", "")
        )
        cost = row.get("total_cost_usd")
        label = row.get("label") or ""
        print(
            f"  {row['run_id']:34} {str(row.get('started_at', ''))[:19]:20} "
            f"{str(row.get('winner') or '—')[:16]:16} "
            f"{('$%.4f' % cost) if cost is not None else '—':>9}  {state} {label}"
        )
    print()
    return 0


def cmd_label(args: argparse.Namespace) -> int:
    from .service import runs as svc  # noqa: PLC0415

    root = Path(args.project)
    svc.label_run(root.parent, root.name, args.run_id, label=args.label, notes=args.notes)
    print(f"Labelled {args.run_id}.")
    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    from .service import projects as pj, runs as rn  # noqa: PLC0415

    archived = not args.undo
    if args.what == "project":
        pj.archive_project(args.projects_dir, args.name, archived)
    else:
        if not args.project:
            print("error: --project is required when archiving a run", file=sys.stderr)
            return 1
        root = Path(args.project)
        rn.archive_run(root.parent, root.name, args.name, archived)
    print(f"{'Archived' if archived else 'Unarchived'} {args.what} {args.name}.")
    return 0


def cmd_duplicate(args: argparse.Namespace) -> int:
    from .service import projects as svc  # noqa: PLC0415

    detail = svc.duplicate_project(args.projects_dir, args.name, args.new_name)
    print(f"Copied {args.name} to {detail['name']} (results not copied).")
    print(f"  arena evaluate --project {detail['path']}")
    return 0


def cmd_rm(args: argparse.Namespace) -> int:
    from .service import projects as pj, runs as rn  # noqa: PLC0415

    if args.what == "project":
        plan = pj.delete_project(
            args.projects_dir, args.name, keep_results=args.keep_results, dry_run=True
        )
        target = f"project {args.name!r}"
    else:
        if not args.project:
            print("error: --project is required when deleting a run", file=sys.stderr)
            return 1
        root = Path(args.project)
        plan = rn.delete_run(
            root.parent, root.name, args.name, hard=args.hard, dry_run=True
        )
        target = f"run {args.name!r}"

    _print_plan(plan)
    if args.dry_run:
        print("  (dry run — nothing was changed)")
        return 0
    if not _confirm(f"Delete {target}?", args.yes):
        print("Cancelled.")
        return 1

    if args.what == "project":
        pj.delete_project(args.projects_dir, args.name, keep_results=args.keep_results)
    else:
        root = Path(args.project)
        rn.delete_run(root.parent, root.name, args.name, hard=args.hard)
        if not args.hard:
            print("  (soft delete — `arena vacuum` removes it permanently)")
    print(f"Deleted {target}.")
    return 0


def cmd_vacuum(args: argparse.Namespace) -> int:
    from .service import runs as svc  # noqa: PLC0415

    root = Path(args.project)
    plan = svc.vacuum(root.parent, root.name, dry_run=True)
    if not plan["runs_removed"]:
        print("Nothing to reclaim — no deleted runs.")
        return 0
    print(f"\n  This will permanently remove {plan['runs_removed']} deleted run(s)")
    print(f"  and {plan['results_removed']} recorded call(s).\n")
    if args.dry_run:
        print("  (dry run — nothing was changed)")
        return 0
    if not _confirm("Permanently remove them?", args.yes):
        print("Cancelled.")
        return 1
    done = svc.vacuum(root.parent, root.name)
    freed = (done["bytes_before"] - (done["bytes_after"] or 0)) / 1024
    print(f"Removed {done['runs_removed']} run(s); reclaimed {freed:.0f} KB.")
    return 0


def cmd_providers(args: argparse.Namespace) -> int:
    from .service import providers as svc  # noqa: PLC0415

    action = getattr(args, "action", None) or "list"
    if action == "list":
        profiles = svc.user_providers()
        if not profiles:
            print("No provider profiles. Add one:")
            print("  arena providers add work --kind openai --api-key '${env:OPENAI_API_KEY}'")
            return 0
        print(f"\n  {'id':16} {'kind':20} {'base url':38} key")
        for profile in profiles:
            print(
                f"  {profile.id:16} {profile.kind:20} "
                f"{(profile.base_url or '—')[:38]:38} {profile.api_key_ref or '—'}"
            )
        print()
        return 0

    if action == "add":
        headers = {}
        for item in args.header:
            key, _, value = item.partition("=")
            if not value:
                print(f"error: --header must be KEY=VALUE, got {item!r}", file=sys.stderr)
                return 1
            headers[key.strip()] = value.strip()
        profile = svc.save_provider(
            {
                "id": args.id, "kind": args.kind, "base_url": args.base_url,
                "api_key": args.api_key, "headers": headers,
                "model_prefix": args.model_prefix,
            }
        )
        print(f"Saved provider {profile.id!r}.")
        if args.api_key and not args.api_key.startswith("${"):
            print(f"  The key went to your keyring; settings hold {profile.api_key_ref}")
        return 0

    if action == "test":
        report = svc.health_check(svc.get_provider(args.id))
        if report["ok"]:
            print(f"OK — {report['models_endpoint']} responded in {report['latency_ms']}ms")
            return 0
        print(f"Unreachable — {report['error'] or report['status']}", file=sys.stderr)
        return 1

    if action == "discover":
        models = svc.discover_models(svc.get_provider(args.id))
        if not models:
            print("No models reported. Many gateways do not implement /v1/models.")
            return 0
        for model in models:
            print(f"  {model}")
        return 0

    if action == "rm":
        plan = svc.delete_provider(args.id, purge_key=args.purge_key, dry_run=True)
        print(f"\n  This removes provider {args.id!r}"
              + (" and its stored key.\n" if args.purge_key else ".\n"))
        if not _confirm(f"Delete provider {args.id!r}?", args.yes):
            print("Cancelled.")
            return 1
        svc.delete_provider(args.id, purge_key=args.purge_key)
        print(f"Deleted provider {args.id!r}.")
        return 0

    print("usage: arena providers list|add|test|discover|rm", file=sys.stderr)
    return 1


def cmd_secrets(args: argparse.Namespace) -> int:
    from .service.providers import KEYRING_SERVICE  # noqa: PLC0415
    from .service.secrets import keyring_delete, keyring_get, keyring_set  # noqa: PLC0415

    action = getattr(args, "action", None)
    if action == "set":
        value = args.value
        if not value:
            if sys.stdin.isatty():
                import getpass  # noqa: PLC0415

                value = getpass.getpass(f"Value for {args.account}: ")
            else:
                value = sys.stdin.read().strip()
        if not value:
            print("error: no value given", file=sys.stderr)
            return 1
        keyring_set(KEYRING_SERVICE, args.account, value)
        print(f"Stored. Reference it as ${{keyring:{KEYRING_SERVICE}/{args.account}}}")
        return 0

    if action == "get":
        value = keyring_get(KEYRING_SERVICE, args.account)
        if value is None:
            print(f"No credential stored for {args.account!r}.", file=sys.stderr)
            return 1
        # Masked unless asked: this command gets run in shared terminals and
        # pasted into issues.
        print(value if args.reveal else "***")
        return 0

    if action == "rm":
        removed = keyring_delete(KEYRING_SERVICE, args.account)
        print("Deleted." if removed else "Nothing stored under that name.")
        return 0 if removed else 1

    print("usage: arena secrets set|get|rm <account>", file=sys.stderr)
    return 1


def cmd_config(args: argparse.Namespace) -> int:
    import json as _json  # noqa: PLC0415

    from .service import settings as svc  # noqa: PLC0415

    action = getattr(args, "action", None) or "get"
    if action == "get":
        data = svc.load()
        data.pop("providers", None)  # shown by `arena providers list`
        print(_json.dumps(data, indent=2))
        return 0
    if action == "set":
        raw = args.value
        try:
            value = _json.loads(raw)
        except _json.JSONDecodeError:
            value = raw  # a bare string is the common case
        svc.save({args.key: value})
        print(f"Set {args.key} = {value!r}")
        return 0
    if action == "reset":
        svc.reset([args.key] if args.key else None)
        print(f"Reset {args.key or 'all settings'}.")
        return 0
    print("usage: arena config get|set|reset", file=sys.stderr)
    return 1


def cmd_export(args: argparse.Namespace) -> int:
    from .service import export as svc  # noqa: PLC0415

    root = Path(args.project)
    if args.all:
        path = svc.export_all(root.parent, root.name, args.out)
    else:
        path = svc.export_run(root.parent, root.name, args.run_id, args.format, args.out)
    print(f"Wrote {path}")
    if args.format == "html" and not args.all:
        print("  A single self-contained file — no network needed to read it.")
    return 0


def cmd_env(args: argparse.Namespace) -> int:
    from .core.env import find_env_files  # noqa: PLC0415

    files = find_env_files(args.project)
    if not files:
        print("No .env files found.")
        print("  Looked in: ~/.config/agent-arena/.env and <project>/.env")
        return 0
    print("\n  .env files, nearest last (nearer wins):\n")
    for path in files:
        print(f"    {path}")
    print("\n  Values are not shown. A real environment variable always wins")
    print("  over a file, so an exported key beats a stale .env.\n")
    return 0


COMMANDS = {
    "evaluate": cmd_evaluate,
    "projects": cmd_projects,
    "runs": cmd_runs,
    "label": cmd_label,
    "archive": cmd_archive,
    "duplicate": cmd_duplicate,
    "rm": cmd_rm,
    "vacuum": cmd_vacuum,
    "export": cmd_export,
    "providers": cmd_providers,
    "secrets": cmd_secrets,
    "config": cmd_config,
    "env": cmd_env,
    "run": cmd_evaluate,
    "report": cmd_report,
    "history": cmd_history,
    "init": cmd_init,
    "models": cmd_models,
    "scorers": cmd_scorers,
    "tests": cmd_tests,
    "validate": cmd_validate,
    "ui": cmd_ui,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Load .env before anything reads a credential. Real environment variables
    # win, so an explicitly exported key always beats a stale file. Without
    # this, a UI launched from a desktop icon sees none of the keys set in a
    # shell profile and silently skips every real model.
    load_env(getattr(args, "project", None) or ".")

    if getattr(args, "version", False):
        from . import __version__  # noqa: PLC0415

        print(f"agent-arena {__version__}")
        return 0

    if not args.command:
        parser.print_help()
        return 1

    handler = COMMANDS[args.command]
    try:
        return handler(args)
    except ArenaError as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
