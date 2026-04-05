"""Typer CLI entrypoint for the benchmark suite."""

from __future__ import annotations

from pathlib import Path

import typer

from logcrush_bench.console import console

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    help="Benchmark structure-aware log compression against standard baselines.",
)


def _validate_selection(dataset: str | None, all_datasets: bool) -> None:
    """Validate dataset selection flags."""

    if bool(dataset) == all_datasets:
        raise typer.BadParameter("Choose exactly one of --dataset or --all.")


@app.command()
def download(
    dataset: str | None = typer.Option(None, "--dataset", help="Dataset id to download."),
    all_datasets: bool = typer.Option(False, "--all", help="Download every supported dataset."),
) -> None:
    """Download and normalize one or more datasets."""

    _validate_selection(dataset, all_datasets)
    from logcrush_bench.datasets import download_and_normalize_datasets

    datasets = download_and_normalize_datasets(dataset_ids=None if all_datasets else [dataset])
    for item in datasets:
        console.print(
            f"[green]ready[/green] {item.id} "
            f"lines={item.line_count} bytes={item.byte_size} "
            f"path={item.raw_path}"
        )


@app.command()
def run(
    dataset: str | None = typer.Option(None, "--dataset", help="Dataset id to benchmark."),
    all_datasets: bool = typer.Option(False, "--all", help="Benchmark every supported dataset."),
    method: str | None = typer.Option(None, "--method", help="Benchmark a single method."),
    all_methods: bool = typer.Option(False, "--all-methods", help="Benchmark every method."),
) -> None:
    """Run the benchmark harness."""

    _validate_selection(dataset, all_datasets)
    if bool(method) == all_methods:
        raise typer.BadParameter("Choose exactly one of --method or --all-methods.")

    from logcrush_bench.benchmark import run_benchmarks

    results = run_benchmarks(
        dataset_ids=None if all_datasets else [dataset],
        methods=None if all_methods else [method],
    )
    for result in results:
        console.print(
            f"[cyan]{result.dataset_id}[/cyan] "
            f"{result.method} ratio={result.compression_ratio:.2f} "
            f"verified={result.roundtrip_verified}"
        )


@app.command()
def report(
    results_path: Path = typer.Option(
        Path("results/results.json"),
        "--results-path",
        help="Path to the stored benchmark results JSON file.",
    ),
) -> None:
    """Generate summary Markdown and charts from recorded results."""

    from logcrush_bench.report import generate_report

    generate_report(results_path=results_path)
    console.print(f"[green]report generated[/green] from {results_path}")


@app.command()
def verify(
    suite: str = typer.Option(
        "full",
        "--suite",
        help="Verification target: full or smoke.",
    ),
    results_path: Path = typer.Option(
        Path("results/results.json"),
        "--results-path",
        help="Path to the stored benchmark results JSON file.",
    ),
    since: str | None = typer.Option(
        None,
        "--since",
        help="Only consider results written at or after this ISO-8601 timestamp.",
    ),
) -> None:
    """Verify that expected benchmark results exist and passed roundtrip validation."""

    from logcrush_bench.verification import (
        VerificationError,
        parse_since_timestamp,
        verify_suite_results,
    )

    try:
        summary = verify_suite_results(
            results_path=results_path,
            suite=suite,
            since=parse_since_timestamp(since),
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except VerificationError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]verified[/green] suite={summary.suite} "
        f"results={summary.expected_result_count} path={summary.results_path}"
    )


def main() -> None:
    """Run the CLI application."""

    app()


if __name__ == "__main__":
    main()
