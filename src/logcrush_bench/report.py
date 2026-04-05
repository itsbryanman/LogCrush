"""Generate Markdown summaries and charts from benchmark results."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from logcrush_bench.console import console
from logcrush_bench.definitions import (
    BenchmarkResult,
    list_benchmark_methods,
    list_supported_dataset_ids,
)
from logcrush_bench.results_store import load_latest_results

METHOD_ORDER = [
    "gzip-6",
    "gzip-9",
    "zstd-1",
    "zstd-3",
    "zstd-9",
    "zstd-19",
    "zstd-dict",
    "clp-basic",
    "logcrush",
]

SUMMARY_METHODS = [
    "gzip-9",
    "zstd-3",
    "zstd-19",
    "zstd-dict",
    "clp-basic",
    "logcrush",
]

METHOD_COLORS = {
    "logcrush": "#2563EB",
    "clp-basic": "#7C3AED",
    "zstd-1": "#D1D5DB",
    "zstd-3": "#9CA3AF",
    "zstd-9": "#6B7280",
    "zstd-19": "#4B5563",
    "zstd-dict": "#9CA3AF",
    "gzip-6": "#FBBF24",
    "gzip-9": "#F59E0B",
}


def generate_report(results_path: Path = Path("results/results.json")) -> None:
    """Generate the Markdown summary and PNG charts from the latest results."""

    latest = load_latest_results(results_path)
    if not latest:
        raise FileNotFoundError(f"No benchmark results found at {results_path}")

    output_dir = results_path.parent
    charts_dir = output_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "summary.md"
    summary_path.write_text(build_summary_markdown(latest), encoding="utf-8")

    plt.style.use("seaborn-v0_8-whitegrid")
    generate_compression_ratio_chart(latest, charts_dir / "compression_ratio_by_dataset.png")
    generate_throughput_chart(latest, charts_dir / "throughput_by_dataset.png")
    generate_breakdown_chart(latest, charts_dir / "breakdown_by_stage.png")
    generate_savings_chart(latest, charts_dir / "savings_vs_zstd.png")
    console.print(f"[green]summary written[/green] {summary_path}")


def build_summary_markdown(latest: dict[str, dict[str, BenchmarkResult]]) -> str:
    """Build the Markdown summary table."""

    headers = [
        "Dataset",
        "Raw Size",
        "gzip-9",
        "zstd-3",
        "zstd-19",
        "zstd-dict",
        "CLP-basic",
        "LogCrush",
        "LC vs zstd-3",
    ]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]

    for dataset_id in _dataset_order(latest):
        methods = latest[dataset_id]
        raw_size = next(iter(methods.values())).raw_bytes
        gzip_9 = methods.get("gzip-9")
        zstd_3 = methods.get("zstd-3")
        zstd_19 = methods.get("zstd-19")
        zstd_dict = methods.get("zstd-dict")
        clp = methods.get("clp-basic")
        logcrush = methods.get("logcrush")
        savings = ""
        if logcrush and zstd_3:
            savings_value = ((logcrush.compressed_bytes / zstd_3.compressed_bytes) - 1) * 100
            savings = f"{savings_value:.1f}%"
        lines.append(
            "| "
            + " | ".join(
                [
                    dataset_id.upper(),
                    human_bytes(raw_size),
                    _summary_cell(gzip_9),
                    _summary_cell(zstd_3),
                    _summary_cell(zstd_19),
                    _summary_cell(zstd_dict),
                    _summary_cell(clp),
                    _summary_cell(logcrush),
                    savings,
                ]
            )
            + " |"
        )

    return "\n".join(lines) + "\n"


def generate_compression_ratio_chart(
    latest: dict[str, dict[str, BenchmarkResult]],
    output_path: Path,
) -> None:
    """Generate grouped compression ratio bars."""

    datasets = _dataset_order(latest)
    methods = _available_methods(latest)
    if not datasets or not methods:
        return

    fig, ax = plt.subplots(figsize=(14, 6))
    x_positions = list(range(len(datasets)))
    bar_width = 0.8 / max(len(methods), 1)
    for index, method in enumerate(methods):
        values = [
            latest[dataset].get(method).compression_ratio if method in latest[dataset] else 0.0
            for dataset in datasets
        ]
        offsets = [x + (index - (len(methods) - 1) / 2) * bar_width for x in x_positions]
        ax.bar(
            offsets,
            values,
            width=bar_width,
            label=method,
            color=METHOD_COLORS.get(method, "#6B7280"),
        )

    ax.set_xticks(x_positions, [dataset.upper() for dataset in datasets], rotation=20)
    ax.set_ylabel("Compression ratio")
    ax.set_title("Compression Ratio by Dataset")
    ax.legend(ncols=3, fontsize=9)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def generate_throughput_chart(
    latest: dict[str, dict[str, BenchmarkResult]],
    output_path: Path,
) -> None:
    """Generate side-by-side throughput charts."""

    datasets = _dataset_order(latest)
    methods = _available_methods(latest)
    if not datasets or not methods:
        return

    fig, axes = plt.subplots(1, 2, figsize=(16, 6), sharey=False)
    metrics = [
        ("compress_throughput_mbps", "Compress Throughput (MiB/s)"),
        ("decompress_throughput_mbps", "Decompress Throughput (MiB/s)"),
    ]
    x_positions = list(range(len(datasets)))
    bar_width = 0.8 / max(len(methods), 1)

    for axis, (field, title) in zip(axes, metrics):
        for index, method in enumerate(methods):
            values = [
                getattr(latest[dataset].get(method), field) if method in latest[dataset] else 0.0
                for dataset in datasets
            ]
            offsets = [x + (index - (len(methods) - 1) / 2) * bar_width for x in x_positions]
            axis.bar(
                offsets,
                values,
                width=bar_width,
                label=method,
                color=METHOD_COLORS.get(method, "#6B7280"),
            )
        axis.set_xticks(x_positions, [dataset.upper() for dataset in datasets], rotation=20)
        axis.set_title(title)

    axes[0].legend(ncols=3, fontsize=9)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def generate_breakdown_chart(
    latest: dict[str, dict[str, BenchmarkResult]],
    output_path: Path,
) -> None:
    """Generate a stacked stage breakdown chart for LogCrush."""

    datasets = [dataset for dataset in _dataset_order(latest) if "logcrush" in latest[dataset]]
    if not datasets:
        return

    template_sizes = []
    column_sizes = []
    overhead_sizes = []
    for dataset in datasets:
        breakdown = latest[dataset]["logcrush"].stage_breakdown or {}
        template_sizes.append(breakdown.get("template_dict", 0))
        column_sizes.append(breakdown.get("column_data", 0))
        overhead_sizes.append(breakdown.get("overhead", 0))

    fig, ax = plt.subplots(figsize=(12, 6))
    x_positions = list(range(len(datasets)))
    ax.bar(x_positions, template_sizes, label="template_dict", color="#2563EB")
    ax.bar(x_positions, column_sizes, bottom=template_sizes, label="column_data", color="#7C3AED")
    bottoms = [template + column for template, column in zip(template_sizes, column_sizes)]
    ax.bar(x_positions, overhead_sizes, bottom=bottoms, label="overhead", color="#9CA3AF")
    ax.set_xticks(x_positions, [dataset.upper() for dataset in datasets], rotation=20)
    ax.set_ylabel("Bytes")
    ax.set_title("LogCrush Byte Breakdown")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def generate_savings_chart(
    latest: dict[str, dict[str, BenchmarkResult]],
    output_path: Path,
) -> None:
    """Generate a savings-vs-zstd-3 horizontal bar chart."""

    datasets = [
        dataset
        for dataset in _dataset_order(latest)
        if "logcrush" in latest[dataset] and "zstd-3" in latest[dataset]
    ]
    if not datasets:
        return

    savings = [
        (
            1
            - (
                latest[dataset]["logcrush"].compressed_bytes
                / latest[dataset]["zstd-3"].compressed_bytes
            )
        )
        * 100
        for dataset in datasets
    ]
    colors = ["#16A34A" if value >= 45 else "#F97316" for value in savings]

    fig, ax = plt.subplots(figsize=(10, 6))
    y_positions = list(range(len(datasets)))
    ax.barh(y_positions, savings, color=colors)
    ax.set_yticks(y_positions, [dataset.upper() for dataset in datasets])
    ax.set_xlabel("Savings vs zstd-3 (%)")
    ax.set_title("LogCrush Savings vs zstd-3")
    ax.axvline(45, color="#111827", linestyle="--", linewidth=1)
    ax.text(45.5, len(datasets) - 0.5, "Target threshold", color="#111827")
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def human_bytes(value: int) -> str:
    """Format a byte count in human-readable units."""

    suffixes = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    suffix = suffixes[0]
    for suffix in suffixes:
        if size < 1024 or suffix == suffixes[-1]:
            break
        size /= 1024
    return f"{size:.2f} {suffix}"


def _summary_cell(result: BenchmarkResult | None) -> str:
    """Format a compressed size summary cell."""

    return human_bytes(result.compressed_bytes) if result is not None else ""


def _dataset_order(latest: dict[str, dict[str, BenchmarkResult]]) -> list[str]:
    """Return datasets in canonical supported order when present."""

    supported = list_supported_dataset_ids()
    return [dataset for dataset in supported if dataset in latest] + [
        dataset for dataset in sorted(latest) if dataset not in supported
    ]


def _available_methods(latest: dict[str, dict[str, BenchmarkResult]]) -> list[str]:
    """Return methods present in the latest results, ordered consistently."""

    present = {method for dataset in latest.values() for method in dataset}
    ordered = [method for method in METHOD_ORDER if method in present]
    extras = [
        method for method in list_benchmark_methods() if method in present and method not in ordered
    ]
    return ordered + extras
