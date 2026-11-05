#!/usr/bin/env python3
"""Check the cloned package without the original host/private evidence tree.

This reads saved notebook/deck outputs and runs packaged reference tests. It
never executes or saves a notebook, regenerates a deck, edits an execution
manifest, or certifies the original FR-001..017 audit or human comprehension.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import nbformat
import pymupdf
from pptx import Presentation

ROOT = Path(__file__).resolve().parents[1]
DECKS = [
    ('trial_lecture.json', 'Trial_Lecture_30min', 14, 30),
    ('research_orientation.json', 'Research_Orientation_20min', 12, 20),
]


def ensure(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-tests', action='store_true', help='Inspect saved outputs only; explicitly skip behavioral tests.')
    args = parser.parse_args()
    result = {'scope': 'Portable package checks only; not the original 17-requirement host/provenance audit.',
              'notebook_execution': 'Saved outputs inspected; notebooks are not rerun.',
              'notebook_rows': [], 'deck_rows': [], 'errors': [],
              'manifests_modified': False, 'human_rehearsal': 'Not assessed.'}
    try:
        notebook_paths = sorted((ROOT / 'notebooks').rglob('*.ipynb'))
        ensure(notebook_paths, 'No runnable notebooks were discovered')
        result['discovered_notebooks'] = [str(path.relative_to(ROOT)) for path in notebook_paths]
        for path in notebook_paths:
            name = str(path.relative_to(ROOT))
            nb = nbformat.read(path, as_version=4)
            nbformat.validate(nb)
            cells = [c for c in nb.cells if c.cell_type == 'code']
            counts = [c.execution_count for c in cells]
            outputs = sum(len(c.get('outputs', [])) for c in cells)
            errors = [o for c in cells for o in c.get('outputs', []) if o.output_type == 'error']
            bypasses = [(index, sorted(set(c.metadata.get('tags', [])) & {'raises-exception', 'skip-execution'}))
                        for index, c in enumerate(nb.cells)
                        if set(c.metadata.get('tags', [])) & {'raises-exception', 'skip-execution'}]
            ensure(not bypasses, f'{name}: forbidden execution-bypass tags {bypasses}')
            ensure(cells and counts == list(range(1, len(cells)+1)), f'{name}: incomplete saved execution counts')
            ensure(outputs > 0 and not errors, f'{name}: missing visible outputs or saved error')
            result['notebook_rows'].append({'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'code_cells': len(cells),
                                            'outputs': outputs, 'saved_errors': len(errors)})
        layout = json.loads((ROOT / 'verification' / 'slides_layout.json').read_text())
        ensure(not layout.get('bounds_violations'), 'Recorded slide bounds violations')
        ensure(not layout.get('text_overlap_violations'), 'Recorded slide text overlaps')
        for source_name, stem, count, minutes in DECKS:
            source_path = ROOT / 'content' / source_name
            data = json.loads(source_path.read_text())
            ensure(len(data['slides']) == count, f'{stem}: source count differs')
            ensure(sum(s['minutes'] for s in data['slides']) == minutes == data['total_minutes'], f'{stem}: schedule differs')
            pptx = Presentation(ROOT / 'slides' / f'{stem}.pptx')
            with pymupdf.open(ROOT / 'slides' / f'{stem}.pdf') as pdf:
                ensure(len(pdf) == len(pptx.slides) == count, f'{stem}: PDF/PPTX count differs')
            for slide, record in zip(pptx.slides, data['slides']):
                ensure(record['speaker_notes'] in slide.notes_slide.notes_text_frame.text, f'{stem}: presenter notes differ')
            record = next(d for d in layout['decks'] if d['name'] == stem)
            ensure(hashlib.sha256(source_path.read_bytes()).hexdigest() == record['source_sha256'], f'{stem}: source changed since recorded rendering')
            result['deck_rows'].append({'name': stem, 'slides': count, 'minutes': minutes, 'source_notes_present': True})
        kernel_path = ROOT / '.jupyter' / 'kernels' / 'vgu-rehearsal' / 'kernel.json'
        ensure(kernel_path.is_file(), 'Project kernel missing; run setup_environment.sh or open_jupyter.sh first')
        kernel = json.loads(kernel_path.read_text())
        ensure(kernel['argv'][0] == str(ROOT / '.venv' / 'bin' / 'python'), 'Project kernel points to another checkout; rerun setup --register-only')
        result['kernel'] = {'name': 'vgu-rehearsal', 'matches_current_checkout': True}
        if args.skip_tests:
            result['behavioral_tests'] = {'status': 'skipped', 'reason': '--skip-tests requested'}
        else:
            env = os.environ.copy()
            env.update(PYTHONDONTWRITEBYTECODE='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
            # Do not inherit options that create/overwrite a host XML report.
            env.pop('PYTEST_ADDOPTS', None)
            run = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests'],
                                 cwd=ROOT, env=env, text=True, capture_output=True, timeout=120)
            result['behavioral_tests'] = {'exit_code': run.returncode, 'output': run.stdout.strip(), 'stderr': run.stderr.strip()}
            ensure(run.returncode == 0, 'Packaged reference behavioral tests failed')
            tier_run = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests'],
                                      cwd=ROOT / 'notebooks/student_exercises', env=env, text=True, capture_output=True, timeout=120)
            result['completed_tier12_tests'] = {'exit_code': tier_run.returncode, 'output': tier_run.stdout.strip(), 'stderr': tier_run.stderr.strip()}
            ensure(tier_run.returncode == 0, 'Completed Tier 1–2 example tests failed')
        practice = ROOT / 'teaching/STUDENT_PRACTICE.md'
        ensure(practice.is_file() and practice.stat().st_size > 500, 'Separate Markdown practice prompts are missing')
        result['completed_tier12_examples'] = 'Provided complete examples; both legacy Student filenames must execute without errors. No claim of learner completion.'
        result['practice_prompts'] = 'teaching/STUDENT_PRACTICE.md; unanswered practice is outside runnable notebooks.'
    except Exception as exc:
        result['errors'].append(f'{type(exc).__name__}: {exc}')
    result['status'] = 'pass' if not result['errors'] else 'fail'
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
