# Realtime Reply 扫描间隔参数传递流程

## 概述

本文档分析 Realtime Reply 系统中扫描间隔参数（scan_interval）从数据库到子进程的完整传递流程。

**结论：✅ 扫描间隔参数传递正常，已正确使用数据库配置**

---

## 参数传递链路

### 1. 数据库存储

**位置：** `settings` 表的 `followup` 分类

**字段：** `default_scan_interval`

```sql
SELECT value FROM settings WHERE category = 'followup' AND key = 'default_scan_interval'
```

---

### 2. 前端读取配置

**文件：** `wecom-desktop/src/views/RealtimeView.vue`

**函数：** `fetchSettings()`

```typescript
async function fetchSettings() {
  try {
    const response = await fetch('http://localhost:8765/api/realtime/settings')
    if (response.ok) {
      const data = await response.json()
      settings.value = { ...settings.value, ...data }
    }
  } catch (error) {
    console.error('Failed to fetch settings:', error)
  }
}
```

**后端端点：** `GET http://localhost:8765/api/realtime/settings`（路由前缀以 `realtime_reply` 路由器为准）

```python
# wecom-desktop/backend/routers/realtime_reply.py:59-73
@router.get("/settings", response_model=RealtimeSettings)
async def get_realtime_settings():
    """获取实时回复设置"""
    try:
        from services.settings import get_settings_service
        service = get_settings_service()
        followup = service.get_followup_settings()

        return RealtimeSettings(
            scan_interval=followup.default_scan_interval,  # 从数据库读取
            use_ai_reply=followup.use_ai_reply,
            send_via_sidecar=followup.send_via_sidecar,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load settings: {str(e)}")
```

**前端存储：** `settings.value.scanInterval`

---

### 3. 前端启动时传递参数

**文件：** `wecom-desktop/src/views/RealtimeView.vue:71-98`

**函数：** `startDeviceFollowUp()`

```typescript
async function startDeviceFollowUp(serial: string) {
  try {
    const params = new URLSearchParams({
      scan_interval: String(settings.value.scanInterval),  // ✅ 使用数据库配置
      use_ai_reply: String(settings.value.useAIReply),
      send_via_sidecar: String(settings.value.sendViaSidecar),
    })

    const response = await fetch(
      `http://localhost:8765/api/realtime/device/${serial}/start?${params}`,
      { method: 'POST' }
    )
    // ...
  }
}
```

**关键改动（已修复）：**

- ❌ 之前：`scan_interval: '60'` （硬编码）
- ✅ 现在：`scan_interval: String(settings.value.scanInterval)` （使用数据库配置）

---

### 4. 后端接收参数

**文件：** `wecom-desktop/backend/routers/realtime_reply.py:101-126`

**端点：** `POST /api/realtime/device/{serial}/start`

```python
@router.post("/device/{serial}/start")
async def start_device(
    serial: str,
    scan_interval: int = Query(60, ge=10, le=600),  # ✅ 接收参数，默认60秒
    use_ai_reply: bool = Query(True),
    send_via_sidecar: bool = Query(True),
):
    manager = get_realtime_reply_manager()

    success = await manager.start_realtime_reply(
        serial=serial,
        scan_interval=scan_interval,  # ✅ 传递给 manager
        use_ai_reply=use_ai_reply,
        send_via_sidecar=send_via_sidecar
    )
```

---

### 5. Manager 构建子进程命令

**文件：** `wecom-desktop/backend/services/realtime_reply_manager.py`

**函数：** `start_realtime_reply()`（还会在启动前清理同 serial 的孤儿 realtime 子进程，见 `orphan_process_cleaner`）

```python
# 构建命令（摘录）
script_path = PROJECT_ROOT / "wecom-desktop" / "backend" / "scripts" / "realtime_reply_process.py"

cmd = [
    "uv", "run",
    str(script_path),
    "--serial", serial,
    "--scan-interval", str(scan_interval),  # ✅ 传递给子进程
]

if use_ai_reply:
    cmd.append("--use-ai-reply")

if send_via_sidecar:
    cmd.append("--send-via-sidecar")
```

---

### 6. 子进程解析参数

**文件：** `wecom-desktop/backend/scripts/realtime_reply_process.py`

**argparse 定义：**

```python
parser = argparse.ArgumentParser(
    description="Realtime Reply Process - Single device runner"
)
parser.add_argument("--serial", required=True, help="Device serial number")
parser.add_argument(
    "--scan-interval",
    type=int,
    default=60,  # ✅ 默认60秒
    help="Scan interval in seconds (default: 60)"
)
parser.add_argument("--use-ai-reply", action="store_true", help="Use AI to generate replies")
parser.add_argument("--send-via-sidecar", action="store_true", help="Send via Sidecar (manual review)")

args = parser.parse_args()
```

**使用：** `realtime_reply_process.py:217-218, 235-236`

```python
# 主循环中使用
logger.info(f"Sleeping {args.scan_interval}s until next scan...")
await asyncio.sleep(args.scan_interval)  # ✅ 使用传入的扫描间隔
```

---

## 参数传递流程图

```
数据库 (settings.followup.default_scan_interval)
    ↓
GET /api/realtime/settings
    ↓
前端 settings.value.scanInterval
    ↓
前端点击 Start 按钮
    ↓
POST /api/realtime/device/{serial}/start?scan_interval={value}
    ↓
RealtimeReplyManager.start_realtime_reply(scan_interval)
    ↓
子进程命令: uv run wecom-desktop/backend/scripts/realtime_reply_process.py --scan-interval {value}
    ↓
args.scan_interval
    ↓
await asyncio.sleep(args.scan_interval)  ← 实际使用
```

---

## 验证要点

### ✅ 1. 前端使用数据库配置

- 位置：`RealtimeView.vue:74`
- 代码：`scan_interval: String(settings.value.scanInterval)`

### ✅ 2. 参数验证范围

- 位置：`realtime_reply.py:104`
- 代码：`Query(60, ge=10, le=600)` - 限制 10-600 秒

### ✅ 3. 命令行传递

- 位置：`realtime_reply_manager.py:190`
- 代码：`"--scan-interval", str(scan_interval)`

### ✅ 4. 子进程使用

- 位置：`realtime_reply_process.py:218, 236`
- 代码：`await asyncio.sleep(args.scan_interval)`

---

## 测试验证

### 场景 1: 使用默认配置（60秒）

```bash
# 数据库中 default_scan_interval = 60
# 启动后子进程每 60 秒扫描一次
```

### 场景 2: 修改配置（120秒）

```bash
# 1. 在设置页面修改扫描间隔为 120 秒
# 2. 保存设置到数据库
# 3. 停止当前运行的实时回复
# 4. 重新启动
# 5. 验证子进程使用 120 秒间隔
```

### 场景 3: 不同设备使用相同配置

```bash
# 所有设备启动时都读取同一个数据库配置
# 可以通过修改数据库统一调整所有设备的扫描间隔
```

---

## 相关文件

- **前端：** `wecom-desktop/src/views/RealtimeView.vue`
- **后端路由：** `wecom-desktop/backend/routers/realtime_reply.py`
- **Manager：** `wecom-desktop/backend/services/realtime_reply_manager.py`
- **子进程：** `wecom-desktop/backend/scripts/realtime_reply_process.py`
- **孤儿进程清理：** `wecom-desktop/backend/utils/orphan_process_cleaner.py`
- **设置服务：** `wecom-desktop/backend/services/settings.py`

---

## 总结

扫描间隔参数传递链路完整，已正确使用数据库配置。用户在前端修改配置后，新启动的实时回复进程会使用新的扫描间隔。

**注意：** 修改配置不会影响已运行的进程，需要重启实时回复才能生效。
