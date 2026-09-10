from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from src.crawlers.http_client import AsyncHTTPCrawler
from src.models.schemas import ResearchPaperContent, ResearchPaperRecord, SourceInfo


class ResearchPaperAdapter:
    """Adapt Semantic Scholar research-paper responses into project models."""

    source_name = "Semantic Scholar"
    source_url = "https://semanticscholar.org"
    default_fields = (
        "title,authors,year,publicationDate,url,externalIds,openAccessPdf,"
        "externalIds,githubUrl,github_stars"
    )

    def __init__(self, crawler: AsyncHTTPCrawler | None = None) -> None:
        self.crawler = crawler or AsyncHTTPCrawler(timeout=15.0, max_concurrency=5)

    def build_search_url(self, query: str, *, limit: int = 10) -> str:
        params = {
            "query": query,
            "limit": str(limit),
            "fields": self.default_fields,
        }
        query_string = "&".join(f"{key}={value}" for key, value in params.items())
        return f"https://api.semanticscholar.org/graph/v1/paper/search?{query_string}"

    def parse_response(self, payload: dict[str, Any]) -> list[ResearchPaperRecord]:
        items = payload.get("data")
        if not isinstance(items, list):
            raise ValueError("Semantic Scholar response must contain a 'data' list")

        return [self.parse_item(item) for item in items]

    def parse_item(self, item: dict[str, Any]) -> ResearchPaperRecord:
        if not isinstance(item, dict):
            raise ValueError("Each paper item must be a dictionary")

        title = (item.get("title") or "").strip()
        if not title:
            raise ValueError("Paper title is required")

        authors = item.get("authors") or []
        author_names: list[str] = []
        for entry in authors:
            if isinstance(entry, dict):
                name = (entry.get("name") or "").strip()
                if name:
                    author_names.append(name)
            elif isinstance(entry, str):
                cleaned = entry.strip()
                if cleaned:
                    author_names.append(cleaned)

        if not author_names:
            raise ValueError("At least one author is required")

        paper_url = self._extract_paper_url(item)
        if not paper_url:
            raise ValueError("Paper URL is required")

        published_date = self._normalize_published_date(item.get("publicationDate") or item.get("year"))
        github_url, github_stars = self._extract_github_metadata(item)

        content = ResearchPaperContent(
            title=title,
            authors=author_names,
            paper_url=paper_url,
            github_url=github_url,
            github_stars=github_stars,
            published_date=published_date,
        )

        return ResearchPaperRecord(
            schemaVersion="1.0",
            recordType="RESEARCH_PAPER",
            source=SourceInfo(name=self.source_name, url=self.source_url),
            content=content,
            collectedAt=datetime.now(timezone.utc),
        )

    async def fetch_and_parse(self, query: str, *, limit: int = 10) -> list[ResearchPaperRecord]:
        url = self.build_search_url(query, limit=limit)
        response = await self.crawler.fetch(url)
        if not response.success:
            raise ValueError(f"Research paper fetch failed for {url}: {response.error}")

        payload = json.loads(response.text)
        return self.parse_response(payload)

    @staticmethod
    def _extract_paper_url(item: dict[str, Any]) -> str | None:
        open_access_pdf = item.get("openAccessPdf")
        if isinstance(open_access_pdf, dict):
            url = open_access_pdf.get("url")
            if isinstance(url, str) and url.strip():
                return url.strip()

        candidate = item.get("url")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()

        return None

    @staticmethod
    def _extract_github_metadata(item: dict[str, Any]) -> tuple[str | None, int | None]:
        github_url = item.get("githubUrl") or item.get("github_url")
        if isinstance(github_url, dict):
            github_url = github_url.get("url")

        if not isinstance(github_url, str) or not github_url.strip():
            github_url = None
        else:
            github_url = github_url.strip()

        github_stars = item.get("github_stars") or item.get("githubStars")
        if github_stars is not None:
            try:
                github_stars = int(github_stars)
            except (TypeError, ValueError):
                github_stars = None

        return github_url, github_stars

    @staticmethod
    def _normalize_published_date(value: Any) -> datetime | str | None:
        if value is None:
            return None

        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

        if isinstance(value, int):
            return datetime(value, 1, 1, tzinfo=timezone.utc)

        if isinstance(value, str):
            candidate = value.strip()
            if not candidate:
                return None

            if len(candidate) == 4:
                try:
                    return datetime.strptime(candidate, "%Y").replace(tzinfo=timezone.utc)
                except ValueError:
                    return None

            normalized = candidate.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(normalized)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except ValueError:
                for fmt in ("%Y-%m-%d", "%Y-%m"):
                    try:
                        dt = datetime.strptime(candidate, fmt)
                        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue

        return None


__all__ = ["ResearchPaperAdapter"]
