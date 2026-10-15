#!/usr/bin/env python3
"""Offline integrity and count audit; does not execute imported workloads."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import import_kalm_corpus as kalm
import import_itbench_corpus as itbench
import import_runtime_corpus as infra


def read_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8_000_000:
        raise ValueError('Expected bounded regular JSON: ' + str(path))
    return json.loads(path.read_text())


def contained_file(root, relative):
    path = Path(relative)
    if not relative or path.is_absolute() or '..' in path.parts or '\\' in relative or str(path) != relative:
        raise ValueError('Unsafe corpus path')
    target = root / path
    if any(p.is_symlink() for p in (target, *target.parents) if p == root or root in p.parents):
        raise ValueError('Symlink in corpus path')
    if not target.is_file():
        raise ValueError('Missing corpus file: ' + str(target))
    return target


def verify_bytes(root, row, *, sha_key='sha256', size_key='bytes'):
    data = contained_file(root, row['path']).read_bytes()
    if len(data) != row[size_key] or hashlib.sha256(data).hexdigest() != row[sha_key]:
        raise ValueError('Corpus bytes changed: ' + row['path'])
    return data


def verify_kalm(root):
    summary = read_json(root / 'summary.json')
    pin = read_json(root / 'provenance.json')
    if pin['repository'] != kalm.REPOSITORY or pin['commit'] != kalm.COMMIT:
        raise ValueError('KALM source pin changed')
    inventory = pin['source_inventory']
    kalm.verify_source_inventory(inventory)
    source_by_path = {row['path']: row for row in inventory}
    if len(source_by_path) != len(inventory):
        raise ValueError('Duplicate KALM source path')
    for row in inventory:
        relative = 'raw/' + row['path'] if row['path'].startswith('manifests/') else row['path']
        data = verify_bytes(root, {**row, 'path': relative})
        if infra.git_blob_sha(data) != row['git_blob_sha1']:
            raise ValueError('KALM source Git blob changed')
    records = [json.loads(line) for line in (root / 'records.jsonl').read_text().splitlines()]
    if len(records) != kalm.EXPECTED_FILES or len({r['candidate_id'] for r in records}) != len(records):
        raise ValueError('KALM candidate inventory changed')
    recomputed = []
    expected_inputs = set()
    for record in records:
        raw = contained_file(root, 'raw/' + record['source_path']).read_bytes()
        current, agent_input = kalm.make_record(record['source_path'], raw)
        current['source_git_blob_sha1'] = source_by_path[record['source_path']]['git_blob_sha1']
        recomputed.append(current)
        relative = 'agent-inputs/' + current['candidate_id'] + '.json'
        expected_inputs.add(relative)
        if contained_file(root, relative).read_bytes() != kalm.canonical(agent_input) + b'\n':
            raise ValueError('KALM agent view changed or exposes source labels')
    partitions = kalm.assign_partitions(recomputed)
    if recomputed != records or partitions != summary['partitions']:
        raise ValueError('KALM records or grouping differ from original inputs')
    actual_inputs = {p.relative_to(root).as_posix() for p in (root / 'agent-inputs').rglob('*') if p.is_file()}
    if actual_inputs != expected_inputs:
        raise ValueError('Unregistered agent input')
    for field in ('exact_duplicate_group', 'semantic_duplicate_group'):
        groups = {}
        for row in records:
            groups.setdefault(row[field], set()).add(row['partition'])
        if any(len(values) != 1 for values in groups.values()):
            raise ValueError('Duplicate group crosses a split')
    if any(row['runtime_validated'] is not False or row['runtime_contract'] is not None for row in records):
        raise ValueError('Import cannot claim runtime validation')
    counts = {'manifest_files': len(records), 'resource_documents': sum(r['document_count'] for r in records),
        'labeled_candidates': sum(bool(r['oracle_annotations']) for r in records),
        'support_files': sum(r['partition'] == 'support' for r in records),
        'identifier_normalized_structural_groups': len({r['semantic_duplicate_group'] for r in records}),
        'rule_families': len({family for r in records for family in r['source_rule_families']}),
        'partitions': dict(sorted(Counter(r['partition'] for r in records).items())),
        'runtime_validated': 0, 'model_runs': 0}
    if (counts['manifest_files'], counts['resource_documents'], counts['labeled_candidates']) != (241, 445, 238):
        raise ValueError('KALM dataset counts changed')
    return counts


def verify_infra(root):
    manifest = read_json(root / 'manifest.json')
    if manifest['repository'] != infra.REPOSITORY or manifest['commit'] != infra.COMMIT:
        raise ValueError('Infra-Bench source pin changed')
    tree_data = (root / 'source-tree.json').read_bytes()
    if hashlib.sha256(tree_data).hexdigest() != manifest['source_tree_sha256']:
        raise ValueError('Infra-Bench source inventory changed')
    source_tree = json.loads(tree_data)
    infra.verify_source_inventory(source_tree)
    roots, sources = infra.select_files(source_tree)
    registered = {row['path'] for row in manifest['files']}
    if len(registered) != len(manifest['files']):
        raise ValueError('Duplicate imported path')
    if len(manifest['files']) != manifest['file_count'] or len(sources) != manifest['file_count']:
        raise ValueError('Infra-Bench file totals changed')
    contents = {}
    for row in manifest['files']:
        data = verify_bytes(root, row)
        contents[row['source_path']] = data
        if infra.git_blob_sha(data) != sources[row['source_path']]['sha']:
            raise ValueError('Infra-Bench source Git blob changed')
        expected_path, expected_role = infra.destination_path(row['source_path'], roots)
        if (row['path'], row['role']) != (expected_path, expected_role):
            raise ValueError('Protected asset promoted into model input')
        if contained_file(root, row['path']).stat().st_mode & 0o111:
            raise ValueError('Imported scripts must not have executable permissions')
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    if actual != registered | {'manifest.json', 'source-tree.json', 'README.md'}:
        raise ValueError('Unregistered or missing Infra-Bench asset')
    cases = manifest['cases']
    expected_cases = infra.derive_cases(roots, contents, manifest['files'])
    if cases != expected_cases:
        raise ValueError('Infra-Bench case metadata differs from pinned task definitions')
    if manifest['case_count'] != len(expected_cases):
        raise ValueError('Infra-Bench declared case total changed')
    if manifest['security_discovery_candidate_count'] != sum(bool(case['discovery_only_security_terms']) for case in expected_cases):
        raise ValueError('Infra-Bench discovery count differs from pinned metadata')
    if len(cases) != infra.EXPECTED_CASES or len({c['case_id'] for c in cases}) != len(cases):
        raise ValueError('Infra-Bench case count changed')
    for case in cases:
        if case['locally_runtime_validated'] is not False or case['ready_for_our_agent'] is not False:
            raise ValueError('Imported tasks cannot claim local execution')
        expected_input = f"cases/{case['case_id']}/agent-inputs/instruction.md"
        if case['agent_input_files'] != [expected_input]:
            raise ValueError('Unexpected model input')
        rows = [r for r in manifest['files'] if r['path'] == expected_input]
        if len(rows) != 1 or rows[0]['role'] != 'untrusted_agent_instruction':
            raise ValueError('Instruction input is not bound to pinned source')
        if set(case['agent_input_files']) & set(case['protected_files']):
            raise ValueError('Answer or verifier exposed as model input')
    return {'task_definitions': len(cases), 'source_assets': len(sources),
        'categories': dict(sorted(Counter(c['upstream_category'] for c in cases).items())),
        'access_and_isolation_candidates': [c['case_id'] for c in cases if c['upstream_category'] == 'access-and-isolation'],
        'runtime_validated': 0, 'ready_for_current_agent': 0, 'model_runs': 0}


def audit(root):
    if root.is_symlink():
        raise ValueError('Corpus root cannot be a symlink')
    kalm_result = verify_kalm(root / 'kalm')
    itbench_result = itbench.verify_corpus(root / 'itbench')
    infra_result = verify_infra(root / 'infra-bench')
    return {'schema_version': 1, 'status': 'offline_intake_verified',
        'kalm': kalm_result, 'itbench': itbench_result, 'infra_bench': infra_result,
        'new_runtime_validated_cases': 0, 'new_model_results': 0, 'v2_experiment_registered': False,
        'notes': ['Counts use different units and must not be pooled as independent runtime tasks.',
                  'V1 remains eight executed authored cases; imported definitions add no measured successes.',
                  'Oracle separation is by input packaging; filesystem/runtime isolation remains to be implemented.',
                  'Source hashes verify bytes, not security truth or behavior-preserving repair correctness.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus-root', type=Path, default=Path('benchmark/corpus-v2'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check-summary', type=Path)
    args = parser.parse_args()
    result = audit(args.corpus_root)
    if args.check_summary and read_json(args.check_summary) != result:
        parser.exit(2, 'Saved intake summary differs from current corpus\n')
    if args.output:
        with args.output.open('x') as handle:
            json.dump(result, handle, indent=2)
            handle.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
