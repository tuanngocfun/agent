"""Provider contracts and strict ingestion without private credentials."""
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from kronos_lab import data


def candles():
    return pd.DataFrame({"timestamps": ["2026-01-01T07:00:00+07:00", "2026-01-02T00:00:00Z"],
                         "open": [10, 11], "high": [12, 13], "low": [9, 10],
                         "close": [11, 12], "volume": [100, 200]})


def test_normalize_sort_utc_and_proxy():
    frame = data.normalize_frame(candles().iloc[::-1])
    assert list(frame.columns) == ["timestamps", *data.FEATURES]
    assert str(frame.timestamps.dt.tz) == "UTC"
    assert frame.timestamps.is_monotonic_increasing
    assert frame.iloc[0].amount == 100 * (10 + 12 + 9 + 11) / 4
    assert frame.attrs["amount_source"].startswith("proxy:")


def test_actual_amount_is_preserved_and_input_unmodified():
    source = candles().assign(amount=[1234, 2345])
    original = source.copy(deep=True)
    result = data.normalize_frame(source)
    assert result.amount.tolist() == [1234, 2345]
    pd.testing.assert_frame_equal(source, original)


@pytest.mark.parametrize("mutation", [
    lambda df: df.assign(close=[np.nan, 12]),
    lambda df: df.assign(volume=[-1, 2]),
    lambda df: df.assign(high=[5, 13]),
    lambda df: df.assign(amount=[np.inf, 10]),
    lambda df: df.assign(timestamps=["2026-01-01", "2026-01-01"]),
    lambda df: df.assign(timestamps=["bad date", "2026-01-01"]),
    lambda df: df.drop(columns="volume"),
])
def test_reject_invalid_market_data(mutation):
    with pytest.raises(ValueError):
        data.normalize_frame(mutation(candles()))


def test_datetime_index_supported():
    frame = candles().drop(columns="timestamps")
    frame.index = pd.date_range("2026-01-01", periods=2, tz="Asia/Ho_Chi_Minh")
    result = data.normalize_frame(frame)
    assert result.timestamps.iloc[0] == pd.Timestamp("2025-12-31T17:00:00Z")


def test_binance_uses_exchange_time_and_actual_turnover(monkeypatch):
    calls = []
    def public(path, params=None):
        calls.append((path, params))
        if path.endswith("time"):
            return {"serverTime": 2000}
        return [[0, "10", "12", "9", "11", "100", 999, "1234"],
                [1000, "11", "13", "10", "12", "200", 2999, "2345"]]
    monkeypatch.setattr(data, "_public_json", public)
    frame = data.fetch_binance("btcusdt", "1m", limit=2)
    assert len(frame) == 1
    assert frame.amount.tolist() == [1234]
    assert calls[1][1]["endTime"] == 1999
    assert frame.attrs["closed_candles_only"] is True
    assert "key" not in str(calls).lower()


def test_yahoo_requests_explicit_raw_prices(monkeypatch):
    def download(symbol, **kwargs):
        assert symbol == "AAPL"
        assert kwargs["auto_adjust"] is False
        assert kwargs["back_adjust"] is False
        assert kwargs["ignore_tz"] is False
        frame = candles().drop(columns="timestamps")
        frame.index = pd.date_range("2026-01-01", periods=2, tz="America/New_York")
        frame.columns = [col.title() for col in frame.columns]
        return frame
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=download))
    frame = data.fetch_yfinance("AAPL")
    assert frame.timestamps.iloc[0] == pd.Timestamp("2026-01-01T05:00:00Z")
    assert frame.attrs["provider"] == "yfinance"


def test_vnstock_current_v5_interface_and_timezone(monkeypatch):
    class Equity:
        def ohlcv(self, **kwargs):
            assert kwargs == {"start": "2026-01-01", "end": "2026-01-03", "interval": "1D",
                              "source": None, "limit": 500, "floating": None}
            return candles().rename(columns={"timestamps": "time"})
    class Market:
        def equity(self, symbol):
            assert symbol == "FPT"
            return Equity()
    monkeypatch.setitem(sys.modules, "vnstock", SimpleNamespace(Market=Market))
    frame = data.fetch_vnstock("FPT", "2026-01-01", "2026-01-03")
    assert frame.attrs["provider"] == "vnstock-v5"
    assert frame.timestamps.iloc[0] == pd.Timestamp("2026-01-01T00:00:00Z")
