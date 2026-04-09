# Follow-up 系统架构迁移指南

## 概述

当前系统正在从 **旧架构（单进程后台扫描）** 迁移到 **新架构（多设备独立子进程）**。本文档详细说明迁移步骤、需要删除的旧文件、设置适配方案以及需要清理的无用设置。

---

## 一、架构对比

### 1.1 旧架构 (BackgroundScheduler)

```
┌─────────────────────────────────────────────────────┐
│                  FollowUpService                     │
│                    (单例模式)                        │
├─────────────────────────────────────────────────────┤
│  BackgroundScheduler                                 │
│  ├── ResponseDetector (Phase 1: 红点检测)           │
│  └── FollowUpScanner  (Phase 2: 定时跟进)           │
├─────────────────────────────────────────────────────┤
│  - 单进程运行                                        │
│  - 所有设备共享一个调度器                            │
│  - 设置通过 router /a../03-impl-and-arch/settings 控制      │
│  - enabled/enableInstantResponse 控制启停            │
└─────────────────────────────────────────────────────┘
```

**旧架构问题：**

- 所有设备共享一个进程，互相干扰
- 一个设备出错会影响所有设备
- 无法单独控制某个设备的 follow-up
- 前端设置页面与新多设备 API 不匹配

### 1.2 新架构 (FollowUpDeviceManager)

```
┌─────────────────────────────────────────────────────┐
│              FollowUpDeviceManager                   │
│                  (单例模式)                          │
├─────────────────────────────────────────────────────┤
│  Device A Process    Device B Process    ...         │
│  ┌─────────────┐    ┌─────────────┐                 │
│  │followup_    │    │followup_    │                 │
│  │process.py   │    │process.py   │                 │
│  │             │    │             │                 │
│  │Response     │    │Response     │                 │
│  │Detector     │    │Detector     │                 │
│  └─────────────┘    └─────────────┘                 │
├─────────────────────────────────────────────────────┤
│  - 每设备独立子进程                                  │
│  - 进程隔离，互不干扰                                │
│  - API: /a../03-impl-and-arch/device/{serial}/start|stop    │
│  - Windows Job Object 支持暂停/恢复                  │
└─────────────────────────────────────────────────────┘
```

**新架构优点：**

- 每个设备运行独立子进程
- 进程隔离，一个设备出错不影响其他设备
- 可单独控制每个设备的 start/stop/pause/resume
- 更好的日志隔离和状态追踪

---

## 二、迁移任务清单

### 2.1 需要保留的文件

| 文件                                                                   | 作用             | 备注                        |
| ---------------------------------------------------------------------- | ---------------- | --------------------------- |
| `followup_process.py`                                                  | 新架构入口脚本   | 核心文件                    |
| `wecom-desktop/backend/services/followup_device_manager.py`            | 多设备进程管理器 | 核心文件                    |
| `wecom-desktop/backend/servic../03-impl-and-arch/repository.py`        | 数据库操作       | 继续复用                    |
| `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py` | 红点检测逻辑     | 被 followup_process.py 调用 |
| `wecom-desktop/backend/servic../03-impl-and-arch/settings.py`          | 设置管理         | 需要适配                    |
| `wecom-desktop/backend/servic../03-impl-and-arch/models.py`            | 数据模型         | 继续复用                    |
| `wecom-desktop/backend/routers/followup.py`                            | API 路由         | 需要清理旧 API              |

### 2.2 需要删除/废弃的文件

| 文件                                                           | 原因                     | 操作       |
| -------------------------------------------------------------- | ------------------------ | ---------- |
| `wecom-desktop/backend/servic../03-impl-and-arch/scheduler.py` | 旧架构调度器，不再需要   | 删除       |
| `wecom-desktop/backend/servic../03-impl-and-arch/scanner.py`   | 旧架构扫描器，不再需要   | 删除       |
| `wecom-desktop/backend/servic../03-impl-and-arch/service.py`   | 旧架构主服务，大部分废弃 | 精简或删除 |
| `wecom-desktop/backend/services/followup_service.py`           | 兼容层，可删除           | 删除       |
| `wecom-desktop/backend/services/followup_service_backup.py`    | 备份文件                 | 删除       |

### 2.3 需要修改的文件

| 文件                                                                      | 需要修改的内容             |
| ------------------------------------------------------------------------- | -------------------------- |
| `wecom-desktop/backend/servic../03-impl-and-arch/__init__.py`             | 移除旧组件导出             |
| `wecom-desktop/backend/routers/followup.py`                               | 移除旧 API，保留多设备 API |
| `wecom-desktop/src/views/FollowUpView.vue`                                | 移除旧设置，适配多设备 UI  |
| `wecom-desktop/backend/servic../03-impl-and-arch/key-modules/defaults.py` | 移除/更新无用设置          |
| `wecom-desktop/backend/servic../03-impl-and-arch/key-modules/models.py`   | 更新 FollowupSettings 模型 |

---

## 三、API 迁移

### 3.1 旧 API (需要删除)

```python
# 这些 API 基于旧的 BackgroundScheduler，需要删除或标记为废弃

# GET /a../03-impl-and-arch/settings - 获取旧架构设置
# POST /a../03-impl-and-arch/settings - 保存旧架构设置（会启动 BackgroundScheduler）
# GET /a../03-impl-and-arch/pending - 获取待跟进客户（旧架构）
# GET /a../03-impl-and-arch/logs - 获取日志历史（旧架构）
# DELETE /a../03-impl-and-arch/logs - 清空日志（旧架构）
```

### 3.2 新 API (需要保留)

```python
# 多设备管理 API - 这些是新架构的 API

# POST /a../03-impl-and-arch/device/{serial}/start - 启动设备 follow-up
# POST /a../03-impl-and-arch/device/{serial}/stop - 停止设备 follow-up
# POST /a../03-impl-and-arch/device/{serial}/pause - 暂停设备 follow-up
# POST /a../03-impl-and-arch/device/{serial}/resume - 恢复设备 follow-up
# GET /a../03-impl-and-arch/device/{serial}/status - 获取设备状态
# GET /a../03-impl-and-arch/devices/status - 获取所有设备状态
# POST /a../03-impl-and-arch/devices/stop-all - 停止所有设备

# 数据/分析 API - 继续保留
# GET /a../03-impl-and-arch/analytics - 获取统计数据
# GET /a../03-impl-and-arch/attempts - 获取跟进记录
# DELETE /a../03-impl-and-arch/attempts - 删除所有记录
# GET /a../03-impl-and-arch/export - 导出数据
```

---

## 四、设置适配

### 4.1 旧设置 (需要清理)

以下设置是为旧架构设计的，在新架构中不再需要：

| 设置                    | 旧用途                        | 新架构处理                          |
| ----------------------- | ----------------------------- | ----------------------------------- |
| `enabled`               | 控制 BackgroundScheduler 启停 | **删除** - 通过 API start/stop 控制 |
| `enableInstantResponse` | 控制是否启用即时响应          | **删除** - 合并到 start 参数        |
| `scan_interval_seconds` | BackgroundScheduler 扫描间隔  | **保留** - 作为 start API 默认参数  |
| `use_ai_reply`          | 是否使用 AI 回复              | **保留** - 作为 start API 参数      |
| `send_via_sidecar`      | 是否通过 Sidecar 发送         | **保留** - 作为 start API 参数      |

### 4.2 新设置架构

```python
# 新架构的设置更简单，因为大部分配置在启动时通过 API 参数传递

@dataclass
class FollowupSettings:
    """新架构跟进设置 - 精简版"""
    # 默认参数（通过 API 可覆盖）
    default_scan_interval: int = 60  # 默认扫描间隔（秒）
    default_use_ai_reply: bool = True  # 默认是否使用 AI 回复
    default_send_via_sidecar: bool = True  # 默认是否通过 Sidecar 发送

    # 跟进策略（仍然需要）
    max_followups: int = 3  # 最大跟进次数
    initial_delay_seconds: int = 120  # 首次延迟（秒）
    subsequent_delay_seconds: int = 120  # 后续延迟（秒）
    use_exponential_backoff: bool = False  # 指数退避
    backoff_multiplier: float = 2.0  # 退避乘数

    # 工作时间（仍然需要）
    enable_operating_hours: bool = True  # 启用工作时间限制
    start_hour: int = 10  # 开始时间
    end_hour: int = 22  # 结束时间
```

### 4.3 需要删除的设置定义

修改 `wecom-desktop/backend/servic../03-impl-and-arch/key-modules/defaults.py`，删除以下设置：

```python
# 删除这些设置定义
(SettingCategory.FOLLOWUP.value, "enabled", ...)  # 删除
(SettingCategory.FOLLOWUP.value, "enable_instant_response", ...)  # 删除
```

### 4.4 前端设置页面适配

修改 `wecom-desktop/src/views/FollowUpView.vue`：

**删除：**

```javascript
// 删除这些设置控件
settings.enabled // 移除
settings.enableInstantResponse // 移除
```

**保留：**

```javascript
// 保留这些设置（作为默认值或全局配置）
settings.scanInterval // 保留，作为默认扫描间隔
settings.maxFollowUps // 保留
settings.initialDelay // 保留
settings.subsequentDelay // 保留
settings.useExponentialBackoff // 保留
settings.backoffMultiplier // 保留
settings.enableOperatingHours // 保留
settings.startHour // 保留
settings.endHour // 保留
settings.useAIReply // 保留，作为默认值
settings.sendViaSidecar // 保留，作为默认值
```

---

## 五、代码迁移步骤

### 步骤 1: 删除旧架构文件

```bash
# 删除旧架构文件
rm wecom-desktop/backend/servic../03-impl-and-arch/scheduler.py
rm wecom-desktop/backend/servic../03-impl-and-arch/scanner.py
rm wecom-desktop/backend/services/followup_service.py
rm wecom-desktop/backend/services/followup_service_backup.py
```

### 步骤 2: 精简 service.py

修改 `wecom-desktop/backend/servic../03-impl-and-arch/service.py`：

```python
"""
Follow-up Service - 精简版

仅保留数据库操作和工具方法，移除 BackgroundScheduler 相关代码。
"""

class FollowUpService:
    """Follow-up 服务 (精简版) - 仅提供数据库操作"""

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or str(DB_PATH)
        self._settings_manager: Optional[SettingsManager] = None
        self._repository: Optional[FollowUpRepository] = None

    # 保留: 设置管理
    def _get_settings_manager(self) -> SettingsManager: ...
    def _get_repository(self) -> FollowUpRepository: ...
    def get_settings(self) -> Dict[str, Any]: ...

    # 保留: 数据库操作
    def find_followup_candidates(self) -> List[FollowUpCandidate]: ...
    def find_or_create_customer(...) -> int: ...
    def get_customer_attempt_count(self, customer_id: int) -> int: ...
    def record_attempt(...) -> int: ...
    def mark_customer_responded(self, customer_id: int) -> int: ...
    def get_pending_followup_customers(self) -> List[Dict[str, Any]]: ...

    # 删除: 以下方法全部删除
    # async def start_background_scanner(self): ...
    # async def stop_background_scanner(self): ...
    # async def pause_for_sync(self) -> Dict[str, Any]: ...
    # async def resume_after_sync(self) -> Dict[str, Any]: ...
    # def is_paused_for_sync(self) -> bool: ...
    # def get_scan_status(self) -> Dict[str, Any]: ...
    # async def run_scan(self) -> ScanResult: ...
    # async def run_active_scan(self) -> ScanResult: ...
    # async def run_active_scan_for_device(...) -> ScanResult: ...
    # async def run_multi_device_scan(...) -> ScanResult: ...
    # async def scan_for_responses(...) -> Dict[str, Any]: ...
```

### 步骤 3: 更新 **init**.py

修改 `wecom-desktop/backend/servic../03-impl-and-arch/__init__.py`：

```python
"""
Follow-up 服务模块 - 多设备架构

新架构组成:
- models: 数据模型
- settings: 设置管理
- repository: 数据库操作
- response_detector: 红点检测（被 followup_process.py 调用）
"""

from .models import FollowUpCandidate, ScanResult, FollowUpAttempt
from .settings import FollowUpSettings, SettingsManager
from .repository import FollowUpRepository
from .response_detector import ResponseDetector

# 移除这些导出：
# from .scanner import FollowUpScanner  # 删除
# from .scheduler import BackgroundScheduler  # 删除
# from .service import FollowUpService, get_followup_service  # 可选保留

__all__ = [
    "FollowUpCandidate",
    "ScanResult",
    "FollowUpAttempt",
    "FollowUpSettings",
    "SettingsManager",
    "FollowUpRepository",
    "ResponseDetector",
]
```

### 步骤 4: 更新路由

修改 `wecom-desktop/backend/routers/followup.py`：

```python
# 删除这些旧的路由处理函数:

# @router.get("/settings", response_model=FollowUpSettings)
# async def get_settings(): ...

# @router.post("/settings", response_model=FollowUpSettings)
# async def update_settings(settings: FollowUpSettings): ...

# @router.get("/pending")
# async def get_pending_followups(): ...

# @router.get("/logs")
# async def get_log_history(): ...

# @router.delete("/logs")
# async def clear_log_history(): ...

# 保留多设备 API 和数据 API
```

### 步骤 5: 更新设置定义

修改 `wecom-desktop/backend/servic../03-impl-and-arch/key-modules/defaults.py`：

```python
# 删除
(SettingCategory.FOLLOWUP.value, "enabled", ValueType.BOOLEAN.value,
 True, "启用跟进系统", False),  # 删除这行

(SettingCategory.FOLLOWUP.value, "enable_instant_response", ValueType.BOOLEAN.value,
 False, "启用即时响应", False),  # 删除这行

# 重命名 scan_interval_seconds 为 default_scan_interval
(SettingCategory.FOLLOWUP.value, "default_scan_interval", ValueType.INT.value,
 60, "默认扫描间隔(秒)", False),
```

### 步骤 6: 更新前端

修改 `wecom-desktop/src/views/FollowUpView.vue`：

1. 移除 Settings Tab 中的 `enabled` 和 `enableInstantResponse` 控件
2. 将 Settings Tab 改为"默认参数设置"
3. 在 Devices Tab 添加启动时的参数配置（scan_interval, use_ai_reply, send_via_sidecar）

---

## 六、数据库迁移

### 6.1 无需迁移

以下表结构在新旧架构中相同，无需迁移：

- `customers` - 客户表
- `messages` - 消息表
- `followup_attempts` - 跟进记录表

### 6.2 设置表清理

如果使用了新的统一设置服务（`settings` 表），需要删除旧设置：

```sql
-- 删除旧的 enabled 设置
DELETE FROM settings WHERE category = 'followup' AND key = 'enabled';

-- 删除旧的 enable_instant_response 设置
DELETE FROM settings WHERE category = 'followup' AND key = 'enable_instant_response';

-- 重命名 scan_interval_seconds 为 default_scan_interval（可选）
UPDATE settings
SET key = 'default_scan_interval'
WHERE category = 'followup' AND key = 'scan_interval_seconds';
```

---

## 七、测试验证

### 7.1 功能测试

```bash
# 1. 测试启动单设备 follow-up
curl -X POST "http://localhost:8765/a../03-impl-and-arch/device/DEVICE_SERIAL/start?scan_interval=60&use_ai_reply=true&send_via_sidecar=true"

# 2. 测试获取设备状态
curl "http://localhost:8765/a../03-impl-and-arch/device/DEVICE_SERIAL/status"

# 3. 测试获取所有设备状态
curl "http://localhost:8765/a../03-impl-and-arch/devices/status"

# 4. 测试暂停设备
curl -X POST "http://localhost:8765/a../03-impl-and-arch/device/DEVICE_SERIAL/pause"

# 5. 测试恢复设备
curl -X POST "http://localhost:8765/a../03-impl-and-arch/device/DEVICE_SERIAL/resume"

# 6. 测试停止设备
curl -X POST "http://localhost:8765/a../03-impl-and-arch/device/DEVICE_SERIAL/stop"

# 7. 测试停止所有设备
curl -X POST "http://localhost:8765/a../03-impl-and-arch/devices/stop-all"
```

### 7.2 确认旧 API 已删除

```bash
# 这些 API 应该返回 404
curl "http://localhost:8765/a../03-impl-and-arch/settings"  # 应该 404
curl -X POST "http://localhost:8765/a../03-impl-and-arch/settings"  # 应该 404
curl "http://localhost:8765/a../03-impl-and-arch/logs"  # 应该 404
```

---

## 八、回滚计划

如果迁移出现问题，可以通过以下步骤回滚：

1. 恢复 `followup_service_backup.py` 文件
2. 恢复 `scheduler.py` 和 `scanner.py` 文件
3. 恢复 `__init__.py` 中的旧导出
4. 恢复 `routers/followup.py` 中的旧 API

建议在迁移前做好完整备份。

---

## 九、迁移时间表

| 阶段     | 内容             | 预计时间        |
| -------- | ---------------- | --------------- |
| 准备     | 备份所有相关文件 | 10 分钟         |
| 阶段 1   | 删除旧架构文件   | 5 分钟          |
| 阶段 2   | 精简 service.py  | 30 分钟         |
| 阶段 3   | 更新路由         | 20 分钟         |
| 阶段 4   | 更新设置定义     | 15 分钟         |
| 阶段 5   | 更新前端         | 45 分钟         |
| 测试     | 功能测试验证     | 30 分钟         |
| **总计** |                  | **约 2.5 小时** |

---

## 十、总结

### 关键变化

1. **进程模型**: 从单进程 BackgroundScheduler 变为多进程 FollowUpDeviceManager
2. **控制方式**: 从设置开关 (`enabled`) 变为 API 调用 (`/device/{serial}/start`)
3. **设置简化**: 删除 `enabled`, `enableInstantResponse`，保留跟进策略设置
4. **API 变化**: 旧的 `/settings` API 删除，使用新的 `/device/{serial}/*` API

### 迁移后的好处

- 每个设备独立进程，更稳定
- 更细粒度的控制（单独启停每个设备）
- 更好的日志隔离
- 更清晰的架构
