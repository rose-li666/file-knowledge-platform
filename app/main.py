import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .database import Probe, open_database
from .embedding import LocalEmbedder, PROJECT_ROOT, SPEC

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    started = time.perf_counter()
    data_dir = Path(os.environ.get("DATA_DIR", str(PROJECT_ROOT / "data"))).resolve()
    for name in ["db", "uploads", "tmp", "quarantine"]:
        (data_dir / name).mkdir(parents=True, exist_ok=True)
    # Verify actual write access, rather than relying on a permission bit.
    probe_file = data_dir / "tmp" / "startup-write-probe"
    probe_file.write_bytes(b"m1")
    probe_file.unlink()
    app.state.engine = open_database(data_dir / "db" / "diagnostics.sqlite3")
    app.state.data_dir = data_dir
    app.state.model = None
    app.state.model_status = "loading"
    try:
        app.state.model = await asyncio.to_thread(
            LocalEmbedder,
            Path(os.environ.get("MODEL_DIR", str(PROJECT_ROOT / "models" / "bge"))),
        )
        app.state.model_status = "ready"
    except Exception:
        logger.exception("Local model load failed")
        app.state.model_status = "failed"
    app.state.startup_seconds = time.perf_counter() - started
    yield
    app.state.engine.dispose()


app = FastAPI(title="文件管理与知识检索平台 — M1", lifespan=lifespan)


@app.get("/api/v1/health")
def health():
    try:
        with Session(app.state.engine) as session:
            session.execute(text("SELECT 1")).scalar_one()
            count = session.scalar(select(func.count()).select_from(Probe))
        database_status = "ready"
    except Exception:
        logger.exception("Database health check failed")
        database_status, count = "failed", None
    payload = {
        "milestone": "M1",
        "status": "ready" if database_status == "ready" and app.state.model_status == "ready" else "degraded",
        "database": {"status": database_status, "probeCount": count},
        "storage": {"startupWriteCheck": "passed"},
        "model": {
            "status": app.state.model_status, "id": SPEC["id"],
            "revision": SPEC["revision"], "dimension": SPEC["dimension"], "device": "cpu",
            "loadSeconds": round(app.state.model.load_seconds, 3) if app.state.model else None,
        },
        "startupSeconds": round(app.state.startup_seconds, 3),
    }
    # Model readiness is reported independently. A model error must not kill base services.
    return JSONResponse(payload, status_code=200 if database_status == "ready" else 503)


class ProbeRequest(BaseModel):
    value: str = Field(min_length=1, max_length=200)


@app.post("/api/v1/m1/probes", status_code=201)
def create_probe(body: ProbeRequest):
    with Session(app.state.engine) as session:
        probe = Probe(value=body.value)
        session.add(probe)
        session.commit()
        session.refresh(probe)
        return {"id": probe.id, "value": probe.value}


@app.get("/api/v1/m1/probes")
def list_probes():
    with Session(app.state.engine) as session:
        rows = session.scalars(select(Probe).order_by(Probe.id.desc()).limit(20)).all()
        return {"items": [{"id": row.id, "value": row.value} for row in rows]}


frontend_dist = PROJECT_ROOT / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
