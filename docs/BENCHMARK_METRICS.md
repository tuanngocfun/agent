# Registered benchmark metrics

The report compares only cells registered in one frozen plan. It reads real worker records and their bound artifacts; it does not generate example outcomes, start models, create clusters or silently add previously successful development runs. The first campaign uses public authored synthetic cases. Development cases and known-good oracle controls are excluded from model comparison denominators.

Run from the project directory:

```sh
python3 scripts/benchmark_report.py \
  --plan benchmark/plan-v1.json \
  --records runs/CAMPAIGN/records \
  --evidence-root runs/CAMPAIGN \
  --output runs/CAMPAIGN/report-v1
```

The destination must be a new directory. The tool writes `report.md`, `summary.json`, `trials.csv` and standalone `index.html`. The HTML uses only the generated values and embedded CSS; it needs no external JavaScript service. JSON retains every registered trial, case/split result, paired comparison, model pin, artifact path and comparison identifier.

## Frozen plan and cells

Plan schema version 1 requires:

- `plan_id`, `suite_fingerprint`, `evaluator_fingerprint`, `source_fingerprint`, `settings_fingerprint`.
- `models`: objects with `model_id` and a nonempty `pin` object containing the registered model tag, manifest digest, weight digest and weight bytes.
- `methods`: objects with `method_id`, `token_ceiling`, `max_actions`, `guided_schema_fingerprint`; further budget metadata can be retained in the plan.
- `cases`: objects with `case_id`, `split` and `expected_outcome` (`repair`, `unchanged` or `abstain`). Case definition hashes and workload family metadata should also be retained.
- `repetitions`: the number of explicitly registered executions per model, method and case.

The expected population is the complete Cartesian product of model × method × case × repetition. Repetition numbers start at 0, matching the worker's `--trial-index`. Record absence creates a `missing` outcome row. Duplicate cells, unregistered cells, changed expected outcomes, mismatched plan/source/suite/evaluator/settings fingerprints and non-finite/negative metrics reject the entire comparison. This prevents mixing successful runs from different prompts, policies or task versions.

## Trial record schema

Every JSON record in the selected records directory is one cell with `schema_version: 1`, the five comparison identifiers, `model_id`, `method_id`, `case_id`, `repetition`, `expected_outcome` and `outcome`.

`outcome` is one of `repaired`, `unchanged`, `abstained`, `behavior_failure`, `security_failure`, `protocol_failure`, `policy_failure`, `provider_failure`, `infrastructure_failure`, `budget_exhausted` or `invalid_evidence`. The worker records `accepted`, `appropriate_abstention`, `unnecessary_change`, `rejected_actions`, `unauthorized_effects`, `failure_reason` and `provenance` separately. Infrastructure failures and transport failures remain visible even if no completed review bundle exists; they never count as a successful task.

`evidence` contains:

- `validated`: whether a completed worker audit is available.
- `model_origin_verified`: whether actual recorded inference was observed; a transport/pre-inference failure can legitimately be false.
- `bundle_path`, relative to the selected evidence root, and `bundle_sha256`, the SHA-256 of that bundle's `binding.json` file bytes.
- `audit_path`, relative to the evidence root, and `audit_sha256`, the SHA-256 of its exact bytes.
- `model_pin_path`/`model_pin_sha256` and `image_pins_path`/`image_pins_sha256` preserve the actual setup documents. They are required when the registered model has a weight blob pin; their bytes and approved weight/CPU verification are rechecked. The aggregator must prefix these relative paths when combining worker artifacts, just as it prefixes bundle and audit paths.

The audit requires `status: "passed"`, `bundle_review_hash` matching the bound bundle and `model_origin_verified` matching the observed raw inference (`eval_count > 0`). `namespace_cleanup_verified` must match every trace verification's namespace cleanup, and `worker_cleanup_verified`/`worker_cleanup` must match the recorded model, cluster, kubeconfig and cache removals. These are trusted worker records, not a cryptographic remote attestation. The reporter independently checks file hashes, the exact bundle inventory and current source binding, raw response hashes, model identity, token counts and raw action equality to engine decisions. A worker merely saying `validated: true` cannot make a changed or absent bundle pass.

`metrics` contains nullable measurements: `inspections`, `repairs`, `tests`, `model_calls`, `prompt_tokens`, `output_tokens`, `total_tokens`, `reserved_tokens`, `protocol_rejections`, `policy_rejections`, `wall_seconds`, `inference_seconds`, `generation_seconds`. Count fields are nonnegative integers. Timings are nonnegative finite seconds. Null means unavailable and is not converted into zero. Actual total tokens must equal prompt plus output when all are available. Exact counters and timings are cross-checked with the bound execution report/trace.

`checks` contains nullable booleans: `behavior`, `static`, `security`, `cleanup`. Behavior/static/runtime security map to the protected verifier's `behavior_pass`, `static_pass`, `negative_pass`; cleanup additionally covers the disposable worker resources. All passed/failed/unavailable counts retain their own denominator. Passing static checks alone does not establish task correctness.

## Success and denominators

A repair trial is task-correct when a revalidated actual model proposal yields an accepted changed candidate and protected Kubernetes behavior/security tests pass. An unchanged trial additionally requires the preserved manifest and no unnecessary change. An abstain trial is correct only for a registered infeasible case and an appropriate recorded model abstention. Infeasibility is established by the case contract and bounded change authority, not by a model's inability to find a solution. No inference means no successful model-origin task result.

Trial counts are descriptive and show raw successful/registered/observed/verified numerators and denominators. A **case** passes only when **every registered repetition** is task-correct. Missing and invalid repetitions remain registered and mean success has not been demonstrated. Repair-case success uses only cases whose expected outcome is repair. Task-correct case success includes repair, unchanged and abstain cases. Per-case repeat counts and split cuts remain visible so this conservative all-repeat definition cannot hide mixed outcomes.

Wilson 95% intervals use distinct registered cases, never repeated trials as independent cases. For count `s` out of `n`, `p = s/n`, `z = 1.959963984540054`, center `(p + z²/(2n))/(1 + z²/n)` and half-width `z sqrt(p(1-p)/n + z²/(4n²))/(1 + z²/n)`. Zero cases produces an unavailable rate and interval. Because this is a deliberately authored suite, these are descriptive binomial intervals; the suite is not a random population sample. No significance, population generalization or causal superiority claims follow from them.

Pairwise comparisons match case IDs with complete revalidated repetitions on both sides. They report both-correct, left-only, right-only, both-incorrect counts; excluded incomplete cases; and `(right-only − left-only)/matched × 100` percentage-point delta. They also show whether the token ceiling and guided schema match and the two action budgets. Different action budgets remain explicit even when token ceilings match. No ranking is claimed across incompatible budgets/settings.

## Costs and missingness

Prompt/output/total tokens come from recorded model-server counters. Aggregated actual totals require complete call counts and at least one measured usage call; partial observations stay in raw provider evidence without turning incomplete usage into a complete zero. Conservative reserved tokens reflect admission control based on prompt bytes and maximum output; they are never described as actual billed/model tokens. Inference seconds cover model requests; generation seconds cover the sum of raw response output evaluation durations; wall seconds cover the task including protected runtime tests. Generation throughput is actual output tokens divided by generation seconds only when both are available and time is positive. Download/setup/smoke inference and disposable cluster lifecycle costs belong in worker provenance and are not silently charged to one task or treated as model decision latency.

Each aggregate reports availability, missing count, sum, mean, median, minimum and maximum. Invalid evidence measurements are excluded from trusted statistics while their trial outcomes remain visible. Reports preserve model manifest and weight pins, source/evaluator/suite/settings identifiers, artifact/audit paths and failure reasons for reproduction. Optional extra measurements remain inspectable in raw record provenance.
