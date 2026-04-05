"""Helpers for verifying benchmark result coverage and roundtrip status."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from logcrush_bench.definitions import (
    SMOKE_DATASET_IDS,
    list_benchmark_methods,
    list_supported_dataset_ids,
)
from logcrush_bench.results_store import load_latest_results


class VerificationError(RuntimeError):
    """Raised when expected benchmark results are missing or invalid."""


@dataclass(slots=True)
class VerificationSummary:
    """Summary of a successful benchmark verification pass."""

    suite: str
    dataset_ids: list[str]
    methods: list[str]
    results_path: Path
    since: datetime | None

    @property
    def expected_result_count(self) -> int:
        """Return the number of dataset/method rows that were verified."""

        return len(self.dataset_ids) * len(self.methods)


def parse_since_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp string used to scope verification."""

    if value is None:
        return None

    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO-8601 timestamp: {value}") from exc


def expected_dataset_ids_for_suite(suite: str) -> list[str]:
    """Return the expected dataset ids for a named verification suite."""

    normalized_suite = suite.lower()
    if normalized_suite == "smoke":
        return list(SMOKE_DATASET_IDS)
    if normalized_suite == "full":
        return list_supported_dataset_ids()

    supported = ", ".join(["smoke", "full"])
    raise ValueError(f"Unsupported suite '{suite}'. Supported: {supported}")


def verify_suite_results(
    results_path: Path,
    suite: str,
    since: datetime | None = None,
) -> VerificationSummary:
    """Verify that a benchmark suite wrote complete, roundtrip-verified results."""

    dataset_ids = expected_dataset_ids_for_suite(suite)
    methods = list_benchmark_methods()
    latest = load_latest_results(results_path, since=since)
    if not latest:
        qualifier = f" at or after {since.isoformat()}" if since is not None else ""
        raise VerificationError(f"No benchmark results found in {results_path}{qualifier}.")

    missing: list[str] = []
    unverified: list[str] = []
    for dataset_id in dataset_ids:
        method_map = latest.get(dataset_id, {})
        for method in methods:
            result = method_map.get(method)
            if result is None:
                missing.append(f"{dataset_id}/{method}")
                continue
            if result.roundtrip_verified is not True:
                unverified.append(f"{dataset_id}/{method}")

    if missing or unverified:
        problems: list[str] = []
        if missing:
            problems.append(f"missing results: {_summarize_refs(missing)}")
        if unverified:
            problems.append(f"roundtrip_verified != True: {_summarize_refs(unverified)}")
        qualifier = f" at or after {since.isoformat()}" if since is not None else ""
        raise VerificationError(
            f"Verification failed for suite '{suite}' in {results_path}{qualifier}: "
            + "; ".join(problems)
        )

    return VerificationSummary(
        suite=suite.lower(),
        dataset_ids=dataset_ids,
        methods=methods,
        results_path=results_path,
        since=since,
    )


def _summarize_refs(items: list[str], limit: int = 8) -> str:
    """Format a bounded list of dataset/method references for error output."""

    if len(items) <= limit:
        return ", ".join(items)

    remaining = len(items) - limit
    return f"{', '.join(items[:limit])} (+{remaining} more)"
