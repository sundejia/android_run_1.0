"""
i18n module for WeCom Desktop

Provides translation services and language management.
"""

from .translations import (
    get_translation,
    get_all_translations,
    get_category_translations,
    get_supported_languages,
    DEFAULT_LANGUAGE,
    SUPPORTED_LANGUAGES,
)

__all__ = [
    "get_translation",
    "get_all_translations",
    "get_category_translations",
    "get_supported_languages",
    "DEFAULT_LANGUAGE",
    "SUPPORTED_LANGUAGES",
]
