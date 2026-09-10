# GraphOne / FrontierAtlas Intelligence Pipeline

GraphOne / FrontierAtlas Intelligence Pipeline is a production-oriented Python backend focused on collecting, normalizing, and structuring data about startups, AI products, research papers, jobs, and news. The project is designed as an incremental AI data pipeline that will eventually support asynchronous crawling, extraction, LLM-based normalization, freshness enforcement, entity resolution, persistence, and export to Google Sheets.

## Problem it solves

AI research, startup activity, product launches, hiring signals, and news coverage are fragmented across public websites and APIs. This project provides a clean, extensible pipeline to ingest raw public information, normalize it into structured records, and maintain a usable data foundation for downstream analysis and operational workflows.

## High-level architecture

The project is intentionally layered to keep responsibilities separated:

- Crawlers: gather raw content from public sources asynchronously
- Extractors: transform HTML or API payloads into intermediate text and structured snippets
- LLM layer: convert raw content into normalized structured data with fault handling for rate limits and payload size issues
- Entity resolution: reconcile messy names and duplicates across records
- Freshness module: enforce refresh windows for jobs and news
- Storage: persist normalized records in a durable format
- Models: validate data contracts using Pydantic
- Config: load environment variables and runtime settings

## Current implementation status

This is an incremental implementation. The project now includes a reusable asynchronous crawling foundation, but it does not yet crawl production sources at scale, call LLM providers, resolve entities, or export to Google Sheets.

Implemented so far:

- Python project structure with modular src layout
- Environment-based configuration system
- Pydantic data models for the required record types
- Reusable async HTTP crawler foundation
- Local test coverage for success, HTTP failures, request exceptions, concurrency, and session cleanup
- README and project metadata scaffolding

Planned modules and future work:

- src/crawlers/
- src/extractors/
- src/llm/
- src/entity_resolution/
- src/freshness/
- src/storage/
- src/models/
- src/utils/
- asynchronous crawling and batching
- LLM retry and backoff handling
- chunking for oversized payloads
- deduplication and entity normalization
- date normalization and freshness rules
- export to Google Sheets

## Async crawler foundation

The crawler in [src/crawlers](src/crawlers) provides a reusable asynchronous HTTP layer for fetching multiple URLs with a shared `aiohttp.ClientSession`. It supports:

- concurrent GET requests
- configurable per-request timeout
- configurable concurrency limit
- default user-agent and HTTP headers
- HTTP status handling
- request/connection exception capture
- session creation and cleanup inside the crawler lifecycle

This is intentionally separated from the later LLM, storage, and entity-resolution stages so the fetch layer remains reusable and testable.

## Why asynchronous crawling is being used

Many public sources are independent and can be fetched in parallel. Asynchronous I/O reduces total wall-clock time for large crawl batches while keeping the code path straightforward and testable. This makes it suitable as the foundation for future scraping workflows without committing to a full distributed architecture yet.

## Small usage example

```python
import asyncio

from src.crawlers.http_client import AsyncHTTPCrawler


async def main() -> None:
    crawler = AsyncHTTPCrawler(timeout=10.0, max_concurrency=5)
    results = await crawler.fetch_many([
        "https://example.com",
        "https://example.org",
    ])

    for item in results:
        print(item.requested_url, item.status, item.success, item.error)


asyncio.run(main())
```

## Local setup

1. Create a virtual environment:
   python -m venv .venv
   .venv\Scripts\activate

2. Install dependencies:
   pip install -r requirements.txt

3. Copy the example environment file:
   copy .env.example .env

4. Update the environment variables in .env as needed.

## Environment variables

The project expects environment variables for runtime and future integrations. Example placeholders are included in [.env.example](.env.example).

Required for foundation:

- APP_NAME
- ENVIRONMENT
- LOG_LEVEL
- MAX_CONCURRENCY

Planned future variables:

- GEMINI_API_KEY
- GROQ_API_KEY
- DEEPSEEK_API_KEY
- DATABASE_URL
- REDIS_URL
- GOOGLE_SHEETS_CREDENTIALS

## Running tests

To run the initial test suite:

pytest

## Notes

This project is intentionally scoped to a clean, maintainable Python backend foundation. It does not implement a frontend, does not call external services yet, and does not claim that the full 500,000-record architecture is complete.
