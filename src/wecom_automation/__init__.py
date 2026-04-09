"""
WeCom Automation - A modular automation framework for WeCom on Android.

This package provides tools for automating WeCom (Enterprise WeChat) on Android devices
using the DroidRun library's non-LLM APIs.
"""

__version__ = "0.2.0"
__author__ = "WeCom Automation Team"

from wecom_automation.core.config import Config
from wecom_automation.core.exceptions import (
    DeviceConnectionError,
    TimeoutError,
    UIElementNotFoundError,
    WeComAutomationError,
)
from wecom_automation.core.models import AvatarInfo, KefuInfo, MessageEntry, UserDetail

__all__ = [
    "Config",
    "MessageEntry",
    "AvatarInfo",
    "KefuInfo",
    "UserDetail",
    "WeComAutomationError",
    "DeviceConnectionError",
    "UIElementNotFoundError",
    "TimeoutError",
]
