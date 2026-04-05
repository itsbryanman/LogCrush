"""Download and normalize LogHub datasets for benchmarking."""

from __future__ import annotations

import hashlib
import json
import shlex
import shutil
import subprocess
import tarfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable
from urllib.parse import parse_qs, urlparse

import requests
from tqdm import tqdm

from logcrush_bench.console import console
from logcrush_bench.definitions import list_supported_dataset_ids

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASETS_ROOT = PROJECT_ROOT / "datasets"
THUNDERBIRD_TRUNCATE_BYTES = 500 * 1024 * 1024
DOWNLOAD_TIMEOUT_SEC = 60
DOWNLOAD_CHUNK_SIZE = 1024 * 1024


@dataclass(slots=True)
class LogDataset:
    """Metadata and local paths for a benchmark dataset."""

    id: str
    name: str
    url: str
    sha256: str | None
    raw_path: Path
    line_count: int | None = None
    byte_size: int | None = None
    normalized_path: Path | None = None


DATASET_SPECS: dict[str, dict[str, str | None]] = {
    "hdfs": {
        "name": "HDFS",
        "url": "https://zenodo.org/records/8196385/files/HDFS_v1.zip?download=1",
        "sha256": None,
    },
    "apache": {
        "name": "Apache",
        "url": "https://zenodo.org/records/8196385/files/Apache.tar.gz?download=1",
        "sha256": None,
    },
    "thunderbird": {
        "name": "Thunderbird",
        "url": "https://zenodo.org/records/8196385/files/Thunderbird.tar.gz?download=1",
        "sha256": None,
    },
    "bgl": {
        "name": "BGL",
        "url": "https://zenodo.org/records/8196385/files/BGL.zip?download=1",
        "sha256": None,
    },
    "linux": {
        "name": "Linux",
        "url": "https://zenodo.org/records/8196385/files/Linux.tar.gz?download=1",
        "sha256": "7e1f820d8d45ae086032e515d9ce8d079a102a9b37dcff5b41a8e60b1f857820",
    },
    "spark": {
        "name": "Spark",
        "url": "https://zenodo.org/records/8196385/files/Spark.tar.gz?download=1",
        "sha256": None,
    },
    "windows": {
        "name": "Windows",
        "url": "https://zenodo.org/records/8196385/files/Windows.tar.gz?download=1",
        "sha256": None,
    },
    "openstack": {
        "name": "OpenStack",
        "url": "https://zenodo.org/records/8196385/files/OpenStack.tar.gz?download=1",
        "sha256": None,
    },
}

if list(DATASET_SPECS) != list_supported_dataset_ids():
    raise ValueError("DATASET_SPECS keys are out of sync with supported dataset ids.")


def get_supported_dataset_ids() -> list[str]:
    """Return supported dataset ids in deterministic order."""

    return list_supported_dataset_ids()


def get_dataset(dataset_id: str) -> LogDataset:
    """Build a dataset object from the registry and any persisted local metadata."""

    normalized_id = dataset_id.lower()
    if normalized_id not in DATASET_SPECS:
        supported = ", ".join(get_supported_dataset_ids())
        raise ValueError(f"Unsupported dataset '{dataset_id}'. Supported: {supported}")

    spec = DATASET_SPECS[normalized_id]
    dataset_dir = dataset_dir_for(normalized_id)
    raw_path = dataset_dir / f"{normalized_id}_raw.log"
    dataset = LogDataset(
        id=normalized_id,
        name=str(spec["name"]),
        url=str(spec["url"]),
        sha256=spec["sha256"] if spec["sha256"] else None,
        raw_path=raw_path,
        normalized_path=dataset_dir / f"{normalized_id}_normalized.log",
    )
    return _merge_metadata(dataset)


def download_and_normalize_datasets(dataset_ids: Iterable[str] | None = None) -> list[LogDataset]:
    """Download, extract, and normalize the requested datasets."""

    ids = list(dataset_ids) if dataset_ids is not None else get_supported_dataset_ids()
    return [download_and_normalize_dataset(dataset_id) for dataset_id in ids]


def download_and_normalize_dataset(dataset_id: str) -> LogDataset:
    """Download one dataset and return updated metadata."""

    dataset = get_dataset(dataset_id)
    dataset_dir = dataset_dir_for(dataset.id)
    dataset_dir.mkdir(parents=True, exist_ok=True)
    archive_path = dataset_dir / archive_name_from_url(dataset.url)
    metadata = _read_metadata(dataset.id)
    expected_hash = dataset.sha256 or metadata.get("sha256")

    if archive_path.exists():
        actual_hash = compute_sha256(archive_path)
        if expected_hash is None:
            expected_hash = actual_hash
            dataset.sha256 = actual_hash
            _write_metadata(dataset, {"archive_name": archive_path.name, "sha256": actual_hash})
        elif actual_hash != expected_hash:
            console.print(
                f"[yellow]hash mismatch[/yellow] {dataset.id}; deleting archive and retrying once"
            )
            archive_path.unlink()
            _download_file(dataset.url, archive_path, dataset.name)
            actual_hash = compute_sha256(archive_path)
            if actual_hash != expected_hash:
                raise RuntimeError(
                    f"Archive hash mismatch for {dataset.id}: expected {expected_hash}, got {actual_hash}"
                )
    else:
        _download_file(dataset.url, archive_path, dataset.name)
        actual_hash = compute_sha256(archive_path)
        if expected_hash is None:
            expected_hash = actual_hash
            dataset.sha256 = actual_hash
        elif actual_hash != expected_hash:
            archive_path.unlink(missing_ok=True)
            _download_file(dataset.url, archive_path, dataset.name)
            actual_hash = compute_sha256(archive_path)
            if actual_hash != expected_hash:
                raise RuntimeError(
                    f"Archive hash mismatch for {dataset.id}: expected {expected_hash}, got {actual_hash}"
                )

    dataset.sha256 = expected_hash
    extracted_paths = _extract_if_needed(dataset, archive_path)
    source_paths = _select_source_paths(extracted_paths)
    if not source_paths:
        raise RuntimeError(f"No candidate log files found for dataset {dataset.id}")

    raw_path = _materialize_raw_input(dataset, source_paths)
    dataset.raw_path = raw_path
    normalized_dataset = normalize_dataset(dataset)
    _write_metadata(
        normalized_dataset,
        {
            "archive_name": archive_path.name,
            "sha256": normalized_dataset.sha256,
            "raw_path": str(normalized_dataset.raw_path.relative_to(PROJECT_ROOT)),
            "normalized_path": str(normalized_dataset.normalized_path.relative_to(PROJECT_ROOT)),
            "line_count": normalized_dataset.line_count,
            "byte_size": normalized_dataset.byte_size,
        },
    )
    return normalized_dataset


def normalize_dataset(dataset: LogDataset) -> LogDataset:
    """Normalize a raw log source into a newline-delimited benchmark file."""

    if dataset.normalized_path is None:
        raise ValueError(f"Dataset {dataset.id} is missing a normalized output path")

    dataset.normalized_path.parent.mkdir(parents=True, exist_ok=True)
    line_count = 0
    bytes_written = 0
    buffer = b""

    with dataset.raw_path.open("rb") as source, dataset.normalized_path.open("wb") as target:
        while True:
            chunk = source.read(DOWNLOAD_CHUNK_SIZE)
            if not chunk:
                break
            normalized_chunk = (
                chunk.replace(b"\x00", b"").replace(b"\r\n", b"\n").replace(b"\r", b"\n")
            )
            buffer += normalized_chunk
            parts = buffer.split(b"\n")
            buffer = parts.pop()
            for line in parts:
                clean_line = line.rstrip(b" \t")
                target.write(clean_line + b"\n")
                line_count += 1
                bytes_written += len(clean_line) + 1

        if buffer:
            clean_line = buffer.rstrip(b" \t")
            target.write(clean_line + b"\n")
            line_count += 1
            bytes_written += len(clean_line) + 1

    return LogDataset(
        id=dataset.id,
        name=dataset.name,
        url=dataset.url,
        sha256=dataset.sha256,
        raw_path=dataset.raw_path,
        line_count=line_count,
        byte_size=bytes_written,
        normalized_path=dataset.normalized_path,
    )


def dataset_dir_for(dataset_id: str) -> Path:
    """Return the directory used to store one dataset."""

    return DATASETS_ROOT / dataset_id


def metadata_path_for(dataset_id: str) -> Path:
    """Return the path of the persisted dataset metadata JSON file."""

    return dataset_dir_for(dataset_id) / "metadata.json"


def archive_name_from_url(url: str) -> str:
    """Infer an archive filename from a Zenodo-style URL."""

    parsed = urlparse(url)
    name = PurePosixPath(parsed.path).name
    query = parse_qs(parsed.query)
    if name:
        return name
    if "download" in query and query["download"]:
        return query["download"][0]
    raise ValueError(f"Could not derive archive name from URL: {url}")


def compute_sha256(path: Path) -> str:
    """Compute the SHA-256 digest of a file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(DOWNLOAD_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _download_file(url: str, destination: Path, label: str) -> None:
    """Download a file with a progress bar."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT_SEC) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            with (
                destination.open("wb") as handle,
                tqdm(
                    total=total,
                    unit="B",
                    unit_scale=True,
                    desc=f"download {label}",
                ) as progress,
            ):
                for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    progress.update(len(chunk))
    except requests.RequestException:
        console.print(f"[yellow]requests download failed[/yellow] for {label}; retrying with curl")
        subprocess.run(
            [
                "bash",
                "-lc",
                f"curl -L --fail {shlex.quote(url)} -o {shlex.quote(str(destination))}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )


def _extract_if_needed(dataset: LogDataset, archive_path: Path) -> list[Path]:
    """Extract an archive when needed and return extracted file paths."""

    suffix = "".join(archive_path.suffixes)
    if suffix not in {".zip", ".tar.gz", ".tgz", ".tar"}:
        return [archive_path]

    extract_root = dataset_dir_for(dataset.id) / "extracted"
    metadata = _read_metadata(dataset.id)
    current_hash = dataset.sha256 or compute_sha256(archive_path)
    if (
        extract_root.exists()
        and metadata.get("extracted_archive_sha256") == current_hash
        and any(path.is_file() for path in extract_root.rglob("*"))
    ):
        return [path for path in sorted(extract_root.rglob("*")) if path.is_file()]

    if extract_root.exists():
        shutil.rmtree(extract_root)
    extract_root.mkdir(parents=True, exist_ok=True)

    extracted: list[Path] = []
    if suffix == ".zip":
        with zipfile.ZipFile(archive_path) as zipped:
            for member in zipped.infolist():
                if member.is_dir():
                    continue
                destination = _safe_archive_destination(extract_root, member.filename)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(member) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
                extracted.append(destination)
    else:
        mode = "r:gz" if suffix in {".tar.gz", ".tgz"} else "r:"
        with tarfile.open(archive_path, mode) as tarred:
            for member in tarred.getmembers():
                if not member.isfile():
                    continue
                destination = _safe_archive_destination(extract_root, member.name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                extracted_file = tarred.extractfile(member)
                if extracted_file is None:
                    continue
                with extracted_file as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
                extracted.append(destination)

    _write_metadata(dataset, {"extracted_archive_sha256": current_hash})
    return extracted


def _safe_archive_destination(root: Path, member_name: str) -> Path:
    """Resolve an archive member path safely under the extraction root."""

    relative = Path(PurePosixPath(member_name))
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"Unsafe archive member path: {member_name}")
    destination = root / relative
    destination.resolve().relative_to(root.resolve())
    return destination


def _select_source_paths(extracted_paths: list[Path]) -> list[Path]:
    """Choose benchmark input files from extracted archive contents."""

    excluded_suffixes = {".md", ".csv", ".json", ".yaml", ".yml", ".png", ".jpg", ".jpeg"}
    excluded_tokens = ("readme", "label", "structured", "template", "drain")
    preferred_suffixes = {".log", ".txt", ".out", ""}

    candidates: list[Path] = []
    for path in extracted_paths:
        if not path.is_file() or path.stat().st_size == 0:
            continue
        lower_name = path.name.lower()
        if any(token in lower_name for token in excluded_tokens):
            continue
        if path.suffix.lower() in excluded_suffixes:
            continue
        candidates.append(path)

    if not candidates:
        return []

    preferred = [path for path in candidates if path.suffix.lower() in preferred_suffixes]
    return sorted(preferred or candidates)


def _materialize_raw_input(dataset: LogDataset, source_paths: list[Path]) -> Path:
    """Create the raw benchmark input file from one or more extracted files."""

    dataset_dir = dataset_dir_for(dataset.id)
    if len(source_paths) == 1:
        raw_path = source_paths[0]
    else:
        raw_path = dataset_dir / f"{dataset.id}_raw.log"
        with raw_path.open("wb") as target:
            for index, path in enumerate(source_paths):
                with path.open("rb") as source:
                    shutil.copyfileobj(source, target, DOWNLOAD_CHUNK_SIZE)
                if index != len(source_paths) - 1:
                    target.write(b"\n")

    if dataset.id == "thunderbird":
        truncated_path = dataset_dir / "thunderbird_truncated.log"
        _truncate_by_line(raw_path, truncated_path, THUNDERBIRD_TRUNCATE_BYTES)
        return truncated_path
    return raw_path


def _truncate_by_line(source_path: Path, destination: Path, max_bytes: int) -> None:
    """Copy a file up to a byte budget while preserving whole lines."""

    written = 0
    with source_path.open("rb") as source, destination.open("wb") as target:
        for line in source:
            if written + len(line) > max_bytes:
                break
            target.write(line)
            written += len(line)


def _merge_metadata(dataset: LogDataset) -> LogDataset:
    """Apply persisted metadata values to a dataset object."""

    metadata = _read_metadata(dataset.id)
    raw_path = Path(metadata["raw_path"]) if "raw_path" in metadata else dataset.raw_path
    normalized_path = (
        Path(metadata["normalized_path"])
        if "normalized_path" in metadata
        else dataset.normalized_path
    )
    return LogDataset(
        id=dataset.id,
        name=dataset.name,
        url=dataset.url,
        sha256=metadata.get("sha256", dataset.sha256),
        raw_path=_resolve_metadata_path(raw_path),
        line_count=metadata.get("line_count"),
        byte_size=metadata.get("byte_size"),
        normalized_path=_resolve_metadata_path(normalized_path) if normalized_path else None,
    )


def _resolve_metadata_path(path: Path) -> Path:
    """Resolve metadata paths relative to the project root when needed."""

    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _read_metadata(dataset_id: str) -> dict[str, str | int | None]:
    """Load dataset metadata from disk."""

    path = metadata_path_for(dataset_id)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_metadata(dataset: LogDataset, updates: dict[str, str | int | None]) -> None:
    """Persist dataset metadata to disk."""

    path = metadata_path_for(dataset.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _read_metadata(dataset.id)
    payload.update(updates)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def dataset_to_dict(dataset: LogDataset) -> dict[str, object]:
    """Serialize a dataset dataclass to JSON-friendly primitives."""

    payload = asdict(dataset)
    payload["raw_path"] = str(dataset.raw_path)
    payload["normalized_path"] = str(dataset.normalized_path) if dataset.normalized_path else None
    return payload
