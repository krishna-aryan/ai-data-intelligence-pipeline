from __future__ import annotations

import asyncio
import json
from urllib import error, request

from src.config.settings import load_settings

from .base import BaseLLMProvider
from .fallback import ProviderRequestError


class GeminiProvider(BaseLLMProvider):
    def __init__(self, *, api_key: str | None = None, model: str = "gemini-1.5-flash", timeout: int = 30):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.provider_name = "gemini"

    async def generate(self, prompt: str) -> str:
        if not self.api_key:
            raise ProviderRequestError(
                provider_name=self.provider_name,
                error_type="invalid_authentication",
                retryable=False,
                message="GEMINI_API_KEY is not configured.",
                status_code=401,
            )

        payload = {"contents": [{"parts": [{"text": prompt}]}]}

        def _request() -> str:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
            data = json.dumps(payload).encode("utf-8")
            req = request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
            try:
                with request.urlopen(req, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8")
            except error.HTTPError as exc:
                parsed = exc.read().decode("utf-8", errors="replace")
                status = exc.code
                if status == 413:
                    raise ProviderRequestError(
                        provider_name=self.provider_name,
                        error_type="payload_too_large",
                        retryable=False,
                        message="Gemini rejected the request because it was too large.",
                        status_code=413,
                        details={"provider": "gemini", "request_size": len(prompt)},
                    ) from exc
                if status in {429, 500, 502, 503, 504}:
                    raise ProviderRequestError(
                        provider_name=self.provider_name,
                        error_type="rate_limited" if status == 429 else "temporary_server_error",
                        retryable=True,
                        message=parsed,
                        status_code=status,
                    ) from exc
                raise ProviderRequestError(
                    provider_name=self.provider_name,
                    error_type="unknown_provider_error",
                    retryable=False,
                    message=parsed,
                    status_code=status,
                ) from exc
            except (TimeoutError, asyncio.TimeoutError):
                raise ProviderRequestError(
                    provider_name=self.provider_name,
                    error_type="timeout",
                    retryable=True,
                    message="Gemini request timed out.",
                ) from None
            except OSError as exc:
                raise ProviderRequestError(
                    provider_name=self.provider_name,
                    error_type="connection_error",
                    retryable=True,
                    message=str(exc),
                ) from exc

            try:
                parsed = json.loads(body)
            except json.JSONDecodeError as exc:
                raise ProviderRequestError(
                    provider_name=self.provider_name,
                    error_type="malformed_provider_response",
                    retryable=False,
                    message=f"Gemini returned malformed JSON: {exc}",
                ) from exc

            candidates = parsed.get("candidates") or []
            if not candidates:
                raise ProviderRequestError(
                    provider_name=self.provider_name,
                    error_type="malformed_provider_response",
                    retryable=False,
                    message="Gemini returned no candidates.",
                )
            parts = candidates[0].get("content", {}).get("parts") or []
            if not parts:
                raise ProviderRequestError(
                    provider_name=self.provider_name,
                    error_type="malformed_provider_response",
                    retryable=False,
                    message="Gemini returned empty content parts.",
                )
            text = parts[0].get("text", "")
            if not isinstance(text, str) or not text.strip():
                raise ProviderRequestError(
                    provider_name=self.provider_name,
                    error_type="malformed_provider_response",
                    retryable=False,
                    message="Gemini returned an empty text payload.",
                )
            return text

        return await asyncio.to_thread(_request)


class GroqProvider(BaseLLMProvider):
    def __init__(self, *, api_key: str | None = None, model: str = "llama-3.1-8b-instant", timeout: int = 30):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.provider_name = "groq"

    async def generate(self, prompt: str) -> str:
        if not self.api_key:
            raise ProviderRequestError(
                provider_name=self.provider_name,
                error_type="invalid_authentication",
                retryable=False,
                message="GROQ_API_KEY is not configured.",
                status_code=401,
            )

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }

        def _request() -> str:
            url = "https://api.groq.com/openai/v1/chat/completions"
            data = json.dumps(payload).encode("utf-8")
            req = request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            try:
                with request.urlopen(req, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8")
            except error.HTTPError as exc:
                status = exc.code
                detail = exc.read().decode("utf-8", errors="replace")
                if status == 413:
                    raise ProviderRequestError(
                        provider_name=self.provider_name,
                        error_type="payload_too_large",
                        retryable=False,
                        message="Groq rejected the request because it was too large.",
                        status_code=413,
                        details={"provider": "groq", "request_size": len(prompt)},
                    ) from exc
                if status in {429, 500, 502, 503, 504}:
                    raise ProviderRequestError(
                        provider_name=self.provider_name,
                        error_type="rate_limited" if status == 429 else "temporary_server_error",
                        retryable=True,
                        message=detail,
                        status_code=status,
                    ) from exc
                raise ProviderRequestError(
                    provider_name=self.provider_name,
                    error_type="unknown_provider_error",
                    retryable=False,
                    message=detail,
                    status_code=status,
                ) from exc
            except (TimeoutError, asyncio.TimeoutError):
                raise ProviderRequestError(
                    provider_name=self.provider_name,
                    error_type="timeout",
                    retryable=True,
                    message="Groq request timed out.",
                ) from None
            except OSError as exc:
                raise ProviderRequestError(
                    provider_name=self.provider_name,
                    error_type="connection_error",
                    retryable=True,
                    message=str(exc),
                ) from exc

            try:
                parsed = json.loads(body)
            except json.JSONDecodeError as exc:
                raise ProviderRequestError(
                    provider_name=self.provider_name,
                    error_type="malformed_provider_response",
                    retryable=False,
                    message=f"Groq returned malformed JSON: {exc}",
                ) from exc

            try:
                choices = parsed["choices"]
                text = choices[0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                raise ProviderRequestError(
                    provider_name=self.provider_name,
                    error_type="malformed_provider_response",
                    retryable=False,
                    message="Groq returned an unexpected response payload.",
                )
            if not isinstance(text, str) or not text.strip():
                raise ProviderRequestError(
                    provider_name=self.provider_name,
                    error_type="malformed_provider_response",
                    retryable=False,
                    message="Groq returned an empty text payload.",
                )
            return text

        return await asyncio.to_thread(_request)


class DeepSeekProvider(BaseLLMProvider):
    def __init__(self, *, api_key: str | None = None, model: str = "deepseek-chat", timeout: int = 30):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.provider_name = "deepseek"

    async def generate(self, prompt: str) -> str:
        if not self.api_key:
            raise ProviderRequestError(
                provider_name=self.provider_name,
                error_type="invalid_authentication",
                retryable=False,
                message="DEEPSEEK_API_KEY is not configured.",
                status_code=401,
            )

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }

        def _request() -> str:
            url = "https://api.deepseek.com/v1/chat/completions"
            data = json.dumps(payload).encode("utf-8")
            req = request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                },
                method="POST",
            )
            try:
                with request.urlopen(req, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8")
            except error.HTTPError as exc:
                status = exc.code
                detail = exc.read().decode("utf-8", errors="replace")
                if status == 413:
                    raise ProviderRequestError(
                        provider_name=self.provider_name,
                        error_type="payload_too_large",
                        retryable=False,
                        message="DeepSeek rejected the request because it was too large.",
                        status_code=413,
                        details={"provider": "deepseek", "request_size": len(prompt)},
                    ) from exc
                if status in {429, 500, 502, 503, 504}:
                    raise ProviderRequestError(
                        provider_name=self.provider_name,
                        error_type="rate_limited" if status == 429 else "temporary_server_error",
                        retryable=True,
                        message=detail,
                        status_code=status,
                    ) from exc
                raise ProviderRequestError(
                    provider_name=self.provider_name,
                    error_type="unknown_provider_error",
                    retryable=False,
                    message=detail,
                    status_code=status,
                ) from exc
            except (TimeoutError, asyncio.TimeoutError):
                raise ProviderRequestError(
                    provider_name=self.provider_name,
                    error_type="timeout",
                    retryable=True,
                    message="DeepSeek request timed out.",
                ) from None
            except OSError as exc:
                raise ProviderRequestError(
                    provider_name=self.provider_name,
                    error_type="connection_error",
                    retryable=True,
                    message=str(exc),
                ) from exc

            try:
                parsed = json.loads(body)
            except json.JSONDecodeError as exc:
                raise ProviderRequestError(
                    provider_name=self.provider_name,
                    error_type="malformed_provider_response",
                    retryable=False,
                    message=f"DeepSeek returned malformed JSON: {exc}",
                ) from exc

            try:
                choices = parsed["choices"]
                text = choices[0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                raise ProviderRequestError(
                    provider_name=self.provider_name,
                    error_type="malformed_provider_response",
                    retryable=False,
                    message="DeepSeek returned an unexpected response payload.",
                )
            if not isinstance(text, str) or not text.strip():
                raise ProviderRequestError(
                    provider_name=self.provider_name,
                    error_type="malformed_provider_response",
                    retryable=False,
                    message="DeepSeek returned an empty text payload.",
                )
            return text

        return await asyncio.to_thread(_request)


def build_default_providers(settings=None):
    settings = settings or load_settings()
    providers = []

    if settings.gemini_api_key:
        providers.append(GeminiProvider(api_key=settings.gemini_api_key, model=settings.gemini_model, timeout=settings.llm_timeout))
    if settings.groq_api_key:
        providers.append(GroqProvider(api_key=settings.groq_api_key, model=settings.groq_model, timeout=settings.llm_timeout))
    if settings.deepseek_api_key:
        providers.append(DeepSeekProvider(api_key=settings.deepseek_api_key, model=settings.deepseek_model, timeout=settings.llm_timeout))

    if not providers:
        return []
    return providers


__all__ = [
    "DeepSeekProvider",
    "GeminiProvider",
    "GroqProvider",
    "build_default_providers",
]
