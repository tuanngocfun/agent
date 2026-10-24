"""Shared bounded job service for the local HTTP dashboard and MCP tools."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
import os
from threading import BoundedSemaphore, Lock
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ForecastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(default="binance", pattern="^(binance|yfinance|vnstock|history)$")
    symbol: str = Field(default="BTCUSDT", pattern=r"^[A-Za-z0-9.^=_-]{1,30}$")
    interval: str = Field(default="1h", max_length=10)
    limit: int = Field(default=500, ge=16, le=1000)
    history: list[dict] | None = Field(default=None, max_length=4096)
    future_timestamps: list[str] | None = Field(default=None, max_length=128)
    lookback: int = Field(default=128, ge=2, le=500)
    horizon: int = Field(default=12, ge=1, le=128)
    sample_count: int = Field(default=20, ge=2, le=64)
    temperature: float = Field(default=0.6, gt=0, le=2, allow_inf_nan=False)
    top_p: float = Field(default=0.9, gt=0, le=1, allow_inf_nan=False)
    top_k: int = Field(default=0, ge=0, le=1024)
    seed: int = Field(default=42, ge=0, le=2**32 - 1)

    @model_validator(mode="after")
    def validate_window(self):
        if self.lookback + self.horizon > 512:
            raise ValueError("lookback + horizon must not exceed 512")
        if self.history is not None and self.source != "history":
            raise ValueError("Supplied candle rows require source=history")
        if self.source == "history" and not self.history:
            raise ValueError("source=history requires candle rows")
        if self.future_timestamps is not None and len(self.future_timestamps) != self.horizon:
            raise ValueError("future_timestamps must have horizon entries")
        return self

    def forecast_config(self):
        from .forecast import ForecastConfig
        return ForecastConfig(**{key: getattr(self, key) for key in (
            "lookback", "horizon", "sample_count", "temperature", "top_p", "top_k", "seed")})


class EvaluationRequest(ForecastRequest):
    include_paper: bool = True
    fee_bps: float = Field(default=10., ge=0, le=1000, allow_inf_nan=False)
    slippage_bps: float = Field(default=5., ge=0, le=1000, allow_inf_nan=False)
    max_windows: int = Field(default=8, ge=4, le=40)
    calibration_fraction: float = Field(default=0.5, gt=0, lt=1, allow_inf_nan=False)
    stride: int | None = Field(default=None, ge=1, le=512)


class QueueFullError(RuntimeError):
    pass


class LabService:
    def __init__(self, forecaster=None, *, queue_size=8, max_jobs=64):
        self._forecaster = forecaster
        self._load_lock = Lock()
        self._compute_lock = Lock()
        self._jobs_lock = Lock()
        self._slots = BoundedSemaphore(queue_size)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kronos")
        self._jobs = {}
        self._max_jobs = max_jobs

    def forecaster(self):
        with self._load_lock:
            if self._forecaster is None:
                from .forecast import KronosForecaster
                self._forecaster = KronosForecaster(
                    upstream_dir=os.environ.get("KRONOS_UPSTREAM_DIR", "vendor/Kronos"),
                    model_id=os.environ.get("KRONOS_MODEL", "NeoQuasar/Kronos-base"),
                    tokenizer_id=os.environ.get("KRONOS_TOKENIZER", "NeoQuasar/Kronos-Tokenizer-base"),
                    device=os.environ.get("KRONOS_DEVICE") or None,
                    model_revision=os.environ.get("KRONOS_MODEL_REVISION") or None,
                    tokenizer_revision=os.environ.get("KRONOS_TOKENIZER_REVISION") or None,
                )
            return self._forecaster

    def history_for(self, request):
        import pandas as pd
        from .data import fetch_binance, fetch_yfinance, fetch_vnstock, normalize_frame
        if request.history is not None:
            return normalize_frame(pd.DataFrame(request.history))
        if request.source == "binance":
            return fetch_binance(request.symbol, request.interval, request.limit)
        if request.source == "yfinance":
            return fetch_yfinance(request.symbol, interval=request.interval, period="1mo" if request.interval != "1d" else "1y").iloc[-request.limit:].copy()
        if request.source == "vnstock":
            return fetch_vnstock(request.symbol, interval=request.interval, limit=request.limit).iloc[-request.limit:].copy()
        raise ValueError("History was not supplied")

    def forecast(self, request):
        frame = self.history_for(request)
        with self._compute_lock:
            result = self.forecaster().forecast(frame,
                future_timestamps=request.future_timestamps, config=request.forecast_config())
        result.setdefault("metadata", {})["request_source"] = request.source
        result["metadata"]["symbol"] = request.symbol
        return result

    def evaluate(self, request):
        from .evaluation import walk_forward
        frame = self.history_for(request)
        with self._compute_lock:
            report = walk_forward(frame, self.forecaster(), request.forecast_config(),
                stride=request.stride, max_windows=request.max_windows,
                calibration_fraction=request.calibration_fraction)
        if request.include_paper:
            if request.stride is not None and request.stride < request.horizon:
                report["paper_trading_skipped"] = "Paper simulation requires nonoverlapping test windows"
            else:
                from .paper import paper_backtest
                try:
                    report["paper_trading"] = paper_backtest(report, frame, fee_bps=request.fee_bps, slippage_bps=request.slippage_bps)
                except ValueError as error:
                    report["paper_trading_skipped"] = "Paper simulation unavailable: " + str(error)
        return report

    def compare(self, request):
        from .comparison import compare_chronos
        frame = self.history_for(request)
        with self._compute_lock:
            kronos = self.forecaster().forecast(frame, future_timestamps=request.future_timestamps,
                                                config=request.forecast_config())
            return compare_chronos(frame, kronos, device=os.environ.get("KRONOS_CHRONOS_DEVICE", "cpu"))

    def submit(self, kind, requests):
        if kind not in ("forecast", "evaluate", "compare", "batch"):
            raise ValueError("Unsupported job type")
        if not self._slots.acquire(blocking=False):
            raise QueueFullError("Job queue is full; retry after a job finishes")
        job_id = uuid4().hex
        job = {"job_id": job_id, "kind": kind, "status": "queued",
               "created_at": datetime.now(timezone.utc).isoformat()}
        with self._jobs_lock:
            for key in list(self._jobs):
                if len(self._jobs) < self._max_jobs:
                    break
                if self._jobs[key]["status"] in ("completed", "failed"):
                    del self._jobs[key]
            self._jobs[job_id] = job
        try:
            self._executor.submit(self._run, job_id, kind, requests)
        except RuntimeError:
            self._slots.release()
            with self._jobs_lock:
                self._jobs.pop(job_id, None)
            raise QueueFullError("Service is shutting down") from None
        return {"job_id": job_id, "status": "queued"}

    def _run(self, job_id, kind, request):
        self._update(job_id, status="running")
        try:
            if kind == "batch":
                result = []
                for item in request:
                    try:
                        result.append({"symbol": item.symbol, "result": self.forecast(item)})
                    except Exception as error:
                        result.append({"symbol": item.symbol, "error": type(error).__name__})
            else:
                result = getattr(self, kind)(request)
            self._update(job_id, status="completed", result=result)
        except Exception as error:
            # Do not expose request contents, local paths or provider URLs in job errors.
            self._update(job_id, status="failed", error=type(error).__name__)
        finally:
            self._slots.release()

    def _update(self, job_id, **updates):
        with self._jobs_lock:
            self._jobs[job_id].update(updates)

    def job_status(self, job_id):
        with self._jobs_lock:
            if job_id not in self._jobs:
                raise KeyError("Unknown or expired job")
            return dict(self._jobs[job_id])

    def close(self):
        self._executor.shutdown(wait=True)
