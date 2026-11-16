"""In-process read cache for recently created orders.

Intent: serve GET /orders/{id} without a repository round-trip right after creation.

NOTE FOR REVIEWERS: this module is the root cause of the sample incident.
`ORDER_CACHE` is a plain module-level dict that only ever grows: `remember()` inserts
and nothing evicts (no TTL, no max size, no LRU). Under a steady stream of orders the
process RSS climbs until the kernel OOM killer terminates it. The fix is a bounded
structure (e.g. `functools.lru_cache`, `cachetools.TTLCache`, or an `OrderedDict`
with a max length) or dropping the cache in favour of the repository.
"""
from __future__ import annotations

import threading

from app.orders.models import Order

# Module-level, process-lifetime, unbounded. Grows forever.
ORDER_CACHE: dict[str, Order] = {}

_lock = threading.Lock()
_stats = {"hits": 0, "misses": 0, "inserts": 0}


def remember(order: Order) -> None:
    """Insert an order into the cache. Never evicts anything."""
    with _lock:
        ORDER_CACHE[order.id] = order
        _stats["inserts"] += 1


def lookup(order_id: str) -> Order | None:
    with _lock:
        order = ORDER_CACHE.get(order_id)
        if order is None:
            _stats["misses"] += 1
        else:
            _stats["hits"] += 1
        return order


def held_bytes() -> int:
    """Approximate bytes held by cached orders (payloads dominate)."""
    with _lock:
        return sum(o.approx_size_bytes() for o in ORDER_CACHE.values())


def cache_stats() -> dict[str, int | float]:
    with _lock:
        entries = len(ORDER_CACHE)
    return {
        "entries": entries,
        "held_mb": round(held_bytes() / (1024 * 1024), 1),
        "hits": _stats["hits"],
        "misses": _stats["misses"],
        "inserts": _stats["inserts"],
        "max_entries": 0,  # 0 == unbounded; there is no eviction policy
    }


def clear() -> None:
    """Only used by tests. Production code never calls this."""
    with _lock:
        ORDER_CACHE.clear()
        for k in _stats:
            _stats[k] = 0
