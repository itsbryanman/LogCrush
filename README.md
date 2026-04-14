# LogCrush Benchmarks

`logcrush-bench` is the public LogHub benchmark harness for LogCrush. This repository intentionally
does **not** contain the proprietary `logcrush-engine` implementation. It exists so anyone can:

- download the canonical LogHub datasets,
- run the full public benchmark matrix,
- verify that every published result was lossless,
- inspect the harness, baselines, reports, and benchmark artifacts.

## Reproduce the Benchmarks

Fresh clone, one obvious command:

```bash
git clone https://github.com/itsbryanman/LogCrush logcrush-bench
cd logcrush-bench
./reproduce.sh
```

That default path reruns the full suite. For a faster Linux-only check:

```bash
./reproduce.sh --smoke
```

What `./reproduce.sh` does:

1. Creates `.venv` if needed.
2. Installs the public benchmark harness.
3. Downloads the proprietary `logcrush-engine` Linux binary release unless you point it at an
   existing binary.
4. Downloads the canonical LogHub archives from Zenodo.
5. Runs `download`, `run`, `report`, and `verify`.
6. Exits nonzero unless every expected row from the current run has `roundtrip_verified == True`.

Environment overrides:

- `LOGCRUSH_ENGINE_BIN`: path to an already-installed proprietary engine binary.
- `LOGCRUSH_ENGINE_URL`: explicit download URL for the proprietary Linux binary.
- `LOGCRUSH_ENGINE_VERSION`: release version used to build the default GitHub release URL.

Requirements:

- Linux with `bash` and `python3`
- Internet access for package installation, LogHub downloads, and the proprietary engine release
- Enough disk and memory for the full suite

## Published Benchmark Table

Latest verified full-run ratio snapshot from `--all --all-methods`:

| Dataset | LogCrush | CLP-basic | gzip-6 | gzip-9 | zstd-1 | zstd-3 | zstd-9 | zstd-19 | zstd-dict | Verified |
|---|---|---|---|---|---|---|---|---|---|---|
| HDFS | 25.49 | 10.03 | 9.63 | 10.10 | 10.29 | 9.98 | 11.93 | 15.32 | 10.01 | Yes |
| APACHE | 46.88 | 17.78 | 19.60 | 21.33 | 19.47 | 19.03 | 24.65 | 28.90 | 19.09 | Yes |
| THUNDERBIRD | 57.69 | 18.90 | 16.43 | 17.06 | 18.29 | 19.76 | 25.39 | 29.61 | 19.73 | Yes |

Every row above came from a run where the harness reported `verified=True`.

Published artifacts in this repo:

- [`results/results.json`](results/results.json): persisted benchmark result store
- [`results/summary.md`](results/summary.md): generated markdown summary
- [`results/charts/compression_ratio_by_dataset.png`](results/charts/compression_ratio_by_dataset.png)
- [`results/charts/throughput_by_dataset.png`](results/charts/throughput_by_dataset.png)
- [`results/charts/breakdown_by_stage.png`](results/charts/breakdown_by_stage.png)
- [`results/charts/savings_vs_zstd.png`](results/charts/savings_vs_zstd.png)

## Supported Datasets

- `hdfs` -> `HDFS_v1.zip`
- `apache` -> `Apache.tar.gz`
- `thunderbird` -> `Thunderbird.tar.gz` with a 500 MB benchmark truncation
- `bgl` -> `BGL.zip`
- `linux` -> `Linux.tar.gz`
- `spark` -> `Spark.tar.gz`
- `windows` -> `Windows.tar.gz`
- `openstack` -> `OpenStack.tar.gz`

Archive SHA-256 values are never fabricated. If a dataset entry does not have a pre-recorded hash,
the first successful download computes and persists the real digest in `datasets/<id>/metadata.json`.

## Repository Scope

This repository contains:

- the public benchmark harness under `src/logcrush_bench/`,
- the baseline implementations used for comparison,
- reproducibility scripts,
- benchmark reports and charts,
- tests for the public harness.

This repository does **not** contain:

- the proprietary `logcrush-engine` source,
- internal engine implementation details,
- private release tooling for packaging the engine binary.

The benchmark harness expects a separately distributed `logcrush-engine` executable. The contract
for that binary is documented in [`ENGINE_INTERFACE.md`](ENGINE_INTERFACE.md).

## Project Layout

```text
logcrush-bench/
├── datasets/
├── results/
├── src/logcrush_bench/
│   ├── baselines/
│   ├── benchmark.py
│   ├── cli.py
│   ├── datasets.py
│   ├── engine_client.py
│   ├── report.py
│   └── verification.py
├── reproduce.sh
├── reproduce_benchmarks.sh
└── tests/
```

## License

The public benchmark harness in this repository is source-available under Business Source License
1.1. See [`LICENSE`](LICENSE).

The separately distributed proprietary `logcrush-engine` binaries are not included here and are
licensed under the commercial terms shipped with those releases.
email bryan@backwoodsdevelopment.com for licensing 
## Development Checks

```bash
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format src/ tests/
.venv/bin/pytest
```

Lossless roundtrip is the hard gate. If a method fails verification, the run is recorded as
invalid instead of being silently counted.
