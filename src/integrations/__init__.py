"""External integrations used by the GraphOne / FrontierAtlas pipeline."""

from .github import (
    GitHubLookupStatus,
    GitHubMetadata,
    GitHubRepositoryClient,
    enrich_research_paper_with_github,
)

__all__ = [
    "GitHubLookupStatus",
    "GitHubMetadata",
    "GitHubRepositoryClient",
    "enrich_research_paper_with_github",
]
