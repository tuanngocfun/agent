# A bounded runtime study of feedback and untrusted evidence

This is a separate protocol from the frozen v1 experiment. It currently defines **12 public base cases, 54 model cells and at most 96 inference calls**. Definitions and unit tests are preparation; only downloaded, audited Actions artifacts establish executed results.

The primary comparison asks whether **trusted runtime feedback helps beyond self-review at the same two-call limit**. A second comparison asks whether removing an untrusted repository note preserves repair performance when the note contains malicious instructions. One-shot repair is a lower-call baseline. Actual calls, tokens and elapsed time remain part of every comparison.

| Method | Call limit | Information after its first proposal |
|---|---:|---|
| `one-shot` | 1 | Final proposal is independently evaluated |
| `self-review` | 2 | Its own prior decision, with no candidate runtime feedback |
| `feedback` | 2 | Trusted candidate security and application observations |
| `feedback-filtered` | 2 | The same runtime feedback; untrusted repository note is omitted |

Every method receives the same trusted initial observations. Feedback shown to the model is a deterministic, bounded summary; complete original observations remain in the evidence. The evaluator, allowed edits, images and application code stay fixed across methods. The model receives JSON inputs and returns edits. It has no shell, cluster credentials, reference repair or verifier access.

## Cases and evidence units

The suite contains ten repair cases, one unchanged case and one bounded infeasibility case. Five exercises adapt external Infra-Bench defect classes: single-container admission, init/sidecar admission, ConfigMap listing, named-config access and a tenant-subject permission error. Seven authored cases cover cache writes, SQLite WAL, separate configuration/output mounts, temporary directories, shared group access, an already-secure workload and a UID-zero application conflict.

These are **adaptations and authored contracts**, not executions of the original external benchmark unchanged. In particular, the tenant exercise is a ConfigMap permission surrogate, not a running custom operator. Several filesystem cases share a template. Family labels, original source revision and adaptation notes are retained; twelve IDs do not establish twelve independent production workloads.

All twelve cases enter the clean three-method comparison. Six repair cases additionally enter the clean/injection comparison of raw versus filtered feedback. One fixed malicious note is used. The 54 cells are paired conditions over twelve cases; they are not 54 independent cases. There is one deterministic execution per cell, with no statistical independence claim for seeds or repeated executions.

This campaign uses the previously pinned **Qwen2.5 3B Instruct** CPU model. It studies methods within one model. The earlier v1 three-model comparison remains separate; this campaign cannot establish a new cross-model ranking.

## Execution and success criteria

The explicitly requested [workflow](../../.github/workflows/robustness-v2.yml) has two stages. First, it runs no-op, naive hardening, fixed-template and reference controls on disposable Kubernetes. Initial states and all feasible reference repairs must be validated with clean namespace/cluster cleanup. The model stage requires that successful validation artifact from the exact registered source and protocol. Only the run-request file may differ between validation and model-dispatch commits.

Each trial creates an owned namespace. Subsequent proposals update the original resources, preserving their UIDs. Only explicitly approved resource paths may change; images, application commands, evaluation settings and resource identities are protected. Security checks cover namespace admission, container controls, live process UID/GID, no-new-privileges, capabilities, seccomp, root mount flags, workload ownership and image identity. RBAC cases include actual authenticated application API operations and separate allow/deny authorization checks.

Application contracts use immutable programs that emit protected markers only after their filesystem or authenticated API assertions pass. These are bounded startup/operation contracts, not production load or long-duration availability tests. Completed Job and init-container processes cannot be probed after exit; their admission/specification, image, termination and application evidence are reported separately from live process probes. A failed application with no process probe cannot claim successful runtime-security coverage.

Every final proposal is verified independently, including self-review and one-shot proposals. A passing worker flag is insufficient: the report replays raw model responses and allowed edits, reconstructs prompts, checks raw token/duration data, binds Kubernetes observations to command ranges, audits image/source pins and requires cleanup. Missing, provider, infrastructure and invalid-evidence records remain visible.

The reference repair is an upper-bound control. It is not a deployable competing method. Deterministic baselines and model methods are compared on matching repair cases; unchanged and appropriate-abstention outcomes are reported separately.

## Reproduction and compute bound

From the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_robustness_*.py' -v
python3 -B scripts/freeze_robustness_plan.py --check benchmark/robustness-v2/plan.json
```

The default branch does not contain this workflow, so GitHub's manual-dispatch endpoint cannot start it there. On `kube-remediation-demo`, commit an explicit [request.json](request.json) with stage `validate`. After it succeeds, change only that file to stage `models` with the actual `validation_run_id` and a new request ID. Only changes to this request path trigger execution; ordinary code or documentation pushes do not start model campaigns. The workflow also supports manual dispatch if it is later registered on the default branch. Do not dispatch another campaign without reconciling the cumulative budget ledger.

The registered workload caps are 20 runner-minutes for reference validation, five model shards of 32 minutes each, and five minutes for reporting. Protocol and ordinary CI jobs consume additional minutes. Before this work, all visible repository jobs totaled 767 minutes after per-job rounding, leaving 233 of the user's authorized 1,000; that is a conservative job-duration proxy, not a billing invoice. Reconcile actual usage before each dispatch.

Reports include every registered cell, per-trial elapsed time, raw generation duration, tokens, failures, case/family outcomes, paired method differences and clean-to-injection changes. Confidence intervals use cases as the unit. Even 12/12 observed successes has a Wilson 95% lower bound of approximately 75.8%; six paired attack cases cannot support a broad robustness claim. Public training exposure, small related case families, a guided edit surface, one model and one injection payload remain limitations.
