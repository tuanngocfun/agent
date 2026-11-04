#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_PYTHON="$PROJECT_DIR/.venv/bin/python"
if [[ ! -x "$PROJECT_PYTHON" ]]; then
  printf '%s\n' 'Run bash scripts/setup_environment.sh from the package directory first.' >&2
  exit 1
fi
export PATH="$PROJECT_DIR/.venv/bin:$PATH"
export JUPYTER_PATH="$PROJECT_DIR/.jupyter${JUPYTER_PATH:+:$JUPYTER_PATH}"
export JUPYTER_RUNTIME_DIR="$PROJECT_DIR/.runtime/jupyter"
export IPYTHONDIR="$PROJECT_DIR/.runtime/ipython"
export MPLCONFIGDIR="$PROJECT_DIR/.cache/matplotlib"
export TORCH_HOME="$PROJECT_DIR/.cache/torch"
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
mkdir -p "$JUPYTER_RUNTIME_DIR" "$IPYTHONDIR"
"$PROJECT_PYTHON" "$PROJECT_DIR/scripts/register_kernel.py"
exec "$PROJECT_PYTHON" -m jupyterlab --ServerApp.root_dir="$PROJECT_DIR" --ServerApp.ip=127.0.0.1 --no-browser "$@"
