"""
Tests for droidrun_index field in data models.

TDD Step 11: Data Models
"""


class TestUserDetailDroidrunIndex:
    """Tests for UserDetail.droidrun_index field."""

    def test_user_detail_has_droidrun_index_field(self):
        """UserDetail should have droidrun_index field."""
        from wecom_automation.core.models import UserDetail

        user = UserDetail(name="wgz")

        assert hasattr(user, "droidrun_index")

    def test_user_detail_droidrun_index_default_none(self):
        """UserDetail.droidrun_index should default to None."""
        from wecom_automation.core.models import UserDetail

        user = UserDetail(name="wgz")

        assert user.droidrun_index is None

    def test_user_detail_droidrun_index_can_be_set(self):
        """UserDetail.droidrun_index can be set to an integer."""
        from wecom_automation.core.models import UserDetail

        user = UserDetail(name="wgz", droidrun_index=5)

        assert user.droidrun_index == 5

    def test_user_detail_droidrun_index_in_to_dict(self):
        """UserDetail.to_dict() should include droidrun_index."""
        from wecom_automation.core.models import UserDetail

        user = UserDetail(name="wgz", droidrun_index=7)

        data = user.to_dict()

        assert "droidrun_index" in data
        assert data["droidrun_index"] == 7

    def test_user_detail_droidrun_index_none_in_to_dict(self):
        """UserDetail.to_dict() should include droidrun_index even when None."""
        from wecom_automation.core.models import UserDetail

        user = UserDetail(name="wgz")

        data = user.to_dict()

        assert "droidrun_index" in data
        assert data["droidrun_index"] is None

    def test_user_detail_from_dict_with_droidrun_index(self):
        """UserDetail.from_dict() should restore droidrun_index."""
        from wecom_automation.core.models import UserDetail

        data = {"name": "wgz", "droidrun_index": 10}

        user = UserDetail.from_dict(data)

        assert user.droidrun_index == 10

    def test_user_detail_from_dict_without_droidrun_index(self):
        """UserDetail.from_dict() should handle missing droidrun_index."""
        from wecom_automation.core.models import UserDetail

        data = {"name": "wgz"}

        user = UserDetail.from_dict(data)

        assert user.droidrun_index is None


class TestUserDetailFormat:
    """Tests for UserDetail.format() including droidrun_index."""

    def test_format_includes_droidrun_index(self):
        """UserDetail.format() should include droidrun_index when set."""
        from wecom_automation.core.models import UserDetail

        user = UserDetail(name="wgz", droidrun_index=5)

        formatted = user.format(1)

        assert "DroidRun Index" in formatted or "droidrun" in formatted.lower()

    def test_format_handles_none_droidrun_index(self):
        """UserDetail.format() should handle None droidrun_index."""
        from wecom_automation.core.models import UserDetail

        user = UserDetail(name="wgz")

        # Should not raise
        formatted = user.format(1)

        assert "wgz" in formatted
