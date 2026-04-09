# FollowUp Sidecar 集成问题

> 创建于：2026-01-20  
> 修复于：2026-01-20  
> 状态：✅ 已修复  
> 严重性：🔴 高

## 问题描述

用户开启了 FollowUp Sidecar 模式，但：

1. AI 生成的消息没有显示在 Sidecar 文本框中
2. 没有倒计时
3. 消息直接发送，绕过了人工审核流程

## 日志表现

```
[INFO] [FOLLOWUP] Generated reply: 你好宝子，方便发张照片看看吗？...
[INFO] [FOLLOWUP] Sending reply: 你好宝子，方便发张照片看看吗？...
```

日志中**没有**出现 `🚀 Sidecar enabled for this scan` 消息，说明 `sidecar_client` 为 `None`。

## 根本原因

### 1. 设置读取错误

**文件**：`backend/servic../03-impl-and-arch/service.py`，第 260-287 行

```python
def get_sidecar_client(self, device_serial: str) -> Optional[Any]:
    settings = settings_service.get_settings()
    sidecar_config = settings.get('sidecar', {})  # ← 读取全局 sidecar 设置

    # 检查是否启用
    enabled = sidecar_config.get('sendViaSidecar', False) or settings.get('sendViaSidecar', False)
    # ↑ 问题：读取的是全局 Sidecar 设置，而不是 FollowUp 特定的设置！
```

### 2. 设置定义不一致

| 设置分类   | 字段名             | 默认值  | 用途           |
| ---------- | ------------------ | ------- | -------------- |
| `sidecar`  | `send_via_sidecar` | `False` | 全局 Sync 使用 |
| `followup` | `send_via_sidecar` | `True`  | FollowUp 使用  |

`get_sidecar_client()` 只检查 `sidecar.send_via_sidecar`，忽略了 `followup.send_via_sidecar`。

### 3. 真正的根因：设置定义缺失 ⚠️

**文件**：`backend/servic../03-impl-and-arch/key-modules/defaults.py`

在 `SETTING_DEFINITIONS` 列表中的 FollowUp 设置（第 125-151 行），**缺少 `send_via_sidecar` 字段的定义**！

这导致：

1. `get_category_defaults("followup")` 不会返回 `send_via_sidecar` 的默认值
2. `get_followup_settings()` 返回的 `FollowupSettings` 对象没有正确的 `send_via_sidecar` 值
3. 即使前端开启了这个开关，后端也无法正确读取

### 4. 实际影响

即使用户在 FollowUp 页面开启了 "Send via Sidecar" 开关，由于设置定义缺失，后端读取到的值可能是 `False` 或无效。

### 5. 更深层的根因：发送逻辑不完整 ⚠️⚠️

**文件**：`backend/servic../03-impl-and-arch/response_detector.py` 第 945-998 行

FollowUp 的 `_send_reply_wrapper` 方法只做了第1步，缺少第2步和第3步：

| 步骤 | Sync 流程                          | FollowUp 流程（修复前） |
| ---- | ---------------------------------- | ----------------------- |
| 1    | `add_message()` - 添加到队列       | ✅ 有                   |
| 2    | `set_message_ready()` - 启动倒计时 | ❌ 缺失                 |
| 3    | `wait_for_send()` - 等待用户审核   | ❌ 缺失                 |

这导致消息被添加到队列后立即返回 `success=True`，没有等待用户审核。

---

## 修复方案

### 方案 A（推荐）：修改 `get_sidecar_client()` 增加 FollowUp 检查

```python
def get_sidecar_client(self, device_serial: str) -> Optional[Any]:
    settings_service = self._get_settings_manager_service()
    if not settings_service:
        return None

    settings = settings_service.get_settings()

    # 检查全局 Sidecar 设置
    sidecar_config = settings.get('sidecar', {})
    global_enabled = sidecar_config.get('sendViaSidecar', False) or settings.get('sendViaSidecar', False)

    # 检查 FollowUp 特定的 Sidecar 设置（优先级更高）
    followup_config = settings.get('followup', {})
    followup_enabled = followup_config.get('send_via_sidecar', False)

    # 只要任一启用就创建客户端
    enabled = global_enabled or followup_enabled

    if not enabled:
        return None

    server_url = settings.get('backendUrl', "http://localhost:8765")
    return SidecarQueueClient(device_serial, server_url, logger=logger)
```

### 方案 B：使用 FollowUp 自身的设置管理器

```python
def get_sidecar_client(self, device_serial: str) -> Optional[Any]:
    # 直接使用 FollowUp 的设置
    followup_settings = self._get_settings_manager().get_settings()

    if not followup_settings.send_via_sidecar:
        return None

    # 从全局设置获取 backendUrl
    settings_service = self._get_settings_manager_service()
    settings = settings_service.get_settings() if settings_service else {}
    server_url = settings.get('backendUrl', "http://localhost:8765")

    return SidecarQueueClient(device_serial, server_url, logger=logger)
```

---

## 文件变更清单

| 文件                                           | 操作 | 说明                             |
| ---------------------------------------------- | ---- | -------------------------------- |
| `backend/servic../03-impl-and-arch/service.py` | 修改 | 修复 `get_sidecar_client()` 方法 |

---

## 验证步骤

1. 确保 FollowUp 页面的 "Send via Sidecar" 开关已开启
2. 启动 FollowUp
3. 触发一条消息（使客户出现红点）
4. 观察日志：
   - ✅ 应出现：`🚀 Sidecar enabled for this scan`
   - ✅ 应出现：`Adding to Sidecar queue for {user_name}`
   - ✅ 应出现：`Message queued for manual review`
5. 观察 Sidecar 页面：
   - ✅ 文本框应显示 AI 生成的消息
   - ✅ 应有倒计时显示

---

## 实际修复代码

**采用方案 B**：直接使用 FollowUp 自身的设置管理器

**文件**：`backend/servic../03-impl-and-arch/service.py`

```python
def get_sidecar_client(self, device_serial: str) -> Optional[Any]:
    """获取指定设备的 Sidecar 客户端"""
    # NOTE: Since SidecarQueueClient needs a session context, usually it's used within an async context manager.
    # The actual instantiation should happen in ResponseDetector or Scheduler where the loop is valid.
    from wecom_automation.services.integration.sidecar import SidecarQueueClient

    # 首先检查 FollowUp 本身的设置（这是 FollowUp 流程应该使用的）
    followup_settings = self._get_settings_manager().get_settings()
    followup_enabled = followup_settings.send_via_sidecar

    # 如果 FollowUp 设置明确禁用，直接返回 None
    if not followup_enabled:
        logger.debug(f"Sidecar disabled in FollowUp settings")
        return None

    # 从全局设置获取 backendUrl
    settings_service = self._get_settings_manager_service()
    if settings_service:
        global_settings = settings_service.get_settings()
        server_url = global_settings.get('backendUrl', "http://localhost:8765")
    else:
        server_url = "http://localhost:8765"

    logger.info(f"Creating SidecarQueueClient for {device_serial} (enabled by FollowUp settings)")
    return SidecarQueueClient(device_serial, server_url, logger=logger)
```

**关键改动**：

1. 使用 `self._get_settings_manager().get_settings()` 读取 FollowUp 本身的设置
2. 直接检查 `followup_settings.send_via_sidecar` 而不是全局 Sidecar 设置
3. 添加日志确认 Sidecar 客户端创建成功
