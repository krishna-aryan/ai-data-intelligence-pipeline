from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


class ProviderRequestError(RuntimeError):
    def __init__(
        self,
        *,
        provider_name: str,
        error_type: str,
        retryable: bool,
        message: str,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.provider_name = provider_name
        self.error_type = error_type
        self.retryable = retryable
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class ProviderFallbackError(RuntimeError):
    def __init__(
        self,
        *,
        providers_attempted: list[str],
        provider_failures: list[ProviderRequestError],
        final_status: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.providers_attempted = providers_attempted
        self.provider_failures = provider_failures
        self.final_status = final_status
        self.message = message
        self.metadata = metadata or {}
        super().__init__(message)


@dataclass
class ProviderAttemptResult:
    provider_name: str
    attempt_index: int
    succeeded: bool = False
    response: str | None = None
    error: ProviderRequestError | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class FallbackOrchestrator:
    """Try providers in order until one succeeds or all fail."""

    def __init__(self, providers: list[Any]) -> None:
        self.providers = providers
        self.last_provider_used: str | None = None
        self.last_metadata: dict[str, Any] = {}

    async def generate(self, prompt: str, *, chunk_id: str | None = None) -> str:
        if not self.providers:
            raise ProviderFallbackError(
                providers_attempted=[],
                provider_failures=[],
                final_status="all_providers_failed",
                message="No providers were configured.",
                metadata={"chunk_id": chunk_id},
            )

        failures: list[ProviderRequestError] = []
        attempts: list[str] = []

        for index, provider in enumerate(self.providers):
            provider_name = getattr(provider, "provider_name", getattr(provider, "name", f"provider-{index}"))
            attempts.append(provider_name)

            if hasattr(provider, "is_available") and not provider.is_available():
                try:
                    await provider.generate(prompt)
                except ProviderRequestError as exc:
                    failures.append(exc)
                    continue
                except Exception as exc:
                    failure = ProviderRequestError(
                        provider_name=provider_name,
                        error_type="invalid_authentication",
                        retryable=False,
                        message=str(exc),
                        status_code=getattr(exc, "status_code", 401),
                    )
                    failures.append(failure)
                    continue
                else:
                    self.last_provider_used = provider_name
                    self.last_metadata = {
                        "provider_used": provider_name,
                        "attempts": len(attempts),
                        "fallback_occurred": len(failures) > 0,
                        "providers_attempted": attempts.copy(),
                        "provider_failures": [
                            {"provider_name": err.provider_name, "error_type": err.error_type, "retryable": err.retryable, "status_code": err.status_code}
                            for err in failures
                        ],
                        "chunk_id": chunk_id,
                    }
                    return ""

            try:
                response = await provider.generate(prompt)
                self.last_provider_used = provider_name
                self.last_metadata = {
                    "provider_used": provider_name,
                    "attempts": len(attempts),
                    "fallback_occurred": len(failures) > 0,
                    "providers_attempted": attempts.copy(),
                    "provider_failures": [
                        {"provider_name": err.provider_name, "error_type": err.error_type, "retryable": err.retryable, "status_code": err.status_code}
                        for err in failures
                    ],
                    "chunk_id": chunk_id,
                }
                return response
            except ProviderRequestError as exc:
                failures.append(exc)
                if exc.retryable:
                    continue
                raise ProviderFallbackError(
                    providers_attempted=attempts.copy(),
                    provider_failures=failures,
                    final_status="non_retryable_error",
                    message=f"Provider {provider_name} failed with a non-retryable error: {exc.message}",
                    metadata={
                        "provider_used": provider_name,
                        "attempts": len(attempts),
                        "fallback_occurred": len(failures) > 1,
                        "chunk_id": chunk_id,
                    },
                ) from exc
            except TimeoutError as exc:
                err = ProviderRequestError(
                    provider_name=provider_name,
                    error_type="timeout",
                    retryable=True,
                    message=str(exc),
                    status_code=None,
                )
                failures.append(err)
                continue
            except ConnectionError as exc:
                err = ProviderRequestError(
                    provider_name=provider_name,
                    error_type="connection_error",
                    retryable=True,
                    message=str(exc),
                    status_code=None,
                )
                failures.append(err)
                continue
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                error_type = getattr(exc, "error_type", "unknown_provider_error")
                message = str(exc)
                retryable = bool(getattr(exc, "retryable", False))

                if isinstance(status_code, int) and status_code in {429, 500, 502, 503, 504}:
                    retryable = True
                if error_type in {"rate_limited", "timeout", "connection_error", "temporary_server_error"}:
                    retryable = True
                if "api key" in message.lower() or "authentication" in message.lower() or status_code == 401:
                    retryable = False
                    error_type = "invalid_authentication"
                elif not retryable and error_type == "unknown_provider_error":
                    retryable = True

                next_error = ProviderRequestError(
                    provider_name=provider_name,
                    error_type=error_type,
                    retryable=retryable,
                    message=message,
                    status_code=status_code,
                )
                failures.append(next_error)
                if not retryable:
                    raise ProviderFallbackError(
                        providers_attempted=attempts.copy(),
                        provider_failures=failures,
                        final_status="non_retryable_error",
                        message=f"Provider {provider_name} failed with a non-retryable error: {message}",
                        metadata={
                            "provider_used": provider_name,
                            "attempts": len(attempts),
                            "fallback_occurred": len(failures) > 1,
                            "chunk_id": chunk_id,
                        },
                    ) from exc
                continue
            try:
                response = await provider.generate(prompt)
                self.last_provider_used = provider_name
                self.last_metadata = {
                    "provider_used": provider_name,
                    "attempts": len(attempts),
                    "fallback_occurred": len(failures) > 0,
                    "providers_attempted": attempts.copy(),
                    "provider_failures": [
                        {
                            "provider_name": err.provider_name,
                            "error_type": err.error_type,
                            "retryable": err.retryable,
                            "status_code": err.status_code,
                        }
                        for err in failures
                    ],
                    "chunk_id": chunk_id,
                }
                return response
            except ProviderRequestError as exc:
                failures.append(exc)
                if exc.retryable:
                    continue
                raise ProviderFallbackError(
                    providers_attempted=attempts.copy(),
                    provider_failures=failures,
                    final_status="non_retryable_error",
                    message=f"Provider {provider_name} failed with a non-retryable error: {exc.message}",
                    metadata={
                        "provider_used": provider_name,
                        "attempts": len(attempts),
                        "fallback_occurred": len(failures) > 1,
                        "chunk_id": chunk_id,
                    },
                ) from exc
            except TimeoutError as exc:
                err = ProviderRequestError(
                    provider_name=provider_name,
                    error_type="timeout",
                    retryable=True,
                    message=str(exc),
                    status_code=None,
                )
                failures.append(err)
                continue
            except ConnectionError as exc:
                err = ProviderRequestError(
                    provider_name=provider_name,
                    error_type="connection_error",
                    retryable=True,
                    message=str(exc),
                    status_code=None,
                )
                failures.append(err)
                continue
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                error_type = getattr(exc, "error_type", "unknown_provider_error")
                message = str(exc)
                retryable = bool(getattr(exc, "retryable", False))

                if isinstance(status_code, int) and status_code in {429, 500, 502, 503, 504}:
                    retryable = True
                if error_type in {"rate_limited", "timeout", "connection_error", "temporary_server_error"}:
                    retryable = True
                if "api key" in message.lower() or "authentication" in message.lower() or status_code == 401:
                    retryable = False
                    error_type = "invalid_authentication"
                elif not retryable and error_type == "unknown_provider_error":
                    retryable = True

                next_error = ProviderRequestError(
                    provider_name=provider_name,
                    error_type=error_type,
                    retryable=retryable,
                    message=message,
                    status_code=status_code,
                )
                failures.append(next_error)
                if not retryable:
                    raise ProviderFallbackError(
                        providers_attempted=attempts.copy(),
                        provider_failures=failures,
                        final_status="non_retryable_error",
                        message=f"Provider {provider_name} failed with a non-retryable error: {message}",
                        metadata={
                            "provider_used": provider_name,
                            "attempts": len(attempts),
                            "fallback_occurred": len(failures) > 1,
                            "chunk_id": chunk_id,
                        },
                    ) from exc
                continue

        self.last_metadata = {
            "providers_attempted": attempts,
            "fallback_occurred": bool(failures),
            "provider_failures": [
                {
                    "provider_name": err.provider_name,
                    "error_type": err.error_type,
                    "retryable": err.retryable,
                    "status_code": err.status_code,
                }
                for err in failures
            ],
            "chunk_id": chunk_id,
        }
        raise ProviderFallbackError(
            providers_attempted=attempts,
            provider_failures=failures,
            final_status="all_providers_failed",
            message="All configured providers failed.",
            metadata=self.last_metadata,
        )


__all__ = [
    "FallbackOrchestrator",
    "ProviderAttemptResult",
    "ProviderFallbackError",
    "ProviderRequestError",
]
