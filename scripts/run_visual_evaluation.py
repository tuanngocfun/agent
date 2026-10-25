#!/usr/bin/env python3
"""Fresh paired Kronos/Chronos experiment with frozen chronological calibration.

Native Chronos quantiles are retained without manufacturing Monte Carlo paths or
up probabilities. Model inference is cached per origin so an interrupted run can
resume on exactly the saved closed-candle snapshot. This script never reads API
credentials and never places orders.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from kronos_lab.comparison import compare_chronos
from kronos_lab.data import fetch_binance, load_csv
from kronos_lab.evaluation import _fit_expansion, _json_value, _pinball, save_evaluation, walk_forward
from kronos_lab.forecast import ForecastConfig, KronosForecaster
from kronos_lab.paper import paper_backtest

MODEL_REVISION = "2b554741eca47781b64468546e77fef3e85130e6"
TOKENIZER_REVISION = "0e0117387f39004a9016484a186a908917e22426"
CHRONOS_REVISION = "29ec3766d36d6f73f0696f85560a422f50e8498c"


def emit(event, **values):
    print(json.dumps({"time_utc": datetime.now(timezone.utc).isoformat(),
                      "event": event, **values}), flush=True)


def stamp_key(value):
    return pd.Timestamp(value).strftime("%Y%m%dT%H%M%SZ")


def load_json(path):
    return json.loads(Path(path).read_text())


class CachedForecaster:
    def __init__(self, engine, output):
        self.engine, self.output = engine, output
        self.results = {}

    def forecast(self, history, *, future_timestamps=None, config):
        key = stamp_key(history["timestamps"].iloc[-1])
        path = self.output / "native" / f"kronos-{key}.json"
        expected = asdict(config)
        if path.is_file():
            result = load_json(path)
            assert result["metadata"]["config"] == expected
            assert result["metadata"]["model"]["revision"] == MODEL_REVISION
            assert result["metadata"]["tokenizer"]["revision"] == TOKENIZER_REVISION
            assert pd.Timestamp(result["history"][-1]["timestamps"]) == history["timestamps"].iloc[-1]
            emit("kronos_cached", history_end=key)
        else:
            started = time.monotonic()
            result = self.engine.forecast(history, future_timestamps=future_timestamps, config=config)
            result["metadata"]["wall_seconds_including_load"] = time.monotonic() - started
            save_evaluation(result, path)
            emit("kronos_completed", history_end=key, seconds=result["metadata"]["wall_seconds_including_load"])
        if future_timestamps is not None:
            assert pd.DatetimeIndex(pd.to_datetime(result["timestamps"], utc=True)).equals(
                pd.DatetimeIndex(pd.to_datetime(future_timestamps, utc=True)))
        self.results[key] = result
        return result


def native_metrics(windows, *, calibrated=False, baseline=False, median_point=False):
    actual = np.asarray([w["actual_close"] for w in windows], dtype=float)
    anchors = np.asarray([w["last_close"] for w in windows], dtype=float)[:, None]
    point_key = "median_close" if median_point else "forecast_close"
    points = np.broadcast_to(anchors, actual.shape) if baseline else np.asarray(
        [w[point_key] for w in windows], dtype=float)
    error = points - actual
    return_error = error / anchors * 100
    signs = np.sign(points - anchors) == np.sign(actual - anchors)
    result = {
        "windows": len(windows), "observations": int(actual.size), "horizon": actual.shape[1],
        "close_mae": float(np.abs(error).mean()), "close_rmse": float(np.sqrt((error ** 2).mean())),
        "return_mae_pct": float(np.abs(return_error).mean()),
        "return_rmse_pct": float(np.sqrt((return_error ** 2).mean())),
        "terminal_return_mae_pct": float(np.abs(return_error[:, -1]).mean()),
        "directional_accuracy": float(signs.mean()),
        "terminal_directional_accuracy": float(signs[:, -1].mean()),
        "brier_score": None, "terminal_brier_score": None,
        "coverage80": None, "mean_interval_width": None,
        "pinball_q10": None, "pinball_q50": None, "pinball_q90": None,
        "mean_pinball_loss": None,
    }
    if baseline:
        result["neutral_probability_brier"] = .25
        return result
    prefix = "calibrated" if calibrated else "raw"
    lower = np.asarray([w[f"{prefix}_lower"] for w in windows], dtype=float)
    upper = np.asarray([w[f"{prefix}_upper"] for w in windows], dtype=float)
    median = np.asarray([w["median_close"] for w in windows], dtype=float)
    pinballs = [_pinball(actual, lower, .1), _pinball(actual, median, .5), _pinball(actual, upper, .9)]
    result.update(coverage80=float(((actual >= lower) & (actual <= upper)).mean()),
                  mean_interval_width=float((upper - lower).mean()),
                  pinball_q10=pinballs[0], pinball_q50=pinballs[1], pinball_q90=pinballs[2],
                  mean_pinball_loss=float(np.mean(pinballs)))
    if all("p_up_by_horizon" in w for w in windows):
        probability = np.asarray([w["p_up_by_horizon"] for w in windows], dtype=float)
        brier = (probability - (actual > anchors)) ** 2
        result.update(brier_score=float(brier.mean()), terminal_brier_score=float(brier[:, -1].mean()))
    return result


def model_part(window):
    keys = ("forecast_close", "median_close", "raw_lower", "raw_upper", "calibrated_lower",
            "calibrated_upper", "p_up_by_horizon")
    return {key: window[key] for key in keys if key in window}


def strategy_reports(paired, frame, fee_bps=10., slippage_bps=5.):
    fee, slip = fee_bps / 10000, slippage_bps / 10000
    friction = ((1 + slip) * (1 + fee)) / ((1 - slip) * (1 - fee)) - 1
    definitions = {
        "kronos_positive": "LONG iff Kronos sample-mean terminal return from last observed close > 0",
        "chronos2_positive": "LONG iff Chronos median terminal return from last observed close > 0",
        "kronos_cost_filter": "LONG iff Kronos sample-mean terminal return exceeds the fixed friction threshold",
        "chronos2_cost_filter": "LONG iff Chronos median terminal return exceeds the fixed friction threshold",
        "consensus_cost_filter": "LONG iff both model terminal returns exceed the fixed friction threshold",
        "momentum_12h": "LONG iff last observed close / close twelve bars earlier - 1 > 0",
        "persistence_cash": "Always FLAT; persistence forecasts exactly the observed close",
        "buy_hold": "One LONG from first test candle OPEN through final test candle CLOSE",
    }
    tests = [w for w in paired if w["split"] == "test"]
    reports = {}
    for name in definitions:
        windows = []
        for w in tests:
            anchor, origin = w["last_close"], w["origin_index"]
            kronos_return = w["kronos"]["forecast_close"][-1] / anchor - 1
            chronos_return = w["chronos2"]["forecast_close"][-1] / anchor - 1
            momentum_return = float(frame["close"].iloc[origin - 1] / frame["close"].iloc[origin - 13] - 1)
            active = {
                "kronos_positive": kronos_return > 0,
                "chronos2_positive": chronos_return > 0,
                "kronos_cost_filter": kronos_return > friction,
                "chronos2_cost_filter": chronos_return > friction,
                "consensus_cost_filter": kronos_return > friction and chronos_return > friction,
                "momentum_12h": momentum_return > 0,
                "persistence_cash": False, "buy_hold": True,
            }[name]
            # Synthetic strategy markers encode a predeclared LONG/FLAT action;
            # these are not asserted to be additional model forecasts.
            forecast = [anchor * (1 + 1e-6 if active else 1)] * len(w["actual_close"])
            windows.append({"origin_index": origin, "split": "test", "timestamps": w["timestamps"],
                            "last_close": anchor, "actual_close": w["actual_close"],
                            "forecast_close": forecast})
        if name == "buy_hold":
            windows = [{**windows[0], "timestamps": [t for w in windows for t in w["timestamps"]],
                        "actual_close": [v for w in windows for v in w["actual_close"]],
                        "forecast_close": [windows[0]["last_close"] * (1 + 1e-6)] * sum(len(w["actual_close"]) for w in windows)}]
        report = paper_backtest({"per_window": windows}, frame, fee_bps=fee_bps, slippage_bps=slippage_bps)
        source_windows = {w["origin_index"]: w for w in tests}
        for ledger in report["per_window"]:
            w = source_windows[ledger["origin_index"]]
            origin, anchor = w["origin_index"], w["last_close"]
            bases = {"kronos_sample_mean_return": w["kronos"]["forecast_close"][-1] / anchor - 1,
                     "chronos2_median_return": w["chronos2"]["forecast_close"][-1] / anchor - 1,
                     "historical_12h_return": float(frame["close"].iloc[origin - 1] / frame["close"].iloc[origin - 13] - 1),
                     "friction_threshold": friction}
            ledger["internal_action_marker_return"] = ledger.pop("forecast_terminal_return")
            ledger["signal_basis"] = bases
            ledger["model_return_statistic"] = "Kronos sample mean / Chronos median; historical momentum has no model forecast"
        trades = [w for w in report["per_window"] if w["signal"] == "LONG"]
        report["traded_win_rate"] = float(np.mean([w["net_return"] > 0 for w in trades])) if trades else None
        report["strategy"] = name
        report["strategy_definition"] = definitions[name]
        report["assumptions"]["signal"] = definitions[name]
        report["assumptions"]["marker_forecasts"] = "Internal positive/flat markers pass predeclared actions to shared accounting; not model forecasts"
        report["assumptions"]["latency"] = "Idealized zero inference/decision latency at next candle open"
        report["assumptions"]["evaluation_origins"] = len(tests)
        report["assumptions"]["buy_hold_comparison"] = "One continuous trade spans the same 40-origin test interval" if name == "buy_hold" else None
        reports[name] = report
    return {"schema_version": 1,
            "settings": {"fee_bps_per_side": fee_bps, "slippage_bps_per_side": slippage_bps,
                         "friction_threshold_fraction": friction,
                         "friction_threshold_pct": friction * 100,
                         "threshold_anchor": "Last observed close; next candle open is unknown at decision time",
                         "test_windows": len(tests), "shorting_allowed": False,
                         "selection": "Fixed before model evaluation; no thresholds fitted to test outcomes",
                         "latency": "Idealized zero decision/inference latency at next candle open",
                         "signal_statistics": {"kronos": "sample mean", "chronos2": "median"}},
            "definitions": definitions,
            "comparison": [{"strategy": name, **r["summary"], "traded_win_rate": r["traded_win_rate"]}
                           for name, r in reports.items()], "strategies": reports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "output/visual-run-20261025")
    parser.add_argument("--device", default="cuda:1")
    parser.add_argument("--chronos-device", default="cpu")
    parser.add_argument("--windows", type=int, default=60)
    parser.add_argument("--calibration-windows", type=int, default=20)
    args = parser.parse_args()
    assert 0 < args.calibration_windows < args.windows
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cfg = ForecastConfig(lookback=128, horizon=12, sample_count=20, seed=42)
    protocol = {"schema_version": 1, "symbol": "BTCUSDT", "interval": "1h", "download_limit": 1000,
                "forecast": asdict(cfg), "stride": cfg.horizon,
                "selected_windows": args.windows, "calibration_windows": args.calibration_windows,
                "test_windows": args.windows - args.calibration_windows,
                "model_revision": MODEL_REVISION, "tokenizer_revision": TOKENIZER_REVISION,
                "chronos2_revision": CHRONOS_REVISION,
                "point_methods": {"kronos": "Monte Carlo sample mean; sample median also scored for paired location comparison",
                                  "chronos2": "Native predictions column equals median q0.5, not a predictive mean",
                                  "primary_location_comparison": "Kronos sample median versus Chronos median"},
                "strategy_policy": "Fixed zero/cost-threshold/consensus LONG-FLAT; 12h momentum; cash; one-trade buy-hold",
                "fee_bps_per_side": 10, "slippage_bps_per_side": 5,
                "devices": {"kronos": args.device, "chronos2": args.chronos_device}}
    protocol_path = output / "protocol.json"
    if protocol_path.exists():
        assert load_json(protocol_path) == protocol, "Existing run protocol differs; choose a new output directory"
    else:
        save_evaluation(protocol, protocol_path)
    data_path, meta_path = output / "BTCUSDT_1h.csv", output / "data-provenance.json"
    if data_path.exists():
        frame = load_csv(data_path)
        meta = load_json(meta_path)
        frame.attrs.update(meta["provider_metadata"])
        assert hashlib.sha256(data_path.read_bytes()).hexdigest() == meta["csv_sha256"]
        emit("saved_snapshot_loaded", rows=len(frame), sha256=meta["csv_sha256"])
    else:
        frame = fetch_binance("BTCUSDT", "1h", limit=1000)
        frame.to_csv(data_path, index=False)
        meta = {"downloaded_at_utc": datetime.now(timezone.utc).isoformat(), "rows": len(frame),
                "first_open_timestamp": frame["timestamps"].iloc[0].isoformat(),
                "last_open_timestamp": frame["timestamps"].iloc[-1].isoformat(),
                "csv_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
                "provider_metadata": dict(frame.attrs)}
        save_evaluation(meta, meta_path)
        emit("download_completed", **meta)
    import torch
    torch.set_num_threads(min(8, torch.get_num_threads()))
    available = list(range(cfg.lookback, len(frame) - cfg.horizon + 1, cfg.horizon))
    assert len(available) >= args.windows, "Insufficient closed candles for the registered window count"
    selected = available[-args.windows:]
    engine = CachedForecaster(KronosForecaster(upstream_dir=ROOT / "vendor/Kronos",
                             model_revision=MODEL_REVISION, tokenizer_revision=TOKENIZER_REVISION,
                             device=args.device), output)
    eval_path = output / "evaluation.json"
    if eval_path.exists():
        report = load_json(eval_path)
        assert report["settings"]["forecast"] == asdict(cfg)
        assert [w["origin_index"] for w in report["per_window"]] == selected
        emit("kronos_evaluation_cached")
    else:
        report = walk_forward(frame, engine, cfg, stride=cfg.horizon, max_windows=args.windows,
                              calibration_fraction=args.calibration_windows / args.windows)
        save_evaluation(report, eval_path)
    save_evaluation(report["final_forecast"], output / "forecast.json")
    paired, chronos_windows = [], []
    for count, w in enumerate(report["per_window"], 1):
        origin = w["origin_index"]
        history = frame.iloc[origin - cfg.lookback:origin].copy().reset_index(drop=True)
        key = stamp_key(history["timestamps"].iloc[-1])
        native_kronos = engine.results.get(key) or load_json(output / "native" / f"kronos-{key}.json")
        cache = output / "native" / f"comparison-{key}.json"
        if cache.exists():
            comparison = load_json(cache)
            emit("chronos_cached", origin=origin, completed=count, total=args.windows)
        else:
            started = time.monotonic()
            comparison = compare_chronos(history, native_kronos, device=args.chronos_device,
                                         revision=CHRONOS_REVISION)
            save_evaluation(comparison, cache)
            emit("chronos_completed", origin=origin, completed=count, total=args.windows,
                 seconds=time.monotonic() - started)
        c = comparison["chronos2"]
        c["metadata"]["point_statistic"] = "median q0.5"
        c["metadata"]["expected_return_pct_alias"] = "Median point return; preserved dashboard-compatible field name, not predictive mean"
        assert c["metadata"]["revision"] == CHRONOS_REVISION
        assert c["timestamps"] == w["timestamps"]
        cw = {key: w[key] for key in ("origin_index", "history_end", "timestamps", "last_close", "actual_close", "split")}
        cw.update(forecast_close=c["close"], median_close=c["quantiles"]["q50"],
                  raw_lower=c["quantiles"]["q10"], raw_upper=c["quantiles"]["q90"])
        lower, median, upper = (np.asarray(c["quantiles"][q]) for q in ("q10", "q50", "q90"))
        assert lower.shape == median.shape == upper.shape == (cfg.horizon,)
        assert np.isfinite(np.concatenate([lower, median, upper, c["close"]])).all()
        assert np.all(lower <= median) and np.all(median <= upper)
        chronos_windows.append(cw)
        paired.append({**{key: w[key] for key in ("origin_index", "split", "timestamps", "history_end", "last_close", "actual_close")},
                       "kronos": model_part(w), "chronos2": cw,
                       "native_outputs": {"kronos": native_kronos, "chronos2": c}})
    calibration_windows = [w for w in chronos_windows if w["split"] == "calibration"]
    calibration = _fit_expansion([{key: np.asarray(value) if key in {"actual_close", "raw_lower", "raw_upper"} else value
                                  for key, value in w.items()} for w in calibration_windows])
    expansion = np.asarray(calibration["expansion_by_horizon"])
    for pair, w in zip(paired, chronos_windows):
        w["calibrated_lower"] = np.asarray(w["raw_lower"]) - expansion
        w["calibrated_upper"] = np.asarray(w["raw_upper"]) + expansion
        pair["chronos2"] = model_part(w)
    test_chronos = [w for w in chronos_windows if w["split"] == "test"]
    test_kronos = [w for w in report["per_window"] if w["split"] == "test"]
    chronos_report = {"schema_version": 1, "settings": report["settings"],
                      "provenance": {**report["provenance"], "point_forecast": "Native Chronos median q0.5",
                                     "probabilities": "Unavailable; no probabilities inferred from three quantiles"},
                      "split": report["split"], "calibration": calibration,
                      "metrics": {"baseline": report["metrics"]["baseline"],
                                  "model_raw": native_metrics(test_chronos),
                                  "model_calibrated": native_metrics(test_chronos, calibrated=True)},
                      "per_window": chronos_windows}
    save_evaluation(chronos_report, output / "chronos-evaluation.json")
    # Independent native scoring must agree with the existing dashboard scorer.
    for mode, opts in [("model_raw", {}), ("model_calibrated", {"calibrated": True})]:
        calculated = native_metrics(test_kronos, **opts)
        for key, value in calculated.items():
            if value is not None:
                assert np.isclose(value, report["metrics"][mode][key], rtol=1e-11, atol=1e-10), key
    paired_report = {"schema_version": 1, "settings": report["settings"], "provenance": report["provenance"],
                     "split": report["split"], "model_methods": protocol["point_methods"],
                     "calibration": {"kronos": report["calibration"], "chronos2": calibration},
                     "metrics": {"persistence": report["metrics"]["baseline"],
                                 "kronos": {"raw": report["metrics"]["model_raw"], "calibrated": report["metrics"]["model_calibrated"]},
                                 "chronos2": {"raw": native_metrics(test_chronos), "calibrated": native_metrics(test_chronos, calibrated=True)}},
                     "point_metrics": {"kronos_sample_mean": native_metrics(test_kronos),
                                       "kronos_sample_median": native_metrics(test_kronos, median_point=True),
                                       "chronos2_median": native_metrics(test_chronos, median_point=True)},
                     "per_window": paired,
                     "limitations": ["One asset and short recent period; 40 origins are temporally dependent",
                                     "Chronos uses native point and quantile outputs; no paths or p_up are fabricated",
                                     "Kronos Brier uses raw empirical sample frequencies; interval expansion does not calibrate votes",
                                     "Chronos close+past-volume covariates differ from Kronos OHLCVA inputs",
                                     "Model pretraining data was not independently audited",
                                     "Paper strategies/thresholds fixed before evaluation; observed winner is not evidence of general dominance"]}
    save_evaluation(paired_report, output / "paired-evaluation.json")
    strategies = strategy_reports(paired, frame)
    save_evaluation(strategies, output / "strategy-summary.json")
    latest_key = stamp_key(frame["timestamps"].iloc[-1])
    latest_path = output / "native" / f"comparison-{latest_key}.json"
    if latest_path.exists():
        latest = load_json(latest_path)
    else:
        latest = compare_chronos(frame, report["final_forecast"], device=args.chronos_device, revision=CHRONOS_REVISION)
        save_evaluation(latest, latest_path)
    latest["chronos2"]["metadata"]["point_statistic"] = "median q0.5"
    latest["chronos2"]["metadata"]["expected_return_pct_alias"] = "Median point return; preserved dashboard-compatible field name, not predictive mean"
    save_evaluation(latest, output / "comparison.json")
    anchor = latest["kronos"]["summary"]["last_close"]
    kronos_return = latest["kronos"]["summary"]["expected_return_pct"] / 100
    chronos_return = latest["chronos2"]["expected_return_pct"] / 100
    threshold = strategies["settings"]["friction_threshold_fraction"]
    signal = {"issued_at_utc": latest["kronos"]["metadata"]["issued_at_utc"], "last_observed_close": anchor,
              "forecast_timestamps": latest["kronos"]["timestamps"],
              "kronos": {"point_statistic": "Monte Carlo sample mean", "terminal_return_pct": kronos_return * 100, "raw_terminal_q10": latest["kronos"]["quantiles"]["q10"][-1],
                         "raw_terminal_q90": latest["kronos"]["quantiles"]["q90"][-1],
                         "expanded_terminal_q10": latest["kronos"]["calibrated_quantiles"]["q10"][-1],
                         "expanded_terminal_q90": latest["kronos"]["calibrated_quantiles"]["q90"][-1],
                         "p_up": latest["kronos"]["summary"]["p_up"],
                         "vote_semantics": "Raw terminal Monte Carlo frequency, not calibrated correctness",
                         "positive_action": "LONG" if kronos_return > 0 else "FLAT",
                         "cost_filtered_action": "LONG" if kronos_return > threshold else "FLAT"},
              "chronos2": {"point_statistic": "median q0.5, not predictive mean", "terminal_return_pct": chronos_return * 100,
                           "raw_terminal_q10": latest["chronos2"]["quantiles"]["q10"][-1],
                           "raw_terminal_q90": latest["chronos2"]["quantiles"]["q90"][-1],
                           "expanded_terminal_q10": latest["chronos2"]["quantiles"]["q10"][-1] - expansion[-1],
                           "expanded_terminal_q90": latest["chronos2"]["quantiles"]["q90"][-1] + expansion[-1],
                           "p_up": None, "positive_action": "LONG" if chronos_return > 0 else "FLAT",
                           "cost_filtered_action": "LONG" if chronos_return > threshold else "FLAT"},
              "friction_threshold_pct": threshold * 100,
              "consensus_cost_filtered_action": "LONG" if min(kronos_return, chronos_return) > threshold else "FLAT",
              "action_semantics": "Local research LONG/FLAT policy; FLAT means cash or exit, no short position",
              "interval_semantics": "Frozen earlier per-model expansion; no future coverage guarantee"}
    save_evaluation(signal, output / "latest-signal.json")
    import torch
    manifest = {"schema_version": 1, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "data": meta, "protocol": protocol, "split": report["split"],
                "origins": selected, "calibration_origins": selected[:args.calibration_windows],
                "test_origins": selected[args.calibration_windows:],
                "environment": {"python": sys.version, "torch": torch.__version__,
                                "numpy": np.__version__, "pandas": pd.__version__,
                                "gpu": torch.cuda.get_device_name(torch.device(args.device)) if args.device.startswith("cuda") else None},
                "metrics": paired_report["metrics"], "point_metrics": paired_report["point_metrics"],
                "strategy_comparison": strategies["comparison"],
                "latest_signal": signal,
                "validation": {"paired_origins_and_labels_match": True, "chronos_probabilities_fabricated": False,
                               "native_quantiles_finite_ordered": True, "kronos_score_independent_recomputation": True,
                               "calibration_frozen_before_test_scoring": True, "no_order_api_used": True,
                               "retained_kronos_native_forecasts": len(paired) + 1,
                               "invalid_generated_candles_all_origins_and_latest": sum(
                                   w["native_outputs"]["kronos"]["metadata"]["invalid_generated_candle_count"] for w in paired)
                                   + latest["kronos"]["metadata"]["invalid_generated_candle_count"]}}
    save_evaluation(manifest, output / "run-manifest.json")
    emit("run_completed", output_dir=str(output), metrics=paired_report["metrics"], strategies=strategies["comparison"], latest=signal)


if __name__ == "__main__":
    main()
