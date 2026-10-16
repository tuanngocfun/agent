# Follow-up after the decoder diagnostic

The failed v2 campaign is a harness failure, with zero correct repairs. The v3 diagnostic isolates decoder changes on two review-selected cases. Neither run establishes a winning agent method. The [actual diagnostic](../reports/robustness-v3-2026-10-16/README.md) produced zero correct repairs, three request timeouts and three task failures. Returned calls spent most server time on prompt evaluation. Generic evidence transport, faster inference and redundant-proposal diagnosis should be investigated before committing to a full rerun.

The [prepared full plan](../benchmark/robustness-v3/full-plan.json) computes a **372 runner-minute** ceiling for 12 base cases, 54 registered cells and up to 96 repair calls. It is unrun and its diagnostic-only workflow does not launch it. A separate full-campaign workflow and fresh source validation are required before execution. The prior 1,000-minute cumulative allowance is not a fresh allowance for each rerun.

## Comparison worth measuring next

Compare trusted runtime feedback against self-review at the same two-call cap. Include one-shot as a lower-cost baseline and the fixed template as a strong deterministic baseline. Report paired base-case outcomes, repair-only success, already-secure preservation, appropriate abstention, actual tokens, elapsed time, infrastructure failures and all missing cells. Similar call limits alone do not guarantee equal tokens or execution time.

The twelve existing cases are public development cases after repeated debugging. A corrected rerun is a pilot on known cases, not a held-out robustness result. The six attack cases share one known payload; filtering it does not demonstrate general injection resistance.

## Add cases by validated behavior contracts

An external YAML file becomes a runtime repair case only after the initial security defect, required application behavior, allowed changes and reference repair have been verified on Kubernetes. Keep unchanged and infeasible cases too. Imported file counts do not increase the repair-task denominator.

Prioritize additional independent container-hardening tasks from Infra-Bench. Add network-policy tasks after establishing a CNI that enforces policy and independently testing allowed and denied traffic. KALM and ITBench configurations need application contracts before supporting behavior-preserving repair claims. Record upstream task and application families; cluster related adaptations rather than counting each parameter change as an independent case.

For a fresh evaluation split, freeze task families, allowed edits and protected tests before prompt changes or model inference. Hold out whole families where possible. Public-source holdout means held out from this project's development; it does not imply absence from model pretraining. Add neutral notes, useful legitimate instructions and several malicious payload types to measure both attack resistance and the cost of discarding useful evidence.

## Scope of the current agent methods

Current methods receive initial evidence directly and optionally get one candidate's runtime feedback. They mainly evaluate proposal generation and revision. A stronger investigation study would give a bounded set of read-only tools for selecting logs, events, image metadata and application settings, then measure whether those choices improve repair correctness at a comparable total budget. That extension needs its own protocol; it is not a result of the present fixed evidence loop.

One pinned Qwen model, related templates, bounded edit authority, a single execution per cell, a small attack set and no hidden evaluation set remain material limitations. Harness unit tests establish properties of the runner; they do not add agent benchmark cases or model calls.
