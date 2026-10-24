"""Causal, chronologically partitioned Kronos adaptation.

The two supported ablations share the exact same forecasting objective:
``predictor-only`` freezes the original tokenizer; ``two-stage`` first adapts
the tokenizer, restores its best validation checkpoint, then freezes it.
Zero-shot evaluation belongs to the evaluation CLI and never enters this module.
All heavy dependencies are imported lazily so the non-training CLI remains light.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random


FEATURES = ("open", "high", "low", "close", "volume", "amount")


class CausalWindowDataset:
    """Sliding OHLCVA windows contained entirely within ``[start, end)``.

    The first ``context_length`` rows alone determine normalization statistics.
    Future rows are labels; changing them cannot change normalized history.
    Splits intentionally do not borrow context from the preceding partition.
    This conservative rule also prevents any training label crossing a boundary.
    """

    def __init__(self, frame, context_length: int, horizon: int, *,
                 split_start=None, split_end=None, stride: int = 1,
                 timestamp_column: str = "timestamps", clip: float = 5.0,
                 epsilon: float = 1e-5):
        import numpy as np
        import pandas as pd

        if context_length < 2 or horizon < 1 or stride < 1:
            raise ValueError("context_length >= 2, horizon >= 1 and stride >= 1 are required")
        if not math.isfinite(clip) or clip <= 0 or not math.isfinite(epsilon) or epsilon <= 0:
            raise ValueError("clip and epsilon must be positive and finite")
        if timestamp_column not in frame and timestamp_column == "timestamps" and "timestamp" in frame:
            timestamp_column = "timestamp"
        missing = [c for c in (timestamp_column, *FEATURES) if c not in frame]
        if missing:
            raise ValueError(f"Missing training columns: {missing}")
        frame = frame.copy()
        times = pd.to_datetime(frame[timestamp_column], utc=True, errors="raise")
        if times.isna().any() or times.duplicated().any() or not times.is_monotonic_increasing:
            raise ValueError("Training timestamps must be valid, unique and strictly increasing")
        start = pd.Timestamp(split_start) if split_start is not None else None
        end = pd.Timestamp(split_end) if split_end is not None else None
        start = start.tz_localize("UTC") if start is not None and start.tzinfo is None else start
        end = end.tz_localize("UTC") if end is not None and end.tzinfo is None else end
        if start is not None and end is not None and start >= end:
            raise ValueError("split_start must precede split_end")
        selected = pd.Series(True, index=frame.index)
        if start is not None:
            selected &= times >= start
        if end is not None:
            selected &= times < end
        frame = frame.loc[selected].reset_index(drop=True)
        times = times.loc[selected].reset_index(drop=True)
        values = frame[list(FEATURES)].to_numpy(dtype=np.float32)
        if not np.isfinite(values).all():
            raise ValueError("Training OHLCVA values must be finite")
        self.context_length, self.horizon = context_length, horizon
        self.window_length = context_length + horizon
        self.starts = list(range(0, max(0, len(frame) - self.window_length + 1), stride))
        self.values, self.timestamps = values, times
        self.stamps = np.column_stack([
            times.dt.minute, times.dt.hour, times.dt.weekday, times.dt.day, times.dt.month
        ]).astype(np.float32)
        self.clip, self.epsilon = float(clip), float(epsilon)

    def __len__(self):
        return len(self.starts)

    def __getitem__(self, index):
        import numpy as np
        import torch

        start = self.starts[index]
        raw = self.values[start:start + self.window_length]
        history = raw[:self.context_length]
        mean = history.mean(axis=0, dtype=np.float64).astype(np.float32)
        std = history.std(axis=0, dtype=np.float64).astype(np.float32)
        normalized = np.clip((raw - mean) / (std + self.epsilon), -self.clip, self.clip)
        return {
            "x": torch.from_numpy(normalized.astype(np.float32)),
            "stamp": torch.from_numpy(self.stamps[start:start + self.window_length].copy()),
        }

    def sample_metadata(self, index):
        start = self.starts[index]
        return {
            "context_start": self.timestamps.iloc[start].isoformat(),
            "context_end": self.timestamps.iloc[start + self.context_length - 1].isoformat(),
            "target_start": self.timestamps.iloc[start + self.context_length].isoformat(),
            "target_end": self.timestamps.iloc[start + self.window_length - 1].isoformat(),
        }


def _upstream(kronos_path):
    from .forecast import import_upstream
    upstream = import_upstream(Path(kronos_path).expanduser().resolve())
    return upstream.KronosTokenizer, upstream.Kronos


@contextmanager
def causal_loss_mode(model, *, training=False):
    """Keep full-sequence validation causal, including the dependency head.

    Upstream self-attention is always causal. Its cross-attention, however, uses
    ``is_causal=self.training``. Setting only those attention modules to training
    mode fixes teacher-forced validation without enabling dropout elsewhere.
    The context restores every module flag and attention-dropout setting.
    """
    flags = [(module, module.training) for module in model.modules()]
    dropout = []
    model.train(training)
    for module in model.modules():
        if type(module).__name__ == "MultiHeadCrossAttentionWithRoPE":
            module.training = True
            if not training:
                dropout.append((module, module.attn_dropout_p))
                module.attn_dropout_p = 0.0
    try:
        yield
    finally:
        for module, value in dropout:
            module.attn_dropout_p = value
        for module, flag in flags:
            module.training = flag


def _bare(model):
    return getattr(model, "module", model)


def _loss(stage, model, tokenizer, batch, context_length, device):
    import torch
    from torch.nn import functional as F

    x, stamp = batch["x"].to(device), batch["stamp"].to(device)
    if stage == "tokenizer":
        (coarse, full), quantization_loss, _, _ = model(x)
        return (F.mse_loss(coarse, x) + F.mse_loss(full, x) + quantization_loss) / 2
    with torch.no_grad():
        first, second = tokenizer.encode(x, half=True)
    # Predict the future portion only. History normalization uses the entire
    # observed context, so losses on positions inside that context would not be
    # comparable to a genuine historical forecast origin.
    logits = model(first[:, :-1], second[:, :-1], stamp[:, :-1],
                   use_teacher_forcing=True, s1_targets=first[:, 1:])
    begin = context_length - 1
    return _bare(model).head.compute_loss(
        logits[0][:, begin:], logits[1][:, begin:],
        first[:, context_length:], second[:, context_length:]
    )[0]


def _distributed(device_name):
    import torch
    import torch.distributed as dist

    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    rank = int(os.environ.get("RANK", "0"))
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    owns_group = False
    if world_size > 1:
        use_cuda = str(device_name).startswith("cuda")
        if use_cuda:
            torch.cuda.set_device(local_rank)
            device_name = f"cuda:{local_rank}"
        if not dist.is_initialized():
            dist.init_process_group("nccl" if use_cuda else "gloo")
            owns_group = True
    return torch.device(device_name), rank, world_size, owns_group


def _train_stage(stage, model, tokenizer, datasets, config, output, device, rank, world_size):
    import torch
    import torch.distributed as dist
    from torch.nn.parallel import DistributedDataParallel
    from torch.utils.data import DataLoader, DistributedSampler

    epochs = int(config.get(f"{stage}_epochs", config.get("epochs", 5)))
    max_steps = config.get(f"{stage}_max_steps", config.get("max_steps"))
    max_steps = int(max_steps) if max_steps is not None else None
    patience = int(config.get("patience", 3))
    validation_batches = config.get("max_validation_batches")
    if epochs < 1 or (max_steps is not None and max_steps < 1) or patience < 1:
        raise ValueError("epochs, max_steps and patience must be positive")
    if validation_batches is not None and int(validation_batches) < 1:
        raise ValueError("max_validation_batches must be positive")
    batch_size = int(config.get("batch_size", 8))
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    sampler = DistributedSampler(datasets["train"], num_replicas=world_size, rank=rank,
                                 seed=int(config.get("seed", 42))) if world_size > 1 else None
    generator = torch.Generator().manual_seed(int(config.get("seed", 42)))
    train_loader = DataLoader(datasets["train"], batch_size=batch_size, sampler=sampler,
                              shuffle=sampler is None, generator=generator, num_workers=0)
    # Exact, non-padding partition: every validation window is counted once.
    val_indices = list(range(rank, len(datasets["validation"]), world_size))
    val_loader = DataLoader(datasets["validation"], batch_size=batch_size,
                           sampler=val_indices, num_workers=0)
    bare = model
    if world_size > 1:
        model = DistributedDataParallel(model, device_ids=[device.index] if device.type == "cuda" else None,
                                        broadcast_buffers=False)
    learning_rate = float(config.get(f"{stage}_learning_rate", 1e-5 if stage == "tokenizer" else 4e-5))
    if learning_rate <= 0 or not math.isfinite(learning_rate):
        raise ValueError("Learning rates must be positive and finite")
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=learning_rate,
        betas=tuple(config.get("adam_betas", [0.9, 0.95])),
        weight_decay=float(config.get("weight_decay", 0.01)),
    )
    max_norm = float(config.get("gradient_clip", 2.0))
    if max_norm <= 0 or not math.isfinite(max_norm):
        raise ValueError("gradient_clip must be positive and finite")
    best, bad_epochs, steps, history = math.inf, 0, 0, []
    checkpoint = output / stage
    for epoch in range(epochs):
        if sampler is not None:
            sampler.set_epoch(epoch)
        total, examples = 0.0, 0
        with causal_loss_mode(model, training=True):
            for batch in train_loader:
                optimizer.zero_grad(set_to_none=True)
                loss = _loss(stage, model, tokenizer, batch, datasets["train"].context_length, device)
                if not torch.isfinite(loss):
                    raise FloatingPointError(f"Non-finite {stage} training loss")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm, error_if_nonfinite=True)
                optimizer.step()
                size = len(batch["x"])
                total += float(loss.detach()) * size
                examples += size
                steps += 1
                if max_steps is not None and steps >= max_steps:
                    break
        validation_total, validation_examples = 0.0, 0
        # Do not use the DDP wrapper in validation: ranks may have different
        # counts, and forwards must not wait for another rank's buffer sync.
        with causal_loss_mode(bare), torch.no_grad():
            for batch_index, batch in enumerate(val_loader):
                if validation_batches is not None and batch_index >= int(validation_batches):
                    break
                loss = _loss(stage, bare, tokenizer, batch, datasets["train"].context_length, device)
                if not torch.isfinite(loss):
                    raise FloatingPointError(f"Non-finite {stage} validation loss")
                size = len(batch["x"])
                validation_total += float(loss) * size
                validation_examples += size
        metrics = torch.tensor([total, examples, validation_total, validation_examples],
                               device=device, dtype=torch.float64)
        if world_size > 1:
            dist.all_reduce(metrics, op=dist.ReduceOp.SUM)
        validation_loss = float(metrics[2] / metrics[3])
        record = {"epoch": epoch + 1, "steps": steps, "train_loss": float(metrics[0] / metrics[1]),
                  "validation_loss": validation_loss}
        history.append(record)
        if rank == 0:
            print(json.dumps({"stage": stage, **record}), flush=True)
        if validation_loss < best - float(config.get("min_delta", 0.0)):
            best, bad_epochs = validation_loss, 0
            if rank == 0:
                bare.save_pretrained(str(checkpoint))
        else:
            bad_epochs += 1
        if world_size > 1:
            dist.barrier()
        if bad_epochs >= patience or (max_steps is not None and steps >= max_steps):
            break
    return {"checkpoint": str(checkpoint), "steps": steps, "best_validation_loss": best,
            "epochs_completed": len(history), "learning_rate": learning_rate, "history": history,
            "validation_limited": validation_batches is not None}


def train(config: dict) -> dict:
    """Run a bounded or full adaptation experiment and save reloadable models.

    ``max_steps`` applies independently to each selected stage. Tiny random
    architectures can be supplied via ``tokenizer_config``/``model_config`` for
    integration tests; manifests explicitly distinguish these from pretrained
    fine-tuning. With ``calibration_end``, calibration and final test are separate
    held-out partitions. Neither enters optimization or checkpoint selection.
    """
    import numpy as np
    import pandas as pd
    import torch
    import torch.distributed as dist
    from .forecast import _checkpoint, verify_upstream

    config = dict(config)
    mode = config.get("mode", "two-stage")
    if mode not in ("two-stage", "predictor-only"):
        raise ValueError("Training mode must be two-stage or predictor-only; evaluate zero-shot separately")
    default_root = Path(__file__).resolve().parents[1]
    KronosTokenizer, Kronos = _upstream(config.get("kronos_path", default_root / "vendor/Kronos"))
    seed = int(config.get("seed", 42))
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    device, rank, world_size, owns_group = _distributed(config.get("device", "cuda" if torch.cuda.is_available() else "cpu"))
    output = Path(config.get("output_dir", f"outputs/training/{mode}")).expanduser().resolve()
    data_path = Path(config["data_csv"]).expanduser().resolve()
    try:
        frame = pd.read_csv(data_path)
        train_end, validation_end = pd.Timestamp(config["train_end"]), pd.Timestamp(config["validation_end"])
        train_end = train_end.tz_localize("UTC") if train_end.tzinfo is None else train_end
        validation_end = validation_end.tz_localize("UTC") if validation_end.tzinfo is None else validation_end
        if train_end >= validation_end:
            raise ValueError("train_end must precede validation_end")
        calibration_end = (pd.to_datetime(config["calibration_end"], utc=True)
                           if config.get("calibration_end") is not None else None)
        if calibration_end is not None and calibration_end <= validation_end:
            raise ValueError("calibration_end must follow validation_end")
        test_start = calibration_end if calibration_end is not None else validation_end
        test_end = config.get("test_end")
        if test_end is not None and pd.to_datetime(test_end, utc=True) <= test_start:
            raise ValueError("test_end must follow the start of the test partition")
        common = {"context_length": int(config.get("context_length", 128)),
                  "horizon": int(config.get("horizon", 16)), "stride": int(config.get("stride", 1)),
                  "timestamp_column": config.get("timestamp_column", "timestamps"),
                  "clip": float(config.get("clip", 5.0))}
        datasets = {
            "train": CausalWindowDataset(frame, split_start=config.get("train_start"), split_end=train_end, **common),
            "validation": CausalWindowDataset(frame, split_start=train_end, split_end=validation_end, **common),
            "test": CausalWindowDataset(frame, split_start=test_start, split_end=test_end, **common),
        }
        if calibration_end is not None:
            datasets["calibration"] = CausalWindowDataset(frame, split_start=validation_end,
                                                          split_end=calibration_end, **common)
        for split, dataset in datasets.items():
            if len(dataset) == 0:
                raise ValueError(f"{split} split has no complete windows; need context_length + horizon rows within each split")
        output_error = [None]
        if rank == 0:
            if output.exists() and (not output.is_dir() or any(output.iterdir())):
                output_error[0] = f"Training output must be empty; choose a new output_dir: {output}"
            else:
                output.mkdir(parents=True, exist_ok=True)
        if world_size > 1:
            dist.broadcast_object_list(output_error, src=0)
        if output_error[0]:
            raise FileExistsError(output_error[0])
        def initial_checkpoint(identifier, requested_revision):
            # Resolve moving Hub tags only once per distributed run. All workers
            # share this checkout/cache and must freeze the identical tokenizer.
            if world_size == 1:
                return _checkpoint(identifier, requested_revision)
            payload = [None]
            if rank == 0:
                try:
                    path, metadata = _checkpoint(identifier, requested_revision)
                    payload[0] = {"path": str(path), "metadata": metadata}
                except Exception as exc:
                    payload[0] = {"error": f"{type(exc).__name__}: {exc}"}
            dist.broadcast_object_list(payload, src=0)
            if "error" in payload[0]:
                raise RuntimeError(f"Could not resolve initial checkpoint: {payload[0]['error']}")
            return Path(payload[0]["path"]), payload[0]["metadata"]

        initial_checkpoints = {}
        if "tokenizer_config" in config:
            tokenizer = KronosTokenizer(**config["tokenizer_config"])
            initial_checkpoints["tokenizer"] = {"source": "random initialization", "seed": seed,
                                                 "config": config["tokenizer_config"]}
        else:
            path, metadata = initial_checkpoint(config.get("tokenizer_path", "NeoQuasar/Kronos-Tokenizer-base"),
                                               config.get("tokenizer_revision"))
            tokenizer = KronosTokenizer.from_pretrained(str(path))
            initial_checkpoints["tokenizer"] = metadata
        if "model_config" in config:
            model = Kronos(**config["model_config"])
            initial_checkpoints["model"] = {"source": "random initialization", "seed": seed,
                                             "config": config["model_config"]}
        else:
            path, metadata = initial_checkpoint(config.get("model_path", "NeoQuasar/Kronos-small"),
                                               config.get("model_revision"))
            model = Kronos.from_pretrained(str(path))
            initial_checkpoints["model"] = metadata
        tokenizer, model = tokenizer.to(device), model.to(device)
        if tokenizer.d_in != len(FEATURES) or (tokenizer.s1_bits, tokenizer.s2_bits) != (model.s1_bits, model.s2_bits):
            raise ValueError("Tokenizer/predictor bit sizes must match, with six OHLCVA tokenizer inputs")
        stages = {}
        if mode == "two-stage":
            stages["tokenizer"] = _train_stage("tokenizer", tokenizer, None, datasets, config, output,
                                                 device, rank, world_size)
            # Always freeze the selected checkpoint, not the last epoch's weights.
            path, metadata = _checkpoint(stages["tokenizer"]["checkpoint"], None)
            tokenizer = KronosTokenizer.from_pretrained(str(path)).to(device)
            stages["tokenizer"]["checkpoint_metadata"] = metadata
        elif rank == 0:
            tokenizer.save_pretrained(str(output / "tokenizer"))
        tokenizer.eval()
        tokenizer.requires_grad_(False)
        stages["predictor"] = _train_stage("predictor", model, tokenizer, datasets, config, output,
                                           device, rank, world_size)
        kronos_path = Path(config.get("kronos_path", default_root / "vendor/Kronos")).resolve()
        revision = verify_upstream(kronos_path)
        trained_checkpoints = {"tokenizer": _checkpoint(str(output / "tokenizer"), None)[1],
                               "model": _checkpoint(str(output / "predictor"), None)[1]}
        manifest = {
            "schema_version": 1, "mode": mode, "created_at": datetime.now(timezone.utc).isoformat(),
            "initialization": "random-test" if "model_config" in config or "tokenizer_config" in config else "pretrained",
            "kronos_revision": revision, "data_csv": str(data_path),
            "data_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
            "torch_version": torch.__version__, "device": str(device), "world_size": world_size,
            "normalization": "per-feature mean/std of context only; epsilon 1e-5; clip recorded in config",
            "predictor_objective": "future horizon only; teacher-forced dual-head cross entropy; causal attention",
            "splits": {name: {"windows": len(ds), "first": ds.sample_metadata(0),
                               "last": ds.sample_metadata(-1)} for name, ds in datasets.items()},
            "test_used_for_training_or_selection": False,
            "calibration_used_for_training_or_selection": False,
            "initial_checkpoints": initial_checkpoints, "trained_checkpoints": trained_checkpoints,
            "tokenizer_path": str(output / "tokenizer"), "model_path": str(output / "predictor"),
            "stages": stages, "config": config,
        }
        if rank == 0:
            (output / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n")
        if world_size > 1:
            dist.barrier()
        return manifest
    finally:
        if owns_group:
            dist.destroy_process_group()


def train_from_config(config_path, **overrides):
    config_path = Path(config_path).expanduser().resolve()
    config = json.loads(config_path.read_text())
    config.update({key: value for key, value in overrides.items() if value is not None})
    return train(config)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--max-steps", type=int, help="Optimizer-step limit PER stage")
    parser.add_argument("--epochs", type=int)
    parser.add_argument("--device")
    parser.add_argument("--output-dir")
    parser.add_argument("--mode", choices=("predictor-only", "two-stage"))
    args = vars(parser.parse_args(argv))
    config = args.pop("config")
    result = train_from_config(config, **args)
    if int(os.environ.get("RANK", "0")) == 0:
        print(json.dumps({"manifest": str(Path(result["model_path"]).parent / "manifest.json"),
                          "model_path": result["model_path"], "tokenizer_path": result["tokenizer_path"]}))


if __name__ == "__main__":
    main()
