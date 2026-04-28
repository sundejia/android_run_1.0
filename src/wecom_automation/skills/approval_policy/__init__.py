"""Approval-policy skill family.

A skill version takes the four boolean fields produced by the rating-server
prompt and decides whether the customer image clears the review gate.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

_SUPPORTED_VERSIONS = ("v1",)


def load(skill_version: str) -> ModuleType:
    """Return the module implementing ``skill_version``.

    Raises:
        KeyError: when ``skill_version`` is not registered.
    """
    if skill_version not in _SUPPORTED_VERSIONS:
        raise KeyError(skill_version)
    return import_module(f"{__name__}.{skill_version}")


def supported_versions() -> tuple[str, ...]:
    return _SUPPORTED_VERSIONS
