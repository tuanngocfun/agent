"""Authenticated local FastAPI application. No exchange order endpoints."""
from contextlib import asynccontextmanager
import os
from pathlib import Path
import secrets

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from .service import EvaluationRequest, ForecastRequest, LabService, QueueFullError

WEB_ROOT = Path(__file__).parent / "web"


class JobRequest(BaseModel):
    kind: str = Field(pattern="^(forecast|evaluate|compare)$")
    request: EvaluationRequest


class BatchRequest(BaseModel):
    requests: list[ForecastRequest] = Field(min_length=1, max_length=16)


def create_app(service=None, *, token=None):
    token = token or os.environ.get("KRONOS_API_TOKEN")
    if not token or len(token) < 16:
        raise ValueError("Set KRONOS_API_TOKEN to at least 16 characters before starting the API")
    service = service or LabService()

    @asynccontextmanager
    async def lifespan(app):
        yield
        service.close()

    app = FastAPI(title="Kronos Forecasting Lab", version="1.0.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None)

    def protect(response, path):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.middleware("http")
    async def headers_and_limits(request: Request, call_next):
        if request.headers.get("origin"):
            from urllib.parse import urlsplit
            try:
                origin = urlsplit(request.headers["origin"])
            except ValueError:
                return protect(JSONResponse({"detail": "Malformed Origin header"}, status_code=403), request.url.path)
            if (origin.netloc != request.headers.get("host") or origin.scheme != request.url.scheme):
                return protect(JSONResponse({"detail": "Cross-origin requests are disabled"}, status_code=403), request.url.path)
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > 2_000_000):
            return protect(JSONResponse({"detail": "Request body too large"}, status_code=413), request.url.path)
        if request.method in ("POST", "PUT", "PATCH"):
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 2_000_000:
                    return protect(JSONResponse({"detail": "Request body too large"}, status_code=413), request.url.path)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        return protect(await call_next(request), request.url.path)

    def authorize(request: Request):
        supplied = request.headers.get("authorization", "")
        if not secrets.compare_digest(supplied.encode("utf-8"), ("Bearer " + token).encode("utf-8")):
            raise HTTPException(status_code=401, detail="A valid Bearer token is required")

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "kronos-lab", "orders_enabled": False}

    @app.get("/")
    def index():
        return FileResponse(WEB_ROOT / "index.html")

    @app.get("/assets/app.js")
    def javascript():
        return FileResponse(WEB_ROOT / "app.js", media_type="application/javascript")

    @app.get("/assets/style.css")
    def stylesheet():
        return FileResponse(WEB_ROOT / "style.css", media_type="text/css")

    @app.get("/assets/plotly.js")
    def plotly():
        from plotly.offline import get_plotlyjs
        return Response(get_plotlyjs(), media_type="application/javascript",
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.post("/api/jobs", dependencies=[Depends(authorize)], status_code=202)
    def submit(request: JobRequest):
        try:
            return service.submit(request.kind, request.request)
        except QueueFullError as error:
            raise HTTPException(status_code=429, detail=str(error)) from None

    @app.post("/api/batch", dependencies=[Depends(authorize)], status_code=202)
    def batch(request: BatchRequest):
        try:
            return service.submit("batch", request.requests)
        except QueueFullError as error:
            raise HTTPException(status_code=429, detail=str(error)) from None

    @app.get("/api/jobs/{job_id}", dependencies=[Depends(authorize)])
    def status(job_id: str):
        try:
            return service.job_status(job_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="Unknown or expired job") from None

    app.state.service = service
    return app
