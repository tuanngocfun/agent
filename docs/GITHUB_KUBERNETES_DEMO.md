# Real Kubernetes demo on GitHub Actions

The private repository [`tuanngocfun/agent`](https://github.com/tuanngocfun/agent) now contains the source on `kube-remediation-demo`. [Run 38408621533](https://github.com/tuanngocfun/agent/actions/runs/38408621533) succeeded for source commit `4461388`, and its downloaded artifact confirms execution on Kubernetes **v1.34.0**. Read the [Vietnamese result record](REAL_KUBERNETES_RESULT_VI.md) for the evidence and limits.

The workflow is [kubernetes-demo.yml](../.github/workflows/kubernetes-demo.yml); setup is [kind_demo.py](../scripts/kind_demo.py). The source is placed at the repository root on the demo branch. The initial default-branch README is only a bootstrap; the full demo source stays on `kube-remediation-demo` unless a separate merge is requested.

## Open the job and its evidence

1. Select `kube-remediation-demo` in the repository branch picker to browse the code.
2. Open the [confirmed run for commit `4461388`](https://github.com/tuanngocfun/agent/actions/runs/38408621533). For later runs, select **Kubernetes remediation demo** in [Actions](https://github.com/tuanngocfun/agent/actions) and check the source commit.
3. Read **Prepare trusted images and run real Kubernetes** to see cluster execution. A green checkout or unit-test step alone is insufficient.
4. Download `kubernetes-remediation-evidence` from the run's artifacts. Read `summary.json`, then the repair bundle's `REVIEW.md`, `report.json`, `trace.json` and `patch.diff`.

The workflow supports `workflow_dispatch` and the exact `kube-remediation-demo` branch; its YAML defines which pushes trigger a job. No merge is required. When `workflow_dispatch` is available in the GitHub UI, choose the demo branch. The initial job was started by publishing the demo source.

## Confirmed outcomes

| Case | Observed outcome |
|---|---|
| `noop` | Application/cache works; target security controls fail. |
| `naive` | All static controls pass; startup/cache fails with a read-only filesystem error. |
| `known-good` | All declared static, behavior and runtime checks pass. |
| `agent` (`scripted`) | Accepted after 2 candidates and 3 tests; 5 actions, about 39 seconds. |

The accepted candidate runs as UID 10001, denies root-filesystem writes with `EROFS`, reports `NoNewPrivs=1`, zero capabilities and seccomp filter mode 2. HTTP health, independently computed SHA-256 result, cache read-back/reuse, image identity and namespace cleanup also pass. Seccomp filter mode does not identify the full contents of the profile.

The artifact records source fingerprint `df02a9f5baee95c5c0d6ecdb9039a4170428eb9b20c7aad7624f54db06f1f098`. Later documentation commits do not change which source this successful run tested.

## What the worker checks

The Ubuntu worker creates a dedicated `kind` cluster, builds the supplied fixture, loads its image and runs no-op, naive hardening, known-good and adaptive scripted cases. The naive repair should satisfy static configuration checks while failing required cache behavior. The accepted repair must preserve application behavior and satisfy the declared runtime checks. A summary verifies these expected outcomes before the launcher reports success.

The outputs include runtime checks, patch/trace/review bundles and fixture/source/image identities. Actions are pinned to commit IDs; tool downloads are verified against official release SHA256 checksums. Kubernetes/kind versions are fixed. The Python base image digest is resolved during setup and recorded in `image-pin.json`; use that digest when reproducing the same base.

The job has read-only repository permissions, a 20-minute cap and seven-day artifact retention. Kubeconfig and raw cluster logs are excluded from the artifact upload. Existing local `runs/` are Git-ignored and are not part of the source publication; inspect the artifact from the actual job instead.

The provider in this workflow is **`scripted`**. The confirmed job proves Kubernetes runtime execution of this supplied fixture and its declared checks. It does not establish autonomous LLM reasoning, general repair accuracy or a reliability-study result. [The Vietnamese runbook](KUBERNETES_DEMO_VI.md) explains how to run the same launcher locally or supply an Ollama/session provider.
