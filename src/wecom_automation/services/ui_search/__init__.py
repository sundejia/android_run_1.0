"""Reusable UI search strategy module for WeCom automation."""

from wecom_automation.services.ui_search.models import ContactMatch, SearchConfig
from wecom_automation.services.ui_search.strategy import (
    CompositeContactFinder,
    ContactFinderStrategy,
    ScrollContactFinder,
    SearchContactFinder,
)

__all__ = [
    "CompositeContactFinder",
    "ContactFinderStrategy",
    "ContactMatch",
    "ScrollContactFinder",
    "SearchConfig",
    "SearchContactFinder",
]
