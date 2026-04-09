"""
Follow-up 数据模型

定义 Follow-up 系统使用的数据结构。

Note: 仅保留 Phase 1（实时回复）相关模型。
Phase 2（补刀）模型已移除，未来将在新的补刀系统中重新设计。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ScanResult:
    """扫描结果"""

    scan_time: datetime
    candidates_found: int
    followups_sent: int
    followups_failed: int
    errors: list[str] = field(default_factory=list)
    details: list[dict[str, Any]] = field(default_factory=list)


# FollowUpAttempt model removed - now managed by followup_manage.py router
# which defines its own Pydantic model for API responses
