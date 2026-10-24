"""Distribution preservation, causal scaling, calendars and real model shapes."""
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import torch

from kronos_lab.forecast import ForecastConfig, KronosForecaster, future_index, import_upstream
from kronos_lab import forecast as engine

ROOT = Path(__file__).resolve().parents[1]


def history(n=12):
    close = np.arange(n, dtype=float) + 100
    return pd.DataFrame({"timestamps": pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC"),
                         "open": close - 0.5, "high": close + 1, "low": close - 1,
                         "close": close, "volume": close * 10, "amount": close * 1000})


class FakeTokenizer:
    def __init__(self):
        self.calls = 0
        self.last_input = None
    def encode(self, x, half):
        self.calls += 1
        self.last_input = x.clone()
        assert x.shape[0] == 1
        return [torch.zeros(x.shape[:2], dtype=torch.long) for _ in range(2)]
    def decode(self, tokens, half):
        return (tokens[0].float() - 3).unsqueeze(-1).repeat(1, 1, 6) / 10


class FakeModel:
    def decode_s1(self, pre, post, stamps):
        assert pre.shape[1] == stamps.shape[1]
        return torch.zeros((*pre.shape, 8)), torch.zeros((*pre.shape, 16))
    def decode_s2(self, context, pre):
        assert context.shape[1] == pre.shape[1] == 1
        return torch.zeros((*pre.shape, 8))


def fake_forecaster():
    forecaster = KronosForecaster(device="cpu")
    forecaster.model, forecaster.tokenizer = FakeModel(), FakeTokenizer()
    forecaster._metadata = {"purpose": "test fake, no forecast skill claim"}
    return forecaster


@pytest.mark.parametrize("values", [
    {"lookback": 1}, {"horizon": 0}, {"sample_count": 0}, {"sample_count": 257},
    {"temperature": float("nan")}, {"temperature": 0}, {"top_p": 0}, {"top_p": 1.1},
    {"lookback": 500, "horizon": 20}, {"top_k": -1}, {"seed": -1}, {"lookback": True},
])
def test_config_validation(values):
    with pytest.raises(ValueError):
        ForecastConfig(**values)


def test_preserves_paths_quantiles_votes_and_seed_without_global_rng_changes():
    forecaster = fake_forecaster()
    cfg = ForecastConfig(lookback=8, horizon=3, sample_count=20)
    rng = torch.random.get_rng_state().clone()
    first = forecaster.forecast(history(), config=cfg)
    assert torch.equal(rng, torch.random.get_rng_state())
    second = forecaster.forecast(history(), config=cfg)
    assert first["trajectories"] == second["trajectories"]
    paths = np.asarray(first["trajectories"])
    assert paths.shape == (20, 3, 6)
    assert np.unique(paths[:, :, 3], axis=0).shape[0] > 1
    np.testing.assert_allclose(first["mean"], paths.mean(axis=0))
    assert first["summary"]["first_step_gap"] == pytest.approx(paths[:, 0, 3].mean() - first["summary"]["last_close"])
    assert first["summary"]["first_step_gap_pct"] == pytest.approx(first["summary"]["first_step_gap"] / first["summary"]["last_close"] * 100)
    np.testing.assert_allclose(first["quantiles"]["q10"], np.quantile(paths[:, :, 3], .1, axis=0))
    expected_votes = np.sum(paths[:, -1, 3] > first["summary"]["last_close"])
    assert first["summary"]["p_up"] == expected_votes / 20
    assert first["summary"]["calibrated"] is False
    assert "not a calibrated" in first["metadata"]["probability_semantics"]
    json.dumps(first, allow_nan=False)


def test_encoding_once_and_history_only_scaling():
    forecaster = fake_forecaster()
    cfg = ForecastConfig(lookback=8, horizon=3, sample_count=20)
    frame = history()
    result = forecaster.forecast(frame, config=cfg)
    assert forecaster.tokenizer.calls == 1
    stats = frame.iloc[-8:][result["features"]].to_numpy()
    np.testing.assert_allclose(result["metadata"]["normalization"]["mean"], stats.mean(axis=0))
    np.testing.assert_allclose(forecaster.tokenizer.last_input.mean(dim=1), 0, atol=1e-6)
    # Older values outside the context must not alter scales or model input.
    frame.loc[:3, ["open", "high", "low", "close"]] *= 100
    again = forecaster.forecast(frame, config=cfg)
    assert again["trajectories"] == result["trajectories"]


def test_concurrent_forecasts_isolate_rng_and_return_identical_seeded_paths():
    forecaster = fake_forecaster()
    cfg = ForecastConfig(lookback=8, horizon=3, sample_count=10)
    state = torch.random.get_rng_state().clone()
    with ThreadPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(lambda _: forecaster.forecast(history(), config=cfg), range(2)))
    assert outputs[0]["trajectories"] == outputs[1]["trajectories"]
    assert torch.equal(state, torch.random.get_rng_state())


def test_hub_branch_is_resolved_before_weights_download(monkeypatch):
    import huggingface_hub
    resolved = "a" * 40
    calls = []
    class Hub:
        def model_info(self, repo, revision):
            calls.append(("resolve", repo, revision))
            return SimpleNamespace(sha=resolved)
    def snapshot(repo, **kwargs):
        calls.append(("download", repo, kwargs["revision"]))
        return "/tmp/test-snapshot"
    monkeypatch.setattr(huggingface_hub, "HfApi", Hub)
    monkeypatch.setattr(huggingface_hub, "snapshot_download", snapshot)
    _, metadata = engine._checkpoint("Example/test-model", "main")
    assert calls == [("resolve", "Example/test-model", "main"), ("download", "Example/test-model", resolved)]
    assert metadata["revision"] == resolved


def test_local_checkpoint_content_hash_changes_with_weights(tmp_path):
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "model.safetensors").write_bytes(b"first")
    _, first = engine._checkpoint(str(tmp_path), None)
    (tmp_path / "model.safetensors").write_bytes(b"second")
    _, second = engine._checkpoint(str(tmp_path), None)
    assert first["revision"] != second["revision"]
    assert first["revision"].startswith("local-sha256:")


def test_model_loading_does_not_consume_caller_rng(monkeypatch):
    class Loader:
        @staticmethod
        def from_pretrained(path):
            module = torch.nn.Linear(3, 3)
            module.d_in, module.s1_bits, module.s2_bits = 6, 2, 2
            return module
    monkeypatch.setattr(engine, "import_upstream", lambda _: SimpleNamespace(Kronos=Loader, KronosTokenizer=Loader))
    monkeypatch.setattr(engine, "_checkpoint", lambda identifier, _: (Path("."), {"id": identifier, "revision": "test"}))
    forecaster = KronosForecaster(device="cpu")
    state = torch.random.get_rng_state().clone()
    forecaster.load()
    assert torch.equal(state, torch.random.get_rng_state())


def test_calendars_never_median_fill_session_gaps():
    irregular = pd.to_datetime(["2026-01-02", "2026-01-05", "2026-01-06"], utc=True)
    with pytest.raises(ValueError, match="Irregular"):
        future_index(irregular, 2)
    actual = pd.to_datetime(["2026-01-07", "2026-01-08"], utc=True)
    pd.testing.assert_index_equal(future_index(irregular, 2, actual), actual)
    with pytest.raises(ValueError, match="Exchange-session"):
        future_index(pd.date_range("2026-01-01", periods=5, tz="UTC"), 2, require_explicit=True)
    with pytest.raises(ValueError, match="follow"):
        future_index(irregular, 2, irregular[:2])


def test_reject_future_ohlc_values_and_too_short_history():
    forecaster = fake_forecaster()
    cfg = ForecastConfig(lookback=8, horizon=3)
    with pytest.raises(ValueError, match="at least"):
        forecaster.forecast(history(5), config=cfg)
    with pytest.raises((TypeError, ValueError)):
        forecaster.forecast(history(), future_timestamps=history(3), config=cfg)


def test_official_tiny_models_execute_real_autoregressive_heads():
    upstream_root = ROOT / "vendor" / "Kronos"
    if not upstream_root.exists():
        pytest.skip("Pinned upstream checkout not installed")
    upstream = import_upstream(upstream_root)
    # These are random initialized official layers, intentionally not pretrained
    # accuracy evidence. They detect shape/architecture errors fakes cannot.
    tokenizer = upstream.KronosTokenizer(d_in=6, d_model=16, n_heads=4, ff_dim=32,
                    n_enc_layers=2, n_dec_layers=2, ffn_dropout_p=0., attn_dropout_p=0.,
                    resid_dropout_p=0., s1_bits=2, s2_bits=2, beta=.25,
                    gamma0=1., gamma=1., zeta=1., group_size=2).eval()
    model = upstream.Kronos(s1_bits=2, s2_bits=2, n_layers=1, d_model=16, n_heads=4,
                    ff_dim=32, ffn_dropout_p=0., attn_dropout_p=0., resid_dropout_p=0.,
                    token_dropout_p=0., learn_te=True).eval()
    forecaster = KronosForecaster(device="cpu")
    forecaster.model, forecaster.tokenizer = model, tokenizer
    forecaster._metadata = {"purpose": "random official architecture test"}
    with patch.object(tokenizer, "encode", wraps=tokenizer.encode) as encode:
        output = forecaster.forecast(history(), config=ForecastConfig(lookback=8, horizon=3, sample_count=4))
    assert np.asarray(output["trajectories"]).shape == (4, 3, 6)
    assert encode.call_count == 1
    assert np.isfinite(np.asarray(output["trajectories"])).all()
