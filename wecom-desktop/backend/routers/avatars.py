"""
Avatars router.

Provides endpoints to serve avatar images from the avatars folder.
This solves the issue where backend saves avatars to `avatars/` folder
but frontend expects them from `public/avatars/`.

Now frontend can fetch avatars directly from backend API regardless of
development or production environment.
"""

import re
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from wecom_automation.database.schema import PROJECT_ROOT

# Avatar directory at project root
AVATARS_DIR = PROJECT_ROOT / "avatars"

router = APIRouter()


class AvatarInfo(BaseModel):
    """Avatar metadata."""

    filename: str
    name: str


class AvatarListResponse(BaseModel):
    """Response for avatar list."""

    avatars: List[AvatarInfo]
    avatars_dir: str


class AvatarLookupResponse(BaseModel):
    """Response for avatar lookup by name."""

    found: bool
    name: str
    url: str
    filename: Optional[str] = None


def _extract_name_from_filename(filename: str) -> Optional[str]:
    """
    Extract the name part from avatar filename.

    Supports two filename formats:
    1. avatar_XX_name.png (with numeric prefix, e.g., avatar_01_张三.png)
    2. avatar_name.png (without prefix, e.g., avatar_张三.png)

    Returns None if filename doesn't match expected pattern.
    """
    # Try format with numeric prefix first: avatar_XX_name.png
    match = re.match(r"^avatar_\d+_(.+)\.png$", filename)
    if match:
        return match.group(1)

    # Try format without prefix: avatar_name.png
    match = re.match(r"^avatar_(.+)\.png$", filename)
    if match:
        name = match.group(1)
        # Exclude "default" as it's the fallback avatar
        if name.lower() != "default":
            return name

    return None


def _normalize_name(name: str) -> str:
    """
    Normalize a name for matching.

    This matches the frontend logic in avatars.ts:
    - Lowercase
    - Keep alphanumeric (including Chinese characters), hyphens, underscores, dots
    - Replace all other characters with underscore
    """
    return re.sub(r"[^a-z0-9\u4e00-\u9fff\-_.]", "_", name.lower().strip())


def _get_avatar_files() -> List[AvatarInfo]:
    """
    Get list of avatar files with their metadata.

    Excludes avatar_default.png from the list.
    """
    if not AVATARS_DIR.exists():
        return []

    avatars = []
    for file in sorted(AVATARS_DIR.iterdir()):
        if not file.is_file():
            continue
        if not file.suffix.lower() == ".png":
            continue
        if file.name == "avatar_default.png":
            continue
        if not file.name.startswith("avatar_"):
            continue

        name = _extract_name_from_filename(file.name)
        if name:
            avatars.append(AvatarInfo(filename=file.name, name=name))

    return avatars


def _find_matching_avatar(customer_name: str) -> Optional[AvatarInfo]:
    """
    Find an avatar that matches the given customer name.

    Tries exact match first, then checks if customer name starts with avatar name.
    """
    avatars = _get_avatar_files()
    normalized = _normalize_name(customer_name)

    # 1. Try exact match (case-insensitive, normalized)
    for avatar in avatars:
        if _normalize_name(avatar.name) == normalized:
            return avatar

    # 2. Try to find avatar name that the customer name starts with
    # Sort by name length descending to prefer longer matches
    sorted_avatars = sorted(avatars, key=lambda a: len(a.name), reverse=True)
    for avatar in sorted_avatars:
        avatar_norm = _normalize_name(avatar.name)
        if normalized.startswith(avatar_norm):
            return avatar

    # 3. Try to find if avatar name starts with customer name
    for avatar in avatars:
        avatar_norm = _normalize_name(avatar.name)
        if avatar_norm.startswith(normalized) and len(normalized) >= 2:
            return avatar

    return None


@router.get("/", response_model=AvatarListResponse)
async def list_avatars():
    """
    List all available avatars.

    Returns a list of avatar files with their extracted names.
    Excludes the default avatar from the list.
    """
    avatars = _get_avatar_files()
    return AvatarListResponse(
        avatars=avatars,
        avatars_dir=str(AVATARS_DIR),
    )


@router.get("/metadata")
async def get_avatars_metadata():
    """
    Get avatar metadata as JSON array.

    This is compatible with the format expected by the frontend's
    loadAvatarsFromJson() function.

    Returns:
        List of {filename, name} objects.
    """
    avatars = _get_avatar_files()
    return [{"filename": a.filename, "name": a.name} for a in avatars]


@router.get("/by-name/{name}", response_model=AvatarLookupResponse)
async def get_avatar_by_name(name: str):
    """
    Find avatar URL by customer name.

    Tries to match the name against available avatars.
    If no match is found, returns the default avatar.

    Args:
        name: Customer name to look up.

    Returns:
        Avatar lookup result with URL.
    """
    avatar = _find_matching_avatar(name)

    if avatar:
        return AvatarLookupResponse(
            found=True,
            name=name,
            url=f"/avatars/{avatar.filename}",
            filename=avatar.filename,
        )

    # Return default avatar
    return AvatarLookupResponse(
        found=False,
        name=name,
        url="/avatars/avatar_default.png",
        filename="avatar_default.png",
    )


@router.get("/{filename}")
async def get_avatar_file(filename: str):
    """
    Serve an avatar image file.

    Args:
        filename: Avatar filename (e.g., avatar_01_testuser.png)

    Returns:
        The avatar image file.

    Raises:
        HTTPException: If file not found or path traversal attempted.
    """
    # Security: Prevent path traversal
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=404, detail="Avatar not found")

    # Build the file path
    file_path = AVATARS_DIR / filename

    # Security: Ensure the resolved path is within AVATARS_DIR
    try:
        file_path = file_path.resolve()
        if not str(file_path).startswith(str(AVATARS_DIR.resolve())):
            raise HTTPException(status_code=404, detail="Avatar not found")
    except (ValueError, OSError):
        raise HTTPException(status_code=404, detail="Avatar not found")

    # Check if file exists
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Avatar not found")

    # Determine media type
    suffix = file_path.suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_types.get(suffix, "image/png")

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=filename,
    )
