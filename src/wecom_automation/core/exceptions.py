"""
Custom exception classes for WeCom Automation.

This module defines a hierarchy of exceptions for better error handling,
debugging, and monitoring. Each exception includes context information
that can be used for logging and troubleshooting.
"""

from __future__ import annotations

from typing import Any


class WeComAutomationError(Exception):
    """
    Base exception for all WeCom Automation errors.

    All custom exceptions in this package inherit from this class,
    making it easy to catch all automation-related errors.

    Attributes:
        message: Human-readable error message
        context: Additional context data for debugging
        original_error: The original exception that caused this error, if any
    """

    def __init__(
        self,
        message: str,
        context: dict[str, Any] | None = None,
        original_error: Exception | None = None,
    ):
        self.message = message
        self.context = context or {}
        self.original_error = original_error
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        """Format the exception message with context."""
        parts = [self.message]
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            parts.append(f"[{context_str}]")
        if self.original_error:
            parts.append(f"(caused by: {self.original_error})")
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for logging/serialization."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "context": self.context,
            "original_error": str(self.original_error) if self.original_error else None,
        }


class DeviceConnectionError(WeComAutomationError):
    """
    Raised when there's an issue connecting to the Android device.

    This could be due to:
    - Device not connected
    - ADB daemon not running
    - USB debugging not enabled
    - Device serial number not found
    """

    def __init__(
        self,
        message: str = "Failed to connect to device",
        serial: str | None = None,
        **kwargs,
    ):
        context = kwargs.pop("context", {})
        if serial:
            context["serial"] = serial
        super().__init__(message, context=context, **kwargs)


class UIElementNotFoundError(WeComAutomationError):
    """
    Raised when a required UI element cannot be found.

    This helps diagnose issues with:
    - Changed app UI layout
    - Elements not loaded yet
    - Wrong screen/state
    """

    def __init__(
        self,
        message: str = "UI element not found",
        element_description: str | None = None,
        search_patterns: list | None = None,
        **kwargs,
    ):
        context = kwargs.pop("context", {})
        if element_description:
            context["element"] = element_description
        if search_patterns:
            context["patterns"] = search_patterns
        super().__init__(message, context=context, **kwargs)


class TimeoutError(WeComAutomationError):
    """
    Raised when an operation times out.

    Includes information about:
    - What operation timed out
    - How long it waited
    - Expected vs actual state
    """

    def __init__(
        self,
        message: str = "Operation timed out",
        operation: str | None = None,
        timeout_seconds: float | None = None,
        **kwargs,
    ):
        context = kwargs.pop("context", {})
        if operation:
            context["operation"] = operation
        if timeout_seconds is not None:
            context["timeout_seconds"] = timeout_seconds
        super().__init__(message, context=context, **kwargs)


class AppNotRunningError(WeComAutomationError):
    """Raised when WeCom app is not running or not in expected state."""

    def __init__(
        self,
        message: str = "WeCom app is not running or not in expected state",
        expected_state: str | None = None,
        actual_state: str | None = None,
        **kwargs,
    ):
        context = kwargs.pop("context", {})
        if expected_state:
            context["expected_state"] = expected_state
        if actual_state:
            context["actual_state"] = actual_state
        super().__init__(message, context=context, **kwargs)


class NavigationError(WeComAutomationError):
    """Raised when navigation to a specific screen/state fails."""

    def __init__(
        self,
        message: str = "Navigation failed",
        target: str | None = None,
        current_state: str | None = None,
        **kwargs,
    ):
        context = kwargs.pop("context", {})
        if target:
            context["target"] = target
        if current_state:
            context["current_state"] = current_state
        super().__init__(message, context=context, **kwargs)


class DataExtractionError(WeComAutomationError):
    """Raised when data extraction from UI fails."""

    def __init__(
        self,
        message: str = "Failed to extract data from UI",
        extraction_type: str | None = None,
        partial_data: dict[str, Any] | None = None,
        **kwargs,
    ):
        context = kwargs.pop("context", {})
        if extraction_type:
            context["extraction_type"] = extraction_type
        if partial_data:
            context["partial_data"] = partial_data
        super().__init__(message, context=context, **kwargs)


class SkipUserException(WeComAutomationError):
    """
    Raised when the user requests to skip the current customer sync.
    """

    def __init__(self, message: str = "Skipping current user by request", **kwargs):
        super().__init__(message, **kwargs)


class DeviceDisconnectedError(WeComAutomationError):
    """
    Raised when the device is disconnected during an operation.

    This error should trigger:
    - Immediate stop of the current operation
    - Checkpoint saving for recovery
    """

    def __init__(
        self,
        message: str = "Device disconnected",
        serial: str | None = None,
        operation: str | None = None,
        **kwargs,
    ):
        context = kwargs.pop("context", {})
        if serial:
            context["serial"] = serial
        if operation:
            context["operation"] = operation
        super().__init__(message, context=context, **kwargs)


def is_device_disconnected_error(error: Exception) -> bool:
    """
    Check if an error indicates device disconnection.

    Args:
        error: The exception to check

    Returns:
        True if the error indicates the device is disconnected
    """
    if isinstance(error, DeviceDisconnectedError):
        return True

    error_str = str(error).lower()

    # Common device disconnection error patterns
    patterns = [
        "device" in error_str and "not found" in error_str,
        "device" in error_str and "offline" in error_str,
        "no devices/emulators found" in error_str,
        "error: closed" in error_str,
        "cannot connect" in error_str,
        "connection refused" in error_str,
    ]

    return any(patterns)
