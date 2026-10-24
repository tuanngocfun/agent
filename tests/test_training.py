"""Adversarial leakage checks and a real upstream optimizer/checkpoint smoke."""
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pd = pytest.importorskip("pandas")
torch = pytest.importorskip("torch")

from kronos_lab.training import CausalWindowDataset, _upstream, causal_loss_mode, train


def candles(count=54):
    values = np.arange(count, dtype=np.float32) + 100
    return pd.DataFrame({
        "timestamps": pd.date_range("2025-01-01", periods=count, freq="h", tz="UTC"),
        "open": values, "high": values + 2, "low": values - 2,
        "close": values + 1, "volume": values * 3, "amount": values * values * 3,
    })


def test_future_cannot_change_normalized_history():
    frame = candles(12)
    changed = frame.copy()
    changed.loc[4:5, ["open", "high", "low", "close", "volume", "amount"]] *= 1000
    original = CausalWindowDataset(frame, 4, 2)
    adversarial = CausalWindowDataset(changed, 4, 2)
    assert torch.equal(original[0]["x"][:4], adversarial[0]["x"][:4])
    assert not torch.equal(original[0]["x"][4:], adversarial[0]["x"][4:])
    assert torch.allclose(original[0]["x"][:4].mean(dim=0), torch.zeros(6), atol=1e-5)


def test_all_window_labels_stay_in_their_timestamp_partition():
    frame = candles(72)
    boundaries = [frame.timestamps.iloc[0], frame.timestamps.iloc[18], frame.timestamps.iloc[36],
                  frame.timestamps.iloc[54],
                  frame.timestamps.iloc[-1] + pd.Timedelta(hours=1)]
    for start, end in zip(boundaries, boundaries[1:]):
        dataset = CausalWindowDataset(frame, 4, 2, split_start=start, split_end=end)
        assert len(dataset) == 13
        for index in range(len(dataset)):
            metadata = dataset.sample_metadata(index)
            assert start <= pd.Timestamp(metadata["context_start"])
            assert pd.Timestamp(metadata["context_end"]) < pd.Timestamp(metadata["target_start"])
            assert pd.Timestamp(metadata["target_end"]) < end


def test_invalid_timestamps_and_missing_features_are_rejected():
    frame = candles()
    with pytest.raises(ValueError, match="strictly increasing"):
        CausalWindowDataset(frame.iloc[::-1], 4, 2)
    with pytest.raises(ValueError, match="Missing training columns"):
        CausalWindowDataset(frame.drop(columns="amount"), 4, 2)


def tiny_configs():
    return {
        "tokenizer_config": {
            "d_in": 6, "d_model": 16, "n_heads": 2, "ff_dim": 32,
            "n_enc_layers": 2, "n_dec_layers": 2, "ffn_dropout_p": 0.0,
            "attn_dropout_p": 0.0, "resid_dropout_p": 0.0,
            "s1_bits": 2, "s2_bits": 2, "beta": 0.05, "gamma0": 1.0,
            "gamma": 1.0, "zeta": 1.0, "group_size": 2,
        },
        "model_config": {
            "s1_bits": 2, "s2_bits": 2, "n_layers": 1, "d_model": 16,
            "n_heads": 2, "ff_dim": 32, "ffn_dropout_p": 0.0,
            "attn_dropout_p": 0.0, "resid_dropout_p": 0.0,
            "token_dropout_p": 0.0, "learn_te": True,
        },
    }


@pytest.fixture
def upstream():
    root = Path(__file__).resolve().parents[1] / "vendor/Kronos"
    if not (root / "model/kronos.py").exists():
        pytest.skip("Pinned upstream checkout not installed; run scripts/setup.sh")
    pytest.importorskip("huggingface_hub")
    old_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    yield _upstream(root)
    torch.set_num_threads(old_threads)


def test_upstream_tokenized_history_ignores_future_mutations(upstream):
    Tokenizer, _ = upstream
    torch.manual_seed(17)
    tokenizer = Tokenizer(**tiny_configs()["tokenizer_config"]).eval()
    original = CausalWindowDataset(candles(12), 4, 2)[0]["x"].unsqueeze(0)
    changed = original.clone()
    changed[:, 4:] = torch.randn_like(changed[:, 4:]) * 100
    with torch.no_grad():
        before = tokenizer.encode(original, half=True)
        after = tokenizer.encode(changed, half=True)
    for first, second in zip(before, after):
        assert torch.equal(first[:, :4], second[:, :4])


def test_dependency_head_validation_cannot_see_future_targets(upstream):
    _, Predictor = upstream
    torch.manual_seed(19)
    model = Predictor(**tiny_configs()["model_config"]).eval()
    first = torch.randint(0, 4, (2, 8))
    second = torch.randint(0, 4, (2, 8))
    targets = torch.randint(0, 4, (2, 8))
    changed_targets = targets.clone()
    changed_targets[:, 4:] = (targets[:, 4:] + 1) % 4
    with torch.no_grad(), causal_loss_mode(model):
        before = model(first, second, use_teacher_forcing=True, s1_targets=targets)
        after = model(first, second, use_teacher_forcing=True, s1_targets=changed_targets)
    assert torch.allclose(before[1][:, :4], after[1][:, :4], atol=1e-6)
    assert not model.training
    assert not model.dep_layer.cross_attn.training


@pytest.mark.parametrize("mode", ["two-stage", "predictor-only"])
def test_real_one_step_training_saves_reloadable_models(tmp_path, upstream, mode):
    Tokenizer, Predictor = upstream
    config = tiny_configs()
    torch.manual_seed(123)
    initial_tokenizer = Tokenizer(**config["tokenizer_config"])
    initial_predictor = Predictor(**config["model_config"])
    frame = candles(72)
    csv_path = tmp_path / "candles.csv"
    frame.to_csv(csv_path, index=False)
    config.update({
        "mode": mode, "data_csv": str(csv_path), "output_dir": str(tmp_path / "run"),
        "context_length": 4, "horizon": 2, "batch_size": 2,
        "train_end": frame.timestamps.iloc[18].isoformat(),
        "validation_end": frame.timestamps.iloc[36].isoformat(),
        "calibration_end": frame.timestamps.iloc[54].isoformat(),
        "device": "cpu", "epochs": 1, "max_steps": 1, "seed": 123,
        "tokenizer_learning_rate": 1e-3, "predictor_learning_rate": 1e-3,
    })
    manifest = train(config)
    assert manifest["initialization"] == "random-test"
    assert manifest["stages"]["predictor"]["steps"] == 1
    assert manifest["test_used_for_training_or_selection"] is False
    assert manifest["calibration_used_for_training_or_selection"] is False
    assert pd.Timestamp(manifest["splits"]["calibration"]["first"]["context_start"]) >= frame.timestamps.iloc[36]
    assert pd.Timestamp(manifest["splits"]["test"]["first"]["context_start"]) >= frame.timestamps.iloc[54]
    assert manifest["trained_checkpoints"]["model"]["revision"].startswith("local-sha256:")
    assert (tmp_path / "run/manifest.json").is_file()
    saved_tokenizer = Tokenizer.from_pretrained(manifest["tokenizer_path"])
    saved_predictor = Predictor.from_pretrained(manifest["model_path"])
    tokenizer_changed = any(not torch.equal(value, saved_tokenizer.state_dict()[key])
                            for key, value in initial_tokenizer.state_dict().items())
    predictor_changed = any(not torch.equal(value, saved_predictor.state_dict()[key])
                            for key, value in initial_predictor.state_dict().items())
    assert tokenizer_changed == (mode == "two-stage")
    assert predictor_changed
    assert np.isfinite(manifest["stages"]["predictor"]["best_validation_loss"])
    if mode == "two-stage":
        assert manifest["stages"]["tokenizer"]["steps"] == 1


def test_calibration_and_test_mutations_cannot_change_training_selection(tmp_path, upstream):
    frame = candles(72)
    config = tiny_configs()
    config.update({
        "mode": "predictor-only", "context_length": 4, "horizon": 2, "batch_size": 2,
        "train_end": frame.timestamps.iloc[18].isoformat(),
        "validation_end": frame.timestamps.iloc[36].isoformat(),
        "calibration_end": frame.timestamps.iloc[54].isoformat(),
        "device": "cpu", "epochs": 1, "max_steps": 1, "seed": 123,
    })
    manifests = []
    for index in range(2):
        csv_path = tmp_path / f"candles-{index}.csv"
        if index:
            frame.loc[36:, ["open", "high", "low", "close", "volume", "amount"]] *= 100
        frame.to_csv(csv_path, index=False)
        manifests.append(train({**config, "data_csv": str(csv_path),
                                "output_dir": str(tmp_path / f"run-{index}")}))
    assert manifests[0]["data_sha256"] != manifests[1]["data_sha256"]
    assert manifests[0]["trained_checkpoints"]["model"]["revision"] == manifests[1]["trained_checkpoints"]["model"]["revision"]
    assert manifests[0]["stages"]["predictor"]["best_validation_loss"] == manifests[1]["stages"]["predictor"]["best_validation_loss"]


def test_local_initial_checkpoints_are_hashed_and_loaded(tmp_path, upstream):
    Tokenizer, Predictor = upstream
    architecture = tiny_configs()
    tokenizer_path, model_path = tmp_path / "initial-tokenizer", tmp_path / "initial-model"
    Tokenizer(**architecture["tokenizer_config"]).save_pretrained(str(tokenizer_path))
    Predictor(**architecture["model_config"]).save_pretrained(str(model_path))
    frame = candles()
    csv_path = tmp_path / "candles.csv"
    frame.to_csv(csv_path, index=False)
    manifest = train({
        "mode": "predictor-only", "data_csv": str(csv_path), "output_dir": str(tmp_path / "run"),
        "tokenizer_path": str(tokenizer_path), "model_path": str(model_path),
        "context_length": 4, "horizon": 2, "batch_size": 2,
        "train_end": frame.timestamps.iloc[18].isoformat(),
        "validation_end": frame.timestamps.iloc[36].isoformat(),
        "device": "cpu", "epochs": 1, "max_steps": 1, "seed": 123,
    })
    assert manifest["initialization"] == "pretrained"
    initial = manifest["initial_checkpoints"]
    final = manifest["trained_checkpoints"]
    assert initial["model"]["source"] == "local checkpoint"
    assert initial["model"]["revision"].startswith("local-sha256:")
    assert initial["tokenizer"]["revision"] == final["tokenizer"]["revision"]
    assert initial["model"]["revision"] != final["model"]["revision"]
