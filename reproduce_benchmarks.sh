#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./reproduce_benchmarks.sh [--full | --smoke] [--help]

Reproduce the LogCrush benchmark numbers from the repo root.

Defaults to --full so ./reproduce.sh reruns the full published benchmark matrix.
Use --smoke for a faster Linux-only validation run that exercises the same CLI
and verification path on the lightest supported dataset.

Environment:
  LOGCRUSH_ENGINE_BIN      Existing proprietary engine executable to use.
  LOGCRUSH_ENGINE_URL      Explicit download URL for the proprietary Linux binary.
  LOGCRUSH_ENGINE_VERSION  Version used for the default GitHub release URL.

Outputs:
  results/results.json
  results/summary.md
  results/reproduce-full.log or results/reproduce-smoke.log

Verification:
  The script exits nonzero unless every expected dataset/method result written
  during this run is present in results/results.json and has
  roundtrip_verified == True.
EOF
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR"
MODE="full"
MODE_SET="false"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --full)
      if [ "$MODE_SET" = "true" ] && [ "$MODE" != "full" ]; then
        fail "choose only one of --full or --smoke"
      fi
      MODE="full"
      MODE_SET="true"
      ;;
    --smoke)
      if [ "$MODE_SET" = "true" ] && [ "$MODE" != "smoke" ]; then
        fail "choose only one of --full or --smoke"
      fi
      MODE="smoke"
      MODE_SET="true"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
  shift
done

[ -f "$ROOT_DIR/pyproject.toml" ] || fail "run this script from the repository root"
[ -f "$ROOT_DIR/src/logcrush_bench/cli.py" ] || fail "src/logcrush_bench/cli.py not found"

RESULTS_DIR="$ROOT_DIR/results"
RESULTS_PATH="$RESULTS_DIR/results.json"
SUMMARY_PATH="$RESULTS_DIR/summary.md"
LOG_PATH="$RESULTS_DIR/reproduce-${MODE}.log"
VENV_DIR="$ROOT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_CLI="$VENV_DIR/bin/logcrush-bench"
ENGINE_VERSION="${LOGCRUSH_ENGINE_VERSION:-0.1.0}"
DEFAULT_ENGINE_URL="https://github.com/itsbryanman/LogCrush/releases/download/engine-v${ENGINE_VERSION}/logcrush-engine-linux-amd64"
ENGINE_INSTALL_PATH="$VENV_DIR/bin/logcrush-engine"

mkdir -p "$RESULTS_DIR"
: > "$LOG_PATH"
exec > >(tee "$LOG_PATH") 2>&1

on_exit() {
  status=$?
  if [ "$status" -ne 0 ]; then
    printf '\nReproduction failed. See %s for details.\n' "$LOG_PATH" >&2
  fi
}
trap on_exit EXIT

cd "$ROOT_DIR"

printf '==> Mode: %s\n' "$MODE"
if [ "$MODE" = "smoke" ]; then
  printf '==> Smoke mode reruns the Linux dataset across all benchmark methods.\n'
else
  printf '==> Full mode reruns every supported dataset across all benchmark methods.\n'
fi

if [ ! -x "$VENV_PYTHON" ]; then
  printf '==> Creating virtual environment at %s\n' "$VENV_DIR"
  python3 -m venv "$VENV_DIR"
fi

printf '==> Installing project and dev dependencies into %s\n' "$VENV_DIR"
"$VENV_PYTHON" -m pip install -e '.[dev]'

install_engine() {
  if [ -n "${LOGCRUSH_ENGINE_BIN:-}" ]; then
    [ -x "$LOGCRUSH_ENGINE_BIN" ] || fail "LOGCRUSH_ENGINE_BIN is not executable: $LOGCRUSH_ENGINE_BIN"
    printf '==> Using proprietary engine binary: %s\n' "$LOGCRUSH_ENGINE_BIN"
    export LOGCRUSH_ENGINE_BIN
    return
  fi

  if command -v logcrush-engine >/dev/null 2>&1; then
    LOGCRUSH_ENGINE_BIN="$(command -v logcrush-engine)"
    printf '==> Using proprietary engine binary from PATH: %s\n' "$LOGCRUSH_ENGINE_BIN"
    export LOGCRUSH_ENGINE_BIN
    return
  fi

  ENGINE_URL="${LOGCRUSH_ENGINE_URL:-$DEFAULT_ENGINE_URL}"
  printf '==> Downloading proprietary engine binary from %s\n' "$ENGINE_URL"
  curl -L --fail "$ENGINE_URL" -o "$ENGINE_INSTALL_PATH"
  chmod +x "$ENGINE_INSTALL_PATH"
  LOGCRUSH_ENGINE_BIN="$ENGINE_INSTALL_PATH"
  export LOGCRUSH_ENGINE_BIN
}

install_engine

RUN_STARTED_AT="$(
  python3 - <<'PY'
from datetime import datetime, timezone

print(datetime.now(timezone.utc).isoformat())
PY
)"
printf '==> Run start timestamp: %s\n' "$RUN_STARTED_AT"

DOWNLOAD_ARGS=(--all)
RUN_ARGS=(--all --all-methods)
VERIFY_ARGS=(--suite full)
if [ "$MODE" = "smoke" ]; then
  DOWNLOAD_ARGS=(--dataset linux)
  RUN_ARGS=(--dataset linux --all-methods)
  VERIFY_ARGS=(--suite smoke)
fi

printf '==> Downloading datasets from the canonical LogHub sources defined in src/logcrush_bench/datasets.py\n'
"$VENV_CLI" download "${DOWNLOAD_ARGS[@]}"

printf '==> Running benchmarks\n'
"$VENV_CLI" run "${RUN_ARGS[@]}"
[ -s "$RESULTS_PATH" ] || fail "expected benchmark results at $RESULTS_PATH"

printf '==> Generating summary report\n'
"$VENV_CLI" report --results-path "$RESULTS_PATH"
[ -s "$SUMMARY_PATH" ] || fail "expected report at $SUMMARY_PATH"

printf '==> Enforcing roundtrip verification gate\n'
"$VENV_CLI" verify --results-path "$RESULTS_PATH" "${VERIFY_ARGS[@]}" --since "$RUN_STARTED_AT"

printf '\nReproduction complete.\n'
printf 'Results JSON: %s\n' "$RESULTS_PATH"
printf 'Summary Markdown: %s\n' "$SUMMARY_PATH"
printf 'Run Log: %s\n' "$LOG_PATH"
