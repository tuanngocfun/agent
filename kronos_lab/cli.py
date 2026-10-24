"""Command line entry point for the reproducible local research pipeline."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import secrets


def _write(path, result):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(f"Saved {path}")


def _data(args):
    from .data import fetch_binance, fetch_yfinance, fetch_vnstock, load_csv
    if args.csv:
        return load_csv(args.csv)
    if args.source == "binance":
        return fetch_binance(args.symbol, args.interval, args.limit)
    if args.source == "yfinance":
        return fetch_yfinance(args.symbol, start=args.start, end=args.end,
                              interval=args.interval, period=args.period)
    return fetch_vnstock(args.symbol, start=args.start, end=args.end,
                        interval=args.interval, limit=args.limit)


def _engine(args):
    from .forecast import KronosForecaster
    return KronosForecaster(upstream_dir=args.upstream_dir, model_id=args.model,
        tokenizer_id=args.tokenizer, device=args.device, model_revision=args.model_revision,
        tokenizer_revision=args.tokenizer_revision)


def _config(args):
    from .forecast import ForecastConfig
    return ForecastConfig(**{key: getattr(args, key) for key in (
        "lookback", "horizon", "sample_count", "temperature", "top_p", "top_k", "seed")})


def main(argv=None):
    parser = argparse.ArgumentParser(description="Kronos forecasting, evaluation, training and local tools")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("download", "forecast", "evaluate", "compare"):
        p = sub.add_parser(command)
        p.add_argument("--csv", type=Path)
        p.add_argument("--source", choices=["binance", "yfinance", "vnstock"], default="binance")
        p.add_argument("--symbol", default="BTCUSDT")
        p.add_argument("--interval", default="1h")
        p.add_argument("--limit", type=int, default=500)
        p.add_argument("--start")
        p.add_argument("--end")
        p.add_argument("--period", default="1mo")
        p.add_argument("--output", default=f"output/{command}.json" if command != "download" else "data/BTCUSDT_1h.csv")
        if command != "download":
            p.add_argument("--upstream-dir", default="vendor/Kronos")
            p.add_argument("--model", default="NeoQuasar/Kronos-base")
            p.add_argument("--tokenizer", default="NeoQuasar/Kronos-Tokenizer-base")
            p.add_argument("--model-revision")
            p.add_argument("--tokenizer-revision")
            p.add_argument("--device", default=None)
            p.add_argument("--lookback", type=int, default=128)
            p.add_argument("--horizon", type=int, default=12)
            p.add_argument("--sample-count", type=int, default=20)
            p.add_argument("--temperature", type=float, default=.6)
            p.add_argument("--top-p", type=float, default=.9)
            p.add_argument("--top-k", type=int, default=0)
            p.add_argument("--seed", type=int, default=42)
            p.add_argument("--future-timestamps", type=Path, help="JSON array of future session timestamps")
        if command == "evaluate":
            p.add_argument("--max-windows", type=int, default=8)
            p.add_argument("--stride", type=int)
            p.add_argument("--calibration-fraction", type=float, default=.5)
            p.add_argument("--calibration-end")
            p.add_argument("--evaluation-start")
        if command == "compare":
            p.add_argument("--chronos-device", default="cpu")
    for command in ("train", "ablate"):
        p = sub.add_parser(command)
        p.add_argument("--config", type=Path, required=True)
        if command == "ablate":
            p.add_argument("--output", default="output/ablation.json")
            p.add_argument("--max-windows", type=int, default=8)
            p.add_argument("--sample-count", type=int, default=20)
    paper = sub.add_parser("paper")
    paper.add_argument("--report", type=Path, required=True)
    paper.add_argument("--csv", type=Path, required=True)
    paper.add_argument("--fee-bps", type=float, default=10.)
    paper.add_argument("--slippage-bps", type=float, default=5.)
    paper.add_argument("--output", default="output/paper.json")
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--token-file", type=Path)
    token = sub.add_parser("init-token")
    token.add_argument("--output", type=Path, default=Path(".cache/api.token"))
    sub.add_parser("mcp")
    args = parser.parse_args(argv)
    if args.command == "init-token":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Never overwrite an existing token or print its value.
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(secrets.token_urlsafe(32))
        print(f"Created token file {args.output}; paste its contents into the local dashboard")
        return 0
    if args.command == "serve":
        import uvicorn
        from .api import create_app
        token = args.token_file.read_text().strip() if args.token_file else None
        uvicorn.run(create_app(token=token), host="127.0.0.1", port=args.port, log_level="info", access_log=False)
        return 0
    if args.command == "mcp":
        from .mcp_server import main as mcp_main
        mcp_main()
        return 0
    if args.command == "paper":
        from .paper import paper_backtest
        from .data import load_csv
        _write(args.output, paper_backtest(json.loads(args.report.read_text()), load_csv(args.csv),
            fee_bps=args.fee_bps, slippage_bps=args.slippage_bps))
        return 0
    if args.command == "train":
        from .training import train_from_config
        train_from_config(args.config)
        return 0
    if args.command == "ablate":
        from .ablation import run_ablation
        from .forecast import ForecastConfig
        config = json.loads(args.config.read_text())
        cfg = ForecastConfig(lookback=config.get("context_length", 128),
            horizon=config.get("horizon", 12), sample_count=args.sample_count, seed=config.get("seed", 42))
        _write(args.output, run_ablation(config, cfg, max_windows=args.max_windows))
        return 0
    frame = _data(args)
    if args.command == "download":
        output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(output, index=False)
        _write(output.with_suffix(".meta.json"), {**frame.attrs, "rows": len(frame), "timezone": "UTC"})
        return 0
    cfg, engine = _config(args), _engine(args)
    future = json.loads(args.future_timestamps.read_text()) if args.future_timestamps else None
    if args.command == "forecast":
        result = engine.forecast(frame, future_timestamps=future, config=cfg)
    elif args.command == "compare":
        from .comparison import compare_chronos
        result = compare_chronos(frame, engine.forecast(frame, future_timestamps=future, config=cfg), device=args.chronos_device)
    else:
        from .evaluation import walk_forward
        result = walk_forward(frame, engine, cfg, stride=args.stride, max_windows=args.max_windows,
            calibration_fraction=args.calibration_fraction, calibration_end=args.calibration_end,
            evaluation_start=args.evaluation_start)
    _write(args.output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
