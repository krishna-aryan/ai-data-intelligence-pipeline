from datetime import datetime

import pytest
from pydantic import ValidationError

from src.models.schemas import (
    JobRecord,
    NewsRecord,
    ProductRecord,
    ResearchPaperRecord,
    SourceInfo,
    StartupRecord,
)


def test_startup_record_validates_required_fields():
    payload = {
        "schemaVersion": "1.0",
        "recordType": "STARTUP",
        "source": {"name": "Crunchbase", "url": "https://example.com/startup"},
        "content": {"entityName": "GraphOne"},
        "collectedAt": "2026-09-11T12:00:00Z",
    }

    startup = StartupRecord.model_validate(payload)

    assert startup.recordType == "STARTUP"
    assert startup.content.entityName == "GraphOne"
    assert startup.source.name == "Crunchbase"


def test_product_record_optional_fields_are_allowed():
    payload = {
        "schemaVersion": "1.0",
        "recordType": "PRODUCT",
        "source": {"name": "Product Hunt", "url": "https://example.com/product"},
        "content": {
            "startupName": "GraphOne",
            "pricingModel": "usage_based",
        },
        "collectedAt": "2026-09-11T12:00:00Z",
    }

    product = ProductRecord.model_validate(payload)

    assert product.content.pricingModel == "usage_based"
    assert str(product.source.url).startswith("https://")


def test_research_paper_record_requires_title_and_url():
    payload = {
        "schemaVersion": "1.0",
        "recordType": "RESEARCH_PAPER",
        "content": {
            "title": "A scalable retrieval architecture",
            "authors": ["Ada Lovelace", "Grace Hopper"],
            "paper_url": "https://arxiv.org/abs/1234.5678",
            "github_url": "https://github.com/example/repo",
            "github_stars": 120,
            "published_date": "2026-08-01T00:00:00Z",
        },
        "collectedAt": "2026-09-11T12:00:00Z",
    }

    paper = ResearchPaperRecord.model_validate(payload)

    assert paper.content.title == "A scalable retrieval architecture"
    assert paper.content.github_stars == 120


def test_job_record_requires_company_and_role_family():
    payload = {
        "schemaVersion": "1.0",
        "recordType": "JOB",
        "content": {
            "company": "GraphOne",
            "date": "2026-09-10",
            "is_remote": True,
            "role_family": "machine_learning",
        },
        "collectedAt": "2026-09-11T12:00:00Z",
    }

    job = JobRecord.model_validate(payload)

    assert job.recordType == "JOB"
    assert job.content.is_remote is True


def test_news_record_allows_optional_metadata():
    payload = {
        "schemaVersion": "1.0",
        "recordType": "NEWS",
        "source": {"name": "TechCrunch", "url": "https://techcrunch.com"},
        "content": {
            "title": "AI startup raises new funding",
            "summary": "The company announced a new AI financing round.",
            "published_at": "2026-09-11T11:00:00Z",
        },
        "collectedAt": "2026-09-11T12:00:00Z",
    }

    news = NewsRecord.model_validate(payload)

    assert news.recordType == "NEWS"
    assert news.content.title == "AI startup raises new funding"


def test_invalid_record_type_rejected():
    with pytest.raises(ValidationError):
        StartupRecord.model_validate({
            "schemaVersion": "1.0",
            "recordType": "INVALID",
            "source": {"name": "Example", "url": "https://example.com"},
            "content": {"entityName": "GraphOne"},
            "collectedAt": "2026-09-11T12:00:00Z",
        })


def test_source_model_validates_url():
    source = SourceInfo.model_validate({
        "name": "OpenAI",
        "url": "https://openai.com",
    })

    assert source.name == "OpenAI"
    assert str(source.url).startswith("https://")


def test_collected_at_is_iso8601_datetime():
    dt = datetime.fromisoformat("2026-09-11T12:00:00+00:00")
    assert dt.tzinfo is not None
