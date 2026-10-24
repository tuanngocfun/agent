"""Behavioral evaluation tests use a deterministic fake, without model downloads."""
from dataclasses import dataclass
from datetime import timedelta
import json

import numpy as np
import pandas as pd
import pytest

from kronos_lab.evaluation import save_evaluation, walk_forward


@dataclass
class Config:
    lookback: int = 4
    horizon: int = 2
    sample_count: int = 4
    seed: int = 7


def candles(n=20):
    close = np.arange(n, dtype=float) + 100
    return pd.DataFrame({
        "timestamps": pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC"),
        "open": close,
        "high": close + 2,
        "low": close - 2,
        "close": close,
        "volume": np.full(n, 10.),
        "amount": close * 10,
    })


class FakeForecaster:
    def __init__(self, *, trend=1., width=1., constant=None, sample_offsets=None):
        self.calls = []
        self.trend = trend
        self.width = width
        self.constant = constant
        self.sample_offsets = sample_offsets

    def forecast(self, history, *, future_timestamps, config):
        self.calls.append((history.copy(deep=True), future_timestamps.copy(deep=True)))
        point = (np.full(config.horizon, self.constant, dtype=float) if self.constant is not None
                 else history["close"].iloc[-1] + np.arange(1, config.horizon + 1) * self.trend)
        features = np.tile(point[:, None], (1, 6))
        offsets = (np.asarray(self.sample_offsets) if self.sample_offsets is not None
                   else np.linspace(-.5, .5, config.sample_count))
        trajectories = np.stack([features + offset for offset in offsets])
        return {
            "timestamps": future_timestamps.tolist(),
            "mean": features,
            "quantiles": {"q10": point - self.width, "q50": point, "q90": point + self.width},
            "trajectories": trajectories,
            "metadata": {"model_id": "deterministic-fake", "seed": config.seed},
            "summary": {"p_up": np.mean(trajectories[:, -1, 3] > history["close"].iloc[-1])},
        }


def test_forecaster_sees_history_only_and_reports_are_strict_json(tmp_path):
    frame = candles(20)
    forecaster = FakeForecaster()
    report = walk_forward(frame, forecaster, Config(), max_windows=6)
    windows = report["per_window"]
    assert len(windows) == 6
    assert len(forecaster.calls) == 7  # calibration + test + final forecast
    for (history, future), window in zip(forecaster.calls, windows):
        origin = window["origin_index"]
        pd.testing.assert_frame_equal(history, frame.iloc[origin - 4:origin].reset_index(drop=True))
        assert list(future) == list(frame.iloc[origin:origin + 2]["timestamps"])
        assert history["timestamps"].max() < future.min()
    pd.testing.assert_frame_equal(forecaster.calls[-1][0], frame.iloc[-4:].reset_index(drop=True))
    assert forecaster.calls[-1][1].min() > frame["timestamps"].max()
    json.dumps(report, allow_nan=False)
    path = save_evaluation(report, tmp_path / "report.json")
    assert json.loads(path.read_text()) == report
    assert report["provenance"]["profitability_evaluated"] is False
    assert report["provenance"]["scoring"].startswith("test only")


def test_test_labels_never_fit_calibration():
    original = candles(20)
    config = Config()
    first = walk_forward(original, FakeForecaster(constant=105., width=.25), config)
    first_test_origin = first["split"]["test"]["first_origin_index"]
    altered = original.copy()
    altered.loc[first_test_origin:, ["open", "high", "low", "close"]] += 10_000
    altered.loc[first_test_origin:, "amount"] = altered.loc[first_test_origin:, "close"] * 10
    second = walk_forward(altered, FakeForecaster(constant=105., width=.25), config)
    assert second["calibration"] == first["calibration"]
    assert second["metrics"]["model_raw"]["close_mae"] > first["metrics"]["model_raw"]["close_mae"]
    assert first["calibration"]["frozen_before_test"] is True
    assert first["calibration"]["coverage_guarantee_claimed"] is False


def test_overlapping_boundary_windows_are_purged():
    report = walk_forward(candles(16), FakeForecaster(), Config(horizon=3), stride=1)
    calibration = [w for w in report["per_window"] if w["split"] == "calibration"]
    test = [w for w in report["per_window"] if w["split"] == "test"]
    calibration_labels = {stamp for w in calibration for stamp in w["timestamps"]}
    test_labels = {stamp for w in test for stamp in w["timestamps"]}
    assert calibration_labels.isdisjoint(test_labels)
    assert max(calibration_labels) < min(test_labels)
    assert report["split"]["purged_origins"] == [9, 10]
    assert report["split"]["label_sets_disjoint"] is True
    assert report["split"]["overlap_within_split"] is True
    assert any("overlap within each split" in warning for warning in report["warnings"])


def test_model_metrics_and_persistence_baseline_match_same_test_origins():
    report = walk_forward(candles(20), FakeForecaster(), Config())
    metrics = report["metrics"]
    raw = metrics["model_raw"]
    baseline = metrics["baseline"]
    assert raw["windows"] == baseline["windows"] == report["split"]["test"]["windows"]
    assert raw["close_mae"] == 0
    assert raw["close_rmse"] == 0
    assert raw["return_mae_pct"] == 0
    assert raw["directional_accuracy"] == 1
    assert raw["terminal_directional_accuracy"] == 1
    assert raw["brier_score"] == 0
    assert raw["terminal_brier_score"] == 0
    assert raw["coverage80"] == 1
    assert raw["mean_interval_width"] == 2
    assert raw["pinball_q10"] == pytest.approx(.1)
    assert raw["pinball_q50"] == 0
    assert raw["pinball_q90"] == pytest.approx(.1)
    assert raw["mean_pinball_loss"] == pytest.approx(.2 / 3)
    assert baseline["close_mae"] == 1.5
    assert baseline["close_rmse"] == pytest.approx(np.sqrt(2.5))
    assert baseline["directional_accuracy"] == 0
    assert baseline["brier_score"] is None  # point persistence has no predictive distribution
    assert baseline["neutral_probability_brier"] == .25
    anchors = np.asarray([w["last_close"] for w in report["per_window"] if w["split"] == "test"])
    assert baseline["return_mae_pct"] == pytest.approx(np.mean(150 / anchors))
    assert report["calibration"]["expansion_by_horizon"] == [0, 0]
    assert report["metrics"]["model_calibrated"] == raw


def test_brier_is_computed_from_samples_not_summary_or_directional_accuracy():
    class WrongSummary(FakeForecaster):
        def forecast(self, *args, **kwargs):
            result = super().forecast(*args, **kwargs)
            result["summary"]["p_up"] = 0.999
            return result

    report = walk_forward(candles(20), WrongSummary(trend=0., sample_offsets=[-1, -1, 1, 1]), Config())
    assert report["metrics"]["model_raw"]["brier_score"] == .25
    assert report["metrics"]["model_raw"]["directional_accuracy"] == 0
    assert all(w["p_up_by_horizon"] == [.5, .5] for w in report["per_window"])


def test_nonnegative_conformal_expansion_is_per_horizon_and_final_uses_frozen_values():
    report = walk_forward(candles(20), FakeForecaster(trend=0., width=.25), Config())
    assert report["calibration"]["expansion_by_horizon"] == [.75, 1.75]
    assert report["metrics"]["model_raw"]["coverage80"] == 0
    assert report["metrics"]["model_calibrated"]["coverage80"] == 1
    assert report["metrics"]["model_calibrated"]["mean_interval_width"] == 3
    final = report["final_forecast"]
    assert np.asarray(final["calibrated_quantiles"]["q10"]) == pytest.approx(
        np.asarray(final["quantiles"]["q10"]) - [.75, 1.75])
    assert "p_up remain raw" in final["calibration_note"]


def test_small_sample_rank_is_explicit_and_latest_windows_selected():
    report = walk_forward(candles(30), FakeForecaster(trend=0), Config(), max_windows=2)
    assert report["split"]["calibration"]["first_origin_index"] == 26
    assert report["split"]["test"]["first_origin_index"] == 28
    assert report["calibration"]["rank_capped_for_small_sample"] is True
    assert report["calibration"]["requested_order_statistic_rank"] == 2
    assert report["calibration"]["used_order_statistic_rank"] == 1
    assert any("Fewer than 30" in warning for warning in report["warnings"])


def test_irregular_calendar_keeps_evaluation_but_skips_final_forecast():
    frame = candles(20)
    frame["timestamps"] = pd.date_range("2026-01-01", periods=22, freq="h", tz="UTC").delete([10, 11])
    forecaster = FakeForecaster()
    report = walk_forward(frame, forecaster, Config())
    assert report["final_forecast"] is None
    assert "explicit future exchange-session timestamps" in report["final_forecast_error"]
    assert len(forecaster.calls) == len(report["per_window"])
    assert report["metrics"]["model_raw"]["close_mae"] == 0


@pytest.mark.parametrize("kwargs,match", [
    ({"calibration_fraction": 0}, "strictly between"),
    ({"calibration_fraction": 1}, "strictly between"),
    ({"calibration_fraction": float("nan")}, "strictly between"),
    ({"calibration_fraction": .01}, "empty calibration"),
    ({"stride": 0}, "stride"),
    ({"stride": True}, "stride"),
    ({"max_windows": 1}, "at least one"),
])
def test_invalid_split_options_fail_before_forecasting(kwargs, match):
    forecaster = FakeForecaster()
    with pytest.raises(ValueError, match=match):
        walk_forward(candles(20), forecaster, Config(), **kwargs)
    assert not forecaster.calls


def test_insufficient_data_and_purging_empty_test_fail():
    with pytest.raises(ValueError, match="at least two"):
        walk_forward(candles(7), FakeForecaster(), Config())
    with pytest.raises(ValueError, match="No test windows remain"):
        walk_forward(candles(10), FakeForecaster(), Config(horizon=3), stride=1)


def test_misaligned_forecast_timestamps_are_rejected():
    class Misaligned(FakeForecaster):
        def forecast(self, history, *, future_timestamps, config):
            result = super().forecast(history, future_timestamps=future_timestamps, config=config)
            result["timestamps"] = [t.to_pydatetime() + timedelta(hours=1) for t in future_timestamps]
            return result

    with pytest.raises(ValueError, match="do not match"):
        walk_forward(candles(20), Misaligned(), Config())


def test_invalid_quantiles_and_samples_are_rejected():
    class Invalid(FakeForecaster):
        def forecast(self, *args, **kwargs):
            result = super().forecast(*args, **kwargs)
            result["quantiles"]["q10"] = result["quantiles"]["q90"] + 1
            return result

    with pytest.raises(ValueError, match="q10 <= q50 <= q90"):
        walk_forward(candles(20), Invalid(), Config())


def test_timestamp_cutoffs_keep_train_calibration_and_test_labels_separate():
    frame = candles(30)
    train_end = frame["timestamps"].iloc[8]
    validation_end = frame["timestamps"].iloc[18]
    report = walk_forward(frame, FakeForecaster(), Config(), stride=1,
                          evaluation_start=train_end,
                          calibration_end=validation_end - pd.Timedelta(1, unit="ns"),
                          max_windows=6)
    assert report["settings"]["split_method"] == "timestamp"
    calibration = [w for w in report["per_window"] if w["split"] == "calibration"]
    test = [w for w in report["per_window"] if w["split"] == "test"]
    assert len(calibration) == len(test) == 3
    assert [w["origin_index"] for w in calibration] == [14, 15, 16]
    assert [w["origin_index"] for w in test] == [26, 27, 28]
    for window in calibration:
        assert pd.Timestamp(window["timestamps"][0]) >= train_end
        assert pd.Timestamp(window["timestamps"][-1]) < validation_end
    for window in test:
        assert pd.Timestamp(window["timestamps"][0]) >= validation_end
    assert report["split"]["purged_origins"] == [17]


def test_explicit_calibration_end_is_inclusive():
    frame = candles(20)
    cutoff = frame["timestamps"].iloc[11]
    report = walk_forward(frame, FakeForecaster(), Config(), calibration_end=cutoff)
    assert report["split"]["calibration"]["last_label_timestamp"] == cutoff.isoformat()
    assert pd.Timestamp(report["split"]["test"]["first_label_timestamp"]) > cutoff


@pytest.mark.parametrize("kwargs,match", [
    ({"calibration_end": "2025-01-01"}, "empty calibration"),
    ({"calibration_end": "2027-01-01"}, "empty calibration"),
    ({"evaluation_start": "2027-01-01"}, "at least two"),
    ({"evaluation_start": "2026-01-02", "calibration_end": "2026-01-01"}, "must not follow"),
    ({"calibration_end": "invalid"}, "valid timestamp"),
])
def test_invalid_timestamp_boundaries_fail_before_inference(kwargs, match):
    forecaster = FakeForecaster()
    with pytest.raises(ValueError, match=match):
        walk_forward(candles(), forecaster, Config(), **kwargs)
    assert not forecaster.calls


def test_business_day_pattern_and_exchange_providers_do_not_invent_future_sessions():
    frame = candles(20)
    frame["timestamps"] = pd.bdate_range("2026-01-01", periods=20, tz="UTC")
    assert walk_forward(frame, FakeForecaster(), Config())["final_forecast"] is None
    hourly = candles(20)
    hourly.attrs["provider"] = "yfinance"
    assert walk_forward(hourly, FakeForecaster(), Config())["final_forecast"] is None
