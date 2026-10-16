#!/usr/bin/env python3
"""Render static scientific figures from an already audited primary summary.

No Kubernetes/model execution or synthetic-data fallback. Wilson intervals are
descriptive for designed tasks, not a production-population inference.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import tempfile

ORDER = [("one-shot", "clean"), ("self-review", "clean"), ("feedback", "clean"),
         ("feedback-filtered", "clean"), ("feedback", "injection"), ("feedback-filtered", "injection")]
STATES = ["correct", "task_failure", "provider_failure", "infrastructure_failure", "deadline_exceeded", "missing", "invalid_evidence"]
NAMES = ["Task correct", "Task failure", "Provider failure", "Infrastructure failure", "Deadline exceeded", "Missing", "Invalid evidence"]
COLORS = ["#347866", "#B75D39", "#8067A7", "#4D7BA4", "#AD8A2F", "#CFD4DA", "#A2416A"]
HATCHES = ["", "//", "..", "\\\\", "xx", "--", "++"]


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def integer(value):
    if type(value) is not int or value < 0:
        raise ValueError("Expected a nonnegative integer count")
    return value


def wilson(successes, count):
    z = 1.959963984540054
    rate, denominator = successes / count, 1 + z * z / count
    center = (rate + z * z / (2 * count)) / denominator
    half = z * math.sqrt(rate * (1 - rate) / count + z * z / (4 * count * count)) / denominator
    return rate, max(0, center - half), min(1, center + half)


def reviewed_rows(summary):
    if summary.get("schema_version") != "robustness-v2-report-v1":
        raise ValueError("Expected the audited robustness-v2 primary summary")
    coverage = summary["coverage"]
    if coverage["base_cases"] != 12 or coverage["registered_trials"] != 54:
        raise ValueError("This figure contract requires 12 cases and 54 registered cells")
    indexed = {(group["method_id"], group["condition"]): group for group in summary["groups"]}
    if len(indexed) != 6 or len(summary["groups"]) != 6 or set(indexed) != set(ORDER):
        raise ValueError("Unexpected or duplicate method/condition groups")
    rows, total = [], Counter()
    for method, condition in ORDER:
        group = indexed[(method, condition)]
        count = 12 if condition == "clean" and method != "feedback-filtered" else 6
        if group["model_id"] != "qwen25-3b" or group["registered_trials"] != count or group["base_case_count"] != count:
            raise ValueError("Unexpected model, repetitions, or case denominator")
        outcomes = {state: integer(group["outcomes"].get(state, 0)) for state in STATES}
        if set(group["outcomes"]) - set(STATES) or sum(outcomes.values()) != count:
            raise ValueError("Outcome states must partition every registered cell")
        success = integer(group["case_success"]["successes"])
        if success > count or success != group["correct_trials"] or success != outcomes["correct"] or group["case_success"]["cases"] != count:
            raise ValueError("Correct-task count disagrees with the audited denominator")
        rate, low, high = wilson(success, count)
        for key, value in zip(("rate", "low", "high"), (rate, low, high)):
            if not math.isclose(group["case_success"][key], value, rel_tol=0, abs_tol=1e-12):
                raise ValueError("Reported Wilson interval does not reproduce")
        label = method.replace("-", " ").capitalize() + " / " + condition + f" ({count} cases)"
        rows.append({"model_id": group["model_id"], "method_id": method, "condition": condition,
                     "label": label, "correct": success, "cases": count, "rate": rate,
                     "wilson95_low": low, "wilson95_high": high, "outcomes": outcomes})
        total.update(outcomes)
    if any(total[state] != coverage["outcomes"].get(state, 0) for state in STATES):
        raise ValueError("Group outcome counts do not reconcile with campaign coverage")
    return rows


def render(summary, raw, output):
    rows = reviewed_rows(summary)
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix=".mpl-config-", dir=output) as cache:
        os.environ["MPLCONFIGDIR"] = cache
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.spines.top": False,
                             "axes.spines.right": False, "svg.fonttype": "none", "svg.hashsalt": "robustness-v2",
                             "pdf.fonttype": 42, "figure.facecolor": "white", "axes.facecolor": "white"})
        source = {"summary_sha256": hashlib.sha256(raw).hexdigest(), "plan_id": summary["plan_id"],
                  "source_sha256": summary["source_sha256"], "rows": rows, "outcome_order": STATES,
                  "population": "12 designed related cases; one execution per registered cell; Qwen2.5 3B CPU",
                  "uncertainty": "Wilson 95%, descriptive; no population or causal superiority claim",
                  "versions": {"python": platform.python_version(), "matplotlib": matplotlib.__version__, "numpy": np.__version__}}
        (output / "source-chart-data.json").write_text(json.dumps(source, indent=2, sort_keys=True, allow_nan=False) + "\n")
        def canvas(title, xlabel):
            fig, ax = plt.subplots(figsize=(12, 7.4))
            fig.subplots_adjust(left=.35, right=.89, top=.82, bottom=.24)
            fig.suptitle(title, x=.35, y=.95, ha="left", fontsize=16, fontweight="bold")
            fig.text(.35, .90, "Qwen2.5 3B · CPU · designed suite: 12 base cases", fontsize=11)
            y = np.arange(len(rows))
            ax.set_yticks(y, [row["label"] for row in rows]); ax.invert_yaxis()
            ax.set_xlabel(xlabel); ax.grid(axis="x", color="#E4E7EA", linewidth=.7); ax.set_axisbelow(True)
            return fig, ax, y
        def save(fig, name):
            for extension in ("svg", "png", "pdf"):
                metadata = {"Creator": "Reproducible robustness figures"} if extension != "png" else {"Software": "Reproducible robustness figures"}
                if extension == "svg": metadata["Date"] = None
                if extension == "pdf": metadata.update(CreationDate=None, ModDate=None)
                fig.savefig(output / (name + "." + extension), dpi=200, metadata=metadata)
            plt.close(fig)
        fig, ax, y = canvas("Task-correct outcomes with descriptive uncertainty", "Task-correct base cases (%)")
        for index, row in enumerate(rows):
            rate, low, high = [100 * row[key] for key in ("rate", "wilson95_low", "wilson95_high")]
            # Wilson arithmetic can leave a sub-ULP positive lower bound at
            # zero successes; Matplotlib requires nonnegative error widths.
            ax.errorbar(rate, index, xerr=[[max(0.0, rate-low)], [max(0.0, high-rate)]], fmt="o", color="#315F85", capsize=4, markersize=7)
            ax.text(1.025, index, f"{row['correct']}/{row['cases']} ({rate:.1f}%)", transform=ax.get_yaxis_transform(), va="center", fontsize=10)
        ax.set_xlim(0, 100); ax.set_xticks([0, 25, 50, 75, 100])
        fig.text(.04, .12, "Points: correct / registered base cases. Bars: Wilson 95% intervals (descriptive).", fontsize=10)
        fig.text(.04, .075, "Six-case rows use a preselected subset; compare matched cases. Related tasks, one execution per cell.", fontsize=10)
        save(fig, "method-success-intervals")
        fig, ax, y = canvas("Outcomes across every registered model cell", "Registered model cells (count)")
        left = np.zeros(len(rows))
        for state, name, color, hatch in zip(STATES, NAMES, COLORS, HATCHES):
            values = np.array([row["outcomes"][state] for row in rows])
            ax.barh(y, values, left=left, height=.65, color=color, edgecolor="white", hatch=hatch, label=name)
            for index, value in enumerate(values):
                if value: ax.text(left[index] + value/2, index, str(value), va="center", ha="center", color="black" if state in {"missing", "deadline_exceeded"} else "white", fontsize=10)
            left += values
        for index, row in enumerate(rows): ax.text(row["cases"] + .15, index, f"N={row['cases']}", va="center", fontsize=10)
        ax.set_xlim(0, 13.3); ax.set_xticks(range(0, 13, 2))
        fig.legend(loc="lower center", bbox_to_anchor=(.52, .10), ncol=4, frameon=False, fontsize=9)
        fig.text(.04, .035, "Every registered cell remains visible. Zero-count categories remain in the legend; cells are not independent cases.", fontsize=10)
        save(fig, "registered-outcome-counts")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.summary.is_symlink() or not args.summary.is_file() or args.summary.stat().st_size > 25_000_000:
        parser.error("Summary must be a bounded regular file")
    if args.output.exists() or any(path.is_symlink() for path in (args.output, *args.output.parents)):
        parser.error("Output must be fresh and have no symlink ancestors")
    try:
        raw = args.summary.read_bytes()
        summary = json.loads(raw, object_pairs_hook=unique_object, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        render(summary, raw, args.output)
    except (OSError, ValueError, TypeError, KeyError) as error:
        parser.exit(2, f"Figures refused: {type(error).__name__}: {error}\n")


if __name__ == "__main__":
    main()
