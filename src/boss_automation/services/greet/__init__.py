"""Greet executor and supporting machinery for BOSS Zhipin.

Public surface:
- ``QuotaGuard``: per-day / per-hour / per-job send caps.
- ``GreetSchedule`` + ``is_within_window``: time-of-day and weekday
  windowing, including cross-midnight windows.
- ``GreetExecutor``: orchestration of one greet attempt with full
  state-machine awareness (already-greeted, quota-exhausted,
  risk-control, etc.).
"""

from __future__ import annotations
