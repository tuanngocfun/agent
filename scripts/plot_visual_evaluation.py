#!/usr/bin/env python3
"""Render publication figures from the saved, real paired experiment exports.

No inference or market-data download occurs here. Inputs must share timestamps,
anchors and held-out observations. Figures are PDF+PNG with inspectable plotted
values and source SHA-256 hashes in figure-data.json and figure-manifest.json.

Usage: .venv/bin/python scripts/plot_visual_evaluation.py \
    --input-dir output/visual-run-20261025
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MaxNLocator, PercentFormatter
import numpy as np

COLORS = {
    "kronos": "#2465A6", "chronos2": "#C46A20", "actual": "#20262E",
    "persistence": "#757D86", "calibration": "#977A17", "consensus": "#6D6696",
    "winner": "#73853B", "grid": "#E4E7EA",
}
LABELS = {
    "kronos_positive": "Kronos: positive return",
    "chronos2_positive": "Chronos-2: positive return",
    "kronos_cost_filter": "Kronos: cost filter",
    "chronos2_cost_filter": "Chronos-2: cost filter",
    "consensus_cost_filter": "Consensus: cost filter",
    "momentum_12h": "12h momentum",
    "persistence_cash": "Cash / persistence",
    "buy_hold": "Buy and hold",
}
STYLE = {
    "font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 11,
    "axes.labelsize": 10, "xtick.labelsize": 9, "ytick.labelsize": 9,
    "legend.fontsize": 9, "axes.spines.top": False, "axes.spines.right": False,
    "axes.edgecolor": "#6B727A", "axes.labelcolor": "#20262E",
    "text.color": "#20262E", "xtick.color": "#424A53", "ytick.color": "#424A53",
    "axes.titleweight": "semibold", "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.axisbelow": True, "pdf.fonttype": 42, "ps.fonttype": 42,
    "savefig.facecolor": "white", "lines.linewidth": 1.8,
}
plt.rcParams.update(STYLE)


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def finite(values, name: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if not np.isfinite(arr).all():
        raise ValueError(f"Non-finite plotted values in {name}")
    return arr


def dates(values):
    return [datetime.fromisoformat(x.replace("Z", "+00:00")) for x in values]


def time_axis(ax, values, *, rotation=0):
    """Keep first/latest reviewed times visible with a shared calendar formatter."""
    x = np.asarray(mdates.date2num(values), float)
    span_hours = float(x[-1]-x[0])*24
    candidates = [1,2,3,4,6,8,12,24,48,72,96,168,336,720,2160,8760]
    step_hours = next((v for v in candidates if span_hours/v <= 4), candidates[-1])
    step = step_hours/24
    ticks = np.arange(math.ceil(x[0]/step)*step, x[-1], step)
    ticks = ticks[(ticks > x[0]) & (ticks < x[-1])]
    # Endpoints are mandatory; remove crowded neighboring calendar ticks.
    sep = max(float(x[-1]-x[0])*.10, 1e-6)
    ticks = [x[0]] + [v for v in ticks if v-x[0] > sep and x[-1]-v > sep] + [x[-1]]
    ax.set_xticks(ticks)
    span = x[-1] - x[0]
    fmt = "%d %b\n%H:%M" if span < 4 else "%d %b"
    ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt, tz=timezone.utc))
    ax.tick_params(axis="x", rotation=rotation)
    ax.set_xlim(x[0], x[-1])


def grid(ax):
    ax.grid(axis="y", color=COLORS["grid"], linewidth=.7)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))


def save(fig, output: Path, stem: str):
    fig.savefig(output/f"{stem}.pdf", bbox_inches="tight", pad_inches=.08)
    fig.savefig(output/f"{stem}.png", dpi=180, bbox_inches="tight", pad_inches=.08)
    plt.close(fig)


def close_mean(forecast):
    index = forecast["features"].index("close")
    return finite(forecast["mean"], "forecast mean")[:, index]


def latest_figure(forecast, comparison, output):
    kronos, chronos = comparison["kronos"], comparison["chronos2"]
    if forecast["timestamps"] != kronos["timestamps"] or kronos["timestamps"] != chronos["timestamps"]:
        raise ValueError("Latest forecast timestamps differ across inputs")
    history = kronos["history"]
    if history[-1]["timestamps"] != forecast["history"][-1]["timestamps"]:
        raise ValueError("Latest forecast origins differ")
    ts = dates(kronos["timestamps"])
    hist_t = dates([v["timestamps"] for v in history])
    hist_y = finite([v["close"] for v in history], "historical close")
    anchor = float(hist_y[-1])
    km = close_mean(kronos)
    cm = finite(chronos["quantiles"]["q50"], "Chronos median")
    kq = kronos["quantiles"]
    cq = chronos["quantiles"]
    fig, axes = plt.subplots(2, 1, figsize=(6.3, 6.2), layout="constrained")
    first = axes[0]
    first.plot(hist_t, hist_y, color=COLORS["actual"], lw=1.5, label="Observed close")
    for key, quantiles, point, label, style in [
        ("kronos", kq, km, "Kronos sample mean", "-"),
        ("chronos2", cq, cm, "Chronos-2 median", "--"),
    ]:
        for ax in axes:
            ax.fill_between(ts, finite(quantiles["q10"], key+" q10"), finite(quantiles["q90"], key+" q90"),
                            color=COLORS[key], alpha=.14, linewidth=0)
            ax.plot([hist_t[-1]]+ts, [anchor]+point.tolist(), color=COLORS[key], ls=style,
                    marker="o" if key=="kronos" else "s", markersize=3, label=label)
    for ax in axes:
        ax.axhline(anchor, color=COLORS["persistence"], ls=":", lw=1.2, label="Last-close persistence")
        ax.axvline(hist_t[-1], color=COLORS["actual"], lw=.8, ls=":")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:,.0f}"))
        ax.set_ylabel("BTCUSDT close (USDT)")
        grid(ax)
    time_axis(axes[0], hist_t+ts)
    time_axis(axes[1], [hist_t[-1]]+ts)
    axes[0].set_title("(a) Observed context and latest forecast")
    axes[1].set_title("(b) Forecast horizon in detail")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside upper center", ncols=2, frameon=False, fontsize=8.5)
    fig.supxlabel("Candle-open timestamp (UTC)", fontsize=10)
    save(fig, output, "latest_forecast")
    return {
        "history": [{"timestamp": h["timestamps"], "close": h["close"]} for h in history],
        "forecast": [{"timestamp": t, "kronos_sample_mean": float(km[i]), "kronos_q10": kq["q10"][i],
                      "kronos_q90": kq["q90"][i], "chronos_median": float(cm[i]),
                      "chronos_q10": cq["q10"][i], "chronos_q90": cq["q90"][i]} for i,t in enumerate(kronos["timestamps"])],
        "anchor": anchor,
        "caption": "Latest forecast from the same closed-candle history. Blue is the Kronos sample mean; orange is the Chronos-2 native median. Shading spans each model's raw q10 to q90. These are nominal 80% quantile ranges, not demonstrated future coverage. The dotted horizontal reference repeats the last observed close. No future actuals are scored in this panel.",
    }


def test_windows(paired):
    rows = [w for w in paired["per_window"] if w["split"] == "test"]
    if not rows:
        raise ValueError("No test windows to plot")
    h = len(rows[0]["actual_close"])
    previous_end = None
    for w in rows:
        finite(w["actual_close"], "actual close")
        if len(w["timestamps"]) != h or len(w["actual_close"]) != h:
            raise ValueError("Held-out horizons have unequal lengths")
        if previous_end is not None and dates(w["timestamps"])[0] <= previous_end:
            raise ValueError("Test label windows overlap or are unordered")
        previous_end = dates(w["timestamps"])[-1]
        for key in ("kronos", "chronos2"):
            for field in ("forecast_close", "median_close", "raw_lower", "raw_upper", "calibrated_lower", "calibrated_upper"):
                if len(w[key][field]) != h:
                    raise ValueError(f"{key} {field} horizon differs")
    return rows


def heldout_figure(rows, output):
    total = len(rows)
    selection = np.unique(np.rint(np.linspace(0,total-1,min(4,total))).astype(int))
    rows = [rows[i] for i in selection]
    n = len(rows)
    cols = min(2, n)
    nr = math.ceil(n/cols)
    fig, axes = plt.subplots(nr, cols, figsize=(6.3, 2.55*nr+.55), squeeze=False, layout="constrained", sharex=True, sharey=True)
    all_vals = []
    data=[]
    for ax,w in zip(axes.flat,rows):
        h = len(w["actual_close"])
        x = np.arange(1,h+1)
        anchor = float(w["last_close"])
        transform = lambda v: (finite(v,"test close")/anchor-1)*100
        actual=transform(w["actual_close"])
        all_vals.append(actual)
        ax.plot(x,actual,color=COLORS["actual"],marker="o",markersize=2.7,lw=1.5,label="Observed")
        record={"origin_index":w["origin_index"],"history_end":w["history_end"],"last_close":anchor,"timestamps":w["timestamps"],"actual_return_pct":actual.tolist()}
        for key,label,style in [("kronos","Kronos median","-"),("chronos2","Chronos-2 median","--")]:
            model=w[key]
            point,lo,hi=(transform(model[k]) for k in ("median_close","raw_lower","raw_upper"))
            all_vals.extend([lo,hi])
            ax.fill_between(x,lo,hi,color=COLORS[key],alpha=.13,lw=0)
            ax.plot(x,point,color=COLORS[key],ls=style,lw=1.5,label=label)
            record[key]={"median_return_pct":point.tolist(),"raw_lower_return_pct":lo.tolist(),"raw_upper_return_pct":hi.tolist()}
        ax.axhline(0,color=COLORS["persistence"],ls=":",lw=1)
        origin=dates([w["history_end"]])[0]
        ax.set_title(f"Origin {w['origin_index']} | {origin:%d %b %H:%M} UTC",fontsize=9.5)
        ax.set_xlim(1,h)
        ax.set_xticks(sorted(set([1,h//2,h])))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v,_:f"{v:+.1f}%"))
        grid(ax)
        data.append(record)
    for ax in list(axes.flat)[n:]:
        ax.set_visible(False)
    low=min(float(v.min()) for v in all_vals)
    high=max(float(v.max()) for v in all_vals)
    margin=(high-low)*.08 if high>low else .1
    axes[0,0].set_ylim(low-margin,high+margin)
    handles,labels=axes[0,0].get_legend_handles_labels()
    fig.legend(handles,labels,loc="outside upper center",ncols=3,frameon=False)
    fig.supxlabel("Forecast horizon (hours)")
    fig.supylabel("Close return from the origin's last observed close")
    save(fig,output,"heldout_forecasts")
    return {"selected_origin_order_zero_based":selection.tolist(),"total_test_windows":total,"windows":data,"caption": f"Four predetermined, evenly spaced chronological origins (or all origins when fewer than four) from {total} frozen test windows; selection includes the first and latest test origins. Both models use identical horizons and observed targets. Point lines use medians for an aligned comparison; blue and orange bands show raw q10 to q90. Returns are normalized to each origin's last observed close, and all panels share the same vertical scale. The zero reference is last-close persistence. Calibration windows do not appear here."}


def error_calibration_figure(rows,output):
    data=[]
    n=len(rows)
    h=len(rows[0]["actual_close"])
    for w in rows:
        actual=finite(w["actual_close"],"actual")
        record={"origin_index":w["origin_index"],"history_end":w["history_end"],
                "persistence_mae":float(np.mean(np.abs(actual-float(w["last_close"]))))}
        for key in ("kronos","chronos2"):
            record[key+"_median_mae"]=float(np.mean(np.abs(actual-finite(w[key]["median_close"],"median"))))
        data.append(record)
    fig=plt.figure(figsize=(6.3,6.2),layout="constrained")
    gs=fig.add_gridspec(2,2,height_ratios=[1.1,1])
    err=fig.add_subplot(gs[0,:])
    cov=fig.add_subplot(gs[1,0])
    width=fig.add_subplot(gs[1,1],sharex=cov)
    origin_times=dates([r["history_end"] for r in data])
    for key,label,color,ls,marker in [("kronos_median_mae","Kronos median",COLORS["kronos"],"-","o"),("chronos2_median_mae","Chronos-2 median",COLORS["chronos2"],"--","s"),("persistence_mae","Persistence",COLORS["persistence"],":","^")]:
        err.plot(origin_times,[r[key] for r in data],color=color,ls=ls,marker=marker,markersize=2.5,lw=1.2,label=label)
    time_axis(err,origin_times)
    err.set_xlabel("Forecast-origin timestamp (UTC)")
    err.set_ylabel("Mean absolute close error (USDT)")
    err.set_title("(a) Paired point error by held-out origin")
    err.set_ylim(bottom=0)
    err.legend(frameon=False,fontsize=8)
    grid(err)
    actual=np.stack([w["actual_close"] for w in rows])
    horizon=np.arange(1,h+1)
    horizon_data=[]
    for key,label in [("kronos","Kronos"),("chronos2","Chronos-2")]:
        for prefix,ls,suffix in [("raw","-","raw"),("calibrated","--","calibrated")]:
            lo=np.stack([w[key][prefix+"_lower"] for w in rows])
            hi=np.stack([w[key][prefix+"_upper"] for w in rows])
            coverage=np.mean((actual>=lo)&(actual<=hi),axis=0)
            widths=np.mean(hi-lo,axis=0)
            cov.plot(horizon,coverage,color=COLORS[key],ls=ls,marker="o" if prefix=="raw" else "s",markersize=3,label=f"{label} {suffix}")
            width.plot(horizon,widths,color=COLORS[key],ls=ls,marker="o" if prefix=="raw" else "s",markersize=3)
            horizon_data.append({"model":key,"interval":prefix,"coverage_by_horizon":coverage.tolist(),"mean_width_usdt_by_horizon":widths.tolist()})
    cov.axhline(.8,color=COLORS["actual"],ls=":",lw=1,label="Nominal 80%")
    cov.yaxis.set_major_formatter(PercentFormatter(1,decimals=0))
    cov.set_ylim(-.04,1.05)
    cov.set_ylabel("Empirical coverage")
    cov.set_title("(b) Test coverage",fontsize=10)
    cov.set_xlabel("Forecast horizon (hours)")
    cov.text(.04,.05,"Solid: raw\nDashed: calibrated",transform=cov.transAxes,fontsize=8,va="bottom")
    width.set_title("(c) Interval width",fontsize=10)
    width.set_ylabel("Mean width (USDT)")
    width.set_xlabel("Forecast horizon (hours)")
    width.set_ylim(bottom=0)
    width.set_xticks(sorted(set([1,*range(3,h,3),h])))
    for ax in (cov,width):
        ax.set_xlim(.8,h+.2)
        grid(ax)
    save(fig,output,"paired_errors_calibration")
    return {"per_origin_mae":data,"per_horizon_intervals":horizon_data,
            "caption": f"Upper: median-based MAE for each identical test origin, with persistence scored on the same actual closes. Lower: empirical q10-q90 coverage and mean interval width by horizon, before and after separately fitted, frozen per-model calibration. Each coverage point has {n} test observations; the complete test grid has {n*h} origin-horizon observations. The 80% guide is nominal, and observed coverage is not a future coverage guarantee. Larger calibrated widths can raise coverage while reducing precision."}


def strategy_figure(strategy,output):
    all_rows=strategy["comparison"]
    strategies=strategy["strategies"]
    ranked=sorted(all_rows,key=lambda r:float(r["net_return"]),reverse=True)
    winner=ranked[0]["strategy"]
    names=list(dict.fromkeys(["kronos_positive","chronos2_positive","consensus_cost_filter","buy_hold",winner]))
    names=[name for name in names if name in strategies]
    color_map={"kronos_positive":COLORS["kronos"],"chronos2_positive":COLORS["chronos2"],"consensus_cost_filter":COLORS["consensus"],"buy_hold":COLORS["actual"]}
    if winner not in color_map:
        color_map[winner]=COLORS["winner"]
    fig=plt.figure(figsize=(6.3,7.2),layout="constrained")
    gs=fig.add_gridspec(3,1,height_ratios=[1.1,.8,1.5])
    equity=fig.add_subplot(gs[0])
    dd=fig.add_subplot(gs[1],sharex=equity)
    bar=fig.add_subplot(gs[2])
    plotted=[]
    all_times=[]
    for i,name in enumerate(names):
        result=strategies[name]
        curve=result["equity_curve"]
        ts=dates([p["timestamp"] for p in curve])
        eq=finite([p["equity"] for p in curve],name+" equity")
        draw=finite([p["drawdown"] for p in curve],name+" drawdown")
        # Ledger uses positive drawdown magnitudes; plot losses below zero.
        draw=-np.abs(draw)*100
        ls=["-","--","-.",":","-"][i]
        label=LABELS.get(name,name)
        equity.plot(ts,(eq-1)*100,color=color_map[name],ls=ls,label=label)
        dd.plot(ts,draw,color=color_map[name],ls=ls)
        all_times.extend(ts)
        plotted.append({"strategy":name,"curve":curve})
    equity.axhline(0,color=COLORS["persistence"],ls=":",lw=1)
    dd.axhline(0,color=COLORS["persistence"],lw=.8)
    equity.set_ylabel("Net equity return (%)")
    dd.set_ylabel("Drawdown (%)")
    equity.set_title("(a) Primary signals and selected baselines")
    handles, labels = equity.get_legend_handles_labels()
    fig.legend(handles,labels,frameon=False,fontsize=8,ncols=2,loc="outside upper center")
    equity.tick_params(labelbottom=False)
    time_axis(dd,[min(all_times),max(all_times)])
    dd.set_xlabel("Candle-open timestamp (UTC)")
    for ax in (equity,dd):
        grid(ax)
    labels=[LABELS.get(r["strategy"],r["strategy"]) for r in ranked]
    values=[float(r["net_return"])*100 for r in ranked]
    ys=np.arange(len(ranked))
    bars=bar.barh(ys,values,color=[color_map.get(r["strategy"],"#B4BBC2") for r in ranked],height=.62)
    bar.set_yticks(ys,labels,fontsize=8.5)
    bar.invert_yaxis()
    bar.axvline(0,color=COLORS["actual"],lw=.8)
    bar.set_xlabel("Net return (%)")
    bar.set_title("(c) All predefined rules")
    dd.set_title("(b) Sampled drawdown",fontsize=10)
    extent=max(max(abs(v) for v in values),.1)
    bar.set_xlim(min(min(values)-extent*.06,-extent*.15),max(max(values)+extent*.75,extent*.75))
    for r,b,v in zip(ranked,bars,values):
        trade_count=int(r["trade_count"])
        annotation_x=max(max(values),0)+extent*.035
        bar.text(annotation_x,b.get_y()+b.get_height()/2,
                 f"{v:+.2f}% | {trade_count} trade{'s' if trade_count!=1 else ''}",
                 ha="left",va="center",fontsize=8)
    bar.grid(axis="x",color=COLORS["grid"],lw=.7)
    save(fig,output,"strategy_equity")
    return {"displayed_curves":plotted,"all_strategy_summaries":all_rows,"selected_best_net_rule":winner,
            "caption": "Paper execution on the frozen non-overlapping test windows only. Upper panels show the two positive-return model rules, consensus cost filter, buy-and-hold baseline, and the best observed net rule if different; this last selection is descriptive and made after scoring. Lower panel includes every predefined rule and actual completed trade counts. Net equity includes the exported fees and slippage. Drawdown is sampled at ledger marks, excludes intrabar extremes, and is shown below zero. No annualization or out-of-sample strategy-selection claim is made."}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir",type=Path,default=Path("output/visual-run-20261025"))
    parser.add_argument("--output-dir",type=Path)
    args=parser.parse_args()
    output=args.output_dir or args.input_dir/"figures"
    output.mkdir(parents=True,exist_ok=True)
    required=["forecast.json","comparison.json","paired-evaluation.json","strategy-summary.json"]
    inputs={name:read(args.input_dir/name) for name in required}
    rows=test_windows(inputs["paired-evaluation.json"])
    data={
        "latest_forecast":latest_figure(inputs["forecast.json"],inputs["comparison.json"],output),
        "heldout_forecasts":heldout_figure(rows,output),
        "paired_errors_calibration":error_calibration_figure(rows,output),
        "strategy_equity":strategy_figure(inputs["strategy-summary.json"],output),
    }
    (output/"figure-data.json").write_text(json.dumps(data,indent=2,allow_nan=False)+"\n")
    manifest={
        "generated_at_utc":datetime.now(timezone.utc).isoformat(),
        "generator":"scripts/plot_visual_evaluation.py",
        "sources":[{"path":str(args.input_dir/name),"sha256":hashlib.sha256((args.input_dir/name).read_bytes()).hexdigest()} for name in required],
        "test_windows":len(rows),"test_horizon":len(rows[0]["actual_close"]),
        "point_semantics":{"latest_kronos":"sample mean","latest_chronos2":"native q50 median","heldout_both":"median_close","paired_mae_both":"median_close"},
        "interval_semantics":"Raw model q10-q90 versus frozen additive per-horizon calibration; empirical coverage, no future guarantee.",
        "figures":[{"name":name,"pdf":name+".pdf","png":name+".png","caption":detail["caption"]} for name,detail in data.items()],
    }
    (output/"figure-manifest.json").write_text(json.dumps(manifest,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"output_dir":str(output),"figures":list(data),"test_windows":len(rows)},indent=2))


if __name__=="__main__":
    main()
