#!/usr/bin/env bash
# Portable current-package checks; no private host/provenance audit.
set -euo pipefail
REHEARSAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REHEARSAL_PYTHON="$REHEARSAL_ROOT/.venv/bin/python"
if [[ ! -x "$REHEARSAL_PYTHON" ]]; then
  echo 'Run bash scripts/setup_environment.sh first.' >&2
  exit 2
fi
export PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export JUPYTER_PATH="$REHEARSAL_ROOT/.jupyter"
export JUPYTER_RUNTIME_DIR="$REHEARSAL_ROOT/.runtime"
export IPYTHONDIR="$REHEARSAL_ROOT/.runtime/ipython"
export MPLCONFIGDIR="$REHEARSAL_ROOT/.cache/matplotlib"
export TORCH_HOME="$REHEARSAL_ROOT/.cache/torch"
mkdir -p "$REHEARSAL_ROOT/.runtime/ipython" "$REHEARSAL_ROOT/.cache/matplotlib" "$REHEARSAL_ROOT/.cache/torch"
cd "$REHEARSAL_ROOT"
if [[ "${1:-}" == "--rebuild" ]]; then
  "$REHEARSAL_PYTHON" scripts/run_notebooks.py
  "$REHEARSAL_PYTHON" scripts/render_decks.py
  "$REHEARSAL_PYTHON" scripts/render_docs.py
  echo 'Fresh rendering still needs visual inspection; this command does not certify it.' >&2
elif [[ $# -gt 0 ]]; then
  echo 'Usage: bash scripts/verify_all.sh [--rebuild]' >&2
  exit 2
fi
"$REHEARSAL_PYTHON" scripts/validate_package.py
