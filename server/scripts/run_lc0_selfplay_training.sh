#!/usr/bin/env bash
# Run Leela Chess Zero in selfplay mode with training data enabled.
#
# Prerequisites:
#   - lc0 on PATH (Homebrew: /opt/homebrew/bin/lc0) or set LC0_PATH
#   - LC0_WEIGHTS set to your network file (e.g. ~/.local/share/lc0/lc0net.pb.gz)
#
# Usage:
#   export LC0_WEIGHTS="$HOME/.local/share/lc0/lc0net.pb.gz"
#   ./server/scripts/run_lc0_selfplay_training.sh
#
# Optional env:
#   LC0_PATH        — path to lc0 binary (default: lc0 from PATH)
#   LC0_GAMES       — games to play (-1 = forever, default: 10 for a short run)
#   LC0_THREADS     — worker threads (default: 2)
#   LC0_BACKEND     — e.g. metal, blas (default: metal on Darwin, blas elsewhere)
#   LC0_EXTRA_ARGS  — extra args passed through to lc0 selfplay (quoted string)
#   LC0_ARCH_WRAPPER — if your shell is Rosetta but Homebrew is ARM, set to: arch -arm64
#
# Training output:
#   LC0 creates a temporary subdirectory for chunks (see lc0 log / cwd). Check the
#   first lines printed after start, or use --logfile (via LC0_EXTRA_ARGS).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

if [[ -z "${LC0_WEIGHTS:-}" ]]; then
  echo "error: export LC0_WEIGHTS=/path/to/your/network.pb.gz" >&2
  exit 1
fi

LC0_BIN="${LC0_PATH:-lc0}"
if ! command -v "$LC0_BIN" >/dev/null 2>&1 && [[ "$LC0_BIN" == "lc0" ]]; then
  echo "error: lc0 not found on PATH; set LC0_PATH to the binary" >&2
  exit 1
fi

GAMES="${LC0_GAMES:-10}"
THREADS="${LC0_THREADS:-2}"
if [[ "$(uname -s)" == "Darwin" ]]; then
  BACKEND="${LC0_BACKEND:-metal}"
else
  BACKEND="${LC0_BACKEND:-blas}"
fi

WRAPPER=()
if [[ -n "${LC0_ARCH_WRAPPER:-}" ]]; then
  # shellcheck disable=SC2206
  WRAPPER=($LC0_ARCH_WRAPPER)
fi

EXTRA=()
if [[ -n "${LC0_EXTRA_ARGS:-}" ]]; then
  # shellcheck disable=SC2206
  EXTRA=($LC0_EXTRA_ARGS)
fi

echo "Starting lc0 selfplay + training (games=$GAMES threads=$THREADS backend=$BACKEND)" >&2
echo "Weights: $LC0_WEIGHTS" >&2
echo "Working directory: $ROOT (training temp dir is created by lc0)" >&2

exec "${WRAPPER[@]}" "$LC0_BIN" selfplay \
  --weights="$LC0_WEIGHTS" \
  --backend="$BACKEND" \
  --threads="$THREADS" \
  --training \
  --games="$GAMES" \
  "${EXTRA[@]}" \
  "$@"
