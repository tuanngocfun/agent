# Validation records

## Real LLM and Kubernetes — 14 October 2026

The current full unit suite passed **139 tests** before [workflow #14](https://github.com/tuanngocfun/agent/actions/runs/38528564033) ran source commit `d770c0efea239754e221606a8f76ff16fcc5aedb`. The GitHub job completed successfully. Actual Qwen2.5 3B Instruct Q4_K_M CPU inference generated one changed candidate, accepted after **14/14 protected checks on Kubernetes v1.34.0**. The agent made 1 model call and 2 verifier runs, with 2,205 prompt + 197 completion = 2,402 reported agent tokens. Model/server smoke inference is recorded separately.

Completion uses the explicitly enabled `verified-repair` policy: the engine records `trusted_completion` after the changed, policy-valid candidate passes verification with a matching hash and no infrastructure error. The default still requires model `finish`. New tests cover successful termination without another provider call, revision after failed cache behavior, requested verification, default/no-op/initial behavior and policy/cleanup/hash guards. Verifier predicates and budgets were not relaxed.

The downloaded archive matches GitHub digest `72a5ae2561aa4dddaf137777abc4bc47bdd578139486b10f705d429801fc5bdf`. A local consistency audit passed for source fingerprint, four review bundles, raw model response/action/candidate replay, exact request hash, model/weight/CPU identity, explicit task UID/GID targets, all protected checks, nonexportable progress journal and recorded cleanup. A second read-only review found no discrepancy. The same audit passed again on the durable copy of evidence.

See [LLM result and limitations](REAL_LLM_KUBERNETES_RESULT_VI.md), [audit](../evidence/llm-kubernetes-2026-10-14/audit.json) and [artifact metadata](../evidence/llm-kubernetes-2026-10-14/artifact-info.json). One schema-guided synthetic fixture does not establish iterative investigation, adversarial robustness or held-out reliability. Checkov was not run. Worker records are trusted evidence, not remote attestation.

Historical workflow #13 had an intermediate LLM candidate that passed all 14 checks but ended with a token-budget error after repeated tests. Its final result remains failed. The fresh run demonstrates the controller fix; earlier attempts varied prompts/models/protocol settings and are development history, not a benchmark success rate.

The host workspace preflight was repeated on 14 October: the same missing `/workspace` and read/write `/data` discrepancy remains. Shared datasets and GPUs were not used. No local cluster was started; the real model/Kubernetes execution occurred on the authorized GitHub worker.

## Starter validation — 13 October 2026

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

At this initial stage, no real LLM inference, Docker container, Kubernetes cluster, Checkov scanner, GPU job or held-out evaluation had been executed. Simulation proved only the behavior of this model of the fixtures. Later runtime/model results are recorded separately above and below.

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
