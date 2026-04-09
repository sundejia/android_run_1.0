"""
Tests for type-specific element helpers.

TDD Step 7: Type Helpers
"""


class TestGetElementsByType:
    """Tests for get_elements_by_type() method."""

    def test_get_elements_by_type_filters_by_classname(self):
        """get_elements_by_type() should filter by className."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.clickable_elements = [
            {"index": 0, "className": "android.widget.Button"},
            {"index": 1, "className": "android.widget.TextView"},
            {"index": 2, "className": "android.widget.ImageButton"},
        ]

        buttons = service.get_elements_by_type("Button")

        assert len(buttons) == 2
        assert buttons[0]["index"] == 0
        assert buttons[1]["index"] == 2

    def test_get_elements_by_type_case_insensitive(self):
        """get_elements_by_type() should be case insensitive."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.clickable_elements = [
            {"index": 0, "className": "android.widget.Button"},
        ]

        buttons = service.get_elements_by_type("button")

        assert len(buttons) == 1

    def test_get_elements_by_type_returns_empty_when_none_found(self):
        """get_elements_by_type() should return empty list when none found."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.clickable_elements = [
            {"index": 0, "className": "android.widget.TextView"},
        ]

        buttons = service.get_elements_by_type("Button")

        assert buttons == []

    def test_get_elements_by_type_handles_missing_classname(self):
        """get_elements_by_type() should handle elements without className."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.clickable_elements = [
            {"index": 0},  # No className
            {"index": 1, "className": "android.widget.Button"},
        ]

        buttons = service.get_elements_by_type("Button")

        assert len(buttons) == 1
        assert buttons[0]["index"] == 1


class TestGetButtons:
    """Tests for get_buttons() method."""

    def test_get_buttons_returns_button_elements(self):
        """get_buttons() should return Button and ImageButton elements."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.clickable_elements = [
            {"index": 0, "className": "android.widget.Button"},
            {"index": 1, "className": "android.widget.TextView"},
            {"index": 2, "className": "android.widget.ImageButton"},
        ]

        buttons = service.get_buttons()

        assert len(buttons) == 2
        assert buttons[0]["index"] == 0
        assert buttons[1]["index"] == 2

    def test_get_buttons_returns_empty_when_none(self):
        """get_buttons() should return empty list when no buttons."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.clickable_elements = [
            {"index": 0, "className": "android.widget.TextView"},
        ]

        buttons = service.get_buttons()

        assert buttons == []


class TestGetTextFields:
    """Tests for get_text_fields() method."""

    def test_get_text_fields_returns_edittext_elements(self):
        """get_text_fields() should return EditText elements."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.clickable_elements = [
            {"index": 0, "className": "android.widget.EditText"},
            {"index": 1, "className": "android.widget.TextView"},
            {"index": 2, "className": "android.widget.EditText"},
        ]

        fields = service.get_text_fields()

        assert len(fields) == 2
        assert fields[0]["index"] == 0
        assert fields[1]["index"] == 2

    def test_get_text_fields_returns_empty_when_none(self):
        """get_text_fields() should return empty list when no text fields."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.clickable_elements = [
            {"index": 0, "className": "android.widget.Button"},
        ]

        fields = service.get_text_fields()

        assert fields == []


class TestGetImageViews:
    """Tests for get_image_views() method."""

    def test_get_image_views_returns_imageview_elements(self):
        """get_image_views() should return ImageView elements."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.clickable_elements = [
            {"index": 0, "className": "android.widget.ImageView"},
            {"index": 1, "className": "android.widget.TextView"},
            {"index": 2, "className": "android.widget.ImageView"},
        ]

        images = service.get_image_views()

        assert len(images) == 2
        assert images[0]["index"] == 0
        assert images[1]["index"] == 2

    def test_get_image_views_returns_empty_when_none(self):
        """get_image_views() should return empty list when no image views."""
        from wecom_automation.core.config import Config
        from wecom_automation.services.adb_service import ADBService

        config = Config()
        service = ADBService(config)

        service._cache.clickable_elements = [
            {"index": 0, "className": "android.widget.Button"},
        ]

        images = service.get_image_views()

        assert images == []
