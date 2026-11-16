"""Service layer: validation, persistence and the read cache."""
from __future__ import annotations

from app.orders import cache
from app.orders.models import Order, OrderCreate
from app.orders.repository import get_repository


def create_order(data: OrderCreate, payload: bytes | None = None) -> Order:
    order = Order(customer_id=data.customer_id, lines=data.lines, note=data.note, payload=payload)
    get_repository().save(order)
    # Warm the read cache so the follow-up GET is served from memory.
    cache.remember(order)
    return order


def get_order(order_id: str) -> Order | None:
    cached = cache.lookup(order_id)
    if cached is not None:
        return cached
    return get_repository().get(order_id)


def list_orders(limit: int = 50) -> list[Order]:
    return get_repository().list_recent(limit=limit)
