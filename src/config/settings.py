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
    llm_provider: str = "gemini"
    llm_model: str = "gemini-1.5-flash"
    llm_timeout: int = 30
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    deepseek_api_key: str | None = None
    github_token: str | None = None
    database_url: str | None = None
    redis_url: str | None = None
    google_sheets_credentials: str | None = None


_DEFAULTS: Final[dict[str, object]] = {
    "APP_NAME": "graphone-intelligence-pipeline",
    "ENVIRONMENT": "development",
    "LOG_LEVEL": "INFO",
    "MAX_CONCURRENCY": 8,
    "LLM_PROVIDER": "gemini",
    "LLM_MODEL": "gemini-1.5-flash",
    "LLM_TIMEOUT": 30,
}


def load_settings() -> Settings:
    load_dotenv()

    app_name = os.getenv("APP_NAME", str(_DEFAULTS["APP_NAME"]))
    environment = os.getenv("ENVIRONMENT", str(_DEFAULTS["ENVIRONMENT"]))
    log_level = os.getenv("LOG_LEVEL", str(_DEFAULTS["LOG_LEVEL"]))
    max_concurrency = int(os.getenv("MAX_CONCURRENCY", str(_DEFAULTS["MAX_CONCURRENCY"])))
    llm_provider = os.getenv("LLM_PROVIDER", str(_DEFAULTS["LLM_PROVIDER"]))
    llm_model = os.getenv("LLM_MODEL", str(_DEFAULTS["LLM_MODEL"]))
    llm_timeout = int(os.getenv("LLM_TIMEOUT", str(_DEFAULTS["LLM_TIMEOUT"])))

    return Settings(
        app_name=app_name,
        environment=environment,
        log_level=log_level,
        max_concurrency=max_concurrency,
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_timeout=llm_timeout,
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
        groq_api_key=os.getenv("GROQ_API_KEY"),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
        github_token=os.getenv("GITHUB_TOKEN"),
        database_url=os.getenv("DATABASE_URL"),
        redis_url=os.getenv("REDIS_URL"),
        google_sheets_credentials=os.getenv("GOOGLE_SHEETS_CREDENTIALS"),
    )
