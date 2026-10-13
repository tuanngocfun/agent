# Validation — 13 October 2026

This records software validation of the starter, not a reliability study.

| Executed check | Outcome |
|---|---|
| `PYTHONPATH=src python3 -m unittest discover -s tests -v` | 53 tests passed |
| CLI integration via `scripts/validate_cli.py` | 12 checks passed |
| Demo: four scenarios × five controls/providers | 20 simulated runs recorded |
| Cache-path scripted repair | Accepted by simulated fixture checks after two candidates |
| Volume-permissions scripted repair | Accepted by simulated fixture checks after two candidates |
| Authority-limit scripted outcome | Appropriate abstention; no repair exported |
| Already-secure scripted outcome | Accepted unchanged; zero candidate repairs |
| Naive cache-path hardening | Static checks pass; required behavior fails |
| Review/export | Local export succeeds; replay and changed artifact rejected |
| Missing Ollama model selection | CLI rejects before a request |

The unit suite also exercises hostPath/image/suppression edits, workload deletion, forged success, malformed actions, protected JSON types, stale base/source, model transport limits, Docker start/cleanup failures and trusted probe parsing. Ollama and Docker protocol tests use mocks. One fixture handler test calls application logic locally without opening a socket; command deadline/output tests run small local Python subprocesses.

No real LLM inference, Docker container, Kubernetes cluster, Checkov scanner, GPU job or held-out evaluation was executed. Runtime and inference adapters remain unvalidated on actual services. Simulation proves only the behavior of this model of the fixtures.

The record directory was created using the existing `new_experiment.sh` convention with its output root explicitly inside the requested project:

```bash
EXPERIMENT_ROOT=/home/ngocnt/agents/kube-security-remediation/runs \
  bash /home/ngocnt/scripts/new_experiment.sh kube-repair-starter-validation
```

Read the `runs/2026-10-13_kube-repair-starter-validation/results/cli/demo/SUMMARY.md` (local workspace), `runs/2026-10-13_kube-repair-starter-validation/results/cli/cli-checks.json` (local workspace), and `runs/2026-10-13_kube-repair-starter-validation/task-state.json` (local workspace).

`tamper-control` is deliberately invalidated by the CLI test; its failed review is expected. Other bundles retain their original review bindings. Files under `runs/` are ignored by Git.

The required `/workspace/scripts/check_workspace.sh` path was absent. Its host equivalent was attempted and exited 1: `/workspace` and `/data_ngoc` are unavailable, and `/data` is mounted read/write. Shared datasets were not read or changed. Actual workspace research runs still require resolving that environment discrepancy.

The shared ChatGPT URL returned a cache miss. The supplied quotation and the locally saved long-term strategy were sufficient to implement this first lab.

## Kubernetes preparation update

The current suite passed **81 tests**. Eight Kubernetes protocol tests and four kind-launcher lifecycle tests use mocks; twelve session-bridge tests use bounded local files. The updated CLI passed **12 integration checks**, which continue to use simulation. No real cluster, runtime or model service was started.

The real launcher was invoked on this host and stopped with exit 2 before creating artifacts or resources: Docker, kind and kubectl are missing. User namespace mappings are denied by the host, sudo requires a password, and no kubeconfig/CRI socket is available. The user confirmed Kubernetes is mandatory and no other lab environment is currently available.

Workflow YAML, exact-branch trigger, read-only permissions, full commit action pins and official tool checksum URLs were verified. A reviewable source package is prepared; GitHub publication and worker execution require a chosen/authorized repository. No GitHub writes or job starts occurred.

Read [Kubernetes runbook](KUBERNETES_DEMO_VI.md). Preparation records are in `runs/2026-10-13_kube-remediation-kubernetes-preparation/`.

## Authorized remote run

The user selected private `tuanngocfun/agent` and authorized publishing/running `kube-remediation-demo`. A bootstrap README initializes the previously empty default branch; code/workflow are isolated on the demo branch. Actual runtime results will be recorded after the GitHub worker finishes.

## Actual Kubernetes execution

Run38408621533 completed successfully at commit44613880014ca56882f0a21e5de461db97941b50. The downloaded ZIP matches GitHub artifact digest7361704237d39eeef6cb0db119444b6a392f69664a3caf43e2751a68f687faec. All4 review bundles passed integrity checks and the source/fixture fingerprints match.

Kubernetesv1.34.0 observed: noop preserves behavior but fails security; naive hardening passes static checks and fails cache initialization with errno30; known-good and scripted repair pass all14 final checks. Namespace/cluster cleanup verified. Agent5actions,2candidate repairs,3tests. No LLM inference or Checkov run.

See [verified real result](REAL_KUBERNETES_RESULT_VI.md) and [durable evidence](../evidence/kubernetes-2026-10-13/summary.json).
