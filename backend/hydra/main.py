"""HTTP API and dashboard. Run with: uvicorn hydra.main:app --app-dir backend"""
from __future__ import annotations

import threading
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from .config import ROOT, Config
from .engine import Hydra

config = Config.from_env()
hydra = Hydra.from_config(config)
stop = threading.Event()


def control_loop() -> None:
    while not stop.is_set():
        started = time.monotonic()
        try:
            hydra.tick()
        except Exception as exc:  # keep monitoring through unexpected errors
            hydra.store.add_event("error", f"Control loop error: {exc}")
        stop.wait(max(0.0, config.probe_interval - (time.monotonic() - started)))


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Live mode spends money, so it waits for POST /api/deploy.
    if config.mode != "live":
        hydra.start()
    elif hydra.replicas:
        hydra.running = True
    thread = threading.Thread(target=control_loop, daemon=True)
    thread.start()
    yield
    stop.set()
    thread.join(timeout=5)


app = FastAPI(title="Hydra", lifespan=lifespan)


@app.get("/api/state")
def state() -> dict:
    return hydra.state()


@app.post("/api/deploy")
def deploy() -> dict:
    hydra.start()
    return {"running": True}


@app.post("/api/chaos")
def chaos(replica_id: Optional[str] = None) -> dict:
    victim = hydra.chaos(replica_id)
    if victim is None:
        raise HTTPException(status_code=404, detail="No live replica to kill")
    return {"killed": victim.id, "provider": victim.provider}


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    page = (ROOT / "frontend" / "index.html").read_text()
    return '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">' + page
