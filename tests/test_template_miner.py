"""Tests for template extraction and timestamp parsing."""

from __future__ import annotations

import pytest

pytest.importorskip("drain3")

from logcrush_bench.pipeline.template_miner import (
    TemplateMiner,
    coverage_percent,
    extract_timestamp_prefix,
)


def test_template_miner_discovers_three_templates() -> None:
    """Synthetic inputs should collapse into three templates."""

    miner = TemplateMiner()
    lines = []
    for index in range(34):
        lines.append(
            f"Jan 15 08:23:{index:02d} worker auth success user=user{index} from host{index}"
        )
    for index in range(33):
        lines.append(
            f"Jan 15 08:24:{index:02d} worker permission denied uid={index} path=/srv/{index}"
        )
    for index in range(33):
        lines.append(f"Jan 15 08:25:{index:02d} worker job finished id={index}")

    result = miner.extract(lines)

    assert len(result.templates) == 3
    assert coverage_percent(result) == 100.0


def test_timestamp_extraction_handles_all_required_formats() -> None:
    """Known timestamp formats should be extracted and stripped."""

    samples = {
        "2024-01-15T08:23:41.123Z service started": "2024-01-15T08:23:41.123Z",
        "Jan 15 08:23:41 service started": "Jan 15 08:23:41",
        "1705305821 service started": "1705305821",
        "1705305821123 service started": "1705305821123",
        "15/Jan/2024:08:23:41 +0000 service started": "15/Jan/2024:08:23:41 +0000",
        "081109 203518 service started": "081109 203518",
    }

    for line, expected in samples.items():
        extracted = extract_timestamp_prefix(line)
        assert extracted.timestamp == expected
        assert extracted.message == "service started"


def test_singleton_template_does_not_crash() -> None:
    """A one-off template should still be recorded safely."""

    miner = TemplateMiner()
    result = miner.extract(["unmatched literal event"])

    assert len(result.templates) == 1
    assert result.records[0].params == []
    assert result.records[0].raw_line == "unmatched literal event"
