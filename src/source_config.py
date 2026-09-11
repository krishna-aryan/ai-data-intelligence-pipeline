from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from src.config.settings import load_settings


class SourceConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class SourceConfiguration:
    startups: str | None = None
    products: str | None = None
    research_papers: str | None = None
    jobs: str | None = None
    news: str | None = None

    def configured(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (name, value)
            for name, value in (
                ("startups", self.startups),
                ("products", self.products),
                ("research_papers", self.research_papers),
                ("jobs", self.jobs),
                ("news", self.news),
            )
            if value
        )

    def missing(self) -> tuple[str, ...]:
        return tuple(
            name for name, value in (
                ("STARTUP_SOURCE_URL", self.startups),
                ("PRODUCT_SOURCE_URL", self.products),
                ("RESEARCH_PAPER_SOURCE_URL", self.research_papers),
                ("JOB_SOURCE_URL", self.jobs),
                ("NEWS_SOURCE_URL", self.news),
            )
            if not value
        )


def _validate_url(name: str, value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    cleaned = value.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SourceConfigurationError(
            f"{name} must be an absolute http(s) URL."
        )
    return cleaned


def load_source_configuration() -> SourceConfiguration:
    """Load explicitly configured source URLs through the existing settings path."""
    settings = load_settings()
    configuration = SourceConfiguration(
        startups=_validate_url("STARTUP_SOURCE_URL", settings.startup_source_url),
        products=_validate_url("PRODUCT_SOURCE_URL", settings.product_source_url),
        research_papers=_validate_url("RESEARCH_PAPER_SOURCE_URL", settings.research_paper_source_url),
        jobs=_validate_url("JOB_SOURCE_URL", settings.job_source_url),
        news=_validate_url("NEWS_SOURCE_URL", settings.news_source_url),
    )
    return configuration


__all__ = ["SourceConfiguration", "SourceConfigurationError", "load_source_configuration"]