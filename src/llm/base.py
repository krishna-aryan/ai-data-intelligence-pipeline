from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol


class LLMProvider(Protocol):
    """Small provider contract for model text generation."""

    async def generate(self, prompt: str) -> str:
        """Generate raw model output from a prompt."""


class BaseLLMProvider(ABC):
    """Abstract base class for LLM backends."""

    @abstractmethod
    async def generate(self, prompt: str) -> str:
        """Return model output in plain text form."""
