"""Drain3-backed template extraction with timestamp preprocessing."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from drain3 import TemplateMiner as DrainTemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

TIMESTAMP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"
        r"(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)(?P<suffix>\s+)(?P<message>.*)$"
    ),
    re.compile(
        r"^(?P<timestamp>[A-Z][a-z]{2}\s{1,2}\d{1,2}\s\d{2}:\d{2}:\d{2})"
        r"(?P<suffix>\s+)(?P<message>.*)$"
    ),
    re.compile(r"^(?P<timestamp>\d{13})(?P<suffix>\s+)(?P<message>.*)$"),
    re.compile(r"^(?P<timestamp>\d{10})(?P<suffix>\s+)(?P<message>.*)$"),
    re.compile(
        r"^(?P<timestamp>\d{1,2}/[A-Z][a-z]{2}/\d{4}:\d{2}:\d{2}:\d{2}\s[+-]\d{4})"
        r"(?P<suffix>\s+)(?P<message>.*)$"
    ),
    re.compile(r"^(?P<timestamp>\d{6}\s\d{6})(?P<suffix>\s+)(?P<message>.*)$"),
)


@dataclass(slots=True)
class LogRecord:
    """A structured record extracted from one raw log line."""

    template_id: int
    timestamp: str | None
    params: list[str]
    raw_line: str
    timestamp_prefix: str | None = None


@dataclass(slots=True)
class TemplateExtractionResult:
    """Templates and per-line extraction output from the miner."""

    templates: dict[int, str]
    records: list[LogRecord]


@dataclass(slots=True)
class TimestampExtraction:
    """Timestamp extraction outcome for one line."""

    timestamp: str | None
    prefix: str | None
    message: str


class TemplateMiner:
    """Wrap Drain3 to extract templates from raw log lines."""

    def __init__(self, sim_th: float = 0.4, depth: int = 4, max_children: int = 100) -> None:
        """Create a configured Drain3 miner."""

        config = TemplateMinerConfig()
        config.drain_sim_th = sim_th
        config.drain_depth = depth
        config.drain_max_children = max_children
        self._miner = DrainTemplateMiner(config=config)

    def extract(self, lines: Iterable[str]) -> TemplateExtractionResult:
        """Extract templates and records from raw lines."""

        staged_records: list[tuple[int, TimestampExtraction, str, str]] = []
        for line in lines:
            raw_line = line.rstrip("\n")
            timestamp_info = extract_timestamp_prefix(raw_line)
            mining_input = timestamp_info.message or raw_line
            result = self._miner.add_log_message(mining_input)
            staged_records.append(
                (int(result["cluster_id"]), timestamp_info, raw_line, mining_input)
            )

        templates = {
            int(cluster_id): cluster.get_template()
            for cluster_id, cluster in self._miner.drain.id_to_cluster.items()
        }
        records: list[LogRecord] = []
        for cluster_id, timestamp_info, raw_line, mining_input in staged_records:
            template = templates[cluster_id]
            extracted = self._miner.extract_parameters(
                template,
                mining_input,
                exact_matching=False,
            )
            params = [parameter.value for parameter in extracted or []]
            records.append(
                LogRecord(
                    template_id=cluster_id,
                    timestamp=timestamp_info.timestamp,
                    params=params,
                    raw_line=raw_line,
                    timestamp_prefix=timestamp_info.prefix,
                )
            )
        return TemplateExtractionResult(templates=templates, records=records)


def extract_timestamp_prefix(line: str) -> TimestampExtraction:
    """Extract a leading timestamp when a known format is present."""

    for pattern in TIMESTAMP_PATTERNS:
        match = pattern.match(line)
        if match is None:
            continue
        timestamp = match.group("timestamp")
        suffix = match.group("suffix")
        message = match.group("message")
        return TimestampExtraction(
            timestamp=timestamp,
            prefix=f"{timestamp}{suffix}",
            message=message,
        )
    return TimestampExtraction(timestamp=None, prefix=None, message=line)


def template_frequencies(result: TemplateExtractionResult) -> Counter[int]:
    """Count record frequency per template id."""

    return Counter(record.template_id for record in result.records)


def coverage_percent(result: TemplateExtractionResult) -> float:
    """Return coverage percentage for templates with more than one record."""

    if not result.records:
        return 0.0
    frequencies = template_frequencies(result)
    covered = sum(1 for record in result.records if frequencies.get(record.template_id, 0) > 1)
    return (covered / len(result.records)) * 100.0
