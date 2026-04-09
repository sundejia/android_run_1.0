"""
Unit tests for custom exceptions.
"""

from wecom_automation.core.exceptions import (
    AppNotRunningError,
    DataExtractionError,
    DeviceConnectionError,
    NavigationError,
    TimeoutError,
    UIElementNotFoundError,
    WeComAutomationError,
)


class TestWeComAutomationError:
    """Tests for base exception class."""

    def test_basic_message(self):
        """Test basic error with just a message."""
        error = WeComAutomationError("Something went wrong")
        assert str(error) == "Something went wrong"
        assert error.message == "Something went wrong"

    def test_with_context(self):
        """Test error with context."""
        error = WeComAutomationError(
            "Operation failed",
            context={"step": "login", "attempt": 3},
        )
        error_str = str(error)
        assert "Operation failed" in error_str
        assert "step=login" in error_str
        assert "attempt=3" in error_str

    def test_with_original_error(self):
        """Test error wrapping another exception."""
        original = ValueError("Invalid value")
        error = WeComAutomationError(
            "Wrapped error",
            original_error=original,
        )
        error_str = str(error)
        assert "Wrapped error" in error_str
        assert "caused by:" in error_str
        assert "Invalid value" in error_str

    def test_to_dict(self):
        """Test converting error to dictionary."""
        original = RuntimeError("Inner error")
        error = WeComAutomationError(
            "Test error",
            context={"key": "value"},
            original_error=original,
        )
        d = error.to_dict()
        assert d["error_type"] == "WeComAutomationError"
        assert d["message"] == "Test error"
        assert d["context"] == {"key": "value"}
        assert "Inner error" in d["original_error"]


class TestDeviceConnectionError:
    """Tests for DeviceConnectionError."""

    def test_default_message(self):
        """Test default error message."""
        error = DeviceConnectionError()
        assert "Failed to connect to device" in str(error)

    def test_with_serial(self):
        """Test error with device serial."""
        error = DeviceConnectionError(
            "Cannot connect",
            serial="emulator-5554",
        )
        error_str = str(error)
        assert "Cannot connect" in error_str
        assert "serial=emulator-5554" in error_str

    def test_custom_context(self):
        """Test with additional context."""
        error = DeviceConnectionError(
            "Device offline",
            serial="123ABC",
            context={"usb_connected": False},
        )
        d = error.to_dict()
        assert d["context"]["serial"] == "123ABC"
        assert d["context"]["usb_connected"] is False


class TestUIElementNotFoundError:
    """Tests for UIElementNotFoundError."""

    def test_default_message(self):
        """Test default error message."""
        error = UIElementNotFoundError()
        assert "UI element not found" in str(error)

    def test_with_element_description(self):
        """Test error with element description."""
        error = UIElementNotFoundError(
            "Could not locate button",
            element_description="Submit button",
        )
        error_str = str(error)
        assert "Could not locate button" in error_str
        assert "element=Submit button" in error_str

    def test_with_patterns(self):
        """Test error with search patterns."""
        error = UIElementNotFoundError(
            "Element not found",
            search_patterns=["Private Chats", "私聊"],
        )
        d = error.to_dict()
        assert d["context"]["patterns"] == ["Private Chats", "私聊"]


class TestTimeoutError:
    """Tests for TimeoutError."""

    def test_default_message(self):
        """Test default error message."""
        error = TimeoutError()
        assert "Operation timed out" in str(error)

    def test_with_details(self):
        """Test error with operation details."""
        error = TimeoutError(
            "Waiting for UI element",
            operation="find_element",
            timeout_seconds=30.0,
        )
        error_str = str(error)
        assert "Waiting for UI element" in error_str
        assert "operation=find_element" in error_str
        assert "timeout_seconds=30.0" in error_str


class TestAppNotRunningError:
    """Tests for AppNotRunningError."""

    def test_default_message(self):
        """Test default error message."""
        error = AppNotRunningError()
        assert "not running" in str(error).lower()

    def test_with_states(self):
        """Test error with expected and actual state."""
        error = AppNotRunningError(
            "App not in expected state",
            expected_state="Messages tab",
            actual_state="Login screen",
        )
        d = error.to_dict()
        assert d["context"]["expected_state"] == "Messages tab"
        assert d["context"]["actual_state"] == "Login screen"


class TestNavigationError:
    """Tests for NavigationError."""

    def test_default_message(self):
        """Test default error message."""
        error = NavigationError()
        assert "Navigation failed" in str(error)

    def test_with_target(self):
        """Test error with navigation target."""
        error = NavigationError(
            "Could not navigate",
            target="Private Chats",
            current_state="Messages tab - All",
        )
        d = error.to_dict()
        assert d["context"]["target"] == "Private Chats"
        assert d["context"]["current_state"] == "Messages tab - All"


class TestDataExtractionError:
    """Tests for DataExtractionError."""

    def test_default_message(self):
        """Test default error message."""
        error = DataExtractionError()
        assert "Failed to extract data" in str(error)

    def test_with_partial_data(self):
        """Test error with partial extraction data."""
        error = DataExtractionError(
            "Incomplete extraction",
            extraction_type="user_list",
            partial_data={"extracted": 5, "expected": 10},
        )
        d = error.to_dict()
        assert d["context"]["extraction_type"] == "user_list"
        assert d["context"]["partial_data"]["extracted"] == 5
