"""Run comparable zero-shot, predictor-only, and two-stage experiments.

Four chronological partitions are mandatory: optimization, checkpoint-selection
validation, interval calibration, and final test. Every variant scores exactly
the same forecast origins with identical generation settings.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import gc
import os
from pathlib import Path
import sys

import pandas as pd

from .data import normalize_frame
from .evaluation import save_evaluation, walk_forward
from .forecast import KronosForecaster, _checkpoint
from .training import train


def _boundary(config: dict, key: str) -> pd.Timestamp:
    if key not in config or config[key] is None:
        raise ValueError(f"Ablation requires {key} for four separate chronological partitions")
    try:
        value = pd.Timestamp(config[key])
        if pd.isna(value):
            raise ValueError("Missing boundary")
        return value.tz_localize("UTC") if value.tzinfo is None else value.tz_convert("UTC")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{key} must be a valid timestamp") from exc


def _release_memory() -> None:
    gc.collect()
    torch = sys.modules.get("torch")
    if torch is not None and torch.cuda.is_available():
        torch.cuda.empty_cache()


def _signature(report: dict) -> list:
    return [(window["split"], window["origin_index"], window["timestamps"])
            for window in report["per_window"]]


def run_ablation(training_config: dict, forecast_config, max_windows: int = 8) -> dict:
    """Train two adaptations and compare them with the original pretrained model.

    `training_config` uses the training module's configuration, additionally
    requiring `calibration_end > validation_end`. Its `output_dir` is the new
    experiment root; stage checkpoints are placed beneath variant subdirectories.
    All boundaries are exclusive ends: train < train_end; validation <
    validation_end; calibration < calibration_end; test < optional test_end.
    Evaluation borrows only historical context across these boundaries.

    A nonempty output root is rejected to preserve prior evidence. This is a
    single-process orchestrator; distributed training is available separately.
    Results report forecast quality only, without trading/profitability claims.
    """
    config = dict(training_config)
    if int(os.environ.get("WORLD_SIZE", "1")) > 1:
        raise ValueError("Run ablation in a single process; use the training CLI for distributed training")
    if "model_config" in config or "tokenizer_config" in config:
        raise ValueError("Ablation requires pretrained checkpoints, not random architecture test configs")
    if "data_csv" not in config:
        raise ValueError("Ablation requires data_csv")
    train_end = _boundary(config, "train_end")
    validation_end = _boundary(config, "validation_end")
    calibration_end = _boundary(config, "calibration_end")
    if not train_end < validation_end < calibration_end:
        raise ValueError("Require train_end < validation_end < calibration_end")
    test_end = _boundary(config, "test_end") if config.get("test_end") is not None else None
    if test_end is not None and test_end <= calibration_end:
        raise ValueError("test_end must follow calibration_end")
    if forecast_config.lookback != int(config.get("context_length", 128)):
        raise ValueError("Forecast lookback must match training context_length for comparable ablations")
    if forecast_config.horizon != int(config.get("horizon", 16)):
        raise ValueError("Forecast horizon must match training horizon for comparable ablations")

    evaluation_stride = config.get("evaluation_stride", forecast_config.horizon)
    if isinstance(evaluation_stride, bool) or not isinstance(evaluation_stride, int) or evaluation_stride < 1:
        raise ValueError("evaluation_stride must be a positive integer")
    calibration_fraction = config.get("calibration_fraction", .5)
    if (isinstance(calibration_fraction, bool) or not isinstance(calibration_fraction, (int, float))
            or not 0 < calibration_fraction < 1):
        raise ValueError("calibration_fraction must be strictly between 0 and 1")
    if isinstance(max_windows, bool) or not isinstance(max_windows, int) or max_windows < 2:
        raise ValueError("max_windows must be an integer allowing at least two windows")
    if not 1 <= int(max_windows * calibration_fraction) < max_windows:
        raise ValueError("calibration_fraction leaves an empty calibration or test budget")

    data_path = Path(config["data_csv"]).expanduser().resolve()
    raw = pd.read_csv(data_path)
    timestamp_column = config.get("timestamp_column", "timestamps")
    if timestamp_column != "timestamps" and timestamp_column in raw:
        raw = raw.rename(columns={timestamp_column: "timestamps"})
    frame = normalize_frame(raw)
    frame.attrs["provider"] = "csv"
    if test_end is not None:
        frame = frame.loc[frame["timestamps"] < test_end].reset_index(drop=True)
    # Check scored partitions before downloading weights or starting training.
    origins = range(forecast_config.lookback, len(frame) - forecast_config.horizon + 1, evaluation_stride)
    calibration_origins = [origin for origin in origins
                           if frame["timestamps"].iloc[origin] >= validation_end
                           and frame["timestamps"].iloc[origin + forecast_config.horizon - 1] < calibration_end]
    test_origins = [origin for origin in origins if frame["timestamps"].iloc[origin] >= calibration_end]
    if not calibration_origins or not test_origins:
        raise ValueError("Ablation requires complete forecast windows in independent calibration and test partitions")
    output = Path(config.get("output_dir", "outputs/ablation")).expanduser().resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise FileExistsError(f"Ablation output must be empty; choose a new output_dir: {output}")
    output.mkdir(parents=True, exist_ok=True)
    model_id = str(config.get("model_path", "NeoQuasar/Kronos-small"))
    tokenizer_id = str(config.get("tokenizer_path", "NeoQuasar/Kronos-Tokenizer-base"))
    # Resolve mutable Hub names once, so every branch starts with identical bytes.
    initial_model, initial_model_metadata = _checkpoint(model_id, config.get("model_revision"))
    initial_tokenizer, initial_tokenizer_metadata = _checkpoint(tokenizer_id, config.get("tokenizer_revision"))
    model_id, tokenizer_id = str(initial_model), str(initial_tokenizer)
    config["model_path"], config["tokenizer_path"] = model_id, tokenizer_id
    upstream_dir = config.get("kronos_path", Path(__file__).resolve().parents[1] / "vendor/Kronos")
    evaluation_options = {
        "stride": evaluation_stride,
        "max_windows": max_windows,
        "calibration_fraction": calibration_fraction,
        "evaluation_start": validation_end,
        "calibration_end": calibration_end - pd.Timedelta(1, unit="ns"),
    }
    reports = {}
    variants = {}
    expected_signature = None
    for variant in ("zero-shot", "predictor-only", "two-stage"):
        manifest = None
        if variant == "zero-shot":
            variant_model, variant_tokenizer = model_id, tokenizer_id
        else:
            stage_config = dict(config)
            stage_config["output_dir"] = str(output / variant)
            stage_config["mode"] = variant
            manifest = train(stage_config)
            if manifest.get("test_used_for_training_or_selection") is not False:
                raise RuntimeError("Training manifest does not confirm untouched held-out labels")
            variant_model = manifest["model_path"]
            variant_tokenizer = manifest["tokenizer_path"]
        forecaster = KronosForecaster(
            upstream_dir=upstream_dir,
            model_id=variant_model,
            tokenizer_id=variant_tokenizer,
            device=config.get("device"),
        )
        report = walk_forward(frame, forecaster, forecast_config, **evaluation_options)
        current_signature = _signature(report)
        if expected_signature is None:
            expected_signature = current_signature
        elif current_signature != expected_signature:
            raise RuntimeError("Ablation variants did not score exactly the same calibration/test origins")
        report["ablation"] = {
            "variant": variant,
            "checkpoint_selection_validation_end_exclusive": validation_end.isoformat(),
            "calibration_end_exclusive": calibration_end.isoformat(),
            "calibration_reuses_checkpoint_selection_validation": False,
        }
        report_path = save_evaluation(report, output / "reports" / f"{variant}.json")
        reports[variant] = report
        variants[variant] = {
            "report_path": str(report_path),
            "model_path": str(variant_model),
            "tokenizer_path": str(variant_tokenizer),
            "training_manifest_path": str(output / variant / "manifest.json") if manifest else None,
            "training_steps": {stage: details["steps"] for stage, details in manifest["stages"].items()}
                if manifest else {},
            "metrics": report["metrics"],
        }
        del forecaster
        _release_memory()

    baseline_mae = reports["zero-shot"]["metrics"]["model_raw"]["close_mae"]
    comparison = [{
        "variant": variant,
        "test_close_mae": reports[variant]["metrics"]["model_raw"]["close_mae"],
        "mae_change_vs_zero_shot": reports[variant]["metrics"]["model_raw"]["close_mae"] - baseline_mae,
        "test_brier": reports[variant]["metrics"]["model_raw"]["brier_score"],
        "test_raw_coverage80": reports[variant]["metrics"]["model_raw"]["coverage80"],
        "test_calibrated_coverage80": reports[variant]["metrics"]["model_calibrated"]["coverage80"],
    } for variant in reports]
    result = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "experiment": "four-partition chronological pretrained adaptation ablation",
        "data_csv": str(data_path),
        "data_sha256": reports["zero-shot"]["provenance"]["data_sha256"],
        "initial_checkpoints": {"model": initial_model_metadata, "tokenizer": initial_tokenizer_metadata},
        "forecast_config": asdict(forecast_config) if is_dataclass(forecast_config) else
            reports["zero-shot"]["settings"]["forecast"],
        "boundaries": {
            "train_end_exclusive": train_end.isoformat(),
            "validation_end_exclusive": validation_end.isoformat(),
            "calibration_end_exclusive": calibration_end.isoformat(),
            "test_end_exclusive": test_end.isoformat() if test_end is not None else None,
        },
        "same_scored_origins": True,
        "calibration_reuses_checkpoint_selection_validation": False,
        "split": reports["zero-shot"]["split"],
        "variants": variants,
        "comparison": comparison,
        "profitability_evaluated": False,
        "warnings": [
            "Forecast metric differences alone do not establish trading profitability or generalization.",
            *reports["zero-shot"]["warnings"],
        ],
    }
    save_evaluation(result, output / "ablation.json")
    return result
