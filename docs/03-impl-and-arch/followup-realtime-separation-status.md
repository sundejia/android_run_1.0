# Followup 与 Realtime Reply 配置分离状态

## 概述

本文档记录将实时回复（Realtime Reply）配置从 `followup` 分类迁移到 `realtime` 分类的进度。

**目标**：清晰分离两个功能的配置，为真正的补刀功能预留配置空间。

---

## ✅ 已完成的修改

### 1. Settings 模型层 (`servic../03-impl-and-arch/key-modules/models.py`)

#### 新增 `REALTIME` 分类

```python
class SettingCategory(str, Enum):
    REALTIME = "realtime"  # 新增
    FOLLOWUP = "followup"
```

#### 新增 `RealtimeSettings` 数据类

```python
@dataclass
class RealtimeSettings:
    """实时回复设置"""
    scan_interval: int = 60
    use_ai_reply: bool = False
    send_via_sidecar: bool = True
```

#### 更新 `FollowupSettings` 数据类

```python
@dataclass
class FollowupSettings:
    """补刀功能设置（真正的补刀功能）"""
    followup_enabled: bool = False
    max_followups: int = 5
    use_ai_reply: bool = False
    enable_operating_hours: bool = False
    start_hour: str = "09:00"
    end_hour: str = "18:00"
    message_templates: list = [...]
    followup_prompt: str = ""
    idle_threshold_minutes: int = 30
    max_attempts_per_customer: int = 3
```

#### 更新 `AllSettings`

```python
@dataclass
class AllSettings:
    ...
    realtime: RealtimeSettings  # 新增
    followup: FollowupSettings  # 更新
```

---

### 2. 默认配置 (`servic../03-impl-and-arch/key-modules/defaults.py`)

#### Realtime Reply 配置（新增）

```python
(SettingCategory.REALTIME.value, "scan_interval", ValueType.INT.value, 60, ...),
(SettingCategory.REALTIME.value, "use_ai_reply", ValueType.BOOLEAN.value, False, ...),
(SettingCategory.REALTIME.value, "send_via_sidecar", ValueType.BOOLEAN.value, True, ...),
```

#### Followup 配置（更新）

```python
(SettingCategory.FOLLOWUP.value, "followup_enabled", ValueType.BOOLEAN.value, False, ...),
(SettingCategory.FOLLOWUP.value, "max_followups", ValueType.INT.value, 5, ...),
(SettingCategory.FOLLOWUP.value, "use_ai_reply", ValueType.BOOLEAN.value, False, ...),
(SettingCategory.FOLLOWUP.value, "enable_operating_hours", ValueType.BOOLEAN.value, False, ...),
(SettingCategory.FOLLOWUP.value, "start_hour", ValueType.STRING.value, "09:00", ...),
(SettingCategory.FOLLOWUP.value, "end_hour", ValueType.STRING.value, "18:00", ...),
(SettingCategory.FOLLOWUP.value, "message_templates", ValueType.JSON.value, [...], ...),
(SettingCategory.FOLLOWUP.value, "followup_prompt", ValueType.STRING.value, "", ...),
(SettingCategory.FOLLOWUP.value, "idle_threshold_minutes", ValueType.INT.value, 30, ...),
(SettingCategory.FOLLOWUP.value, "max_attempts_per_customer", ValueType.INT.value, 3, ...),
```

#### 前端字段映射（新增）

```python
FRONTEND_FIELD_MAP = {
    # Realtime Reply
    "scanInterval": (SettingCategory.REALTIME.value, "scan_interval"),
    "realtimeUseAIReply": (SettingCategory.REALTIME.value, "use_ai_reply"),
    "realtimeSendViaSidecar": (SettingCategory.REALTIME.value, "send_via_sidecar"),

    # Followup (补刀功能)
    "followupEnabled": (SettingCategory.FOLLOWUP.value, "followup_enabled"),
    "maxFollowupPerScan": (SettingCategory.FOLLOWUP.value, "max_followups"),
    ...
}
```

---

### 3. Settings Service (`servic../03-impl-and-arch/key-modules/service.py`)

#### 启动时初始化默认键值

每次 `SettingsService` 初始化时都会调用 `SettingsRepository.initialize_defaults()`，对 `SETTING_DEFINITIONS` 中所有（category, key）进行检查：若数据库中不存在该键，则插入默认值；已存在的键不会被覆盖。因此新增的 followup 键（如 `followup_prompt`、`idle_threshold_minutes`、`max_attempts_per_customer`）在下次后端启动时会自动写入数据库。详见 [Followup 设置数据库键值初始化](../03-impl-and-arch/key-modules/followup-settings-database-init.md)。

#### 新增 `get_realtime_settings()` 方法

```python
def get_realtime_settings(self) -> RealtimeSettings:
    """获取实时回复设置"""
    data = self.get_category(SettingCategory.REALTIME.value)
    return RealtimeSettings(**data)
```

#### 更新 `get_followup_settings()` 方法

- 只读取补刀功能相关字段
- 移除旧的实时回复字段

#### 更新 `get_all_settings()` 方法

```python
def get_all_settings(self) -> AllSettings:
    return AllSettings(
        ...
        realtime=self.get_realtime_settings(),  # 新增
        followup=self.get_followup_settings(),  # 更新
    )
```

---

### 4. Realtime Reply API (`routers/realtime_reply.py`)

#### GE../03-impl-and-arch/key-modules/realtime/settings

```python
@router.get("/settings", response_model=RealtimeSettings)
async def get_realtime_settings():
    service = get_settings_service()

    # ✅ 从 realtime 分类读取
    scan_interval = service.get(SettingCategory.REALTIME.value, "scan_interval", 60)
    use_ai_reply = service.get(SettingCategory.REALTIME.value, "use_ai_reply", False)
    send_via_sidecar = service.get(SettingCategory.REALTIME.value, "send_via_sidecar", True)

    return RealtimeSettings(...)
```

#### POS../03-impl-and-arch/key-modules/realtime/settings

```python
@router.post("/settings")
async def update_realtime_settings(settings: RealtimeSettings):
    service = get_settings_service()

    updates = {
        "scan_interval": settings.scan_interval,  # ✅ 键名更新
        "use_ai_reply": settings.use_ai_reply,
        "send_via_sidecar": settings.send_via_sidecar,
    }

    service.set_category(SettingCategory.REALTIME.value, updates, "api")  # ✅ 分类更新
```

---

### 5. Followup Settings (`servic../03-impl-and-arch/settings.py`)

#### 完全重写为补刀功能专用

- 移除所有实时回复相关字段（`scan_interval`, `initial_delay`, `subsequent_delay` 等）
- 只保留补刀功能字段
- 更新 `get_settings()` 和 `save_settings()` 方法

---

## 📊 配置分类对比

### Before（旧架构）

```
followup 分类:
  ├── default_scan_interval  (实时回复)
  ├── use_ai_reply          (实时回复)
  ├── send_via_sidecar      (实时回复)
  ├── max_followups         (补刀)
  ├── initial_delay         (补刀)
  ├── subsequent_delay      (补刀)
  └── ...
```

### After（新架构）

```
realtime 分类:
  ├── scan_interval       ✅
  ├── use_ai_reply        ✅
  └── send_via_sidecar    ✅

followup 分类:
  ├── followup_enabled          ✅
  ├── max_followups             ✅
  ├── use_ai_reply              ✅ (补刀专用)
  ├── enable_operating_hours    ✅
  ├── start_hour                ✅
  ├── end_hour                  ✅
  ├── message_templates        ✅
  ├── followup_prompt           ✅
  ├── idle_threshold_minutes    ✅
  └── max_attempts_per_customer ✅
```

---

## 🔄 数据库迁移

### 迁移脚本

文件：`wecom-desktop/backend/scripts/migrate_realtime_settings.py`

功能：

- 从 `followup.default_scan_interval` → `realtime.scan_interval`
- 从 `followup.use_ai_reply` → `realtime.use_ai_reply`
- 从 `followup.send_via_sidecar` → `realtime.send_via_sidecar`

**注意**：旧数据保留作为备份，不会删除。

---

## 📂 影响的文件清单

### ✅ 已修改

- `wecom-desktop/backend/servic../03-impl-and-arch/key-modules/models.py`
  - 新增 `RealtimeSettings`
  - 更新 `FollowupSettings`
  - 更新 `AllSettings`

- `wecom-desktop/backend/servic../03-impl-and-arch/key-modules/defaults.py`
  - 添加 `REALTIME` 分类配置
  - 更新 `FOLLOWUP` 分类配置
  - 添加前端字段映射

- `wecom-desktop/backend/servic../03-impl-and-arch/key-modules/service.py`
  - 新增 `get_realtime_settings()`
  - 更新 `get_followup_settings()`
  - 更新 `get_all_settings()`

- `wecom-desktop/backend/routers/realtime_reply.py`
  - GET../03-impl-and-arch/key-modules/realtime/settings`从`realtime` 分类读取
  - POST../03-impl-and-arch/key-modules/realtime/settings`写入`realtime` 分类

- `wecom-desktop/backend/servic../03-impl-and-arch/settings.py`
  - 完全重写，只处理补刀功能配置
  - 移除实时回复相关字段

- `wecom-desktop/src/views/FollowUpManageView.vue`
  - 更新为补刀功能专用界面
  - 包含历史记录和设置两个标签

- `wecom-desktop/backend/i18n/translations.py`
  - 更新 `followup_manage` 翻译键

- `wecom-desktop/backend/scripts/migrate_realtime_settings.py`
  - 新增数据库迁移脚本

---

## ⚠️ 注意事项

### 向后兼容

- 旧的 `followup` 分类数据仍然保留在数据库中
- 新代码优先从 `realtime` 分类读取
- 如果 `realtime` 分类不存在，使用默认值

### 前端字段名

为避免冲突，实时回复和补刀使用不同的前端字段名：

- Realtime: `realtimeUseAIReply`, `realtimeSendViaSidecar`
- Followup: `followupUseAIReply`, `followupEnabled`

---

## 🎯 下一步

用户表示会稍后添加真正的补刀功能配置和实现。当前架构已为此预留空间：

1. **配置层面**：`FollowupSettings` 数据类已准备就绪
2. **数据库层面**：`followup` 分类已清理，可存储补刀配置
3. **API 层面**：可以创建新的 `/a../03-impl-and-arch/settings` 端点
4. **前端层面**：`FollowUpManageView.vue` 已准备就绪

---

## ✅ 验证清单

- [x] `REALTIME` 分类已创建
- [x] `RealtimeSettings` 数据类已创建
- [x] `FollowupSettings` 已更新为补刀专用
- [x] 默认配置已分离
- [x] API 路由已更新
- [x] 前端字段映射已添加
- [x] 无 lint 错误
- [x] 迁移脚本已创建

---

## 📝 总结

实时回复和补刀功能的配置分离已完成。两个功能现在有清晰的边界：

- **Realtime Reply**：负责扫描红点并实时回复客户消息
- **Followup（补刀）**：负责在空闲时主动联系长时间未回复的目标客户

配置分离确保了功能的独立性和可维护性，为未来扩展提供了良好的基础。
