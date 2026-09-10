from __future__ import annotations

import asyncio
import json
from urllib import error, request

from .base import BaseLLMProvider


class GeminiProviderError(RuntimeError):
    """Raised when the Gemini provider fails."""


class GeminiProvider(BaseLLMProvider):
    """Minimal Gemini REST provider for the current extraction foundation."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gemini-1.5-flash",
        api_base_url: str | None = None,
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.api_base_url = api_base_url or (
            "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        )

    async def generate(self, prompt: str) -> str:
        if not self.api_key:
            raise GeminiProviderError("GEMINI_API_KEY is not configured.")

        url = self.api_base_url.format(model=self.model)
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                    ]
                }
            ]
        }

        def _do_request() -> str:
            data = json.dumps(payload).encode("utf-8")
            req = request.Request(
                f"{url}?key={self.api_key}",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with request.urlopen(req, timeout=self.timeout) as response:
                    body = response.read().decode("utf-8")
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise GeminiProviderError(f"Gemini API request failed: {detail}") from exc
            except Exception as exc:  # pragma: no cover - defensive branch
                raise GeminiProviderError(f"Gemini API request failed: {exc}") from exc

            try:
                parsed = json.loads(body)
            except json.JSONDecodeError as exc:
                raise GeminiProviderError(f"Gemini returned malformed JSON: {exc}") from exc

            candidates = parsed.get("candidates") or []
            if not candidates:
                raise GeminiProviderError("Gemini returned no candidates.")

            parts = candidates[0].get("content", {}).get("parts") or []
            if not parts:
                raise GeminiProviderError("Gemini returned empty content parts.")

            text = parts[0].get("text", "")
            if not isinstance(text, str) or not text.strip():
                raise GeminiProviderError("Gemini returned an empty text payload.")

            return text

        try:
            return await asyncio.to_thread(_do_request)
        except GeminiProviderError:
            raise
        except Exception as exc:  # pragma: no cover - defensive branch
            raise GeminiProviderError(f"Gemini provider failure: {exc}") from exc


__all__ = ["GeminiProvider", "GeminiProviderError"]
