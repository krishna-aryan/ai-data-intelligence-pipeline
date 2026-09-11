import io
import json
from urllib.error import HTTPError

import pytest

from src.llm import LLMExtractor
from src.llm.provider import GeminiProvider
from src.llm.fallback import ProviderRequestError


class FakeGeminiHTTPResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


@pytest.mark.asyncio
async def test_gemini_provider_missing_api_key_raises_structured_error():
    provider = GeminiProvider(api_key=None, model="gemini-1.5-flash")

    with pytest.raises(ProviderRequestError) as exc:
        await provider.generate("hello")

    assert exc.value.error_type == "invalid_authentication"
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_gemini_provider_malformed_response_is_classified():
    provider = GeminiProvider(api_key="fake-key", model="gemini-1.5-flash")

    def fake_urlopen(req, timeout):
        return FakeGeminiHTTPResponse({"unexpected": "shape"})

    import src.llm.provider as provider_module

    original = provider_module.request.urlopen
    provider_module.request.urlopen = fake_urlopen
    try:
        with pytest.raises(ProviderRequestError) as exc:
            await provider.generate("hello")
    finally:
        provider_module.request.urlopen = original

    assert exc.value.error_type == "malformed_provider_response"


@pytest.mark.asyncio
async def test_gemini_provider_classifies_rate_limit_and_server_error():
    provider = GeminiProvider(api_key="fake-key", model="gemini-1.5-flash")
    import src.llm.provider as provider_module

    original = provider_module.request.urlopen

    def make_http_error(code, body):
        return HTTPError(
            url="https://example.test",
            hdrs=None,
            code=code,
            msg="error",
            fp=io.BytesIO(json.dumps({"error": body}).encode("utf-8")),
        )

    provider_module.request.urlopen = lambda req, timeout: (_ for _ in ()).throw(make_http_error(429, "rate limited"))
    try:
        with pytest.raises(ProviderRequestError) as exc:
            await provider.generate("hello")
    finally:
        provider_module.request.urlopen = original

    assert exc.value.error_type == "rate_limited"
    assert exc.value.retryable is True

    provider_module.request.urlopen = lambda req, timeout: (_ for _ in ()).throw(make_http_error(503, "server"))
    try:
        with pytest.raises(ProviderRequestError) as exc2:
            await provider.generate("hello")
    finally:
        provider_module.request.urlopen = original

    assert exc2.value.error_type == "temporary_server_error"
    assert exc2.value.retryable is True


@pytest.mark.asyncio
async def test_gemini_fallback_with_extractor_preserves_provenance():
    class FakeFallbackProvider:
        def __init__(self, response):
            self.response = response
            self.provider_name = "gemini"

        async def generate(self, prompt: str) -> str:
            return self.response

    provider = FakeFallbackProvider(json.dumps({
        "records": [{
            "recordType": "STARTUP",
            "schemaVersion": "1.0",
            "source": {"name": "Example", "url": "https://example.com/startup"},
            "content": {"entityName": "GraphOne", "employeeCount": 15},
            "collectedAt": "2026-09-11T12:00:00Z",
        }]
    }))
    extractor = LLMExtractor(provider)

    result = await extractor.extract(source_url="https://example.com/startup", raw_text="GraphOne has 15 employees.")

    assert result.ok is True
    assert str(result.records[0].source.url) == "https://example.com/startup"
    assert result.records[0].content.entityName == "GraphOne"
    assert result.records[0].content.employeeCount == 15


@pytest.mark.asyncio
async def test_gemini_chunking_stays_with_existing_extractor_contract():
    payload = {
        "records": [
            {
                "recordType": "PRODUCT",
                "schemaVersion": "1.0",
                "source": {"name": "Example", "url": "https://example.com/product"},
                "content": {"startupName": "GraphOne", "pricingModel": "usage_based"},
                "collectedAt": "2026-09-11T12:00:00Z",
            }
        ]
    }

    class ChunkedProvider:
        def __init__(self):
            self.calls = []

        async def generate(self, prompt: str) -> str:
            self.calls.append(prompt)
            return json.dumps(payload)

    provider = ChunkedProvider()
    extractor = LLMExtractor(provider, max_input_chars=20, overlap_chars=2)
    result = await extractor.extract(source_url="https://example.com/product", raw_text="GraphOne product details. " * 10)

    assert result.ok is True
    assert len(provider.calls) >= 1
    assert str(result.records[0].source.url) == "https://example.com/product"
    assert result.records[0].content.startupName == "GraphOne"


@pytest.mark.asyncio
async def test_gemini_extractor_rejects_schema_mismatch_without_fabrication():
    class Provider:
        async def generate(self, prompt: str) -> str:
            return json.dumps({
                "records": [{
                    "recordType": "NEWS",
                    "schemaVersion": "1.0",
                    "source": {"name": "Example", "url": "https://example.com/news"},
                    "content": {"summary": "Only a summary without title"},
                    "collectedAt": "2026-09-11T12:00:00Z",
                }]
            })

    extractor = LLMExtractor(Provider())
    result = await extractor.extract(source_url="https://example.com/news", raw_text="A story.")

    assert result.ok is False
    assert result.error_type == "schema_validation_failure"
