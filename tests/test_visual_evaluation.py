"""Audit native forecasts, frozen economic rules and paired uncertainty."""
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from kronos_lab.evaluation import walk_forward
from kronos_lab.forecast import ForecastConfig
from scripts.run_visual_evaluation import native_metrics, strategy_reports
from scripts.summarize_paired_uncertainty import summarize


def flat_candles(count=60):
    return pd.DataFrame({
        "timestamps": pd.date_range("2026-01-01", periods=count, freq="h", tz="UTC"),
        "open": np.full(count, 100.), "high": np.full(count, 101.),
        "low": np.full(count, 99.), "close": np.full(count, 100.),
        "volume": np.full(count, 10.), "amount": np.full(count, 1000.),
    })


def pair(frame, origin, kronos_return, chronos_return, *, horizon=12, split="test"):
    anchor = float(frame.close.iloc[origin - 1])
    return {"origin_index": origin, "split": split, "last_close": anchor,
            "timestamps": [t.isoformat() for t in frame.timestamps.iloc[origin:origin + horizon]],
            "actual_close": frame.close.iloc[origin:origin + horizon].tolist(),
            "kronos": {"forecast_close": [anchor * (1 + kronos_return)] * horizon},
            "chronos2": {"forecast_close": [anchor * (1 + chronos_return)] * horizon}}


def test_native_median_point_and_probabilities_keep_their_distinct_meaning():
    window = {"last_close": 100., "actual_close": [100., 104.],
              "forecast_close": [110., 120.], "median_close": [100., 104.],
              "raw_lower": [99., 103.], "raw_upper": [101., 105.],
              "calibrated_lower": [98., 102.], "calibrated_upper": [102., 106.]}
    native = native_metrics([window])
    median = native_metrics([window], median_point=True)
    assert native["close_mae"] == 13
    assert median["close_mae"] == median["close_rmse"] == 0
    assert native["brier_score"] is None  # Native quantiles do not supply up probabilities.
    assert median["coverage80"] == 1
    assert median["mean_interval_width"] == 2
    window["p_up_by_horizon"] = [.2, .8]
    expanded = native_metrics([window], calibrated=True)
    assert expanded["mean_interval_width"] == 4
    assert expanded["brier_score"] == pytest.approx(.04)
    assert expanded["brier_score"] == native_metrics([window])["brier_score"]


def test_frozen_cost_gate_cash_winrate_and_single_roundtrip_buy_hold():
    frame = flat_candles()
    friction = (1.0005 * 1.001) / (.9995 * .999) - 1
    pairs = [pair(frame, 24, friction * .9, friction * 1.1),
             pair(frame, 36, friction * 1.1, -.01),
             pair(frame, 12, 10., 10., split="calibration")]
    result = strategy_reports(pairs, frame)
    strategies = result["strategies"]
    assert result["settings"]["test_windows"] == 2
    assert result["settings"]["friction_threshold_fraction"] == pytest.approx(friction)
    assert strategies["kronos_positive"]["summary"]["trade_count"] == 2
    assert strategies["kronos_cost_filter"]["summary"]["trade_count"] == 1
    assert strategies["chronos2_cost_filter"]["summary"]["trade_count"] == 1
    assert strategies["consensus_cost_filter"]["summary"]["trade_count"] == 0
    assert strategies["persistence_cash"]["traded_win_rate"] is None
    assert strategies["persistence_cash"]["summary"]["final_equity"] == 1
    assert strategies["kronos_cost_filter"]["traded_win_rate"] == 0  # Flat prices lose the roundtrip friction.
    hold = strategies["buy_hold"]
    assert hold["summary"]["trade_count"] == 1
    assert len(hold["per_window"]) == 1
    assert hold["per_window"][0]["origin_index"] == 24
    assert hold["per_window"][0]["exit_index"] == 47
    one_roundtrip = (.9995 * .999) / (1.0005 * 1.001)
    assert hold["summary"]["final_equity"] == pytest.approx(one_roundtrip)
    assert strategies["kronos_positive"]["summary"]["final_equity"] == pytest.approx(one_roundtrip ** 2)
    assert hold["summary"]["fees_paid"] == pytest.approx(sum(
        w["entry_fee"] + w["exit_fee"] for w in hold["per_window"]))
    assert hold["summary"]["max_drawdown"] == pytest.approx(1 - one_roundtrip)


def test_future_outcomes_change_returns_and_winrate_without_changing_any_signal():
    frame = flat_candles()
    original = pair(frame, 24, .01, -.01)
    first = strategy_reports([original], frame)
    changed = frame.copy()
    changed.loc[24:, ["open", "high", "low", "close", "amount"]] *= 1.1
    # Entry is deliberately left unchanged while later closes move.
    changed.loc[24, ["open", "low"]] = [100., 99.]
    frozen = deepcopy(original)
    frozen["actual_close"] = changed.close.iloc[24:36].tolist()
    second = strategy_reports([frozen], changed)
    for name in first["strategies"]:
        before, after = first["strategies"][name], second["strategies"][name]
        assert [w["signal"] for w in before["per_window"]] == [w["signal"] for w in after["per_window"]]
    assert first["strategies"]["kronos_positive"]["traded_win_rate"] == 0
    assert second["strategies"]["kronos_positive"]["traded_win_rate"] == 1


def test_registered_recent_origins_are_twenty_calibration_and_forty_disjoint_test():
    frame = flat_candles(999)
    config = ForecastConfig(lookback=128, horizon=12, sample_count=20, seed=42)

    class SpyForecaster:
        def __init__(self):
            self.calls = []

        def forecast(self, history, *, future_timestamps, config):
            self.calls.append((history.copy(), list(future_timestamps)))
            point = np.full((config.horizon, 6), float(history.close.iloc[-1]))
            return {"mean": point, "quantiles": {"q10": point[:, 3] - 1,
                    "q50": point[:, 3], "q90": point[:, 3] + 1},
                    "trajectories": np.repeat(point[None], config.sample_count, axis=0)}

    spy = SpyForecaster()
    report = walk_forward(frame, spy, config, stride=12, max_windows=60, calibration_fraction=20 / 60)
    calibration = [w for w in report["per_window"] if w["split"] == "calibration"]
    tests = [w for w in report["per_window"] if w["split"] == "test"]
    assert [w["origin_index"] for w in calibration] == list(range(272, 512, 12))
    assert [w["origin_index"] for w in tests] == list(range(512, 992, 12))
    assert report["split"]["label_sets_disjoint"]
    assert not report["split"]["overlap_within_split"]
    assert report["calibration"]["calibration_windows"] == 20
    assert report["metrics"]["model_raw"]["observations"] == 480
    assert len(spy.calls) == 61
    for (history, future), window in zip(spy.calls, report["per_window"]):
        origin = window["origin_index"]
        pd.testing.assert_frame_equal(history, frame.iloc[origin - 128:origin].reset_index(drop=True))
        assert history.timestamps.max() < min(future)


def uncertainty_report(count=8):
    return {"per_window": [
        {"split": "test", "origin_index": 128 + 12 * i, "last_close": 100.,
         "actual_close": [100., 100.], "kronos": {"median_close": [101., 101.]},
         "chronos2": {"median_close": [102., 102.]}}
        for i in range(count)
    ]}


def test_paired_uncertainty_keeps_constant_within_origin_error_difference():
    report = uncertainty_report()
    result = summarize(report, block_length=4, repetitions=2000, seed=42)
    primary = result["comparisons"]["kronos_median_minus_chronos_median"]
    assert primary["observed_mean_mae_difference"] == -1
    assert primary["bootstrap_95_percentile_interval"] == [-1, -1]
    assert result == summarize(report, block_length=4, repetitions=2000, seed=42)
    assert result["settings"]["test_origins"] == 8


def test_uncertainty_rejects_duplicate_origins_and_misaligned_horizons():
    duplicated = uncertainty_report()
    duplicated["per_window"][1]["origin_index"] = duplicated["per_window"][0]["origin_index"]
    with pytest.raises(ValueError, match="unique"):
        summarize(duplicated)
    misaligned = uncertainty_report()
    misaligned["per_window"][0]["chronos2"]["median_close"] = [102.]
    with pytest.raises(ValueError, match="aligned"):
        summarize(misaligned)
