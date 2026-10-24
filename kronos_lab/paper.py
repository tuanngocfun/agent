"""Local, cost-aware LONG/FLAT simulation of frozen held-out forecasts.

No account, broker, order API, or future value participates in signal selection.
Each non-overlapping forecast window is an independent full-capital roundtrip;
capital remains cash between windows. Returns are fractions, not percentages.
"""
from __future__ import annotations

import math
from numbers import Integral, Real

import numpy as np
import pandas as pd

from .data import normalize_frame


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{label} must be finite and numeric")
    return float(value)


def _positive_vector(value, label):
    try:
        result = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite positive price vector") from exc
    if result.ndim != 1 or not len(result) or not np.isfinite(result).all() or (result <= 0).any():
        raise ValueError(f"{label} must be a finite positive price vector")
    return result


def paper_backtest(report, frame, *, fee_bps=10.0, slippage_bps=5.0):
    """Simulate already-produced test windows with explicit execution costs.

    A positive terminal forecast return selects LONG; otherwise cash (FLAT).
    Entry uses the first forecast candle's open plus adverse slippage. Exit uses
    the final candle's close minus adverse slippage. Fees apply to each actual
    fill notional. Quantity includes the entry fee in the available cash budget,
    so leverage and negative cash are never introduced.

    Drawdown uses an initial equity of 1, the entry mark at the unslipped open,
    every held candle close, and the actual exit proceeds. This is a sampled
    close-marked drawdown, not an intrabar-low drawdown. Candle timestamps label
    their opening times; a ``close`` event refers to that candle's close.
    """
    fee_bps = _number(fee_bps, "fee_bps")
    slippage_bps = _number(slippage_bps, "slippage_bps")
    if not 0 <= fee_bps < 10000 or not 0 <= slippage_bps < 10000:
        raise ValueError("fee_bps and slippage_bps must be in [0, 10000)")
    if not isinstance(report, dict) or not isinstance(report.get("per_window"), list):
        raise ValueError("report must contain a per_window list")
    frame = normalize_frame(frame)
    windows = []
    for raw in report["per_window"]:
        if not isinstance(raw, dict):
            raise ValueError("Every per_window record must be an object")
        if raw.get("split") != "test":
            continue
        origin = raw.get("origin_index")
        if isinstance(origin, bool) or not isinstance(origin, Integral) or not 1 <= origin < len(frame):
            raise ValueError("test origin_index must identify a candle after observed history")
        origin = int(origin)
        forecast = _positive_vector(raw.get("forecast_close"), "forecast_close")
        actual = _positive_vector(raw.get("actual_close"), "actual_close")
        end = origin + len(forecast)
        if end > len(frame) or len(actual) != len(forecast):
            raise ValueError("Forecast/actual horizons must match and fit within frame")
        try:
            timestamps = pd.DatetimeIndex(pd.to_datetime(raw.get("timestamps"), utc=True, errors="raise"))
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError("Window timestamps must match the forecast candle rows") from exc
        expected = pd.DatetimeIndex(frame["timestamps"].iloc[origin:end])
        if len(timestamps) != len(expected) or timestamps.hasnans or not timestamps.equals(expected):
            raise ValueError("Window timestamps do not align with origin_index and frame")
        last_close = _number(raw.get("last_close"), "last_close")
        if last_close <= 0 or not math.isclose(last_close, float(frame["close"].iloc[origin - 1]),
                                             rel_tol=1e-10, abs_tol=1e-12):
            raise ValueError("last_close must match the last observed candle before origin_index")
        if not np.allclose(actual, frame["close"].iloc[origin:end].to_numpy(), rtol=1e-10, atol=1e-12):
            raise ValueError("actual_close does not match the supplied frame")
        # Decisions depend only on frozen predictions and the observed anchor.
        signal_return = float(forecast[-1] / last_close - 1.0)
        if not math.isfinite(signal_return):
            raise ValueError("Forecast return overflows")
        windows.append({"origin": origin, "end": end, "signal_return": signal_return,
                        "signal": "LONG" if signal_return > 0 else "FLAT"})
    if not windows:
        raise ValueError("At least one test window is required for paper simulation")
    windows.sort(key=lambda window: window["origin"])
    for first, second in zip(windows, windows[1:]):
        if second["origin"] < first["end"]:
            raise ValueError("Overlapping test windows cannot be simulated as independent roundtrips")

    fee, slip = fee_bps / 10000.0, slippage_bps / 10000.0
    equity = gross_equity = peak = 1.0
    max_drawdown = total_turnover = total_fees = total_slippage = 0.0
    trade_count = 0
    curve, ledger = [], []

    def mark(index, event, value, position):
        nonlocal peak, max_drawdown
        if not math.isfinite(value) or value <= 0:
            raise FloatingPointError("Paper equity became non-finite or non-positive")
        peak = max(peak, value)
        drawdown = max(0.0, 1.0 - value / peak)
        max_drawdown = max(max_drawdown, drawdown)
        curve.append({"candle_index": int(index),
                      "timestamp": frame["timestamps"].iloc[index].isoformat(),
                      "event": event, "position": position, "equity": float(value),
                      "drawdown": float(drawdown)})

    cursor = windows[0]["origin"]
    mark(cursor - 1, "initial", equity, "FLAT")
    for window in windows:
        origin, end, signal = window["origin"], window["end"], window["signal"]
        for index in range(cursor, origin):
            mark(index, "gap_close", equity, "FLAT")
        start_equity = equity
        record = {
            "origin_index": origin, "exit_index": end - 1,
            "entry_timestamp": frame["timestamps"].iloc[origin].isoformat(),
            "exit_candle_timestamp": frame["timestamps"].iloc[end - 1].isoformat(),
            "signal": signal, "forecast_terminal_return": window["signal_return"],
            "equity_before": start_equity,
        }
        if signal == "LONG":
            entry_open = float(frame["open"].iloc[origin])
            exit_close = float(frame["close"].iloc[end - 1])
            entry_fill, exit_fill = entry_open * (1 + slip), exit_close * (1 - slip)
            quantity = start_equity / (entry_fill * (1 + fee))
            entry_notional, exit_notional = quantity * entry_fill, quantity * exit_fill
            entry_fee, exit_fee = entry_notional * fee, exit_notional * fee
            entry_slippage, exit_slippage = quantity * (entry_fill - entry_open), quantity * (exit_close - exit_fill)
            equity = exit_notional - exit_fee
            gross_return = exit_close / entry_open - 1
            gross_equity *= 1 + gross_return
            net_return = equity / start_equity - 1
            trade_count += 1
            total_turnover += entry_notional + exit_notional
            total_fees += entry_fee + exit_fee
            total_slippage += entry_slippage + exit_slippage
            mark(origin, "entry_open", quantity * entry_open, "LONG")
            for index in range(origin, end):
                final = index == end - 1
                mark(index, "exit_close" if final else "holding_close",
                     equity if final else quantity * float(frame["close"].iloc[index]),
                     "FLAT" if final else "LONG")
            record.update({
                "quantity": quantity, "entry_open": entry_open, "exit_close": exit_close,
                "entry_fill": entry_fill, "exit_fill": exit_fill,
                "entry_notional": entry_notional, "exit_notional": exit_notional,
                "entry_fee": entry_fee, "exit_fee": exit_fee,
                "entry_slippage": entry_slippage, "exit_slippage": exit_slippage,
                "gross_return": gross_return, "net_return": net_return,
                "turnover": entry_notional + exit_notional,
            })
        else:
            for index in range(origin, end):
                mark(index, "flat_close", equity, "FLAT")
            record.update({"quantity": 0.0, "entry_fill": None, "exit_fill": None,
                           "entry_notional": 0.0, "exit_notional": 0.0,
                           "entry_fee": 0.0, "exit_fee": 0.0,
                           "entry_slippage": 0.0, "exit_slippage": 0.0,
                           "gross_return": 0.0, "net_return": 0.0, "turnover": 0.0})
        record["equity_after"] = equity
        ledger.append(record)
        cursor = end

    summary = {
        "test_windows": len(windows), "trade_count": trade_count,
        "flat_windows": len(windows) - trade_count,
        "gross_return": gross_equity - 1.0, "net_return": equity - 1.0,
        "initial_equity": 1.0, "final_equity": equity,
        "max_drawdown": max_drawdown, "turnover": total_turnover,
        "fees_paid": total_fees, "slippage_cost": total_slippage,
    }
    if not all(math.isfinite(value) for value in summary.values()):
        raise FloatingPointError("Paper summary overflowed")
    return {
        "schema_version": 1, "kind": "local-paper-backtest", "summary": summary,
        "assumptions": {
            "signal": "LONG iff forecast_close[-1] / last_close - 1 > 0; otherwise FLAT",
            "sizing": "All available cash, entry fee reserved, no leverage or short positions",
            "execution": "First forecast candle OPEN to final forecast candle CLOSE; independent roundtrips",
            "fee_bps_per_side": fee_bps, "slippage_bps_per_side": slippage_bps,
            "gaps": "FLAT with zero interest between forecast windows",
            "drawdown": "Sampled entry-open/held-close/exit-close equity; intrabar extrema excluded",
            "timestamp_semantics": "Timestamps label candle opens; close events refer to that candle's close",
            "turnover": "Sum of actual entry and exit notionals divided by initial equity (1.0)",
            "return_units": "Fractions; multiply by 100 for percent",
            "gross_return": "Compounded identical signals without fees or slippage",
            "cost_units": "Cash units relative to initial equity (1.0); gross-net gap also includes sizing and compounding",
        },
        "provenance": {"scoring": "Test windows only", "non_overlapping_windows": True,
                       "future_prices_used_for_signal": False, "broker_or_order_api_used": False,
                       "annualized_metrics_computed": False},
        "per_window": ledger, "equity_curve": curve,
    }
