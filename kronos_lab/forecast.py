"""Causal Kronos sampling which preserves each Monte Carlo trajectory.

The official predictor averages its samples. This adapter uses the same pinned
tokenizer and autoregressive heads, retaining the paths for distributional
evaluation. Input statistics come exclusively from the lookback history.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import importlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import threading

import numpy as np
import pandas as pd

from .data import FEATURES, normalize_frame

UPSTREAM_REVISION = "67b630e67f6a18c9e9be918d9b4337c960db1e9a"
_IMPORT_LOCK = threading.RLock()
_INFERENCE_LOCK = threading.RLock()


@dataclass(frozen=True)
class ForecastConfig:
    lookback: int = 128
    horizon: int = 12
    sample_count: int = 20
    temperature: float = 0.6
    top_p: float = 0.9
    top_k: int = 0
    seed: int = 42
    max_context: int = 512

    def __post_init__(self):
        for key in ("lookback", "horizon", "sample_count", "top_k", "seed", "max_context"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{key} must be an integer")
        if not 2 <= self.lookback <= 511:
            raise ValueError("lookback must be in 2..511")
        if not 1 <= self.horizon <= 510:
            raise ValueError("horizon must be in 1..510")
        if not 3 <= self.max_context <= 512 or self.lookback + self.horizon > self.max_context:
            raise ValueError("lookback + horizon must not exceed max_context <= 512")
        if not 1 <= self.sample_count <= 256:
            raise ValueError("sample_count must be in 1..256")
        if not 0 <= self.seed < 2**63:
            raise ValueError("seed must be in 0..2**63-1")
        if not 0 <= self.top_k <= 65536:
            raise ValueError("top_k must be in 0..65536")
        for key in ("temperature", "top_p"):
            value = getattr(self, key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{key} must be finite")
        if not 0 < self.temperature <= 10:
            raise ValueError("temperature must be in (0,10]")
        if not 0 < self.top_p <= 1:
            raise ValueError("top_p must be in (0,1]")


def verify_upstream(upstream_dir: str | Path) -> str:
    """Require the audited commit and no modifications to tracked source."""
    root = Path(upstream_dir).resolve()
    try:
        revision = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"],
                                           text=True, stderr=subprocess.DEVNULL).strip()
        dirty = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
                                        text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Missing pinned vendor/Kronos checkout; run scripts/setup.sh") from exc
    if revision != UPSTREAM_REVISION or dirty:
        raise RuntimeError(f"Upstream must be clean at audited revision {UPSTREAM_REVISION}")
    return revision


def import_upstream(upstream_dir: str | Path):
    """Import official classes without accepting another package named model."""
    root = Path(upstream_dir).resolve()
    verify_upstream(root)
    with _IMPORT_LOCK:
        existing = sys.modules.get("model")
        if existing is not None:
            source = Path(getattr(existing, "__file__", "")).resolve()
            if source != root / "model" / "__init__.py":
                raise RuntimeError(f"Conflicting imported package named model: {source}")
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        return importlib.import_module("model")


def future_index(history_timestamps, horizon: int, future_timestamps=None,
                 require_explicit: bool = False) -> pd.DatetimeIndex:
    """Accept explicit sessions, or infer only a completely regular cadence."""
    past = pd.DatetimeIndex(pd.to_datetime(history_timestamps, utc=True, errors="raise"))
    if len(past) < 2 or past.hasnans or past.has_duplicates or not past.is_monotonic_increasing:
        raise ValueError("History timestamps must be unique and increasing")
    if future_timestamps is not None:
        future = pd.DatetimeIndex(pd.to_datetime(future_timestamps, utc=True, errors="raise"))
        if len(future) != horizon or future.hasnans or future.has_duplicates or not future.is_monotonic_increasing:
            raise ValueError("Future timestamps must be increasing, unique and match horizon")
        if future[0] <= past[-1]:
            raise ValueError("All future timestamps must follow the last historical candle")
        return future
    if require_explicit:
        raise ValueError("Exchange-session forecasts require explicit future_timestamps from the trading calendar")
    deltas = np.diff(past.asi8)
    if not np.all(deltas == deltas[0]) or deltas[0] <= 0:
        raise ValueError("Irregular history requires explicit future_timestamps; no trading calendar is assumed")
    step = pd.Timedelta(int(deltas[0]), unit="ns")
    return pd.date_range(past[-1] + step, periods=horizon, freq=step)


def _checkpoint(identifier: str, revision: str | None) -> tuple[Path, dict]:
    local = Path(identifier).expanduser()
    if local.is_dir():
        local = local.resolve()
        files = sorted(p for p in local.rglob("*") if p.is_file() and
                       (p.name == "config.json" or p.suffix in {".safetensors", ".bin"}))
        if not any(p.suffix in {".safetensors", ".bin"} for p in files) or not (local / "config.json").is_file():
            raise ValueError(f"Incomplete local model checkpoint: {local}")
        digest = hashlib.sha256()
        for path in files:
            digest.update(str(path.relative_to(local)).encode())
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        return local, {"id": identifier, "revision": "local-sha256:" + digest.hexdigest(),
                       "source": "local checkpoint", "path": str(local)}
    from huggingface_hub import HfApi, snapshot_download
    # An explicitly supplied immutable SHA can use an already cached snapshot
    # offline. Branch/tag/default revisions must first be resolved via the Hub.
    resolved = revision if isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{40}", revision) else HfApi().model_info(identifier, revision=revision).sha
    if not isinstance(resolved, str) or re.fullmatch(r"[0-9a-f]{40}", resolved) is None:
        raise RuntimeError(f"Could not resolve immutable Hub revision for {identifier}")
    snapshot = snapshot_download(identifier, revision=resolved,
                                 allow_patterns=["config.json", "model.safetensors", "pytorch_model.bin",
                                                 "*.safetensors.index.json", "*.safetensors"])
    return Path(snapshot), {"id": identifier, "revision": resolved, "source": "huggingface"}


def _time_features(stamps: pd.DatetimeIndex) -> np.ndarray:
    return np.column_stack([stamps.minute, stamps.hour, stamps.weekday, stamps.day, stamps.month]).astype(np.float32)


def _sample(logits, config: ForecastConfig, torch):
    logits = logits.float() / config.temperature
    if config.top_k:
        threshold = torch.topk(logits, min(config.top_k, logits.shape[-1]), dim=-1).values[:, -1:]
        logits = logits.masked_fill(logits < threshold, -torch.inf)
    if config.top_p < 1:
        ordered, indices = torch.sort(logits, dim=-1, descending=True)
        cumulative = torch.softmax(ordered, dim=-1).cumsum(dim=-1)
        remove = cumulative > config.top_p
        remove[:, 1:] = remove[:, :-1].clone()
        remove[:, 0] = False
        logits = logits.masked_fill(torch.zeros_like(remove).scatter(1, indices, remove), -torch.inf)
    return torch.multinomial(torch.softmax(logits, dim=-1), 1)


class KronosForecaster:
    def __init__(self, upstream_dir: str | Path = "vendor/Kronos",
                 model_id: str = "NeoQuasar/Kronos-base",
                 tokenizer_id: str = "NeoQuasar/Kronos-Tokenizer-base",
                 device: str | None = None, model_revision: str | None = None,
                 tokenizer_revision: str | None = None):
        self.upstream_dir = Path(upstream_dir)
        self.model_id, self.tokenizer_id = model_id, tokenizer_id
        self.model_revision, self.tokenizer_revision = model_revision, tokenizer_revision
        self.device = device
        self.model = self.tokenizer = None
        self._load_lock = threading.RLock()
        self._metadata: dict = {}

    def load(self):
        """Lazily fetch immutable weights and load real official model classes."""
        with self._load_lock:
            if self.model is not None and self.tokenizer is not None:
                return self
            import torch
            upstream = import_upstream(self.upstream_dir)
            tokenizer_path, tokenizer_meta = _checkpoint(self.tokenizer_id, self.tokenizer_revision)
            model_path, model_meta = _checkpoint(self.model_id, self.model_revision)
            if self.device is None:
                self.device = ("cuda:0" if torch.cuda.is_available() else
                               "mps" if hasattr(torch.backends, "mps") and torch.backends.mps.is_available() else "cpu")
            # Model constructors initialize parameters before checkpoint load.
            # Isolate those CPU RNG draws as well as later inference draws.
            with _INFERENCE_LOCK, torch.random.fork_rng(devices=[]):
                tokenizer = upstream.KronosTokenizer.from_pretrained(str(tokenizer_path)).to(self.device).eval()
                model = upstream.Kronos.from_pretrained(str(model_path)).to(self.device).eval()
            if (tokenizer.d_in != len(FEATURES) or
                (tokenizer.s1_bits, tokenizer.s2_bits) != (model.s1_bits, model.s2_bits) or
                tokenizer.s1_bits != tokenizer.s2_bits):
                raise ValueError("Model/tokenizer must have matching equal-width token halves and six OHLCVA features")
            self.tokenizer, self.model = tokenizer, model
            self._metadata = {"upstream_revision": UPSTREAM_REVISION, "model": model_meta,
                              "tokenizer": tokenizer_meta, "torch": torch.__version__, "device": str(self.device)}
            return self

    def _generate(self, normalized: np.ndarray, past: pd.DatetimeIndex,
                  future: pd.DatetimeIndex, config: ForecastConfig) -> np.ndarray:
        import torch
        device = torch.device(self.device)
        x = torch.as_tensor(normalized[None], dtype=torch.float32, device=device)
        stamps = torch.as_tensor(np.concatenate([_time_features(past), _time_features(future)])[None],
                                 dtype=torch.float32, device=device).repeat(config.sample_count, 1, 1)
        # The history tokenizer has global sequence work. Encode once and then
        # branch only token paths, preserving independent autoregressive samples.
        history_pre, history_post = self.tokenizer.encode(x, half=True)
        pre = history_pre.repeat(config.sample_count, 1)
        post = history_post.repeat(config.sample_count, 1)
        for _ in range(config.horizon):
            logits, context = self.model.decode_s1(pre, post, stamps[:, :pre.shape[1]])
            next_pre = _sample(logits[:, -1], config, torch)
            # DependencyAwareLayer expects matching sequence lengths. Only the
            # final causal context is needed for this single sibling token.
            next_logits = self.model.decode_s2(context[:, -1:, :], next_pre)
            next_post = _sample(next_logits[:, -1], config, torch)
            pre = torch.cat([pre, next_pre], dim=1)
            post = torch.cat([post, next_post], dim=1)
        decoded = self.tokenizer.decode([pre, post], half=True)
        return decoded[:, -config.horizon:, :].cpu().numpy().astype(np.float64)

    def forecast(self, history: pd.DataFrame, future_timestamps=None,
                 config: ForecastConfig = ForecastConfig()) -> dict:
        if not isinstance(config, ForecastConfig):
            raise ValueError("config must be a ForecastConfig")
        frame = normalize_frame(history)
        if len(frame) < config.lookback:
            raise ValueError(f"Need at least {config.lookback} history candles")
        frame = frame.iloc[-config.lookback:].reset_index(drop=True)
        past = pd.DatetimeIndex(frame["timestamps"])
        future = future_index(past, config.horizon, future_timestamps,
                              require_explicit=frame.attrs.get("provider") in {"vnstock-v5", "yfinance"})
        values = frame[FEATURES].to_numpy(dtype=np.float64)
        # Population variance matches official inference. No future value is read.
        location, scale = values.mean(axis=0), values.std(axis=0) + 1e-5
        if not np.isfinite(location).all() or not np.isfinite(scale).all():
            raise ValueError("History magnitudes overflow normalization statistics")
        normalized = np.clip((values - location) / scale, -5.0, 5.0)
        self.load()
        import torch
        device = torch.device(self.device)
        cuda_devices = [device.index if device.index is not None else torch.cuda.current_device()] if device.type == "cuda" else []
        with _INFERENCE_LOCK, torch.inference_mode(), torch.random.fork_rng(devices=cuda_devices):
            mps_state = torch.mps.get_rng_state() if device.type == "mps" else None
            try:
                torch.random.default_generator.manual_seed(config.seed)
                if device.type == "cuda":
                    with torch.cuda.device(device):
                        torch.cuda.manual_seed(config.seed)
                elif device.type == "mps":
                    torch.mps.manual_seed(config.seed)
                normalized_paths = self._generate(normalized, past, future, config)
            finally:
                if mps_state is not None:
                    torch.mps.set_rng_state(mps_state)
        paths = normalized_paths * scale[None, None, :] + location[None, None, :]
        if paths.shape != (config.sample_count, config.horizon, len(FEATURES)) or not np.isfinite(paths).all():
            raise RuntimeError("Kronos generated non-finite values or an unexpected trajectory shape")
        mean = paths.mean(axis=0)
        closes = paths[:, :, 3]
        last_close = float(values[-1, 3])
        returns = (closes[:, -1] / last_close - 1) * 100
        up, down = int(np.sum(returns > 0)), int(np.sum(returns < 0))
        flat = config.sample_count - up - down
        violations = ((paths[:, :, :4] <= 0).any(axis=-1) |
                      (paths[:, :, 2] > np.minimum(paths[:, :, 0], paths[:, :, 3])) |
                      (paths[:, :, 1] < np.maximum(paths[:, :, 0], paths[:, :, 3])) |
                      (paths[:, :, 4:] < 0).any(axis=-1))
        records = frame.copy()
        records["timestamps"] = records["timestamps"].map(lambda value: value.isoformat())
        input_json = records.to_json(orient="records", double_precision=15)
        metadata = {**self._metadata, "config": asdict(config), "seed": config.seed,
                    "issued_at_utc": datetime.now(timezone.utc).isoformat(),
                    "input_sha256": hashlib.sha256(input_json.encode()).hexdigest(),
                    "normalization": {"scope": "history only", "mean": location.tolist(), "std_plus_epsilon": scale.tolist(), "clip": 5.0},
                    "amount_source": frame.attrs.get("amount_source"),
                    "timestamp_policy": "explicit" if future_timestamps is not None else "observed regular UTC interval; no session calendar",
                    "probability_semantics": "p_up is terminal Monte Carlo vote frequency, not a calibrated probability of correctness",
                    "price_adjustment": "none; raw decoded trajectories, no universal volatility multiplier",
                    "invalid_generated_candle_count": int(violations.sum()),
                    "pandas": pd.__version__, "numpy": np.__version__}
        expected = float(returns.mean())
        return {"timestamps": [value.isoformat() for value in future], "features": FEATURES.copy(),
                "mean": mean.tolist(),
                "quantiles": {label: np.quantile(closes, q, axis=0).tolist() for label, q in [("q10", 0.1), ("q50", 0.5), ("q90", 0.9)]},
                "trajectories": paths.tolist(), "history": records.to_dict(orient="records"),
                "summary": {"last_close": last_close, "expected_return_pct": expected,
                            "first_step_gap": float(mean[0, 3] - last_close),
                            "first_step_gap_pct": float((mean[0, 3] / last_close - 1) * 100),
                            "return_std_pct": float(returns.std()), "p_up": up / config.sample_count,
                            "direction": "up" if expected > 0 else "down" if expected < 0 else "flat",
                            "sample_votes": {"up": up, "down": down, "flat": flat},
                            "sample_count": config.sample_count, "terminal_q10": float(np.quantile(closes[:, -1], 0.1)),
                            "terminal_q90": float(np.quantile(closes[:, -1], 0.9)), "calibrated": False},
                "metadata": metadata}
