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

## Batch concurrency and scaling

The pipeline uses [src/batch.py](src/batch.py) as a reusable asynchronous batch boundary. `BoundedBatchProcessor` runs a fixed number of workers, applies an `asyncio.Semaphore`, and uses a bounded queue so a large iterable does not create one task per record. Results retain input order and expose deterministic counts for `total`, `succeeded`, `failed`, `skipped`, and elapsed duration.

`PipelineOrchestrator.process_batch(...)` uses this layer with `BATCH_CONCURRENCY` from the environment (default `8`), or an explicit `batch_concurrency` constructor value. A mapping with `skip=True` is counted as skipped; handler exceptions and extraction failures are isolated to that input and do not cancel the rest of the batch. The existing crawler remains responsible for reusing one `aiohttp.ClientSession` per fetch batch, its semaphore, and its retry/backoff policy. LLM chunk-level concurrency and provider fallback remain unchanged, and SQLite remains the persistence backend.

This is a local bounded-concurrency design rather than distributed infrastructure. To move toward hundreds of thousands of records later, a durable work queue and partitioned workers could feed the same batch and pipeline contracts, while source-specific crawlers could reuse long-lived sessions and bounded batches. SQLite can remain useful for local development and validation; a later storage adapter could replace it behind the existing repository contract without changing provenance, result aggregation, or failure isolation.

## Google Sheets export

The dedicated exporter in [src/integrations/google_sheets.py](src/integrations/google_sheets.py) reads persisted records only through `SQLiteRecordRepository`. It writes deterministic snapshots to `Startups`, `Products`, `Research Papers`, `Jobs`, `News`, and `Entity Mapping Log`. Each worksheet is created when needed and replaced as a complete header-plus-rows snapshot, so repeated exports do not duplicate rows and empty datasets remain valid header-only worksheets.

The exporter uses an injectable `GoogleSheetsClient` interface, so offline tests do not contact Google. Rows preserve source URLs, source names, collected dates, applicable freshness fields, and entity-resolution metadata. Rows and columns have fixed ordering, and mapping-log rows are sorted deterministically. Authentication, configuration, API, and export failures use structured exceptions without including credential contents in error messages.

Configure `GOOGLE_SHEETS_SPREADSHEET_ID` and `GOOGLE_SHEETS_CREDENTIALS` locally when a real client integration is added. The current export layer deliberately does not create a Google client or require credentials; the environment values are placeholders only.

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

## Freshness tracking and publication-date normalization

The project includes a deterministic freshness foundation under [src/freshness](src/freshness). This layer is intentionally small and reusable: it normalizes absolute and relative publication dates, evaluates age against a supplied reference time, and keeps unknown or malformed dates from being treated as fresh.

Supported absolute formats include ISO-8601 timestamps, RFC-style HTTP dates, common English month/day strings, explicit UTC values, and timestamps with timezone offsets. Supported relative expressions include `2 hours ago`, `30 minutes ago`, `15 mins ago`, `1 day ago`, and `yesterday`. All relative calculations are anchored to the explicit reference datetime supplied by the caller rather than the current wall clock, which keeps the behavior deterministic and testable.

Freshness evaluation enforces a 24-hour freshness window: a publication datetime exactly 24 hours old is still `fresh`, while anything older than that is `stale`. A publication date in the future remains `future` and is never silently treated as fresh. Missing or unparseable dates remain `unknown` and do not produce a fake publication time.

For HTML/text inputs, the extraction precedence is deterministic: JSON-LD `datePublished`, then `meta[property="article:published_time"]`, then `meta[name="date"]` / `meta[name="pubdate"]`, then `<time datetime="...">`, and finally visible text fallback. If a higher-priority source exists but is invalid, the parser falls through to the next valid source instead of inventing a date.

This freshness layer is a foundation for later News and Job ingestion work and does not claim that those workflows are complete.

## News ingestion foundation

This project includes a deterministic News ingestion adapter under [src/crawlers/news.py](src/crawlers/news.py). It uses a public structured RSS feed as the selected source for this step, rather than arbitrary HTML scraping or browser automation. The source is intentionally narrow and simple: it exposes a stable item structure with `title`, `link`, and `pubDate`, which makes it suitable for a deterministic offline test harness without requiring authentication or LLM processing.

The adapter reuses the existing asynchronous HTTP crawler and the Step 10 freshness/date-normalization package. For each article, the pipeline is:

1. fetch feed via the async crawler
2. parse the feed item structure
3. validate `title` and `source URL`
4. normalize the publication date with `parse_publication_date(...)`
5. evaluate freshness with `evaluate_freshness(...)`
6. include only records whose age is within the configured 24-hour freshness window

The default freshness rule is `age <= 24 hours => fresh`, while missing values, malformed values, future dates, and stale items are excluded rather than guessed. Unknown dates remain `unknown` and are never treated as fresh. URL deduplication is deterministic and conservative: same normalized source URL is kept once, while different URLs remain separate. Public source limitations include that the adapter intentionally supports a feed-based ingestion pattern rather than all possible News sites or arbitrary HTML pages.

## Job ingestion foundation

This project includes a conservative Job ingestion adapter under [src/crawlers/jobs.py](src/crawlers/jobs.py). The selected public structured source is a simple RSS/Atom-like public job feed format that exposes stable job metadata: `title`, `link`, `pubDate`, and optional fields such as `source`, `description`, `location`, and `employmentType`. This is intentionally narrow and deterministic: it avoids arbitrary HTML scraping, anti-bot workarounds, and any authentication requirement.

The adapter reuses the existing asynchronous HTTP crawler from [src/crawlers/http_client.py](src/crawlers/http_client.py) and the Step 10 date/freshness layer from [src/freshness](src/freshness). The pipeline is:

1. fetch job feed via the async crawler
2. parse public RSS job items
3. preserve the original source URL from the source feed
4. normalize `pubDate` using `parse_publication_date(...)`
5. evaluate freshness with `evaluate_freshness(...)`
6. keep `fresh`, `stale`, `unknown`, and `future` states distinct for downstream auditing

The default freshness window remains 24 hours. A job exactly 24 hours old remains `fresh`, while anything older than that is `stale`. Missing or malformed posting dates stay `unknown` and are not guessed. A future posting date remains `future` and is excluded from fresh results. The implementation keeps provenance honest: it never fabricates a job URL, title, company, date, or location, and it preserves `None` where the source does not provide a value.

Deduplication is deterministic and conservative: repeated source URLs are collapsed by their normalized URL, while different URLs are kept separate. The implementation is testable offline and does not claim coverage of all job boards or production-scale monitoring. It intentionally does not implement Redis, database persistence, distributed crawling, browser automation, or generalized scraping of non-public job sites.

## SQLite persistence architecture

The project now includes a deterministic local persistence layer under [src/storage](src/storage). It uses SQLite as the initial durable store and keeps the storage contract intentionally generic so a future PostgreSQL implementation can replace it without changing the `crawlers` or `extractors` interfaces.

The repository is a small data-access layer rather than a full ORM:

- schema is created explicitly with `initialize()`
- records are upserted via a source URL key
- duplicates are prevented by normalized URL uniqueness rather than application-side heuristics alone
- bulk writes run inside a single transaction and rollback on any failure
- canonical payloads are stored as JSON blobs while preserving provenance and freshness metadata in dedicated columns

Default database location:

- environment variable: `DATABASE_PATH`
- fallback: `data/pipeline.sqlite3`

This keeps the default behavior local, deterministic, and credential-free. No PostgreSQL, Redis, Docker, or secret configuration is required for this step.

The persistence design stores canonical entity rows for:

- Startup records
- Product records
- Research Paper records
- Job records
- News records

The schema keeps the following metadata for each record:

- `entity_type`
- `source_url`
- normalized `source_url_normalized`
- `source_name`
- `collected_at`
- `published_date`
- `freshness_status`
- `freshness_reason`
- full canonical record JSON payload

Deterministic deduplication is based on a normalized source URL. Re-ingesting the same record does not create duplicates; it updates the existing row instead. This is enforced both in the application layer and in the SQLite uniqueness constraint, so the persistence layer remains idempotent and safe under retries.

## LLM extraction foundation

The project now includes a small LLM extraction layer under [src/llm](src/llm). It follows a narrow contract:

### Gemini integration

This repository uses the native Gemini REST API through the existing provider abstraction in [src/llm/provider.py](src/llm/provider.py). The active fallback order is Gemini → Groq → Cerebras. The provider contract remains the same `generate(prompt)` interface used elsewhere in the pipeline.

Configuration is environment-driven:

- `GEMINI_API_KEY` required for live Gemini calls
- `GROQ_API_KEY` enables Groq fallback
- `CEREBRAS_API_KEY` enables Cerebras fallback
- `GEMINI_MODEL`, `GROQ_MODEL`, and `CEREBRAS_MODEL` override the default model names

The provider chain is intentionally isolated from the rest of the pipeline and is invoked through the same chunking and extraction code path as the other backends. Large prompts are chunked before sending them to a provider, and oversized requests are classified as `payload_too_large`/413 failures without fabricating data.

Offline tests require no external API key. Live tests are marked with the `live` marker and are skipped unless their environment variable is set and the test is invoked explicitly.

### Strict extraction policy

Gemini output is still constrained by the project’s strict rules:

- JSON only
- canonical schema only
- preserve the source URL from the original request
- do not invent missing values
- missing fields remain `null` or omitted according to the schema
- malformed outputs are rejected before persistence
- rate limits, timeouts, and transient server failures are surfaced as structured provider errors

## Gemini setup

Create a local `.env` file (which stays gitignored) containing:

```bash
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-1.5-flash
```

For the optional live test, run:

```bash
pytest -q -m live tests/test_live_gemini.py
```

The default offline suite remains safe for CI and local development without any API key present.

## Chunking and 413 protection

Large source documents are chunked before they are sent to an LLM provider. This is a conservative input-size guard designed to prevent oversized requests and provider-level 413 responses before they happen. The implementation is intentionally character-based rather than token-based because the codebase does not yet include a real tokenizer; this is a safe size-control heuristic until the tokenizer layer is introduced.

The split logic prefers natural boundaries in this order:

1. section/heading boundaries
2. paragraph breaks
3. sentence boundaries
4. whitespace boundaries
5. hard character fallback

This avoids blindly slicing every N characters when a natural break exists. Overlap is configurable via `LLM_CHUNK_OVERLAP_CHARS` to keep enough context across adjacent chunks without creating unnecessary API load. If a provider still reports a 413, the extractor returns a structured failure that includes the chunk size and overlap metadata so a later implementation can reduce the chunk size and retry cleanly.

Entity resolution is intentionally not performed during chunk merging. Large inputs are processed into validated canonical records and deduplicated only for exact duplicates; two different entities are not merged merely because their names look similar.

raw source text
      ↓
LLM provider
      ↓
JSON response
      ↓
Pydantic validation
      ↓
canonical project schema

This stack intentionally keeps one provider abstraction and one extractor layer, while validating every extracted record against the existing canonical schemas in [src/models/schemas.py](src/models/schemas.py). The current implementation supports Gemini as the first provider, and later steps will add provider fallback, chunking, and broader enrichment.

The extractor receives the source URL and raw text together, preserves the source URL on every record, and rejects malformed or hallucinated output before it becomes part of the canonical pipeline.

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

## Selected research source for Step 3

Selected source: Semantic Scholar Graph API

- Source endpoint: https://api.semanticscholar.org/graph/v1/paper/search
- Source page: https://www.semanticscholar.org/
- Why it was selected: it exposes a public, structured API with paper metadata including title, authors, publication information, paper URL, and optional source links. This makes it suitable for a deterministic, offline-testable adapter without arbitrary HTML scraping.

## Research-paper ingestion architecture

The current Step 3 architecture is intentionally small and explicit:

Semantic Scholar API
      ↓
AsyncHTTPCrawler
      ↓
ResearchPaperAdapter
      ↓
ResearchPaper Pydantic model

The adapter converts normalized API responses into the existing project schema while preserving the legitimate source URL and publication metadata.

## Fields currently extracted

For each paper record, the current adapter extracts:

- title
- authors
- paper_url
- github_url (only when legitimately present in the source response)
- github_stars (only when legitimately present in the source response)
- published_date
- record source metadata

## GitHub information limitation

This step does not perform GitHub API enrichment. If the selected source does not provide a legitimate GitHub URL, the adapter keeps:

- `github_url = None`
- `github_stars = None`

No GitHub repository or star count is invented.

## GitHub metadata enrichment

This project also includes a small GitHub integration for resolving repository metadata associated with research papers. GitHub is used as a source of `stargazers_count` because it is the canonical public API for repository-level star data and keeps the metadata current without requiring a full scrape of GitHub pages.

The integration is intentionally narrow:

- only repository URLs already present on a paper are resolved
- the REST API endpoint used is `GET https://api.github.com/repos/{owner}/{repo}`
- an optional `GITHUB_TOKEN` can be configured via environment variables to increase API headroom when available
- if no valid repository URL is present, or if the repo cannot be resolved, `github_stars` remains `None`

To configure a token locally, add the following to `.env`:

```bash
GITHUB_TOKEN=your_token_here
```

For any paper with `github_url` set, the enrichment step resolves the repository and updates `github_stars` to the latest public `stargazers_count`. If the data is unavailable or the repository is missing, `github_stars` stays `None` instead of being guessed.

## Why asynchronous crawling is being used

Many public sources are independent and can be fetched in parallel. Asynchronous I/O reduces total wall-clock time for large crawl batches while keeping the code path straightforward and testable. This makes it suitable as the foundation for future scraping workflows without committing to a full distributed architecture yet.

## Small usage example

```python
import asyncio

from src.crawlers.http_client import AsyncHTTPCrawler
from src.crawlers.research_papers import ResearchPaperAdapter


async def main() -> None:
    crawler = AsyncHTTPCrawler(timeout=10.0, max_concurrency=5)
    adapter = ResearchPaperAdapter(crawler)
    results = await adapter.fetch_and_parse("transformer model", limit=5)

    for item in results:
        print(item.content.title)
        print(item.content.authors)
        print(item.content.paper_url)


asyncio.run(main())
```

## Current implementation status

This step only establishes a deterministic research-paper ingestion foundation. It does not yet collect 1,000+ papers, does not yet enrich GitHub metadata from the GitHub API, and does not yet implement LLM extraction or other dataset types.

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
- CEREBRAS_API_KEY
- DATABASE_URL
- REDIS_URL
- GOOGLE_SHEETS_CREDENTIALS

## Running tests

To run the project test suite:

pytest

## Notes

This project is intentionally scoped to a clean, maintainable Python backend foundation. It does not implement a frontend, does not claim the 1,000-paper goal is complete yet, and does not fabricate missing research metadata.

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
- CEREBRAS_API_KEY
- DATABASE_URL
- REDIS_URL
- GOOGLE_SHEETS_CREDENTIALS

## Running tests

To run the initial test suite:

pytest

## Notes

This project is intentionally scoped to a clean, maintainable Python backend foundation. It does not implement a frontend, does not call external services yet, and does not claim that the full 500,000-record architecture is complete.
