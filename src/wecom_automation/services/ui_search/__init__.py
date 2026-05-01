"""Reusable UI search strategy module for WeCom automation."""

from wecom_automation.services.ui_search.models import ContactMatch, SearchConfig
from wecom_automation.services.ui_search.strategy import (
    ContactFinderStrategy,
    ScrollContactFinder,
    SearchContactFinder,
)

__all__ = [
    "ContactFinderStrategy",
    "ContactMatch",
    "ScrollContactFinder",
    "SearchConfig",
    "SearchContactFinder",
]
