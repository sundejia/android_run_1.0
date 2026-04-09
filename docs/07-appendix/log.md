# 日志分析系统 - 数据收集实现方案

## 概述

本文档描述如何在程序运行过程中收集业务指标数据并写入结构化日志，供后续日志分析系统使用。

---

## 1. 监控指标体系

### 1.1 三层监控金字塔

#### L1 汇总级别 - 每日整体业务健康度

| 指标           | 字段名                                     | 说明                      |
| -------------- | ------------------------------------------ | ------------------------- |
| 消息处理总量   | `total_messages`                           | 新增/去重消息数           |
| AI回复生成数   | `ai_replies_generated` / `ai_replies_sent` | 生成和实际发送的AI回复    |
| 客户互动率     | `engagement_rate`                          | 有回复的客户数 / 总客户数 |
| 黑名单新增数   | `blacklist_additions`                      | 新增黑名单用户数          |
| 用户删除检测数 | `user_deleted_detected`                    | 检测到用户删除的数量      |
| 系统错误率     | `error_rate`                               | 错误数 / 总操作数         |
| 平均响应时间   | `avg_response_time_ms`                     | AI响应平均耗时            |

#### L2 客户级别 - 单客户互动质量

| 指标           | 字段名                  | 说明           |
| -------------- | ----------------------- | -------------- |
| 客户名称       | `customer_name`         | 客户唯一标识   |
| 消息总数       | `message_count`         | 累计消息数     |
| AI回复数       | `ai_reply_count`        | AI生成的回复数 |
| 对话轮次       | `conversation_rounds`   | 你来我往算一轮 |
| 最后互动时间   | `last_interaction_time` | 最后消息时间   |
| 是否被拉黑     | `is_blacklisted`        | 黑名单状态     |
| 是否删除关系   | `is_deleted`            | 用户是否删除   |
| 客户活跃度评分 | `activity_score`        | 0-100综合评分  |

#### L3 消息级别 - 单条消息处理详情

| 指标             | 字段名                   | 说明                     |
| ---------------- | ------------------------ | ------------------------ |
| 消息数据库ID     | `message_db_id`          | 数据库中的消息主键       |
| 回复关联ID       | `reply_to_message_db_id` | 这条回复是针对哪条消息的 |
| 客户数据库ID     | `customer_db_id`         | 客户在数据库中的ID       |
| 消息ID           | `message_id`             | 唯一标识                 |
| 客户             | `customer_name`          | 所属客户                 |
| 消息类型         | `message_type`           | text/image/voice/video   |
| 发送方           | `sender`                 | customer/kefu            |
| AI是否生成回复   | `ai_generated`           | 是否触发AI               |
| AI回复内容长度   | `ai_reply_length`        | 回复字符数               |
| 回复发送成功     | `reply_sent_success`     | 发送结果                 |
| 客户是否跟进回复 | `customer_followed_up`   | 客户后续是否回复         |
| 处理耗时         | `processing_duration_ms` | 毫秒                     |
| 错误信息         | `error_message`          | 如有错误                 |

#### L4 对话记录级别 - 完整聊天上下文

| 指标             | 字段名                  | 说明                           |
| ---------------- | ----------------------- | ------------------------------ |
| 客户数据库ID     | `customer_db_id`        | 客户在数据库中的ID             |
| 客户名称         | `customer_name`         | 客户名                         |
| 当天消息IDs      | `today_message_db_ids`  | 当天所有消息的数据库ID列表     |
| 当天消息数       | `today_message_count`   | 当天消息总数                   |
| 当天AI回复IDs    | `today_ai_reply_db_ids` | AI生成的回复的数据库ID         |
| 当天AI回复数     | `today_ai_reply_count`  | AI回复数量                     |
| 对话线索         | `conversation_thread`   | 消息ID链（客户发->AI回->...)） |
| 完整聊天记录快照 | `conversation_snapshot` | 包含最近N条消息的快照          |

---

## 2. 结构化日志格式

### 2.1 日志行格式

采用 **JSON Lines** 格式，每行一个JSON对象，便于后续解析：

```json
{"timestamp": "2026-01-21T17:38:20.123+08:00", "level": "METRIC", "event": "message_processed", "data": {...}}
```

### 2.2 统一日志结构

```python
{
    "timestamp": "ISO8601格式",
    "level": "METRIC",           # 专用级别，区分业务日志
    "event": "事件类型",
    "session_id": "会话ID",      # 关联同一次处理流程
    "device_serial": "设备ID",
    "data": {
        # 具体指标数据
    }
}
```

### 2.3 事件类型定义

| event 值               | 触发时机       | 数据内容                      |
| ---------------------- | -------------- | ----------------------------- |
| `message_received`     | 收到新消息     | L3 消息级别数据               |
| `message_processed`    | 消息处理完成   | L3 + 处理结果 + 数据库ID      |
| `ai_reply_generated`   | AI生成回复     | AI相关指标 + 回复关联的消息ID |
| `reply_sent`           | 回复发送完成   | 发送结果 + 回复数据库ID       |
| `customer_updated`     | 客户状态变更   | L2 客户级别数据               |
| `conversation_context` | 对话完成时     | L4 完整聊天记录快照           |
| `blacklist_added`      | 加入黑名单     | 黑名单原因                    |
| `user_deleted`         | 检测到用户删除 | 删除详情                      |
| `session_summary`      | 会话结束汇总   | L1 汇总数据                   |
| `error_occurred`       | 发生错误       | 错误详情                      |

#### 2.3.1 新增错误子类型 (2026-04-09)

`error_occurred` 事件的 `error_type` 字段现已覆盖所有 AI 失败路径：

| `error_type`              | 含义                        | 触发条件                                         |
| ------------------------- | --------------------------- | ------------------------------------------------ |
| `ai_no_reply`             | AI 返回 None，客户未获回复  | `_process_unread_user_with_wait` 中 `reply=None` |
| `ai_no_reply_interactive` | 交互等待循环中 AI 返回 None | `_interactive_wait_loop` 中 `reply=None`         |
| `ai_circuit_open`         | AI 熔断器打开，跳过调用     | 连续 3 次 AI 失败后                              |
| `ai_timeout`              | AI 请求超时                 | `_generate_reply` 中 `TimeoutError`              |
| `ai_connection_error`     | AI 连接/网络错误            | `_generate_reply` 中其他异常                     |
| `ai_http_error`           | AI 返回非 200 HTTP 状态码   | `_generate_reply` 中 `response.status != 200`    |
| `ai_empty_reply`          | AI 返回空字符串             | `_generate_reply` 中回复为空                     |
| `ai_human_transfer`       | AI 请求转人工               | AI 回复含 "command back to user operation"       |
| `click_failed`            | 点击进入聊天失败            | `click_user_in_list` 返回 False                  |
| `click_cooldown_skip`     | 点击冷却期内跳过            | 该客户最近点击失败，仍在冷却中                   |

#### 2.3.2 监控服务事件 (2026-04-09)

独立于 MetricsLogger JSONL，以下数据写入 `monitoring.db` SQLite 数据库：

| 表名               | 写入时机           | 主要字段                                                                                           |
| ------------------ | ------------------ | -------------------------------------------------------------------------------------------------- |
| `heartbeats`       | 每次 scan 循环开始 | `device_serial`, `scan_number`, `status`, `scan_duration_ms`, `customers_in_queue`                 |
| `ai_health_checks` | 每 5 分钟          | `ai_server_url`, `status`, `response_time_ms`, `network`, `http_service`, `inference`, `diagnosis` |
| `process_events`   | 进程启动/停止      | `device_serial`, `event_type`, `scan_count`, `uptime_seconds`, `exit_reason`                       |

API 端点：`GET /api/monitoring/heartbeats`, `/heartbeats/latest`, `/ai-health`, `/process-events`。

---

## 3. 实现方案

### 3.1 新建 MetricsLogger 模块

**文件**: `src/wecom_automation/core/metrics_logger.py`

```python
"""
业务指标日志记录器

专门用于收集和记录业务指标，采用JSON Lines格式输出。
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import dataclass, asdict
from logging.handlers import TimedRotatingFileHandler
import uuid


@dataclass
class MetricEvent:
    """指标事件"""
    timestamp: str
    level: str
    event: str
    session_id: str
    device_serial: str
    data: Dict[str, Any]


class MetricsLogger:
    """业务指标日志记录器"""

    def __init__(
        self,
        log_dir: Optional[Path] = None,
        device_serial: str = "unknown",
    ):
        self._device_serial = device_serial
        self._session_id = str(uuid.uuid4())[:8]

        # 确定日志目录
        if log_dir is None:
            from wecom_automation.core.config import get_project_root
            log_dir = get_project_root() / "logs" / "metrics"

        log_dir.mkdir(parents=True, exist_ok=True)

        # 创建专用Logger
        self._logger = logging.getLogger(f"metrics.{device_serial}")
        self._logger.setLevel(logging.INFO)
        self._logger.handlers.clear()

        # 文件Handler - JSON Lines 格式
        log_file = log_dir / "metrics.jsonl"
        handler = TimedRotatingFileHandler(
            log_file,
            when="midnight",
            backupCount=0,  # 永久保留
            encoding="utf-8",
        )
        handler.suffix = "%Y-%m-%d"
        handler.setFormatter(logging.Formatter("%(message)s"))  # 只输出消息本身
        self._logger.addHandler(handler)

        # 统计计数器
        self._counters = {
            "messages_added": 0,
            "messages_skipped": 0,
            "ai_replies_generated": 0,
            "ai_replies_sent": 0,
            "ai_replies_failed": 0,
            "blacklist_additions": 0,
            "user_deleted_detected": 0,
            "errors": 0,
            "customers_processed": set(),
            "customers_engaged": set(),  # 有回复的客户
        }

        self._start_time = datetime.now()

    def _emit(self, event: str, data: Dict[str, Any]) -> None:
        """输出一条指标日志"""
        metric = MetricEvent(
            timestamp=datetime.now().isoformat(),
            level="METRIC",
            event=event,
            session_id=self._session_id,
            device_serial=self._device_serial,
            data=data,
        )
        self._logger.info(json.dumps(asdict(metric), ensure_ascii=False))

    # =========================================================================
    # L3 消息级别事件
    # =========================================================================

    def log_message_received(
        self,
        customer_name: str,
        message_type: str,
        sender: str,
        content_length: int = 0,
    ) -> None:
        """记录收到消息"""
        self._emit("message_received", {
            "customer_name": customer_name,
            "message_type": message_type,
            "sender": sender,
            "content_length": content_length,
        })

    def log_message_processed(
        self,
        customer_db_id: int,
        customer_name: str,
        message_db_id: int,  # 消息在数据库中的ID
        message_type: str,
        sender: str,
        added: bool,
        processing_duration_ms: float,
        ai_generated: bool = False,
        ai_reply_length: int = 0,
        ai_reply_db_id: Optional[int] = None,  # AI回复的数据库ID
        reply_to_message_db_id: Optional[int] = None,  # 回复的是哪条消息
        reply_sent_success: bool = False,
        error_message: Optional[str] = None,
    ) -> None:
        """记录消息处理完成"""
        if added:
            self._counters["messages_added"] += 1
        else:
            self._counters["messages_skipped"] += 1

        self._counters["customers_processed"].add(customer_name)

        if ai_generated:
            self._counters["ai_replies_generated"] += 1
            if reply_sent_success:
                self._counters["ai_replies_sent"] += 1
                self._counters["customers_engaged"].add(customer_name)
            else:
                self._counters["ai_replies_failed"] += 1

        if error_message:
            self._counters["errors"] += 1

        self._emit("message_processed", {
            "customer_db_id": customer_db_id,
            "customer_name": customer_name,
            "message_db_id": message_db_id,
            "message_type": message_type,
            "sender": sender,
            "added": added,
            "processing_duration_ms": processing_duration_ms,
            "ai_generated": ai_generated,
            "ai_reply_length": ai_reply_length,
            "ai_reply_db_id": ai_reply_db_id,
            "reply_to_message_db_id": reply_to_message_db_id,
            "reply_sent_success": reply_sent_success,
            "error_message": error_message,
        })

    def log_ai_reply_generated(
        self,
        customer_db_id: int,
        customer_name: str,
        reply_to_message_db_id: int,  # 回复的是哪条消息
        reply_content: str,
        generation_time_ms: float,
    ) -> None:
        """记录AI回复生成"""
        self._emit("ai_reply_generated", {
            "customer_db_id": customer_db_id,
            "customer_name": customer_name,
            "reply_to_message_db_id": reply_to_message_db_id,
            "reply_length": len(reply_content),
            "generation_time_ms": generation_time_ms,
        })

    def log_reply_sent(
        self,
        customer_name: str,
        success: bool,
        method: str,  # "sidecar" or "direct"
        reply_db_id: Optional[int] = None,  # 回复消息的数据库ID
        error: Optional[str] = None,
    ) -> None:
        """记录回复发送结果"""
        self._emit("reply_sent", {
            "customer_name": customer_name,
            "success": success,
            "method": method,
            "reply_db_id": reply_db_id,
            "error": error,
        })

    # =========================================================================
    # L2 客户级别事件
    # =========================================================================

    def log_customer_updated(
        self,
        customer_db_id: int,
        customer_name: str,
        channel: Optional[str],
        message_count: int,
        ai_reply_count: int,
        is_blacklisted: bool,
        is_deleted: bool,
    ) -> None:
        """记录客户状态更新"""
        self._emit("customer_updated", {
            "customer_db_id": customer_db_id,
            "customer_name": customer_name,
            "channel": channel,
            "message_count": message_count,
            "ai_reply_count": ai_reply_count,
            "is_blacklisted": is_blacklisted,
            "is_deleted": is_deleted,
        })

    def log_blacklist_added(
        self,
        customer_db_id: Optional[int],
        customer_name: str,
        channel: Optional[str],
        reason: str,
        deleted_by_user: bool = False,
    ) -> None:
        """记录加入黑名单"""
        self._counters["blacklist_additions"] += 1

        self._emit("blacklist_added", {
            "customer_db_id": customer_db_id,
            "customer_name": customer_name,
            "channel": channel,
            "reason": reason,
            "deleted_by_user": deleted_by_user,
        })

    def log_user_deleted(
        self,
        customer_db_id: Optional[int],
        customer_name: str,
        channel: Optional[str],
        detected_message: str,
    ) -> None:
        """记录检测到用户删除"""
        self._counters["user_deleted_detected"] += 1

        self._emit("user_deleted", {
            "customer_db_id": customer_db_id,
            "customer_name": customer_name,
            "channel": channel,
            "detected_message": detected_message,
        })

    # =========================================================================
    # L4 对话记录级别事件
    # =========================================================================

    def log_conversation_context(
        self,
        customer_db_id: int,
        customer_name: str,
        channel: Optional[str],
        today_message_db_ids: List[int],
        today_ai_reply_db_ids: List[int],
        conversation_thread: List[Dict[str, Any]],
        conversation_snapshot: List[Dict[str, Any]],
    ) -> None:
        """
        记录完整对话上下文

        在处理完一个客户后调用，记录当天的完整聊天记录ID链。

        Args:
            customer_db_id: 客户数据库ID
            customer_name: 客户名称
            channel: 渠道
            today_message_db_ids: 当天所有消息的数据库ID列表
            today_ai_reply_db_ids: 当天AI回复的数据库ID列表
            conversation_thread: 对话线索 [{"db_id": 1, "sender": "customer"}, {"db_id": 2, "sender": "kefu"}, ...]
            conversation_snapshot: 最近N条消息快照 [{"db_id": 1, "sender": "customer", "content": "...", "type": "text"}, ...]
        """
        self._emit("conversation_context", {
            "customer_db_id": customer_db_id,
            "customer_name": customer_name,
            "channel": channel,
            "today_message_count": len(today_message_db_ids),
            "today_message_db_ids": today_message_db_ids,
            "today_ai_reply_count": len(today_ai_reply_db_ids),
            "today_ai_reply_db_ids": today_ai_reply_db_ids,
            "conversation_thread": conversation_thread,
            "conversation_snapshot": conversation_snapshot,
        })

    # =========================================================================
    # L1 汇总级别事件
    # =========================================================================

    def log_session_summary(self) -> None:
        """记录会话结束汇总"""
        duration = (datetime.now() - self._start_time).total_seconds()
        total_messages = self._counters["messages_added"] + self._counters["messages_skipped"]
        total_customers = len(self._counters["customers_processed"])
        engaged_customers = len(self._counters["customers_engaged"])

        self._emit("session_summary", {
            "duration_seconds": duration,
            "total_messages": total_messages,
            "messages_added": self._counters["messages_added"],
            "messages_skipped": self._counters["messages_skipped"],
            "ai_replies_generated": self._counters["ai_replies_generated"],
            "ai_replies_sent": self._counters["ai_replies_sent"],
            "ai_replies_failed": self._counters["ai_replies_failed"],
            "blacklist_additions": self._counters["blacklist_additions"],
            "user_deleted_detected": self._counters["user_deleted_detected"],
            "errors": self._counters["errors"],
            "total_customers": total_customers,
            "engaged_customers": engaged_customers,
            "engagement_rate": engaged_customers / total_customers if total_customers > 0 else 0,
        })

    def log_error(
        self,
        error_type: str,
        error_message: str,
        customer_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """记录错误"""
        self._counters["errors"] += 1

        self._emit("error_occurred", {
            "error_type": error_type,
            "error_message": error_message,
            "customer_name": customer_name,
            "context": context or {},
        })


# 全局实例管理
_metrics_loggers: Dict[str, MetricsLogger] = {}


def get_metrics_logger(device_serial: str = "default") -> MetricsLogger:
    """获取指定设备的指标记录器"""
    if device_serial not in _metrics_loggers:
        _metrics_loggers[device_serial] = MetricsLogger(device_serial=device_serial)
    return _metrics_loggers[device_serial]
```

---

## 4. 埋点位置

### 4.1 FollowUp Response Detector 埋点

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`

| 位置                                  | 埋点方法                 | 触发条件             |
| ------------------------------------- | ------------------------ | -------------------- |
| `_process_unread_user_with_wait` 开始 | -                        | 日志上下文初始化     |
| 消息提取后                            | `log_message_received`   | 每条新消息           |
| 消息存储后                            | `log_message_processed`  | 消息处理完成         |
| AI回复生成后                          | `log_ai_reply_generated` | AI生成回复           |
| 回复发送后                            | `log_reply_sent`         | 发送成功/失败        |
| 检测到用户删除                        | `log_user_deleted`       | 系统消息匹配         |
| 加入黑名单                            | `log_blacklist_added`    | 调用BlacklistService |
| 处理完毕                              | `log_customer_updated`   | 退出对话前           |

#### 代码示例

```python
# 在 _process_unread_user_with_wait 方法中

from wecom_automation.core.metrics_logger import get_metrics_logger

async def _process_unread_user_with_wait(self, wecom, serial, unread_user, ...):
    metrics = get_metrics_logger(serial)
    start_time = time.time()

    # ... 现有代码 ...

    # 消息提取后
    for msg in messages:
        metrics.log_message_received(
            customer_name=user_name,
            message_type=getattr(msg, 'message_type', 'text'),
            sender='customer' if not getattr(msg, 'is_self', False) else 'kefu',
            content_length=len(getattr(msg, 'content', '') or ''),
        )

    # 消息存储后
    processing_time = (time.time() - start_time) * 1000
    metrics.log_message_processed(
        customer_name=user_name,
        message_type="text",
        sender="customer",
        added=True,
        processing_duration_ms=processing_time,
        ai_generated=bool(reply),
        ai_reply_length=len(reply) if reply else 0,
        reply_sent_success=success,
    )

    # 检测到用户删除
    if self._wecom.ui_parser.is_user_deleted_message(content):
        metrics.log_user_deleted(
            customer_name=user_name,
            channel=user_channel,
            detected_message=content,
        )
```

### 4.2 Sync 流程埋点

**文件**: `src/wecom_automation/services/sync/customer_syncer.py`

| 位置         | 埋点方法                 | 触发条件           |
| ------------ | ------------------------ | ------------------ |
| 消息处理循环 | `log_message_processed`  | 每条消息处理后     |
| AI回复后     | `log_ai_reply_generated` | AI生成回复         |
| 回复发送后   | `log_reply_sent`         | Sidecar/Direct发送 |
| sync方法结束 | `log_customer_updated`   | 客户同步完成       |

### 4.3 BlacklistService 埋点

**文件**: `src/wecom_automation/services/blacklist_service.py`

```python
def add_to_blacklist(self, device_serial, customer_name, ...):
    # 现有逻辑...

    # 新增埋点
    from wecom_automation.core.metrics_logger import get_metrics_logger
    metrics = get_metrics_logger(device_serial)
    metrics.log_blacklist_added(
        customer_name=customer_name,
        channel=customer_channel,
        reason=reason,
        deleted_by_user=deleted_by_user,
    )
```

### 4.4 会话结束汇总

**文件**: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`

在 `scan_for_responses` 方法结束时：

```python
async def scan_for_responses(self, ...):
    metrics = get_metrics_logger(device_serial or "all")

    try:
        # ... 现有扫描逻辑 ...
        pass
    finally:
        # 无论成功失败都输出汇总
        metrics.log_session_summary()
```

---

## 5. 日志文件示例

### 5.1 文件位置

```
项目根目录/
├── logs/
│   └── metrics/
│       ├── metrics.jsonl              # 当天日志
│       ├── metrics.jsonl.2026-01-20   # 历史日志
│       └── metrics.jsonl.2026-01-19
```

### 5.2 日志内容示例

#### 消息处理流程（带数据库ID）

```json
{"timestamp": "2026-01-21T17:38:20.123+08:00", "level": "METRIC", "event": "message_received", "session_id": "a1b2c3d4", "device_serial": "AN2FVB1706003302", "data": {"customer_name": "张三", "message_type": "text", "sender": "customer", "content_length": 28}}

{"timestamp": "2026-01-21T17:38:21.456+08:00", "level": "METRIC", "event": "ai_reply_generated", "session_id": "a1b2c3d4", "device_serial": "AN2FVB1706003302", "data": {"customer_db_id": 42, "customer_name": "张三", "reply_to_message_db_id": 1001, "reply_length": 45, "generation_time_ms": 1200.5}}

{"timestamp": "2026-01-21T17:38:22.789+08:00", "level": "METRIC", "event": "reply_sent", "session_id": "a1b2c3d4", "device_serial": "AN2FVB1706003302", "data": {"customer_name": "张三", "success": true, "method": "sidecar", "reply_db_id": 1002, "error": null}}

{"timestamp": "2026-01-21T17:38:23.012+08:00", "level": "METRIC", "event": "message_processed", "session_id": "a1b2c3d4", "device_serial": "AN2FVB1706003302", "data": {"customer_db_id": 42, "customer_name": "张三", "message_db_id": 1001, "message_type": "text", "sender": "customer", "added": true, "processing_duration_ms": 2889.0, "ai_generated": true, "ai_reply_length": 45, "ai_reply_db_id": 1002, "reply_to_message_db_id": 1001, "reply_sent_success": true, "error_message": null}}
```

#### 完整对话上下文记录

```json
{
  "timestamp": "2026-01-21T17:38:25.000+08:00",
  "level": "METRIC",
  "event": "conversation_context",
  "session_id": "a1b2c3d4",
  "device_serial": "AN2FVB1706003302",
  "data": {
    "customer_db_id": 42,
    "customer_name": "张三",
    "channel": "@WeChat",
    "today_message_count": 6,
    "today_message_db_ids": [998, 999, 1000, 1001, 1002, 1003],
    "today_ai_reply_count": 2,
    "today_ai_reply_db_ids": [1000, 1002],
    "conversation_thread": [
      { "db_id": 998, "sender": "customer" },
      { "db_id": 999, "sender": "kefu" },
      { "db_id": 1000, "sender": "kefu" },
      { "db_id": 1001, "sender": "customer" },
      { "db_id": 1002, "sender": "kefu" },
      { "db_id": 1003, "sender": "customer" }
    ],
    "conversation_snapshot": [
      { "db_id": 998, "sender": "customer", "content": "你好，我想咨询一下", "type": "text" },
      { "db_id": 999, "sender": "kefu", "content": "您好，请问有什么可以帮您？", "type": "text" },
      {
        "db_id": 1000,
        "sender": "kefu",
        "content": "[AI] 欢迎咨询，请告诉我您的需求",
        "type": "text"
      },
      { "db_id": 1001, "sender": "customer", "content": "产品价格是多少？", "type": "text" },
      { "db_id": 1002, "sender": "kefu", "content": "[AI] 我们的产品价格...", "type": "text" },
      { "db_id": 1003, "sender": "customer", "content": "好的谢谢", "type": "text" }
    ]
  }
}
```

#### 用户删除和黑名单

```json
{"timestamp": "2026-01-21T17:40:00.000+08:00", "level": "METRIC", "event": "user_deleted", "session_id": "a1b2c3d4", "device_serial": "AN2FVB1706003302", "data": {"customer_db_id": 55, "customer_name": "李四", "channel": "@WeChat", "detected_message": "对方开启了联系人验证"}}

{"timestamp": "2026-01-21T17:40:01.000+08:00", "level": "METRIC", "event": "blacklist_added", "session_id": "a1b2c3d4", "device_serial": "AN2FVB1706003302", "data": {"customer_db_id": 55, "customer_name": "李四", "channel": "@WeChat", "reason": "User deleted/blocked", "deleted_by_user": true}}
```

#### 会话汇总

```json
{
  "timestamp": "2026-01-21T17:45:00.000+08:00",
  "level": "METRIC",
  "event": "session_summary",
  "session_id": "a1b2c3d4",
  "device_serial": "AN2FVB1706003302",
  "data": {
    "duration_seconds": 420.5,
    "total_messages": 25,
    "messages_added": 20,
    "messages_skipped": 5,
    "ai_replies_generated": 8,
    "ai_replies_sent": 7,
    "ai_replies_failed": 1,
    "blacklist_additions": 1,
    "user_deleted_detected": 1,
    "errors": 0,
    "total_customers": 10,
    "engaged_customers": 7,
    "engagement_rate": 0.7
  }
}
```

---

## 6. AI 服务器请求/响应日志

实时回复与补刀流程中，向 AI 服务器发起的请求与响应会写入设备维度的 followup 日志，便于排查与审计。

**位置**: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py`，方法 `_generate_reply` 内。

**请求日志**（每次调用前）:

- AI 服务器 URL、超时、会话 ID
- 系统提示词（system prompt）
- 用户提示词（user prompt）
- 对话上下文（最近若干条消息，角色 + 内容）

**响应日志**（收到 HTTP 响应后）:

- HTTP 状态码
- 成功时：完整响应 JSON、解析出的 AI 回复内容
- 非 200 时：响应 body 原文
- 超时/异常：超时时间、错误信息与 traceback

**日志输出**: 使用 logger `followup.response_detector`，写入 `lo../03-impl-and-arch/response_detector.log`（或项目配置的 followup 日志目录）。前端可通过设备维度的 WebSocket 日志流查看同一设备上的 AI 请求/响应摘要。

---

## 7. 任务清单

| 任务   | 文件                                          | 内容                                          |
| ------ | --------------------------------------------- | --------------------------------------------- |
| Task 1 | `src/wecom_automation/core/metrics_logger.py` | 创建 MetricsLogger 模块（含数据库ID支持）     |
| Task 2 | `response_detector.py`                        | 添加消息处理埋点（含数据库ID）                |
| Task 3 | `response_detector.py`                        | 添加AI回复埋点（含回复关联ID）                |
| Task 4 | `response_detector.py`                        | 添加对话上下文埋点 `log_conversation_context` |
| Task 5 | `response_detector.py`                        | 添加会话汇总埋点                              |
| Task 6 | `customer_syncer.py`                          | 添加Sync流程埋点（含数据库ID）                |
| Task 7 | `blacklist_service.py`                        | 添加黑名单埋点（含客户数据库ID）              |
| Task 8 | `scanner.py`                                  | 添加FollowUp Scanner埋点                      |
| Task 9 | `repository.py`                               | 确保消息存储返回数据库ID                      |

---

## 8. 后续分析系统接口

日志分析系统可通过以下方式读取数据：

```python
# 读取 JSON Lines 日志
import json
from pathlib import Path

def read_metrics(log_file: Path):
    with open(log_file, 'r', encoding='utf-8') as f:
        for line in f:
            yield json.loads(line)

# 按事件类型筛选
def filter_events(log_file: Path, event_type: str):
    for event in read_metrics(log_file):
        if event['event'] == event_type:
            yield event

# 示例：获取所有会话汇总
for summary in filter_events(metrics_file, 'session_summary'):
    print(f"设备 {summary['device_serial']}: 处理了 {summary['data']['total_messages']} 条消息")
```

---

**创建时间**: 2026-01-21
**状态**: 待实现
