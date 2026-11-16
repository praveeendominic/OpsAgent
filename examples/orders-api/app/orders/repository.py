"""Order persistence.

A deliberately boring in-memory repository standing in for a database table. It is
bounded by what callers store and supports batch reads, so there is no N+1 pattern
here and nothing to blame for memory growth: `get_many` resolves a list of ids in one
pass instead of a lookup per id.
"""
from __future__ import annotations

import threading
from collections import OrderedDict

from app.orders.models import Order

# Keep the most recent orders only; older rows would live in the database in a real
# deployment. This bound exists so the repository itself cannot grow without limit.
MAX_ROWS = 10_000


class OrderRepository:
    def __init__(self, max_rows: int = MAX_ROWS) -> None:
        self._rows: OrderedDict[str, Order] = OrderedDict()
        self._max_rows = max_rows
        self._lock = threading.Lock()

    def save(self, order: Order) -> Order:
        with self._lock:
            self._rows[order.id] = order
            self._rows.move_to_end(order.id)
            while len(self._rows) > self._max_rows:
                self._rows.popitem(last=False)
        return order

    def get(self, order_id: str) -> Order | None:
        with self._lock:
            return self._rows.get(order_id)

    def get_many(self, order_ids: list[str]) -> list[Order]:
        """Single pass over the requested ids (no per-id round trip)."""
        with self._lock:
            return [self._rows[i] for i in order_ids if i in self._rows]

    def list_recent(self, limit: int = 50) -> list[Order]:
        with self._lock:
            items = list(self._rows.values())
        return items[-limit:][::-1]

    def count(self) -> int:
        with self._lock:
            return len(self._rows)


_default_repository = OrderRepository()


def get_repository() -> OrderRepository:
    return _default_repository
