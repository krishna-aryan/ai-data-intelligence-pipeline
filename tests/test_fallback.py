import json

import pytest

from src.llm.fallback import (
    FallbackOrchestrator,
    ProviderFallbackError,
    ProviderRequestError,
)


class FakeProvider:
    def __init__(self, name, *, response=None, error=None, available=True):
        self.name = name
        self.response = response
        self.error = error
        self._available = available
        self.calls = []

    @property
    def provider_name(self):
        return self.name

    def is_available(self):
        return self._available

    async def generate(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self._available:
            raise ProviderRequestError(
                provider_name=self.name,
                error_type="invalid_authentication",
                retryable=False,
                message="API key is missing.",
                status_code=401,
            )
        if self.error is not None:
            raise self.error
        return self.response


class GemRetryableError(ProviderRequestError):
    def __init__(self, error_type: str = "rate_limited"):
        super().__init__(
            provider_name="gemini",
            error_type=error_type,
            retryable=True,
            message="temporary failure",
            status_code=429 if error_type == "rate_limited" else 503,
        )


@pytest.mark.asyncio
async def test_gemini_succeeds_without_fallback_call():
    gemini = FakeProvider("gemini", response='{"ok": true}')
    groq = FakeProvider("groq", response='{"ok": false}')
    cerebras = FakeProvider("cerebras", response='{"ok": false}')
    orchestrator = FallbackOrchestrator([gemini, groq, cerebras])

    result = await orchestrator.generate("hello")

    assert result == '{"ok": true}'
    assert len(gemini.calls) == 1
    assert len(groq.calls) == 0
    assert len(cerebras.calls) == 0


@pytest.mark.asyncio
async def test_gemini_429_falls_back_to_groq():
    gemini = FakeProvider("gemini", error=GemRetryableError("rate_limited"))
    groq = FakeProvider("groq", response='{"ok": true}')
    cerebras = FakeProvider("cerebras", response='{"ok": false}')
    orchestrator = FallbackOrchestrator([gemini, groq, cerebras])

    result = await orchestrator.generate("hello")

    assert result == '{"ok": true}'
    assert len(gemini.calls) == 1
    assert len(groq.calls) == 1
    assert len(cerebras.calls) == 0


@pytest.mark.asyncio
async def test_gemini_5xx_falls_back_to_groq():
    gemini = FakeProvider("gemini", error=GemRetryableError("temporary_server_error"))
    groq = FakeProvider("groq", response='{"ok": true}')
    orchestrator = FallbackOrchestrator([gemini, groq])

    result = await orchestrator.generate("hello")

    assert result == '{"ok": true}'
    assert len(gemini.calls) == 1
    assert len(groq.calls) == 1


@pytest.mark.asyncio
async def test_gemini_timeout_falls_back_to_groq():
    gemini = FakeProvider("gemini", error=TimeoutError("timed out"))
    groq = FakeProvider("groq", response='{"ok": true}')
    orchestrator = FallbackOrchestrator([gemini, groq])

    result = await orchestrator.generate("hello")

    assert result == '{"ok": true}'
    assert len(gemini.calls) == 1
    assert len(groq.calls) == 1


@pytest.mark.asyncio
async def test_gemini_connection_failure_falls_back_to_groq():
    gemini = FakeProvider("gemini", error=ConnectionError("connection refused"))
    groq = FakeProvider("groq", response='{"ok": true}')
    orchestrator = FallbackOrchestrator([gemini, groq])

    result = await orchestrator.generate("hello")

    assert result == '{"ok": true}'
    assert len(gemini.calls) == 1
    assert len(groq.calls) == 1


@pytest.mark.asyncio
async def test_invalid_authentication_is_not_retried():
    gemini = FakeProvider("gemini", error=ProviderRequestError(
        provider_name="gemini",
        error_type="invalid_authentication",
        retryable=False,
        message="API key is invalid.",
        status_code=401,
    ))
    groq = FakeProvider("groq", response='{"ok": true}')
    orchestrator = FallbackOrchestrator([gemini, groq])

    with pytest.raises(ProviderFallbackError) as excinfo:
        await orchestrator.generate("hello")

    err = excinfo.value
    assert err.final_status == "non_retryable_error"
    assert err.provider_failures[0].error_type == "invalid_authentication"
    assert len(groq.calls) == 0


@pytest.mark.asyncio
async def test_groq_success_after_gemini_failure():
    gemini = FakeProvider("gemini", error=ProviderRequestError(
        provider_name="gemini", error_type="temporary_server_error", retryable=True,
        message="provider down", status_code=503,
    ))
    groq = FakeProvider("groq", response='{"ok": true}')
    orchestrator = FallbackOrchestrator([gemini, groq])

    result = await orchestrator.generate("hello")

    assert result == '{"ok": true}'
    assert orchestrator.last_provider_used == "groq"


@pytest.mark.asyncio
async def test_cerebras_used_after_gemini_and_groq_fail():
    gemini = FakeProvider("gemini", error=ProviderRequestError(
        provider_name="gemini", error_type="temporary_server_error", retryable=True,
        message="provider down", status_code=503,
    ))
    groq = FakeProvider("groq", error=ProviderRequestError(
        provider_name="groq", error_type="connection_error", retryable=True,
        message="groq down",
    ))
    cerebras = FakeProvider("cerebras", response='{"ok": true}')
    orchestrator = FallbackOrchestrator([gemini, groq, cerebras])

    result = await orchestrator.generate("hello")

    assert result == '{"ok": true}'
    assert orchestrator.last_provider_used == "cerebras"


@pytest.mark.asyncio
async def test_all_providers_fail_returns_structured_failure():
    gemini = FakeProvider("gemini", error=ProviderRequestError(
        provider_name="gemini", error_type="temporary_server_error", retryable=True,
        message="gemini down", status_code=503,
    ))
    groq = FakeProvider("groq", error=ProviderRequestError(
        provider_name="groq", error_type="connection_error", retryable=True,
        message="groq down",
    ))
    cerebras = FakeProvider("cerebras", error=ProviderRequestError(
        provider_name="cerebras", error_type="timeout", retryable=True,
        message="cerebras down",
    ))
    orchestrator = FallbackOrchestrator([gemini, groq, cerebras])

    with pytest.raises(ProviderFallbackError) as excinfo:
        await orchestrator.generate("hello")

    err = excinfo.value
    assert err.final_status == "all_providers_failed"
    assert err.providers_attempted == ["gemini", "groq", "cerebras"]
    assert len(err.provider_failures) == 3
    assert err.provider_failures[0].provider_name == "gemini"


@pytest.mark.asyncio
async def test_unexpected_exception_does_not_fall_back():
    gemini = FakeProvider("gemini", error=RuntimeError("programming error"))
    groq = FakeProvider("groq", response='{"ok": true}')
    orchestrator = FallbackOrchestrator([gemini, groq])

    with pytest.raises(ProviderFallbackError) as excinfo:
        await orchestrator.generate("hello")

    assert excinfo.value.final_status == "non_retryable_error"
    assert excinfo.value.provider_failures[0].error_type == "unknown_provider_error"
    assert len(groq.calls) == 0


@pytest.mark.asyncio
async def test_provider_order_is_deterministic():
    providers = [FakeProvider("cerebras", response='{"ok": true}'), FakeProvider("gemini", response='{"ok": true}')]
    orchestrator = FallbackOrchestrator(providers)

    result = await orchestrator.generate("hello")

    assert result == '{"ok": true}'
    assert orchestrator.providers[0].name == "cerebras"
    assert orchestrator.providers[1].name == "gemini"


@pytest.mark.asyncio
async def test_missing_provider_api_key_is_handled_safely():
    gemini = FakeProvider("gemini", available=False)
    groq = FakeProvider("groq", response='{"ok": true}')
    orchestrator = FallbackOrchestrator([gemini, groq])

    result = await orchestrator.generate("hello")

    assert result == '{"ok": true}'
    assert len(gemini.calls) == 1
    assert len(groq.calls) == 1


@pytest.mark.asyncio
async def test_provider_usage_metadata_is_correct():
    gemini = FakeProvider("gemini", error=GemRetryableError("rate_limited"))
    groq = FakeProvider("groq", response='{"ok": true}')
    orchestrator = FallbackOrchestrator([gemini, groq])

    result = await orchestrator.generate("hello")

    assert result == '{"ok": true}'
    assert orchestrator.last_provider_used == "groq"
    assert orchestrator.last_metadata["fallback_occurred"] is True
    assert orchestrator.last_metadata["providers_attempted"] == ["gemini", "groq"]


@pytest.mark.asyncio
async def test_multi_chunk_extraction_can_use_different_providers_per_chunk():
    class ChunkSpecificProvider:
        def __init__(self, name, chunk_to_response):
            self.name = name
            self.chunk_to_response = chunk_to_response
            self.calls = []

        async def generate(self, prompt: str) -> str:
            self.calls.append(prompt)
            for chunk_name, response in self.chunk_to_response.items():
                if chunk_name in prompt:
                    return response
            raise RuntimeError("unexpected chunk")

    chunk_1 = ChunkSpecificProvider("gemini", {"chunk-1": '{"records": [{"recordType": "STARTUP", "schemaVersion": "1.0", "source": {"name": "Source", "url": "https://example.com/a"}, "content": {"entityName": "Alpha"}, "collectedAt": "2026-09-11T12:00:00Z"}]}'} )
    chunk_2 = ChunkSpecificProvider("groq", {"chunk-2": '{"records": [{"recordType": "STARTUP", "schemaVersion": "1.0", "source": {"name": "Source", "url": "https://example.com/b"}, "content": {"entityName": "Beta"}, "collectedAt": "2026-09-11T12:00:00Z"}]}'} )

    orchestrator_1 = FallbackOrchestrator([chunk_1])
    orchestrator_2 = FallbackOrchestrator([chunk_2])

    result_a = await orchestrator_1.generate("chunk-1")
    result_b = await orchestrator_2.generate("chunk-2")

    assert 'Alpha' in result_a
    assert 'Beta' in result_b
    assert chunk_1.calls == ["chunk-1"]
    assert chunk_2.calls == ["chunk-2"]


@pytest.mark.asyncio
async def test_extractor_keeps_existing_json_parsing_and_validation():
    class ProviderStub:
        async def generate(self, prompt: str) -> str:
            return json.dumps({
                "records": [
                    {
                        "recordType": "STARTUP",
                        "schemaVersion": "1.0",
                        "source": {"name": "Example", "url": "https://example.com/startup"},
                        "content": {"entityName": "GraphOne", "employeeCount": 25},
                        "collectedAt": "2026-09-11T12:00:00Z",
                    }
                ]
            })

    orchestrator = FallbackOrchestrator([ProviderStub()])
    from src.llm import LLMExtractor

    extractor = LLMExtractor(orchestrator)
    result = await extractor.extract(source_url="https://example.com/startup", raw_text="GraphOne has 25 employees.")

    assert result.ok is True
    assert result.records[0].content.entityName == "GraphOne"
