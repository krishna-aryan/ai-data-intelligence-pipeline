from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from dotenv import load_dotenv
import os


@dataclass(frozen=True)
class Settings:
    app_name: str = "graphone-intelligence-pipeline"
    environment: str = "development"
    log_level: str = "INFO"
    max_concurrency: int = 8
    batch_concurrency: int = 8
    queue_concurrency: int = 8
    queue_max_retries: int = 0
    llm_provider: str = "gemini"
    llm_model: str = "gemini-1.5-flash"
    llm_timeout: int = 30
    llm_max_input_chars: int = 20000
    llm_chunk_overlap_chars: int = 400
    gemini_model: str = "gemini-1.5-flash"
    groq_model: str = "llama-3.1-8b-instant"
    cerebras_model: str = "llama3.1-8b"
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    cerebras_api_key: str | None = None
    github_token: str | None = None
    database_url: str | None = None
    database_path: str | None = None
    redis_url: str | None = None
    google_sheets_credentials: str | None = None
    google_sheets_spreadsheet_id: str | None = None
    startup_source_url: str | None = None
    product_source_url: str | None = None
    research_paper_source_url: str | None = None
    job_source_url: str | None = None
    news_source_url: str | None = None


_DEFAULTS: Final[dict[str, object]] = {
    "APP_NAME": "graphone-intelligence-pipeline",
    "ENVIRONMENT": "development",
    "LOG_LEVEL": "INFO",
    "MAX_CONCURRENCY": 8,
    "BATCH_CONCURRENCY": 8,
    "QUEUE_CONCURRENCY": 8,
    "QUEUE_MAX_RETRIES": 0,
    "LLM_PROVIDER": "gemini",
    "LLM_MODEL": "gemini-1.5-flash",
    "GEMINI_MODEL": "gemini-1.5-flash",
    "GROQ_MODEL": "llama-3.1-8b-instant",
    "CEREBRAS_MODEL": "llama3.1-8b",
    "LLM_TIMEOUT": 30,
    "LLM_MAX_INPUT_CHARS": 20000,
    "LLM_CHUNK_OVERLAP_CHARS": 400,
}


def load_settings() -> Settings:
    load_dotenv()

    app_name = os.getenv("APP_NAME", str(_DEFAULTS["APP_NAME"]))
    environment = os.getenv("ENVIRONMENT", str(_DEFAULTS["ENVIRONMENT"]))
    log_level = os.getenv("LOG_LEVEL", str(_DEFAULTS["LOG_LEVEL"]))
    max_concurrency = int(os.getenv("MAX_CONCURRENCY", str(_DEFAULTS["MAX_CONCURRENCY"])))
    batch_concurrency = int(os.getenv("BATCH_CONCURRENCY", str(_DEFAULTS["BATCH_CONCURRENCY"])))
    queue_concurrency = int(os.getenv("QUEUE_CONCURRENCY", str(_DEFAULTS["QUEUE_CONCURRENCY"])))
    queue_max_retries = int(os.getenv("QUEUE_MAX_RETRIES", str(_DEFAULTS["QUEUE_MAX_RETRIES"])))
    llm_provider = os.getenv("LLM_PROVIDER", str(_DEFAULTS["LLM_PROVIDER"]))
    llm_model = os.getenv("LLM_MODEL", str(_DEFAULTS["LLM_MODEL"]))
    gemini_model = os.getenv("GEMINI_MODEL", str(_DEFAULTS["GEMINI_MODEL"]))
    groq_model = os.getenv("GROQ_MODEL", str(_DEFAULTS["GROQ_MODEL"]))
    cerebras_model = os.getenv("CEREBRAS_MODEL", str(_DEFAULTS["CEREBRAS_MODEL"]))
    llm_timeout = int(os.getenv("LLM_TIMEOUT", str(_DEFAULTS["LLM_TIMEOUT"])))
    llm_max_input_chars = int(os.getenv("LLM_MAX_INPUT_CHARS", str(_DEFAULTS["LLM_MAX_INPUT_CHARS"])))
    llm_chunk_overlap_chars = int(
        os.getenv("LLM_CHUNK_OVERLAP_CHARS", str(_DEFAULTS["LLM_CHUNK_OVERLAP_CHARS"]))
    )

    return Settings(
        app_name=app_name,
        environment=environment,
        log_level=log_level,
        max_concurrency=max_concurrency,
        batch_concurrency=batch_concurrency,
        queue_concurrency=queue_concurrency,
        queue_max_retries=queue_max_retries,
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_timeout=llm_timeout,
        llm_max_input_chars=llm_max_input_chars,
        llm_chunk_overlap_chars=llm_chunk_overlap_chars,
        gemini_model=gemini_model,
        groq_model=groq_model,
        cerebras_model=cerebras_model,
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        groq_api_key=os.getenv("GROQ_API_KEY"),
        cerebras_api_key=os.getenv("CEREBRAS_API_KEY"),
        github_token=os.getenv("GITHUB_TOKEN"),
        database_url=os.getenv("DATABASE_URL"),
        database_path=os.getenv("DATABASE_PATH") or os.getenv("DATABASE_URL"),
        redis_url=os.getenv("REDIS_URL"),
        google_sheets_credentials=os.getenv("GOOGLE_SHEETS_CREDENTIALS"),
        google_sheets_spreadsheet_id=os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID"),
        startup_source_url=os.getenv("STARTUP_SOURCE_URL"),
        product_source_url=os.getenv("PRODUCT_SOURCE_URL"),
        research_paper_source_url=os.getenv("RESEARCH_PAPER_SOURCE_URL"),
        job_source_url=os.getenv("JOB_SOURCE_URL"),
        news_source_url=os.getenv("NEWS_SOURCE_URL"),
    )
