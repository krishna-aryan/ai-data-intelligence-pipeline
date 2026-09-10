from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class DateParseResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    original_value: Any = None
    normalized_datetime: datetime | None = None
    parsing_method: str = "unknown"
    timezone_assumption: str | None = None
    status: Literal["parsed", "unparseable", "missing"] = "unparseable"
    reason: str = ""


class FreshnessResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    publication_datetime: datetime | None = None
    reference_datetime: datetime
    age_seconds: int | None = None
    max_age_hours: float = 24
    status: Literal["fresh", "stale", "unknown", "future"] = "unknown"
    reason: str = ""


__all__ = ["DateParseResult", "FreshnessResult"]
