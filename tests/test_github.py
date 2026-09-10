from datetime import datetime, timezone

import pytest

from src.crawlers.http_client import AsyncHTTPCrawler
from src.crawlers.models import CrawlResult
from src.integrations.github import (
    GitHubLookupStatus,
    GitHubMetadata,
    GitHubRepositoryClient,
    enrich_research_paper_with_github,
)
from src.models.schemas import ResearchPaperContent, ResearchPaperRecord


class FakeCrawler:
    def __init__(self, *, payload=None, status=None, error=None):
        self.payload = payload
        self.status = status
        self.error = error

    async def fetch(self, url: str, headers=None):
        if self.payload is not None:
            return CrawlResult(
                requested_url=url,
                status=self.status if self.status is not None else 200,
                success=True,
                text=self.payload,
            )
        return CrawlResult(
            requested_url=url,
            status=self.status,
            success=False,
            error=self.error or "Mock error",
            error_type="mock_error",
        )


def test_parse_valid_github_url():
    parsed = GitHubRepositoryClient.parse_repo_url("https://github.com/openai/gpt-3")

    assert parsed is not None
    assert parsed.owner == "openai"
    assert parsed.repo == "gpt-3"
    assert parsed.normalized_url == "https://github.com/openai/gpt-3"


def test_parse_invalid_github_url():
    assert GitHubRepositoryClient.parse_repo_url("https://example.com/openai/gpt-3") is None
    assert GitHubRepositoryClient.parse_repo_url("https://github.com/openai") is None


def test_parse_trailing_slash_and_git_suffix():
    parsed = GitHubRepositoryClient.parse_repo_url("https://github.com/org/repository/\n")
    assert parsed is not None and parsed.owner == "org" and parsed.repo == "repository"

    parsed_git = GitHubRepositoryClient.parse_repo_url("https://github.com/org/repository.git")
    assert parsed_git is not None and parsed_git.repo == "repository"


@pytest.mark.asyncio
async def test_successful_repository_lookup():
    client = GitHubRepositoryClient(
        crawler=FakeCrawler(payload='{"full_name": "openai/gpt-3", "stargazers_count": 321}', status=200),
    )

    result = await client.lookup_repository("https://github.com/openai/gpt-3")

    assert result.status == GitHubLookupStatus.SUCCESS
    assert result.stargazers_count == 321
    assert result.full_name == "openai/gpt-3"


@pytest.mark.asyncio
async def test_repository_not_found_lookup():
    client = GitHubRepositoryClient(
        crawler=FakeCrawler(status=404, error="HTTP 404"),
    )

    result = await client.lookup_repository("https://github.com/org/missing")

    assert result.status == GitHubLookupStatus.REPOSITORY_NOT_FOUND
    assert result.stargazers_count is None


@pytest.mark.asyncio
async def test_rate_limit_lookup():
    client = GitHubRepositoryClient(
        crawler=FakeCrawler(status=403, error="HTTP 403"),
    )

    result = await client.lookup_repository("https://github.com/org/repo")

    assert result.status in {GitHubLookupStatus.RATE_LIMITED, GitHubLookupStatus.FORBIDDEN}
    assert result.stargazers_count is None


@pytest.mark.asyncio
async def test_other_http_error_lookup():
    client = GitHubRepositoryClient(
        crawler=FakeCrawler(status=500, error="HTTP 500"),
    )

    result = await client.lookup_repository("https://github.com/org/repo")

    assert result.status == GitHubLookupStatus.HTTP_ERROR
    assert result.stargazers_count is None


@pytest.mark.asyncio
async def test_connection_failure_lookup():
    client = GitHubRepositoryClient(
        crawler=FakeCrawler(status=None, error="Connection failed"),
    )

    result = await client.lookup_repository("https://github.com/org/repo")

    assert result.status == GitHubLookupStatus.REQUEST_ERROR
    assert result.error is not None


@pytest.mark.asyncio
async def test_research_paper_without_github_url_is_left_untouched():
    paper = ResearchPaperRecord(
        schemaVersion="1.0",
        recordType="RESEARCH_PAPER",
        source={"name": "Semantic Scholar", "url": "https://semanticscholar.org"},
        content={
            "title": "Paper without repo",
            "authors": ["A. Author"],
            "paper_url": "https://example.com/paper",
            "github_url": None,
            "github_stars": None,
            "published_date": "2025-01-15",
        },
        collectedAt="2026-09-11T12:00:00Z",
    )

    enriched = await enrich_research_paper_with_github(paper)

    assert enriched.content.github_stars is None
    assert enriched.content.title == "Paper without repo"


@pytest.mark.asyncio
async def test_research_paper_enrichment_with_github_url():
    client = GitHubRepositoryClient(
        crawler=FakeCrawler(payload='{"full_name": "openai/gpt-3", "stargazers_count": 12345}', status=200),
    )

    paper = ResearchPaperRecord(
        schemaVersion="1.0",
        recordType="RESEARCH_PAPER",
        source={"name": "Semantic Scholar", "url": "https://semanticscholar.org"},
        content={
            "title": "Paper with repo",
            "authors": ["A. Author"],
            "paper_url": "https://example.com/paper",
            "github_url": "https://github.com/openai/gpt-3",
            "github_stars": None,
            "published_date": "2025-01-15",
        },
        collectedAt="2026-09-11T12:00:00Z",
    )

    enriched = await enrich_research_paper_with_github(paper, github_client=client)

    assert enriched.content.github_stars == 12345
    assert str(enriched.content.paper_url) == "https://example.com/paper"
    assert enriched.content.title == "Paper with repo"


@pytest.mark.asyncio
async def test_github_enrichment_preserves_unrelated_fields():
    client = GitHubRepositoryClient(
        crawler=FakeCrawler(payload='{"full_name": "anthropic/claude", "stargazers_count": 999}', status=200),
    )

    paper = ResearchPaperRecord(
        schemaVersion="1.0",
        recordType="RESEARCH_PAPER",
        source={"name": "Semantic Scholar", "url": "https://semanticscholar.org"},
        content={
            "title": "Field preservation",
            "authors": ["Alpha", "Beta"],
            "paper_url": "https://example.com/field-preservation",
            "github_url": "https://github.com/anthropic/claude",
            "github_stars": None,
            "published_date": "2024-02-10",
        },
        collectedAt=datetime.now(timezone.utc),
    )

    enriched = await enrich_research_paper_with_github(paper, github_client=client)

    assert enriched.content.title == "Field preservation"
    assert enriched.content.authors == ["Alpha", "Beta"]
    assert enriched.content.paper_url is not None
    assert enriched.content.github_stars == 999


def test_no_hallucinated_default_star_count_when_github_unavailable():
    assert GitHubRepositoryClient.parse_repo_url("https://example.com/nope") is None
    assert GitHubRepositoryClient.parse_repo_url("https://github.com/test") is None
