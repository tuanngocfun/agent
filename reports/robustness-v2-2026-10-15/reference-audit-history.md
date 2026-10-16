# Reference validation and harness history

The accepted reference run is [38779680209](https://github.com/tuanngocfun/agent/actions/runs/38779680209). Its worker completed **48 control measurements across 12 base cases**, reported no worker errors, and recorded final cluster/kubeconfig/model/cache cleanup flags as true. Independent artifact replay validated all 48 control records. There was **no model inference in this reference stage**.

- Plan: `robustness-v2-0b2666e6ec62a843d35dcabe14599e9f55340e92404749322dff95b46f8d8333`.
- Source fingerprint: `f49a4550e31d63dcd4fd949a52aaeef617c63c08e0196747ebca62b1c931ca0b`.
- Measured worker elapsed time: **761.2250079 seconds**, approximately **12 minutes 41 seconds**. This includes worker setup and cleanup; it is not total GitHub workflow/queue time or billed runner-minutes.
- Model-method evaluation is a separate run, [38781747009](https://github.com/tuanngocfun/agent/actions/runs/38781747009), dispatched from commit `fc32d4cb222978d7f4897253504807a83fb4bb17`. This note supplies no model-method ranking.

## What the deterministic controls actually show

The suite contains ten repair tasks, one already-secure task and one infeasible task. Counts below mean **both security and application checks passed**, not model-origin task correctness or an abstention decision.

| Control | Security + application pass | Repair tasks | Already secure | Infeasible task |
|---|---:|---:|---:|---|
| No change | 1/12 | 0/10 | 1/1 | Fails, as expected |
| Naive hardening flags | 3/12 | 2/10 | 1/1 | Fails, as expected |
| Fixed hardening/writable-mount template | 5/12 | 4/10 | 1/1 | Fails, as expected |
| Protected reference edits | 11/12 | 10/10 | 1/1 | Fails, as expected |

Naive hardening recovers the single-container and init/sidecar admission cases. The fixed template additionally recovers cache, SQLite and temporary-directory writes, but loses the init/sidecar case by making protected consumer mounts writable. It also fails the separate read-only-configuration/writable-output contract, scoped RBAC tasks and shared-group identity contract. This illustrates a concrete limitation of blanket writable-mount repairs; it does not establish a general template ranking.

The oracle's 11/12 total is the intended result: the twelfth task has an immutable UID-zero application requirement that conflicts with the required non-root policy. The oracle is an operator-side feasibility reference, not a deployable competitor. A model must explicitly abstain with a reason on that task. Forty-eight controls are repeated measurements of twelve tasks, not forty-eight independent cases.

## Failed validation attempts remain visible

| Run | Recorded controls/models | Worker seconds | Preserved outcome |
|---|---:|---:|---|
| [38737214434](https://github.com/tuanngocfun/agent/actions/runs/38737214434) | 0 / 0 | 116.376204592 | Namespace cleanup wait timed out during initial setup; final global cleanup flags were true. |
| [38738048984](https://github.com/tuanngocfun/agent/actions/runs/38738048984) | 48 / 0 | 735.775469761 | Filesystem references failed because the current-ReplicaSet selector treated omitted `volumeMount.readOnly: false` as a mismatch. Diagnostics also exposed optimistic readiness during a two-replica rolling transition. |
| [38777257458](https://github.com/tuanngocfun/agent/actions/runs/38777257458) | 48 / 0 | 748.828998844 | Healthy init/sidecar and already-secure references failed because an immediate log request returned empty startup output. |
| [38779680209](https://github.com/tuanngocfun/agent/actions/runs/38779680209) | 48 / 0 | 761.225007900 | All registered broken-state/reference requirements met; 48/48 control records independently validated. |

The fixes preserve application/security requirements: recognize Kubernetes' omitted false mount default; require one updated, ready, available and total replica of the observed generation; and wait for protected startup markers within the existing readiness deadline. Marker polling retains the selected current-pod binding and every raw command. It does not retry a repair, replace the process, or restart a failing application. Fatal/admission failures retain diagnostic observations without the startup-marker polling loop.

Earlier runs retain their original source fingerprints, failed outcomes and raw observations. They are harness-development records, not scored LLM comparisons and not replacement repetitions for the accepted reference run. Model comparison must use the newly frozen protocol and independently audited model artifacts.
