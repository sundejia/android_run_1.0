"""
Tests for Avatar API endpoints.

These tests verify:
1. List all avatars
2. Serve individual avatar files
3. Serve default avatar
4. Refresh avatar metadata
"""

import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile
import shutil

# Add paths for imports
from utils.path_utils import get_project_root

backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))
project_root = get_project_root()
sys.path.insert(0, str(project_root / "src"))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers.avatars import router as avatars_router


# Create a minimal test app with just avatars router
test_app = FastAPI()
test_app.include_router(avatars_router, prefix="/avatars")


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(test_app)


@pytest.fixture
def temp_avatars_dir():
    """Create a temporary avatars directory with test files."""
    temp_dir = tempfile.mkdtemp()
    avatars_dir = Path(temp_dir) / "avatars"
    avatars_dir.mkdir()

    # Create some test avatar files (simple 1x1 PNG)
    # Minimal valid PNG: 89 50 4E 47 0D 0A 1A 0A + IHDR + IDAT + IEND
    minimal_png = bytes(
        [
            0x89,
            0x50,
            0x4E,
            0x47,
            0x0D,
            0x0A,
            0x1A,
            0x0A,  # PNG signature
            0x00,
            0x00,
            0x00,
            0x0D,
            0x49,
            0x48,
            0x44,
            0x52,  # IHDR chunk
            0x00,
            0x00,
            0x00,
            0x01,
            0x00,
            0x00,
            0x00,
            0x01,
            0x08,
            0x02,
            0x00,
            0x00,
            0x00,
            0x90,
            0x77,
            0x53,
            0xDE,
            0x00,
            0x00,
            0x00,
            0x0C,
            0x49,
            0x44,
            0x41,  # IDAT chunk
            0x54,
            0x08,
            0xD7,
            0x63,
            0xF8,
            0xFF,
            0xFF,
            0x3F,
            0x00,
            0x05,
            0xFE,
            0x02,
            0xFE,
            0xDC,
            0xCC,
            0x59,
            0xE7,
            0x00,
            0x00,
            0x00,
            0x00,
            0x49,
            0x45,
            0x4E,  # IEND chunk
            0x44,
            0xAE,
            0x42,
            0x60,
            0x82,
        ]
    )

    # Create avatar files
    (avatars_dir / "avatar_01_testuser.png").write_bytes(minimal_png)
    (avatars_dir / "avatar_02_沈子涵.png").write_bytes(minimal_png)
    (avatars_dir / "avatar_default.png").write_bytes(minimal_png)

    yield avatars_dir

    # Cleanup
    shutil.rmtree(temp_dir)


class TestAvatarsList:
    """Tests for GET /avatars endpoint."""

    def test_list_avatars(self, client, temp_avatars_dir):
        """Test listing all avatars."""
        with patch("routers.avatars.AVATARS_DIR", temp_avatars_dir):
            response = client.get("/avatars/")

            assert response.status_code == 200
            data = response.json()

            assert "avatars" in data
            assert len(data["avatars"]) == 2  # Excludes avatar_default.png

            # Check avatar metadata structure
            for avatar in data["avatars"]:
                assert "filename" in avatar
                assert "name" in avatar

    def test_list_avatars_extracts_names_correctly(self, client, temp_avatars_dir):
        """Test that avatar names are extracted correctly from filenames."""
        with patch("routers.avatars.AVATARS_DIR", temp_avatars_dir):
            response = client.get("/avatars/")

            assert response.status_code == 200
            data = response.json()

            names = [a["name"] for a in data["avatars"]]
            assert "testuser" in names
            assert "沈子涵" in names

    def test_list_avatars_empty_directory(self, client):
        """Test listing avatars when directory is empty."""
        with tempfile.TemporaryDirectory() as temp_dir:
            empty_dir = Path(temp_dir) / "avatars"
            empty_dir.mkdir()

            with patch("routers.avatars.AVATARS_DIR", empty_dir):
                response = client.get("/avatars/")

                assert response.status_code == 200
                data = response.json()
                assert data["avatars"] == []


class TestAvatarFile:
    """Tests for GET /avatars/{filename} endpoint."""

    def test_get_avatar_file(self, client, temp_avatars_dir):
        """Test getting an avatar file."""
        with patch("routers.avatars.AVATARS_DIR", temp_avatars_dir):
            response = client.get("/avatars/avatar_01_testuser.png")

            assert response.status_code == 200
            assert response.headers["content-type"] == "image/png"

    def test_get_avatar_file_chinese_name(self, client, temp_avatars_dir):
        """Test getting an avatar file with Chinese characters in filename."""
        with patch("routers.avatars.AVATARS_DIR", temp_avatars_dir):
            response = client.get("/avatars/avatar_02_沈子涵.png")

            assert response.status_code == 200
            assert response.headers["content-type"] == "image/png"

    def test_get_avatar_file_not_found(self, client, temp_avatars_dir):
        """Test getting a non-existent avatar file."""
        with patch("routers.avatars.AVATARS_DIR", temp_avatars_dir):
            response = client.get("/avatars/nonexistent.png")

            assert response.status_code == 404

    def test_get_default_avatar(self, client, temp_avatars_dir):
        """Test getting the default avatar."""
        with patch("routers.avatars.AVATARS_DIR", temp_avatars_dir):
            response = client.get("/avatars/avatar_default.png")

            assert response.status_code == 200
            assert response.headers["content-type"] == "image/png"


class TestAvatarByName:
    """Tests for GET /avatars/by-name/{name} endpoint."""

    def test_get_avatar_by_name_exact_match(self, client, temp_avatars_dir):
        """Test finding avatar by exact name match."""
        with patch("routers.avatars.AVATARS_DIR", temp_avatars_dir):
            response = client.get("/avatars/by-name/testuser")

            assert response.status_code == 200
            data = response.json()
            assert data["found"] is True
            assert "avatar_01_testuser.png" in data["url"]

    def test_get_avatar_by_name_chinese(self, client, temp_avatars_dir):
        """Test finding avatar by Chinese name."""
        with patch("routers.avatars.AVATARS_DIR", temp_avatars_dir):
            response = client.get("/avatars/by-name/沈子涵")

            assert response.status_code == 200
            data = response.json()
            assert data["found"] is True

    def test_get_avatar_by_name_not_found(self, client, temp_avatars_dir):
        """Test when no matching avatar is found."""
        with patch("routers.avatars.AVATARS_DIR", temp_avatars_dir):
            response = client.get("/avatars/by-name/nonexistent")

            assert response.status_code == 200
            data = response.json()
            assert data["found"] is False
            # Should return default avatar
            assert "avatar_default.png" in data["url"]


class TestAvatarMetadata:
    """Tests for GET /avatars/metadata endpoint."""

    def test_get_avatars_metadata(self, client, temp_avatars_dir):
        """Test getting avatar metadata as JSON."""
        with patch("routers.avatars.AVATARS_DIR", temp_avatars_dir):
            response = client.get("/avatars/metadata")

            assert response.status_code == 200
            data = response.json()

            assert isinstance(data, list)
            assert len(data) == 2

            for item in data:
                assert "filename" in item
                assert "name" in item


class TestPathTraversal:
    """Tests for path traversal security."""

    def test_path_traversal_blocked(self, client, temp_avatars_dir):
        """Test that path traversal is blocked."""
        with patch("routers.avatars.AVATARS_DIR", temp_avatars_dir):
            # Try to access parent directory
            response = client.get("/avatars/../../../etc/passwd")
            assert response.status_code == 404

    def test_absolute_path_blocked(self, client, temp_avatars_dir):
        """Test that absolute paths are blocked."""
        with patch("routers.avatars.AVATARS_DIR", temp_avatars_dir):
            response = client.get("/avatars//etc/passwd")
            assert response.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
