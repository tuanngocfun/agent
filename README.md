# Kronos Financial Forecasting Lab

A working implementation of the main financial project in **Nghiên Cứu Chuyên Sâu Kronos.docx**:
probabilistic forecasting, chronological evaluation, two-stage adaptation, agent tools,
and a local dashboard. Code runs against the real official Kronos models; it does not
replace forecasts with synthetic demo data.

The project lives on [`kronos-evaluation-lab`](https://github.com/tuanngocfun/agent/tree/kronos-evaluation-lab).
The separate Kubernetes demo remains on `kube-remediation-demo`.

Verified desktop/mobile screenshots remain local under `output/browser/`.

## Start the dashboard on this machine

The isolated `.venv` and pinned `vendor/Kronos` checkout have already been prepared locally.

The dashboard is an application process: the page is reachable only while its
server is running. The commands below detach it from the current terminal and
anchor all paths to this checkout. They work even when your terminal is in `/home`:

```bash
bash /home/ngocnt/experiments/agents_financial_forcasting_market_lab/scripts/dashboard.sh start --device cuda:1
bash /home/ngocnt/experiments/agents_financial_forcasting_market_lab/scripts/dashboard.sh status
# Stop it explicitly when finished:
bash /home/ngocnt/experiments/agents_financial_forcasting_market_lab/scripts/dashboard.sh stop
```

`start` waits for `/health` to return success before reporting `ready: true`.
Repeated starts keep the same running instance. Process state and logs are in
`.cache/dashboard/`; the local service token stays in `.cache/api.token` and is
never printed by the helper. The process survives closing the starting terminal;
it is not configured to restart after a machine reboot. This background helper
uses Linux process ownership checks; use foreground `serve` on other platforms.

Open **http://127.0.0.1:8765**. Paste the contents of `.cache/api.token` into the
password field. This is a local application token; your Binance key is not needed.
GPU `cuda:1` was used for the recorded runs; choose `cpu` or another available GPU
on another machine. For foreground debugging, run the existing `kronos_lab serve`
command from this project directory.

**VS Code Remote SSH:** the server runs on the remote machine. In the **Ports** tab,
select **Forward a Port**, enter **8765**, then use **Open in Browser** and the
forwarded local address. If port 8765 is occupied on your laptop, VS Code can choose
a different local port; use the address displayed in Ports. See the
[official Remote SSH port-forwarding guide](https://code.visualstudio.com/docs/remote/ssh#_forwarding-a-port-creating-ssh-tunnel).
An embedded IDE viewer may reject framing; opening the forwarded address in an
external browser preserves the app's security policy. A `ready: false` status or
`ERR_EMPTY_RESPONSE` should first be checked against `.cache/dashboard/server.log`.

The dashboard generates forecasts, evaluates eight chronological windows, compares
Chronos-2 when installed, imports saved results/CSV, exports JSON, and shows a 3D
empirical sample-density surface. Explicit future session timestamps can be supplied
for stock data. API jobs are authenticated, bounded, and processed one at a time.

## Install on a new checkout

Python 3.10+ and Git are required. Install a suitable PyTorch build for your device.
The setup helper uses `uv` when available, otherwise Python's `venv`/pip.

```bash
bash scripts/setup.sh
# Optional independent model comparator:
uv pip install --python .venv/bin/python -e '.[compare]'
```

`requirements.lock` records the tested Linux/Python 3.12/CUDA environment, including
optional dependencies. Use `pyproject.toml` for other platforms. For fully pinned
Linux reproduction, `uv pip sync --python .venv/bin/python requirements.lock` can
restore that environment; then install this project with `--no-deps -e .`.
Weights are downloaded on first use. Forecasts and training resolve Hub references
to immutable SHAs, and local checkpoints receive content hashes. The audited upstream
code is fixed at `67b630e67f6a18c9e9be918d9b4337c960db1e9a`.

## Data → forecast → evaluation

```bash
.venv/bin/python -m kronos_lab download --symbol BTCUSDT --interval 1h --limit 1000
.venv/bin/python -m kronos_lab forecast --csv data/BTCUSDT_1h.csv --device cuda:1 \
  --lookback 128 --horizon 12 --sample-count 20 --output output/forecast.json
.venv/bin/python -m kronos_lab evaluate --csv data/BTCUSDT_1h.csv --device cuda:1 \
  --lookback 128 --horizon 12 --sample-count 20 --max-windows 20 --output output/evaluation.json
.venv/bin/python -m kronos_lab paper --report output/evaluation.json \
  --csv data/BTCUSDT_1h.csv --fee-bps 10 --slippage-bps 5 --output output/paper.json
```

- **Data:** UTC OHLCVA; Binance uses closed public candles and actual quote volume.
  CSV and optional yfinance/Vnstock v5 adapters use strict validation. Missing amount
  gets a labelled `volume × mean(OHLC)` proxy. Missing prices/volumes and duplicates
  are rejected. yfinance uses unadjusted prices and records that policy.
- **Forecast:** encode history once; retain the full `(samples,horizon,6)` tensor;
  return mean, q10/q50/q90, terminal voting, continuity and invalid-candle diagnostics.
  Normalization uses historical observations only. Context plus horizon is bounded
  by 512. No universal ×2.7 multiplier or “MCP confidence” is added.
- **Evaluation:** score last-close persistence and Kronos at matching origins.
  Fit per-horizon interval expansion on earlier calibration labels, freeze it, and
  score later, disjoint test labels. Metrics include MAE/RMSE, return/direction errors,
  Brier, coverage, interval width and pinball loss. Small samples and temporal
  dependence prevent a nominal-coverage guarantee.
- **Paper simulation:** LONG/FLAT decisions use forecast values only. Entry is the
  next candle's open; exit is the final candle's close, with adverse slippage and
  fees on both sides. Overlapping test windows are rejected. Outputs include net/gross
  return, turnover, costs and sampled drawdown. This is a local simulation, not an order API.

`p_up` is the fraction of generated paths whose terminal price exceeds the last
observed close. It is not a calibrated probability that the prediction is correct.
Generated OHLC constraints are diagnosed and left visible rather than silently repaired.
For equity/exchange sessions, pass `--future-timestamps sessions.json` containing the
actual future session timestamps. A CSV with regular timestamps alone does not prove
that the market trades through weekends; provide sessions when the calendar matters.

Optional provider examples:

```bash
.venv/bin/python -m kronos_lab download --source yfinance --symbol NVDA --interval 1d \
  --period 1y --output data/NVDA_1d.csv
.venv/bin/python -m kronos_lab download --source vnstock --symbol FPT --interval 1D \
  --output data/FPT_1d.csv
.venv/bin/python -m kronos_lab compare --csv data/BTCUSDT_1h.csv --device cuda:1 \
  --chronos-device cpu --output output/comparison.json
```

Vnstock v5 requires its provider-specific installation/setup; it is deliberately
optional. The recorded integration runs used Binance. Live yfinance/Vnstock access
was not exercised. Source data rights are separate from model/code licenses.

## Train and compare the three variants

Training is implemented locally, without calling the leaky upstream CSV dataset.
Create boundaries matching your data instead of copying historical dates:

```bash
.venv/bin/python scripts/make_training_config.py --csv data/BTCUSDT_1h.csv \
  --device cuda:1 --lookback 64 --horizon 8 --epochs 1 --max-steps 2 \
  --run-dir output/my-ablation --output output/my-training.json
.venv/bin/python -m kronos_lab ablate --config output/my-training.json \
  --sample-count 8 --max-windows 8 --output output/my-ablation-summary.json
```

This bounded command is an integration smoke test. Increase epochs/data/steps for
research; two optimizer steps do not establish adaptation quality. Four partitions
separate optimization, checkpoint-selection validation, calibration and final test.
All three variants use the same initial checkpoints, origins and sampling settings.
Historical statistics are used for every training window; labels remain inside their
partition. Predictor loss is restricted to the forecast horizon. Checkpoints and
manifests are saved, the best validation checkpoint is restored, and test/calibration
labels never select it. `configs/finetune.example.json` documents all settings.

To train one variant, set `mode` to `predictor-only` or `two-stage` and run:

```bash
.venv/bin/python -m kronos_lab train --config output/my-training.json
# Optional distributed training, with devices selected explicitly:
CUDA_VISIBLE_DEVICES=0,1 .venv/bin/python -m torch.distributed.run --standalone \
  --nproc_per_node=2 --module kronos_lab.training --config output/my-training.json
```

Use a new output directory per run. Two-worker CPU DDP was verified; multi-GPU DDP
was not run because other workloads occupied the first GPU.

## Connect an agent through MCP

```json
{
  "mcpServers": {
    "kronos-lab": {
      "command": "/absolute/path/to/project/.venv/bin/python",
      "args": ["-m", "kronos_lab.mcp_server"],
      "cwd": "/absolute/path/to/project",
      "env": {"KRONOS_DEVICE": "cuda:1"}
    }
  }
}
```

Tools: `forecast_kline`, `forecast_signal`, `forecast_compare`, `forecast_batch`,
`job_status`. Heavy inference runs outside the protocol event loop. Batch failures
are isolated per symbol. MCP supplies forecast evidence for an agent; this repository
does not contain a news RAG corpus or claim that model agreement proves accuracy.

HTTP clients use `POST /api/jobs` with `{"kind":"forecast","request":{...}}`,
`POST /api/batch`, and `GET /api/jobs/{job_id}` with `Authorization: Bearer ...`.
Valid kinds are `forecast`, `evaluate`, `compare`. Supply `source:"history"` with
candle rows to evaluate your own data. Jobs/results live in bounded process memory;
export results before restarting. Raw traces and secret values are not returned on failure.

## Verification and scope

```bash
.venv/bin/python -m pytest tests -q
PYTHONPATH="$PWD/vendor/Kronos" .venv/bin/python -m pytest vendor/Kronos/tests/test_kronos_regression.py -q
# Optional browser check after starting the API and creating saved runs:
.venv/bin/python -m playwright install chromium
.venv/bin/python scripts/browser_smoke.py
```

See [VALIDATION.md](VALIDATION.md), [recorded evidence](evidence/run-summary.json),
and [plan-to-code mapping](docs/IMPLEMENTATION.md). Real runs include Kronos-base,
Chronos-2, chronological evaluation and pretrained three-way ablation. Long research
training, broad market benchmarking, clinical/cross-domain datasets and news RAG
remain separate experiments; their results are not represented as complete.

The [technical report (PDF)](docs/technical-report/report.pdf) documents the methods,
architecture, recorded results, and limitations. Its [LaTeX source and build instructions](docs/technical-report/README.md)
include tables generated from the versioned evidence and a source-hash manifest.

`.env`, local API tokens, raw data, weights, environments and generated run reports are
ignored. The original Word files stay local; searchable text versions are retained
in [docs/plans](docs/plans). Legacy starter scripts remain available, including
`check_testnet.py` for an explicit read-only HMAC Spot-testnet check. No private
exchange request or live order was used for this implementation.
