# Validation record — 24 October 2026 (Asia/Ho_Chi_Minh)

- Python 3.10+ standard-library offline suite: 16 tests passed.
- Syntax checks passed for all three scripts; CLI `--help` passed for all three.
- Public network smoke test succeeded: 10 closed BTCUSDT 1h candles downloaded
  from `https://data-api.binance.vision/api/v3/klines`. Timestamp range:
  2026-10-24T03:00:00+00:00 through 2026-10-24T12:00:00+00:00.
  CSV/metadata were saved outside the repository in `/tmp` and are not published.
- Offline checks cover closed-candle filtering, quote-volume mapping, duplicate
  timestamps, gaps, invalid prices, malformed CSV, timestamp normalization,
  HMAC signature, server-clock offset, fixed GET endpoints, rejected redirects,
  environment-file precedence and sanitized failure output.
- Reviewed `KronosPredictor.predict()` and dependency declarations at upstream
  revision `67b630e67f6a18c9e9be918d9b4337c960db1e9a`. Held-out prices are not
  passed to the predictor.
- No model weights downloaded and no Kronos inference, fine-tuning, evaluation
  benchmark, private testnet request or order execution was performed.
  This host's default Python lacks numpy, pandas and torch; setup is documented
  in README for a separate virtual environment.
- Original DOCX ZIP contents, normalized text and supplied HTML were checked
  against local `.env` credential values: zero exact matches. Embedded DOCX
  images were visually inspected and contain formulas/research charts, without
  credential screenshots. This is a targeted check, not a general secret audit.
  Original DOCX files and `.env` stay local and ignored by Git.
- Workspace harness check was attempted as required by the parent AGENTS.md.
  It cannot pass on this host: its expected Docker `/workspace` and `/data_ngoc`
  mounts are absent, and `/data` is mounted writable rather than read-only.
  No mounts, datasets or unrelated projects were changed.
