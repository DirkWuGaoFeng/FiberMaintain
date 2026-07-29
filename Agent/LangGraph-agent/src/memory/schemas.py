"""
Memory schemas for the long-term memory store.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class FiberSnapshot(BaseModel):
    """A single fiber metric snapshot stored in long-term memory."""

    fiber_id: str = Field(description="Fiber ID")
    spanloss: float = Field(description="Span loss in dB")
    color: str = Field(description="Fiber color: GREEN, YELLOW, RED")
    summary: str = Field(default="", description="Brief analysis summary")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Snapshot timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "fiber_id": "FIB-0001",
                "spanloss": 0.35,
                "color": "YELLOW",
                "summary": "Span loss approaching threshold",
                "created_at": "2026-07-28T10:00:00",
            }
        }
