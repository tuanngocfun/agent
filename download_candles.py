#!/usr/bin/env python3
"""Download closed Binance Spot candles without API credentials (Python 3.10+)."""

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://data-api.binance.vision"
INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
               "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
COLUMNS = ["timestamps", "open", "high", "low", "close", "volume", "amount"]


def get_json(path, params=None):
    url = BASE_URL + path
    if params:
        url += "?" + urlencode(params)
    request = Request(url, headers={"User-Agent": "kronos-evaluation-lab/0.1"}, method="GET")
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def closed_candles(payload, server_time_ms, interval):
    """Reject invalid OHLCVA and gaps; omit any candle still open at server time."""
    if not isinstance(payload, list):
        raise ValueError("Expected a list of Binance candles")
    rows = []
    for candle in payload:
        if not isinstance(candle, list) or len(candle) != 12:
            raise ValueError("Expected the documented 12-field candle format")
        opened, closed = int(candle[0]), int(candle[6])
        if closed >= server_time_ms:
            continue
        if closed != opened + INTERVAL_MS[interval] - 1:
            raise ValueError("Candle duration differs from requested interval")
        values = [Decimal(str(candle[i])) for i in (1, 2, 3, 4, 5, 7)]
        if not all(v.is_finite() for v in values):
            raise ValueError("Non-finite OHLCVA value")
        op, high, low, close, volume, amount = values
        if min(op, high, low, close) <= 0 or volume < 0 or amount < 0:
            raise ValueError("Prices must be positive and volumes nonnegative")
        if not (low <= min(op, close) <= max(op, close) <= high):
            raise ValueError("Inconsistent OHLC candle bounds")
        stamp = datetime.fromtimestamp(opened / 1000, timezone.utc).isoformat()
        rows.append((opened, dict(zip(COLUMNS, [stamp, *map(str, values)]))))
    rows.sort(key=lambda item: item[0])
    for previous, current in zip(rows, rows[1:]):
        if current[0] - previous[0] != INTERVAL_MS[interval]:
            raise ValueError("Duplicate timestamps or gaps in candles")
    if not rows:
        raise ValueError("No closed candles returned")
    return [row for _, row in rows]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", choices=INTERVAL_MS, default="1h")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--output", type=Path, default=Path("data/BTCUSDT_1h.csv"))
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Z0-9]{2,30}", args.symbol) or not 1 <= args.limit <= 1000:
        parser.error("Use an uppercase alphanumeric symbol and limit from 1 to 1000")
    try:
        server_time = int(get_json("/api/v3/time")["serverTime"])
        payload = get_json("/api/v3/klines", {"symbol": args.symbol, "interval": args.interval,
                                               "limit": min(args.limit + 1, 1000)})
        rows = closed_candles(payload, server_time, args.interval)[-args.limit:]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        metadata = {"source": BASE_URL + "/api/v3/klines", "symbol": args.symbol,
                    "interval": args.interval, "server_time_ms": server_time,
                    "closed_candles_only": True, "timezone": "UTC", "rows": len(rows),
                    "amount": "Binance quote asset volume"}
        args.output.with_suffix(".meta.json").write_text(json.dumps(metadata, indent=2) + "\n")
    except HTTPError as exc:
        print(f"Public API failed: HTTP {exc.code}", file=sys.stderr)
        return 1
    except (URLError, OSError, ValueError, TypeError, KeyError, InvalidOperation):
        print("Could not download or validate public candles", file=sys.stderr)
        return 1
    print(f"Saved {len(rows)} closed candles to {args.output} (UTC)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
