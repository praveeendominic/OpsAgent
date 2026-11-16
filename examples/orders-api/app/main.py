"""orders-api HTTP entrypoint.

Run locally:
    uvicorn app.main:app --host 0.0.0.0 --port 8080

Replay the incident (demo only):
    LEAK=1 LEAK_STEP_MB=20 LEAK_INTERVAL_S=5 uvicorn app.main:app --port 8080
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import PlainTextResponse

from app import SERVICE_NAME, __version__
from app.logging_config import configure_logging, memory_snapshot
from app.orders import cache
from app.orders.models import OrderCreate, OrderOut
from app.orders.repository import get_repository
from app.orders.service import create_order, get_order, list_orders

log = configure_logging()
_started_at = time.time()
_request_count = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("service starting")
    leak_task: asyncio.Task | None = None
    # Demo-only: opt into the leak reproduction with LEAK=1 or --leak.
    if os.environ.get("LEAK", "").lower() in {"1", "true", "yes", "on"} or "--leak" in sys.argv:
        from app.leak_demo import start_leak_task

        leak_task = start_leak_task(asyncio.get_running_loop())
    try:
        yield
    finally:
        if leak_task is not None:
            leak_task.cancel()
        log.info("service stopping")


app = FastAPI(title=SERVICE_NAME, version=__version__, lifespan=lifespan)


@app.middleware("http")
async def count_requests(request, call_next):
    global _request_count
    _request_count += 1
    return await call_next(request)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": SERVICE_NAME, "version": __version__, "uptime_s": round(time.time() - _started_at)}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    snap = memory_snapshot()
    stats = cache.cache_stats()
    lines = [
        "# TYPE orders_api_requests_total counter",
        f"orders_api_requests_total {_request_count}",
        "# TYPE orders_api_repository_rows gauge",
        f"orders_api_repository_rows {get_repository().count()}",
        "# TYPE orders_api_cache_entries gauge",
        f"orders_api_cache_entries {stats['entries']}",
        "# TYPE orders_api_cache_held_mb gauge",
        f"orders_api_cache_held_mb {stats['held_mb']}",
        "# TYPE process_resident_memory_mb gauge",
        f"process_resident_memory_mb {snap['rss_mb']}",
        "# TYPE host_mem_available_pct gauge",
        f"host_mem_available_pct {snap['mem_available_pct']}",
    ]
    return "\n".join(lines) + "\n"


@app.post("/orders", response_model=OrderOut, status_code=201)
async def post_order(data: OrderCreate) -> OrderOut:
    order = create_order(data)
    log.info("order created")
    return OrderOut.from_order(order)


@app.get("/orders", response_model=list[OrderOut])
async def get_orders(limit: int = 50) -> list[OrderOut]:
    return [OrderOut.from_order(o) for o in list_orders(limit=min(limit, 500))]


@app.get("/orders/{order_id}", response_model=OrderOut)
async def get_order_by_id(order_id: str) -> OrderOut:
    order = get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return OrderOut.from_order(order)


@app.get("/", include_in_schema=False)
async def root() -> Response:
    return Response(status_code=204)


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), log_config=None)
