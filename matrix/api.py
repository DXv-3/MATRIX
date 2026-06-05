from __future__ import annotations

import logging
import subprocess
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from matrix.config import scan_roots
from matrix.db import Database
from matrix.events import bus
from matrix.logging_config import setup_logging
from matrix.preview import generate_preview
from matrix.reveal import reveal_asset_in_finder
from matrix.security import PathValidationError, resolve_directory
from matrix.settings import load_env, settings

load_env()
from matrix.services import (
    approve_group,
    get_asset,
    get_groups_export,
    get_report,
    list_assets,
    list_lineage,
    list_pending_groups,
    run_dedup_pipeline,
    run_full_pipeline,
    run_scan_from_path,
)

log = logging.getLogger("matrix.api")
STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"

# Simple rate limit: max requests per IP per minute on mutating endpoints
_RATE: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 30
_RATE_WINDOW = 60.0


@asynccontextmanager
async def lifespan(_app: FastAPI):
    load_env()
    setup_logging()
    cfg = settings()
    errs = cfg.validate_production()
    if errs:
        for e in errs:
            log.error("production config: %s", e)
        if cfg.production:
            raise RuntimeError("Invalid production configuration: " + "; ".join(errs))
    log.info("MATRIX API started env=%s host=%s", cfg.env, cfg.api_host)
    yield
    log.info("MATRIX API shutdown")


app = FastAPI(
    title="MATRIX",
    version="1.2.0",
    description="Photo archive intelligence API",
    lifespan=lifespan,
)


@lru_cache
def get_db() -> Database:
    db = Database()
    db.init_schema()
    return db


def _check_auth(request: Request) -> None:
    cfg = settings()
    token = cfg.api_token
    if cfg.production and not token:
        raise HTTPException(503, "API token not configured")
    if not token:
        return
    auth = request.headers.get("Authorization", "")
    if auth == f"Bearer {token}":
        return
    if request.query_params.get("token") == token:
        return
    raise HTTPException(401, "Unauthorized")


def _rate_limit(request: Request) -> None:
    if settings().env == "development":
        return
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    window = _RATE[ip]
    window[:] = [t for t in window if now - t < _RATE_WINDOW]
    if len(window) >= _RATE_LIMIT:
        raise HTTPException(429, "Too many requests")
    window.append(now)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    protected = (
        request.url.path.startswith("/api/")
        and request.url.path not in ("/api/health", "/health")
    ) or request.url.path in {"/scan", "/dedup", "/approve"}
    if protected:
        try:
            _check_auth(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    if request.method in ("POST", "PUT", "DELETE") and request.url.path.startswith("/api/"):
        try:
            _rate_limit(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


cfg_init = settings()
if cfg_init.production:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            f"http://127.0.0.1:{cfg_init.api_port}",
            f"http://localhost:{cfg_init.api_port}",
        ],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )


class ScanRequest(BaseModel):
    root: str = Field(..., min_length=1, max_length=4096)
    workers: int = Field(4, ge=1, le=32)

    @field_validator("root")
    @classmethod
    def strip_root(cls, v: str) -> str:
        return v.strip()


class PipelineRequest(ScanRequest):
    pass


class ApproveRequest(BaseModel):
    group_id: int = Field(..., ge=1)
    action: str = Field(..., pattern="^(KEEP_ALL|DELETE_DUPLICATES|SKIP|MANUAL)$")
    dry_run: bool = True


@app.exception_handler(PathValidationError)
async def path_validation_handler(_request: Request, exc: PathValidationError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def _health_payload() -> dict:
    db = get_db()
    try:
        row = db.fetchone("SELECT COUNT(*) AS c FROM assets")
        assets = row["c"] if row else 0
        db_ok = True
    except Exception as exc:
        log.exception("health db check failed")
        assets = 0
        db_ok = False
        return {
            "status": "degraded",
            "db": False,
            "error": str(exc),
            "assets": assets,
        }
    return {
        "status": "ok" if db_ok else "degraded",
        "app": "matrix",
        "version": "1.2.0",
        "environment": settings().env,
        "db": db_ok,
        "assets": assets,
        "catalog": str(db.path),
    }


@app.get("/health")
@app.get("/api/health")
def health() -> dict:
    return _health_payload()


@app.get("/api/report")
def report() -> dict:
    return get_report(get_db())


@app.get("/api/config")
def config() -> dict:
    cfg = settings()
    return {
        "scan_roots": [str(p) for p in scan_roots()],
        "environment": cfg.env,
        "production": cfg.production,
        "auth_required": bool(cfg.api_token),
    }


@app.get("/api/assets")
def assets(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)) -> dict:
    return list_assets(get_db(), limit=limit, offset=offset)


@app.get("/api/assets/{asset_id}")
def asset_detail(asset_id: int) -> dict:
    if asset_id < 1:
        raise HTTPException(400, "invalid asset_id")
    row = get_asset(get_db(), asset_id)
    if not row:
        raise HTTPException(404, "asset not found")
    return row


@app.get("/api/assets/{asset_id}/preview")
def asset_preview(asset_id: int) -> Response:
    if asset_id < 1:
        raise HTTPException(400, "invalid asset_id")
    result = generate_preview(get_db(), asset_id)
    if not result:
        raise HTTPException(404, "preview unavailable")
    data, mime = result
    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": "private, max-age=300"},
    )


@app.post("/api/assets/{asset_id}/reveal")
def asset_reveal(asset_id: int) -> dict:
    if asset_id < 1:
        raise HTTPException(400, "invalid asset_id")
    try:
        return reveal_asset_in_finder(get_db(), asset_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(501, str(exc)) from exc
    except subprocess.CalledProcessError as exc:
        raise HTTPException(500, "could not open Finder") from exc


@app.get("/api/groups")
def groups() -> dict:
    return get_groups_export(get_db())


@app.get("/api/groups/pending")
def groups_pending() -> dict:
    items = list_pending_groups(get_db())
    return {"count": len(items), "items": items}


@app.get("/api/lineage")
def lineage(limit: int = Query(50, ge=1, le=200)) -> dict:
    items = list_lineage(get_db(), limit=limit)
    return {"count": len(items), "items": items}


@app.post("/api/scan")
def scan(req: ScanRequest) -> dict:
    bus.publish("scan.start", {"root": req.root})
    try:
        stats = run_scan_from_path(get_db(), req.root, workers=req.workers)
        bus.publish("scan.done", stats)
        return stats
    except PathValidationError:
        raise
    except Exception as exc:
        bus.publish("scan.error", {"error": str(exc)})
        log.exception("scan failed")
        raise HTTPException(500, "scan failed") from exc


@app.post("/api/dedup")
def dedup() -> dict:
    bus.publish("dedup.start", {})
    stats = run_dedup_pipeline(get_db())
    bus.publish("dedup.done", stats)
    return stats


@app.post("/api/pipeline")
def pipeline(req: PipelineRequest) -> dict:
    bus.publish("pipeline.start", {"root": req.root})
    try:
        stats = run_full_pipeline(get_db(), req.root, workers=req.workers)
        bus.publish("pipeline.done", stats)
        return stats
    except PathValidationError:
        raise
    except Exception as exc:
        bus.publish("pipeline.error", {"error": str(exc)})
        log.exception("pipeline failed")
        raise HTTPException(500, "pipeline failed") from exc


@app.post("/api/approve")
def approve(req: ApproveRequest) -> dict:
    try:
        result = approve_group(get_db(), req.group_id, req.action, req.dry_run)
        bus.publish("review.action", {"group_id": req.group_id, **result})
        return result
    except LookupError:
        raise HTTPException(404, "group not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except PathValidationError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/events")
async def events_stream() -> StreamingResponse:
    return StreamingResponse(
        bus.sse_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/scan")
def scan_legacy(req: ScanRequest) -> dict:
    return scan(req)


@app.post("/dedup")
def dedup_legacy() -> dict:
    return dedup()


@app.get("/groups")
def groups_legacy() -> dict:
    return groups()


@app.post("/approve")
def approve_legacy(req: ApproveRequest) -> dict:
    return approve(req)


@app.get("/report")
def report_legacy() -> dict:
    return report()


@app.get("/")
def ui_index() -> FileResponse:
    index = STATIC_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(503, "Web UI not installed")
    return FileResponse(index)


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")