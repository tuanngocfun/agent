# Real LLM and Kubernetes demo on GitHub Actions

The current workflow runs a **CPU language model that chooses repair actions**, then tests each permitted candidate on Kubernetes. It uses [llm_kubernetes_demo.py](../scripts/llm_kubernetes_demo.py), rather than the historical scripted-only launcher.

The launcher selects pinned **Qwen2.5-3B-Instruct** with **compact-schema guided decoding** and guarded trusted-engine completion. The recorded [run 38528564033](https://github.com/tuanngocfun/agent/actions/runs/38528564033) completed successfully, and the downloaded artifact passed its [local audit](../evidence/llm-kubernetes-2026-10-14/audit.json). Its source is `d770c0efea239754e221606a8f76ff16fcc5aedb`, with 139 full tests passed.

The model returned **one proposal, producing one repair and two test runs**: the initial configuration and the candidate. All 14 protected checks passed; the [final report](../evidence/llm-kubernetes-2026-10-14/reports/kubernetes/results/agent/report.json) records `accepted: true`, `status: repaired` and completion by `trusted_engine`. Ollama reported 2,205 prompt tokens and 197 completion tokens, totaling 2,402 for the repair call. This run needed no inspect action or revision and demonstrates one guided repair, rather than an adaptive-feedback benchmark. The [Vietnamese result record](REAL_LLM_KUBERNETES_RESULT_VI.md) links the raw response, patch and audit. Kubernetes and Ollama ran on the disposable Actions worker; no cluster or model service was started on the original workstation.

The earlier [successful scripted run](https://github.com/tuanngocfun/agent/actions/runs/38408621533) remains separate in the [historical result record](REAL_KUBERNETES_RESULT_VI.md). The previous model run with a passing candidate still ended with `accepted: false`; its overall failure is preserved below.

## Read the current job

1. Open the run and verify its source commit. The private repository is [`tuanngocfun/agent`](https://github.com/tuanngocfun/agent); source is on `kube-remediation-demo`.
2. Inspect **Run pinned CPU LLM with protected Kubernetes tests**. A green checkout or unit-test step does not establish a model-generated repair.
3. Download `real-llm-kubernetes-evidence`. Upload runs even after failure, so an artifact's existence also does not establish success.
4. Read the top-level `summary.json`, then `kubernetes/summary.json`, `model-pin.json` and `kubernetes/results/agent/report.json`.
5. Connect model responses in the report to actions in `trace.json`, candidate tests and `patch.diff`.

While the job runs, the Actions log now shows flushed stage/counter lines such as `Agent progress: stage=before_model_call ... current_verified_pass=false`. The wrappers forward this output live. If the final bundle is absent after an interruption, inspect `kubernetes/results/agent-progress.json` for partial evidence.

The workflow is [kubernetes-demo.yml](../.github/workflows/kubernetes-demo.yml), named **Real LLM Kubernetes remediation demo**. Its YAML declares `workflow_dispatch` and pushes to the exact demo branch. It uses an Ubuntu 24.04 worker, read-only repository permissions, a 40-minute job cap and seven-day artifact retention.

To repeat a recorded commit, open its completed run and choose **Re-run all jobs**; a rerun uses the original commit/ref. Push changed source to `kube-remediation-demo` to test the updated commit. See [GitHub's rerun documentation](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs). The workflow file currently lives on the demo branch while `main` has the bootstrap only. GitHub requires the workflow file on the default branch for `workflow_dispatch`, so the **Run workflow** UI is conditional on that prerequisite; its presence is not promised for this repository layout. [GitHub manual-workflow documentation](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)

## Fixed model and runtime

| Component | Current selection and check |
|---|---|
| Model | Qwen2.5-3B-Instruct, `qwen2.5:3b-instruct-q4_K_M`, about 1.93 GB; its approved manifest digest is checked before and after the repair loop. |
| Weights | The downloaded GGUF layer is SHA256-checked separately. |
| Server | Ollama `0.6.8` in a digest-pinned Docker image, exposed on a loopback-only random port. |
| Inference | Temperature 0, context 8192, two CPU threads, at most 512 output tokens and 420 seconds per action call; `/api/ps` must report zero VRAM use. |
| Decoding | The pinned launcher explicitly selects `compact-schema` and checks the provider's actual mode in the final report. |
| Completion | The pinned launcher explicitly selects `verified-repair`; successful guarded completion is attributed to `trusted_engine`. |
| Workload | The trusted cache fixture, built from a digest-pinned Python base. |
| Kubernetes | kind with a digest-pinned Kubernetes v1.34.0 node image; tool binaries are checksum-verified. |

The whole agent process has a 1,800-second cap; the enclosing kind launcher has a 2,100-second cap. These are separate from the 420-second per-action deadline and the job's 40-minute cap. A timeout remains a failed/incomplete run.

The selected quantization is listed by [Ollama](https://ollama.com/library/qwen2.5:3b-instruct-q4_K_M). Model weights are downloaded into the disposable worker's cache; they are not published in this repository or the evidence artifact. This general 3B checkpoint is published under the [Qwen Research License](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct).

The approved model manifest is `sha256:357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`; the GGUF layer is `sha256:5ee4f07cdb9beadbbb293e85803c569b01bd37ed059d2715faa7bb405f31caa6`. Both are checked against the downloaded model and recorded in `model-pin.json`.

The current **compact-schema** mode uses a 2,273-byte system guide and a 1,745-byte generation schema. The schema offers three action variants: inspect, propose with `changes`, and test/finish/abstain. It constrains the outer action envelope and requires all seven security-context fields whenever that group is present. Complete manifest proposals are excluded in this mode. The schema contributes field names and allowed control/storage shapes, including the existing drop-ALL and RuntimeDefault structures. UID/GID remain freely generated positive integers, without task-specific defaults or identity values inserted by the engine. Boolean choices and mount paths are also generated and remain subject to policy.

This is **guided typed decoding**, so results measure the model together with that protocol guidance. They do not establish unconstrained instruction following. Strict Python validation, mutation policy, backend and all 14 acceptance checks remain unchanged. The CLI still supports `--decoding-mode json|schema|compact-schema`, with `json` as its default; the pinned wrapper explicitly chooses compact-schema. The existing `schema` mode uses the full action schema, while JSON mode constrains JSON syntax and relies on subsequent action validation.

The guide clarifies tool effects: the initial manifest and every valid proposal are tested automatically; `inspect` only fetches evidence; `test` reruns the unchanged current configuration and applies no repair. A deterministic failure needs investigation or a changed proposal to make progress. The task's `required_security_controls` includes contract-derived `runAsUser` and `runAsGroup`—10001 for this Kubernetes fixture. Workload names, labels, selectors and app container identity stay protected; task-approved process UID/GID changes are allowed. Non-root, read-only root filesystem, no privilege escalation, drop ALL capabilities and RuntimeDefault seccomp remain required.

A short generation smoke test must produce actual completion tokens before the repair loop starts. Its simple JSON reply checks model generation, not the full repair protocol. Loading a model with an empty warm-up request can produce zero tokens and does not prove generation works.

Partial `changes.securityContext` proposals merge supplied fields into the current configuration; omitted fields retain their values. Setting `runAsNonRoot` checks the selected user and does not choose a UID. If `runAsUser` is currently 0, the model must explicitly supply the task-approved `runAsUser` and `runAsGroup`. The engine applies model-authored fields without inserting those target values, and the acceptance checks remain unchanged.

The launcher runs the model container with the worker UID:GID, `HOME=/tmp` and its cache mounted at `/tmp/.ollama`. This startup configuration is supplied automatically; reproduction does not require manually changing cache permissions.

[kind_demo.py](../scripts/kind_demo.py) creates a dedicated cluster and kubeconfig, loads the fixture and establishes its actual CRI image ID. It compares no-op, naive hardening, known-good and the **Ollama provider** on the same scenario. There is no scripted decision fallback in the LLM launcher.

The engine retries only a trusted adapter `ProviderError` with code `invalid_action`, within the existing action budget. It records `rejected_provider_output` and a `trusted_protocol` validation error for the next model call. The rejected output executes no tool, applies no manifest, runs no verification and consumes no candidate-repair budget; the model-call/action budget is still consumed. Transport, identity and other provider failures stop the loop. The model must author a new valid action; the engine does not rewrite its output or supply a repair by rule.

The naive control must pass static checks and fail required cache behavior. The accepted agent repair must preserve the declared application behavior and satisfy protected Kubernetes runtime checks. The launcher also requires actual LLM completion tokens, the selected provider/model digest and successful model/cluster cleanup before reporting success.

## Trusted completion after a verified repair

The CLI and kind launcher offer opt-in `--stop-on-verified-repair`, defaulting to false. The pinned LLM wrapper enables it. The engine stops only after a changed valid model proposal has been applied, the latest independent verification passes all checks, its manifest hash matches the current candidate, no infrastructure error exists and fresh policy validation succeeds. It records `trusted_completion` with actor `trusted_engine`; report fields are `completion_policy: verified-repair` and `completion_actor: trusted_engine`. It does not invent an LLM `finish` action.

Default `model-finish` behavior is preserved. An initially secure or unchanged workload still requires the provider to finish, including when the opt-in flag is present. This is a controller termination fix: the existing `test` action, token/action budgets, schema and 14 hardening/behavior checks stay unchanged. The trace proves repeated tests after a passing candidate; it does not prove that enum ordering caused the model's repetitions.

Model-authored repair values and engine-controlled completion are separate contributions. The current workflow uses pinned Ollama; the user's Copilot Student access has not been initialized or called for this demo.

The backend recognizes only the exact kubelet `CreateContainerConfigError` rejection for a candidate with `runAsNonRoot: true` and integer `runAsUser: 0` as failed application-startup feedback. The model can then propose a permitted non-root identity. Unknown configuration errors, image failures and other infrastructure problems still stop the run. If kubelet rejects startup before reporting an image ID, image-identity and runtime checks fail; the record makes no claim that a container executed or that its image identity was verified.

## Evidence to inspect

| Artifact path | Purpose |
|---|---|
| `summary.json` | Overall launcher outcome, model/provider and error if present. |
| `model-pin.json` | Model/weight digests, server version, settings, tags before/after and CPU residency observations. |
| `inference-smoke.json` | Short JSON generation before the repair loop, with actual completion-token counts. This call has a 32-token cap. |
| `model-commands.json`, `model-server.log` | Setup, inference-server and cleanup evidence. |
| `kubernetes/summary.json`, `kubernetes/image-pin.json` | Control outcomes and trusted fixture/source/runtime image identity. |
| `kubernetes/results/agent/report.json` | Independent verification, budgets, model metadata and `provider.inference_calls`. |
| `completion_policy`, `completion_actor` in that report | Whether completion came from provider finish or guarded trusted-engine verification. |
| `kubernetes/results/agent-progress.json` | Atomic partial snapshot of model responses/actions, manifest, verifier results and counters; diagnostic only. |
| `kubernetes/results/agent/trace.json`, `patch.diff` | The decision trajectory, policy rejections, candidate tests and accepted change. |

Each `inference_calls` entry retains the raw Ollama server response, the parsed action, reported token usage, request/response hashes and status. Compare its `action` with the engine's decision event. The raw response is model-origin evidence from the local server, not the authority that decides whether tests passed. Verification comes from the runner. Context compaction retains the current task, manifest, inspected evidence, full latest trusted verifier observation and policy feedback. Duplicated latest-test data in history refers to that preserved observation; historical manifest/evidence duplicates are hashed and older verifier results summarized.

The upload explicitly selects reports and bundles. Kubeconfig, model weights and raw cluster logs are excluded. A report with `accepted: true` should also show backend `kubernetes`, `runtime_verified: true`, provider `ollama`, `uses_llm: true`, the selected model revision and actual inference calls. Check both summaries and cleanup commands before describing the whole job as successful.

The optional CLI `--progress-output` requires a fresh file path whose parent directory already exists. Snapshots are replaced atomically and contain a snapshot hash, source fingerprint and the manifest hash associated with verification. They preserve information available at the last saved stage; an in-flight model call killed by an outer timeout may still have no retained response. They always say `accepted: false` and `exportable: false`, including a snapshot taken after the final bundle is written. A progress-stage line or passing current probe is not approval or completion. Only the final hash-bound review bundle can authorize local export under the existing workflow.

## Earlier evidence and limits

| Recorded run/configuration | What was established |
|---|---|
| [Scripted Kubernetes run](https://github.com/tuanngocfun/agent/actions/runs/38408621533), commit `44613880014ca56882f0a21e5de461db97941b50` | Runtime repair passed with hand-written rules. It is separate from LLM evidence. |
| Earlier Qwen2.5-Coder attempts: [1.5B](https://github.com/tuanngocfun/agent/actions/runs/38449404110), [3B UID omissions](https://github.com/tuanngocfun/agent/actions/runs/38456111385), [3B repair-budget stop](https://github.com/tuanngocfun/agent/actions/runs/38498086650) | Real model responses were retained; proposed repairs omitted required controls or process identity and were not accepted. Earlier CPU/schema attempts also timed out. |
| [General Qwen2.5 JSON-mode run](https://github.com/tuanngocfun/agent/actions/runs/38500479314) | Twelve real responses had invalid action envelopes; zero repairs, one initial test, 33,961 reported tokens. No repair was applied. |
| [General Qwen2.5 compact-schema run](https://github.com/tuanngocfun/agent/actions/runs/38502780956), commit `59e0e9fab8fd51a18065ece5241d2ee15b174693` | The first proposal supplied UID/GID 10001, fsGroup 2000 and the cache configuration; all 14 Kubernetes checks passed. Nine subsequent `test` actions also passed, then a budget error ended the workflow with `accepted: false`. |

The last run had **10 completed model calls, one repair and 11 tests**. Ollama reported 31,575 prompt tokens plus 422 completion tokens, totaling 31,997. The eleventh attempted call hit the conservative budget before another inference occurred. The model's passing proposal is preserved in its trace; the failed final bundle retains the base in `candidate.json` and is not exportable as an accepted repair.

The controller fix now ends a fresh verified repair through the explicit guarded engine policy. It retains `test`, the same decoder, model pins, budgets and all 14 checks. Model-finish remains the default for other CLI runs. This addresses the observed continuation after success; causal claims about enum order or decoder bias remain hypotheses. Earlier checkpoints, prompts and budgets changed, so the attempt history is not a controlled model-quality study.

This audited success covers one synthetic workload and declared probes. It is not a held-out benchmark, prompt-injection study, production-security guarantee or proof that an agent beats templates. Static checks are built into this lab; Checkov is not part of the run. Seccomp filter mode confirms a filter is active without proving the full profile contents. See the [Vietnamese runbook](KUBERNETES_DEMO_VI.md) for reproduction and scope.
