# Decoder correction and bounded diagnostic v3

This amendment preserves the failed [v2 campaign](../../reports/robustness-v2-2026-10-15/README.md). It has its own source package, worker, reporter, workflow and frozen plans. No v2 record is rescored with corrected code.

The pinned Ollama 0.6.8 JSON Schema converter interprets an empty schema as an object grammar. V2 used `value: {}` for arbitrary JSON, so all 128 generated edit values in its parseable responses were objects. Required boolean/integer/list repairs were unavailable. See the [source evidence and review](../../docs/REVIEW_ROUND_3.md). Removal of repetition bounds might separately improve decoding speed; this remains a measurement hypothesis.

## Registered diagnostic

| Property | Value |
|---|---|
| Cases | `restricted-init-sidecar`, `rbac-list-configmaps` |
| Conditions | Clean evidence only |
| Decoder treatments | Legacy bounded schema; repetition bounds removed; bounds removed plus explicit six-type JSON union |
| Model | Pinned Qwen2.5 3B, Ollama 0.6.8, CPU, same model/image digests as v2 |
| Cells | 2 cases × 3 schemas × 1 execution = 6 |
| Calls | One repair call per cell, 120-second hard wall, 256 output tokens; a separate empty-message model-load request is retained in setup metadata |
| Controls | Initial no-op and protected oracle on each case = 4 |
| Order | Forward schema order on first case, reverse on second |
| Isolation | A fresh namespace per control/cell; loopback model endpoint |
| Job limits | Protocol 3 minutes + diagnostic 30 minutes + existing Source CI 10 minutes = 43 runner-minutes |

The logical validator, permitted edits and protected final tests remain strict across all schemas. The decoder transformation changes which JSON types can be generated; it grants no additional edit permission. Prompts ask for minimal necessary changes without case-specific answer hints, an arbitrary two-edit cap, or a blanket prohibition on Job edits.

Predictions registered before execution:

1. Legacy and unbounded schemas will continue to emit object edit values when they emit edits. Removing bounds alone will not restore scalar repair values.
2. The explicit type union will permit booleans, numbers, strings and arrays. This does not guarantee the model chooses a correct repair.
3. Bound removal could change latency, but two cases and reversed orders cannot establish a stable speedup or remove cache/hardware confounding.

The worker enforces separate cumulative setup, processing, finalization, model-call, verification, persistence and cleanup allowances. Before starting a cell, it reserves its full remaining worst-case work. The diagnostic cap includes report/upload and tool-installation reserves. Exhaustion produces missing/failure evidence, never a scripted repair fallback.

The diagnostic is an engineering check of the decoder, not a robustness study or model ranking. Cases were selected after reviewing v2 failure evidence; they are not held out. Raw responses, schema hashes, request hashes, prompt/generation durations, per-cell wall time, Kubernetes observations and cleanup outcomes are retained, including failures. Official artifacts are expiring copies; durable published reports include a hash-verified archive.

## Follow-up prepared, not run

`full-plan.json` defines the same 12-case, 54-cell, up-to-96-call method comparison with corrected decoding and computed per-shard capacity. Imported corpora still do not count as runtime-validated cases. One pinned model does not establish a cross-model ranking. The diagnostic-only workflow rejects full campaign requests; a broader campaign needs an explicitly funded run after the diagnostic is inspected.

## Offline checks

```bash
python3 -B scripts/freeze_robustness_v3_plan.py --check benchmark/robustness-v3/diagnostic-plan.json
python3 -B scripts/freeze_robustness_v3_plan.py --check benchmark/robustness-v3/full-plan.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_robustness_v3_*.py'
```

The run request binds the exact diagnostic plan ID. Updating documentation alone does not launch inference. Only a change to `request.json` on the demo branch triggers the bounded diagnostic workflow.
