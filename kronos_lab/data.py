"""Strict OHLCVA ingestion. Providers are optional and imported only when used.

Native provider timestamps are converted to UTC. Amount is quote turnover when
the source supplies it; otherwise an explicitly labelled OHLC-average proxy.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

FEATURES = ["open", "high", "low", "close", "volume", "amount"]
BINANCE_INTERVALS = {"1s", "1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"}
BINANCE_PUBLIC = "https://data-api.binance.vision"


def normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Return sorted, unique UTC timestamps and finite validated six features.

    Naive CSV timestamps are interpreted as UTC. Provider adapters localize
    exchange timestamps before calling this function. No missing prices,
    volumes, duplicate timestamps, or invalid OHLC bounds are silently repaired.
    """
    if not isinstance(df, pd.DataFrame) or df.empty:
        raise ValueError("OHLCVA input must be a nonempty pandas DataFrame")
    if isinstance(df.columns, pd.MultiIndex):
        raise ValueError("MultiIndex columns must be flattened by the provider adapter")
    frame = df.copy()
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    if frame.columns.duplicated().any():
        raise ValueError("Duplicate column names")
    timestamp_cols = [c for c in ["timestamps", "timestamp", "datetime", "date", "time"] if c in frame]
    if timestamp_cols:
        raw_time = frame[timestamp_cols[0]]
    elif isinstance(frame.index, pd.DatetimeIndex):
        raw_time = pd.Series(frame.index, index=frame.index)
    else:
        raise ValueError("A timestamps column or DatetimeIndex is required")
    try:
        stamps = pd.to_datetime(raw_time, utc=True, errors="raise", format="mixed")
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("Invalid timestamp; use ISO-8601 strings or datetime values") from exc
    if pd.isna(stamps).any():
        raise ValueError("Missing timestamp")
    if pd.Index(stamps).has_duplicates:
        raise ValueError("Timestamps must be unique")
    missing = set(FEATURES[:5]) - set(frame.columns)
    if missing:
        raise ValueError(f"Missing required OHLCV columns: {sorted(missing)}")
    out = pd.DataFrame({"timestamps": np.asarray(stamps)})
    for name in FEATURES[:5]:
        try:
            out[name] = pd.to_numeric(frame[name], errors="raise").to_numpy(dtype=np.float64)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Nonnumeric {name}") from exc
    if "amount" in frame:
        try:
            out["amount"] = pd.to_numeric(frame["amount"], errors="raise").to_numpy(dtype=np.float64)
        except (ValueError, TypeError) as exc:
            raise ValueError("Nonnumeric amount") from exc
        amount_source = df.attrs.get("amount_source", "provided")
    else:
        out["amount"] = out["volume"] * out[FEATURES[:4]].mean(axis=1)
        amount_source = "proxy: volume * mean(open,high,low,close)"
    values = out[FEATURES].to_numpy()
    if not np.isfinite(values).all():
        raise ValueError("OHLCVA must contain only finite values")
    if (out[FEATURES[:4]] <= 0).any().any():
        raise ValueError("OHLC prices must be positive")
    if (out[["volume", "amount"]] < 0).any().any():
        raise ValueError("Volume and amount cannot be negative")
    if ((out["low"] > out[["open", "close"]].min(axis=1)) |
        (out["high"] < out[["open", "close"]].max(axis=1))).any():
        raise ValueError("Invalid OHLC bounds: low <= open,close <= high is required")
    out = out.sort_values("timestamps", kind="stable").reset_index(drop=True)
    out.attrs.update(df.attrs)
    out.attrs["amount_source"] = amount_source
    return out[["timestamps", *FEATURES]]


def load_csv(path: str | Path) -> pd.DataFrame:
    frame = normalize_frame(pd.read_csv(path))
    frame.attrs.setdefault("provider", "csv")
    return frame


def _public_json(path: str, params: dict | None = None):
    url = f"{BINANCE_PUBLIC}{path}"
    if params:
        url += "?" + urlencode(params)
    request = Request(url, headers={"User-Agent": "kronos-research-lab/0.1"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def fetch_binance(symbol: str, interval: str, limit: int = 500) -> pd.DataFrame:
    """Read closed official public candles; no API key is sent or read.

    The dedicated market-data endpoint and exchange server time prevent a
    partly formed final candle from entering training or forecast context.
    See developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints.
    """
    symbol = str(symbol).upper()
    if not re.fullmatch(r"[A-Z0-9]{2,30}", symbol):
        raise ValueError("Invalid Binance symbol")
    if interval not in BINANCE_INTERVALS:
        raise ValueError(f"Unsupported Binance interval: {interval}")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("Binance limit must be an integer in 1..1000")
    server_time = int(_public_json("/api/v3/time")["serverTime"])
    payload = _public_json("/api/v3/klines", {"symbol": symbol, "interval": interval,
                                               "limit": limit, "endTime": server_time - 1})
    if not isinstance(payload, list) or not payload:
        raise ValueError("Binance returned no candle rows")
    rows = []
    for bar in payload:
        if not isinstance(bar, list) or len(bar) < 8:
            raise ValueError("Malformed Binance candle response")
        if int(bar[6]) >= server_time:
            continue
        rows.append({"timestamps": pd.to_datetime(int(bar[0]), unit="ms", utc=True),
                     **dict(zip(FEATURES, [bar[1], bar[2], bar[3], bar[4], bar[5], bar[7]]))})
    frame = pd.DataFrame(rows)
    frame.attrs.update(provider="binance", symbol=symbol, interval=interval,
                       amount_source="Binance quote asset volume", closed_candles_only=True,
                       exchange_server_time_utc=pd.to_datetime(server_time, unit="ms", utc=True).isoformat())
    return normalize_frame(frame)


def fetch_yfinance(symbol: str, start: str | None = None, end: str | None = None,
                   interval: str = "1d", period: str = "1y") -> pd.DataFrame:
    """Fetch raw, unadjusted Yahoo OHLCV through the optional yfinance adapter.

    End is exclusive. Historical corporate actions can still affect research;
    record the returned adjustment policy when comparing providers.
    """
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("Install the market extra: pip install -e '.[market]'") from exc
    kwargs = {"interval": interval, "auto_adjust": False, "back_adjust": False,
              "actions": False, "progress": False, "threads": False,
              "ignore_tz": False, "multi_level_index": False, "timeout": 30}
    if start is not None:
        kwargs.update(start=start, end=end)
    else:
        kwargs.update(period=period)
        if end is not None:
            kwargs["end"] = end
    frame = yf.download(symbol, **kwargs)
    if frame is None or frame.empty:
        raise ValueError(f"Yahoo returned no candles for {symbol}")
    if isinstance(frame.columns, pd.MultiIndex):
        if len(frame.columns.get_level_values(-1).unique()) != 1:
            raise ValueError("Only one Yahoo symbol may be fetched per request")
        frame.columns = frame.columns.get_level_values(0)
    frame.attrs.update(provider="yfinance", symbol=symbol, interval=interval,
                       adjustment_policy="auto_adjust=False, back_adjust=False",
                       candle_finality="provider dependent; caller must choose completed session end")
    return normalize_frame(frame)


def fetch_vnstock(symbol: str, start: str | None = None, end: str | None = None,
                  interval: str = "1D", source: str | None = None,
                  limit: int = 500) -> pd.DataFrame:
    """Read Vnstock v5's documented Market().equity().ohlcv() interface.

    Optional provider installation: https://vnstocks.com/docs/vnstock/cai-dat
    API reference: https://vnstocks.com/docs/vnstock/thi-truong-market
    Provider setup/authentication belongs to the user's local Vnstock CLI.
    """
    try:
        from vnstock import Market
    except ImportError as exc:
        raise RuntimeError("Vnstock v5 is required; install using https://vnstocks.com/docs/vnstock/cai-dat") from exc
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20000:
        raise ValueError("Vnstock limit must be an integer in 1..20000")
    frame = Market().equity(symbol).ohlcv(start=start, end=end, interval=interval,
                                          source=source, limit=limit, floating=None)
    if frame is None or frame.empty:
        raise ValueError(f"Vnstock returned no candles for {symbol}")
    frame.attrs.update(provider="vnstock-v5", symbol=symbol, interval=interval,
                       price_unit="thousand VND; provider adjusted equity prices",
                       candle_finality="provider dependent; caller must choose completed session end")
    return normalize_frame(frame)
