# 指标统计数据为 0 问题修复

**日期**: 2026-01-24
**状态**: 已修复

## 问题描述

用户反馈在 Follow-Up 运行过程中，虽然界面和文本日志显示已成功存储消息和发送回复（例如 "Messages stored: 27", "Replies sent: 4"），但底部的 JSON 汇总日志 (`session_summary`) 中相关统计字段均为 0：

```json
"data": {
    "total_messages": 0,
    "messages_added": 0,
    "ai_replies_sent": 0,
    ...
}
```

## 原因分析

1.  **ResponseDetector 未更新计数器**：`ResponseDetector` 仅仅调用了 `log_reply_sent` 等方法来发射事件，但并没有调用能够增加内部计数器的方法（如 `log_message_processed`）。
2.  **MetricsLogger 设计缺陷**：`MetricsLogger.log_reply_sent` 方法原本只负责发射事件（Event），没有更新内部的 `_counters`（如 `ai_replies_sent`）。
3.  **消息存储统计缺失**：`ResponseDetector` 使用批量存储方法 `_store_messages_to_db`，该过程没有向 `MetricsLogger` 汇报存储数量。

## 修复方案

### 1. 增强 `MetricsLogger`

在 `src/wecom_automation/core/metrics_logger.py` 中：

- **修改 `log_reply_sent`**: 现在会根据 `success` 状态自动增加 `ai_replies_sent` 或 `ai_replies_failed` 计数器。
- **新增辅助方法**: 添加了专门用于更新计数器的方法：
  - `record_messages_stored(added, skipped)`: 用于批量更新消息统计。
  - `record_customer_processed(name)`: 用于记录已处理客户。
  - `record_ai_reply_generated()`: 用于记录 AI 回复生成数。

### 2. 更新 `ResponseDetector`

在 `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py` 中：

- 在 `_process_unread_user_with_wait` 流程中注入统计调用。
- **处理开始时**: 调用 `metrics.record_customer_processed(user_name)`。
- **消息存储后**: 调用 `metrics.record_messages_stored(stored_count)`。
- **AI 回复生成后**: 调用 `metrics.record_ai_reply_generated()`。

## 验证

下次 Follow-Up 任务运行时，`session_summary` 日志应能正确反映本次会话的统计数据。
