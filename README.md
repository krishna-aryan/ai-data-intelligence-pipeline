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

This is an incremental implementation. At this stage, the project establishes the foundation and architecture only. It does not yet crawl live sources, call LLM providers, or claim support for large-scale production ingestion.

Implemented so far:

- Python project structure with modular src layout
- Environment-based configuration system
- Pydantic data models for the required record types
- Initial test coverage for configuration and model validation
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
