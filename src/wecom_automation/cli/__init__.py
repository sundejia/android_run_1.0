"""
CLI module for WeCom Automation.

Provides command-line interface commands for:
- Launching WeCom
- Switching to Private Chats
- Extracting user details
- Running the full workflow
"""

from wecom_automation.cli.commands import main, run_workflow

__all__ = ["main", "run_workflow"]
