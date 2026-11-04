#!/usr/bin/env python3
"""Recreate the project-local kernelspec for the current checkout location."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv' / 'bin' / 'python'


def main() -> None:
    if not PYTHON.is_file() or not os.access(PYTHON, os.X_OK):
        raise SystemExit('Project interpreter is missing. Run bash scripts/setup_environment.sh first.')
    import ipykernel  # noqa: F401 — fail here if the environment is incomplete

    kernel = ROOT / '.jupyter' / 'kernels' / 'vgu-rehearsal'
    kernel.mkdir(parents=True, exist_ok=True)
    spec = {
        'argv': [str(PYTHON), '-m', 'ipykernel_launcher', '-f', '{connection_file}'],
        'display_name': 'VGU rehearsal (CPU)',
        'language': 'python',
        'env': {'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
                'PYTHONDONTWRITEBYTECODE': '1',
                'MPLCONFIGDIR': str(ROOT / '.cache' / 'matplotlib'),
                'TORCH_HOME': str(ROOT / '.cache' / 'torch'),
                'IPYTHONDIR': str(ROOT / '.runtime' / 'ipython')},
    }
    (kernel / 'kernel.json').write_text(json.dumps(spec, indent=2) + '\n')
    print(f'Registered VGU rehearsal (CPU): {PYTHON}')


if __name__ == '__main__':
    main()
