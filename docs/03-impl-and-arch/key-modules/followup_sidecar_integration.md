# FollowUp Sidecar 集成实现方案

> 文档创建于：2026-01-20  
> 版本：v1.0  
> 状态：实现文档  
> 关联：[docs/followup_system_refactor.md](./followup_system_refactor.md) - 问题 4

## 目录

1. [问题分析](#问题分析)
2. [目标设计](#目标设计)
3. [实现方案](#实现方案)
4. [后端代码实现](#后端代码实现)
5. [前端代码实现](#前端代码实现)
6. [测试验证](#测试验证)

---

## 问题分析

### 当前问题

| 问题               | 说明                                            |
| ------------------ | ----------------------------------------------- |
| **无人工监督**     | AI 生成的回复直接发送，没有审核环节             |
| **容易出错**       | AI 可能生成不合适的回复，造成客户关系损害       |
| **无法编辑**       | 用户无法在发送前修改 AI 回复                    |
| **与 Sync 不一致** | Sync 流程使用 Sidecar 队列，FollowUp 却直接发送 |

### Sync 流程参考

Sync 流程已经实现了 Sidecar 集成：

```
Sync 流程：
1. Sync 进程检测到需要发送的消息
2. 调用 /a../03-impl-and-arch/{serial}/queue/add 添加到队列
3. Sidecar 前端显示队列，用户可以：
   - 查看消息内容
   - 编辑消息
   - 取消发送
   - 确认发送
4. 用户确认后，消息发送到设备
```

### FollowUp 当前流程

```
当前 FollowUp 流程 (直接发送):
1. FollowUp 检测到需要回复的客户
2. AI 生成回复消息
3. 直接调用发送 API，发送到设备 ❌
   ↳ 没有人工审核机会！
```

---

## 目标设计

### 目标流程

```
新 FollowUp 流程 (通过 Sidecar):
1. FollowUp 检测到需要回复的客户
2. AI 生成回复消息
3. 调用 /a../03-impl-and-arch/{serial}/queue/add 添加到队列 ✅
4. Sidecar 前端显示 FollowUp 生成的回复：
   - 标记来源为 "FollowUp"
   - 用户可以编辑/取消/确认
5. 用户确认后，消息发送到设备 ✅
```

### 架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    FollowUp Sidecar 集成架构                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────┐                                               │
│  │ FollowUp 进程       │                                               │
│  │                     │                                               │
│  │  检测未读消息        │                                               │
│  │       ↓             │                                               │
│  │  AI 生成回复        │                                               │
│  │       ↓             │                                               │
│  │  检查设置           │                                               │
│  │       ↓             │                                               │
│  └─────┬───────────────┘                                               │
│        │                                                                │
│        │ send_via_sidecar = true?                                       │
│        │                                                                │
│   ┌────▼────┐                    ┌─────────────────┐                   │
│   │  是     │────────────────────▶│ Sidecar Queue   │                   │
│   └─────────┘                    │                 │                   │
│                                  │ POST /queue/add │                   │
│   ┌─────────┐                    │ source: followup│                   │
│   │  否     │────────────────────▶│ 直接发送        │                   │
│   └─────────┘                    └─────────────────┘                   │
│                                          │                             │
│                                          ▼                             │
│                                  ┌─────────────────┐                   │
│                                  │ Sidecar 面板    │                   │
│                                  │                 │                   │
│                                  │ ┌─────────────┐ │                   │
│                                  │ │ 待发送队列  │ │                   │
│                                  │ │             │ │                   │
│                                  │ │ [FOLLOWUP]  │ │ ← 来源标记        │
│                                  │ │ 给张三的回复│ │                   │
│                                  │ │             │ │                   │
│                                  │ │ [编辑] [发送]│ │                   │
│                                  │ └─────────────┘ │                   │
│                                  └─────────────────┘                   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 设置选项

在 FollowUp Settings 中添加一个新选项：

```
┌─────────────────────────────────────────┐
│ Follow-Up Settings                      │
├─────────────────────────────────────────┤
│                                         │
│ ☑ Use AI Reply                          │
│                                         │
│ ☑ Send via Sidecar (推荐) ← 新增        │
│   ┗ AI 生成的回复将添加到 Sidecar       │
│     队列，需要人工确认后才发送           │
│                                         │
│ ☐ Auto-send without review              │
│   ┗ 警告：直接发送，无人工审核           │
│                                         │
└─────────────────────────────────────────┘
```

---

## 实现方案

### 3.1 消息队列扩展

在 `QueuedMessageModel` 中添加 `source` 字段：

```python
class QueuedMessageModel(BaseModel):
    id: str
    serial: str
    customerName: str
    channel: Optional[str] = None
    message: str
    timestamp: float
    status: MessageStatus = MessageStatus.PENDING
    error: Optional[str] = None
    source: str = "manual"  # 新增：消息来源 - "manual" | "sync" | "followup"
```

### 3.2 FollowUp 发送逻辑修改

修改 FollowUp 的发送逻辑，根据设置决定是否通过 Sidecar：

```python
async def send_reply(self, serial: str, customer_name: str, channel: str, message: str):
    """发送回复消息"""

    if self.settings.send_via_sidecar:
        # 通过 Sidecar 队列发送（需要人工确认）
        await self._add_to_sidecar_queue(serial, customer_name, channel, message)
    else:
        # 直接发送（无人工审核）
        await self._send_directly(serial, customer_name, channel, message)
```

### 3.3 设置字段

在 FollowUp Settings 中添加：

```python
# 后端设置
class FollowUpSettings:
    send_via_sidecar: bool = True  # 默认启用
```

```typescript
// 前端设置
interface FollowUpSettings {
  sendViaSidecar: boolean // 默认 true
}
```

---

## 后端代码实现

### 4.1 扩展 QueuedMessageModel

**文件**: `backend/routers/sidecar.py`

```python
class QueuedMessageModel(BaseModel):
    """A message queued for sending via sidecar."""
    id: str
    serial: str
    customerName: str
    channel: Optional[str] = None
    message: str
    timestamp: float
    status: MessageStatus = MessageStatus.PENDING
    error: Optional[str] = None
    source: str = "manual"  # 新增：消息来源 - "manual" | "sync" | "followup"


class AddMessageRequest(BaseModel):
    """Request to add a message to the queue."""
    customerName: str
    channel: Optional[str] = None
    message: str
    source: str = "manual"  # 新增：消息来源
```

### 4.2 修改添加消息 API

**文件**: `backend/routers/sidecar.py`

```python
@router.post("/{serial}/queue/add", response_model=AddMessageResponse)
async def add_message_to_queue(serial: str, request: AddMessageRequest):
    """Add a message to the sidecar queue for a device."""

    message_id = str(uuid.uuid4())

    queued_message = QueuedMessageModel(
        id=message_id,
        serial=serial,
        customerName=request.customerName,
        channel=request.channel,
        message=request.message,
        timestamp=time.time(),
        source=request.source,  # 新增：保存消息来源
    )

    if serial not in _queues:
        _queues[serial] = []
    _queues[serial].append(queued_message)

    return AddMessageResponse(id=message_id, success=True)
```

### 4.3 修改 FollowUp 设置

**文件**: `backend/servic../03-impl-and-arch/settings.py`

```python
@dataclass
class FollowUpSettings:
    """FollowUp 设置"""
    enabled: bool = True
    scan_interval: int = 60
    max_followups: int = 3
    initial_delay: int = 120
    subsequent_delay: int = 120
    use_exponential_backoff: bool = False
    backoff_multiplier: float = 2.0
    enable_operating_hours: bool = True
    start_hour: int = 10
    end_hour: int = 22
    use_ai_reply: bool = False
    enable_instant_response: bool = False
    send_via_sidecar: bool = True  # 新增：是否通过 Sidecar 发送
```

### 4.4 修改 FollowUp 发送逻辑

**文件**: `backend/servic../03-impl-and-arch/scanner.py` 或 `followup_process.py`

```python
import aiohttp

async def send_reply(
    self,
    serial: str,
    customer_name: str,
    channel: Optional[str],
    message: str,
    send_via_sidecar: bool = True
) -> bool:
    """
    发送回复消息

    Args:
        serial: 设备序列号
        customer_name: 客户名称
        channel: 频道（可选）
        message: 消息内容
        send_via_sidecar: 是否通过 Sidecar 队列发送

    Returns:
        是否成功
    """
    if send_via_sidecar:
        return await self._add_to_sidecar_queue(serial, customer_name, channel, message)
    else:
        return await self._send_directly(serial, customer_name, channel, message)


async def _add_to_sidecar_queue(
    self,
    serial: str,
    customer_name: str,
    channel: Optional[str],
    message: str
) -> bool:
    """
    添加消息到 Sidecar 队列（需要人工确认）
    """
    try:
        url = f"http://localhost:8765/a../03-impl-and-arch/{serial}/queue/add"
        payload = {
            "customerName": customer_name,
            "channel": channel,
            "message": message,
            "source": "followup"  # 标记来源为 FollowUp
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("success"):
                        self.logger.info(
                            f"[FollowUp] Message queued for {customer_name}: "
                            f"waiting for manual confirmation"
                        )
                        return True

                self.logger.error(f"[FollowUp] Failed to queue message: {response.status}")
                return False

    except Exception as e:
        self.logger.error(f"[FollowUp] Error adding to sidecar queue: {e}")
        return False


async def _send_directly(
    self,
    serial: str,
    customer_name: str,
    channel: Optional[str],
    message: str
) -> bool:
    """
    直接发送消息（无人工审核）
    """
    # 现有的直接发送逻辑
    try:
        url = f"http://localhost:8765/a../03-impl-and-arch/{serial}/send"
        payload = {"message": message}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("success", False)
                return False

    except Exception as e:
        self.logger.error(f"[FollowUp] Error sending directly: {e}")
        return False
```

### 4.5 更新设置 API

**文件**: `backend/routers/followup.py`

```python
class FollowUpSettingsRequest(BaseModel):
    """FollowUp 设置请求"""
    enabled: bool = True
    scan_interval: int = 60
    max_followups: int = 3
    initial_delay: int = 120
    subsequent_delay: int = 120
    use_exponential_backoff: bool = False
    backoff_multiplier: float = 2.0
    enable_operating_hours: bool = True
    start_hour: int = 10
    end_hour: int = 22
    use_ai_reply: bool = False
    enable_instant_response: bool = False
    send_via_sidecar: bool = True  # 新增


@router.get("/settings")
async def get_settings():
    """获取 FollowUp 设置"""
    service = get_followup_service()
    settings = service.get_settings()
    return {
        "enabled": settings.enabled,
        "scan_interval": settings.scan_interval,
        # ... 其他字段 ...
        "send_via_sidecar": settings.send_via_sidecar,  # 新增
    }


@router.post("/settings")
async def update_settings(request: FollowUpSettingsRequest):
    """更新 FollowUp 设置"""
    service = get_followup_service()
    await service.update_settings(
        enabled=request.enabled,
        scan_interval=request.scan_interval,
        # ... 其他字段 ...
        send_via_sidecar=request.send_via_sidecar,  # 新增
    )
    return {"success": True, "message": "Settings updated"}
```

---

## 前端代码实现

### 5.1 更新 FollowUpView 设置界面

**文件**: `src/views/FollowUpView.vue`

```vue
<script setup lang="ts">
// 在 settings ref 中添加新字段
const settings = ref({
  enabled: true,
  scanInterval: 60,
  maxFollowUps: 3,
  initialDelay: 120,
  subsequentDelay: 120,
  useExponentialBackoff: false,
  backoffMultiplier: 2,
  enableOperatingHours: true,
  startHour: 10,
  endHour: 22,
  useAIReply: false,
  enableInstantResponse: false,
  sendViaSidecar: true, // 新增
})
</script>

<template>
  <!-- 在 Settings Tab 中添加新选项 -->
  <div v-if="activeTab === 'settings'" class="space-y-6">
    <!-- AI Reply 设置部分 -->
    <div class="bg-wecom-dark/80 backdrop-blur rounded-xl p-6 border border-wecom-border">
      <h3 class="text-lg font-semibold text-wecom-text mb-4">AI Reply Settings</h3>

      <!-- 现有的 useAIReply 选项 -->
      <div class="space-y-4">
        <label class="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            v-model="settings.useAIReply"
            class="mt-1 w-4 h-4 rounded border-wecom-border bg-wecom-surface text-wecom-primary"
          />
          <div>
            <span class="text-wecom-text font-medium">Use AI Reply</span>
            <p class="text-xs text-wecom-muted mt-1">
              Use AI to generate personalized follow-up messages
            </p>
          </div>
        </label>

        <!-- 新增：Sidecar 模式选项 -->
        <label
          class="flex items-start gap-3 cursor-pointer"
          :class="{ 'opacity-50': !settings.useAIReply }"
        >
          <input
            type="checkbox"
            v-model="settings.sendViaSidecar"
            :disabled="!settings.useAIReply"
            class="mt-1 w-4 h-4 rounded border-wecom-border bg-wecom-surface text-wecom-primary"
          />
          <div>
            <span class="text-wecom-text font-medium">Send via Sidecar (Recommended)</span>
            <p class="text-xs text-wecom-muted mt-1">
              AI-generated replies will be added to the Sidecar queue for manual review before
              sending. This ensures you can edit or cancel messages before they are sent.
            </p>
            <div
              v-if="!settings.sendViaSidecar && settings.useAIReply"
              class="mt-2 px-3 py-2 bg-amber-500/10 border border-amber-500/30 rounded-lg"
            >
              <p class="text-xs text-amber-400 flex items-center gap-1">
                ⚠️ Warning: Messages will be sent automatically without human review
              </p>
            </div>
          </div>
        </label>
      </div>
    </div>

    <!-- ... 其他设置 ... -->
  </div>
</template>
```

### 5.2 更新 SidecarView 队列显示

**文件**: `src/views/SidecarView.vue`

在队列消息显示中添加来源标记：

```vue
<template>
  <!-- 队列消息列表 -->
  <div v-for="msg in queuedMessages" :key="msg.id" class="queued-message">
    <!-- 新增：来源标记 -->
    <div class="flex items-center gap-2 mb-2">
      <span
        v-if="msg.source === 'followup'"
        class="px-2 py-0.5 text-xs font-medium rounded bg-blue-500/20 text-blue-400 border border-blue-500/30"
      >
        🔄 FOLLOWUP
      </span>
      <span
        v-else-if="msg.source === 'sync'"
        class="px-2 py-0.5 text-xs font-medium rounded bg-green-500/20 text-green-400 border border-green-500/30"
      >
        🔃 SYNC
      </span>
      <span
        v-else
        class="px-2 py-0.5 text-xs font-medium rounded bg-gray-500/20 text-gray-400 border border-gray-500/30"
      >
        ✍️ MANUAL
      </span>

      <span class="text-xs text-wecom-muted"> To: {{ msg.customerName }} </span>
    </div>

    <!-- 消息内容 -->
    <div class="message-content">
      {{ msg.message }}
    </div>

    <!-- 操作按钮 -->
    <div class="flex items-center gap-2 mt-3">
      <button @click="editMessage(msg)" class="btn-secondary text-sm">✏️ Edit</button>
      <button @click="cancelMessage(msg.id)" class="btn-secondary text-sm text-red-400">
        ✖️ Cancel
      </button>
      <button @click="sendMessage(msg.id)" class="btn-primary text-sm">📤 Send</button>
    </div>
  </div>
</template>

<style scoped>
.queued-message {
  @apply bg-wecom-surface/50 rounded-lg p-4 border border-wecom-border;
}

.message-content {
  @apply bg-wecom-dark/60 rounded-lg p-3 text-wecom-text text-sm whitespace-pre-wrap;
}
</style>
```

### 5.3 更新 API 类型定义

**文件**: `src/services/api.ts`

```typescript
export interface QueuedMessage {
  id: string
  serial: string
  customerName: string
  channel?: string
  message: string
  timestamp: number
  status: 'pending' | 'ready' | 'sending' | 'sent' | 'failed' | 'cancelled'
  error?: string
  source: 'manual' | 'sync' | 'followup' // 新增
}

export interface FollowUpSettings {
  enabled: boolean
  scanInterval: number
  maxFollowUps: number
  initialDelay: number
  subsequentDelay: number
  useExponentialBackoff: boolean
  backoffMultiplier: number
  enableOperatingHours: boolean
  startHour: number
  endHour: number
  useAIReply: boolean
  enableInstantResponse: boolean
  sendViaSidecar: boolean // 新增
}
```

---

## 文件变更清单

### 后端

| 文件                                            | 操作 | 说明                                             |
| ----------------------------------------------- | ---- | ------------------------------------------------ |
| `backend/routers/sidecar.py`                    | 修改 | 添加 `source` 字段到 `QueuedMessageModel` 和 API |
| `backend/servic../03-impl-and-arch/settings.py` | 修改 | 添加 `send_via_sidecar` 设置                     |
| `backend/servic../03-impl-and-arch/scanner.py`  | 修改 | 添加 `_add_to_sidecar_queue` 方法                |
| `backend/routers/followup.py`                   | 修改 | 更新设置 API 支持新字段                          |

### 前端

| 文件                         | 操作 | 说明                           |
| ---------------------------- | ---- | ------------------------------ |
| `src/views/FollowUpView.vue` | 修改 | 添加 `sendViaSidecar` 设置选项 |
| `src/views/SidecarView.vue`  | 修改 | 显示消息来源标记               |
| `src/services/api.ts`        | 修改 | 更新类型定义                   |

---

## 测试验证

### 6.1 测试用例

#### 测试 1：Sidecar 模式启用

1. 在 FollowUp Settings 中启用 "Send via Sidecar"
2. 启动 FollowUp 扫描
3. 等待检测到需要回复的客户
4. 验证：
   - 消息出现在 Sidecar 队列中
   - 消息带有 "FOLLOWUP" 标记
   - 消息**未**直接发送到设备

#### 测试 2：Sidecar 队列操作

1. 在 Sidecar 面板中看到 FollowUp 生成的消息
2. 测试编辑功能：修改消息内容
3. 测试取消功能：取消消息发送
4. 测试发送功能：确认发送消息
5. 验证消息正确发送到设备

#### 测试 3：直接发送模式

1. 在 FollowUp Settings 中禁用 "Send via Sidecar"
2. 验证警告信息显示
3. 启动 FollowUp 扫描
4. 验证消息直接发送，不经过 Sidecar 队列

### 6.2 验收标准

| 测试项   | 验收标准                             |
| -------- | ------------------------------------ |
| 设置选项 | 能够切换 "Send via Sidecar" 选项     |
| 队列添加 | FollowUp 消息正确添加到 Sidecar 队列 |
| 来源标记 | 队列消息显示 "FOLLOWUP" 来源标记     |
| 编辑功能 | 能够在发送前编辑消息                 |
| 取消功能 | 能够取消发送消息                     |
| 发送功能 | 确认后消息正确发送到设备             |
| 直接发送 | 禁用 Sidecar 后消息直接发送          |
| 警告提示 | 禁用 Sidecar 时显示警告              |

---

## 迁移步骤

### Step 1：后端改动

1. 修改 `sidecar.py` 添加 `source` 字段
2. 修改 `settings.py` 添加 `send_via_sidecar` 设置
3. 修改 `scanner.py` 添加 Sidecar 队列方法
4. 更新 `followup.py` 设置 API

### Step 2：前端改动

1. 更新 `FollowUpView.vue` 添加设置选项
2. 更新 `SidecarView.vue` 添加来源标记
3. 更新 `api.ts` 类型定义

### Step 3：测试

1. 运行测试用例
2. 验证 Sidecar 模式工作正常
3. 验证直接发送模式工作正常

---

## 总结

通过实现 Sidecar 集成，FollowUp 系统将：

1. **增加人工审核环节**：AI 生成的回复不会直接发送，需要人工确认
2. **允许编辑修改**：用户可以在发送前修改 AI 回复
3. **提供取消功能**：用户可以取消不合适的回复
4. **与 Sync 流程一致**：统一使用 Sidecar 队列，体验一致
5. **可配置**：用户可以选择是否使用 Sidecar 模式
