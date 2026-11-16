"""Pydantic models for the orders API."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field


def _new_id() -> str:
    return uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class OrderLine(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, le=10_000)
    unit_price_cents: int = Field(ge=0)


class OrderCreate(BaseModel):
    customer_id: str = Field(min_length=1, max_length=64)
    lines: list[OrderLine] = Field(min_length=1)
    note: str | None = Field(default=None, max_length=2_000)


class Order(BaseModel):
    id: str = Field(default_factory=_new_id)
    customer_id: str
    lines: list[OrderLine]
    note: str | None = None
    status: str = "created"
    created_at: datetime = Field(default_factory=_now)
    # Free-form attachment (receipt rendering, audit blob). Not size-limited on purpose;
    # the demo leak uses it to carry a large synthetic payload.
    payload: bytes | None = Field(default=None, repr=False)

    @property
    def total_cents(self) -> int:
        return sum(line.quantity * line.unit_price_cents for line in self.lines)

    def approx_size_bytes(self) -> int:
        """Rough in-memory footprint used by cache statistics."""
        size = 256 + 64 * len(self.lines)
        if self.note:
            size += len(self.note)
        if self.payload is not None:
            size += len(self.payload)
        return size


class OrderOut(BaseModel):
    id: str
    customer_id: str
    lines: list[OrderLine]
    note: str | None
    status: str
    created_at: datetime
    total_cents: int

    @classmethod
    def from_order(cls, order: Order) -> "OrderOut":
        return cls(
            id=order.id,
            customer_id=order.customer_id,
            lines=order.lines,
            note=order.note,
            status=order.status,
            created_at=order.created_at,
            total_cents=order.total_cents,
        )
