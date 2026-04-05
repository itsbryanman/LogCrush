"""Simplified CLP-style baseline built on template extraction plus zstd."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable

import zstandard as zstd

from logcrush_bench.pipeline.template_miner import TemplateMiner

CLP_COMPRESSOR = zstd.ZstdCompressor(level=3)
CLP_DECOMPRESSOR = zstd.ZstdDecompressor()


@dataclass(slots=True)
class CLPCompressionArtifact:
    """Compressed payload and template metadata for the CLP-style baseline."""

    data: bytes
    template_count: int


class CLPBaselineCompressor:
    """Template-based baseline without typed column codecs."""

    def __init__(self, sim_th: float = 0.4, depth: int = 4, max_children: int = 100) -> None:
        """Create a baseline compressor with the benchmark Drain settings."""

        self._miner = TemplateMiner(sim_th=sim_th, depth=depth, max_children=max_children)

    def compress(self, lines: Iterable[str]) -> bytes:
        """Compress raw lines to a CLP-style zstd payload."""

        return self.compress_with_metrics(lines).data

    def compress_with_metrics(self, lines: Iterable[str]) -> CLPCompressionArtifact:
        """Compress raw lines and return template count metadata."""

        normalized_lines = [line.rstrip("\n") for line in lines]
        extraction = self._miner.extract(normalized_lines)
        records = [
            {
                "template_id": record.template_id,
                "timestamp_prefix": record.timestamp_prefix,
                "params": record.params,
            }
            for record in extraction.records
        ]
        raw_overrides = {
            str(index): record.raw_line
            for index, record in enumerate(extraction.records)
            if f"{record.timestamp_prefix or ''}{_render_template(extraction.templates[record.template_id], record.params)}"
            != record.raw_line
        }
        blob = json.dumps(
            {"templates": extraction.templates, "records": records, "raw_overrides": raw_overrides},
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8", errors="surrogatepass")
        return CLPCompressionArtifact(
            data=CLP_COMPRESSOR.compress(blob),
            template_count=len(extraction.templates),
        )

    def decompress(self, data: bytes) -> list[str]:
        """Decompress a CLP-style payload back to exact log lines."""

        decoded = json.loads(
            CLP_DECOMPRESSOR.decompress(data).decode("utf-8", errors="surrogatepass")
        )
        templates = {int(key): value for key, value in decoded["templates"].items()}
        raw_overrides = {int(key): value for key, value in decoded.get("raw_overrides", {}).items()}
        lines: list[str] = []
        for index, record in enumerate(decoded["records"]):
            template = templates[int(record["template_id"])]
            message = _render_template(template, record["params"])
            reconstructed = f"{record['timestamp_prefix'] or ''}{message}"
            lines.append(raw_overrides.get(index, reconstructed))
        return lines


def _render_template(template: str, params: list[str]) -> str:
    """Render a Drain template by replacing wildcards with raw parameters."""

    parts = template.split("<*>")
    if len(parts) == 1:
        return template

    rendered = [parts[0]]
    for param, suffix in zip(params, parts[1:]):
        rendered.append(param)
        rendered.append(suffix)
    return "".join(rendered)
