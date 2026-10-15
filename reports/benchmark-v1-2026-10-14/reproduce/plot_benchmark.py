"""Render actual registered results with Matplotlib; never synthesize cells."""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--summary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.summary.read_bytes()
    summary = json.loads(raw)
    plan = summary['plan']
    args.output.mkdir(parents=True, exist_ok=False)
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'svg.fonttype': 'none'})
    groups = [(model['model_id'], method['method_id']) for model in plan['models'] for method in plan['methods']]
    cells = {(row['model_id'], row['method_id'], row['case_id'], row['repetition']): row for row in summary['trials']}
    categories = [('C', '#2a8c78', 'Task correct'), ('F', '#d48a2f', 'Verified failed task'),
                  ('I', '#9f4b7e', 'Infrastructure failure'), ('X', '#b44444', 'Invalid evidence'),
                  ('M', '#e2e5e9', 'Missing')]
    colors = {code: color for code, color, _ in categories}
    figure, axis = plt.subplots(figsize=(13, 5.7))
    case_ids = [case['case_id'] for case in plan['cases']]
    for y, group in enumerate(groups):
        for case_index, case in enumerate(case_ids):
            for repeat in range(plan['repetitions']):
                row = cells[(*group, case, repeat)]
                if row['outcome'] == 'missing': code = 'M'
                elif row['outcome'] == 'infrastructure_failure': code = 'I'
                elif row['outcome'] == 'invalid_evidence': code = 'X'
                elif row['task_correct']: code = 'C'
                else: code = 'F'
                x = case_index * plan['repetitions'] + repeat
                axis.add_patch(plt.Rectangle((x - .46, y - .42), .92, .84,
                                             facecolor=colors[code], edgecolor='white'))
                axis.text(x, y, code, ha='center', va='center',
                          color='#303642' if code == 'M' else 'white', fontweight='bold')
    axis.set_xlim(-.6, len(case_ids) * plan['repetitions'] - .4)
    axis.set_ylim(len(groups) - .4, -.6)
    axis.set_yticks(range(len(groups)), [model + ' / ' + method for model, method in groups])
    axis.set_xticks([i * plan['repetitions'] + (plan['repetitions'] - 1) / 2 for i in range(len(case_ids))],
                   [case.replace('-', '\n', 1) for case in case_ids])
    axis.tick_params(length=0)
    axis.set_xlabel('Each case has two adjacent cells: repetition 0, then 1', labelpad=12)
    coverage = summary['coverage']
    axis.set_title(f"Registered trial outcomes — {coverage['observed_trials']}/{coverage['expected_trials']} observed, "
                   f"{coverage['verified_trials']} verified", loc='left', pad=17, fontweight='bold')
    axis.legend(handles=[Patch(facecolor=color, label=code + ': ' + label) for code, color, label in categories],
                loc='upper center', bbox_to_anchor=(.5, -.25), ncol=3, frameon=False)
    figure.text(.02, .02, 'Eight public authored cases across two fixture families. Repetitions are not independent cases.', fontsize=8)
    figure.subplots_adjust(left=.25, right=.98, top=.88, bottom=.33)
    save(figure, args.output, 'trial-outcomes')

    figure, axis = plt.subplots(figsize=(10.5, 5.7))
    methods = [method['method_id'] for method in plan['methods']]
    method_colors = {'one-shot': '#376a9d', 'feedback': '#d48a2f'}
    models = [model['model_id'] for model in plan['models']]
    incomplete = []
    for group in summary['groups']:
        model, method = group['model_id'], group['method_id']
        location = models.index(model) + (-.18 if method == methods[0] else .18)
        score = group['case_task_correct']
        rate = 100 * score['rate'] if score['rate'] is not None else 0
        complete = group['observed_trials'] == group['expected_trials'] and group['verified_trials'] == group['expected_trials']
        if not complete:
            incomplete.append(model + '/' + method)
            axis.text(location, 10, f"incomplete\n{group['verified_trials']}/{group['expected_trials']} verified",
                      ha='center', va='bottom', fontsize=7, color=method_colors[method],
                      bbox={'facecolor': 'white', 'edgecolor': method_colors[method], 'boxstyle': 'round,pad=.3'})
            continue
        axis.bar(location, rate, width=.32, color=method_colors[method], alpha=1 if complete else .45,
                 hatch=None if complete else '//')
        if score['rate'] is not None:
            axis.errorbar(location, rate, yerr=[[rate - 100 * score['low']], [100 * score['high'] - rate]],
                          color='#303642', capsize=3, fmt='none')
        axis.text(location, min(104, rate + 4), f"{score['successes']}/{score['cases']}", ha='center', fontsize=9)
    axis.set_xticks(range(len(models)), models)
    axis.set_xlim(-.6, len(models) - .4)
    axis.set_ylim(0, 110)
    axis.set_yticks(range(0, 101, 20), [str(value) + '%' for value in range(0, 101, 20)])
    axis.set_ylabel('Cases correct in both registered repetitions')
    axis.set_title('Demonstrated task completion by distinct case', loc='left', fontweight='bold', pad=14)
    axis.legend(handles=[Patch(facecolor=method_colors[method], label=method) for method in methods], frameon=False)
    axis.grid(axis='y', alpha=.2)
    axis.set_axisbelow(True)
    figure.text(.02, .07, 'Error bars: descriptive Wilson 95% intervals over 8 authored cases, not a random population sample.', fontsize=8)
    figure.text(.02, .035, 'No rate estimate is plotted for groups with incomplete verified coverage; the full registered denominator remains in the report.', fontsize=8)
    figure.subplots_adjust(left=.10, right=.98, top=.88, bottom=.20)
    save(figure, args.output, 'case-completion')

    figure, axis = plt.subplots(figsize=(10.5, 6))
    markers = {'one-shot': 'o', 'feedback': '^'}
    model_colors = dict(zip(models, ['#376a9d', '#ba6d25', '#2a8c78']))
    plotted = 0
    for model, method in groups:
        rows = [row for row in summary['trials'] if row['model_id'] == model and row['method_id'] == method
                and row['evidence_verified'] and row['metrics'].get('total_tokens') is not None
                and row['metrics'].get('wall_seconds') is not None]
        if not rows: continue
        plotted += len(rows)
        axis.scatter([row['metrics']['total_tokens'] for row in rows],
                     [row['metrics']['wall_seconds'] for row in rows],
                     label=f'{model} / {method} (n={len(rows)})', marker=markers[method],
                     color=model_colors[model], alpha=.75, s=40, edgecolors='white', linewidths=.5)
    axis.set_xlim(left=0)
    axis.set_ylim(bottom=0)
    axis.set_xlabel('Actual server-reported prompt + output tokens per task')
    axis.set_ylabel('Task wall time, including protected tests (seconds)')
    axis.set_title(f'Observed task cost — {plotted} verified rows with complete measurements', loc='left', fontweight='bold')
    if plotted: axis.legend(frameon=False, fontsize=8)
    axis.grid(alpha=.2)
    figure.text(.02, .035, 'Setup/download/cluster costs are separate. Shared-runner hardware and contention vary; unavailable costs are omitted, not zero.', fontsize=8)
    figure.subplots_adjust(left=.10, right=.98, top=.88, bottom=.17)
    save(figure, args.output, 'task-cost')
    metadata = {'plan_id': summary['plan_id'], 'input_summary_sha256': hashlib.sha256(raw).hexdigest(),
                'matplotlib': matplotlib.__version__, 'coverage': coverage,
                'figure_names': ['trial-outcomes', 'case-completion', 'task-cost'],
                'interpretation': 'Descriptive visualization of frozen outcomes; no new primary score or significance claim.'}
    (args.output / 'figure-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(metadata))


def save(figure, output, name):
    for extension in ('svg', 'png', 'pdf'):
        figure.savefig(output / (name + '.' + extension), dpi=170)
    plt.close(figure)


if __name__ == '__main__':
    main()
