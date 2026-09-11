from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from src.config.settings import load_settings
from src.models.schemas import (
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
from src.storage import SQLiteRecordRepository, default_database_path, normalize_source_url


@pytest.fixture
def startup_record() -> StartupRecord:
    return StartupRecord(
        schemaVersion="1.0",
        recordType="STARTUP",
        source=SourceInfo(name="Nova Labs", url="https://example.com/startups/alpha"),
        content=StartupContent(entityName="Nova Labs", employeeCount=42),
        collectedAt=datetime(2026, 1, 3, 9, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def product_record() -> ProductRecord:
    return ProductRecord(
        schemaVersion="1.0",
        recordType="PRODUCT",
        source=SourceInfo(name="Nova Labs", url="https://example.com/products/alpha"),
        content=ProductContent(startupName="Nova Labs", pricingModel="usage-based"),
        collectedAt=datetime(2026, 1, 4, 9, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def job_record() -> JobRecord:
    return JobRecord(
        schemaVersion="1.0",
        recordType="JOB",
        source=SourceInfo(name="Example Jobs", url="https://example.com/jobs/alpha"),
        content=JobContent(company="Nova Labs", date="2026-01-05T12:00:00Z", is_remote=True, role_family="Engineer"),
        collectedAt=datetime(2026, 1, 5, 9, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def news_record() -> NewsRecord:
    return NewsRecord(
        schemaVersion="1.0",
        recordType="NEWS",
        source=SourceInfo(name="Example News", url="https://example.com/news/alpha"),
        content=NewsContent(title="New launch", summary="Details", published_at="2026-01-06T11:00:00Z"),
        collectedAt=datetime(2026, 1, 6, 9, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def paper_record() -> ResearchPaperRecord:
    return ResearchPaperRecord(
        schemaVersion="1.0",
        recordType="RESEARCH_PAPER",
        source=SourceInfo(name="Semantic Scholar", url="https://semanticscholar.org/paper/alpha"),
        content=ResearchPaperContent(
            title="Graph Learning for Data Retrieval",
            authors=["Ada Example"],
            paper_url="https://example.com/paper/alpha",
            github_url="https://github.com/example/repo",
            github_stars=42,
            published_date="2025-12-01T12:00:00Z",
        ),
        collectedAt=datetime(2026, 1, 7, 9, 0, tzinfo=timezone.utc),
    )


def test_sqlite_repository_initializes_schema(tmp_path):
    db_path = tmp_path / "storage.sqlite3"
    repo = SQLiteRecordRepository(db_path)
    repo.initialize()

    assert db_path.exists()
    assert repo.count_by_type("STARTUP") == 0
    repo.close()


def test_insert_and_retrieve_record(startup_record, tmp_path):
    repo = SQLiteRecordRepository(tmp_path / "storage.sqlite3")
    repo.initialize()

    repo.upsert_record(startup_record)
    saved = repo.get_by_source_url("https://example.com/startups/alpha")

    assert saved is not None
    assert saved.recordType == "STARTUP"
    assert saved.source is not None
    assert str(saved.source.url) == "https://example.com/startups/alpha"
    assert saved.content.entityName == "Nova Labs"

    repo.close()


def test_duplicate_source_url_is_idempotent_and_does_not_create_duplicates(startup_record, tmp_path):
    repo = SQLiteRecordRepository(tmp_path / "storage.sqlite3")
    repo.initialize()

    repo.upsert_record(startup_record)
    updated = StartupRecord(
        schemaVersion="1.0",
        recordType="STARTUP",
        source=SourceInfo(name="Nova Labs", url="https://example.com/startups/alpha?utm=1#frag"),
        content=StartupContent(entityName="Nova Labs Updated", employeeCount=77),
        collectedAt=datetime(2026, 1, 8, 9, 0, tzinfo=timezone.utc),
    )
    repo.upsert_record(updated)

    assert repo.count_by_type("STARTUP") == 1
    saved = repo.get_by_source_url("https://example.com/startups/alpha")
    assert saved is not None
    assert saved.content.entityName == "Nova Labs Updated"
    assert saved.content.employeeCount == 77

    repo.close()


def test_bulk_upsert_commits_once_and_tracks_entity_counts(startup_record, product_record, tmp_path):
    repo = SQLiteRecordRepository(tmp_path / "storage.sqlite3")
    repo.initialize()

    repo.bulk_upsert([startup_record, product_record])

    assert repo.count_by_type("STARTUP") == 1
    assert repo.count_by_type("PRODUCT") == 1
    assert len(repo.get_by_type("STARTUP")) == 1
    assert len(repo.get_by_type("PRODUCT")) == 1

    repo.close()


def test_bulk_upsert_rolls_back_on_failure(tmp_path):
    repo = SQLiteRecordRepository(tmp_path / "storage.sqlite3")
    repo.initialize()

    valid_record = StartupRecord(
        schemaVersion="1.0",
        recordType="STARTUP",
        source=SourceInfo(name="One", url="https://example.com/startups/one"),
        content=StartupContent(entityName="One", employeeCount=1),
        collectedAt=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    with pytest.raises(TypeError):
        repo.bulk_upsert([valid_record, "not-a-record"])

    assert repo.count_by_type("STARTUP") == 0
    repo.close()


def test_get_by_type_returns_records_for_entity_type(job_record, news_record, tmp_path):
    repo = SQLiteRecordRepository(tmp_path / "storage.sqlite3")
    repo.initialize()

    repo.bulk_upsert([job_record, news_record])
    jobs = repo.get_by_type("JOB")
    news = repo.get_by_type("NEWS")

    assert len(jobs) == 1
    assert len(news) == 1
    assert jobs[0].recordType == "JOB"
    assert news[0].recordType == "NEWS"

    repo.close()


def test_retrieval_by_normalized_source_url_handles_variants(startup_record, tmp_path):
    repo = SQLiteRecordRepository(tmp_path / "storage.sqlite3")
    repo.initialize()

    repo.upsert_record(startup_record)
    saved = repo.get_by_source_url("https://example.com/startups/alpha?utm=source#top")
    assert saved is not None
    assert saved.source is not None
    assert str(saved.source.url) == "https://example.com/startups/alpha"

    repo.close()


def test_repository_persists_across_reopening(tmp_path, startup_record):
    db_path = tmp_path / "persist.sqlite3"
    repo = SQLiteRecordRepository(db_path)
    repo.initialize()
    repo.upsert_record(startup_record)
    repo.close()

    reopened = SQLiteRecordRepository(db_path)
    one = reopened.get_by_source_url("https://example.com/startups/alpha")
    assert one is not None
    assert one.content.entityName == "Nova Labs"
    reopened.close()


def test_provenance_and_freshness_metadata_are_preserved(job_record, news_record, tmp_path):
    repo = SQLiteRecordRepository(tmp_path / "storage.sqlite3")
    repo.initialize()

    repo.bulk_upsert([job_record, news_record])

    job = repo.get_by_source_url("https://example.com/jobs/alpha")
    news = repo.get_by_source_url("https://example.com/news/alpha")

    assert job is not None and job.source is not None
    assert str(job.source.url) == "https://example.com/jobs/alpha"
    assert job.content.date == "2026-01-05T12:00:00Z"

    assert news is not None and news.source is not None
    assert str(news.source.url) == "https://example.com/news/alpha"
    assert news.content.published_at == "2026-01-06T11:00:00Z"

    repo.close()


def test_default_database_path_uses_env_var(monkeypatch, tmp_path):
    target = tmp_path / "custom.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(target))
    assert default_database_path() == str(target)


def test_settings_include_database_path(monkeypatch, tmp_path):
    target = tmp_path / "settings.sqlite3"
    monkeypatch.setenv("DATABASE_PATH", str(target))
    settings = load_settings()
    assert settings.database_path == str(target)


def test_normalize_source_url_removes_fragment_and_query_and_trailing_slash():
    assert normalize_source_url("https://Example.com/Startups/Alpha?utm=1#frag") == "https://example.com/startups/alpha"
    assert normalize_source_url(" https://example.com/startups/alpha/ ") == "https://example.com/startups/alpha"
