"""
Internationalization API Endpoints
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional

from i18n.translations import (
    get_all_translations,
    get_category_translations,
    get_supported_languages,
    DEFAULT_LANGUAGE,
)
from models.system_settings import SystemSettingsModel

router = APIRouter(prefix="/api/settings", tags=["i18n"])

settings_model = SystemSettingsModel()


class LanguageRequest(BaseModel):
    language: str


class LanguageResponse(BaseModel):
    current: str
    supported: Dict[str, str]
    default: str


class TranslationsResponse(BaseModel):
    language: str
    translations: Dict[str, Any]


@router.get("/language", response_model=LanguageResponse)
async def get_language():
    """Get current language setting"""
    return LanguageResponse(
        current=settings_model.get_language(),
        supported=get_supported_languages(),
        default=DEFAULT_LANGUAGE,
    )


@router.put("/language")
async def set_language(request: LanguageRequest):
    """Set language"""
    supported = get_supported_languages()
    if request.language not in supported:
        raise HTTPException(
            status_code=400, detail=f"Unsupported language: {request.language}. Supported: {list(supported.keys())}"
        )

    settings_model.set_language(request.language)
    return {
        "success": True,
        "language": request.language,
        "message": f"Language changed to {supported[request.language]}",
    }


@router.get("/translations", response_model=TranslationsResponse)
async def get_translations(lang: Optional[str] = None):
    """Get all translations"""
    if lang is None:
        lang = settings_model.get_language()

    return TranslationsResponse(
        language=lang,
        translations=get_all_translations(lang),
    )


@router.get("/translations/{category}")
async def get_translations_by_category(category: str, lang: Optional[str] = None):
    """Get translations for specified category"""
    if lang is None:
        lang = settings_model.get_language()

    translations = get_category_translations(lang, category)
    if not translations:
        raise HTTPException(status_code=404, detail=f"Category '{category}' not found")

    return {
        "language": lang,
        "category": category,
        "translations": translations,
    }
