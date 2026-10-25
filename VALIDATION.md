# Validation — 24–25 October 2026, Asia/Ho_Chi_Minh

The following were executed on the development machine. Aggregate results and
immutable checkpoint identities are in [evidence/run-summary.json](evidence/run-summary.json).

| Check | Actual result |
|---|---|
| Project tests | **155 passed**; one nonfatal pandas/NumPy timedelta deprecation warning in a test fixture |
| Official pinned upstream regression suite | **4 passed**, 29.54 seconds on CPU with pinned Kronos-small/tokenizer weights |
| Real Kronos-base inference | GPU `cuda:1`, A100 MIG 20 GB; 64 historical candles, 8 forecast bars, 8 separate paths |
| Public data | 499 closed BTCUSDT 1h candles, 2026-10-03T22:00Z–2026-10-24T16:00Z |
| Chronological evaluation | Four calibration windows, four disjoint test windows, eight bars per window |
| Chronos-2 comparison | Real CPU inference on the same history/timestamps, close target + past volume |
| Pretrained ablation | Real zero-shot, predictor-only and two-stage; **two optimizer steps per trained stage**, saved/reloaded checkpoints |
| DDP | Two CPU workers, one step per stage using tiny real official architectures |
| MCP | Official JSON-RPC memory/stdio tests plus actual pretrained forecast_signal and batch success/error isolation |
| Browser | Desktop/mobile, forecast/evaluation/comparison JSON, 3D surface, export, real authenticated model job, stale-state regression |
| Secret isolation | Exact local credential values absent from staged text/binaries; `.env`, tokens, checkpoints and raw data ignored |

The actual small Kronos-base test run had close MAE 185.40 versus persistence 290.77.
Raw 80% interval coverage was 65.625%; expanded coverage was 96.875%, with mean width
increasing from 418.72 to 2953.80 and worse aggregate pinball loss. Wider bands are
not evidence of universally better uncertainty. Four windows cannot establish
statistical reliability or trading profitability. These figures describe this
recorded software smoke test, not a market-wide benchmark.

Both pretrained adaptation variants trained and changed their saved checkpoint
hashes. Two steps are insufficient to conclude that adaptation improves forecast
skill. The last-close baseline, sample settings, and scored origins are identical
across the three variants. Calibration does not reuse checkpoint-selection labels.
The recorded LONG/FLAT paper simulation stayed flat on all four test windows,
incurring no fees; active-trade cost/slippage behavior is covered by 22 paper tests.

Screenshots use actual saved runs. Full trajectory/evaluation exports and model
checkpoints stay under ignored `output/real-run/`; the raw CSV stays in `data/`.
Browser runtime and three missing shared libraries were installed/unpacked inside
`.cache/`; system packages were not changed. The temporary preview server is stopped
after QA. No private exchange request or order was performed.

Not run: full research-scale fine-tuning, multi-GPU training, live Yahoo/Vnstock
requests, broad equity universes, clinical/cross-domain experiments, or a separate
news/multimodal RAG system. Initial checkpoint pretraining data was not independently
audited. The implemented workflows support subsequent experiments without claiming
their scientific outcomes in advance.

The parent workspace harness was attempted. Its Docker-specific `/workspace` and
`/data_ngoc` mounts are absent on this host, and `/data` is writable rather than the
expected read-only mount. Shared datasets/mounts were not modified. Project outputs
and the experiment record were created under `/home/ngocnt/experiments/`.


## Availability fix — 25 October 2026

The initial preview process had been stopped after QA. The implementation tests did
not imply that port 8765 remained live for the user. After the user's failed-page
report, a persistent start/status/stop helper was added and launched from `/home`.
The homepage and `/health` returned HTTP 200, and a newly submitted authenticated
Kronos-base job completed on `cuda:1`, retaining shape `(8,8,6)` in about 13 seconds
including model load. The service is left running for the user. Process logs/state
are ignored under `.cache/dashboard/`; no system-wide service or reboot startup was
installed. Browser verification and four isolated lifecycle tests cover this change. The
updated complete project suite passes 159 tests.

## Fresh forecasts, paired evaluation and visual report — 25 October 2026

Executed `scripts/run_visual_evaluation.py` on a new frozen public Binance
snapshot: 999 closed BTCUSDT 1h candles, 2026-09-13T10:00Z–2026-10-25T00:00Z.
The CSV SHA-256 is
`5d53c32778c5fcbd3cc78c8ee3471791715d00dc70cc5cb341abc1d1b8ca8934`.
Pinned Kronos-base GPU and Chronos-2 CPU each generated 60 chronological native
forecasts plus the latest forecast, with 128 history and 12 future bars;
Kronos retained 20 paths, seed42. Twenty earlier windows fit separate interval
expansions and 40 later windows supply 480 test horizon observations.

Independent review matched all 60 history hashes, timestamps and labels to the
frozen CSV, verified native Chronos points equal q50, recomputed point error,
coverage/width, every executed trade's fill accounting, compounded equity and
fees. No Chronos paths or probability estimates were invented. Invalid Kronos
OHLC bounds were exposed: 67 of 14,640 generated candles across the 61 forecasts;
the latest has zero. No nonpositive OHLC or negative volume/amount was generated.

Kronos median MAE is 467.02 USDT versus Chronos499.24, while persistence459.08
beats both. Kronos mean MAE460.13 also fails to beat persistence. Raw/expanded
coverage is Kronos38.33%/73.75%, Chronos72.50%/76.04%. The exploratory paired
four-origin moving-block interval for Kronos-minus-Chronos median MAE difference
is [-62.34,12.22] USDT (2,000 draws, seed42), crossing zero.

Eight economic rules were fixed before scoring. Consensus above a0.30045%
cost gate returned +0.44056% from only two trades,50% trade win rate,2.2873%
sampled max drawdown. Cash returned0%; all other active candidates lost net.
Chronos cost filtering won57.1% of seven trades but lost2.195%, illustrating
why win rate alone cannot identify profitability. Latest native returns are
Kronos mean−0.44494% and Chronos median+0.27915%; both cost filters select FLAT.
Paper execution is idealized next-open entry with10bps fees and5bps adverse
slippage per side; latency, intrabar drawdown and actual execution are not tested.

`scripts/plot_visual_evaluation.py` created four readable scientific figures;
`scripts/capture_report_dashboard.py` captured actual forecast, evaluation and
comparison views from new exports, without credentials or JavaScript errors.
Source SHA receipts and plotted values accompany the versioned figures. Six
new focused evaluation tests pass; the complete suite passes **165 tests in
12.20s**, with the same one nonfatal timedelta warning. No fresh adaptation,
multi-GPU training, private exchange request or order was performed.
