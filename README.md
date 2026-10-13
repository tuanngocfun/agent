# Kubernetes Security Remediation Agent

A runnable first project for the question: **can an agent harden a container without breaking its required behavior?**

**Demo Kubernetes thật đã chạy thành công:** [xem GitHub Actions run](https://github.com/tuanngocfun/agent/actions/runs/38408621533) trên repo riêng `tuanngocfun/agent`, nhánh `kube-remediation-demo`, source commit `4461388`. Cluster `kind` chạy Kubernetes **v1.34.0**; artifact chứa patch, trace và kiểm tra runtime. Bản hardening đơn giản làm cache lỗi; vòng `scripted` sửa được sau **2 ứng viên, 3 lượt test**. Đây là bộ điều khiển viết tay trên Kubernetes thật, chưa phải thí nghiệm LLM.

Đọc [kết quả và giới hạn](docs/REAL_KUBERNETES_RESULT_VI.md), rồi dùng [hướng dẫn tiếng Việt](docs/KUBERNETES_DEMO_VI.md) để chạy lại.

See the [GitHub worker guide](docs/GITHUB_KUBERNETES_DEMO.md) for the workflow and evidence to inspect.

For the architecture and simulated teaching loop, start with [Hướng dẫn tiếng Việt](docs/START_HERE_VI.md), then read [ưu, nhược điểm của đề tài](docs/TOPIC_REVIEW_VI.md). This repository implements the first teaching loop of the long-term plan; the separate strategy package is stored only on the original workstation and is not included here.

## Run the simulated teaching demo

No installation, API key, GPU or cluster is required for this command. Python 3.10+; standard library only.

```bash
cd path/to/agent
bash scripts/demo.sh
```

The command prints the location of `SUMMARY.md`. Each scenario saves a base/candidate manifest, patch, trace, independent checks and a hash-bound review bundle. Existing output directories are never overwritten. Kubernetes accepts the JSON manifest format used here.

```bash
PYTHONPATH=src python3 -m kube_repair run \
  --scenario cache-path --output runs/my-first-repair

PYTHONPATH=src python3 -m kube_repair review --bundle runs/my-first-repair
```

Use a new output name on subsequent runs, or omit `--output` for a timestamped directory.

## What is implemented

The engine asks a provider to inspect approved evidence, propose a bounded manifest change, request tests, finish or abstain. Every proposal is checked against an allowlist before the trusted verifier runs. Test feedback returns to the provider, which can choose another step within action/repair budgets. The engine decides whether verification actually passed.

| Component | Current scope |
|---|---|
| Decision provider | Hand-authored `scripted` teaching baseline; optional local Ollama LLM adapter |
| Repair policy | One fixture Deployment; named security-context fields, approved group and bounded cache `emptyDir` |
| Verifier | Explicit simulation; Docker fixture runtime; Kubernetes namespaces on an explicit lab context |
| Cases | Required cache path; volume group permissions; image requires root; already secure |
| Controls | No-op, flags-only hardening, fixed storage template, oracle known-good |
| Review | Diff, trace, hashes; stale content/source/base detection; one-time local export |

**Default demo results are simulated and deterministic.** They demonstrate the control loop and evaluator failure cases. They are not LLM results, Kubernetes runtime evidence, a Checkov run, a held-out benchmark, or evidence that this method beats existing tools.

The `naive` baseline enables hardening flags but cannot write its cache. The `template` also mounts storage using a fixed group; it misses the 2000-group fixture. The `known-good` control reads author-provided fixture contracts and is an oracle control. These distinctions are visible in every report.

## Use an actual LLM

With a local Ollama server and an already installed model:

```bash
PYTHONPATH=src python3 -m kube_repair run \
  --scenario cache-path --provider ollama --model YOUR_LOCAL_MODEL \
  --backend simulated --output runs/local-model-trial
```

The adapter calls the loopback `/api/chat` endpoint with a structured JSON schema, disables HTTP proxies/redirects, enforces bounded response/context/time budgets, and records reported tokens separately from its conservative byte-based reservation. No model is downloaded or server started by this project. A model name is not an immutable revision; reports mark revision pinning unavailable. Resolve and record model digests before a research comparison. See the [Ollama chat API](https://docs.ollama.com/api/chat).

Add `--attacked` to include malicious repository instructions, and inspect `trace.json` to confirm whether the provider actually read that source. The attack is not exposed unless an `inspect repository` action occurs. There are no hidden tests or adaptive attacks in this starter.

## Run the fixture in Docker later

Use a dedicated lab machine with Docker and a trusted local Python base image. Build the supplied fixture yourself; arbitrary images may fake in-container probe evidence, so they are outside this runner's trust assumptions.

```bash
docker build --pull=false --network=none \
  -t repair-cache-app:lab fixtures/cache_app

PYTHONPATH=src python3 -m kube_repair run \
  --scenario cache-path --backend docker --image repair-cache-app:lab \
  --output runs/container-trial
```

The build needs `python:3.12-slim` present locally. For repeatable studies, pass `--build-arg BASE_IMAGE=python@sha256:YOUR_VERIFIED_LOCAL_DIGEST` and retain the digest and build records. The runner resolves the resulting local image ID before the task, refuses image changes, and uses `--pull=never`.

The trusted runner launches a container with fixed arguments, no host mounts, no published ports, no external network, memory/CPU/process limits and cleanup. It probes HTTP health, an independently computed result, cache read-back/reuse, process UID, actual root write denial, no-new-privileges, capabilities and seccomp filter mode. The model never receives the Docker socket or arbitrary command execution. See [Docker run](https://docs.docker.com/engine/containers/run/).

Docker's group/tmpfs mapping approximates the fixture's volume semantics. It does not test Kubernetes admission, volume ownership, CSI or cluster execution; seccomp filter mode does not identify the exact default profile. The [Kubernetes runner](docs/KUBERNETES_DEMO_VI.md) separately checks the fixture on real Pods; research claims still need independent workload histories and a broader evaluator. See [Kubernetes security contexts](https://kubernetes.io/docs/tasks/configure-pod-container/security-context/).

If Docker is missing or cleanup fails, verification fails. It never falls back to simulation.

## Review and local export

```bash
PYTHONPATH=src python3 -m kube_repair review --bundle runs/my-first-repair

PYTHONPATH=src python3 -m kube_repair export \
  --bundle runs/my-first-repair --output runs/reviewed-export \
  --expected-hash HASH_FROM_REVIEW
```

Export writes local files, including `deployment.json`, and records a receipt. It preserves the verification level in the report. It refuses changed artifacts or source, a mismatched reviewed hash, failed/abstained candidates, existing output and replay. Add `--base path/to/current-deployment.json` to check a current base snapshot. There is no deployment or GitHub PR integration. This integrity mechanism is not identity authentication; an operator with access to all source and artifacts remains trusted.

## Validate and extend

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Tests exercise unauthorized edits, forged success claims, runtime failures, malformed actions, policy boundaries and stale/replayed review. Docker protocol and Ollama transport tests use mocks; real backend execution must be validated separately.

Read source in this order: [fixtures](src/kube_repair/scenarios.py), [allowed edits](src/kube_repair/policy.py), [verification](src/kube_repair/verification.py), [decision providers](src/kube_repair/providers.py), [engine](src/kube_repair/engine.py), [review artifacts](src/kube_repair/artifacts.py).

The next milestone is an LLM-driven repair on the demonstrated Kubernetes runtime, followed by several independent workload histories. Freeze evaluator/model versions, establish competent one-shot/fixed-workflow baselines, protect held-out tests and compare at matched budgets before claiming a research contribution. Persistence here is an auditable trace, not resumable agent execution.

## Environment record

The required workspace preflight was attempted on 13 October 2026. This host lacks `/workspace`, and the host counterpart reports `/data` mounted read/write. This task only creates the user-requested project and validates software with synthetic fixtures; shared data is unused. Docker, kubectl and kind were absent during implementation. The shared ChatGPT URL could not be retrieved; the supplied quotation and saved strategy files were used instead.

Read [validation record](docs/VALIDATION.md) for executed checks and their limits. Historical files under `runs/` and the separate strategy package are local-only; the GitHub workflow uploads new runtime evidence as an Actions artifact.
