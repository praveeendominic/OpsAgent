"""The order cache never evicts: this is the defect behind the OOM incident, pinned by a test."""
from __future__ import annotations

import pytest

from app.orders import cache
from app.orders.models import Order, OrderLine


def _order(i: int, payload_bytes: int = 0) -> Order:
    return Order(
        customer_id=f"c{i}",
        lines=[OrderLine(sku="X", quantity=1, unit_price_cents=100)],
        payload=bytes(payload_bytes) if payload_bytes else None,
    )


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


def test_cache_grows_without_bound():
    n = 5_000
    for i in range(n):
        cache.remember(_order(i))
    assert len(cache.ORDER_CACHE) == n
    assert cache.cache_stats()["entries"] == n
    assert cache.cache_stats()["max_entries"] == 0  # unbounded


def test_held_bytes_tracks_payloads():
    cache.remember(_order(1, payload_bytes=1024 * 1024))
    cache.remember(_order(2, payload_bytes=1024 * 1024))
    assert cache.held_bytes() >= 2 * 1024 * 1024
    assert cache.cache_stats()["held_mb"] >= 2.0


def test_lookup_hits_and_misses():
    o = _order(1)
    cache.remember(o)
    assert cache.lookup(o.id) is o
    assert cache.lookup("missing") is None
    stats = cache.cache_stats()
    assert stats["hits"] == 1 and stats["misses"] == 1 and stats["inserts"] == 1


def test_no_eviction_api_exists():
    # Guard against someone "fixing" the sample by accident: the defect must stay reproducible.
    assert not hasattr(cache, "evict")
    assert not hasattr(cache, "MAX_ENTRIES")
