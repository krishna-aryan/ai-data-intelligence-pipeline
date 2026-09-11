from __future__ import annotations

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
    def __init__(self, providers: list[Any]) -> None:
        self.providers = providers
        self.last_provider_used: str | None = None
        self.last_metadata: dict[str, Any] = {}

    async def generate(self, prompt: str, *, chunk_id: str | None = None) -> str:
        attempts: list[str] = []
        failures: list[ProviderRequestError] = []
        self.last_provider_used = None

        for index, provider in enumerate(self.providers):
            name = getattr(provider, "provider_name", getattr(provider, "name", f"provider-{index}"))
            attempts.append(name)
            if hasattr(provider, "is_available") and not provider.is_available():
                try:
                    await provider.generate(prompt)
                except ProviderRequestError as exc:
                    failures.append(exc)
                except Exception as exc:
                    failures.append(
                        ProviderRequestError(
                            provider_name=name,
                            error_type="invalid_authentication",
                            retryable=False,
                            message=str(exc),
                            status_code=401,
                        )
                    )
                continue
            try:
                response = await provider.generate(prompt)
            except ProviderRequestError as exc:
                failures.append(exc)
                if not exc.retryable:
                    raise self._non_retryable(attempts, failures, chunk_id, name, exc) from exc
                continue
            except (TimeoutError, ConnectionError) as exc:
                failures.append(self._classified(name, exc))
                continue
            except Exception as exc:
                classified = self._classify_exception(name, exc)
                failures.append(classified)
                if not classified.retryable:
                    raise self._non_retryable(attempts, failures, chunk_id, name, classified) from exc
                continue

            self.last_provider_used = name
            self.last_metadata = self._metadata(attempts, failures, chunk_id, name)
            return response

        self.last_metadata = self._metadata(attempts, failures, chunk_id, None)
        raise ProviderFallbackError(
            providers_attempted=attempts,
            provider_failures=failures,
            final_status="all_providers_failed",
            message="All configured providers failed." if attempts else "No providers were configured.",
            metadata=self.last_metadata,
        )

    def _metadata(self, attempts, failures, chunk_id, provider_name):
        return {
            "provider_used": provider_name,
            "providers_attempted": list(attempts),
            "attempts": len(attempts),
            "fallback_occurred": bool(failures),
            "provider_failures": [
                {"provider_name": item.provider_name, "error_type": item.error_type,
                 "retryable": item.retryable, "status_code": item.status_code}
                for item in failures
            ],
            "chunk_id": chunk_id,
        }

    def _non_retryable(self, attempts, failures, chunk_id, provider_name, error):
        return ProviderFallbackError(
            providers_attempted=list(attempts),
            provider_failures=list(failures),
            final_status="non_retryable_error",
            message=f"Provider {provider_name} failed with a non-retryable error: {error.message}",
            metadata=self._metadata(attempts, failures, chunk_id, provider_name),
        )

    @staticmethod
    def _classified(provider_name: str, error: Exception) -> ProviderRequestError:
        error_type = "timeout" if isinstance(error, TimeoutError) else "connection_error"
        return ProviderRequestError(
            provider_name=provider_name, error_type=error_type, retryable=True, message=str(error)
        )

    @staticmethod
    def _classify_exception(provider_name: str, error: Exception) -> ProviderRequestError:
        status_code = getattr(error, "status_code", None)
        error_type = getattr(error, "error_type", "unknown_provider_error")
        message = str(error)
        retryable = bool(getattr(error, "retryable", False))
        if status_code in {429, 500, 502, 503, 504} or error_type in {
            "rate_limited", "timeout", "connection_error", "temporary_server_error"
        }:
            retryable = True
        if status_code == 401 or "api key" in message.lower() or "authentication" in message.lower():
            error_type = "invalid_authentication"
            retryable = False
        return ProviderRequestError(
            provider_name=provider_name, error_type=error_type, retryable=retryable,
            message=message, status_code=status_code
        )


__all__ = ["FallbackOrchestrator", "ProviderAttemptResult", "ProviderFallbackError", "ProviderRequestError"]
