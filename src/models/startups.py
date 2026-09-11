from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StartupArticle(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1)
    source_url: str | None = None
    published_date: datetime | None = None
    raw_published_date: str | None = None
    source: str | None = None
    description: str | None = None
    website: str | None = None
    founded_date: datetime | None = None
    raw_founded_date: str | None = None
    location: str | None = None
    freshness_status: str | None = None
    freshness_reason: str | None = None


__all__ = ["StartupArticle"]
