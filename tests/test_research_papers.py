import pytest
from pydantic import ValidationError

from src.crawlers.research_papers import ResearchPaperAdapter
from src.models.schemas import ResearchPaperRecord


@pytest.fixture
def semantic_scholar_payload():
    return {
        "data": [
            {
                "title": "Attention Is All You Need",
                "authors": [
                    {"name": "Ashish Vaswani"},
                    {"name": "Noam Shazeer"},
                    {"name": "Niki Parmar"},
                ],
                "paper_url": "https://arxiv.org/abs/1706.03762",
                "url": "https://arxiv.org/abs/1706.03762",
                "openAccessPdf": {"url": "https://arxiv.org/pdf/1706.03762.pdf"},
                "publicationDate": "2017-06-12",
                "githubUrl": "https://github.com/tensorflow/tensor2tensor",
                "github_stars": 42000,
            }
        ]
    }


@pytest.fixture
def multiple_papers_payload():
    return {
        "data": [
            {
                "title": "A Survey on Large Language Models",
                "authors": [{"name": "A"}, {"name": "B"}],
                "publicationDate": "2023-11-14",
                "url": "https://example.com/paper-1",
                "openAccessPdf": {"url": "https://example.com/paper-1.pdf"},
            },
            {
                "title": "Efficient Transformers",
                "authors": [{"name": "C"}, {"name": "D"}],
                "publicationDate": "2024-02-01",
                "url": "https://example.com/paper-2",
                "openAccessPdf": {"url": "https://example.com/paper-2.pdf"},
            },
        ]
    }


def test_successful_parsing_of_research_paper(semantic_scholar_payload):
    adapter = ResearchPaperAdapter()

    records = adapter.parse_response(semantic_scholar_payload)

    assert len(records) == 1
    record = records[0]
    assert record.recordType == "RESEARCH_PAPER"
    assert record.content.title == "Attention Is All You Need"
    assert record.content.authors == ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"]
    assert str(record.content.paper_url).startswith("https://")
    assert str(record.content.github_url) == "https://github.com/tensorflow/tensor2tensor"
    assert record.content.github_stars == 42000


def test_multiple_authors_are_kept(semantic_scholar_payload):
    adapter = ResearchPaperAdapter()

    record = adapter.parse_response(semantic_scholar_payload)[0]

    assert len(record.content.authors) == 3
    assert record.content.authors[0] == "Ashish Vaswani"
    assert record.content.authors[-1] == "Niki Parmar"


def test_multiple_papers_are_parsed(multiple_papers_payload):
    adapter = ResearchPaperAdapter()

    records = adapter.parse_response(multiple_papers_payload)

    assert len(records) == 2
    assert records[0].content.title == "A Survey on Large Language Models"
    assert records[1].content.title == "Efficient Transformers"


def test_missing_github_information_is_none():
    adapter = ResearchPaperAdapter()
    payload = {
        "data": [{
            "title": "A minimal paper",
            "authors": [{"name": "Jane Doe"}],
            "publicationDate": "2024-08-15",
            "url": "https://example.com/minimal-paper",
            "openAccessPdf": {"url": "https://example.com/minimal-paper.pdf"},
        }]
    }

    record = adapter.parse_response(payload)[0]

    assert record.content.github_url is None
    assert record.content.github_stars is None


def test_valid_github_url_when_present():
    adapter = ResearchPaperAdapter()
    payload = {
        "data": [{
            "title": "Repo-backed paper",
            "authors": [{"name": "John Smith"}],
            "publicationDate": "2024-01-01",
            "url": "https://example.com/repo-paper",
            "openAccessPdf": {"url": "https://example.com/repo-paper.pdf"},
            "githubUrl": "https://github.com/example/project",
            "github_stars": 77,
        }]
    }

    record = adapter.parse_response(payload)[0]

    assert str(record.content.github_url) == "https://github.com/example/project"
    assert record.content.github_stars == 77


def test_publication_date_is_normalized():
    adapter = ResearchPaperAdapter()
    payload = {
        "data": [{
            "title": "A date-normalized paper",
            "authors": [{"name": "Jane Doe"}],
            "publicationDate": "2023-12-05",
            "url": "https://example.com/date-paper",
            "openAccessPdf": {"url": "https://example.com/date-paper.pdf"},
        }]
    }

    record = adapter.parse_response(payload)[0]

    assert record.content.published_date is not None
    assert str(record.content.published_date).startswith("2023-12-05")


def test_malformed_incomplete_source_data_raises_value_error():
    adapter = ResearchPaperAdapter()
    payload = {
        "data": [{
            "title": "",
            "authors": [],
        }]
    }

    with pytest.raises(ValueError):
        adapter.parse_response(payload)


def test_pydantic_validation_failure_for_invalid_records():
    with pytest.raises(ValidationError):
        ResearchPaperRecord.model_validate({
            "schemaVersion": "1.0",
            "recordType": "RESEARCH_PAPER",
            "content": {
                "title": "bad paper",
                "authors": [],
                "paper_url": "not-a-url",
            },
            "collectedAt": "2026-09-11T12:00:00Z",
        })


def test_integration_mocked_source_response_to_record():
    adapter = ResearchPaperAdapter()
    payload = {
        "data": [{
            "title": "Transformers for language understanding",
            "authors": [{"name": "Alice"}, {"name": "Bob"}],
            "publicationDate": "2025-05-18",
            "url": "https://example.com/transformers",
            "openAccessPdf": {"url": "https://example.com/transformers.pdf"},
        }]
    }

    records = adapter.parse_response(payload)

    assert len(records) == 1
    record = records[0]
    assert isinstance(record, ResearchPaperRecord)
    assert record.content.title == "Transformers for language understanding"
    assert record.content.authors == ["Alice", "Bob"]
    assert record.content.published_date is not None
