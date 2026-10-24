# Plan-to-code mapping

This implements the financial forecasting project described in the supplied Word
plan. The plan also proposes independent research directions; implementation does
not imply that their scientific hypotheses have been established.

| Plan requirement | Implementation | Verification |
|---|---|---|
| Public/local OHLCVA | `kronos_lab/data.py`; CSV, Binance, Yahoo, Vnstock v5 | Binance live; provider adapters mocked |
| Real Kronos and immutable provenance | `forecast.py`, clean pinned upstream and resolved model SHAs | Kronos-base GPU; four official upstream regressions |
| Keep all Monte Carlo paths | Encode once, branch token paths, return S×H×6 | Real eight-path GPU run; causal/RNG/shape tests |
| Quantiles, voting, continuity | `forecast.py` summary and diagnostics | Raw q10/q50/q90 and sample fractions |
| Walk-forward and baseline | `evaluation.py` | Real chronological calibration/test; adversarial leakage tests |
| Uncertainty calibration | Earlier-label additive per-horizon expansion | Frozen before test; width and held-out coverage reported |
| Two-stage fine-tuning | `training.py`, tokenizer then predictor | Actual pretrained two-step stages; checkpoint reload and hashes |
| Ablation | `ablation.py` | Zero-shot/predictor-only/two-stage, identical scored origins |
| Distributed training | torchrun/DDP, correct rank saves/sampling | Two CPU workers; GPU DDP not run |
| Paper trading with costs | `paper.py` | Causal next-open entry, exact cost math tests; real report stayed FLAT |
| MCP/agent integration | `mcp_server.py`, shared `service.py` | Official SDK JSON-RPC memory and actual stdio integration |
| Chronos-2 comparison | `comparison.py` | Real pretrained CPU inference using close + past volume |
| Batch jobs and failures | Bounded shared executor, per-symbol outcomes | Queue saturation/release and batch-isolation tests |
| Local dashboard/API | `api.py`, `web/` | Browser desktop/mobile, live authenticated model call, 3D density |
| Cross-domain/biomedical research | Independent proposed study, not a financial feature | No dataset or scientific result supplied; not run |
| News/multimodal RAG | MCP boundary is available for an external agent | No corpus or separate RAG model implemented |

## Corrections to the source plan

- No global ×2.7 calibration constant. Interval correction is fitted on a dedicated
  chronological calibration split and inspected on later labels.
- No field called “MCP-standard confidence”. MCP is a tool protocol. Sample votes
  remain descriptive, and Brier scores/coverage are measured separately.
- Stock sessions are explicit. Irregular data does not get a guessed business-day
  calendar; a regular-looking CSV still needs an appropriate calendar policy.
- The official averaging predictor is not used to estimate sample distributions.
- Fine-tuning does not wrap the upstream `finetune_csv` normalization. Every window
  fits its statistics on historical values only; calibration/test mutations are
  tested to leave selected training checkpoints unchanged.
- Pinned upstream dependency cross-attention switches causal behavior in eval.
  Training validation explicitly preserves causal attention while disabling dropout;
  otherwise teacher-forced validation could see later sibling tokens.
- Model/checkpoint identities are saved. Pretraining data provenance is not
  independently audited; these runs are software/evaluation evidence, not proof
  of uncontaminated broad-market forecasting skill or profitability.

## Architecture

Public/CSV providers → strict UTC OHLCVA → immutable Kronos model → separate paths.
The same engine serves CLI, authenticated local HTTP jobs and stdio MCP tools.
Evaluation feeds only historical prices and known future timestamps into the engine;
actual prices are scored afterward. Training has separate optimization, selection,
calibration and test partitions. Exports carry revisions, seeds and data hashes.
