import os

import pytest

from src.llm import LLMExtractor
from src.llm.provider import GeminiProvider


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_gemini_integration_smoke_test():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        pytest.skip("GEMINI_API_KEY is not configured for live integration testing.")

    provider = GeminiProvider(api_key=api_key, model="gemini-1.5-flash")
    extractor = LLMExtractor(provider, max_input_chars=5000, overlap_chars=100)

    result = await extractor.extract(
        source_url="https://example.com/graphone-live",
        raw_text=(
            "GraphOne is a startup. It has 15 employees. "
            "GraphOne launched a product called Atlas in 2026. "
            "The source states that Atlas is usage-based pricing."
        ),
        source_name="Example",
    )

    assert result.ok is True
    assert result.records
    assert str(result.records[0].source.url) == "https://example.com/graphone-live"
    assert result.records[0].recordType in {"STARTUP", "PRODUCT"}
