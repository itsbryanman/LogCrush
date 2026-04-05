#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_PATH="${LOG_PATH:-$ROOT_DIR/results/full-run.nohup.log}"
PID_PATH="${PID_PATH:-$ROOT_DIR/results/full-run.pid}"

mkdir -p "$(dirname "$LOG_PATH")" "$(dirname "$PID_PATH")"

if [ "$#" -eq 0 ]; then
  set -- --all --all-methods
fi

cd "$ROOT_DIR"
setsid env PYTHONUNBUFFERED=1 .venv/bin/logcrush-bench run "$@" >>"$LOG_PATH" 2>&1 < /dev/null &
PID=$!
printf '%s\n' "$PID" >"$PID_PATH"
printf 'started detached benchmark pid=%s log=%s\n' "$PID" "$LOG_PATH"
