# Realtime Reply Settings 分析报告

**分析日期**: 2026-01-30  
**状态**: 🔴 发现问题

---

## 1. 问题摘要

在架构分离重构后，实时回复(Realtime Reply)的设置功能存在 **API 端点缺失** 问题。

### 🔴 关键问题

前端 `RealtimeView.vue` 调用的设置 API 端点 **不存在**：

```typescript
// RealtimeView.vue 第192行
const response = await fetch('http://localhost:8765/a../03-impl-and-arch/settings')

// RealtimeView.vue 第208行
const response = await fetch('http://localhost:8765/a../03-impl-and-arch/settings', {
  method: 'POST',
  ...
})
```

**原因**：

1. `followup.py` 路由前缀已改为../03-impl-and-arch/key-modules/realtime`
2. 该路由中从未定义过 `/settings` 端点
3. 前端仍在调用旧的 `/a../03-impl-and-arch/settings` 路径

---

## 2. 设置数据流分析

### 2.1 当前架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         Settings Architecture                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────────┐                                                   │
│  │ RealtimeView.vue │                                                   │
│  │                  │                                                   │
│  │ GET /a../03-impl-and-arch/settings  ──────────────────▶  ❌ 404 NOT FOUND   │
│  │ POST /a../03-impl-and-arch/settings ──────────────────▶  ❌ 404 NOT FOUND   │
│  └──────────────────┘                                                   │
│                                                                         │
│  ┌──────────────────┐      ┌──────────────────┐                        │
│  │ followup.py      │      │ settings.py      │                        │
│  │ router           │      │ router           │                        │
│  │                  │      │                  │                        │
│  │ prefix:          │      │ prefix:          │                        │
│  ../03-impl-and-arch/key-modules/realtime    │      │ /settings        │                        │
│  │                  │      │                  │                        │
│  │ ❌ 无 /settings  │      │ ✅ 有统一设置    │                        │
│  │    端点          │      │    端点          │                        │
│  └──────────────────┘      └──────────────────┘                        │
│                                    │                                    │
│                                    ▼                                    │
│                        ┌──────────────────────┐                        │
│                        │ SettingsService      │                        │
│                        │ (统一设置服务)       │                        │
│                        │                      │                        │
│                        │ get_followup_settings()                       │
│                        │ get_all_settings()   │                        │
│                        └──────────────────────┘                        │
│                                    │                                    │
│                                    ▼                                    │
│                        ┌──────────────────────┐                        │
│                        │ Database             │                        │
│                        │ settings 表          │                        │
│                        └──────────────────────┘                        │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 设置字段映射

| 前端字段 (RealtimeView.vue) | 后端模型 (FollowupSettings) | 说明                  |
| --------------------------- | --------------------------- | --------------------- |
| `scan_interval`             | `default_scan_interval`     | 扫描间隔（秒）        |
| `use_ai_reply`              | `use_ai_reply`              | 是否使用 AI 回复      |
| `send_via_sidecar`          | `send_via_sidecar`          | 是否通过 Sidecar 发送 |

### 2.3 前端设置初始值

```typescript
// RealtimeView.vue 第73-77行
const settings = ref({
  scan_interval: '60',
  use_ai_reply: 'false',
  send_via_sidecar: 'true',
})
```

---

## 3. 后端设置模型

### 3.1 FollowupSettings (新架构)

```python
# wecom-desktop/backend/servic../03-impl-and-arch/key-modules/models.py

@dataclass
class FollowupSettings:
    """跟进系统设置 (新架构 - 精简版)"""

    # 实时回复相关
    default_scan_interval: int = 60      # 默认扫描间隔（秒）
    use_ai_reply: bool = False           # 默认是否使用 AI 回复
    send_via_sidecar: bool = True        # 默认是否通过 Sidecar 发送

    # 补刀跟进策略（Phase 2 保留）
    max_followups: int = 3               # 最大跟进次数
    initial_delay_seconds: int = 120     # 首次延迟（秒）
    subsequent_delay_seconds: int = 120  # 后续延迟（秒）
    use_exponential_backoff: bool = False
    backoff_multiplier: float = 2.0

    # 工作时间限制
    enable_operating_hours: bool = True
    start_hour: int = 10
    end_hour: int = 22
```

### 3.2 统一设置服务

```python
# wecom-desktop/backend/servic../03-impl-and-arch/key-modules/service.py

class SettingsService:
    def get_followup_settings(self) -> FollowupSettings:
        """获取跟进设置"""
        data = self.get_category(SettingCategory.FOLLOWUP.value)
        return FollowupSettings(**filtered)
```

---

## 4. 进程启动时的设置使用

### 4.1 RealtimeReplyManager.start_realtime_reply()

```python
# wecom-desktop/backend/services/realtime_reply_manager.py

async def start_realtime_reply(
    self,
    serial: str,
    scan_interval: int = 60,        # ⚠️ 默认值，非从设置读取
    use_ai_reply: bool = True,      # ⚠️ 默认值，非从设置读取
    send_via_sidecar: bool = True,  # ⚠️ 默认值，非从设置读取
) -> bool:
    # 构建命令
    cmd = [
        "uv", "run",
        str(script_path),
        "--serial", serial,
        "--scan-interval", str(scan_interval),
    ]

    if use_ai_reply:
        cmd.append("--use-ai-reply")

    if send_via_sidecar:
        cmd.append("--send-via-sidecar")
```

### 4.2 前端调用 API

```typescript
// RealtimeView.vue 第221-225行

const params = new URLSearchParams({
  scan_interval: settings.value.scan_interval,
  use_ai_reply: settings.value.use_ai_reply,
  send_via_sidecar: settings.value.send_via_sidecar,
})

const response = await fetch(
  `http://localhost:87../03-impl-and-arch/key-modules/realtime/device/${serial}/start?${params}`,
  { method: 'POST' }
)
```

**分析**：设置通过 URL 查询参数传递，而非从后端读取。

---

## 5. 修复建议

### 方案 A：添加专用设置端点（推荐）

在 `followup.py` 中添加设置端点：

```python
# wecom-desktop/backend/routers/followup.py

@router.get("/settings")
async def get_realtime_settings():
    """获取实时回复设置"""
    from services.settings import get_settings_service
    service = get_settings_service()
    followup = service.get_followup_settings()

    return {
        "scan_interval": followup.default_scan_interval,
        "use_ai_reply": followup.use_ai_reply,
        "send_via_sidecar": followup.send_via_sidecar,
    }


@router.post("/settings")
async def update_realtime_settings(request: dict):
    """更新实时回复设置"""
    from services.settings import get_settings_service, SettingCategory
    service = get_settings_service()

    updates = {}
    if "scan_interval" in request:
        updates["default_scan_interval"] = int(request["scan_interval"])
    if "use_ai_reply" in request:
        updates["use_ai_reply"] = request["use_ai_reply"] in (True, "true", "True")
    if "send_via_sidecar" in request:
        updates["send_via_sidecar"] = request["send_via_sidecar"] in (True, "true", "True")

    service.set_category(SettingCategory.FOLLOWUP.value, updates, "api")

    return {"success": True, "message": "Settings saved"}
```

同时更新前端 API 路径：

```typescript
// RealtimeView.vue

// 修改前
const response = await fetch('http://localhost:8765/a../03-impl-and-arch/settings')

// 修改后
const response = await fetch('http://localhost:87../03-impl-and-arch/key-modules/realtime/settings')
```

### 方案 B：使用统一设置 API

前端改用统一设置 API：

```typescript
// 获取设置
const response = await fetch('http://localhost:87../03-impl-and-arch/key-modules/category/followup')

// 更新设置
const response = await fetch(
  'http://localhost:87../03-impl-and-arch/key-modules/category/followup',
  {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      default_scan_interval: parseInt(settings.value.scan_interval),
      use_ai_reply: settings.value.use_ai_reply === 'true',
      send_via_sidecar: settings.value.send_via_sidecar === 'true',
    }),
  }
)
```

---

## 6. 当前功能影响

### ✅ 正常工作

| 功能         | 说明               |
| ------------ | ------------------ |
| 启动实时回复 | 使用前端传入的参数 |
| 停止实时回复 | 正常               |
| 暂停/恢复    | 正常               |
| 设备状态查询 | 正常               |

### ⚠️ 异常行为

| 功能       | 问题                     |
| ---------- | ------------------------ |
| 加载设置   | 404 错误，使用前端默认值 |
| 保存设置   | 404 错误，保存失败       |
| 设置持久化 | 无法保存到数据库         |

### 用户体验影响

1. **每次打开页面**：设置重置为默认值
2. **保存设置时**：显示错误提示 "Failed to save settings"
3. **重启应用后**：之前的设置丢失

---

## 7. 实施优先级

| 优先级 | 任务                                                             | 工作量  |
| ------ | ---------------------------------------------------------------- | ------- |
| 🔴 高  | 添加../03-impl-and-arch/key-modules/realtime/settings` GET 端点  | 15 分钟 |
| 🔴 高  | 添加../03-impl-and-arch/key-modules/realtime/settings` POST 端点 | 15 分钟 |
| 🟡 中  | 更新前端 API 调用路径                                            | 5 分钟  |
| 🟢 低  | 添加设置迁移逻辑（可选）                                         | 30 分钟 |

---

## 8. 总结

**问题根因**：架构分离时更改了路由前缀，但未同步更新前端 API 调用路径，且原本就缺少设置端点。

**影响范围**：实时回复设置无法正确加载和保存。

**推荐修复**：采用方案 A，在../03-impl-and-arch/key-modules/realtime/settings` 添加专用端点，保持 API 语义清晰。

---

_报告生成时间: 2026-01-30_
