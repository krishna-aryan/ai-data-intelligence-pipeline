from __future__ import annotations

import asyncio
import json
from urllib import error, request

from src.config.settings import load_settings

from .base import BaseLLMProvider
from .fallback import ProviderRequestError


_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class GeminiProvider(BaseLLMProvider):
    def __init__(self, *, api_key: str | None = None, model: str = "gemini-1.5-flash", api_base_url: str | None = None, timeout: int = 30) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.api_base_url = api_base_url or "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        self.provider_name = "gemini"

    def is_available(self) -> bool:
        return bool(self.api_key)

    async def generate(self, prompt: str) -> str:
        if not self.api_key:
            raise ProviderRequestError(provider_name=self.provider_name, error_type="invalid_authentication", retryable=False, message="GEMINI_API_KEY is not configured.", status_code=401)
        payload = {"contents": [{"parts": [{"text": prompt}]}]}

        def do_request() -> str:
            url = f"{self.api_base_url.format(model=self.model)}?key={self.api_key}"
            req = request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
            try:
                with request.urlopen(req, timeout=self.timeout) as response:
                    body = response.read().decode()
            except error.HTTPError as exc:
                raise _http_error(self.provider_name, exc, prompt) from exc
            except (TimeoutError, asyncio.TimeoutError) as exc:
                raise ProviderRequestError(provider_name=self.provider_name, error_type="timeout", retryable=True, message="Gemini request timed out.") from exc
            except OSError as exc:
                raise ProviderRequestError(provider_name=self.provider_name, error_type="connection_error", retryable=True, message=str(exc)) from exc
            try:
                parsed = json.loads(body)
                text = parsed["candidates"][0]["content"]["parts"][0]["text"]
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                raise ProviderRequestError(provider_name=self.provider_name, error_type="malformed_provider_response", retryable=False, message="Gemini returned an unexpected response payload.") from exc
            if not isinstance(text, str) or not text.strip():
                raise ProviderRequestError(provider_name=self.provider_name, error_type="malformed_provider_response", retryable=False, message="Gemini returned an empty text payload.")
            return text

        return await asyncio.to_thread(do_request)


class _OpenAICompatibleProvider(BaseLLMProvider):
    api_url: str
    credential_name: str

    def __init__(self, *, api_key: str | None, model: str, timeout: int, provider_name: str, api_url: str, credential_name: str) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.provider_name = provider_name
        self.api_url = api_url
        self.credential_name = credential_name

    def is_available(self) -> bool:
        return bool(self.api_key)

    async def generate(self, prompt: str) -> str:
        if not self.api_key:
            raise ProviderRequestError(provider_name=self.provider_name, error_type="invalid_authentication", retryable=False, message=f"{self.credential_name} is not configured.", status_code=401)
        payload = {"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}

        def do_request() -> str:
            req = request.Request(self.api_url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}, method="POST")
            try:
                with request.urlopen(req, timeout=self.timeout) as response:
                    body = response.read().decode()
            except error.HTTPError as exc:
                raise _http_error(self.provider_name, exc, prompt) from exc
            except (TimeoutError, asyncio.TimeoutError) as exc:
                raise ProviderRequestError(provider_name=self.provider_name, error_type="timeout", retryable=True, message=f"{self.provider_name.title()} request timed out.") from exc
            except OSError as exc:
                raise ProviderRequestError(provider_name=self.provider_name, error_type="connection_error", retryable=True, message=str(exc)) from exc
            try:
                text = json.loads(body)["choices"][0]["message"]["content"]
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                raise ProviderRequestError(provider_name=self.provider_name, error_type="malformed_provider_response", retryable=False, message=f"{self.provider_name.title()} returned an unexpected response payload.") from exc
            if not isinstance(text, str) or not text.strip():
                raise ProviderRequestError(provider_name=self.provider_name, error_type="malformed_provider_response", retryable=False, message=f"{self.provider_name.title()} returned an empty text payload.")
            return text

        return await asyncio.to_thread(do_request)


class GroqProvider(_OpenAICompatibleProvider):
    def __init__(self, *, api_key: str | None = None, model: str = "llama-3.1-8b-instant", timeout: int = 30) -> None:
        super().__init__(api_key=api_key, model=model, timeout=timeout, provider_name="groq", api_url="https://api.groq.com/openai/v1/chat/completions", credential_name="GROQ_API_KEY")


class CerebrasProvider(_OpenAICompatibleProvider):
    def __init__(self, *, api_key: str | None = None, model: str = "llama3.1-8b", timeout: int = 30) -> None:
        super().__init__(api_key=api_key, model=model, timeout=timeout, provider_name="cerebras", api_url="https://api.cerebras.ai/v1/chat/completions", credential_name="CEREBRAS_API_KEY")


def _http_error(provider_name: str, exc: error.HTTPError, prompt: str) -> ProviderRequestError:
    status = exc.code
    detail = exc.read().decode("utf-8", errors="replace")
    if status == 413:
        return ProviderRequestError(provider_name=provider_name, error_type="payload_too_large", retryable=False, message=f"{provider_name.title()} rejected the request because it was too large.", status_code=413, details={"provider": provider_name, "request_size": len(prompt)})
    if status in _RETRYABLE_STATUS_CODES:
        return ProviderRequestError(provider_name=provider_name, error_type="rate_limited" if status == 429 else "temporary_server_error", retryable=True, message=detail, status_code=status)
    return ProviderRequestError(provider_name=provider_name, error_type="unknown_provider_error", retryable=False, message=detail, status_code=status)


def build_default_providers(settings=None):
    settings = settings or load_settings()
    providers = []
    if settings.gemini_api_key:
        providers.append(GeminiProvider(api_key=settings.gemini_api_key, model=settings.gemini_model, timeout=settings.llm_timeout))
    if settings.groq_api_key:
        providers.append(GroqProvider(api_key=settings.groq_api_key, model=settings.groq_model, timeout=settings.llm_timeout))
    if settings.cerebras_api_key:
        providers.append(CerebrasProvider(api_key=settings.cerebras_api_key, model=settings.cerebras_model, timeout=settings.llm_timeout))
    return providers


__all__ = ["CerebrasProvider", "GeminiProvider", "GroqProvider", "build_default_providers"]
