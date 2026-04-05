"""Benchmark harness for LogCrush and baseline compressors."""

from __future__ import annotations

import json
import resource
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Callable

from rich.table import Table

from logcrush_bench.baselines.gzip_baseline import compress_gzip, decompress_gzip
from logcrush_bench.baselines.zstd_baseline import (
    compress_zstd,
    decompress_zstd,
    train_zstd_dictionary,
)
from logcrush_bench.console import console
from logcrush_bench.definitions import BenchmarkResult, list_benchmark_methods
from logcrush_bench.datasets import get_dataset, get_supported_dataset_ids
from logcrush_bench.engine_client import benchmark_with_engine

DEFAULT_RESULTS_PATH = Path("results/results.json")


@dataclass(slots=True)
class _RunSample:
    """One timing sample for a benchmark method."""

    compressed_bytes: int
    compress_time_sec: float
    decompress_time_sec: float
    roundtrip_verified: bool
    peak_memory_mb: float
    template_count: int | None
    stage_breakdown: dict[str, int] | None


def run_benchmarks(
    dataset_ids: list[str] | None = None,
    methods: list[str] | None = None,
    results_path: Path = DEFAULT_RESULTS_PATH,
) -> list[BenchmarkResult]:
    """Benchmark selected methods across one or more normalized datasets."""

    active_dataset_ids = dataset_ids or get_supported_dataset_ids()
    active_methods = methods or list_benchmark_methods()

    results: list[BenchmarkResult] = []
    for dataset_id in active_dataset_ids:
        dataset = get_dataset(dataset_id)
        if dataset.normalized_path is None or not dataset.normalized_path.exists():
            raise FileNotFoundError(
                f"Normalized dataset not found for {dataset_id}. Run `logcrush-bench download` first."
            )

        raw_size = dataset.normalized_path.stat().st_size
        raw_bytes: bytes | None = None
        raw_lines: list[str] | None = None
        for method in active_methods:
            if method == "logcrush":
                result = benchmark_with_engine(
                    dataset_id=dataset.id,
                    dataset_path=dataset.normalized_path,
                    raw_bytes=raw_size,
                )
            else:
                if method == "clp-basic" and raw_lines is None:
                    raw_lines = dataset.normalized_path.read_text(
                        encoding="utf-8",
                        errors="surrogateescape",
                    ).splitlines()
                if method != "clp-basic" and raw_bytes is None:
                    raw_bytes = dataset.normalized_path.read_bytes()
                result = _benchmark_method(
                    dataset_id=dataset.id,
                    method=method,
                    raw_size=raw_size,
                    raw_bytes=raw_bytes,
                    raw_lines=raw_lines,
                )
            results.append(result)
            _persist_results([result], results_path)
            console.print(
                f"[green]completed[/green] {dataset.id} {method} "
                f"ratio={result.compression_ratio:.2f} verified={result.roundtrip_verified}"
            )

    _render_results(results)
    return results


def _benchmark_method(
    dataset_id: str,
    method: str,
    raw_size: int,
    raw_bytes: bytes | None,
    raw_lines: list[str] | None,
) -> BenchmarkResult:
    """Benchmark one method on one dataset."""

    if method == "logcrush":
        raise ValueError("The proprietary LogCrush engine is benchmarked via engine_client.")

    samples = [
        _run_single_sample(method=method, raw_bytes=raw_bytes, raw_lines=raw_lines)
        for _ in range(3)
    ]
    compress_times = [sample.compress_time_sec for sample in samples]
    decompress_times = [sample.decompress_time_sec for sample in samples]
    peak_memories = [sample.peak_memory_mb for sample in samples]
    compressed_bytes = samples[0].compressed_bytes
    template_count = samples[0].template_count
    stage_breakdown = samples[0].stage_breakdown
    roundtrip_verified = all(sample.roundtrip_verified for sample in samples)

    compress_time = median(compress_times)
    decompress_time = median(decompress_times)
    peak_memory = median(peak_memories)
    compression_ratio = raw_size / compressed_bytes if compressed_bytes else 0.0
    space_saving_pct = (1 - (compressed_bytes / raw_size)) * 100 if raw_size else 0.0

    return BenchmarkResult(
        dataset_id=dataset_id,
        method=method,
        raw_bytes=raw_size,
        compressed_bytes=compressed_bytes,
        compression_ratio=compression_ratio,
        space_saving_pct=space_saving_pct,
        compress_time_sec=compress_time,
        decompress_time_sec=decompress_time,
        compress_throughput_mbps=_throughput_mb_per_sec(raw_size, compress_time),
        decompress_throughput_mbps=_throughput_mb_per_sec(raw_size, decompress_time),
        roundtrip_verified=roundtrip_verified,
        peak_memory_mb=peak_memory,
        template_count=template_count,
        stage_breakdown=stage_breakdown,
    )


def _run_single_sample(
    method: str,
    raw_bytes: bytes | None,
    raw_lines: list[str] | None,
) -> _RunSample:
    """Execute one compress/decompress measurement for a method."""

    compress_fn, decompress_fn = _method_handlers(method, raw_bytes, raw_lines)
    rss_before = _current_rss_mb()
    start = perf_counter()
    compressed, template_count, stage_breakdown = compress_fn()
    compress_time = perf_counter() - start

    start = perf_counter()
    restored = decompress_fn(compressed)
    decompress_time = perf_counter() - start
    rss_after = _current_rss_mb()

    if isinstance(restored, bytes):
        if raw_bytes is None:
            raise ValueError(f"raw_bytes is required for method {method}")
        roundtrip_verified = restored == raw_bytes
    else:
        if raw_lines is None:
            raise ValueError(f"raw_lines is required for method {method}")
        roundtrip_verified = restored == raw_lines

    if not roundtrip_verified:
        console.print(f"[bold red]roundtrip mismatch[/bold red] for method {method}")

    return _RunSample(
        compressed_bytes=len(compressed),
        compress_time_sec=compress_time,
        decompress_time_sec=decompress_time,
        roundtrip_verified=roundtrip_verified,
        peak_memory_mb=max(rss_before, rss_after),
        template_count=template_count,
        stage_breakdown=stage_breakdown,
    )


def _method_handlers(
    method: str,
    raw_bytes: bytes | None,
    raw_lines: list[str] | None,
) -> tuple[
    Callable[[], tuple[bytes, int | None, dict[str, int] | None]],
    Callable[[bytes], bytes | list[str]],
]:
    """Return compress/decompress callables for a method name."""

    if method == "clp-basic":
        if raw_lines is None:
            raise ValueError("raw_lines is required for clp-basic benchmarks")
        try:
            from logcrush_bench.baselines.clp_baseline import CLPBaselineCompressor
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "clp-basic requires the project dependencies to be installed."
            ) from exc
        compressor = CLPBaselineCompressor()

        def compress() -> tuple[bytes, int | None, dict[str, int] | None]:
            artifact = compressor.compress_with_metrics(raw_lines)
            return artifact.data, artifact.template_count, None

        return compress, compressor.decompress

    if method == "gzip-6":
        if raw_bytes is None:
            raise ValueError("raw_bytes is required for gzip-6 benchmarks")
        return (
            lambda: (compress_gzip(raw_bytes, level=6), None, None),
            decompress_gzip,
        )
    if method == "gzip-9":
        if raw_bytes is None:
            raise ValueError("raw_bytes is required for gzip-9 benchmarks")
        return (
            lambda: (compress_gzip(raw_bytes, level=9), None, None),
            decompress_gzip,
        )
    if method.startswith("zstd-") and method != "zstd-dict":
        if raw_bytes is None:
            raise ValueError(f"raw_bytes is required for {method} benchmarks")
        level = int(method.split("-", maxsplit=1)[1])
        return (
            lambda: (compress_zstd(raw_bytes, level=level), None, None),
            decompress_zstd,
        )
    if method == "zstd-dict":
        if raw_bytes is None:
            raise ValueError("raw_bytes is required for zstd-dict benchmarks")
        dictionary = train_zstd_dictionary(raw_bytes)
        return (
            lambda: (compress_zstd(raw_bytes, level=3, dictionary=dictionary), None, None),
            lambda data: decompress_zstd(data, dictionary=dictionary),
        )

    supported = ", ".join(list_benchmark_methods())
    raise ValueError(f"Unsupported method '{method}'. Supported: {supported}")


def _persist_results(results: list[BenchmarkResult], results_path: Path) -> None:
    """Append benchmark results into the JSON result store."""

    results_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _load_results_store(results_path)
    timestamp = datetime.now(tz=UTC).isoformat()
    for result in results:
        key = f"{result.dataset_id}|{result.method}|{timestamp}"
        payload[key] = asdict(result)
    results_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _load_results_store(results_path: Path) -> dict[str, object]:
    """Load an existing result store or return an empty mapping."""

    if not results_path.exists():
        return {}
    return json.loads(results_path.read_text(encoding="utf-8"))


def _render_results(results: list[BenchmarkResult]) -> None:
    """Render benchmark results to stdout as a compact rich table."""

    table = Table(title="Benchmark Results")
    table.add_column("Dataset")
    table.add_column("Method")
    table.add_column("Ratio", justify="right")
    table.add_column("Comp MB/s", justify="right")
    table.add_column("Decomp MB/s", justify="right")
    table.add_column("Verified", justify="center")
    for result in results:
        table.add_row(
            result.dataset_id,
            result.method,
            f"{result.compression_ratio:.2f}",
            f"{result.compress_throughput_mbps:.2f}",
            f"{result.decompress_throughput_mbps:.2f}",
            "yes" if result.roundtrip_verified else "no",
        )
    console.print(table)


def _current_rss_mb() -> float:
    """Return current ru_maxrss expressed in megabytes."""

    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return usage / 1024.0


def _throughput_mb_per_sec(byte_count: int, seconds: float) -> float:
    """Compute throughput in MiB/s."""

    if seconds <= 0:
        return 0.0
    return (byte_count / (1024 * 1024)) / seconds
