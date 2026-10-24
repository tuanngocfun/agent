#!/usr/bin/env python3
"""Kronos smoke test against a held-out CSV window; not an OOS benchmark."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
import math

UPSTREAM_REVISION = "67b630e67f6a18c9e9be918d9b4337c960db1e9a"
FEATURES = ["open", "high", "low", "close", "volume", "amount"]


def read_window(path, lookback, horizon):
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not {"timestamps", *FEATURES}.issubset(reader.fieldnames or []):
            raise ValueError("CSV must contain timestamps and all six OHLCVA fields")
        rows = list(reader)
    if len(rows) < lookback + horizon:
        raise ValueError("CSV is shorter than lookback + horizon")
    # Only timestamps are used from the held-out window. Its prices are never model inputs.
    rows = rows[-(lookback + horizon):]
    if any(not isinstance(r.get("timestamps"), str) or not r["timestamps"].strip() for r in rows):
        raise ValueError("Missing timestamp in CSV")
    timestamps = [datetime.fromisoformat(r["timestamps"].replace("Z", "+00:00")) for r in rows]
    timestamps = [t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)
                  for t in timestamps]
    deltas = [(b - a).total_seconds() for a, b in zip(timestamps, timestamps[1:])]
    if any(delta <= 0 for delta in deltas):
        raise ValueError("Timestamps must be unique and increasing")
    # Gaps in exchange session data may be valid; do not invent a trading calendar.
    for row in rows[:lookback]:
        try:
            values = [float(row[key]) for key in FEATURES]
        except (TypeError, ValueError):
            raise ValueError("Missing or nonnumeric OHLCVA value in history") from None
        if not all(math.isfinite(value) for value in values):
            raise ValueError("History has non-finite OHLCVA")
        op, high, low, close, volume, amount = values
        if min(op, high, low, close) <= 0 or volume < 0 or amount < 0:
            raise ValueError("Invalid prices or volumes in history")
        if not low <= min(op, close) <= max(op, close) <= high:
            raise ValueError("Invalid OHLC bounds in history")
    return rows, timestamps


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kronos-dir", type=Path, default=Path("vendor/Kronos"))
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--lookback", type=int, default=256)
    parser.add_argument("--horizon", type=int, default=24)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default=None, help="Default: upstream chooses CUDA, MPS or CPU")
    parser.add_argument("--output", type=Path, default=Path("output/forecast_smoke_test.csv"))
    args = parser.parse_args(argv)
    if not 2 <= args.lookback <= 512 or not 1 <= args.horizon <= 512:
        parser.error("lookback must be 2..512; horizon must be 1..512")
    root = args.kronos_dir.resolve()
    source = args.csv or root / "tests/data/regression_input.csv"
    try:
        revision = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"],
                                           text=True, stderr=subprocess.DEVNULL).strip()
        if revision != UPSTREAM_REVISION:
            raise ValueError("Upstream revision differs from the pinned version; see README")
        if subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"], text=True).strip():
            raise ValueError("Upstream checkout has local modifications")
        rows, timestamps = read_window(source, args.lookback, args.horizon)
        import numpy as np
        import pandas as pd
        import torch
        sys.path.insert(0, str(root))
        from model import Kronos, KronosTokenizer, KronosPredictor
        np.random.seed(args.seed)
        torch.manual_seed(args.seed)
        tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
        model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
        tokenizer.eval()
        model.eval()
        predictor = KronosPredictor(model, tokenizer, device=args.device, max_context=512)
        history = pd.DataFrame(rows[:args.lookback])[FEATURES].astype(float)
        stamps = pd.Series(pd.to_datetime(timestamps, utc=True)).dt.tz_localize(None)
        with torch.inference_mode():
            prediction = predictor.predict(df=history, x_timestamp=stamps.iloc[:args.lookback],
                y_timestamp=stamps.iloc[args.lookback:].reset_index(drop=True),
                pred_len=args.horizon, sample_count=1, T=1.0, top_k=0, top_p=0.9, verbose=True)
        if prediction.shape != (args.horizon, 6) or not np.isfinite(prediction.to_numpy()).all():
            raise ValueError("Unexpected prediction shape or non-finite output")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        prediction.to_csv(args.output, index_label="timestamps")
        metadata = {"purpose": "held-out software smoke test; not evidence of forecast skill",
            "issued_at_utc": datetime.now(timezone.utc).isoformat(), "upstream_revision": revision,
            "model": "NeoQuasar/Kronos-small", "tokenizer": "NeoQuasar/Kronos-Tokenizer-base",
            "weights_revision": "Hugging Face default; not pinned in this starter",
            "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "seed": args.seed,
            "lookback": args.lookback, "horizon": args.horizon, "sample_count": 1,
            "temperature": 1.0, "top_k": 0, "top_p": 0.9, "device": str(predictor.device),
            "python": sys.version.split()[0], "torch": torch.__version__, "pandas": pd.__version__}
        args.output.with_suffix(".meta.json").write_text(json.dumps(metadata, indent=2) + "\n")
    except ImportError:
        print("Missing inference dependencies; follow the README setup steps", file=sys.stderr)
        return 1
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        return 1
    print(f"Saved forecast to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
