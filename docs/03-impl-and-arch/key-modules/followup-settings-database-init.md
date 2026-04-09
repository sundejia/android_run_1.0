# Followup 设置数据库键值初始化

## 概述

补刀（Followup）功能使用独立的 `followup` 分类存储设置。本文档说明如何确保所有 followup 相关键值存在于数据库中，以及初始化策略。

## 数据库键值列表

以下键值定义于 `wecom-desktop/backend/servic../03-impl-and-arch/key-modules/defaults.py` 的 `SETTING_DEFINITIONS` 中（category = `followup`）：

| 键                          | 类型    | 默认值  | 说明                 |
| --------------------------- | ------- | ------- | -------------------- |
| `followup_enabled`          | boolean | false   | 启用补刀功能         |
| `max_followups`             | int     | 5       | 每次扫描最大补刀数量 |
| `use_ai_reply`              | boolean | false   | 补刀使用 AI 回复     |
| `enable_operating_hours`    | boolean | false   | 启用工作时间限制     |
| `start_hour`                | string  | "09:00" | 开始时间             |
| `end_hour`                  | string  | "18:00" | 结束时间             |
| `message_templates`         | json    | [...]   | 消息模板列表         |
| `followup_prompt`           | string  | ""      | 补刀 AI 提示词       |
| `idle_threshold_minutes`    | int     | 30      | 空闲阈值（分钟）     |
| `max_attempts_per_customer` | int     | 3       | 每客户最大补刀次数   |

## 初始化策略

### 1. 启动时自动补全（推荐）

`SettingsService` 在每次初始化时调用 `SettingsRepository.initialize_defaults()`。

- **行为**：遍历 `SETTING_DEFINITIONS`，若某条 `(category, key)` 在数据库中不存在，则插入默认值；已存在的键不会被覆盖。
- **位置**：`wecom-desktop/backend/servic../03-impl-and-arch/key-modules/service.py` 的 `SettingsService.__init__`。
- **效果**：新增加的 followup 键（如 `followup_prompt`、`idle_threshold_minutes`、`max_attempts_per_customer`）在下次后端启动时会自动写入数据库。

### 2. 手动初始化脚本（可选）

脚本 `wecom-desktop/backend/scripts/init_followup_settings.py` 可单独运行，用于：

- 一次性为 followup 分类补全缺失键值；
- 验证当前数据库中 followup 设置的值。

运行方式（在项目根目录）：

```bash
cd wecom-desktop/backend
python scripts/init_followup_settings.py
```

脚本会输出每个键是“已存在”还是“已添加”，并在最后打印当前 followup 设置以作验证。

## 与架构文档的关系

- Followup 与 Realtime 配置分离见：[Followup 与 Realtime Reply 配置分离状态](../03-impl-and-arch/followup-realtime-separation-status.md)。
- 本初始化机制确保分离后新增的 followup 键值在任意环境（新部署或已有数据库）下都会存在，无需单独迁移脚本。

## 验证清单

- [x] `SETTING_DEFINITIONS` 中包含全部 followup 键值
- [x] `SettingsService` 启动时调用 `initialize_defaults()`，不覆盖已有值
- [x] 可选脚本 `init_followup_settings.py` 可独立运行并验证
- [x] 前端字段映射（`FRONTEND_KEY_MAPPING`）包含 followup 相关前端键名
