"""Thin client for the separately distributed proprietary LogCrush engine."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from logcrush_bench.definitions import BenchmarkResult

ENGINE_BINARY_ENV = "LOGCRUSH_ENGINE_BIN"
ENGINE_BINARY_NAME = "logcrush-engine"


class EngineClientError(RuntimeError):
    """Raised when the proprietary engine binary is missing or returns invalid output."""


@dataclass(slots=True)
class EngineBenchmarkMetrics:
    """Metrics returned by the proprietary engine binary."""

    compressed_bytes: int
    compress_time_sec: float
    decompress_time_sec: float
    peak_memory_mb: float
    roundtrip_verified: bool
    template_count: int | None
    stage_breakdown: dict[str, int] | None


def resolve_engine_binary() -> Path:
    """Resolve the proprietary engine binary from the environment or PATH."""

    configured = os.environ.get(ENGINE_BINARY_ENV)
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
        raise EngineClientError(
            f"{ENGINE_BINARY_ENV} points to a non-executable path: {candidate}"
        )

    discovered = shutil.which(ENGINE_BINARY_NAME)
    if discovered is not None:
        return Path(discovered)

    raise EngineClientError(
        "Proprietary engine binary not found. Set LOGCRUSH_ENGINE_BIN or run ./reproduce.sh "
        "to download the official release asset."
    )


def benchmark_with_engine(
    dataset_id: str,
    dataset_path: Path,
    raw_bytes: int,
    iterations: int = 3,
) -> BenchmarkResult:
    """Run the proprietary engine benchmark command for one normalized dataset file."""

    engine_binary = resolve_engine_binary()
    with TemporaryDirectory(prefix="logcrush-engine-") as tmp_dir:
        metrics_path = Path(tmp_dir) / "metrics.json"
        command = [
            str(engine_binary),
            "benchmark-file",
            "--input",
            str(dataset_path),
            "--dataset-id",
            dataset_id,
            "--iterations",
            str(iterations),
            "--json-output",
            str(metrics_path),
        ]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )

        if completed.returncode != 0:
            raise EngineClientError(
                f"Engine command failed: {shlex.join(command)}\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )
        if not metrics_path.exists():
            raise EngineClientError(
                f"Engine command did not write metrics JSON: {metrics_path}"
            )
        metrics = _load_metrics(metrics_path)

    compression_ratio = raw_bytes / metrics.compressed_bytes if metrics.compressed_bytes else 0.0
    space_saving_pct = (
        (1 - (metrics.compressed_bytes / raw_bytes)) * 100 if raw_bytes else 0.0
    )
    return BenchmarkResult(
        dataset_id=dataset_id,
        method="logcrush",
        raw_bytes=raw_bytes,
        compressed_bytes=metrics.compressed_bytes,
        compression_ratio=compression_ratio,
        space_saving_pct=space_saving_pct,
        compress_time_sec=metrics.compress_time_sec,
        decompress_time_sec=metrics.decompress_time_sec,
        compress_throughput_mbps=_throughput_mb_per_sec(raw_bytes, metrics.compress_time_sec),
        decompress_throughput_mbps=_throughput_mb_per_sec(
            raw_bytes,
            metrics.decompress_time_sec,
        ),
        roundtrip_verified=metrics.roundtrip_verified,
        peak_memory_mb=metrics.peak_memory_mb,
        template_count=metrics.template_count,
        stage_breakdown=metrics.stage_breakdown,
    )


def _load_metrics(metrics_path: Path) -> EngineBenchmarkMetrics:
    """Load and validate the metrics JSON produced by the proprietary engine."""

    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    stage_breakdown = payload.get("stage_breakdown")
    normalized_breakdown: dict[str, int] | None = None
    if stage_breakdown is not None:
        if not isinstance(stage_breakdown, dict):
            raise EngineClientError("Engine metrics field 'stage_breakdown' must be an object.")
        normalized_breakdown = {
            str(key): int(value) for key, value in stage_breakdown.items()
        }

    return EngineBenchmarkMetrics(
        compressed_bytes=_require_int(payload, "compressed_bytes"),
        compress_time_sec=_require_float(payload, "compress_time_sec"),
        decompress_time_sec=_require_float(payload, "decompress_time_sec"),
        peak_memory_mb=_require_float(payload, "peak_memory_mb"),
        roundtrip_verified=_require_bool(payload, "roundtrip_verified"),
        template_count=_optional_int(payload, "template_count"),
        stage_breakdown=normalized_breakdown,
    )


def _require_int(payload: dict[str, object], key: str) -> int:
    """Require an integer field from engine metrics."""

    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise EngineClientError(f"Engine metrics field '{key}' must be an integer.")
    return value


def _optional_int(payload: dict[str, object], key: str) -> int | None:
    """Require an optional integer field from engine metrics."""

    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise EngineClientError(f"Engine metrics field '{key}' must be an integer or null.")
    return value


def _require_float(payload: dict[str, object], key: str) -> float:
    """Require a numeric field from engine metrics."""

    value = payload.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise EngineClientError(f"Engine metrics field '{key}' must be numeric.")
    return float(value)


def _require_bool(payload: dict[str, object], key: str) -> bool:
    """Require a boolean field from engine metrics."""

    value = payload.get(key)
    if not isinstance(value, bool):
        raise EngineClientError(f"Engine metrics field '{key}' must be boolean.")
    return value


def _throughput_mb_per_sec(byte_count: int, seconds: float) -> float:
    """Compute throughput in MiB/s."""

    if seconds <= 0:
        return 0.0
    return (byte_count / (1024 * 1024)) / seconds
