"""Chronological forecast evaluation with a frozen, earlier calibration split.

This module scores forecasts, not trading performance. Held-out OHLCVA values
never enter the forecaster. Quantile expansion is fitted on earlier calibration
windows, then frozen before any test window is scored.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


_NOMINAL_COVERAGE = 0.8
_CLOSE_INDEX = 3


def _json_value(value: Any) -> Any:
    """Convert model/numpy/pandas output into strict JSON-compatible values."""
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    if isinstance(value, np.ndarray):
        return _json_value(value.tolist())
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Evaluation output contains a non-finite number")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Cannot serialize evaluation value of type {type(value).__name__}")


def _positive_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _config_dict(config: Any) -> dict:
    if is_dataclass(config):
        return asdict(config)
    # Only forecast settings are recorded: avoid serializing arbitrary objects.
    return {
        key: getattr(config, key)
        for key in (
            "lookback", "horizon", "sample_count", "temperature", "top_p",
            "top_k", "seed", "max_context",
        )
        if hasattr(config, key)
    }


def _finite_array(value: Any, shape: tuple[int, ...], name: str) -> np.ndarray:
    result = np.asarray(value, dtype=np.float64)
    if result.shape != shape or not np.isfinite(result).all():
        raise ValueError(f"{name} must have shape {shape} and contain finite values")
    return result


def _forecast_window(frame: pd.DataFrame, origin: int, forecaster: Any, config: Any) -> dict:
    horizon, lookback = int(config.horizon), int(config.lookback)
    # The first unknown row is `origin`; the model only gets preceding prices.
    history = frame.iloc[origin - lookback:origin].copy().reset_index(drop=True)
    future_times = frame.iloc[origin:origin + horizon]["timestamps"].copy().reset_index(drop=True)
    result = forecaster.forecast(history, future_timestamps=future_times, config=config)
    if "timestamps" in result:
        returned_times = pd.DatetimeIndex(pd.to_datetime(result["timestamps"], utc=True))
        if not np.array_equal(returned_times.asi8, pd.DatetimeIndex(future_times).asi8):
            raise ValueError("Forecaster timestamps do not match the held-out timestamps")
    mean = _finite_array(result["mean"], (horizon, 6), "Forecast mean")[:, _CLOSE_INDEX]
    quantiles = result["quantiles"]
    lower = _finite_array(quantiles["q10"], (horizon,), "q10")
    median = _finite_array(quantiles["q50"], (horizon,), "q50")
    upper = _finite_array(quantiles["q90"], (horizon,), "q90")
    if np.any(lower > median) or np.any(median > upper):
        raise ValueError("Forecast quantiles must satisfy q10 <= q50 <= q90")
    samples = np.asarray(result["trajectories"], dtype=np.float64)
    if (samples.ndim != 3 or samples.shape[0] < 1 or samples.shape[1:] != (horizon, 6)
            or not np.isfinite(samples).all()):
        raise ValueError("Forecast trajectories must have finite shape (samples, horizon, 6)")
    last_close = float(history["close"].iloc[-1])
    actual = frame.iloc[origin:origin + horizon]["close"].to_numpy(dtype=np.float64)
    return {
        "origin_index": origin,
        "history_end": history["timestamps"].iloc[-1],
        "timestamps": future_times.tolist(),
        "last_close": last_close,
        "actual_close": actual,
        "forecast_close": mean,
        "median_close": median,
        "raw_lower": lower,
        "raw_upper": upper,
        "p_up_by_horizon": np.mean(samples[:, :, _CLOSE_INDEX] > last_close, axis=0),
        "actual_up_by_horizon": actual > last_close,
        "metadata": result.get("metadata", {}),
    }


def _fit_expansion(windows: list[dict]) -> dict:
    """Fit nonnegative additive split-conformal scores separately per horizon.

    Finite-sample order-statistic rank is ceil((n+1)*0.8). With very few
    calibration windows that rank may exceed n; the largest observed score is
    then used and explicitly reported as a capped exploratory estimate. Time
    dependence also prevents claiming an exchangeability-based guarantee.
    """
    scores = np.stack([
        np.maximum.reduce((w["raw_lower"] - w["actual_close"],
                           w["actual_close"] - w["raw_upper"],
                           np.zeros_like(w["actual_close"])))
        for w in windows
    ])
    n = len(windows)
    requested_rank = int(math.ceil((n + 1) * _NOMINAL_COVERAGE))
    rank = min(n, requested_rank)
    expansion = np.sort(scores, axis=0)[rank - 1]
    return {
        "method": "nonnegative_additive_split_conformal_per_horizon",
        "nominal_coverage": _NOMINAL_COVERAGE,
        "expansion_by_horizon": expansion,
        "calibration_windows": n,
        "requested_order_statistic_rank": requested_rank,
        "used_order_statistic_rank": rank,
        "rank_capped_for_small_sample": requested_rank > n,
        "frozen_before_test": True,
        "coverage_guarantee_claimed": False,
        "interpretation": (
            "Empirical chronological calibration only. Serial dependence and small "
            "samples can invalidate nominal coverage; inspect held-out test coverage."
        ),
    }


def _pinball(actual: np.ndarray, predicted: np.ndarray, quantile: float) -> float:
    error = actual - predicted
    return float(np.mean(np.maximum(quantile * error, (quantile - 1) * error)))


def _metrics(windows: list[dict], *, baseline: bool = False, calibrated: bool = False) -> dict:
    actual = np.stack([w["actual_close"] for w in windows])
    anchors = np.asarray([w["last_close"] for w in windows])[:, None]
    predicted = np.broadcast_to(anchors, actual.shape) if baseline else np.stack(
        [w["forecast_close"] for w in windows]
    )
    errors = predicted - actual
    actual_return = (actual / anchors - 1) * 100
    predicted_return = (predicted / anchors - 1) * 100
    return_errors = predicted_return - actual_return
    actual_direction = np.sign(actual - anchors)
    predicted_direction = np.sign(predicted - anchors)
    output = {
        "windows": len(windows),
        "observations": int(actual.size),
        "horizon": int(actual.shape[1]),
        "close_mae": float(np.mean(np.abs(errors))),
        "close_rmse": float(np.sqrt(np.mean(errors ** 2))),
        "return_mae_pct": float(np.mean(np.abs(return_errors))),
        "return_rmse_pct": float(np.sqrt(np.mean(return_errors ** 2))),
        "terminal_return_mae_pct": float(np.mean(np.abs(return_errors[:, -1]))),
        "directional_accuracy": float(np.mean(predicted_direction == actual_direction)),
        "terminal_directional_accuracy": float(np.mean(
            predicted_direction[:, -1] == actual_direction[:, -1]
        )),
    }
    if baseline:
        output.update({
            "brier_score": None,
            "terminal_brier_score": None,
            "coverage80": None,
            "mean_interval_width": None,
            "pinball_q10": None,
            "pinball_q50": None,
            "pinball_q90": None,
            "mean_pinball_loss": None,
            "neutral_probability_brier": 0.25,
            "probability_note": (
                "Last-close persistence supplies a point forecast only; the separate "
                "neutral 0.5 up-probability benchmark has Brier score 0.25."
            ),
        })
        return output
    prefix = "calibrated" if calibrated else "raw"
    lower = np.stack([w[f"{prefix}_lower"] for w in windows])
    upper = np.stack([w[f"{prefix}_upper"] for w in windows])
    median = np.stack([w["median_close"] for w in windows])
    probabilities = np.stack([w["p_up_by_horizon"] for w in windows])
    binary_up = actual > anchors
    brier = (probabilities - binary_up) ** 2
    q10, q50, q90 = (_pinball(actual, lower, .1), _pinball(actual, median, .5),
                       _pinball(actual, upper, .9))
    output.update({
        "brier_score": float(np.mean(brier)),
        "terminal_brier_score": float(np.mean(brier[:, -1])),
        "coverage80": float(np.mean((actual >= lower) & (actual <= upper))),
        "mean_interval_width": float(np.mean(upper - lower)),
        "pinball_q10": q10,
        "pinball_q50": q50,
        "pinball_q90": q90,
        "mean_pinball_loss": float(np.mean([q10, q50, q90])),
    })
    return output


def _future_times(frame: pd.DataFrame, horizon: int) -> tuple[pd.Series | None, str]:
    from .forecast import future_index

    reason = (
        "Final forecast skipped: observed timestamps have no regular constant cadence "
        "or require an exchange calendar. Use forecast with explicit future "
        "exchange-session timestamps."
    )
    if frame.attrs.get("provider") in ("yfinance", "vnstock-v5"):
        return None, reason
    try:
        future = future_index(frame["timestamps"], horizon)
    except ValueError:
        return None, reason
    return pd.Series(future, name="timestamps"), "constant_observed_spacing"


def _split_boundaries(windows: list[dict]) -> dict:
    return {
        "windows": len(windows),
        "first_origin_index": windows[0]["origin_index"],
        "last_origin_index": windows[-1]["origin_index"],
        "first_label_timestamp": windows[0]["timestamps"][0],
        "last_label_timestamp": windows[-1]["timestamps"][-1],
    }


def walk_forward(
    frame: pd.DataFrame,
    forecaster: Any,
    config: Any,
    *,
    stride: int | None = None,
    max_windows: int | None = None,
    calibration_fraction: float = .5,
    evaluation_start: str | pd.Timestamp | None = None,
    calibration_end: str | pd.Timestamp | None = None,
) -> dict:
    """Evaluate disjoint chronological calibration/test labels and forecast next.

    `frame` uses the normal data schema (UTC timestamps and OHLCVA). Each
    prediction receives only the last `config.lookback` historical rows plus
    the future timestamps. The earliest selected windows fit calibration;
    the later test windows measure performance. If `stride < horizon`, windows
    crossing the calibration/test boundary are purged. Repeated labels within
    a split are identified, and metrics weight each origin/horizon observation.
    `evaluation_start` is an inclusive earliest label-start timestamp.
    `calibration_end`, when supplied, is an inclusive calibration label-end;
    test labels must start strictly later. Windows crossing it are purged.
    `max_windows` selects recent windows before a fraction split, or allocates
    that limit by `calibration_fraction` between timestamp-defined splits.

    The returned strict-JSON report includes test metrics, calibration details,
    per-window outcomes, provenance, and a final forecast using all available
    historical data. Its final interval uses the same frozen expansion.
    """
    from .data import normalize_frame

    lookback = _positive_integer(config.lookback, "lookback")
    horizon = _positive_integer(config.horizon, "horizon")
    stride = horizon if stride is None else _positive_integer(stride, "stride")
    if not isinstance(calibration_fraction, (int, float)) or not 0 < calibration_fraction < 1:
        raise ValueError("calibration_fraction must be strictly between 0 and 1")
    if max_windows is not None:
        max_windows = _positive_integer(max_windows, "max_windows")
        if max_windows < 2:
            raise ValueError("max_windows must allow at least one calibration and one test window")
    frame = normalize_frame(frame).reset_index(drop=True)
    if (frame["close"].to_numpy(dtype=float) <= 0).any():
        raise ValueError("close prices must be positive to evaluate returns")
    def parse_boundary(value: Any, name: str) -> pd.Timestamp | None:
        if value is None:
            return None
        try:
            parsed = pd.Timestamp(value)
            if pd.isna(parsed):
                raise ValueError("missing boundary")
            return parsed.tz_localize("UTC") if parsed.tzinfo is None else parsed.tz_convert("UTC")
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"{name} must be a valid timestamp") from exc

    evaluation_start = parse_boundary(evaluation_start, "evaluation_start")
    calibration_end = parse_boundary(calibration_end, "calibration_end")
    if evaluation_start is not None and calibration_end is not None and evaluation_start > calibration_end:
        raise ValueError("evaluation_start must not follow calibration_end")
    origins = list(range(lookback, len(frame) - horizon + 1, stride))
    if evaluation_start is not None:
        origins = [origin for origin in origins if frame["timestamps"].iloc[origin] >= evaluation_start]
    available_windows = len(origins)
    if len(origins) < 2:
        raise ValueError("Need at least two forecast windows for separate calibration and test sets")
    if calibration_end is not None:
        calibration_origins = [origin for origin in origins
                               if frame["timestamps"].iloc[origin + horizon - 1] <= calibration_end]
        test_origins = [origin for origin in origins
                        if frame["timestamps"].iloc[origin] > calibration_end]
        purged_origins = [origin for origin in origins
                          if frame["timestamps"].iloc[origin] <= calibration_end
                          < frame["timestamps"].iloc[origin + horizon - 1]]
        if max_windows is not None:
            calibration_budget = int(max_windows * calibration_fraction)
            if not 1 <= calibration_budget < max_windows:
                raise ValueError("calibration_fraction leaves an empty calibration or test budget")
            calibration_origins = calibration_origins[-calibration_budget:]
            test_origins = test_origins[-(max_windows - calibration_budget):]
        if not calibration_origins or not test_origins:
            raise ValueError("Timestamp boundaries leave an empty calibration or test split")
        selected_windows_before_purging = len(calibration_origins) + len(test_origins) + len(purged_origins)
    else:
        if max_windows is not None:
            origins = origins[-max_windows:]
        n_calibration = int(len(origins) * calibration_fraction)
        if not 1 <= n_calibration < len(origins):
            raise ValueError("calibration_fraction leaves an empty calibration or test split")
        calibration_origins = origins[:n_calibration]
        candidate_test_origins = origins[n_calibration:]
        # Do not permit a label timestamp used to fit calibration to enter test.
        calibration_label_end = calibration_origins[-1] + horizon - 1
        test_origins = [origin for origin in candidate_test_origins if origin > calibration_label_end]
        purged_origins = [origin for origin in candidate_test_origins if origin <= calibration_label_end]
        selected_windows_before_purging = len(origins)
        if not test_origins:
            raise ValueError(
                "No test windows remain after purging overlapping calibration labels; "
                "supply more data/windows or use stride >= horizon"
            )

    calibration_windows = [_forecast_window(frame, origin, forecaster, config)
                           for origin in calibration_origins]
    calibration = _fit_expansion(calibration_windows)
    expansion = calibration["expansion_by_horizon"]
    # Expansion is now frozen. Test targets never enter _fit_expansion.
    test_windows = [_forecast_window(frame, origin, forecaster, config) for origin in test_origins]
    for group, windows in (("calibration", calibration_windows), ("test", test_windows)):
        for window in windows:
            window["split"] = group
            window["calibrated_lower"] = window["raw_lower"] - expansion
            window["calibrated_upper"] = window["raw_upper"] + expansion
    metrics = {
        "baseline": _metrics(test_windows, baseline=True),
        "model_raw": _metrics(test_windows),
        "model_calibrated": _metrics(test_windows, calibrated=True),
    }
    future_times, future_method = _future_times(frame, horizon)
    final_forecast = None
    if future_times is not None:
        final_forecast = dict(forecaster.forecast(
            frame.iloc[-lookback:].copy().reset_index(drop=True),
            future_timestamps=future_times,
            config=config,
        ))
        final_lower = _finite_array(final_forecast["quantiles"]["q10"], (horizon,), "Final q10")
        final_upper = _finite_array(final_forecast["quantiles"]["q90"], (horizon,), "Final q90")
        final_forecast["calibrated_quantiles"] = {
            "q10": final_lower - expansion,
            "q50": final_forecast["quantiles"]["q50"],
            "q90": final_upper + expansion,
        }
        final_forecast["timestamp_provenance"] = future_method
        final_forecast["calibration_note"] = (
            "Uses the frozen historical calibration split. Sample paths and p_up remain "
            "raw; interval expansion is not probability calibration."
        )
    digest = hashlib.sha256(frame.to_csv(index=False).encode("utf-8")).hexdigest()
    all_windows = calibration_windows + test_windows
    warnings = []
    if len(calibration_windows) < 30 or len(test_windows) < 30:
        warnings.append(
            "Fewer than 30 windows in at least one split: exploratory results with "
            "substantial sampling uncertainty; no general performance claim."
        )
    if stride < horizon:
        warnings.append(
            "Windows overlap within each split; repeated timestamps are weighted once "
            "per forecast origin/horizon and observations are dependent."
        )
    if future_times is None:
        warnings.append(future_method)
    return _json_value({
        "schema_version": 1,
        "settings": {
            "forecast": _config_dict(config),
            "stride": stride,
            "max_windows": max_windows,
            "calibration_fraction": calibration_fraction,
            "evaluation_start": evaluation_start,
            "calibration_end": calibration_end,
            "split_method": "timestamp" if calibration_end is not None else "fraction",
            "nominal_coverage": _NOMINAL_COVERAGE,
        },
        "provenance": {
            "generated_at": datetime.now(timezone.utc),
            "data_sha256": digest,
            "data_rows": len(frame),
            "data_source": {key: frame.attrs[key] for key in (
                "provider", "symbol", "interval", "amount_source", "timezone"
            ) if key in frame.attrs},
            "data_first_timestamp": frame["timestamps"].iloc[0],
            "data_last_timestamp": frame["timestamps"].iloc[-1],
            "available_windows": available_windows,
            "selected_windows_before_purging": selected_windows_before_purging,
            "forecaster": calibration_windows[0]["metadata"],
            "point_forecast": "mean of generated close trajectories",
            "direction_definition": "sign(predicted close - last historical close); zero means flat",
            "up_event": "held-out close > last historical close at the same origin",
            "probabilities": "raw empirical sample frequencies; not calibrated probabilities",
            "return_unit": "percentage points relative to each origin's last historical close",
            "scoring": "test only; each forecast origin/horizon receives equal weight",
            "baseline": "last observed close repeated over the identical test origins/horizons",
            "profitability_evaluated": False,
        },
        "split": {
            "calibration": _split_boundaries(calibration_windows),
            "test": _split_boundaries(test_windows),
            "purged_origins": purged_origins,
            "label_sets_disjoint": True,
            "overlap_within_split": stride < horizon,
        },
        "calibration": calibration,
        "metrics": metrics,
        "calibration_metrics": {
            "baseline": _metrics(calibration_windows, baseline=True),
            "model_raw": _metrics(calibration_windows),
            "model_calibrated_in_sample": _metrics(calibration_windows, calibrated=True),
        },
        "per_window": all_windows,
        "final_forecast": final_forecast,
        "final_forecast_error": future_method if future_times is None else None,
        "warnings": warnings,
    })


def save_evaluation(report: dict, path: str | Path) -> Path:
    """Persist a report as strict JSON, without Python/numpy-specific encodings."""
    path = Path(path)
    body = json.dumps(_json_value(report), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path
