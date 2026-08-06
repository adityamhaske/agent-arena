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
from .core.errors import ArenaError
from .core.report import Report, format_metric, text_table, write_reports
from .connectors.registry import resolve_provider
from .core.runner import ArenaRunner
from .core.store import ResultStore
from .core.testcase import load_test_cases

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "projects" / "_template"


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
    runner = ArenaRunner(config, progress=progress)

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
        runs = store.runs(project=config.project, limit=50)
        if not runs:
            print(f"No runs recorded for {config.project} in {config.database}")
            return 1
        record = next((r for r in runs if r["run_id"] == args.run_id), runs[0]) if args.run_id else runs[0]
        if args.run_id and record["run_id"] != args.run_id:
            print(f"No run {args.run_id!r} in {config.database}", file=sys.stderr)
            return 1

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
                card.provider or "?",
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
            "\n  `pricing.models.<id>` in your project config to include them."
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


COMMANDS = {
    "evaluate": cmd_evaluate,
    "run": cmd_evaluate,
    "report": cmd_report,
    "history": cmd_history,
    "init": cmd_init,
    "models": cmd_models,
    "scorers": cmd_scorers,
    "tests": cmd_tests,
    "validate": cmd_validate,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

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
