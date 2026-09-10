from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NewsArticle(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(..., min_length=1)
    source_url: str | None = None
    published_date: datetime | None = None
    raw_published_date: str | None = None
    source: str | None = None
    description: str | None = None
    author: str | None = None
    freshness_status: str | None = None
    freshness_reason: str | None = None


__all__ = ["NewsArticle"]
