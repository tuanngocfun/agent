# Registered Kubernetes remediation benchmark

Observed **96/96** registered trials; **87** have revalidated evidence. **0** are missing and **4** have invalid evidence.

All counts below retain failures and missing cells. Success means the registered expected outcome, including unchanged and abstain cases.

## Models and methods

| Model | Frozen pin |
|---|---|
| qwen25-coder-1.5b | `{"manifest_digest": "sha256:d7372fd828518a4d38b1eb196c673c31a85f2ed302b3d1e406c4c2d1b64a0668", "tag": "qwen2.5-coder:1.5b-instruct-q4_K_M", "weight_blob_digest": "sha256:29d8c98fa6b098e200069bfb88b9508dc3e85586d20cba59f8dda9a808165104", "weight_bytes": 986048576}` |
| qwen25-1.5b | `{"manifest_digest": "sha256:65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b", "tag": "qwen2.5:1.5b-instruct-q4_K_M", "weight_blob_digest": "sha256:183715c435899236895da3869489cc30ac241476b4971a20285b1a462818a5b4", "weight_bytes": 986048512}` |
| qwen25-3b | `{"manifest_digest": "sha256:357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b", "tag": "qwen2.5:3b-instruct-q4_K_M", "weight_blob_digest": "sha256:5ee4f07cdb9beadbbb293e85803c569b01bd37ed059d2715faa7bb405f31caa6", "weight_bytes": 1929903008}` |

| Method | Conservative token ceiling | Action budget | Guided schema |
|---|---:|---:|---|
| one-shot | 32768 | 1 | `45f8e52eb09be1d1b340f75a08f0d48ccaa62667c22571425065d16debb0b843` |
| feedback | 32768 | 6 | `45f8e52eb09be1d1b340f75a08f0d48ccaa62667c22571425065d16debb0b843` |

## Registered case results

A case is successful only when every registered repetition is correct. Intervals use distinct cases, including missing cases as success not demonstrated.

| Model | Method | Observed/registered trials | Verified trials | Correct trials | Repair cases | All task cases |
|---|---|---:|---:|---:|---|---|
| qwen25-coder-1.5b | one-shot | 16/16 | 16 | 6 | 3/4 (75.0%; 95% Wilson 30.1–95.4%) | 3/8 (37.5%; 95% Wilson 13.7–69.4%) |
| qwen25-coder-1.5b | feedback | 16/16 | 13 | 4 | 2/4 (50.0%; 95% Wilson 15.0–85.0%) | 2/8 (25.0%; 95% Wilson 7.1–59.1%) |
| qwen25-1.5b | one-shot | 16/16 | 16 | 5 | 0/4 (0.0%; 95% Wilson 0.0–49.0%) | 2/8 (25.0%; 95% Wilson 7.1–59.1%) |
| qwen25-1.5b | feedback | 16/16 | 16 | 4 | 0/4 (0.0%; 95% Wilson 0.0–49.0%) | 2/8 (25.0%; 95% Wilson 7.1–59.1%) |
| qwen25-3b | one-shot | 16/16 | 16 | 8 | 4/4 (100.0%; 95% Wilson 51.0–100.0%) | 4/8 (50.0%; 95% Wilson 21.5–78.5%) |
| qwen25-3b | feedback | 16/16 | 10 | 7 | 3/4 (75.0%; 95% Wilson 30.1–95.4%) | 3/8 (37.5%; 95% Wilson 13.7–69.4%) |

| Model | Method | Correct unchanged cases | Appropriate abstention cases |
|---|---|---|---|
| qwen25-coder-1.5b | one-shot | 0/2 (0.0%; 95% Wilson 0.0–65.8%) | 0/2 (0.0%; 95% Wilson 0.0–65.8%) |
| qwen25-coder-1.5b | feedback | 0/2 (0.0%; 95% Wilson 0.0–65.8%) | 0/2 (0.0%; 95% Wilson 0.0–65.8%) |
| qwen25-1.5b | one-shot | 0/2 (0.0%; 95% Wilson 0.0–65.8%) | 2/2 (100.0%; 95% Wilson 34.2–100.0%) |
| qwen25-1.5b | feedback | 0/2 (0.0%; 95% Wilson 0.0–65.8%) | 2/2 (100.0%; 95% Wilson 34.2–100.0%) |
| qwen25-3b | one-shot | 0/2 (0.0%; 95% Wilson 0.0–65.8%) | 0/2 (0.0%; 95% Wilson 0.0–65.8%) |
| qwen25-3b | feedback | 0/2 (0.0%; 95% Wilson 0.0–65.8%) | 0/2 (0.0%; 95% Wilson 0.0–65.8%) |

## Outcomes and checks

| Model | Method | Outcomes (trial counts) | Behavior pass/fail/unavailable | Static | Runtime security | Cleanup |
|---|---|---|---|---|---|---|
| qwen25-coder-1.5b | one-shot | {"budget_exhausted": 8, "policy_failure": 2, "repaired": 6} | 12/4/0 | 14/2/0 | 10/6/0 | 16/0/0 |
| qwen25-coder-1.5b | feedback | {"budget_exhausted": 9, "invalid_evidence": 3, "repaired": 4} | 8/5/3 | 12/1/3 | 7/6/3 | 13/0/3 |
| qwen25-1.5b | one-shot | {"abstained": 4, "security_failure": 11, "unchanged": 1} | 16/0/0 | 4/12/0 | 4/12/0 | 16/0/0 |
| qwen25-1.5b | feedback | {"abstained": 4, "security_failure": 12} | 16/0/0 | 4/12/0 | 4/12/0 | 16/0/0 |
| qwen25-3b | one-shot | {"budget_exhausted": 8, "repaired": 8} | 12/4/0 | 16/0/0 | 12/4/0 | 16/0/0 |
| qwen25-3b | feedback | {"budget_exhausted": 3, "infrastructure_failure": 5, "invalid_evidence": 1, "repaired": 7} | 9/1/6 | 9/1/6 | 8/2/6 | 10/0/6 |

## Execution cost

Only measurements bound to revalidated evidence are aggregated. Each value includes availability; missing usage is never zero.

| Model | Method | Actual prompt/output/total tokens (sum) | Conservative reserved tokens (sum) | Wall seconds mean | Inference seconds mean | Generation tokens/sec mean |
|---|---|---|---|---|---|---|
| qwen25-coder-1.5b | one-shot | 40659 [16/16 measured]/3201 [16/16 measured]/43860 [16/16 measured] | 169005 [16/16 measured] | 164.802 [16/16 measured] | 139.873 [16/16 measured] | 10.735 [16/16 measured] |
| qwen25-coder-1.5b | feedback | 59899 [13/16 measured]/4313 [13/16 measured]/64212 [13/16 measured] | 248864 [13/16 measured] | 247.506 [13/16 measured] | 213.321 [13/16 measured] | 10.927 [13/16 measured] |
| qwen25-1.5b | one-shot | 40617 [16/16 measured]/353 [16/16 measured]/40970 [16/16 measured] | 168942 [16/16 measured] | 118.464 [16/16 measured] | 105.221 [16/16 measured] | 12.319 [16/16 measured] |
| qwen25-1.5b | feedback | 40595 [16/16 measured]/391 [16/16 measured]/40986 [16/16 measured] | 169001 [16/16 measured] | 122.584 [16/16 measured] | 109.725 [16/16 measured] | 11.849 [16/16 measured] |
| qwen25-3b | one-shot | 40600 [16/16 measured]/3188 [16/16 measured]/43788 [16/16 measured] | 168944 [16/16 measured] | 312.496 [16/16 measured] | 286.436 [16/16 measured] | 5.927 [16/16 measured] |
| qwen25-3b | feedback | 34053 [10/16 measured]/2285 [10/16 measured]/36338 [10/16 measured] | 141756 [10/16 measured] | 291.013 [10/16 measured] | 265.716 [10/16 measured] | 6.395 [10/16 measured] |

| Model | Method | Inspections | Repairs | Tests | Model calls | Protocol rejects | Policy rejects |
|---|---|---|---|---|---|---|---|
| qwen25-coder-1.5b | one-shot | 0 [16/16 measured] | 16 [16/16 measured] | 30 [16/16 measured] | 16 [16/16 measured] | 0 [16/16 measured] | 2 [16/16 measured] |
| qwen25-coder-1.5b | feedback | 0 [13/16 measured] | 21 [13/16 measured] | 34 [13/16 measured] | 22 [13/16 measured] | 0 [13/16 measured] | 1 [13/16 measured] |
| qwen25-1.5b | one-shot | 0 [16/16 measured] | 0 [16/16 measured] | 16 [16/16 measured] | 16 [16/16 measured] | 0 [16/16 measured] | 0 [16/16 measured] |
| qwen25-1.5b | feedback | 0 [16/16 measured] | 0 [16/16 measured] | 16 [16/16 measured] | 16 [16/16 measured] | 0 [16/16 measured] | 0 [16/16 measured] |
| qwen25-3b | one-shot | 0 [16/16 measured] | 16 [16/16 measured] | 32 [16/16 measured] | 16 [16/16 measured] | 0 [16/16 measured] | 0 [16/16 measured] |
| qwen25-3b | feedback | 2 [10/16 measured] | 11 [10/16 measured] | 20 [10/16 measured] | 13 [10/16 measured] | 0 [10/16 measured] | 1 [10/16 measured] |

## Paired descriptive comparisons

Pairs include only cases with complete revalidated repetitions on both sides. Exclusions and action budgets are explicit; these deltas do not establish significance.

| Left | Right | Matched/excluded cases | Left only/both/right only correct | Right − left (percentage points) | Common ceiling/schema | Action budgets |
|---|---|---|---|---|---|---|
| qwen25-coder-1.5b / one-shot | qwen25-coder-1.5b / feedback | 5/3 | 0/2/0 | 0.000 | True | 1/6 |
| qwen25-coder-1.5b / one-shot | qwen25-1.5b / one-shot | 8/0 | 3/0/2 | -12.500 | True | 1/1 |
| qwen25-coder-1.5b / one-shot | qwen25-1.5b / feedback | 8/0 | 3/0/2 | -12.500 | True | 1/6 |
| qwen25-coder-1.5b / one-shot | qwen25-3b / one-shot | 8/0 | 0/3/1 | 12.500 | True | 1/1 |
| qwen25-coder-1.5b / one-shot | qwen25-3b / feedback | 4/4 | 1/2/1 | 0.000 | True | 1/6 |
| qwen25-coder-1.5b / feedback | qwen25-1.5b / one-shot | 5/3 | 2/0/2 | 0.000 | True | 6/1 |
| qwen25-coder-1.5b / feedback | qwen25-1.5b / feedback | 5/3 | 2/0/2 | 0.000 | True | 6/6 |
| qwen25-coder-1.5b / feedback | qwen25-3b / one-shot | 5/3 | 0/2/0 | 0.000 | True | 6/1 |
| qwen25-coder-1.5b / feedback | qwen25-3b / feedback | 2/6 | 0/2/0 | 0.000 | True | 6/6 |
| qwen25-1.5b / one-shot | qwen25-1.5b / feedback | 8/0 | 0/2/0 | 0.000 | True | 1/6 |
| qwen25-1.5b / one-shot | qwen25-3b / one-shot | 8/0 | 2/0/4 | 25.000 | True | 1/1 |
| qwen25-1.5b / one-shot | qwen25-3b / feedback | 4/4 | 0/0/3 | 75.000 | True | 1/6 |
| qwen25-1.5b / feedback | qwen25-3b / one-shot | 8/0 | 2/0/4 | 25.000 | True | 6/1 |
| qwen25-1.5b / feedback | qwen25-3b / feedback | 4/4 | 0/0/3 | 75.000 | True | 6/6 |
| qwen25-3b / one-shot | qwen25-3b / feedback | 4/4 | 1/3/0 | -25.000 | True | 1/6 |

## Split results

| Model | Method | Split | Correct cases | Complete verified cases |
|---|---|---|---|---:|
| qwen25-coder-1.5b | one-shot | evaluation | 3/8 (37.5%; 95% Wilson 13.7–69.4%) | 8 |
| qwen25-coder-1.5b | feedback | evaluation | 2/8 (25.0%; 95% Wilson 7.1–59.1%) | 5 |
| qwen25-1.5b | one-shot | evaluation | 2/8 (25.0%; 95% Wilson 7.1–59.1%) | 8 |
| qwen25-1.5b | feedback | evaluation | 2/8 (25.0%; 95% Wilson 7.1–59.1%) | 8 |
| qwen25-3b | one-shot | evaluation | 4/8 (50.0%; 95% Wilson 21.5–78.5%) | 8 |
| qwen25-3b | feedback | evaluation | 3/8 (37.5%; 95% Wilson 13.7–69.4%) | 4 |

## Per-case repetition results

| Model | Method | Case | Split | Expected | Observed/registered | Verified | Correct repetitions | Every repetition correct |
|---|---|---|---|---|---|---:|---:|---|
| qwen25-coder-1.5b | one-shot | file-new-path | evaluation | repair | 2/2 | 2 | 2 | True |
| qwen25-coder-1.5b | one-shot | sqlite-new-path | evaluation | repair | 2/2 | 2 | 0 | False |
| qwen25-coder-1.5b | one-shot | sqlite-already-secure | evaluation | unchanged | 2/2 | 2 | 0 | False |
| qwen25-coder-1.5b | one-shot | file-root-required | evaluation | abstain | 2/2 | 2 | 0 | False |
| qwen25-coder-1.5b | one-shot | file-mounted-hardening | evaluation | repair | 2/2 | 2 | 2 | True |
| qwen25-coder-1.5b | one-shot | file-already-secure | evaluation | unchanged | 2/2 | 2 | 0 | False |
| qwen25-coder-1.5b | one-shot | sqlite-mounted-hardening | evaluation | repair | 2/2 | 2 | 2 | True |
| qwen25-coder-1.5b | one-shot | sqlite-root-required | evaluation | abstain | 2/2 | 2 | 0 | False |
| qwen25-coder-1.5b | feedback | file-new-path | evaluation | repair | 2/2 | 1 | 0 | False |
| qwen25-coder-1.5b | feedback | sqlite-new-path | evaluation | repair | 2/2 | 1 | 0 | False |
| qwen25-coder-1.5b | feedback | sqlite-already-secure | evaluation | unchanged | 2/2 | 1 | 0 | False |
| qwen25-coder-1.5b | feedback | file-root-required | evaluation | abstain | 2/2 | 2 | 0 | False |
| qwen25-coder-1.5b | feedback | file-mounted-hardening | evaluation | repair | 2/2 | 2 | 2 | True |
| qwen25-coder-1.5b | feedback | file-already-secure | evaluation | unchanged | 2/2 | 2 | 0 | False |
| qwen25-coder-1.5b | feedback | sqlite-mounted-hardening | evaluation | repair | 2/2 | 2 | 2 | True |
| qwen25-coder-1.5b | feedback | sqlite-root-required | evaluation | abstain | 2/2 | 2 | 0 | False |
| qwen25-1.5b | one-shot | file-new-path | evaluation | repair | 2/2 | 2 | 0 | False |
| qwen25-1.5b | one-shot | sqlite-new-path | evaluation | repair | 2/2 | 2 | 0 | False |
| qwen25-1.5b | one-shot | sqlite-already-secure | evaluation | unchanged | 2/2 | 2 | 0 | False |
| qwen25-1.5b | one-shot | file-root-required | evaluation | abstain | 2/2 | 2 | 2 | True |
| qwen25-1.5b | one-shot | file-mounted-hardening | evaluation | repair | 2/2 | 2 | 0 | False |
| qwen25-1.5b | one-shot | file-already-secure | evaluation | unchanged | 2/2 | 2 | 1 | False |
| qwen25-1.5b | one-shot | sqlite-mounted-hardening | evaluation | repair | 2/2 | 2 | 0 | False |
| qwen25-1.5b | one-shot | sqlite-root-required | evaluation | abstain | 2/2 | 2 | 2 | True |
| qwen25-1.5b | feedback | file-new-path | evaluation | repair | 2/2 | 2 | 0 | False |
| qwen25-1.5b | feedback | sqlite-new-path | evaluation | repair | 2/2 | 2 | 0 | False |
| qwen25-1.5b | feedback | sqlite-already-secure | evaluation | unchanged | 2/2 | 2 | 0 | False |
| qwen25-1.5b | feedback | file-root-required | evaluation | abstain | 2/2 | 2 | 2 | True |
| qwen25-1.5b | feedback | file-mounted-hardening | evaluation | repair | 2/2 | 2 | 0 | False |
| qwen25-1.5b | feedback | file-already-secure | evaluation | unchanged | 2/2 | 2 | 0 | False |
| qwen25-1.5b | feedback | sqlite-mounted-hardening | evaluation | repair | 2/2 | 2 | 0 | False |
| qwen25-1.5b | feedback | sqlite-root-required | evaluation | abstain | 2/2 | 2 | 2 | True |
| qwen25-3b | one-shot | file-new-path | evaluation | repair | 2/2 | 2 | 2 | True |
| qwen25-3b | one-shot | sqlite-new-path | evaluation | repair | 2/2 | 2 | 2 | True |
| qwen25-3b | one-shot | sqlite-already-secure | evaluation | unchanged | 2/2 | 2 | 0 | False |
| qwen25-3b | one-shot | file-root-required | evaluation | abstain | 2/2 | 2 | 0 | False |
| qwen25-3b | one-shot | file-mounted-hardening | evaluation | repair | 2/2 | 2 | 2 | True |
| qwen25-3b | one-shot | file-already-secure | evaluation | unchanged | 2/2 | 2 | 0 | False |
| qwen25-3b | one-shot | sqlite-mounted-hardening | evaluation | repair | 2/2 | 2 | 2 | True |
| qwen25-3b | one-shot | sqlite-root-required | evaluation | abstain | 2/2 | 2 | 0 | False |
| qwen25-3b | feedback | file-new-path | evaluation | repair | 2/2 | 2 | 1 | False |
| qwen25-3b | feedback | sqlite-new-path | evaluation | repair | 2/2 | 2 | 2 | True |
| qwen25-3b | feedback | sqlite-already-secure | evaluation | unchanged | 2/2 | 1 | 0 | False |
| qwen25-3b | feedback | file-root-required | evaluation | abstain | 2/2 | 1 | 0 | False |
| qwen25-3b | feedback | file-mounted-hardening | evaluation | repair | 2/2 | 2 | 2 | True |
| qwen25-3b | feedback | file-already-secure | evaluation | unchanged | 2/2 | 0 | 0 | False |
| qwen25-3b | feedback | sqlite-mounted-hardening | evaluation | repair | 2/2 | 2 | 2 | True |
| qwen25-3b | feedback | sqlite-root-required | evaluation | abstain | 2/2 | 0 | 0 | False |

## Failure reasons

### qwen25-coder-1.5b / one-shot

- 10: Action budget exhausted

### qwen25-coder-1.5b / feedback

- 12: ProviderError: token_budget: The conservative total token budget is exhausted.

### qwen25-1.5b / one-shot

- 5: Manifest edits cannot satisfy the task requirements.
- 1: Manifest edits cannot satisfy the task; evidence required.
- 1: Manifest edits cannot satisfy the task; required changes are not allowed.
- 2: The current manifest does not meet the task requirements and cannot be repaired with approved changes.
- 1: The current manifest satisfies the task requirements without necessitating any changes.
- 1: The task can be satisfied with the current manifest, and no changes are necessary.

### qwen25-1.5b / feedback

- 1: Changes insufficient to satisfy task requirements.
- 2: Manifest edits cannot satisfy the task requirements.
- 1: Manifest edits cannot satisfy the task.
- 1: The current manifest does not meet the task requirements and no changes can be proposed that would satisfy them.
- 1: The current manifest does not meet the task requirements and no evidence suggests a repairable solution.
- 1: The current manifest does not meet the task requirements and requires significant changes to preserve non-root, read-only root filesystem, no privilege escalation, drop all capabilities, and use RuntimeDefault seccomp.
- 1: The current manifest satisfies the task requirements and preserves the application's behavior. No changes are necessary.
- 2: The current manifest satisfies the task requirements without needing any changes.
- 1: The current manifest satisfies the task requirements without requiring any changes.
- 1: manifest edits cannot satisfy task requirements.

### qwen25-3b / one-shot

- 8: Action budget exhausted

### qwen25-3b / feedback

- 4: ProviderError: token_budget: The conservative total token budget is exhausted.
- 5: Worker interrupted by signal 14

## Provenance and limits

- Results describe the registered synthetic Kubernetes case suite, not production incident prevalence.
- Case success requires every registered repetition to be task-correct. Missing/invalid trials remain in registered denominators as success not demonstrated.
- Wilson 95% intervals are descriptive case-level binomial intervals; this designed suite is not a random population sample.
- Repeated runs on a case are not independent cases. No trial-level confidence intervals, significance tests or causal ranking are reported.
- Model output uses the same guided action schema; repair correctness is not attributed solely to unconstrained model instruction following.
- One-shot and feedback methods may share a token ceiling but have different action budgets. Actual tokens and conservative reservations are separate.
- Worker artifacts/audits are assumed trusted execution records, not cryptographic remote attestation.

`summary.json` retains the complete plan, trial paths/pins, outcome rows and missingness. `trials.csv` provides one row for every registered cell. `index.html` shows the same source values without external scripts.

- `plan_id`: `kube-benchmark-v1-6d443fe84fc92e8f5de93cdb8fe01754dcee0cc529ebff32965abdc6af8b83fe`
- `suite_fingerprint`: `281c754461716ed4a7930fd275d2c49900c47ebdcc5934c568c71956e975d6ce`
- `evaluator_fingerprint`: `b92567ce7b520fc0068bf764ee07242c25bc93328d2d6de1e722fea50a498967`
- `source_fingerprint`: `f3b5040d88529d30196609a71a1611931dcf656c95064b6676cc0420a66256f7`
- `settings_fingerprint`: `d3d4555cc9b1ed3c1f99a632b18431945616590edd2aebbd61ac23ee88ff7426`

[Fixed-control comparison](controls.md) · [Control counts](controls-summary.json) · [Collection coverage](collection.json)
