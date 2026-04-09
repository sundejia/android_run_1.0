# Sidecar Block Button Feature

## 功能概述

在 Sidecar 界面中添加一个 **Block（拉黑）** 按钮，允许操作员快速将当前对话用户添加到黑名单中。

## 业务背景

在 Sidecar 界面处理消息时，操作员可能需要将某些用户（如垃圾消息发送者、无效客户等）快速加入黑名单，避免后续的自动跟进。当前需要切换到黑名单页面才能操作，效率较低。

## 功能需求

### 用户故事

- 作为 Sidecar 操作员，我希望能够在消息面板中直接拉黑当前用户，以便快速排除不需要跟进的客户。

### 功能描述

1. 在每个 Sidecar 面板的操作区域添加一个 "Block" 按钮
2. 点击按钮后，弹出确认对话框（防止误操作）
3. 确认后调用后端 API 将用户添加到黑名单
4. 成功后显示状态提示，并自动跳过当前用户

## 技术设计

### 1. 前端修改

#### 1.1 SidecarView.vue 修改

**新增函数：**

```typescript
// 拉黑当前用户
async function blockCurrentUser(serial: string) {
  const panel = ensurePanel(serial)

  if (!panel.state?.conversation?.contact_name) {
    panel.statusMessage = 'No active conversation to block'
    return
  }

  const customerName = panel.state.conversation.contact_name
  const channel = panel.state.conversation.channel

  // 确认对话框
  if (!confirm(`确定要将 "${customerName}" 加入黑名单吗？\n\n该用户将不再收到自动跟进消息。`)) {
    return
  }

  panel.statusMessage = '正在加入黑名单...'

  try {
    const response = await fetch(`${API_BAS../03-impl-and-arch/key-modules/blacklist/add`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        device_serial: serial,
        customer_name: customerName,
        customer_channel: channel,
        reason: 'Manually blocked via Sidecar',
      }),
    })

    const result = await response.json()

    if (result.success) {
      panel.statusMessage = `🚫 已将 ${customerName} 加入黑名单`
      addDeviceLog(serial, 'INFO', `[Block] 已拉黑用户: ${customerName}`)

      // 自动跳过当前用户
      await skipDeviceSync(serial)
    } else {
      panel.statusMessage = result.message || '拉黑失败'
    }
  } catch (e) {
    panel.statusMessage = e instanceof Error ? e.message : '拉黑请求失败'
    addDeviceLog(serial, 'ERROR', `[Block] 拉黑失败: ${e}`)
  }
}
```

**UI 修改位置：**

在面板的操作按钮区域（Skip 按钮附近）添加 Block 按钮：

```vue
<!-- Block Button -->
<button
  v-if="panel.state?.conversation?.contact_name"
  @click="blockCurrentUser(serial)"
  class="btn-danger text-xs px-3 py-1.5"
  :disabled="!panel.state?.conversation?.contact_name"
  title="将当前用户加入黑名单"
>
  🚫 Block
</button>
```

### 2. 后端 API

**已有 API：**../03-impl-and-arch/key-modules/blacklist/add`（POST）

请求体：

```json
{
  "device_serial": "string",
  "customer_name": "string",
  "customer_channel": "string (optional)",
  "reason": "string (optional)",
  "deleted_by_user": false
}
```

响应：

```json
{
  "success": true,
  "message": "Added to blacklist"
}
```

### 3. 国际化

在 `translations.py` 中添加：

**英文：**

```python
"sidecar": {
    # ... existing keys
    "block": "Block",
    "block_confirm": "Are you sure you want to block \"{name}\"?\n\nThis user will no longer receive automated follow-up messages.",
    "block_success": "Blocked {name}",
    "block_failed": "Failed to block user",
    "block_no_conversation": "No active conversation to block",
    "blocking": "Blocking...",
}
```

**中文：**

```python
"sidecar": {
    # ... existing keys
    "block": "拉黑",
    "block_confirm": "确定要将 \"{name}\" 加入黑名单吗？\n\n该用户将不再收到自动跟进消息。",
    "block_success": "已将 {name} 加入黑名单",
    "block_failed": "拉黑失败",
    "block_no_conversation": "没有可拉黑的对话",
    "blocking": "正在拉黑...",
}
```

## 实现步骤

### 任务 1：添加翻译键（5分钟）✅ 已完成

- [x] 在 `backend/i18n/translations.py` 的 `sidecar` 分类中添加英文和中文翻译键

### 任务 2：添加 Block 按钮 UI（10分钟）✅ 已完成

- [x] 在 `SidecarView.vue` 的模板部分添加 Block 按钮
- [x] 按钮位置：Skip 按钮附近
- [x] 样式：使用 `btn-secondary` 类，hover 时变红
- [x] 只有当 `panel.state?.conversation?.contact_name` 存在时才启用

### 任务 3：实现 blockCurrentUser 函数（10分钟）✅ 已完成

- [x] 在 `SidecarView.vue` 的 `<script>` 部分添加 `blockCurrentUser` 函数
- [x] 添加确认对话框
- [x] 调用../03-impl-and-arch/key-modules/blacklist/add` API
- [x] 成功后自动调用 `skipDeviceSync`

### 任务 4：测试验证（5分钟）

- [ ] 启动前后端
- [ ] 在 Sidecar 中打开设备
- [ ] 验证 Block 按钮只在有对话时显示
- [ ] 点击 Block 按钮确认功能正常
- [ ] 检查黑名单页面确认用户已添加

## 文件修改清单

| 文件路径                                     | 修改类型 | 描述                                    |
| -------------------------------------------- | -------- | --------------------------------------- |
| `wecom-desktop/src/views/SidecarView.vue`    | 修改     | 添加 Block 按钮和 blockCurrentUser 函数 |
| `wecom-desktop/backend/i18n/translations.py` | 修改     | 添加 sidecar.block 相关翻译键           |

## UI/UX 设计

### 按钮位置

```
┌─────────────────────────────────────────────────────┐
│  [用户名] @ [渠道]                          [X Close]│
├─────────────────────────────────────────────────────┤
│                                                     │
│  [对话历史区域]                                      │
│                                                     │
├─────────────────────────────────────────────────────┤
│  [消息输入框]                                        │
├─────────────────────────────────────────────────────┤
│  [Generate] [Send] [Skip] [🚫 Block]   [倒计时进度]   │
└─────────────────────────────────────────────────────┘
```

### 按钮样式

- **颜色**：红色（`btn-danger`）表示危险操作
- **图标**：🚫 禁止符号
- **大小**：与 Skip 按钮相同（`text-xs px-3 py-1.5`）
- **状态**：
  - 禁用：没有活跃对话时
  - 加载中：正在执行拉黑操作时

## 安全考虑

1. **确认对话框**：防止误操作
2. **日志记录**：记录所有拉黑操作到设备日志
3. **权限控制**：通过设备序列号限制只能拉黑当前设备的用户

## 后续优化

1. 添加撤销功能（在一定时间内可撤销拉黑）
2. 添加快捷键支持（如 `Ctrl+B` 快速拉黑）
3. 批量拉黑功能
