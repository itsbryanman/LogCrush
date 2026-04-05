"""Tests for benchmark result verification helpers."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from logcrush_bench.definitions import BenchmarkResult, list_benchmark_methods
from logcrush_bench.verification import VerificationError, verify_suite_results


def _build_result(method: str, *, verified: bool = True) -> BenchmarkResult:
    """Create a minimal benchmark result for verification tests."""

    return BenchmarkResult(
        dataset_id="linux",
        method=method,
        raw_bytes=1024,
        compressed_bytes=512,
        compression_ratio=2.0,
        space_saving_pct=50.0,
        compress_time_sec=1.0,
        decompress_time_sec=1.0,
        compress_throughput_mbps=1.0,
        decompress_throughput_mbps=1.0,
        roundtrip_verified=verified,
        peak_memory_mb=64.0,
        template_count=None,
        stage_breakdown=None,
    )


def _write_results(
    path: Path,
    *,
    timestamp: datetime,
    unverified_methods: set[str] | None = None,
    omitted_methods: set[str] | None = None,
) -> None:
    """Write a synthetic result store for the Linux smoke suite."""

    payload: dict[str, dict[str, object]] = {}
    for method in list_benchmark_methods():
        if omitted_methods and method in omitted_methods:
            continue
        payload[f"linux|{method}|{timestamp.isoformat()}"] = asdict(
            _build_result(
                method,
                verified=method not in (unverified_methods or set()),
            )
        )
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def test_verify_suite_results_passes_for_complete_smoke_run(tmp_path: Path) -> None:
    """Smoke verification should pass when every expected result is present and verified."""

    results_path = tmp_path / "results.json"
    run_started_at = datetime.now(timezone.utc)
    _write_results(results_path, timestamp=run_started_at + timedelta(seconds=1))

    summary = verify_suite_results(results_path, suite="smoke", since=run_started_at)

    assert summary.suite == "smoke"
    assert summary.expected_result_count == len(list_benchmark_methods())


def test_verify_suite_results_fails_for_unverified_result(tmp_path: Path) -> None:
    """Verification should fail loudly when any result is unverified."""

    results_path = tmp_path / "results.json"
    run_started_at = datetime.now(timezone.utc)
    _write_results(
        results_path,
        timestamp=run_started_at + timedelta(seconds=1),
        unverified_methods={"logcrush"},
    )

    with pytest.raises(VerificationError, match="roundtrip_verified != True"):
        verify_suite_results(results_path, suite="smoke", since=run_started_at)


def test_verify_suite_results_ignores_stale_results_before_since(tmp_path: Path) -> None:
    """Older results should not satisfy the current run's verification gate."""

    results_path = tmp_path / "results.json"
    old_timestamp = datetime.now(timezone.utc) - timedelta(minutes=5)
    _write_results(results_path, timestamp=old_timestamp)

    with pytest.raises(VerificationError, match="No benchmark results found"):
        verify_suite_results(results_path, suite="smoke", since=datetime.now(timezone.utc))
