from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, StrictInt, field_validator

CHANNEL_RECEIPT = "inventory.receipt"
CHANNEL_ISSUE = "inventory.issue"
CHANNELS = (CHANNEL_RECEIPT, CHANNEL_ISSUE)

EventType = Literal["receipt", "issue"]


class InventoryEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: EventType
    sku: str
    qty: StrictInt = Field(gt=0)
    warehouse: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("sku", "warehouse")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @property
    def channel(self) -> str:
        return CHANNEL_RECEIPT if self.event_type == "receipt" else CHANNEL_ISSUE

    @property
    def signed_qty(self) -> int:
        return self.qty if self.event_type == "receipt" else -self.qty

    def to_message(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_message(cls, payload: Any) -> InventoryEvent:
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        return cls.model_validate_json(payload)
