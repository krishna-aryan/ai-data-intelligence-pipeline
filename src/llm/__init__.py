"""LLM extraction foundation for the intelligence pipeline."""

from .base import BaseLLMProvider, LLMProvider
from .chunking import TextChunk, chunk_text
from .extractor import ExtractionFailure, ExtractionResult, LLMExtractor
from .fallback import FallbackOrchestrator, ProviderFallbackError, ProviderRequestError
from .models import CanonicalRecord, ExtractionRequest, SourceExtractionContext
from .provider import DeepSeekProvider, GeminiProvider, GroqProvider, build_default_providers

__all__ = [
    "BaseLLMProvider",
    "CanonicalRecord",
    "DeepSeekProvider",
    "ExtractionFailure",
    "ExtractionRequest",
    "ExtractionResult",
    "FallbackOrchestrator",
    "GeminiProvider",
    "GroqProvider",
    "LLMExtractor",
    "LLMProvider",
    "ProviderFallbackError",
    "ProviderRequestError",
    "SourceExtractionContext",
    "TextChunk",
    "build_default_providers",
    "chunk_text",
]
