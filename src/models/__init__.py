"""Data model contracts for the intelligence pipeline."""

from .jobs import JobArticle
from .products import ProductArticle
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
from .startups import StartupArticle

__all__ = [
    "BaseRecord",
    "JobArticle",
    "JobContent",
    "JobRecord",
    "NewsContent",
    "NewsRecord",
    "ProductArticle",
    "ProductContent",
    "ProductRecord",
    "ResearchPaperContent",
    "ResearchPaperRecord",
    "SourceInfo",
    "StartupArticle",
    "StartupContent",
    "StartupRecord",
]
