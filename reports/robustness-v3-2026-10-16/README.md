# Real Kubernetes decoder diagnostic — 16 October 2026

**Negative result: zero correct repairs out of six registered cells.** All six records have independently consistent evidence after a separately versioned offline audit: three task failures and three provider timeouts, with zero missing or invalid records. The two underlying cases were reused from v2; this diagnostic adds **zero new independent task cases**.

[Actual Actions run 38868589212](https://github.com/tuanngocfun/agent/actions/runs/38868589212) used source commit `d4bf2d5af3144f06a9d7b770283773c29c8c0f75`. The execution step completed all four protected controls and six repair-call attempts and recorded cleanup of its namespaces, cluster, model server, model cache and kubeconfig. **The workflow is red:** its original reporting step refused the v3 namespace prefix. That refusal remains preserved in [the worker log](worker.log) and [local original-reporter reproduction](original-report-refusal.json).

## Dataset and measured execution

Two review-selected existing cases × three decoder schemas × one execution = **six cells**, one pinned Qwen2.5 3B model, clean evidence only. There are no new models, hidden tasks or independent repetitions here. The frozen [plan](plan.json) records model/image digests, case contracts and all capacities. [Source CI](https://github.com/tuanngocfun/agent/actions/runs/38868589008) passed **525 tests in 14.443 seconds** on the execution commit; harness tests are not agent benchmark cases.

| Case | Decoder | Cell seconds | Call seconds | Audited outcome |
|---|---|---:|---:|---|
| restricted-init-sidecar | decoder-legacy | 125.943 | 120.000 | provider_failure |
| restricted-init-sidecar | decoder-unbounded | 125.748 | 120.000 | provider_failure |
| restricted-init-sidecar | decoder-any-json | 118.238 | 112.728 | task_failure |
| rbac-list-configmaps | decoder-any-json | 124.836 | 120.000 | provider_failure |
| rbac-list-configmaps | decoder-unbounded | 107.295 | 103.925 | task_failure |
| rbac-list-configmaps | decoder-legacy | 87.015 | 83.267 | task_failure |

Cell seconds are the worker measurement from trial start through final verification, before its namespace cleanup and evidence persistence. Call seconds measure the HTTP request, including server prompt processing; they are not token generation time. Setup and teardown are excluded from cell rows.

| Scope | Actual duration |
|---|---:|
| Worker measurement, including setup, controls and global cleanup | 971.261 s (16 min 11.261 s) |
| Diagnostic Actions job, including report/upload | 979 s (16 min 19 s) |
| Protocol job | 8 s |
| Execution-commit Source CI job | 20 s |
| Sum of those three job durations | 1,007 s (16 min 47 s) |
| Conservative per-job rounded minutes | 19 |

These durations are actual measurements. The pre-registered dispatch cap was 43 runner-minutes. The cumulative [33-run budget ledger](runner-budget.json), captured after this diagnostic and before report publication, records **976 per-job rounded minutes used of the authorized 1,000**, with no unfinished jobs and 24 remaining. The final report publication reserves up to 23 more minutes: twenty for two Source CI pushes (including removal of an incidental Python cache file) and three for a separate offline evidence-audit job. That job restores the preserved ZIP and replays the corrected auditor without starting model inference or Kubernetes; no broader model campaign was started.

## What the model actually produced

- **Corrected schema, init/sidecar:** two Boolean `true` edits. Both repeated values already present; the candidate equaled the initial resources. Missing `allowPrivilegeEscalation` fields remained unresolved, and Kubernetes admission still denied Pods.
- **Unbounded schema, RBAC:** five object values assigned to scalar security fields. Kubernetes rejected that candidate; the missing `list` permission remained unresolved.
- **Legacy schema, RBAC:** an incorrect abstention stating the task was already satisfied, despite supplied static failures, HTTP 403 logs and authorization checks returning `no`.
- The other three requests reached the **120-second hard wall** without a returned response.

Thus the explicit JSON type union enabled scalar emission in one observed reply; it did **not** produce a correct repair. This is a correction of decoder representability, not demonstrated method superiority.

## Prompt processing dominated the returned calls

| Case / decoder | Prompt tokens | Output tokens | Prompt seconds | Generation seconds | Load seconds | Server total seconds |
|---|---:|---:|---:|---:|---:|---:|
| restricted-init-sidecar / decoder-any-json | 1816 | 120 | 95.516 | 17.163 | 0.014 | 112.700 |
| rbac-list-configmaps / decoder-unbounded | 1403 | 186 | 78.105 | 25.782 | 0.015 | 103.909 |
| rbac-list-configmaps / decoder-legacy | 1396 | 39 | 77.915 | 5.315 | 0.015 | 83.252 |

The three returned replies ended normally (`done_reason: stop`); none reached the 256-token limit. Their known totals are **4,615 prompt tokens and 345 output tokens**. Token usage and internal timing for the three no-response requests are **unavailable**, so these are partial totals, not six-call cost totals. The empty-message model-load request is retained separately in setup metadata.

Prompt evaluation consumed approximately 75–94% of server time in the returned calls. These six observations do not isolate a grammar-bound speedup: output actions/lengths differ, namespace and runtime context differ, there is one execution per cell, and reversing two orders does not remove caching/hardware confounding. Faster inference and generic evidence transport deserve investigation before a larger method comparison.

## Protected controls

All **four controls are independently evidence-verified**. Both no-op states failed the registered security and behavior checks as expected; both oracle repairs passed security **and** application behavior. All four namespace cleanup flags are true. Oracle edits are author-provided feasibility controls, not model results. Full rows are in [controls.csv](controls.csv).

## Original refusal and explicit auditor correction

The frozen v3 runtime creates `robust-v3-` namespaces. Three copied namespace guards in the original frozen reporter still expected `robust-v2-`, so the original report command exited 2 before writing a report. This was an integration defect that the original mocks failed to catch.

The separate [v3.1 offline auditor](../../scripts/audit_robustness_v3_evidence.py) corrects those three expected prefixes and labels its amendment with hashes of both reporter versions. The frozen execution source, plan, raw responses, allowed changes, protected checks and model-derived candidates remain unchanged. All schema/request hashes, raw decision replay, model/image identity, application/security observations, command bindings and cleanup checks still run. The [summary](summary.json) includes `audit_amendment`; the [generated audited report](report.md) carries the same disclosure. No Kubernetes cluster or model was started by the auditor.

The official [evidence ZIP](evidence.zip) is 164,006 bytes. SHA256 `f4cdcd40b8a5b183c7356527c4b1eabe634097c7c05981e81c79c1fb6913d1b4` matches GitHub's artifact digest. [Metadata](evidence-artifact.json) records artifact ID 12032657138. These are trusted worker execution records with content hashes, not signed hardware attestation.

## Reproduce offline

From a checkout containing the frozen v3 execution source and the separate auditor:

```bash
python3 reports/robustness-v3-2026-10-16/reproduce/recompute.py --output runs/my-diagnostic-reproduction
python3 reports/robustness-v3-2026-10-16/reproduce/diagnostic_analysis.py \
  --summary runs/my-diagnostic-reproduction/recomputed/summary.json \
  --artifact runs/my-diagnostic-reproduction/restored/robustness-v3-diagnostic \
  --output runs/my-diagnostic-supplement
```

The first command checks the ZIP digest, safely restores bounded entries, validates frozen source, reruns the independent auditor and compares the summary (ignoring only machine-local shard paths) plus all three primary CSVs. It has been executed successfully. The supplement rechecks raw calls and emits per-call/field/control tables without changing primary scores; its actual run found **zero consistency disagreements**. Fresh output directories are required.

Read [supplemental tables](supplement/README.md), [original failed v2 campaign](../robustness-v2-2026-10-15/README.md), [round-three review](../../docs/REVIEW_ROUND_3.md) and [follow-up priorities](../../docs/ROBUSTNESS_FOLLOWUP.md). The 12-case full plan is prepared but unrun; its new workflow and final source registration require review before execution. The present diagnostic supports **no ranking of agent methods or models**.
