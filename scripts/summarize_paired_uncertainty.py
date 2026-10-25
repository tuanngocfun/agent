#!/usr/bin/env python3
"""Exploratory paired moving-block uncertainty for one frozen forecast run.

This resamples chronological forecast origins in blocks, preserving the paired
model errors and the twelve horizon observations within each origin. It does
not quantify uncertainty over other assets, regimes, model training or Monte
Carlo seeds, and does not certify trading profitability or a general winner.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import statistics

ROOT = Path(__file__).resolve().parents[1]


def percentile(values, probability):
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize(report, *, block_length=4, repetitions=2000, seed=42):
    tests = sorted((w for w in report["per_window"] if w["split"] == "test"),
                   key=lambda w: w["origin_index"])
    if not 1 <= block_length <= len(tests) or repetitions < 2:
        raise ValueError("Need enough test origins for the positive block length and at least two repetitions")
    origins = [w["origin_index"] for w in tests]
    if len(set(origins)) != len(origins):
        raise ValueError("Test origin indices must be unique")
    rows = []
    horizons = set()
    for window in tests:
        actual = window["actual_close"]
        horizons.add(len(actual))
        anchor = window["last_close"]
        predictions = {
            "kronos_median": window["kronos"]["median_close"],
            "chronos_median": window["chronos2"]["median_close"],
            "persistence": [anchor] * len(actual),
        }
        if not actual or any(len(values) != len(actual) for values in predictions.values()):
            raise ValueError("Actual and median forecast horizons must be nonempty and aligned")
        if not all(math.isfinite(value) and value > 0 for values in [actual, *predictions.values()] for value in values):
            raise ValueError("Prices must be finite and positive")
        rows.append({"origin_index": window["origin_index"], **{
            name + "_mae": statistics.mean(abs(point - observed) for point, observed in zip(values, actual))
            for name, values in predictions.items()
        }})
    if len(horizons) != 1:
        raise ValueError("All origins must share the same forecast horizon")

    definitions = {
        "kronos_median_minus_chronos_median": ("kronos_median", "chronos_median"),
        "kronos_median_minus_persistence": ("kronos_median", "persistence"),
        "chronos_median_minus_persistence": ("chronos_median", "persistence"),
    }
    differences = {
        name: [row[left + "_mae"] - row[right + "_mae"] for row in rows]
        for name, (left, right) in definitions.items()
    }
    generator = random.Random(seed)
    distributions = {name: [] for name in definitions}
    count = len(rows)
    for _ in range(repetitions):
        indices = []
        while len(indices) < count:
            start = generator.randrange(count - block_length + 1)
            indices.extend(range(start, start + block_length))
        indices = indices[:count]
        for name, values in differences.items():
            distributions[name].append(statistics.mean(values[index] for index in indices))

    return {
        "schema_version": 1,
        "method": "paired chronological moving-block bootstrap; noncircular overlapping source blocks",
        "settings": {"block_length_origins": block_length, "repetitions": repetitions, "seed": seed,
                     "random_generator": "Python random.Random", "confidence_level": 0.95,
                     "interval": "2.5th and 97.5th percentiles; linear interpolation",
                     "test_origins": count, "horizon": next(iter(horizons)), "units": "USDT",
                     "primary_comparison": "kronos_median_minus_chronos_median"},
        "comparisons": {
            name: {"left": left, "right": right,
                   "observed_mean_mae_difference": statistics.mean(differences[name]),
                   "bootstrap_95_percentile_interval": [percentile(distributions[name], .025),
                                                        percentile(distributions[name], .975)],
                   "interpretation": "Negative MAE difference favors left; positive favors right"}
            for name, (left, right) in definitions.items()
        },
        "per_origin": rows,
        "limitations": [
            "Exploratory conditional uncertainty for one saved asset/time period and one fixed forecast run",
            "Forty chronological origins are serially dependent; block length four does not establish independence",
            "Finite-sample percentile intervals and block choice are approximate and have no coverage guarantee",
            "No resampling of model training, market regimes or the twenty-path Monte Carlo seed",
            "Forecast-error comparisons do not establish trading profitability or general model dominance",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "output/visual-run-20261025/paired-evaluation.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    source_bytes = args.input.read_bytes()
    result = summarize(json.loads(source_bytes))
    result["source"] = {"file": args.input.name, "sha256": hashlib.sha256(source_bytes).hexdigest()}
    result["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    output = args.output or args.input.with_name("paired-uncertainty.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
