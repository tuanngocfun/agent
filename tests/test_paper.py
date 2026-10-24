"""Paper decisions are causal; execution and both-sided costs are explicit."""
from copy import deepcopy
import json

import numpy as np
import pandas as pd
import pytest

from kronos_lab.paper import paper_backtest


def candles(count=15):
    close = np.arange(count, dtype=float) + 100
    return pd.DataFrame({
        "timestamps": pd.date_range("2026-01-01", periods=count, freq="h", tz="UTC"),
        "open": close, "high": close + 2, "low": close - 2,
        "close": close, "volume": np.full(count, 10.0), "amount": close * 10,
    })


def window(frame, origin=4, horizon=2, signal_return=0.05, split="test"):
    last = float(frame.close.iloc[origin - 1])
    return {"split": split, "origin_index": origin,
            "timestamps": [stamp.isoformat() for stamp in frame.timestamps.iloc[origin:origin + horizon]],
            "last_close": last, "forecast_close": [last * (1 + signal_return)] * horizon,
            "actual_close": frame.close.iloc[origin:origin + horizon].tolist()}


def test_exact_fees_slippage_and_next_open_execution():
    frame = candles()
    frame.loc[4, ["open", "high", "low", "close"]] = [110, 113, 108, 111]
    frame.loc[5, ["open", "high", "low", "close"]] = [118, 122, 117, 120]
    result = paper_backtest({"per_window": [window(frame)]}, frame, fee_bps=100, slippage_bps=200)
    trade = result["per_window"][0]
    quantity = 1 / (110 * 1.02 * 1.01)
    expected_equity = quantity * 120 * 0.98 * 0.99
    assert trade["entry_open"] == 110  # Does not execute at historical last close 103.
    assert trade["entry_fill"] == pytest.approx(112.2)
    assert trade["exit_fill"] == pytest.approx(117.6)
    assert trade["quantity"] == pytest.approx(quantity)
    assert trade["entry_notional"] + trade["entry_fee"] == pytest.approx(1)
    assert trade["entry_fee"] == pytest.approx(quantity * 110 * 1.02 * 0.01)
    assert trade["exit_fee"] == pytest.approx(quantity * 120 * 0.98 * 0.01)
    assert result["summary"]["net_return"] == pytest.approx(expected_equity - 1)
    assert result["summary"]["gross_return"] == pytest.approx(120 / 110 - 1)
    assert result["summary"]["turnover"] == pytest.approx(quantity * (110 * 1.02 + 120 * 0.98))
    assert result["summary"]["slippage_cost"] == pytest.approx(quantity * (110 + 120) * 0.02)
    json.dumps(result, allow_nan=False)


def test_signal_never_depends_on_future_realized_prices():
    frame = candles()
    frozen = window(frame)
    first = paper_backtest({"per_window": [frozen]}, frame)
    changed = frame.copy()
    changed.loc[4, ["open", "high", "low", "close"]] *= 0.2
    changed.loc[5, ["open", "high", "low", "close"]] *= 2.0
    updated = deepcopy(frozen)
    updated["actual_close"] = changed.close.iloc[4:6].tolist()
    second = paper_backtest({"per_window": [updated]}, changed)
    assert first["per_window"][0]["signal"] == second["per_window"][0]["signal"] == "LONG"
    assert first["per_window"][0]["forecast_terminal_return"] == second["per_window"][0]["forecast_terminal_return"]
    assert first["summary"]["net_return"] != second["summary"]["net_return"]


def test_non_positive_signal_is_flat_with_no_cost_and_flat_gaps():
    frame = candles()
    report = {"per_window": [window(frame, 4, signal_return=0),
                             window(frame, 9, signal_return=-0.1),
                             window(frame, 2, split="calibration")]}
    result = paper_backtest(report, frame)
    assert result["summary"]["trade_count"] == 0
    assert result["summary"]["flat_windows"] == 2
    assert result["summary"]["final_equity"] == 1
    assert result["summary"]["fees_paid"] == 0
    assert result["summary"]["turnover"] == 0
    assert result["summary"]["max_drawdown"] == 0
    assert all(point["position"] == "FLAT" for point in result["equity_curve"])
    assert [point["candle_index"] for point in result["equity_curve"] if point["event"] == "gap_close"] == [6, 7, 8]


def test_non_overlapping_roundtrips_compound_and_drawdown_includes_held_closes():
    frame = candles()
    frame.loc[4, ["open", "high", "low", "close"]] = [100, 101, 49, 50]
    frame.loc[5, ["open", "high", "low", "close"]] = [100, 121, 99, 120]
    frame.loc[7, ["open", "high", "low", "close"]] = [100, 101, 79, 80]
    result = paper_backtest({"per_window": [window(frame, 6), window(frame, 4)]}, frame,
                            fee_bps=0, slippage_bps=0)
    expected = (120 / 100) * (80 / 106)
    assert result["summary"]["trade_count"] == 2
    assert result["summary"]["final_equity"] == pytest.approx(expected)
    assert result["summary"]["net_return"] == pytest.approx(expected - 1)
    assert result["summary"]["gross_return"] == pytest.approx(expected - 1)
    assert result["summary"]["max_drawdown"] == pytest.approx(0.5)
    assert result["per_window"][1]["equity_before"] == pytest.approx(1.2)


@pytest.mark.parametrize("mutate,match", [
    (lambda w: w.update(origin_index=0), "origin_index"),
    (lambda w: w.update(origin_index=True), "origin_index"),
    (lambda w: w.update(origin_index=5), "align"),
    (lambda w: w.update(last_close=999), "last_close"),
    (lambda w: w.update(actual_close=[1, 2]), "actual_close"),
    (lambda w: w.update(timestamps=w["timestamps"][::-1]), "align"),
    (lambda w: w.update(forecast_close=[float("nan"), 1]), "forecast_close"),
    (lambda w: w.update(forecast_close=[-1, 1]), "forecast_close"),
    (lambda w: w.update(forecast_close=[1]), "horizons"),
])
def test_misalignment_and_bad_prices_are_rejected(mutate, match):
    frame = candles()
    item = window(frame)
    mutate(item)
    with pytest.raises(ValueError, match=match):
        paper_backtest({"per_window": [item]}, frame)


def test_overlapping_test_windows_are_rejected_even_when_one_is_flat():
    frame = candles()
    report = {"per_window": [window(frame, 4), window(frame, 5, signal_return=-0.1)]}
    with pytest.raises(ValueError, match="Overlapping"):
        paper_backtest(report, frame)


@pytest.mark.parametrize("kwargs", [
    {"fee_bps": -1}, {"fee_bps": 10000}, {"fee_bps": float("inf")},
    {"slippage_bps": -1}, {"slippage_bps": 10000}, {"slippage_bps": float("nan")},
    {"fee_bps": True},
])
def test_bad_cost_ranges_are_rejected(kwargs):
    frame = candles()
    with pytest.raises(ValueError):
        paper_backtest({"per_window": [window(frame)]}, frame, **kwargs)


def test_missing_test_windows_are_rejected():
    frame = candles()
    with pytest.raises(ValueError, match="test window"):
        paper_backtest({"per_window": [window(frame, split="calibration")]}, frame)
