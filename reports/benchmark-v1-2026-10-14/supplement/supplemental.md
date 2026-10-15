# Descriptive benchmark supplement

This snapshot contains 87/96 evidence-verified registered trials; 96 observed and 0 missing. The unchanged primary report contains 34 task-correct trials.

This is supplementary postprocessing. It introduces no new primary score, outcome waiver, model calls or workload execution.

## Raw flags and counters

Flags show true/available; counters show sum/available. Unavailable registered cells remain null in CSV and JSON.

| Model | Method | Verified/registered | Accepted | Appropriate abstention | Unnecessary change | Rejected actions | Unauthorized effects |
|---|---|---:|---:|---:|---:|---:|---:|
| qwen25-coder-1.5b | one-shot | 16/16 | 6/16 | 0/16 | 0/16 | 2/16 | 0/16 |
| qwen25-coder-1.5b | feedback | 13/16 | 4/13 | 0/13 | 0/13 | 1/13 | 0/13 |
| qwen25-1.5b | one-shot | 16/16 | 1/16 | 4/16 | 0/16 | 0/16 | 0/16 |
| qwen25-1.5b | feedback | 16/16 | 0/16 | 4/16 | 0/16 | 0/16 | 0/16 |
| qwen25-3b | one-shot | 16/16 | 8/16 | 0/16 | 0/16 | 0/16 | 0/16 |
| qwen25-3b | feedback | 10/16 | 7/10 | 0/10 | 0/10 | 1/10 | 0/10 |

## Verifier success and task completion

A passing latest verifier result can coexist with a failed task when the model never completes the required action protocol. These rows retain the original unsuccessful outcomes.

| Model | Method | Latest verifier true/false/unavailable | Pass without task completion | Pass without primary correctness |
|---|---|---:|---:|---:|
| qwen25-coder-1.5b | one-shot | 10/6/0 | 4 | 4 |
| qwen25-coder-1.5b | feedback | 7/6/3 | 3 | 3 |
| qwen25-1.5b | one-shot | 4/12/0 | 3 | 3 |
| qwen25-1.5b | feedback | 4/12/0 | 4 | 4 |
| qwen25-3b | one-shot | 12/4/0 | 4 | 4 |
| qwen25-3b | feedback | 8/2/6 | 1 | 1 |

## Workload family cuts

Families contain four public authored cases each. Case success still requires every registered repetition; incomplete cases remain unproven. Families and repetitions are not independent population samples.

| Family | Model | Method | Verified/registered trials | Correct trials | Fully verified cases | All repetitions correct/registered cases |
|---|---|---|---:|---:|---:|---:|
| file-cache | qwen25-1.5b | feedback | 8/8 | 2 | 4 | 1/4 |
| file-cache | qwen25-1.5b | one-shot | 8/8 | 3 | 4 | 1/4 |
| file-cache | qwen25-3b | feedback | 5/8 | 3 | 2 | 1/4 |
| file-cache | qwen25-3b | one-shot | 8/8 | 4 | 4 | 2/4 |
| file-cache | qwen25-coder-1.5b | feedback | 7/8 | 2 | 3 | 1/4 |
| file-cache | qwen25-coder-1.5b | one-shot | 8/8 | 4 | 4 | 2/4 |
| sqlite-cache | qwen25-1.5b | feedback | 8/8 | 2 | 4 | 1/4 |
| sqlite-cache | qwen25-1.5b | one-shot | 8/8 | 2 | 4 | 1/4 |
| sqlite-cache | qwen25-3b | feedback | 5/8 | 4 | 2 | 2/4 |
| sqlite-cache | qwen25-3b | one-shot | 8/8 | 4 | 4 | 2/4 |
| sqlite-cache | qwen25-coder-1.5b | feedback | 6/8 | 2 | 2 | 1/4 |
| sqlite-cache | qwen25-coder-1.5b | one-shot | 8/8 | 2 | 4 | 1/4 |

## Hashed model-pin hardware

| CPU model | Verified pin files | Verified trial rows using those pins |
|---|---:|---:|
| AMD EPYC 7763 64-Core Processor | 19 | 35 |
| AMD EPYC 9V45 96-Core Processor | 8 | 15 |
| AMD EPYC 9V74 80-Core Processor | 10 | 19 |
| INTEL(R) XEON(R) PLATINUM 8573C | 6 | 12 |
| Intel(R) Xeon(R) 6973P-C | 1 | 2 |
| Intel(R) Xeon(R) Platinum 8370C CPU @ 2.80GHz | 3 | 4 |

## Observed worker costs

48/48 registered shard summaries are available. Their observed worker intervals sum to 33003.103 seconds (550.052 aggregate worker minutes). Concurrent worker intervals are added; this is not elapsed campaign time or billed GitHub minutes.

| Timing | Available/unavailable shards | Observed sum seconds |
|---|---:|---:|
| worker_wall_seconds | 48/0 | 33003.103 |
| setup_command_seconds | 48/0 | 7238.201 |
| teardown_command_seconds | 48/0 | 103.398 |
| verified_task_wall_seconds | 40/8 | 15432.21 |
| non_task_worker_seconds | 40/8 | 10461.888 |

## Limits

- These are postprocessing descriptions, not a new primary endpoint or post-hoc acceptance policy.
- Missing and unverified trial flags/counters are null; no unseen zero-effect or successful outcome is imputed.
- A latest-verifier pass does not waive completion, authority, model-origin, identity or registered-outcome requirements.
- Only two authored fixture families are present. Repeated tasks, cases and families are not independent population samples.
- Hardware comes from exact SHA256-bound model-pin metadata; worker records are trusted evidence, not remote attestation.
- Worker wall time excludes checkout, tool installation and artifact upload; summed worker minutes are not elapsed or billed runner minutes.
- Setup-command timing covers recorded wrapper subprocesses, not all setup. Non-task worker residual also includes fixed controls, warmup, audits and cleanup.
- Shard summaries/command timing are worker-provided metadata checked against collected files and hashed here, not independently timed or signed.
- Unfinished registered repetitions remain unproven in all-repetition case counts, including partial campaign snapshots.

Exact inputs, hashes and nullable measurements are retained in `supplemental.json`, `trials.csv`, `families.csv` and `shards.csv`.
