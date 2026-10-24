"""Optional Chronos-2 close + past-volume comparison on the same UTC history."""
import threading
import numpy as np
import pandas as pd

_PIPELINES = {}
_LOCK = threading.Lock()


def compare_chronos(frame, kronos_result, *, device="cpu", model_id="amazon/chronos-2", revision=None):
    try:
        from chronos import Chronos2Pipeline
        from huggingface_hub import HfApi, snapshot_download
    except ImportError as error:
        raise RuntimeError("Install the compare extra: pip install -e '.[compare]'") from error
    from .data import normalize_frame
    history = normalize_frame(frame).iloc[-len(kronos_result["history"]):].copy()
    times = pd.DatetimeIndex(history["timestamps"]).tz_convert("UTC").tz_localize(None)
    if len(set(np.diff(times.asi8).tolist())) != 1:
        raise ValueError("Chronos-2 comparison requires regular timestamps without session gaps")
    future = pd.DatetimeIndex(pd.to_datetime(kronos_result["timestamps"], utc=True)).tz_localize(None)
    horizon = len(future)
    expected = pd.date_range(times[-1] + (times[1] - times[0]), periods=horizon, freq=times[1] - times[0])
    if not np.array_equal(future.asi8, expected.asi8):
        raise ValueError("Chronos-2 comparison future timestamps must continue the regular cadence")
    with _LOCK:
        resolved = HfApi().model_info(model_id, revision=revision).sha
        key = (model_id, resolved, device)
        if key not in _PIPELINES:
            path = snapshot_download(model_id, revision=resolved,
                                     allow_patterns=["*.json", "*.safetensors"])
            _PIPELINES.clear()
            _PIPELINES[key] = Chronos2Pipeline.from_pretrained(path, device_map=device)
        pipeline = _PIPELINES[key]
        data = pd.DataFrame({"item_id": "series", "timestamp": times,
                             "close": history["close"].to_numpy(), "volume": history["volume"].to_numpy()})
        future_df = pd.DataFrame({"item_id": "series", "timestamp": future})
        predicted = pipeline.predict_df(data, future_df=future_df, target="close",
            prediction_length=horizon, quantile_levels=[0.1, 0.5, 0.9],
            context_length=len(history), batch_size=16)
    predicted = predicted.loc[predicted["target_name"] == "close"].sort_values("timestamp")
    if len(predicted) != horizon or not np.array_equal(pd.DatetimeIndex(predicted["timestamp"]).asi8, future.asi8):
        raise RuntimeError("Unexpected Chronos-2 forecast index")
    points = predicted["predictions"].to_numpy(dtype=float)
    quantiles = {f"q{int(q*100)}": predicted[str(q)].to_numpy(dtype=float).tolist() for q in (0.1, 0.5, 0.9)}
    if not np.isfinite(points).all() or not np.isfinite(list(quantiles.values())).all():
        raise RuntimeError("Non-finite Chronos-2 output")
    expected_return = float((points[-1] / history["close"].iloc[-1] - 1) * 100)
    direction = "up" if expected_return > 0 else "down" if expected_return < 0 else "flat"
    return {"kronos": kronos_result, "chronos2": {"timestamps": kronos_result["timestamps"],
        "close": points.tolist(), "quantiles": quantiles, "direction": direction,
        "expected_return_pct": expected_return, "metadata": {"model": model_id,
        "revision": resolved, "device": device, "target": "close", "past_covariates": ["volume"]}},
        "directions_agree": direction == kronos_result["summary"]["direction"],
        "interpretation": "Directional agreement is descriptive; it does not establish forecast accuracy."}
