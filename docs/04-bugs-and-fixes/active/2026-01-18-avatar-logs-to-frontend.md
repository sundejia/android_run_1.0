# Avatar 日志移动到前端页面

**修改日期**: 2026-01-18
**状态**: ✅ 已完成

## 修改概述

将头像捕获（Avatar）日志从控制台输出移动到前端 Logs 页面显示。

## 实现原理

头像捕获运行在子进程中，其日志通过 stdout/stderr 被子进程的输出捕获器读取，并通过 WebSocket 广播到前端。

```
AvatarManager → logger → stdout/stderr → DeviceManager._read_output → WebSocket → 前端 Logs 页面
```

## 修改的文件

### 1. `src/wecom_automation/services/user/avatar.py`

#### 添加 `_log` 方法（第 66-84 行）

```python
async def _log(self, level: str, message: str, to_console: bool = True):
    """
    发送日志到前端和控制台

    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR)
        message: 日志消息
        to_console: 是否同时输出到控制台（默认True，因为日志通过stdout被发送到前端）
    """
    # 发送到前端（如果有回调）
    if self._log_callback:
        try:
            await self._log_callback(level, f"[AVATAR] {message}")
        except Exception:
            pass  # Callback failed, will use console below

    # 输出到控制台（被 DeviceManager._read_output 捕获并发送到前端）
    if to_console:
        getattr(self._logger, level.lower(), self._logger.info)(f"[AVATAR] {message}")
```

#### 更新 `__init__` 方法（第 38-64 行）

添加 `log_callback` 参数：

```python
def __init__(
    self,
    wecom_service,
    avatars_dir: Path,
    default_avatar: Optional[Path] = None,
    logger: Optional[logging.Logger] = None,
    log_callback: Optional[callable] = None  # NEW
):
    # ...
    self._log_callback = log_callback
```

#### 替换所有 `self._logger` 调用为 `await self._log`

所有日志调用现在使用 `_log` 方法，例如：

**修改前**:

```python
self._logger.info(f"[AVATAR] Starting avatar capture for user: {name}")
```

**修改后**:

```python
await self._log("INFO", f"Starting avatar capture for user: {name}")
```

### 2. `src/wecom_automation/services/sync/factory.py`

#### 更新 `create_sync_orchestrator` 函数签名（第 24-34 行）

添加 `log_callback` 参数：

```python
def create_sync_orchestrator(
    config: Optional[Config] = None,
    db_path: Optional[str] = None,
    images_dir: Optional[str] = None,
    videos_dir: Optional[str] = None,
    voices_dir: Optional[str] = None,
    avatars_dir: Optional[str] = None,
    timing_multiplier: float = 1.0,
    logger: Optional[logging.Logger] = None,
    log_callback: Optional[callable] = None,  # NEW
) -> SyncOrchestrator:
```

#### 传递 `log_callback` 到 `AvatarManager`（第 118-124 行）

```python
avatar_manager = AvatarManager(
    wecom_service=wecom,
    avatars_dir=avatars_path,
    default_avatar=default_avatar if default_avatar.exists() else None,
    logger=logger,
    log_callback=log_callback,  # Pass log callback for frontend logging
)
```

## 日志流程

### 完整流程

```
┌────────────────────────────────────────────────────────────────┐
│ 1. AvatarManager 捕获头像                                     │
│    ↓                                                               │
│ 2. 调用 await self._log("INFO", "Avatar captured successfully")    │
│    ↓                                                               │
│ 3. _log 方法调用 self._logger.info() (Python logging)            │
│    ↓                                                               │
│ 4. Python logging 输出到 stdout/stderr                            │
│    ↓                                                               │
│ 5. DeviceManager._read_output() 读取子进程输出                   │
│    ↓                                                               │
│ 6. 解析日志级别 (INFO, DEBUG, WARNING, ERROR)                   │
│    ↓                                                               │
│ 7. DeviceManager._broadcast_log() 通过 WebSocket 广播             │
│    ↓                                                               │
│ 8. 前端 Logs 页面接收并显示                                       │
└────────────────────────────────────────────────────────────────┘
```

### 日志级别映射

| Python logging level | WebSocket level | 前端显示 |
| -------------------- | --------------- | -------- |
| DEBUG                | DEBUG           | 灰色     |
| INFO                 | INFO            | 白色     |
| WARNING              | WARNING         | 黄色     |
| ERROR                | ERROR           | 红色     |

## 效果

### 修改前

- 日志只输出到控制台（终端）
- 用户需要查看终端才能看到头像捕获日志
- 前端 Logs 页面没有头像相关的日志

### 修改后

- 日志通过 stdout 被捕获并发送到前端
- 日志显示在前端 Logs 页面
- 控制台仍然有日志输出（便于调试）
- 日志带有 `[AVATAR]` 前缀，便于过滤

### 前端日志示例

```
[INFO] [AVATAR] Starting avatar capture for user: 张三
[DEBUG] [AVATAR] Collected 1523 nodes from UI tree
[DEBUG] [AVATAR] Found exact name match: '张三'
[DEBUG] [AVATAR] Avatar bounds found: (50, 345, 100, 395)
[INFO] [AVATAR] Avatar captured successfully: 张三 -> /path/to/avatar.png
```

## 验证步骤

1. **启动后端**

   ```bash
   cd wecom-desktop/backend
   uvicorn main:app --reload --port 8765
   ```

2. **启动前端**

   ```bash
   cd wecom-desktop
   npm run dev:electron
   ```

3. **触发头像捕获**
   - 在前端启动设备同步
   - 等待同步开始捕获头像

4. **查看前端 Logs 页面**
   - 选择设备对应的日志流
   - 搜索 `[AVATAR]` 前缀
   - 确认头像捕获日志显示在前端

5. **确认控制台仍有日志**（用于调试）
   - 查看后端终端
   - 确认日志仍然输出

## 日志过滤

在前端 Logs 页面中，可以通过 `[AVATAR]` 前缀过滤头像相关日志：

```
Search: [AVATAR]
```

或者只查看错误：

```
Search: [AVATAR].*ERROR
```

## 相关文档

- 头像捕获失败分析: `docs/04-bugs-and-fixes/active/01-18-avatar-capture-failure-analysis.md`
- 头像调试指南: `docs/04-bugs-and-fixes/active/01-18-avatar-debug-guide.md`

## 注意事项

1. **日志仍然输出到控制台**
   - `to_console=True` 是默认值
   - 这确保日志被 `DeviceManager._read_output` 捕获
   - 同时便于开发时调试

2. **性能影响**
   - 额外的日志可能影响性能
   - DEBUG 级别日志较多，建议生产环境使用 INFO 级别

3. **内存影响**
   - 日志历史保存在前端
   - 建议限制日志历史大小（前端已实现）

## 未来改进

1. **直接 WebSocket 支持**
   - 当前依赖 stdout/stderr 捕获
   - 未来可以直接连接 WebSocket

2. **日志级别控制**
   - 从前端动态调整日志级别
   - 避免过多的 DEBUG 日志

3. **日志分组**
   - 按功能分组（Avatar, Sync, AI Reply 等）
   - 更好的日志过滤和搜索
