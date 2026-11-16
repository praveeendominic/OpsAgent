# orders-api

A small FastAPI order service. It is the sample application that OpsAgent's Code
Correlation crew reads when it has to decide whether an OOM kill on the host is a code
defect or an infrastructure sizing issue.

## Layout

```
app/
  main.py              FastAPI app: POST /orders, GET /orders/{id}, GET /health, GET /metrics
  logging_config.py    JSON log lines (ts, level, service, host, pid, msg, rss_mb, held_mb, mem_available_pct)
  leak_demo.py         DEMO ONLY: background task that replays the production leak
  orders/
    models.py          Order / OrderCreate / OrderOut
    repository.py      bounded in-memory store (negative example: nothing wrong here)
    cache.py           module-level ORDER_CACHE that never evicts  <-- the defect
    service.py         create_order() -> repository.save() + cache.remember()
deploy/orders-api.service   systemd unit (Restart=always, no MemoryHigh/MemoryMax)
tests/test_cache.py         proves the cache never evicts
```

## Run

```
pip install -r requirements.txt
uvicorn app.main:app --port 8080
curl -s -X POST localhost:8080/orders -H 'content-type: application/json' \
  -d '{"customer_id":"c1","lines":[{"sku":"A","quantity":2,"unit_price_cents":500}]}'
```

## Replay the incident

```
LEAK=1 LEAK_STEP_MB=20 LEAK_INTERVAL_S=5 uvicorn app.main:app --port 8080
```

The log shows `"msg": "gradual leak started"` once, then `"msg": "order cache grew"` every
5 seconds with `rss_mb` climbing by about 20 MB per line, until the kernel OOM killer
terminates the process. With the shipped systemd unit (`Restart=always`, no memory
limit) the service comes back after 5 seconds and the cycle repeats.

## Known defect

`app/orders/cache.py` keeps `ORDER_CACHE: dict[str, Order]` at module level and
`remember()` only inserts. There is no TTL, no maximum size and no eviction, so memory
grows with every order created. The repository (`app/orders/repository.py`) is bounded
and is not the cause.

## Tests

```
python -m pytest tests -q
```
