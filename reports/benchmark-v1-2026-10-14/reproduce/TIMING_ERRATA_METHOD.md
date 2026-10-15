# Timing errata methodology

The frozen worker sums each raw Ollama `eval_duration / 1e9`. The frozen reporter sums integer nanoseconds first, divides once and compares with exact floating-point equality. With multiple calls, the two mathematically equivalent formulas can differ by a few floating-point rounding units. This diagnostic describes that measurement-validation defect without changing the evaluated source or any primary outcome.

From the project root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 \
  runs/2026-10-14_kube-benchmark-v1/timing_errata.py \
  --report-root runs/2026-10-14_kube-benchmark-v1/partial-report-0024 \
  --output runs/2026-10-14_kube-benchmark-v1/timing-errata-partial-0024
```

Use a new output directory for each snapshot. The helper validates the locked plan/current frozen source and exactly rebuilds the original primary summary. It then examines its existing `invalid_evidence` rows only.

A timing-only diagnosis requires all of the following:

1. The original failure is exactly the generation-seconds mismatch.
2. Bound bundle files and complete raw model responses pass SHA-256 checks; durations are nonnegative integer nanoseconds.
3. The recorded value exactly equals the frozen worker's per-call floating-point summation.
4. The difference from the integer-sum formula is nonzero and within a conservative bound based on the number of additions and floating-point ULPs.
5. Rechecking an **in-memory copy** with only the derived timing value canonicalized passes every remaining frozen reporter guard.

The helper writes `errata.json`, `errata.csv` and `errata.md`, preserving original/canonical timings, deltas, raw statuses, original primary outcomes and diagnostic results. Unsupported invalid rows are listed separately and receive no rounding-only claim. Missing records are not invented. Input hashes are rechecked before output. Existing outputs cannot be overwritten.

Original files, `invalid_evidence` labels, task-correctness flags, model comparison denominators and missingness remain unchanged. No inference, Kubernetes workload, rerun, acceptance waiver or corrected primary score is produced. Raw worker outcomes remain descriptive evidence; a diagnostic verification pass is not task success.

A future campaign should share one integer-nanosecond timing helper between its worker and reporter and cover multiple model calls in regression tests. The current frozen campaign should retain this erratum alongside its original report.
