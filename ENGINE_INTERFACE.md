# Engine Interface

This repository intentionally excludes the proprietary `logcrush-engine` source code.
`logcrush-bench` interacts with a separately distributed Linux executable.

## Default Release Asset

`reproduce_benchmarks.sh` assumes the official Linux binary is published at:

```text
https://github.com/itsbryanman/LogCrush/releases/download/engine-v${LOGCRUSH_ENGINE_VERSION}/logcrush-engine-linux-amd64
```

Override that with either:

- `LOGCRUSH_ENGINE_BIN=/absolute/path/to/logcrush-engine`
- `LOGCRUSH_ENGINE_URL=https://.../custom/logcrush-engine-linux-amd64`

## Required CLI Contract

The executable must support:

```bash
logcrush-engine benchmark-file \
  --input /path/to/dataset_normalized.log \
  --dataset-id linux \
  --iterations 3 \
  --json-output /tmp/metrics.json
```

## Required Metrics JSON

The binary must write a JSON document with these fields:

```json
{
  "compressed_bytes": 123,
  "compress_time_sec": 1.23,
  "decompress_time_sec": 0.45,
  "peak_memory_mb": 512.0,
  "roundtrip_verified": true,
  "template_count": 42,
  "stage_breakdown": {
    "template_dict": 100,
    "column_data": 200,
    "overhead": 10,
    "after_template_extraction": 500,
    "after_columnar_encoding": 300,
    "final": 310
  }
}
```

Notes:

- `compressed_bytes` must be the final compressed artifact size in bytes.
- `compress_time_sec` and `decompress_time_sec` should report the median across the requested
  iteration count.
- `roundtrip_verified` must only be `true` when decompression exactly matches the input.
- `stage_breakdown` may be `null` for engine versions that do not expose internal byte accounting.
