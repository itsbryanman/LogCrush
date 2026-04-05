"""zstd baseline compressor helpers."""

from __future__ import annotations

import math

import zstandard as zstd


def compress_zstd(
    data: bytes,
    level: int = 3,
    dictionary: zstd.ZstdCompressionDict | None = None,
) -> bytes:
    """Compress bytes with zstd."""

    compressor = zstd.ZstdCompressor(level=level, dict_data=dictionary)
    return compressor.compress(data)


def decompress_zstd(
    data: bytes,
    dictionary: zstd.ZstdCompressionDict | None = None,
) -> bytes:
    """Decompress zstd-compressed bytes."""

    decompressor = zstd.ZstdDecompressor(dict_data=dictionary)
    return decompressor.decompress(data)


def train_zstd_dictionary(
    data: bytes,
    sample_ratio: float = 0.1,
    dict_size: int = 112_640,
) -> zstd.ZstdCompressionDict:
    """Train a zstd dictionary from the first portion of a dataset."""

    if not data:
        raise ValueError("Cannot train a dictionary from empty input")

    training_bytes = max(1, math.floor(len(data) * sample_ratio))
    training_prefix = data[:training_bytes]
    samples = [
        training_prefix[index : index + 4096]
        for index in range(0, len(training_prefix), 4096)
        if training_prefix[index : index + 4096]
    ]
    if len(samples) < 2:
        samples = [training_prefix, training_prefix]
    return zstd.train_dictionary(dict_size, samples)
