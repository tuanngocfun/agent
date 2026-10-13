# Real Kubernetes demo on GitHub Actions

The user selected the private repository [`tuanngocfun/agent`](https://github.com/tuanngocfun/agent) and authorized publishing the prepared source to `kube-remediation-demo` and running this demo. Runtime evidence is still pending; authorization and passing protocol tests do not establish a successful cluster run.

The workflow is [kubernetes-demo.yml](../.github/workflows/kubernetes-demo.yml); setup is [kind_demo.py](../scripts/kind_demo.py). The source is placed at the repository root on the demo branch. The initial default-branch README is only a bootstrap; the full demo source stays on `kube-remediation-demo` unless a separate merge is requested.

## Open the job and its evidence

1. Select `kube-remediation-demo` in the repository branch picker to browse the code.
2. Open [Actions](https://github.com/tuanngocfun/agent/actions) and select **Kubernetes remediation demo** for the exact source commit.
3. Read **Prepare trusted images and run real Kubernetes** to see cluster execution. A green checkout or unit-test step alone is insufficient.
4. Download `kubernetes-remediation-evidence` from the run's artifacts. Read `summary.json`, then the repair bundle's `REVIEW.md`, `report.json`, `trace.json` and `patch.diff`.

The workflow triggers on `workflow_dispatch` or a push to the exact `kube-remediation-demo` branch; no merge is required. When `workflow_dispatch` is available in the GitHub UI, choose the demo branch. A push to that branch is sufficient to start the initial job.

## What the worker checks

The Ubuntu worker creates a dedicated `kind` cluster, builds the supplied fixture, loads its image and runs no-op, naive hardening, known-good and adaptive scripted cases. The naive repair should satisfy static configuration checks while failing required cache behavior. The accepted repair must preserve application behavior and satisfy the declared runtime checks. A summary verifies these expected outcomes before the launcher reports success.

The outputs include runtime checks, patch/trace/review bundles and fixture/source/image identities. Actions are pinned to commit IDs; tool downloads are verified against official release SHA256 checksums. Kubernetes/kind versions are fixed. The Python base image digest is resolved during setup and recorded in `image-pin.json`; use that digest when reproducing the same base.

The job has read-only repository permissions, a 20-minute cap and seven-day artifact retention. Kubeconfig and raw cluster logs are excluded from the artifact upload. Existing local `runs/` are Git-ignored and are not part of the source publication; inspect the artifact from the actual job instead.

The provider in this workflow is **`scripted`**. A successful job proves Kubernetes runtime execution of the supplied fixture and its declared checks. It does not establish autonomous LLM reasoning, general repair accuracy or a reliability-study result. [The Vietnamese runbook](KUBERNETES_DEMO_VI.md) explains how to run the same launcher locally or supply an Ollama/session provider.
