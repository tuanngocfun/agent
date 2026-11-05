"""Strictly execute EVERY canonical notebook recursively and save real outputs.

Each notebook gets a fresh kernel in its own directory. There is no expected-
error, allowed-error, or skipped-cell exception for runnable lecture material.
Unanswered practice prompts live in teaching/STUDENT_PRACTICE.md instead.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = ROOT / 'notebooks'
VERIFY = ROOT / 'verification'
FORBIDDEN_TAGS = {'raises-exception', 'skip-execution'}
STATUS_MARKER = '<!-- canonical-execution-status:end -->'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_text(notebook):
    return [cell.source for cell in notebook.cells if cell.cell_type == 'code']


def object_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def inspect_cells(notebook):
    rows = []
    for index, cell in enumerate(notebook.cells):
        if cell.cell_type != 'code':
            continue
        outputs = cell.get('outputs', [])
        rows.append({
            'cell_index': index,
            'execution_count': cell.get('execution_count'),
            'source_sha256': hashlib.sha256(cell.source.encode()).hexdigest(),
            'output_count': len(outputs),
            'outputs_sha256': object_digest([dict(output) for output in outputs]),
            'output_types': [output.output_type for output in outputs],
            'errors': [{'ename': output.ename, 'evalue': output.evalue}
                       for output in outputs if output.output_type == 'error'],
            'text_outputs': [output.text for output in outputs if output.output_type == 'stream'],
            'image_output_count': sum('image/png' in output.get('data', {}) for output in outputs),
            'execution_bypass_tags': sorted(set(cell.metadata.get('tags', [])) & FORBIDDEN_TAGS),
        })
    return rows


def write_manifest(rows, paths, finished=False):
    passed = finished and len(rows) == len(paths) and all(row['status'] == 'pass' for row in rows)
    result = {
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'python_executable': '.venv/bin/python',
        'python_runtime': 'The interpreter invoking this checkout-local runner; absolute host paths are deliberately omitted from portable evidence.',
        'python_version': sys.version,
        'run_status': 'pass' if passed else ('fail' if finished else 'in_progress'),
        'policy': ('Every .ipynb recursively under notebooks/; fresh independent kernel in each notebook parent; '
                   'allow_errors=False; force_raise_errors=True; allow_error_names=[]; '
                   'raises-exception and skip-execution tags forbidden. Source code is unchanged during execution. '
                   'All examples, including legacy Student filenames, must complete; blank practice is Markdown only.'),
        'discovered_notebooks': [str(path.relative_to(ROOT)) for path in paths],
        'notebooks': rows,
        'summary': {
            'discovered_notebooks': len(paths),
            'processed_notebooks': len(rows),
            'strict_passed_notebooks': sum(row['status'] == 'pass' for row in rows),
            'code_cells': sum(row['code_cells'] for row in rows),
            'executed_code_cells': sum(row['executed_code_cells'] for row in rows),
            'output_count': sum(row['output_count'] for row in rows),
            'image_output_count': sum(row['image_output_count'] for row in rows),
            'error_output_count': sum(len(cell['errors']) for row in rows for cell in row['per_cell']),
            'all_strict_pass': passed,
        },
    }
    (VERIFY / 'notebook_execution.json').write_text(json.dumps(result, indent=2) + '\n')


def main():
    VERIFY.mkdir(exist_ok=True)
    runtime = ROOT / '.runtime'
    for directory in [runtime, runtime / 'ipython', runtime / 'tmp', ROOT / '.cache/matplotlib', ROOT / '.cache/torch']:
        directory.mkdir(parents=True, exist_ok=True)
    kernel = ROOT / '.jupyter/kernels/vgu-rehearsal'
    kernel.mkdir(parents=True, exist_ok=True)
    (kernel / 'kernel.json').write_text(json.dumps({
        'argv': [sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}'],
        'display_name': 'VGU rehearsal (CPU)', 'language': 'python',
    }, indent=2) + '\n')
    os.environ.update({
        'JUPYTER_PATH': str(ROOT / '.jupyter'), 'JUPYTER_RUNTIME_DIR': str(runtime),
        'IPYTHONDIR': str(runtime / 'ipython'), 'TMPDIR': str(runtime / 'tmp'),
        'MPLCONFIGDIR': str(ROOT / '.cache/matplotlib'), 'TORCH_HOME': str(ROOT / '.cache/torch'),
        'PYTHONDONTWRITEBYTECODE': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
    })
    paths = sorted(NOTEBOOKS.rglob('*.ipynb'))
    if not paths:
        raise RuntimeError('No runnable notebooks found under notebooks/')
    rows = []
    write_manifest(rows, paths)
    for path in paths:
        started = time.perf_counter()
        notebook = nbformat.read(path, as_version=4)
        nbformat.validate(notebook)
        sources = code_text(notebook)
        sha_before = digest(path)
        if not notebook.cells or notebook.cells[0].cell_type != 'markdown':
            notebook.cells.insert(0, nbformat.v4.new_markdown_cell(''))
        for cell in notebook.cells:
            if cell.cell_type == 'code':
                cell.outputs = []
                cell.execution_count = None
        error = None
        bypasses = [{'cell_index': index, 'tags': sorted(set(cell.metadata.get('tags', [])) & FORBIDDEN_TAGS)}
                    for index, cell in enumerate(notebook.cells)
                    if set(cell.metadata.get('tags', [])) & FORBIDDEN_TAGS]
        try:
            if bypasses:
                raise ValueError(f'Execution bypass tags are forbidden: {bypasses}')
            NotebookClient(
                notebook, timeout=180, kernel_name='vgu-rehearsal',
                allow_errors=False, force_raise_errors=True, allow_error_names=[],
                resources={'metadata': {'path': str(path.parent)}},
            ).execute()
        except Exception as exc:
            error = {'type': type(exc).__name__, 'message': str(exc).replace(str(ROOT), '.').replace(str(Path.home()), '<user-home>')}
        if code_text(notebook) != sources:
            raise RuntimeError(f'Code changed during execution: {path}')
        cells = inspect_cells(notebook)
        counts = [cell['execution_count'] for cell in cells]
        complete = (bool(cells) and error is None and
                    counts == list(range(1, len(cells) + 1)) and
                    all(not cell['errors'] and not cell['execution_bypass_tags'] for cell in cells))
        status = 'PASS: fresh worked-example execution' if complete else 'FAIL: incomplete strict execution; inspect errors'
        narrative = notebook.cells[0].source
        if STATUS_MARKER in narrative:
            narrative = narrative.split(STATUS_MARKER, 1)[1].lstrip('\n')
        notebook.cells[0].source = (
            f'**{status}.** All saved outputs below came from this notebook\'s actual code. '
            f'Run UTC: `{datetime.now(timezone.utc).isoformat()}`; '
            f'executed {sum(cell["execution_count"] is not None for cell in cells)}/{len(cells)} code cells; '
            f'{sum(cell["output_count"] for cell in cells)} output objects; '
            f'{sum(len(cell["errors"]) for cell in cells)} saved errors. '
            f'No execution errors are allowed or suppressed. These are provided worked examples; '
            f'unanswered learner practice is separate Markdown. The synthetic scope still applies.\n'
            f'{STATUS_MARKER}\n\n{narrative}'
        )
        notebook.metadata['kernelspec'] = {'display_name': 'VGU rehearsal (CPU)', 'language': 'python', 'name': 'vgu-rehearsal'}
        nbformat.validate(notebook)
        nbformat.write(notebook, path)
        saved = nbformat.read(path, as_version=4)
        if code_text(saved) != sources or inspect_cells(saved) != cells:
            raise RuntimeError(f'Saved code/outputs differ from fresh execution: {path}')
        relative = str(path.relative_to(ROOT))
        rows.append({
            'path': relative, 'relative_path': relative,
            'role': 'provided_completed_tier_example' if 'Tier' in path.name else 'provided_worked_example',
            'status': 'pass' if complete else 'fail',
            'allow_errors': False, 'force_raise_errors': True, 'allow_error_names': [],
            'forbidden_execution_tags': sorted(FORBIDDEN_TAGS),
            'sha256_before': sha_before, 'sha256_after': digest(path),
            'code_sha256_before': object_digest(sources), 'code_sha256_after': object_digest(code_text(saved)),
            'code_unchanged': True, 'saved_outputs_verified': True,
            'code_cells': len(cells), 'executed_code_cells': sum(cell['execution_count'] is not None for cell in cells),
            'output_count': sum(cell['output_count'] for cell in cells),
            'image_output_count': sum(cell['image_output_count'] for cell in cells),
            'errors': error, 'elapsed_s': round(time.perf_counter() - started, 3), 'per_cell': cells,
        })
        write_manifest(rows, paths)
        print(f'{status}: {relative}; cells {rows[-1]["executed_code_cells"]}/{len(cells)}; '
              f'outputs {rows[-1]["output_count"]}', flush=True)
    write_manifest(rows, paths, finished=True)
    return int(any(row['status'] != 'pass' for row in rows))


if __name__ == '__main__':
    raise SystemExit(main())
