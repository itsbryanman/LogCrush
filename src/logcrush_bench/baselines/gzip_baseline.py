"""gzip baseline compressor helpers."""

from __future__ import annotations

import gzip


def compress_gzip(data: bytes, level: int = 9) -> bytes:
    """Compress bytes with gzip."""

    return gzip.compress(data, compresslevel=level, mtime=0)


def decompress_gzip(data: bytes) -> bytes:
    """Decompress gzip-compressed bytes."""

    return gzip.decompress(data)
