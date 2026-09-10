from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from src.crawlers.http_client import AsyncHTTPCrawler
from src.models.schemas import ResearchPaperRecord


class GitHubLookupStatus(str, Enum):
    SUCCESS = "success"
    REPOSITORY_NOT_FOUND = "repository_not_found"
    RATE_LIMITED = "rate_limited"
    FORBIDDEN = "forbidden"
    HTTP_ERROR = "http_error"
    REQUEST_ERROR = "request_error"


class GitHubMetadata(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    owner: str | None = None
    repo: str | None = None
    stargazers_count: int | None = None
    full_name: str | None = None
    requested_url: str | None = None
    status: GitHubLookupStatus = GitHubLookupStatus.SUCCESS
    error: str | None = None


@dataclass(frozen=True)
class ParsedGitHubRepo:
    owner: str
    repo: str
    normalized_url: str


class GitHubRepositoryClient:
    def __init__(
        self,
        *,
        crawler: AsyncHTTPCrawler | None = None,
        token: str | None = None,
    ) -> None:
        self.crawler = crawler or AsyncHTTPCrawler(timeout=15.0, max_concurrency=5)
        self.token = token

    @staticmethod
    def parse_repo_url(url: str) -> ParsedGitHubRepo | None:
        if not url:
            return None

        parsed = urlparse(url.strip())
        host = (parsed.netloc or "").lower()
        if host not in {"github.com", "www.github.com"}:
            return None

        path = (parsed.path or "/").strip().strip("/")
        if not path:
            return None

        parts = []
        for segment in path.split("/"):
            cleaned = segment.strip().replace("\n", "").replace("\r", "")
            if cleaned:
                if cleaned.endswith(".git"):
                    cleaned = cleaned[:-4]
                if cleaned:
                    parts.append(cleaned)

        if len(parts) < 2:
            return None

        owner, repo = parts[0], parts[1]
        if not owner or not repo:
            return None

        normalized = f"https://github.com/{owner}/{repo}"
        return ParsedGitHubRepo(owner=owner, repo=repo, normalized_url=normalized)

    async def lookup_repository(self, repository_url: str) -> GitHubMetadata:
        parsed = self.parse_repo_url(repository_url)
        if parsed is None:
            return GitHubMetadata(
                owner=None,
                repo=None,
                requested_url=repository_url,
                status=GitHubLookupStatus.REQUEST_ERROR,
                error="Not a valid GitHub repository URL",
            )

        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        api_url = f"https://api.github.com/repos/{parsed.owner}/{parsed.repo}"
        response = await self.crawler.fetch(api_url, headers=headers)

        if not response.success:
            if response.status == 404:
                return GitHubMetadata(
                    owner=parsed.owner,
                    repo=parsed.repo,
                    requested_url=repository_url,
                    status=GitHubLookupStatus.REPOSITORY_NOT_FOUND,
                    error="Repository not found",
                )
            if response.status in {403, 429}:
                return GitHubMetadata(
                    owner=parsed.owner,
                    repo=parsed.repo,
                    requested_url=repository_url,
                    status=GitHubLookupStatus.RATE_LIMITED,
                    error="GitHub API rate limit or forbidden",
                )
            if response.status == 403:
                return GitHubMetadata(
                    owner=parsed.owner,
                    repo=parsed.repo,
                    requested_url=repository_url,
                    status=GitHubLookupStatus.FORBIDDEN,
                    error="GitHub API access forbidden",
                )
            if response.status is not None:
                return GitHubMetadata(
                    owner=parsed.owner,
                    repo=parsed.repo,
                    requested_url=repository_url,
                    status=GitHubLookupStatus.HTTP_ERROR,
                    error=f"HTTP {response.status}",
                )
            return GitHubMetadata(
                owner=parsed.owner,
                repo=parsed.repo,
                requested_url=repository_url,
                status=GitHubLookupStatus.REQUEST_ERROR,
                error=response.error or "GitHub request failed",
            )

        try:
            payload = json.loads(response.text)
        except (TypeError, ValueError):
            return GitHubMetadata(
                owner=parsed.owner,
                repo=parsed.repo,
                requested_url=repository_url,
                status=GitHubLookupStatus.REQUEST_ERROR,
                error="Invalid GitHub JSON response",
            )

        stargazers_count = payload.get("stargazers_count")
        try:
            stargazers_count = int(stargazers_count)
        except (TypeError, ValueError):
            stargazers_count = None

        return GitHubMetadata(
            owner=parsed.owner,
            repo=parsed.repo,
            stargazers_count=stargazers_count,
            full_name=payload.get("full_name") or f"{parsed.owner}/{parsed.repo}",
            requested_url=repository_url,
            status=GitHubLookupStatus.SUCCESS,
        )


async def enrich_research_paper_with_github(
    paper: ResearchPaperRecord,
    *,
    github_client: GitHubRepositoryClient | None = None,
) -> ResearchPaperRecord:
    if paper.content.github_url is None:
        return paper

    client = github_client or GitHubRepositoryClient()
    github_meta = await client.lookup_repository(str(paper.content.github_url))

    if github_meta.status == GitHubLookupStatus.SUCCESS:
        paper.content.github_stars = github_meta.stargazers_count
    else:
        paper.content.github_stars = None

    return paper


__all__ = ["GitHubMetadata", "GitHubLookupStatus", "GitHubRepositoryClient", "enrich_research_paper_with_github"]
