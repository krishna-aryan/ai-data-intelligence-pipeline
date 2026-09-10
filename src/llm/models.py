from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from src.models.schemas import (
    JobRecord,
    NewsRecord,
    ProductRecord,
    ResearchPaperRecord,
    SourceInfo,
    StartupRecord,
)

CanonicalRecord = StartupRecord | ProductRecord | ResearchPaperRecord | JobRecord | NewsRecord


class ExtractionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_url: HttpUrl
    raw_text: str = Field(..., min_length=1)
    source_name: str | None = None


class SourceExtractionContext(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_url: HttpUrl
    raw_text: str = Field(..., min_length=1)
    source_name: str | None = None


class ExtractionFailure(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    ok: Literal[False] = False
    error_type: Literal[
        "provider_failure",
        "invalid_json",
        "schema_validation_failure",
        "empty_response",
    ]
    message: str
    source_url: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExtractionResult(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    ok: Literal[True] = True
    source_url: str
    records: list[CanonicalRecord] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


__all__ = [
    "CanonicalRecord",
    "ExtractionFailure",
    "ExtractionRequest",
    "ExtractionResult",
    "SourceExtractionContext",
    "SourceInfo",
]
