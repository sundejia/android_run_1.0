# Follow-up System 设置来源分析

**创建日期**: 2026-01-18  
**文档类型**: 架构分析

## 概述

Follow-up System 的设置**仅使用统一设置服务**（`settings` 表）。

## 设置数据来源

### 统一设置服务 (Unified Settings Service)

**位置**: `wecom-desktop/backend/services/settings/`

```
数据库表: settings
文件: 与主库相同（默认项目根目录 wecom_conversations.db，或环境变量 WECOM_DB_PATH）
说明: 不设单独的 settings_history 审计表（已移除）
```

#### 存储结构

```sql
CREATE TABLE settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,       -- 类别，如 'followup'
    key TEXT NOT NULL,            -- 设置键名
    value_type TEXT NOT NULL,     -- 值类型：string/int/float/boolean/json
    value_string TEXT,
    value_int INTEGER,
    value_float REAL,
    value_bool INTEGER,
    value_json TEXT,
    description TEXT,
    is_sensitive INTEGER DEFAULT 0,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    UNIQUE(category, key)
);
```

#### Follow-up 类别的设置项

| 键名                       | 类型    | 默认值 | 说明                 |
| -------------------------- | ------- | ------ | -------------------- |
| `enabled`                  | boolean | true   | 是否启用 Follow-up   |
| `scan_interval_seconds`    | int     | 60     | 扫描间隔（秒）       |
| `max_followups`            | int     | 3      | 最大跟进次数         |
| `initial_delay_seconds`    | int     | 120    | 首次跟进延迟（秒）   |
| `subsequent_delay_seconds` | int     | 120    | 后续跟进延迟（秒）   |
| `use_exponential_backoff`  | boolean | false  | 是否使用指数退避     |
| `backoff_multiplier`       | float   | 2.0    | 退避倍数             |
| `enable_operating_hours`   | boolean | true   | 是否限制工作时间     |
| `start_hour`               | int     | 10     | 工作开始时间（小时） |
| `end_hour`                 | int     | 22     | 工作结束时间（小时） |
| `use_ai_reply`             | boolean | false  | 是否使用 AI 生成回复 |
| `enable_instant_response`  | boolean | false  | 是否启用即时响应     |

## 设置读取流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    FollowUpService                              │
│                         ↓                                       │
│                  SettingsManager                                │
│                         ↓                                       │
│              get_settings() 方法                                │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ 从统一设置服务读取                                               │
│                                                                 │
│   from services.settings import get_settings_service            │
│   svc = get_settings_service()                                  │
│   followup = svc.get_followup_settings()                        │
│                         ↓                                       │
│   成功 → 返回 FollowUpSettings 对象                              │
│   失败 → 返回默认 FollowUpSettings()                             │
└─────────────────────────────────────────────────────────────────┘
```

## 设置保存流程

```python
def save_settings(self, settings: FollowUpSettings) -> None:
    from services.settings import get_settings_service, SettingCategory
    svc = get_settings_service()
    svc.set_category(SettingCategory.FOLLOWUP.value, {...}, "followup_service")
```

## 前端访问路径

前端通过以下 API 端点访问设置：

### 读取设置

```
GET /api/followup/settings
     ↓
FollowUpService.get_settings()
     ↓
SettingsManager.get_settings()
     ↓
(如上述流程)
```

### 保存设置

```
POST /api/followup/settings
     ↓
FollowUpService 处理
     ↓
SettingsManager.save_settings()
     ↓
写入 settings 表（统一设置服务）
```

## 相关文件

| 文件                                                    | 作用                                            |
| ------------------------------------------------------- | ----------------------------------------------- |
| `wecom-desktop/backend/services/followup/settings.py`   | Follow-up 设置管理器，包含 `SettingsManager` 类 |
| `wecom-desktop/backend/services/followup/service.py`    | Follow-up 主服务，暴露设置 API                  |
| `wecom-desktop/backend/services/settings/service.py`    | 统一设置服务                                    |
| `wecom-desktop/backend/services/settings/repository.py` | 统一设置数据库操作                              |
| `wecom-desktop/backend/services/settings/models.py`     | 设置数据模型定义                                |
| `wecom-desktop/backend/services/settings/defaults.py`   | 默认值定义                                      |

## 数据库位置

所有设置都存储在同一个数据库文件中：

```
wecom_conversations.db
└── settings 表（统一设置）
```

数据库路径获取方式：

```python
from wecom_automation.core.config import get_default_db_path
db_path = get_default_db_path()  # 默认: <项目根>/wecom_conversations.db，可用 WECOM_DB_PATH 覆盖
```

## 默认值来源

默认值定义在：

- **统一设置服务**: `wecom-desktop/backend/services/settings/defaults.py`
- **FollowUpSettings dataclass**: 作为备用默认值（统一服务不可用时使用）

## 总结

1. Follow-up System **仅使用统一设置服务** (`settings` 表) 读取和保存配置
2. 如果统一设置服务不可用，则返回 `FollowUpSettings` 的默认值
3. 所有设置都存储在 `wecom_conversations.db` 数据库的 `settings` 表中
