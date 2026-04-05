"""Smoke tests for the public benchmark harness."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from logcrush_bench.benchmark import run_benchmarks
from logcrush_bench.datasets import LogDataset


def test_baseline_benchmark_smoke(tmp_path: Path, monkeypatch) -> None:
    """Public baseline benchmarks should run on a synthetic dataset."""

    dataset_path = tmp_path / "linux_normalized.log"
    dataset_path.write_text("alpha 1\nalpha 2\nbeta 3\n", encoding="utf-8")
    monkeypatch.setattr(
        "logcrush_bench.benchmark.get_dataset",
        lambda dataset_id: LogDataset(
            id=dataset_id,
            name=dataset_id.upper(),
            url="https://example.invalid/dataset",
            sha256=None,
            raw_path=dataset_path,
            normalized_path=dataset_path,
        ),
    )

    results = run_benchmarks(
        dataset_ids=["linux"],
        methods=["gzip-6", "zstd-3"],
        results_path=tmp_path / "results.json",
    )

    assert all(result.roundtrip_verified for result in results)
    assert all(result.compress_time_sec > 0 for result in results)
    assert all(result.decompress_time_sec > 0 for result in results)


def test_logcrush_benchmark_uses_external_engine(tmp_path: Path, monkeypatch) -> None:
    """The logcrush method should delegate to the proprietary engine binary."""

    dataset_path = tmp_path / "linux_normalized.log"
    dataset_path.write_text("alpha 1\nalpha 2\nbeta 3\n", encoding="utf-8")
    monkeypatch.setattr(
        "logcrush_bench.benchmark.get_dataset",
        lambda dataset_id: LogDataset(
            id=dataset_id,
            name=dataset_id.upper(),
            url="https://example.invalid/dataset",
            sha256=None,
            raw_path=dataset_path,
            normalized_path=dataset_path,
        ),
    )

    engine_path = tmp_path / "logcrush-engine"
    engine_path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json",
                "import pathlib",
                "import sys",
                "",
                "args = sys.argv[1:]",
                "assert args[0] == 'benchmark-file'",
                "json_output = pathlib.Path(args[args.index('--json-output') + 1])",
                "input_path = pathlib.Path(args[args.index('--input') + 1])",
                "payload = {",
                "    'compressed_bytes': max(1, input_path.stat().st_size // 2),",
                "    'compress_time_sec': 0.25,",
                "    'decompress_time_sec': 0.10,",
                "    'peak_memory_mb': 32.0,",
                "    'roundtrip_verified': True,",
                "    'template_count': 3,",
                "    'stage_breakdown': {'template_dict': 10, 'column_data': 20, 'overhead': 5},",
                "}",
                "json_output.write_text(json.dumps(payload), encoding='utf-8')",
            ]
        ),
        encoding="utf-8",
    )
    engine_path.chmod(engine_path.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("LOGCRUSH_ENGINE_BIN", os.fspath(engine_path))

    results = run_benchmarks(
        dataset_ids=["linux"],
        methods=["logcrush"],
        results_path=tmp_path / "results.json",
    )

    assert len(results) == 1
    assert results[0].method == "logcrush"
    assert results[0].roundtrip_verified is True
    assert results[0].compression_ratio > 1.0
