# 配置系统数据库化改进计划

## 版本信息

- **版本**: v1.0
- **创建日期**: 2026-01-01
- **完成日期**: 2026-01-01
- **状态**: ✅ 已完成

> **当前设计说明（2026-03 同步）**
>
> - 统一设置仍使用主库 SQLite 中的 **`settings` 表**（默认与 `wecom_conversations.db` 同文件，可由 `WECOM_DB_PATH` 覆盖）。
> - 原 **`settings_history` 表**及 **`GET/POST .../history`** 能力已移除；启动时若存在旧表会执行 `DROP TABLE IF EXISTS settings_history`。
> - 本文档中已删除的历史表 / 历史 API 描述仅反映最初方案，**以代码为准**。

## 实施结果

成功迁移的设置数量：

- `app_settings.json`: 7 个设置
- `ai_config.json`: 1 个设置
- `email_settings.json`: 9 个设置
- `followup_settings`: 11 个设置
- **总计**: 28 个设置项已迁移到数据库

---

## 1. 现状分析

### 1.1 当前设置存储位置

系统当前的设置分散在多个位置，导致管理混乱：

| 存储位置                     | 说明               | 问题                           |
| ---------------------------- | ------------------ | ------------------------------ |
| `localStorage` (前端)        | 主要的用户设置存储 | 仅存在于浏览器，无法跨设备共享 |
| `settings/app_settings.json` | 应用级别配置       | 需要手动同步，可能与前端不一致 |
| `settings/ai_config.json`    | AI 配置            | 历史遗留，与 app_settings 重复 |
| `email_settings.json`        | 邮件配置           | 单独文件，不统一               |
| 数据库 `followup_settings`   | 跟进系统设置       | 已经数据库化，但独立存在       |

### 1.2 当前设置分类

根据 `SettingsView.vue` 和 `stores/settings.ts` 分析，当前设置共分为以下类别：

#### A. 同步设置 (Sync Settings)

| 设置项             | 类型    | 默认值 | 说明                 |
| ------------------ | ------- | ------ | -------------------- |
| `timingMultiplier` | float   | 1.0    | 时间乘数（避免检测） |
| `autoPlaceholder`  | boolean | true   | 语音消息自动占位符   |
| `noTestMessages`   | boolean | false  | 跳过测试消息         |

#### B. 镜像设置 (Mirror Settings)

| 设置项                | 类型    | 默认值 | 说明          |
| --------------------- | ------- | ------ | ------------- |
| `mirrorMaxSize`       | int     | 1080   | 最大分辨率    |
| `mirrorBitRate`       | int     | 8      | 比特率 (Mbps) |
| `mirrorMaxFps`        | int     | 60     | 最大帧率      |
| `mirrorStayAwake`     | boolean | true   | 保持唤醒      |
| `mirrorTurnScreenOff` | boolean | false  | 关闭屏幕      |
| `mirrorShowTouches`   | boolean | false  | 显示触摸点    |

#### C. AI 回复设置 (AI Reply Settings)

| 设置项             | 类型    | 默认值                | 说明              |
| ------------------ | ------- | --------------------- | ----------------- |
| `useAIReply`       | boolean | false                 | 是否使用 AI 回复  |
| `aiServerUrl`      | string  | http://localhost:8000 | AI 服务器地址     |
| `aiReplyTimeout`   | int     | 10                    | AI 回复超时（秒） |
| `systemPrompt`     | text    | ''                    | 系统提示词        |
| `promptStyleKey`   | string  | 'none'                | 提示词风格预设    |
| `aiReplyMaxLength` | int     | 50                    | AI 回复最大长度   |

#### D. AI 分析设置 (AI Analysis Settings)

| 设置项                | 类型    | 默认值                   | 说明          |
| --------------------- | ------- | ------------------------ | ------------- |
| `aiAnalysisEnabled`   | boolean | true                     | 启用 AI 分析  |
| `aiAnalysisProvider`  | string  | 'deepseek'               | AI 供应商     |
| `aiAnalysisApiKey`    | string  | -                        | API Key       |
| `aiAnalysisBaseUrl`   | string  | https://api.deepseek.com | API 地址      |
| `aiAnalysisModel`     | string  | 'deepseek-chat'          | 模型名称      |
| `aiAnalysisMaxTokens` | int     | 4096                     | 最大 Token 数 |

#### E. Volcengine ASR 设置 (语音转写)

| 设置项                    | 类型    | 默认值           | 说明         |
| ------------------------- | ------- | ---------------- | ------------ |
| `volcengineAsrEnabled`    | boolean | true             | 启用语音转写 |
| `volcengineAsrApiKey`     | string  | -                | API Key      |
| `volcengineAsrResourceId` | string  | volc.seedasr.auc | 资源 ID      |

#### F. 时区设置 (Timezone Settings)

| 设置项     | 类型   | 默认值          | 说明          |
| ---------- | ------ | --------------- | ------------- |
| `timezone` | string | 'Asia/Shanghai' | IANA 时区标识 |

#### G. 邮件通知设置 (Email Settings)

| 设置项                      | 类型    | 默认值           | 说明              |
| --------------------------- | ------- | ---------------- | ----------------- |
| `emailEnabled`              | boolean | false            | 启用邮件通知      |
| `emailSmtpServer`           | string  | 'smtp.qq.com'    | SMTP 服务器       |
| `emailSmtpPort`             | int     | 465              | SMTP 端口         |
| `emailSenderEmail`          | string  | ''               | 发件人邮箱        |
| `emailSenderPassword`       | string  | ''               | 发件人密码/授权码 |
| `emailSenderName`           | string  | 'WeCom 同步系统' | 发件人名称        |
| `emailReceiverEmail`        | string  | ''               | 收件人邮箱        |
| `emailNotifyOnVoice`        | boolean | true             | 语音消息通知      |
| `emailNotifyOnHumanRequest` | boolean | true             | 转人工通知        |

#### H. Sidecar 设置

| 设置项                | 类型    | 默认值 | 说明              |
| --------------------- | ------- | ------ | ----------------- |
| `sendViaSidecar`      | boolean | false  | 通过 Sidecar 发送 |
| `countdownSeconds`    | int     | 10     | 倒计时秒数        |
| `sidecarPollInterval` | int     | 10     | 轮询间隔（秒）    |

#### I. 后端/UI 设置

| 设置项                | 类型   | 默认值                | 说明                 |
| --------------------- | ------ | --------------------- | -------------------- |
| `backendUrl`          | string | http://localhost:8765 | 后端地址             |
| `autoRefreshInterval` | int    | 5000                  | 自动刷新间隔（毫秒） |
| `logMaxEntries`       | int    | 1000                  | 日志最大条目数       |

#### J. 跟进系统设置 (Followup Settings) - 已在数据库

| 设置项                     | 类型    | 默认值 | 说明         |
| -------------------------- | ------- | ------ | ------------ |
| `enabled`                  | boolean | true   | 启用跟进系统 |
| `scan_interval_seconds`    | int     | 60     | 扫描间隔     |
| `max_followups`            | int     | 3      | 最大跟进次数 |
| `initial_delay_seconds`    | int     | 120    | 首次延迟     |
| `subsequent_delay_seconds` | int     | 120    | 后续延迟     |
| `use_exponential_backoff`  | boolean | false  | 指数退避     |
| `backoff_multiplier`       | float   | 2.0    | 退避乘数     |
| `enable_operating_hours`   | boolean | true   | 工作时间限制 |
| `start_hour`               | int     | 10     | 开始时间     |
| `end_hour`                 | int     | 22     | 结束时间     |
| `use_ai_reply`             | boolean | false  | 使用 AI 回复 |

### 1.3 现有问题

1. **数据分散**：设置存储在多个位置，难以统一管理
2. **同步复杂**：前端 localStorage 和后端 JSON 文件需要手动同步
3. **无版本控制**：设置修改没有历史记录，无法回滚
4. **跨设备无法共享**：localStorage 数据只存在于单一浏览器
5. **敏感信息风险**：API Key 等敏感信息存储在前端 localStorage
6. **迁移困难**：升级或迁移时需要处理多个文件
7. **类型不一致**：前端 camelCase 和后端 snake_case 命名混乱

---

## 2. 改进目标

### 2.1 核心目标

1. **统一存储**：将所有设置存储到 SQLite 数据库的 `settings` 表
2. **分类管理**：按功能模块分类，便于查询和管理
3. **向后兼容**：支持从现有 JSON 文件迁移，保留现有 API
4. **审计追踪**：记录设置修改历史
5. **安全存储**：敏感信息加密存储（可选）
6. **前后端同步**：建立可靠的同步机制

### 2.2 非目标（不在本次范围内）

- 多用户/多租户支持
- 分布式配置中心
- 设置加密存储

---

## 3. 架构设计

### 3.1 数据库 Schema

```sql
-- 应用设置表（键值对存储）
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 分类和键
    category TEXT NOT NULL,      -- 设置类别：sync, mirror, ai_reply, ai_analysis, volcengine, email, sidecar, followup, general
    key TEXT NOT NULL,           -- 设置键名（snake_case）

    -- 值存储（支持多种类型）
    value_type TEXT NOT NULL,    -- 类型：string, int, float, boolean, json
    value_string TEXT,           -- 字符串值
    value_int INTEGER,           -- 整数值
    value_float REAL,            -- 浮点值
    value_bool INTEGER,          -- 布尔值 (0/1)
    value_json TEXT,             -- JSON 值（复杂对象）

    -- 元数据
    description TEXT,            -- 设置描述
    is_sensitive INTEGER DEFAULT 0,  -- 是否敏感信息
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 约束
    UNIQUE(category, key)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_settings_category ON settings(category);
CREATE INDEX IF NOT EXISTS idx_settings_category_key ON settings(category, key);
```

### 3.2 类别定义

| 类别          | 说明                        | 键数量 |
| ------------- | --------------------------- | ------ |
| `general`     | 通用设置（时区、后端URL等） | 4      |
| `sync`        | 同步设置                    | 3      |
| `mirror`      | 镜像设置                    | 6      |
| `ai_reply`    | AI 回复设置                 | 6      |
| `ai_analysis` | AI 分析设置                 | 6      |
| `volcengine`  | Volcengine ASR 设置         | 3      |
| `email`       | 邮件通知设置                | 10     |
| `sidecar`     | Sidecar 设置                | 3      |
| `followup`    | 跟进系统设置                | 11     |

### 3.3 模块架构

```
wecom-desktop/backend/
├── services/
│   └── settings/
│       ├── __init__.py          # 导出公共 API
│       ├── models.py            # 数据模型定义
│       ├── repository.py        # 数据库操作
│       ├── service.py           # 业务逻辑
│       ├── migration.py         # 迁移工具
│       └── defaults.py          # 默认值定义
├── routers/
│   └── settings.py              # API 路由（保持兼容）
```

---

## 4. 数据模型

### 4.1 Pydantic 模型

```python
from pydantic import BaseModel, Field
from typing import Optional, Any, Dict, List
from enum import Enum
from datetime import datetime


class SettingCategory(str, Enum):
    """设置类别枚举"""
    GENERAL = "general"
    SYNC = "sync"
    MIRROR = "mirror"
    AI_REPLY = "ai_reply"
    AI_ANALYSIS = "ai_analysis"
    VOLCENGINE = "volcengine"
    EMAIL = "email"
    SIDECAR = "sidecar"
    FOLLOWUP = "followup"


class ValueType(str, Enum):
    """值类型枚举"""
    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOLEAN = "boolean"
    JSON = "json"


class SettingRecord(BaseModel):
    """单个设置记录"""
    id: Optional[int] = None
    category: SettingCategory
    key: str
    value_type: ValueType
    value: Any
    description: Optional[str] = None
    is_sensitive: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SettingUpdate(BaseModel):
    """设置更新请求"""
    value: Any
    changed_by: str = "api"


class SettingsGroup(BaseModel):
    """按类别分组的设置"""
    category: SettingCategory
    settings: Dict[str, Any]


# 各类别的完整设置模型
class SyncSettings(BaseModel):
    timing_multiplier: float = 1.0
    auto_placeholder: bool = True
    no_test_messages: bool = False


class MirrorSettings(BaseModel):
    max_size: int = 1080
    bit_rate: int = 8
    max_fps: int = 60
    stay_awake: bool = True
    turn_screen_off: bool = False
    show_touches: bool = False


class AIReplySettings(BaseModel):
    use_ai_reply: bool = False
    server_url: str = "http://localhost:8000"
    reply_timeout: int = 10
    system_prompt: str = ""
    prompt_style_key: str = "none"
    reply_max_length: int = 50


class AIAnalysisSettings(BaseModel):
    enabled: bool = True
    provider: str = "deepseek"
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    max_tokens: int = 4096


class VolcengineSettings(BaseModel):
    enabled: bool = True
    api_key: str = ""
    resource_id: str = "volc.seedasr.auc"


class EmailSettings(BaseModel):
    enabled: bool = False
    smtp_server: str = "smtp.qq.com"
    smtp_port: int = 465
    sender_email: str = ""
    sender_password: str = ""
    sender_name: str = "WeCom 同步系统"
    receiver_email: str = ""
    notify_on_voice: bool = True
    notify_on_human_request: bool = True


class SidecarSettings(BaseModel):
    send_via_sidecar: bool = False
    countdown_seconds: int = 10
    poll_interval: int = 10


# Historical sketch only. Current code uses @dataclass SidecarSettings in
# wecom-desktop/backend/services/settings/models.py with fields aligned to
# services/settings/defaults.py (SIDECAR category), including sidecar_timeout
# and night-mode keys — required for SidecarSettings(**data) in get_sidecar_settings().


class GeneralSettings(BaseModel):
    timezone: str = "Asia/Shanghai"
    backend_url: str = "http://localhost:8765"
    auto_refresh_interval: int = 5000
    log_max_entries: int = 1000


class AllSettings(BaseModel):
    """完整的应用设置"""
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    sync: SyncSettings = Field(default_factory=SyncSettings)
    mirror: MirrorSettings = Field(default_factory=MirrorSettings)
    ai_reply: AIReplySettings = Field(default_factory=AIReplySettings)
    ai_analysis: AIAnalysisSettings = Field(default_factory=AIAnalysisSettings)
    volcengine: VolcengineSettings = Field(default_factory=VolcengineSettings)
    email: EmailSettings = Field(default_factory=EmailSettings)
    sidecar: SidecarSettings = Field(default_factory=SidecarSettings)
```

---

## 5. 实现计划

### 5.1 阶段一：基础架构（预计 2 小时）

1. **创建数据模型**
   - 定义 `models.py` 中的所有数据类
   - 定义默认值 `defaults.py`

2. **创建数据库层**
   - 实现 `repository.py` 的 CRUD 操作
   - 实现表创建和迁移

3. **创建服务层**
   - 实现 `service.py` 的业务逻辑
   - 实现类别化读写

### 5.2 阶段二：迁移工具（预计 1 小时）

1. **JSON 文件迁移**
   - 从 `app_settings.json` 迁移
   - 从 `ai_config.json` 迁移
   - 从 `email_settings.json` 迁移

2. **followup_settings 表合并**
   - 将现有 `followup_settings` 数据迁移到新表
   - 保持向后兼容

### 5.3 阶段三：API 更新（预计 1.5 小时）

1. **更新路由**
   - 保持现有 API 路径兼容
   - 添加新的统一 API 端点

2. **添加批量操作**
   - 批量获取设置
   - 批量更新设置

### 5.4 阶段四：前端适配（预计 1 小时）

1. **更新 settings store**
   - 从后端 API 加载设置
   - 保持 localStorage 作为缓存

2. **更新 SettingsView**
   - 使用新的 API 端点
   - 添加同步状态指示

---

## 6. API 设计

### 6.1 新增 API 端点

```
# 获取所有设置
GET /a../03-impl-and-arch/key-modules/all
Response: AllSettings

# 获取单个类别设置
GET /a../03-impl-and-arch/key-modules/{category}
Response: SettingsGroup

# 更新单个设置
PUT /a../03-impl-and-arch/key-modules/{category}/{key}
Body: SettingUpdate
Response: SettingRecord

# 批量更新设置
PUT /a../03-impl-and-arch/key-modules/{category}
Body: Dict[str, Any]
Response: SettingsGroup

# 重置为默认值
POST /a../03-impl-and-arch/key-modules/{category}/reset
Response: SettingsGroup
```

### 6.2 向后兼容 API

保留现有 API 端点，内部改为调用新的 settings service：

```
# 保留
GET../03-impl-and-arch/key-modules/timezone
PUT../03-impl-and-arch/key-modules/timezone
GET../03-impl-and-arch/key-modules/volcengine-asr
PUT../03-impl-and-arch/key-modules/volcengine-asr
POS../03-impl-and-arch/key-modules/update
GET../03-impl-and-arch/key-modules/email/settings
PUT../03-impl-and-arch/key-modules/email/settings
GET../03-impl-and-arch/settings
POS../03-impl-and-arch/settings
```

---

## 7. 迁移策略

### 7.1 迁移步骤

```python
async def migrate_settings():
    """迁移现有设置到数据库"""

    # 1. 创建新表
    await create_settings_tables()

    # 2. 迁移 app_settings.json
    if app_settings_file.exists():
        data = json.load(app_settings_file)
        await migrate_app_settings(data)

    # 3. 迁移 ai_config.json
    if ai_config_file.exists():
        data = json.load(ai_config_file)
        await migrate_ai_config(data)

    # 4. 迁移 email_settings.json
    if email_settings_file.exists():
        data = json.load(email_settings_file)
        await migrate_email_settings(data)

    # 5. 迁移 followup_settings 表
    await migrate_followup_settings()

    # 6. 标记迁移完成
    await set_migration_flag('settings_v1', completed=True)
```

### 7.2 回滚策略

- 保留原有 JSON 文件作为备份
- 提供回滚脚本导出数据库设置到 JSON

---

## 8. 测试计划

### 8.1 单元测试

- [ ] Repository CRUD 操作
- [ ] Service 业务逻辑
- [ ] 迁移工具

### 8.2 集成测试

- [ ] API 端点测试
- [ ] 前后端同步测试
- [ ] 向后兼容性测试

### 8.3 手动测试

- [ ] SettingsView 功能验证
- [ ] 设置修改后同步验证
- [ ] 浏览器刷新后设置保持

---

## 9. 风险与缓解

| 风险             | 影响 | 缓解措施                     |
| ---------------- | ---- | ---------------------------- |
| 迁移过程数据丢失 | 高   | 迁移前备份所有 JSON 文件     |
| API 兼容性问题   | 中   | 保留所有旧 API 端点          |
| 前端同步失败     | 中   | localStorage 作为降级方案    |
| 性能影响         | 低   | 使用数据库索引，缓存热点数据 |

---

## 10. 时间估算

| 阶段             | 预计时间     | 依赖   |
| ---------------- | ------------ | ------ |
| 阶段一：基础架构 | 2 小时       | 无     |
| 阶段二：迁移工具 | 1 小时       | 阶段一 |
| 阶段三：API 更新 | 1.5 小时     | 阶段一 |
| 阶段四：前端适配 | 1 小时       | 阶段三 |
| 测试与修复       | 1 小时       | 全部   |
| **总计**         | **6.5 小时** |        |

---

## 11. 成功标准

1. ✅ 所有设置存储在数据库 `settings` 表
2. ✅ 现有 JSON 文件数据成功迁移
3. ✅ 前端 SettingsView 正常工作
4. ✅ 所有现有 API 端点保持兼容
5. ✅ 设置修改有历史记录
6. ✅ 跨浏览器/设备设置同步

---

## 12. 附录

### 12.1 键名映射表（前端 camelCase → 后端 snake_case）

```python
KEY_MAPPING = {
    # General
    "backendUrl": "backend_url",
    "autoRefreshInterval": "auto_refresh_interval",
    "logMaxEntries": "log_max_entries",

    # Sync
    "timingMultiplier": "timing_multiplier",
    "autoPlaceholder": "auto_placeholder",
    "noTestMessages": "no_test_messages",

    # Mirror
    "mirrorMaxSize": "max_size",
    "mirrorBitRate": "bit_rate",
    "mirrorMaxFps": "max_fps",
    "mirrorStayAwake": "stay_awake",
    "mirrorTurnScreenOff": "turn_screen_off",
    "mirrorShowTouches": "show_touches",

    # AI Reply
    "useAIReply": "use_ai_reply",
    "aiServerUrl": "server_url",
    "aiReplyTimeout": "reply_timeout",
    "systemPrompt": "system_prompt",
    "promptStyleKey": "prompt_style_key",
    "aiReplyMaxLength": "reply_max_length",

    # AI Analysis
    "aiAnalysisEnabled": "enabled",
    "aiAnalysisProvider": "provider",
    "aiAnalysisApiKey": "api_key",
    "aiAnalysisBaseUrl": "base_url",
    "aiAnalysisModel": "model",
    "aiAnalysisMaxTokens": "max_tokens",

    # Volcengine
    "volcengineAsrEnabled": "enabled",
    "volcengineAsrApiKey": "api_key",
    "volcengineAsrResourceId": "resource_id",

    # Email
    "emailEnabled": "enabled",
    "emailSmtpServer": "smtp_server",
    "emailSmtpPort": "smtp_port",
    "emailSenderEmail": "sender_email",
    "emailSenderPassword": "sender_password",
    "emailSenderName": "sender_name",
    "emailReceiverEmail": "receiver_email",
    "emailNotifyOnVoice": "notify_on_voice",
    "emailNotifyOnHumanRequest": "notify_on_human_request",

    # Sidecar
    "sendViaSidecar": "send_via_sidecar",
    "countdownSeconds": "countdown_seconds",
    "sidecarPollInterval": "poll_interval",
}
```

### 12.2 文件清单

改进后需要新建/修改的文件：

**新建文件：**

- `wecom-desktop/backend/servic../03-impl-and-arch/key-modules/__init__.py`
- `wecom-desktop/backend/servic../03-impl-and-arch/key-modules/models.py`
- `wecom-desktop/backend/servic../03-impl-and-arch/key-modules/repository.py`
- `wecom-desktop/backend/servic../03-impl-and-arch/key-modules/service.py`
- `wecom-desktop/backend/servic../03-impl-and-arch/key-modules/migration.py`
- `wecom-desktop/backend/servic../03-impl-and-arch/key-modules/defaults.py`

**修改文件：**

- `wecom-desktop/backend/routers/settings.py` - 改用新 service
- `wecom-desktop/backend/routers/email.py` - 改用新 service
- `wecom-desktop/backend/routers/followup.py` - 设置部分改用新 service
- `wecom-desktop/src/stores/settings.ts` - 添加后端同步
- `wecom-desktop/src/views/SettingsView.vue` - 添加同步状态

---

## 13. 实施总结

### 13.1 已完成工作

1. ✅ **数据库架构** - 创建了 `settings` 表（历史审计表已按当前设计移除）
2. ✅ **数据模型** - 定义了完整的数据类和枚举类型
3. ✅ **存储层** - 实现了 Repository 提供 CRUD 操作
4. ✅ **服务层** - 实现了 Service 提供业务逻辑
5. ✅ **迁移工具** - 从现有 JSON 文件和数据库表迁移数据
6. ✅ **API 更新** - 更新了 settings, email, followup 路由
7. ✅ **前端适配** - 更新了 settings store 支持后端同步

### 13.2 新增 API 端点

| 端点                                                       | 方法 | 说明                       |
| ---------------------------------------------------------- | ---- | -------------------------- |
| ../03-impl-and-arch/key-modules/all`                       | GET  | 获取所有设置（按类别分组） |
| ../03-impl-and-arch/key-modules/category/{category}`       | GET  | 获取类别设置               |
| ../03-impl-and-arch/key-modules/category/{category}`       | PUT  | 批量更新类别设置           |
| ../03-impl-and-arch/key-modules/{category}/{key}`          | PUT  | 更新单个设置               |
| ../03-impl-and-arch/key-modules/category/{category}/reset` | POST | 重置类别为默认值           |
| ../03-impl-and-arch/key-modules/migrate`                   | POST | 运行迁移                   |

### 13.3 使用方法

```python
# 获取服务实例
from services.settings import get_settings_service

service = get_settings_service()

# 获取所有设置
all_settings = service.get_all_settings()

# 获取特定类别
email = service.get_email_settings()
ai = service.get_ai_reply_settings()

# 获取/设置单个值
timezone = service.get("general", "timezone")
service.set("general", "timezone", "Asia/Tokyo")

# 获取扁平化设置（前端兼容）
flat = service.get_flat_settings()
```

---

_文档结束_
