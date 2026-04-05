"""Helpers for reading stored benchmark results."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from logcrush_bench.definitions import BenchmarkResult


@dataclass(slots=True)
class StoredResult:
    """Stored benchmark result with its timestamp."""

    timestamp: datetime
    result: BenchmarkResult


def load_latest_results(
    results_path: Path,
    since: datetime | None = None,
) -> dict[str, dict[str, BenchmarkResult]]:
    """Load the latest stored result for each dataset/method combination."""

    if not results_path.exists():
        return {}

    payload = json.loads(results_path.read_text(encoding="utf-8"))
    latest: dict[str, dict[str, StoredResult]] = {}
    for key, value in payload.items():
        try:
            dataset_id, method, timestamp = key.split("|", maxsplit=2)
            parsed_timestamp = datetime.fromisoformat(timestamp)
            result = BenchmarkResult(**value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid stored result entry {key!r}: {exc}") from exc

        if since is not None and parsed_timestamp < since:
            continue
        current = latest.setdefault(dataset_id, {}).get(method)
        if current is None or parsed_timestamp > current.timestamp:
            latest[dataset_id][method] = StoredResult(timestamp=parsed_timestamp, result=result)

    return {
        dataset_id: {method: stored.result for method, stored in method_map.items()}
        for dataset_id, method_map in latest.items()
    }
