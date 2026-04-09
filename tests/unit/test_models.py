"""
Unit tests for data models.
"""

from wecom_automation.core.models import (
    AvatarInfo,
    ExtractionResult,
    MessageEntry,
    UserDetail,
)


class TestAvatarInfo:
    """Tests for AvatarInfo model."""

    def test_parse_bounds_valid(self):
        """Test parsing valid bounds string."""
        avatar = AvatarInfo(bounds="[36,200][120,284]")
        assert avatar.parse_bounds() is True
        assert avatar.x1 == 36
        assert avatar.y1 == 200
        assert avatar.x2 == 120
        assert avatar.y2 == 284

    def test_parse_bounds_invalid(self):
        """Test parsing invalid bounds string."""
        avatar = AvatarInfo(bounds="invalid")
        assert avatar.parse_bounds() is False

    def test_parse_bounds_none(self):
        """Test parsing None bounds."""
        avatar = AvatarInfo()
        assert avatar.parse_bounds() is False

    def test_width_height(self):
        """Test width and height properties."""
        avatar = AvatarInfo(bounds="[0,0][100,80]")
        avatar.parse_bounds()
        assert avatar.width == 100
        assert avatar.height == 80

    def test_is_valid(self):
        """Test validity check."""
        avatar = AvatarInfo(bounds="[0,0][100,80]")
        avatar.parse_bounds()
        assert avatar.is_valid is True

        empty_avatar = AvatarInfo()
        assert empty_avatar.is_valid is False

    def test_str_with_path(self):
        """Test string representation with screenshot path."""
        avatar = AvatarInfo(screenshot_path="/path/to/avatar.png")
        assert "saved:" in str(avatar)

    def test_str_with_bounds(self):
        """Test string representation with bounds."""
        avatar = AvatarInfo(bounds="[0,0][100,100]")
        assert "[0,0][100,100]" in str(avatar)

    def test_str_not_found(self):
        """Test string representation when not found."""
        avatar = AvatarInfo()
        assert "not found" in str(avatar)

    def test_to_dict(self):
        """Test dictionary conversion."""
        avatar = AvatarInfo(
            bounds="[0,0][100,100]",
            resource_id="avatar_id",
            screenshot_path="/path/to/file.png",
        )
        d = avatar.to_dict()
        assert d["bounds"] == "[0,0][100,100]"
        assert d["resource_id"] == "avatar_id"
        assert d["screenshot_path"] == "/path/to/file.png"


class TestMessageEntry:
    """Tests for MessageEntry model."""

    def test_format_with_all_fields(self):
        """Test formatting with all fields."""
        entry = MessageEntry(
            title="John",
            snippet="Hello world",
            timestamp="10:30",
        )
        formatted = entry.format(1)
        assert "1. John" in formatted
        assert "Hello world" in formatted
        assert "10:30" in formatted

    def test_format_minimal(self):
        """Test formatting with only title."""
        entry = MessageEntry(title="Jane")
        formatted = entry.format(2)
        assert "2. Jane" in formatted

    def test_to_dict(self):
        """Test dictionary conversion."""
        entry = MessageEntry(
            title="Test",
            snippet="Preview",
            timestamp="12:00",
        )
        d = entry.to_dict()
        assert d["title"] == "Test"
        assert d["snippet"] == "Preview"
        assert d["timestamp"] == "12:00"


class TestUserDetail:
    """Tests for UserDetail model."""

    def test_unique_key_with_channel(self):
        """Test unique key generation with channel."""
        user = UserDetail(name="John", channel="@WeChat")
        assert user.unique_key() == "John|@WeChat"

    def test_unique_key_without_channel(self):
        """Test unique key generation without channel."""
        user = UserDetail(name="John")
        assert user.unique_key() == "John|"

    def test_format(self):
        """Test detailed formatting."""
        user = UserDetail(
            name="张三",
            channel="@WeChat",
            last_message_date="10:30",
            message_preview="Hello!",
        )
        formatted = user.format(1)
        assert "张三" in formatted
        assert "@WeChat" in formatted
        assert "10:30" in formatted
        assert "Hello!" in formatted

    def test_format_table_row(self):
        """Test table row formatting."""
        user = UserDetail(
            name="TestUser",
            channel="@WeChat",
            last_message_date="Today",
            message_preview="Test message",
        )
        row = user.format_table_row(1)
        assert "TestUser" in row
        assert "@WeChat" in row

    def test_to_dict(self):
        """Test dictionary conversion."""
        avatar = AvatarInfo(bounds="[0,0][100,100]")
        user = UserDetail(
            name="Test",
            channel="@WeChat",
            last_message_date="Today",
            message_preview="Hi",
            avatar=avatar,
        )
        d = user.to_dict()
        assert d["name"] == "Test"
        assert d["channel"] == "@WeChat"
        assert d["avatar"] is not None
        assert d["avatar"]["bounds"] == "[0,0][100,100]"

    def test_merge_with_fills_missing(self):
        """Test merging fills in missing fields."""
        user1 = UserDetail(
            name="John",
            channel="@WeChat",
        )
        user2 = UserDetail(
            name="John",
            channel="@WeChat",
            last_message_date="Today",
            message_preview="Hello",
        )
        merged = user1.merge_with(user2)
        assert merged.name == "John"
        assert merged.channel == "@WeChat"
        assert merged.last_message_date == "Today"
        assert merged.message_preview == "Hello"

    def test_merge_preserves_existing(self):
        """Test merging preserves existing fields."""
        user1 = UserDetail(
            name="John",
            channel="@WeChat",
            last_message_date="Yesterday",
        )
        user2 = UserDetail(
            name="John",
            last_message_date="Today",  # Different value
            message_preview="Hello",
        )
        merged = user1.merge_with(user2)
        # Should keep user1's values where they exist
        assert merged.last_message_date == "Yesterday"
        # Should get user2's value for missing field
        assert merged.message_preview == "Hello"


class TestExtractionResult:
    """Tests for ExtractionResult model."""

    def test_total_count(self):
        """Test total count property."""
        users = [
            UserDetail(name="User1"),
            UserDetail(name="User2"),
            UserDetail(name="User3"),
        ]
        result = ExtractionResult(users=users)
        assert result.total_count == 3

    def test_empty_result(self):
        """Test empty result."""
        result = ExtractionResult(users=[])
        assert result.total_count == 0
        assert "No users found" in result.format_table()

    def test_format_table(self):
        """Test table formatting."""
        users = [
            UserDetail(name="User1", channel="@WeChat"),
            UserDetail(name="User2", last_message_date="Today"),
        ]
        result = ExtractionResult(users=users)
        table = result.format_table()
        assert "User1" in table
        assert "User2" in table
        assert "Total: 2 users" in table

    def test_to_dict(self):
        """Test dictionary conversion."""
        users = [UserDetail(name="Test")]
        result = ExtractionResult(
            users=users,
            total_scrolls=5,
            duration_seconds=10.5,
            success=True,
        )
        d = result.to_dict()
        assert d["total_count"] == 1
        assert d["total_scrolls"] == 5
        assert d["duration_seconds"] == 10.5
        assert d["success"] is True
        assert len(d["users"]) == 1

    def test_failed_result(self):
        """Test failed result."""
        result = ExtractionResult(
            users=[],
            success=False,
            error_message="Connection failed",
        )
        assert result.success is False
        assert result.error_message == "Connection failed"
