# 邮件通知发送时机

本文档描述了系统中发送邮件通知的所有时机和触发条件。

## 概述

系统支持两种邮件通知触发条件，可在设置界面中分别开启/关闭：

| 触发条件       | 设置项                      | 说明                            |
| -------------- | --------------------------- | ------------------------------- |
| 用户发语音时   | `emailNotifyOnVoice`        | 客户发送语音消息时触发          |
| 用户要转人工时 | `emailNotifyOnHumanRequest` | AI 检测到用户想转人工服务时触发 |

---

## 触发时机详解

### 1. 用户发送语音消息

**触发条件：** 客户（非客服）发送语音消息

**触发位置：**

#### A. 全量同步模式 (`initial_sync.py`)

```python
# initial_sync.py - on_customer_voice 回调函数
def on_customer_voice(customer_name: str, channel: Optional[str], serial: str):
    """当客户发送语音消息时触发"""
    # 1. 记录日志
    logger.warning(f"🎤 Customer {customer_name} sent a voice message!")

    # 2. 检查是否启用语音通知
    if not voice_email_config.get("notify_on_voice", False):
        return

    # 3. 加入黑名单
    _add_to_blacklist(customer_name, channel, serial)

    # 4. 发送邮件通知
    send_voice_notification_email(customer_name, channel, serial)
```

#### B. Sidecar 模式 (`SidecarView.vue`)

```typescript
// SidecarView.vue - checkForVoiceMessage 函数
const checkForVoiceMessage = async (panel, serial) => {
  // 检测到客户发送语音消息
  if (hasVoiceMessage && settings.value.emailNotifyOnVoice) {
    // 调用后端 API
    await api.reportVoiceMessage(customerName, serial, channel)
  }
}
```

**后端处理：** `POS../03-impl-and-arch/key-modules/email/voice-message`

```python
# email.py - handle_voice_message 端点
async def handle_voice_message(request):
    # 1. 加入黑名单
    _add_to_blacklist(request.customer_name, request.channel, request.serial)

    # 2. 发送邮件（如果启用）
    if email_config.get("notify_on_voice"):
        send_email(...)
```

---

### 2. 用户要求转人工

**触发条件：** AI 返回 `"command back to user operation"` 特殊指令

**检测逻辑：**

```python
# AIReplyService 中的检测
HUMAN_REQUEST_COMMAND = "command back to user operation"

# AI 返回的文本如果等于这个命令，表示用户想转人工
if reply.strip().lower() == HUMAN_REQUEST_COMMAND.lower():
    # 触发人工请求处理
```

**触发位置：**

#### A. 全量同步模式 (`initial_sync.py`)

```python
# AIReplyService.get_ai_reply 方法
async def get_ai_reply(self, message, serial, customer_name, channel, ...):
    reply = await self._call_ai_server(...)

    # 检测是否是人工请求
    if self.is_human_request(reply):
        # 1. 加入黑名单
        self.add_to_blacklist(customer_name, channel, serial)

        # 2. 发送邮件通知（如果启用）
        if self.email_config.get("notify_on_human_request", True):
            self.send_human_request_email(customer_name, channel, serial)

        # 3. 返回特殊标记
        return "__HUMAN_REQUEST__"
```

#### B. Sidecar 模式 (`SidecarView.vue`)

```typescript
// SidecarView.vue - generateReply 函数
const generateReply = async (panel, serial) => {
  const aiResult = await aiService.processTestMessage(...)

  // AI 检测到用户想转人工
  if (aiResult.humanRequested) {
    // 调用后端 API
    await api.reportHumanRequest(customerName, serial, channel, 'AI detected user wants human agent')
  }
}
```

**后端处理：** `POS../03-impl-and-arch/key-modules/email/human-request`

```python
# email.py - handle_human_request 端点
async def handle_human_request(request):
    # 1. 加入黑名单
    _add_to_blacklist(request.customer_name, request.channel, request.serial)

    # 2. 发送邮件（如果启用）
    if email_config.get("notify_on_human_request"):
        send_email(...)
```

---

## 邮件内容

### 语音消息通知邮件

- **主题：** `🎤 用户发语音通知 - {客户名称}`
- **内容：**
  - 客户名称
  - 渠道
  - 设备序列号
  - 时间
  - 警告：系统已自动将该用户加入黑名单

### 人工请求通知邮件

- **主题：** `🙋 用户请求转人工: {客户名称}`
- **内容：**
  - 客户名称
  - 渠道
  - 设备序列号
  - 时间
  - 警告：系统已自动将该用户加入黑名单

---

## 黑名单机制

当触发邮件通知时，用户会同时被加入黑名单。

> **说明（2026-01）**：黑名单已迁移到数据库，不再使用 JSON 文件。详见 [blacklist-database-migration.md](../03-impl-and-arch/experiments/blacklist-database-migration.md)。数据存储在 `wecom_conversations.db` 的 `blacklist` 表中，通过 `services/blacklist_service.py` 的 `BlacklistService` 读写。

**黑名单效果：**

- 全量同步时跳过黑名单中的用户（由 `BlacklistChecker.is_blacklisted()` 查询数据库）
- Sidecar 模式会显示警告但不会自动跳过

---

## 设置界面配置

在 Settings 页面的 "📧 Email Notification Settings" 部分：

1. **启用邮件通知** - 总开关
2. **SMTP 服务器** - 如 `smtp.qq.com`
3. **SMTP 端口** - 如 `465` (SSL)
4. **发件人邮箱** - QQ 邮箱地址
5. **发件人密码** - QQ 邮箱授权码
6. **发件人名称** - 邮件中显示的名称
7. **收件人邮箱** - 接收通知的邮箱
8. **通知触发条件：**
   - ☑️ 用户发语音时
   - ☑️ 用户要转人工时

---

## 流程图

```
┌─────────────────────────────────────────────────────────────────┐
│                        同步过程                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              ┌───────────────────────────────┐
              │      处理客户消息              │
              └───────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
    ┌──────────┐       ┌──────────┐        ┌──────────┐
    │ 文本消息  │       │ 语音消息  │        │ 其他消息  │
    └──────────┘       └──────────┘        └──────────┘
          │                   │
          ▼                   ▼
    ┌──────────┐       ┌─────────────────┐
    │ AI 处理   │       │ 检查语音通知设置 │
    └──────────┘       └─────────────────┘
          │                   │
          ▼                   │ (如果启用)
    ┌──────────────┐          ▼
    │ AI 返回结果   │    ┌─────────────┐
    └──────────────┘    │ 发送邮件     │
          │             │ 加入黑名单   │
          ▼             └─────────────┘
    ┌──────────────┐
    │ 是否要转人工？ │
    └──────────────┘
          │
     是   │   否
          ▼
    ┌─────────────────┐
    │ 检查人工请求通知  │
    └─────────────────┘
          │
          │ (如果启用)
          ▼
    ┌─────────────┐
    │ 发送邮件     │
    │ 加入黑名单   │
    └─────────────┘
```

---

## 相关文件

| 文件                                        | 说明                                 |
| ------------------------------------------- | ------------------------------------ |
| `initial_sync.py`                           | 全量同步中的邮件发送逻辑             |
| `wecom-desktop/backend/routers/email.py`    | 邮件相关 API 端点                    |
| `wecom-desktop/src/views/SidecarView.vue`   | Sidecar 模式的邮件触发               |
| `wecom-desktop/src/views/SettingsView.vue`  | 邮件设置界面                         |
| `wecom-desktop/src/stores/settings.ts`      | 邮件设置状态管理                     |
| `wecom-desktop/src/services/api.ts`         | 前端 API 调用方法                    |
| 数据库 `blacklist` 表 / `BlacklistService`  | 黑名单存储（已由 JSON 迁移至数据库） |
| `wecom-desktop/backend/email_settings.json` | 邮件配置存储文件                     |
