"""
Path utilities for consistent project root resolution.

This module provides a convenient wrapper around the project-wide
get_project_root() function from wecom_automation.core.config.

It ensures that all backend code can consistently access the project root
without hardcoding parent path chains.
"""

from pathlib import Path

# Import the canonical get_project_root from the main package
from wecom_automation.core.config import get_project_root


__all__ = ["get_project_root"]
