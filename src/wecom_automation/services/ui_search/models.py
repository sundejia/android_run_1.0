"""Data models for the UI search strategy module."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchConfig:
    """Configuration for contact search behavior."""

    max_retries: int = 3
    step_delay: float = 1.0
    stabilization_delay: float = 0.5


@dataclass
class ContactMatch:
    """A matched contact element from search/scroll."""

    element: dict
    matched_text: str
    confidence: float = 1.0
