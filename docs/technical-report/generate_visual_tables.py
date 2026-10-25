#!/usr/bin/env python3
"""Package the reviewed fresh run, or rebuild its tables from committed evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SOURCE = REPO / "evidence/visual-evaluation-summary.json"
NOTICE = "% Generated from evidence/visual-evaluation-summary.json.\n"
LABELS = {
    "kronos_positive": "Kronos positive", "chronos2_positive": "Chronos positive",
    "kronos_cost_filter": "Kronos cost filter", "chronos2_cost_filter": "Chronos cost filter",
    "consensus_cost_filter": "Agreement + cost", "momentum_12h": "12h momentum",
    "persistence_cash": "Cash", "buy_hold": "Buy and hold",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def table(columns, headings, rows):
    lines = [NOTICE.rstrip(), r"\begin{tabular}{" + columns + "}", r"\toprule",
             " & ".join(headings) + r" \\", r"\midrule"]
    lines.extend(" & ".join(row) + r" \\" for row in rows)
    return "\n".join(lines + [r"\bottomrule", r"\end{tabular}", ""])


def pct(value, places=2):
    return "--" if value is None else f"{100 * value:.{places}f}" + r"\%"


def package(run):
    source = read(run / "run-manifest.json")
    assert source["protocol"]["test_windows"] == 40
    assert source["protocol"]["calibration_windows"] == 20
    source["bootstrap"] = read(run / "bootstrap-summary.json")
    source["strategy_settings"] = read(run / "strategy-summary.json")["settings"]
    source["dashboard_captures"] = read(run / "screenshots/capture-manifest.json")
    source["figure_manifest"] = read(run / "figures/figure-manifest.json")
    for capture in source["dashboard_captures"]["captures"]:
        assert sha(run / "screenshots" / capture["file"]) == capture["sha256"]
        for name, digest in capture["sources"].items():
            assert sha(run / name) == digest
    for item in source["figure_manifest"]["sources"]:
        assert sha(run / Path(item["path"]).name) == item["sha256"]
    names = ["run-manifest.json", "forecast.json", "evaluation.json", "comparison.json",
             "paired-evaluation.json", "strategy-summary.json", "bootstrap-summary.json"]
    source["local_artifact_sha256"] = {name: sha(run / name) for name in names}
    scripts = ["run_visual_evaluation.py", "capture_report_dashboard.py",
               "plot_visual_evaluation.py", "summarize_paired_uncertainty.py"]
    source["reviewed_script_sha256"] = {name: sha(REPO / "scripts" / name) for name in scripts}
    dest = HERE / "figures"
    dest.mkdir(exist_ok=True)
    for item in source["figure_manifest"]["figures"]:
        for kind in ("pdf", "png"):
            shutil.copy2(run / "figures" / item[kind], dest / item[kind])
    for name in ("figure-data.json", "figure-manifest.json"):
        shutil.copy2(run / "figures" / name, dest / name)
    for capture in source["dashboard_captures"]["captures"]:
        shutil.copy2(run / "screenshots" / capture["file"], dest / capture["file"])
    shutil.copy2(run / "screenshots/capture-manifest.json", dest / "capture-manifest.json")
    source["published_figure_sha256"] = {
        path.name: sha(path) for path in sorted(dest.iterdir()) if path.is_file()
    }
    SOURCE.write_text(json.dumps(source, indent=2, allow_nan=False) + "\n")


def artifacts(source):
    metrics = source["metrics"]
    points = source["point_metrics"]
    native = [("Persistence", metrics["persistence"]),
              ("Kronos sample mean", points["kronos_sample_mean"]),
              ("Kronos median", points["kronos_sample_median"]),
              ("Chronos-2 median", points["chronos2_median"])]
    result = {"visual-point.tex": table("lrrr", ["Point estimator", "MAE", "RMSE", "Terminal dir."], [
        [label, f"{m['close_mae']:.2f}", f"{m['close_rmse']:.2f}", pct(m["terminal_directional_accuracy"])]
        for label, m in native
    ])}
    result["visual-interval.tex"] = table("llrrr", ["Model", "Interval", "Coverage", "Width", "Pinball"], [
        [label, mode_label, pct(metrics[key][mode]["coverage80"]),
         f"{metrics[key][mode]['mean_interval_width']:.2f}", f"{metrics[key][mode]['mean_pinball_loss']:.2f}"]
        for key, label in [("kronos", "Kronos"), ("chronos2", "Chronos-2")]
        for mode, mode_label in [("raw", "Raw"), ("calibrated", "Expanded")]
    ])
    result["visual-strategies.tex"] = table("lrrrrr", ["Rule", "Trades", "Win rate", "Net", "Max DD", "Costs"], [
        [LABELS[r["strategy"]], str(r["trade_count"]), pct(r["traded_win_rate"]),
         pct(r["net_return"]), pct(r["max_drawdown"]), pct(r["fees_paid"] + r["slippage_cost"])]
        for r in source["strategy_comparison"]
    ])
    signal = source["latest_signal"]
    result["visual-signal.tex"] = table("lrrl", ["Model point", "12h return", "Raw range (USDT)", "Cost rule"], [
        [label, f"{signal[key]['terminal_return_pct']:+.3f}" + r"\%",
         f"{signal[key]['raw_terminal_q10']:.2f}--{signal[key]['raw_terminal_q90']:.2f}",
         signal[key]["cost_filtered_action"]]
        for key, label in [("kronos", "Kronos mean"), ("chronos2", "Chronos median")]
    ])
    boot = source["bootstrap"]["comparisons"]["kronos_median_minus_chronos_median"]
    cons = next(r for r in source["strategy_comparison"] if r["strategy"] == "consensus_cost_filter")
    macros = {
        "FreshKMedianMAE": f"{points['kronos_sample_median']['close_mae']:.2f}",
        "FreshCMedianMAE": f"{points['chronos2_median']['close_mae']:.2f}",
        "FreshBaselineMAE": f"{metrics['persistence']['close_mae']:.2f}",
        "FreshKMeanMAE": f"{points['kronos_sample_mean']['close_mae']:.2f}",
        "FreshConsensusNet": pct(cons["net_return"]),
        "FreshBootstrapDifference": f"{boot['observed_mean_mae_difference']:.2f}",
        "FreshBootstrapLow": f"{boot['bootstrap_95_percentile_interval'][0]:.2f}",
        "FreshBootstrapHigh": f"{boot['bootstrap_95_percentile_interval'][1]:.2f}",
        "FreshKReturn": f"{signal['kronos']['terminal_return_pct']:+.3f}" + r"\%",
        "FreshCReturn": f"{signal['chronos2']['terminal_return_pct']:+.3f}" + r"\%",
        "FreshThreshold": f"{signal['friction_threshold_pct']:.5f}" + r"\%",
    }
    result["visual-metrics.tex"] = NOTICE + "".join(
        "\\newcommand{\\" + key + "}{" + value + "}\n" for key, value in macros.items()
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-run", type=Path, help="Package reviewed outputs and figure receipts")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.import_run and args.check:
        parser.error("--check is read-only; do not combine with --import-run")
    if args.import_run:
        package(args.import_run.resolve())
    source = read(SOURCE)
    mismatches = []
    for name, value in artifacts(source).items():
        target = HERE / "tables" / name
        if args.check:
            if not target.exists() or target.read_text() != value:
                mismatches.append(str(target.relative_to(REPO)))
        else:
            target.write_text(value)
    if args.check:
        for name, digest in source["published_figure_sha256"].items():
            target = HERE / "figures" / name
            if not target.exists() or sha(target) != digest:
                mismatches.append(str(target.relative_to(REPO)))
        for name, digest in source["reviewed_script_sha256"].items():
            if sha(REPO / "scripts" / name) != digest:
                mismatches.append("scripts/" + name)
    if mismatches:
        print("Stale or missing visual evidence: " + ", ".join(mismatches), file=sys.stderr)
        return 1
    print("Verified visual evidence and five tables/macros" if args.check else "Generated five visual tables/macros")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
