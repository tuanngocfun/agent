#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_PYTHON="$PROJECT_DIR/.venv/bin/python"
REGISTER_ONLY=0
case "${1:-}" in
  --register-only) REGISTER_ONLY=1 ;;
  --help|-h)
    printf '%s\n' 'Usage: bash scripts/setup_environment.sh [--register-only]' \
      'Install the pinned Linux CPU environment and register the kernel at this checkout.' \
      '--register-only refreshes an already installed environment after moving the folder.'
    exit 0 ;;
  '') ;;
  *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
esac
if [[ $# -gt 1 ]]; then
  printf '%s\n' 'Expected at most one option; use --help.' >&2
  exit 2
fi
export UV_CACHE_DIR="$PROJECT_DIR/.cache/uv"
export UV_PYTHON_INSTALL_DIR="$PROJECT_DIR/.cache/python"
export PIP_CACHE_DIR="$PROJECT_DIR/.cache/pip"
export PYTHONDONTWRITEBYTECODE=1
if [[ "$REGISTER_ONLY" -eq 0 ]]; then
  if command -v uv >/dev/null 2>&1; then
    if [[ ! -x "$PROJECT_PYTHON" ]]; then
      uv venv --python 3.12 "$PROJECT_DIR/.venv"
    fi
    "$PROJECT_PYTHON" -c 'import sys; assert sys.version_info[:2] == (3,12), "This lock targets Python 3.12; recreate .venv with Python 3.12."'
    uv pip install --python "$PROJECT_PYTHON" --torch-backend cpu -r "$PROJECT_DIR/requirements.lock.txt"
  else
    if [[ ! -x "$PROJECT_PYTHON" ]]; then
      if ! command -v python3.12 >/dev/null 2>&1; then
        printf '%s\n' 'Install uv, or Python 3.12 with venv support, then rerun this script.' >&2
        exit 1
      fi
      python3.12 -m venv "$PROJECT_DIR/.venv"
    fi
    "$PROJECT_PYTHON" -c 'import sys; assert sys.version_info[:2] == (3,12), "This lock targets Python 3.12; recreate .venv with Python 3.12."'
    if ! "$PROJECT_PYTHON" -m pip --version >/dev/null 2>&1; then
      "$PROJECT_PYTHON" -m ensurepip --upgrade
    fi
    "$PROJECT_PYTHON" -m pip install 'torch==2.10.0+cpu' --index-url https://download.pytorch.org/whl/cpu
    "$PROJECT_PYTHON" -m pip install -r "$PROJECT_DIR/requirements.lock.txt"
  fi
fi
if [[ ! -x "$PROJECT_PYTHON" ]]; then
  printf '%s\n' 'Project environment is missing; run setup without --register-only.' >&2
  exit 1
fi
"$PROJECT_PYTHON" "$PROJECT_DIR/scripts/register_kernel.py"
"$PROJECT_PYTHON" -c 'import sys, torch, nbclient, nbformat, jupyterlab; print(sys.executable); print("PyTorch",torch.__version__)'
printf '%s\n' 'Ready. Launch: bash scripts/open_jupyter.sh' \
  'Portable checks: .venv/bin/python scripts/check_portable.py'
