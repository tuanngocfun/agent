# Kubernetes remediation benchmark v1

This version turns the single-workload demo into a **registered public synthetic benchmark**. It has eight cases across two independently implemented services, three pinned models, two methods and two repeated executions: **96 model tasks**. It is not a production-workload benchmark or a hidden held-out evaluation.

The plan is frozen in [plan-v1.json](../benchmark/plan-v1.json) before evaluation inference. The [freeze validator](../scripts/freeze_benchmark_plan.py) recomputes case, fixture, probe, source, evaluator, prompt, schema, model-registry and settings bindings. Changing any evaluated code requires a new plan; results from different plans are not combined as one comparison.

## Models and methods

The registry contains Qwen2.5-Coder 1.5B Instruct, Qwen2.5 1.5B Instruct and Qwen2.5 3B Instruct, all Q4_K_M. [models.json](../benchmark/models.json) records manifests obtained from the official Ollama registry, exact weight hashes and sizes. The worker hashes the downloaded weight bytes and checks model identity before and after tasks. All three models are related Qwen models; conclusions do not extend to other families or frontier hosted models.

Both methods receive the same complete approved image/application metadata, labeled repository content, current manifest and initial verifier feedback. They use the same guided decoding schema, temperature 0, 8192 context, two CPU threads, maximum 512 output tokens per call and conservative total ceiling 32768. The ceiling reserves prompt bytes plus maximum output; actual server-reported tokens are measured separately.

| Method | Maximum model actions | Maximum candidate repairs | Completion |
|---|---:|---:|---|
| One-shot | 1 | 1 | Trusted engine after a changed proposal passes; model `finish` for unchanged; model `abstain` for infeasible |
| Feedback | 6 | 3 | Same policy, with subsequent decisions available after failures |

The primary outcome measures completing the registered task through this controller. A no-op proposal that merely preserves an already passing manifest does not count as completed unless the provider finishes. Token ceilings match; action budgets and realized compute differ and remain visible. No equal-compute superiority claim follows from this comparison alone.

## Cases and ground truth

There are four repair cases, two already-secure cases and two infeasible cases, evenly split across file-backed and SQLite-backed cache services. Paths, initial storage state and required process identities vary. The original tuned `cache-path` demo is excluded from the primary denominator.

The file service persists SHA-256 results in files. The separate SQLite service persists committed rows and hit counters in a database. Its protected probe opens the database independently, checks integrity and the expected result, and checks a committed cache-hit increment. Both services must retain startup, health, computation and cache reuse while enforcing non-root, read-only root, no escalation, dropped capabilities and seccomp controls. Image, application, environment, probes and evaluation settings cannot be changed by a model.

Root-required fixtures explicitly refuse startup without UID 0. Since image/application changes are outside repair authority, these cases are infeasible under the required non-root control. Correct abstention is scored separately from successful repair. A model failing to solve a feasible case does not establish infeasibility.

The verifier retains 14 checks covering static controls, pinned runtime image, application behavior, process controls and namespace cleanup. Task-specific configured UID/GID are audited separately; runtime UID is observed, while process GID is not independently probed. Namespace ownership, current candidate hashes, raw model responses/actions and final completion attribution are bound in evidence. These are trusted-worker execution records, not cryptographic remote attestation.

## Controls and statistics

Every case also runs no-op, flags-only hardening, a fixed storage template and the author-provided known-good control. The template and known-good repair manifests coincide on these supported storage cases; the oracle additionally knows which root-required cases warrant abstention. They are controls rather than independent model baselines. Their repeated execution across shards is not counted as extra independent cases.

[Metric definitions](BENCHMARK_METRICS.md) cover task correctness, repair-only outcomes, unnecessary changes, protocol/policy failures, inference/infrastructure failures, coverage, cleanup, calls, tests, inspected evidence, token counts, conservative reservations, timings and generation throughput. Reports include every registered cell, missing data and reasons. Case success requires both registered repetitions to be correct. Wilson 95% intervals use distinct cases, not repetitions; they are descriptive for this deliberately authored small suite. Pairwise comparisons retain matched-case counts and budget differences.

Two temperature-zero repetitions test repeat execution stability. They are not two independent workload samples. No post-evaluation model/prompt/case tuning or failed-run replacement is permitted inside this registered plan.

## Execution and budget

The [benchmark workflow](../.github/workflows/benchmark.yml) runs 48 isolated jobs, two cases each, with a 20-minute job timeout and four jobs at a time. Matrix timeouts sum to 960 runner-minutes. Protocol validation, report collection and source CI bring the maximum to **980 runner-minutes**, below the user-approved 1000. There are no automatic retries. Worker deadlines reserve time for cluster/model cleanup and evidence upload. A deadline or infrastructure failure is preserved, not relabeled as model failure or omitted.

`Source CI` runs on every demo-branch push. The expensive benchmark runs when its frozen plan or workflow changes. A normal documentation/results commit can therefore receive CI without starting another campaign. The historical single-workload demo is now manual; previous successful runs remain available.

On an appropriately provisioned Docker lab worker, one shard can be run with:

```bash
python3 scripts/install_worker_tools.py
python3 scripts/freeze_benchmark_plan.py --check benchmark/plan-v1.json
python3 scripts/benchmark_worker.py --plan benchmark/plan-v1.json \
  --model-id qwen25-1.5b --method one-shot --trial-index 0 --case-shard 0 \
  --output runs/my-benchmark-shard
```

Reports are produced from exact shard artifacts, with their evidence paths rebased without changing bundle bytes:

```bash
python3 scripts/collect_benchmark.py --plan benchmark/plan-v1.json \
  --shards runs/downloaded-benchmark-artifacts --output runs/my-benchmark-report
```

The collection writes `report.md`, `summary.json`, `trials.csv`, standalone `index.html`, fixed-control records, the complete expected/received shard inventory and source evidence. A missing artifact directory produces a report with all tasks missing, not invented results. Weights, usable kubeconfigs and private credentials are excluded.
