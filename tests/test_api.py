"""Offline HTTP and shared job-service integration tests with controlled work."""
from threading import Event
import time

from fastapi.testclient import TestClient
import pandas as pd
import pytest
from pydantic import ValidationError

from kronos_lab.api import create_app
from kronos_lab.service import EvaluationRequest, ForecastRequest, LabService, QueueFullError

TOKEN = "local-test-token-with-at-least-16-chars"
AUTH = {"Authorization": "Bearer " + TOKEN}


def rows():
    return [{"timestamps": stamp.isoformat(), "open": 100., "high": 102., "low": 99.,
             "close": 101., "volume": 10., "amount": 1010.}
            for stamp in pd.date_range("2026-01-01", periods=16, freq="h", tz="UTC")]


def payload(symbol="BTCUSDT"):
    return {"source": "history", "symbol": symbol, "history": rows(),
            "lookback": 8, "horizon": 2, "sample_count": 4}


class OfflineForecaster:
    def __init__(self, started=None, release=None):
        self.started, self.release = started, release
        self.calls = []

    def forecast(self, history, future_timestamps=None, config=None):
        self.calls.append((history.copy(), future_timestamps, config))
        if self.started is not None:
            self.started.set()
        if self.release is not None and not self.release.wait(timeout=10):
            raise TimeoutError("Test worker was not released")
        return {"summary": {"p_up": .75, "calibrated": False},
                "metadata": {"purpose": "offline test fake"},
                "mean": [[100., 102., 99., 101., 10., 1010.]] * config.horizon}


class SelectiveFailureService(LabService):
    def history_for(self, request):
        if request.symbol == "BAD":
            raise ValueError("Sensitive provider URL and local credential details must not escape")
        return super().history_for(request)


def await_job(client, job_id, *, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}", headers=AUTH)
        assert response.status_code == 200
        result = response.json()
        if result["status"] in {"completed", "failed"}:
            return result
        Event().wait(.01)
    pytest.fail("Offline background job did not finish")


@pytest.fixture
def client():
    service = LabService(OfflineForecaster())
    with TestClient(create_app(service, token=TOKEN)) as instance:
        yield instance


def test_public_health_and_private_jobs(client):
    assert client.get("/health").json()["orders_enabled"] is False
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}):
        response = client.post("/api/jobs", headers=headers,
                               json={"kind": "forecast", "request": payload()})
        assert response.status_code == 401
    assert client.get("/api/jobs/unknown").status_code == 401
    assert client.get("/api/jobs/unknown", headers=AUTH).status_code == 404
    assert client.get("/docs").status_code == 404


def test_non_ascii_authorization_is_rejected_without_server_error(client):
    response = client.get("/api/jobs/unknown", headers=[(b"authorization", b"Bearer \xff")])
    assert response.status_code == 401


def test_real_shared_job_lifecycle_and_bounded_queue():
    started, release = Event(), Event()
    forecaster = OfflineForecaster(started, release)
    service = LabService(forecaster, queue_size=1)
    try:
        with TestClient(create_app(service, token=TOKEN)) as client:
            submitted = client.post("/api/jobs", headers=AUTH,
                                    json={"kind": "forecast", "request": payload()})
            assert submitted.status_code == 202
            assert submitted.json()["status"] == "queued"
            job_id = submitted.json()["job_id"]
            assert started.wait(timeout=2)
            assert client.get(f"/api/jobs/{job_id}", headers=AUTH).json()["status"] == "running"
            full = client.post("/api/jobs", headers=AUTH,
                               json={"kind": "forecast", "request": payload()})
            assert full.status_code == 429
            release.set()
            completed = await_job(client, job_id)
            assert completed["status"] == "completed"
            assert completed["result"]["metadata"]["symbol"] == "BTCUSDT"
            assert completed["result"]["metadata"]["request_source"] == "history"
            assert forecaster.calls[0][2].lookback == 8
            # The slot must be returned after completion.
            followup = client.post("/api/jobs", headers=AUTH,
                                   json={"kind": "forecast", "request": payload()})
            assert followup.status_code == 202
            assert await_job(client, followup.json()["job_id"])["status"] == "completed"
    finally:
        release.set()
        service.close()


def test_batch_isolates_failures_without_leaking_exception_text():
    service = SelectiveFailureService(OfflineForecaster())
    with TestClient(create_app(service, token=TOKEN)) as client:
        response = client.post("/api/batch", headers=AUTH,
                               json={"requests": [payload("BTCUSDT"), payload("BAD"), payload("ETHUSDT")]})
        assert response.status_code == 202
        job = await_job(client, response.json()["job_id"])
        assert job["status"] == "completed"
        assert [item["symbol"] for item in job["result"]] == ["BTCUSDT", "BAD", "ETHUSDT"]
        assert "result" in job["result"][0] and "result" in job["result"][2]
        assert job["result"][1] == {"symbol": "BAD", "error": "ValueError"}
        assert "Sensitive" not in str(job)


def test_failed_single_job_releases_its_queue_slot():
    service = SelectiveFailureService(OfflineForecaster(), queue_size=1)
    with TestClient(create_app(service, token=TOKEN)) as client:
        response = client.post("/api/jobs", headers=AUTH,
                               json={"kind": "forecast", "request": payload("BAD")})
        job = await_job(client, response.json()["job_id"])
        assert job["status"] == "failed" and job["error"] == "ValueError"
        retry = client.post("/api/jobs", headers=AUTH,
                            json={"kind": "forecast", "request": payload()})
        assert retry.status_code == 202
        assert await_job(client, retry.json()["job_id"])["status"] == "completed"


@pytest.mark.parametrize("origin", ["https://evil.example", "https://testserver", "null", "http://["])
def test_cross_origin_requests_are_disabled(client, origin):
    response = client.post("/api/jobs", headers={**AUTH, "Origin": origin},
                           json={"kind": "forecast", "request": payload()})
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers


def test_same_origin_request_is_allowed(client):
    response = client.get("/health", headers={"Origin": "http://testserver"})
    assert response.status_code == 200


@pytest.mark.parametrize("status_case", ["ok", "unauthorized", "cross_origin", "too_large"])
def test_security_headers_cover_success_and_rejection(client, status_case):
    if status_case == "ok":
        response = client.get("/api/jobs/unknown", headers=AUTH)
    elif status_case == "unauthorized":
        response = client.get("/api/jobs/unknown")
    elif status_case == "cross_origin":
        response = client.get("/api/jobs/unknown", headers={"Origin": "https://evil.example"})
    else:
        response = client.post("/api/jobs", content=b"x" * 2_000_001, headers=AUTH)
        assert response.status_code == 413
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("changes", [
    {"lookback": 501}, {"horizon": 129}, {"sample_count": 65}, {"sample_count": 1},
    {"lookback": 500, "horizon": 13}, {"temperature": float("inf")}, {"top_p": 0},
    {"source": "production_exchange"}, {"symbol": "../../.env"}, {"unknown": "extra"},
    {"future_timestamps": ["2026-01-01"]},
])
def test_model_caps_reject_invalid_requests(changes):
    with pytest.raises(ValidationError):
        ForecastRequest(**{**payload(), **changes})


def test_evaluation_and_batch_request_caps(client):
    with pytest.raises(ValidationError):
        EvaluationRequest(**payload(), max_windows=41)
    for batch in ([], [payload()] * 17):
        assert client.post("/api/batch", headers=AUTH, json={"requests": batch}).status_code == 422
    assert client.post("/api/jobs", headers=AUTH,
                       json={"kind": "place_order", "request": payload()}).status_code == 422


def test_chunked_body_limit_and_normal_json_body_replay(client):
    def oversized():
        yield b"x" * 1_000_000
        yield b"y" * 1_000_000
        yield b"z"
    rejected = client.post("/api/jobs", headers=AUTH, content=oversized())
    assert rejected.status_code == 413
    assert rejected.headers["cache-control"] == "no-store"
    # Streaming-body inspection must leave valid request JSON available to
    # FastAPI's body parser after middleware has consumed the receive channel.
    accepted = client.post("/api/jobs", headers=AUTH,
                           json={"kind": "forecast", "request": payload()})
    assert accepted.status_code == 202
    assert await_job(client, accepted.json()["job_id"])["status"] == "completed"


def test_startup_requires_a_sufficiently_long_token(monkeypatch):
    monkeypatch.delenv("KRONOS_API_TOKEN", raising=False)
    for token in (None, "short"):
        with pytest.raises(ValueError, match="at least 16"):
            create_app(token=token)


def test_job_retention_is_bounded_and_service_closure_rejects_work():
    service = LabService(OfflineForecaster(), max_jobs=2)
    try:
        for _ in range(3):
            job_id = service.submit("forecast", ForecastRequest(**payload()))["job_id"]
            deadline = time.monotonic() + 2
            while service.job_status(job_id)["status"] not in {"completed", "failed"}:
                assert time.monotonic() < deadline
                Event().wait(.01)
        assert len(service._jobs) <= 2
    finally:
        service.close()
    with pytest.raises(QueueFullError, match="shutting down"):
        service.submit("forecast", ForecastRequest(**payload()))


def test_optional_paper_failure_preserves_scored_metrics(monkeypatch):
    marker = {"metrics": {"model_raw": {"close_mae": 101.0}}}
    monkeypatch.setattr("kronos_lab.evaluation.walk_forward", lambda *a, **kw: marker.copy())
    def cannot_trade(*a, **kw):
        raise ValueError("forecast_close must be a finite positive price vector")
    monkeypatch.setattr("kronos_lab.paper.paper_backtest", cannot_trade)
    service = LabService(OfflineForecaster())
    try:
        result = service.evaluate(EvaluationRequest(**payload()))
        assert result["metrics"] == marker["metrics"]
        assert "finite positive" in result["paper_trading_skipped"]
    finally:
        service.close()
