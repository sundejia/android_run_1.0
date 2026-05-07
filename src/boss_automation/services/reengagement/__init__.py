"""Re-engagement (复聊跟进) services for the BOSS Zhipin pivot.

This subpackage owns the detector that finds silent candidates and
the orchestrator that drives one re-engagement attempt at a time. All
modules here are pure-Python (no ADB / DroidRun import) so they remain
testable without devices.
"""

from __future__ import annotations
