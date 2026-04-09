# 黑名单迁移：JSON 文件 → 数据库

## 概述

黑名单功能已从 JSON 文件（`user_blacklist.json`）完全迁移到数据库（`wecom_conversations.db` 的 `blacklist` 表）。所有读写统一使用 `wecom_automation.services.blacklist_service`。

**完成时间**: 2026-01

## 变更摘要

| 项目     | 变更前                                            | 变更后                                                                   |
| -------- | ------------------------------------------------- | ------------------------------------------------------------------------ |
| 存储     | `user_blacklist.json`                             | 数据库表 `blacklist`                                                     |
| 框架层   | `services/user/blacklist.py` → `BlacklistManager` | `services/blacklist_service.py` → `BlacklistChecker` / `BlacklistWriter` |
| 后端 API | `routers/email.py` 读写 JSON                      | `routers/blacklist.py` + `services/blacklist_service.py` 读写数据库      |
| 接口     | `IBlacklistManager`（已删除）                     | 直接使用 `BlacklistChecker` / `BlacklistService`                         |

## 已删除/废弃

- **文件**: `user_blacklist.json`（已从仓库移除，已加入 `.gitignore`）
- **模块**: `src/wecom_automation/services/user/blacklist.py`（`BlacklistManager` 类，约 294 行）
- **接口**: `src/wecom_automation/core/interfaces.py` 中的 `IBlacklistManager`
- **参数**: `create_sync_orchestrator(blacklist_file=...)`、`initial_sync.py` 中的黑名单文件路径

## 当前使用方式

### 框架层（同步 / Followup）

```python
# 检查是否在黑名单（仅 is_blacklisted=1 的记录）
from wecom_automation.services.blacklist_service import BlacklistChecker

if BlacklistChecker.is_blacklisted(device_serial, customer_name, customer_channel):
    # 跳过该用户
    ...

# Phase 1 全量扫描：批量写入黑名单表（白名单/黑名单状态由后续操作决定）
from wecom_automation.services.blacklist_service import BlacklistWriter
BlacklistWriter().upsert_batch(device_serial, kefu_id, list_of_scanned_users)
```

### 后端（API / Followup 响应检测）

```python
from services.blacklist_service import BlacklistService

service = BlacklistService()
# 确保用户在表中（默认白名单）
service.ensure_user_in_blacklist_table(serial, user_name, user_channel)
# 检查是否拉黑
service.is_blacklisted(serial, user_name, user_channel)
# 添加到黑名单
service.add_to_blacklist(device_serial=..., customer_name=..., reason=..., deleted_by_user=...)
# 列表 / 移除等
service.get_all_blacklisted()
service.remove_from_blacklist_by_name(customer_name, channel)
```

### 涉及模块

- **主同步**: `orchestrator.py` 使用 `BlacklistChecker.is_blacklisted()`；`factory.py` 不再传入 `blacklist_manager`
- **Followup**: `response_detector.py` 使用 `BlacklistChecker` + `BlacklistService`（原本即数据库版）
- **Email**: `routers/email.py` 的 `/human-request`、`GET/DELETE /blacklist` 已改为调用 `BlacklistService`

## 数据库表结构（简要）

`blacklist` 表主要字段：`device_serial`, `customer_name`, `customer_channel`, `is_blacklisted`, `deleted_by_user`, `reason`, `avatar_url` 等。详见 `src/wecom_automation/database/schema.py` 及迁移说明。

## 文档与历史

- 历史设计/计划中仍可能出现 `user_blacklist.json`、`BlacklistManager`、`IBlacklistManager`（如 `docs/plans/upgrade-plan-full-sync.md`），仅作历史参考；当前实现以本文档和代码为准。
- 功能说明见 `do../01-product/blacklist-system.md`、`do../01-product/blacklist-system-backend.md`。
