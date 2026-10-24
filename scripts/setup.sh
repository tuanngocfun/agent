#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p .cache/tmp
export TMPDIR="$PWD/.cache/tmp"
export UV_CACHE_DIR="$PWD/.cache/uv"
if command -v uv >/dev/null 2>&1; then
  [ -x .venv/bin/python ] || uv venv --python python3 .venv
else
  [ -x .venv/bin/python ] || python3 -m venv .venv
fi
if [ ! -d vendor/Kronos/.git ]; then
  git clone https://github.com/shiyu-coder/Kronos.git vendor/Kronos
fi
if [ -n "$(git -C vendor/Kronos status --porcelain --untracked-files=no)" ]; then
  printf 'vendor/Kronos contains local modifications; preserve them before setup.\n' >&2
  exit 1
fi
git -C vendor/Kronos checkout --detach 67b630e67f6a18c9e9be918d9b4337c960db1e9a
if command -v uv >/dev/null 2>&1; then
  uv pip install --python .venv/bin/python -e '.[dev,market]'
else
  .venv/bin/python -m pip install -e '.[dev,market]'
fi
printf '\nSetup complete. Optional Chronos-2: uv pip install --python .venv/bin/python -e ".[compare]"\n'
