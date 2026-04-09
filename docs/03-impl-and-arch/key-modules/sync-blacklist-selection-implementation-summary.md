# 黑名单选择功能实现总结

## 概述

当前实现已经落到统一黑名单服务：

- 统一读写：`src/wecom_automation/services/blacklist_service.py`
- 数据修复：`src/wecom_automation/database/schema.py`
- API：`wecom-desktop/backend/routers/blacklist.py`
- 全量同步过滤：`src/wecom_automation/services/sync/orchestrator.py`

这里总结的是**当前代码已经生效的行为**。

## 当前实现状态

### 数据库与迁移

- `blacklist` 表包含 `avatar_url`、`is_blacklisted`、`deleted_by_user`、`customer_db_id`
- schema repair 会补齐缺失列，并把历史空值回填为 `is_blacklisted=1`
- 历史记录默认视为明确拉黑，这是迁移兼容行为

### 统一服务层

- 高频判断走 `BlacklistChecker.is_blacklisted()`
- 写操作和列表查询走 `BlacklistWriter`
- 桌面端旧的 `backend/services/blacklist_service.py` 不再是主实现，只保留兼容用途

### 全量同步

Phase 1:

- 扫描用户列表
- 调用 `BlacklistWriter.upsert_scanned_users()`
- **新扫描用户显式写入 `is_blacklisted=0`，默认放行**
- 已存在用户保留状态，仅刷新元数据

Phase 1.5:

- 调用 `BlacklistWriter.get_whitelist_names()`
- 仅对白名单用户执行 Phase 2 同步

### 自动拉黑入口

自动拉黑并不意味着 UI 中点击“拉黑”按钮，而是更新控制库 `blacklist` 表：

- 媒体自动拉黑：`media_actions/auto_blacklist.py`
- 用户删除/拉黑客服：`sync/customer_syncer.py`
- Follow-up 检测：`backend/services/followup/response_detector.py`

这些入口都会影响后续同步/跟进阶段的过滤结果。

## 与早期方案的差异

早期设计文档曾写成“新扫描用户默认拉黑”，但当前代码不是这样。

实际运行时行为：

| 场景                     | 当前代码行为                 |
| :----------------------- | :--------------------------- |
| 新用户首次扫描           | 插入 `is_blacklisted=0`      |
| 历史老黑名单迁移         | 回填/保留 `is_blacklisted=1` |
| 手动拉黑                 | 更新为 `is_blacklisted=1`    |
| 手动放行                 | 更新为 `is_blacklisted=0`    |
| 媒体或删好友触发自动拉黑 | 更新为 `is_blacklisted=1`    |

## 关键文件

### 后端

- `src/wecom_automation/database/schema.py`
- `src/wecom_automation/services/blacklist_service.py`
- `src/wecom_automation/services/sync/orchestrator.py`
- `src/wecom_automation/services/sync/customer_syncer.py`
- `wecom-desktop/backend/routers/blacklist.py`
- `wecom-desktop/backend/services/followup/response_detector.py`

### 前端

- `wecom-desktop/src/views/BlacklistView.vue`
- `wecom-desktop/src/services/api.ts`

### 自动拉黑配置

- `wecom-desktop/src/views/MediaActionsView.vue`
- `wecom-desktop/backend/routers/media_actions.py`
- `src/wecom_automation/services/media_actions/factory.py`

## 测试覆盖

当前已有的重点测试包括：

- `tests/unit/test_blacklist_channel_matching.py`
- `tests/unit/test_media_actions_factory.py`
- `tests/unit/test_media_action_integration.py`
- `tests/unit/test_response_detector.py`
- `wecom-desktop/backend/tests/test_blacklist_api.py`
- `wecom-desktop/backend/tests/test_media_actions_api.py`

这些测试覆盖了：

- 名称维度黑名单匹配
- 新扫描用户默认放行
- media action factory 的 settings/effects DB 路由
- follow-up 路径从控制库读取媒体自动动作设置

## 结论

黑名单系统目前已经从“单纯的黑名单列表”演进为“扫描索引 + 状态控制表”。

关键结论：

- 统一服务实现已经收敛到 `src/wecom_automation/services/blacklist_service.py`
- 新扫描用户默认放行，而不是默认拉黑
- 自动拉黑、手动拉黑和同步过滤都使用同一张 `blacklist` 表
- 全量同步与 follow-up 路径都已接入该表，不再是待实现状态
