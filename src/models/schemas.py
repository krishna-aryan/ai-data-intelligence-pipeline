from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class SourceInfo(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1)
    url: HttpUrl


class EntityResolutionMetadata(BaseModel):
    original_name: str
    normalized_name: str
    canonical_name: str | None = None
    match_type: Literal["exact_canonical", "exact_alias", "unresolved"] = "unresolved"
    reason: str = ""
    source_url: str | None = None


class StartupContent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    entityName: str = Field(..., min_length=1)
    employeeCount: int | None = Field(default=None, ge=0)
    entityResolution: EntityResolutionMetadata | None = None


class ProductContent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    startupName: str = Field(..., min_length=1)
    pricingModel: str | None = Field(default=None, min_length=1)
    entityResolution: EntityResolutionMetadata | None = None


class ResearchPaperContent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(..., min_length=1)
    authors: list[str] = Field(default_factory=list)
    paper_url: HttpUrl
    github_url: HttpUrl | None = None
    github_stars: int | None = Field(default=None, ge=0)
    published_date: datetime | str | None = None

    @field_validator("authors")
    @classmethod
    def validate_authors(cls, value):
        if not value:
            raise ValueError("authors must not be empty")
        return [item.strip() for item in value if item and item.strip()]


class JobContent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    company: str = Field(..., min_length=1)
    date: str | datetime
    is_remote: bool = False
    role_family: str = Field(..., min_length=1)


class NewsContent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(..., min_length=1)
    summary: str | None = None
    published_at: str | datetime | None = None


class BaseRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    schemaVersion: str = Field(..., min_length=1)
    recordType: str
    source: SourceInfo | None = None
    content: object
    collectedAt: datetime | str


class StartupRecord(BaseRecord):
    recordType: Literal["STARTUP"]
    content: StartupContent


class ProductRecord(BaseRecord):
    recordType: Literal["PRODUCT"]
    content: ProductContent


class ResearchPaperRecord(BaseRecord):
    recordType: Literal["RESEARCH_PAPER"]
    content: ResearchPaperContent


class JobRecord(BaseRecord):
    recordType: Literal["JOB"]
    content: JobContent


class NewsRecord(BaseRecord):
    recordType: Literal["NEWS"]
    source: SourceInfo | None = None
    content: NewsContent


__all__ = [
    "BaseRecord",
    "EntityResolutionMetadata",
    "JobContent",
    "JobRecord",
    "NewsContent",
    "NewsRecord",
    "ProductContent",
    "ProductRecord",
    "ResearchPaperContent",
    "ResearchPaperRecord",
    "SourceInfo",
    "StartupContent",
    "StartupRecord",
]
