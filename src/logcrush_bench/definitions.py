"""Lightweight benchmark metadata and result schema definitions."""

from __future__ import annotations

from dataclasses import dataclass

BENCHMARK_METHODS = (
    "logcrush",
    "clp-basic",
    "gzip-6",
    "gzip-9",
    "zstd-1",
    "zstd-3",
    "zstd-9",
    "zstd-19",
    "zstd-dict",
)

SUPPORTED_DATASET_IDS = (
    "hdfs",
    "apache",
    "thunderbird",
    "bgl",
    "linux",
    "spark",
    "windows",
    "openstack",
)

SMOKE_DATASET_IDS = ("linux",)


@dataclass(slots=True)
class BenchmarkResult:
    """One benchmark result row for one dataset and one method."""

    dataset_id: str
    method: str
    raw_bytes: int
    compressed_bytes: int
    compression_ratio: float
    space_saving_pct: float
    compress_time_sec: float
    decompress_time_sec: float
    compress_throughput_mbps: float
    decompress_throughput_mbps: float
    roundtrip_verified: bool
    peak_memory_mb: float
    template_count: int | None
    stage_breakdown: dict[str, int] | None


def list_benchmark_methods() -> list[str]:
    """Return the supported benchmark method identifiers."""

    return list(BENCHMARK_METHODS)


def list_supported_dataset_ids() -> list[str]:
    """Return the supported dataset identifiers in deterministic order."""

    return list(SUPPORTED_DATASET_IDS)
