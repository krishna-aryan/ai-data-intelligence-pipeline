"""Data model contracts for the intelligence pipeline."""

from .jobs import JobArticle
from .schemas import (
    BaseRecord,
    JobContent,
    JobRecord,
    NewsContent,
    NewsRecord,
    ProductContent,
    ProductRecord,
    ResearchPaperContent,
    ResearchPaperRecord,
    SourceInfo,
    StartupContent,
    StartupRecord,
)

__all__ = [
    "BaseRecord",
    "JobArticle",
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
