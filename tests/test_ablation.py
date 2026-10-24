"""Ablation orchestration tests run real split/scoring code with fake models."""
from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kronos_lab import ablation


@dataclass(frozen=True)
class Config:
    lookback: int = 4
    horizon: int = 2
    sample_count: int = 4
    seed: int = 9


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    stamps = pd.date_range("2026-01-01", periods=80, freq="h", tz="UTC")
    close = np.arange(80) + 100.
    frame = pd.DataFrame({"timestamps": stamps, "open": close, "high": close + 2,
                          "low": close - 2, "close": close, "volume": 10., "amount": 1000.})
    data_csv = tmp_path / "prices.csv"
    frame.to_csv(data_csv, index=False)
    config = {
        "data_csv": str(data_csv), "output_dir": str(tmp_path / "ablation"),
        "train_end": stamps[20].isoformat(), "validation_end": stamps[40].isoformat(),
        "calibration_end": stamps[60].isoformat(),
        "test_end": "2026-01-04T08:00:00+00:00",  # exclusive hour 80
        "context_length": 4, "horizon": 2, "seed": 9,
        "model_path": "initial-predictor", "tokenizer_path": "initial-tokenizer", "device": "cpu",
    }
    calls = {"training": [], "models": [], "resolve": []}

    def fake_checkpoint(identifier, revision):
        calls["resolve"].append((identifier, revision))
        return tmp_path / identifier, {"id": identifier, "revision": "fixed-sha", "source": "mock"}

    def fake_train(stage_config):
        calls["training"].append(dict(stage_config))
        output = Path(stage_config["output_dir"])
        output.mkdir(parents=True)
        manifest = {
            "model_path": str(output / "predictor"), "tokenizer_path": str(output / "tokenizer"),
            "test_used_for_training_or_selection": False,
            "stages": {"predictor": {"steps": 1}},
        }
        if stage_config["mode"] == "two-stage":
            manifest["stages"]["tokenizer"] = {"steps": 1}
        (output / "manifest.json").write_text(json.dumps(manifest))
        return manifest

    class FakeModel:
        def __init__(self, **kwargs):
            calls["models"].append(kwargs)
            model_id = str(kwargs["model_id"])
            self.trend = 1 if "two-stage" in model_id else .5 if "predictor-only" in model_id else 0

        def forecast(self, history, *, future_timestamps, config):
            point = history["close"].iloc[-1] + np.arange(1, config.horizon + 1) * self.trend
            mean = np.tile(point[:, None], (1, 6))
            return {
                "timestamps": future_timestamps.tolist(), "mean": mean,
                "quantiles": {"q10": point - .25, "q50": point, "q90": point + .25},
                "trajectories": np.stack([mean - .1, mean + .1]), "metadata": {"test_fake": True},
            }

    monkeypatch.setattr(ablation, "_checkpoint", fake_checkpoint)
    monkeypatch.setattr(ablation, "train", fake_train)
    monkeypatch.setattr(ablation, "KronosForecaster", FakeModel)
    return config, calls


def test_ablation_resolves_once_trains_separate_variants_and_scores_identical_origins(experiment):
    config, calls = experiment
    original = dict(config)
    result = ablation.run_ablation(config, Config(), max_windows=8)
    assert config == original
    assert [c["mode"] for c in calls["training"]] == ["predictor-only", "two-stage"]
    assert len(calls["resolve"]) == 2
    zero_model = calls["models"][0]
    for stage in calls["training"]:
        assert stage["model_path"] == zero_model["model_id"]
        assert stage["tokenizer_path"] == zero_model["tokenizer_id"]
        assert stage["train_end"] == original["train_end"]
        assert stage["validation_end"] == original["validation_end"]
        assert stage["calibration_end"] == original["calibration_end"]
    assert result["same_scored_origins"] is True
    assert result["calibration_reuses_checkpoint_selection_validation"] is False
    assert result["profitability_evaluated"] is False
    reports = [json.loads(Path(variant["report_path"]).read_text()) for variant in result["variants"].values()]
    signatures = [[(w["split"], w["origin_index"], w["timestamps"]) for w in r["per_window"]] for r in reports]
    assert signatures[0] == signatures[1] == signatures[2]
    for window in reports[0]["per_window"]:
        assert pd.Timestamp(window["timestamps"][0]) >= pd.Timestamp(config["validation_end"])
        if window["split"] == "calibration":
            assert pd.Timestamp(window["timestamps"][-1]) < pd.Timestamp(config["calibration_end"])
        else:
            assert pd.Timestamp(window["timestamps"][0]) >= pd.Timestamp(config["calibration_end"])
            assert pd.Timestamp(window["timestamps"][-1]) < pd.Timestamp(config["test_end"])
    assert [row["test_close_mae"] for row in result["comparison"]] == [1.5, .75, 0]
    assert json.loads((Path(config["output_dir"]) / "ablation.json").read_text()) == result


@pytest.mark.parametrize("changes,match", [
    ({"calibration_end": None}, "requires calibration_end"),
    ({"calibration_end": "2026-01-02"}, "train_end < validation_end < calibration_end"),
    ({"test_end": "2026-01-02"}, "test_end must follow"),
    ({"context_length": 5}, "lookback must match"),
    ({"horizon": 3}, "horizon must match"),
    ({"model_config": {}}, "pretrained checkpoints"),
    ({"validation_end": "invalid"}, "valid timestamp"),
    ({"evaluation_stride": 0}, "evaluation_stride must"),
    ({"calibration_fraction": 0}, "strictly between"),
])
def test_invalid_experiments_fail_before_models_or_training(experiment, changes, match):
    config, calls = experiment
    config.update(changes)
    with pytest.raises(ValueError, match=match):
        ablation.run_ablation(config, Config())
    assert calls["training"] == calls["models"] == calls["resolve"] == []


def test_existing_results_are_preserved(experiment):
    config, calls = experiment
    output = Path(config["output_dir"])
    output.mkdir()
    artifact = output / "previous.json"
    artifact.write_text("previous evidence")
    with pytest.raises(FileExistsError, match="must be empty"):
        ablation.run_ablation(config, Config())
    assert artifact.read_text() == "previous evidence"
    assert not calls["resolve"]


def test_inconsistent_origin_sets_abort_comparison(experiment, monkeypatch):
    config, calls = experiment
    actual = ablation.walk_forward
    count = 0

    def inconsistent(*args, **kwargs):
        nonlocal count
        report = actual(*args, **kwargs)
        count += 1
        if count == 2:
            report["per_window"][-1]["origin_index"] += 1
        return report

    monkeypatch.setattr(ablation, "walk_forward", inconsistent)
    with pytest.raises(RuntimeError, match="exactly the same"):
        ablation.run_ablation(config, Config())
    assert len(calls["training"]) == 1
    assert not (Path(config["output_dir"]) / "ablation.json").exists()


def test_unconfirmed_test_isolation_aborts_before_adapted_model_scoring(experiment, monkeypatch):
    config, calls = experiment
    train = ablation.train

    def contaminated(cfg):
        result = train(cfg)
        result["test_used_for_training_or_selection"] = True
        return result

    monkeypatch.setattr(ablation, "train", contaminated)
    with pytest.raises(RuntimeError, match="untouched held-out"):
        ablation.run_ablation(config, Config())
    assert len(calls["models"]) == 1
