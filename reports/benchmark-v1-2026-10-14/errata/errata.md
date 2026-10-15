# Frozen benchmark timing errata

Primary snapshot: 96/96 trials observed; 4 invalid-evidence rows. This diagnostic establishes 4 timing-only mismatches and leaves 0 invalid rows unsupported.

All original files, primary outcomes, task-correctness flags and comparison denominators remain unchanged. In-memory canonicalization diagnoses the failed guard; it does not accept, promote or rerun a task.

The frozen worker sums `duration_ns / 1e9` per call. The frozen reporter divides the integer nanosecond sum by `1e9` and compares floats with exact equality. Different rounding can therefore reject otherwise intact evidence.

| Model | Method | Case | Repeat | Primary / raw worker outcome | Original seconds | Canonical seconds | Difference seconds | Sole rounding guard? |
|---|---|---|---:|---|---:|---:|---:|---|
| qwen25-coder-1.5b | feedback | file-new-path | 1 | invalid_evidence / budget_exhausted | 29.127216277000002 | 29.127216277 | 3.552713678800501e-15 | True |
| qwen25-coder-1.5b | feedback | sqlite-new-path | 0 | invalid_evidence / budget_exhausted | 14.273373031000002 | 14.273373031 | 1.7763568394002505e-15 | True |
| qwen25-coder-1.5b | feedback | sqlite-already-secure | 0 | invalid_evidence / budget_exhausted | 38.732174154000006 | 38.732174154 | 7.105427357601002e-15 | True |
| qwen25-3b | feedback | sqlite-already-secure | 1 | invalid_evidence / budget_exhausted | 65.29084671199999 | 65.290846712 | -1.4210854715202004e-14 | True |

## Unsupported invalid rows

None in this snapshot.

## Interpretation

- Exact raw-response hashes, the worker's original summation and every remaining frozen reporter guard must pass before a row is diagnosed as rounding-only.
- Unsupported discrepancies stay unsupported. Neither their outcome nor their evidence state is waived.
- Original `invalid_evidence` outcomes remain visible even when the underlying worker status is a genuine budget failure or accepted candidate.
- This is descriptive report diagnostics, not a corrected primary analysis or remote attestation.
- A future benchmark version should use a shared integer-nanosecond aggregation rule and a multi-call regression test.
