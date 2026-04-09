# 简化恢复功能实现计划

## 概述

基于现有的 Resume Sync 按钮，实现设备断连后的同步恢复功能。**不增加额外的UI界面**。

## 核心需求

1. **断连后能恢复**
   - 设备断开时自动保存检查点
   - 重新连接后点击 Resume Sync 继续

2. **利用现有UI**
   - 使用现有的 Resume Sync 按钮
   - 不新增对话框、通知栏等UI组件

## 当前架构

```
┌─────────────────────────────────────────────────────────────┐
│                    RecoveryManager (SQLite)                  │
├─────────────────────────────────────────────────────────────┤
│  recovery_state 表                                          │
│  ├─ task_id          任务唯一标识                           │
│  ├─ task_type        任务类型 (full_sync)                   │
│  ├─ device_serial    设备序列号                              │
│  ├─ status           状态 (running/pending_recovery)        │
│  ├─ checkpoint_data  检查点数据 (JSON)                       │
│  │   ├─ synced_customers     已同步客户列表                  │
│  │   ├─ current_customer     断开时正在同步的客户            │
│  │   ├─ last_screen_state    断开时的界面状态                │
│  │   └─ stats                统计信息                       │
│  ├─ progress_percent 进度百分比                              │
│  └─ last_checkpoint_at 最后检查点时间                        │
└─────────────────────────────────────────────────────────────┘
```

## Resume Sync 恢复流程

### 详细流程图

```
用户点击 Resume Sync
        │
        ▼
┌─────────────────────┐
│ 1. 检测当前界面状态  │
│    get_current_screen()
└─────────┬───────────┘
          │
          ▼
    ┌─────────────┐
    │ 当前在哪里？ │
    └─────┬───────┘
          │
    ┌─────┴─────┬──────────────┬──────────────┐
    ▼           ▼              ▼              ▼
  聊天界面    私聊列表      其他界面      未知界面
    │           │              │              │
    ▼           │              ▼              ▼
  go_back()     │         导航到私聊      尝试导航
    │           │              │              │
    └───────────┴──────────────┴──────────────┘
                        │
                        ▼
          ┌─────────────────────────┐
          │ 2. 加载检查点数据        │
          │    - synced_customers   │
          │    - current_customer   │
          └─────────┬───────────────┘
                    │
                    ▼
          ┌─────────────────────────┐
          │ 3. 处理中断的客户        │
          │    (current_customer)   │
          │    如果有未完成客户:     │
          │    - 找到该客户         │
          │    - 进入对话           │
          │    - 完成同步           │
          └─────────┬───────────────┘
                    │
                    ▼
          ┌─────────────────────────┐
          │ 4. 正常流程继续          │
          │    - 检测红点用户        │
          │    - 跳过已同步客户      │
          │    - 继续全量同步        │
          └─────────────────────────┘
```

### 界面状态检测

```python
async def get_current_screen(self) -> str:
    """
    检测当前手机界面状态

    Returns:
        'chat': 在聊天对话界面
        'private_chats': 在私聊列表
        'other': 在其他界面 (设置、联系人等)
        'unknown': 无法识别
    """
    tree = await self.adb.get_ui_tree()

    # 检测聊天界面特征: 有返回按钮 + 输入框
    if self._has_chat_indicators(tree):
        return 'chat'

    # 检测私聊列表特征: 有"私聊"标签
    if self._has_private_chat_list_indicators(tree):
        return 'private_chats'

    # 检测其他界面
    if self._is_in_wecom_app(tree):
        return 'other'

    return 'unknown'
```

### 恢复实现代码

```python
async def resume_sync(self, checkpoint_data: dict) -> SyncResult:
    """
    从检查点恢复同步

    Args:
        checkpoint_data: 检查点数据，包含:
            - synced_customers: 已同步客户列表
            - current_customer: 断开时正在同步的客户
            - stats: 统计信息
    """
    synced_customers = checkpoint_data.get('synced_customers', [])
    current_customer = checkpoint_data.get('current_customer')

    # ========== 步骤1: 检测并恢复到正确界面 ==========
    self._logger.info("Step 1: Detecting current screen state...")

    screen_state = await self.get_current_screen()
    self._logger.info(f"Current screen: {screen_state}")

    if screen_state == 'chat':
        # 在聊天界面，需要先返回
        self._logger.info("In chat screen, going back...")
        await self._wecom.go_back()
        await asyncio.sleep(0.5)

    elif screen_state == 'other':
        # 在其他界面，导航到私聊列表
        self._logger.info("In other screen, navigating to private chats...")
        await self._wecom.switch_to_private_chats()
        await asyncio.sleep(0.5)

    elif screen_state == 'unknown':
        # 未知界面，尝试启动企微并导航
        self._logger.warning("Unknown screen, launching WeCom...")
        await self._wecom.ensure_app_running()
        await self._wecom.switch_to_private_chats()

    # ========== 步骤2: 处理中断的客户 ==========
    if current_customer and current_customer not in synced_customers:
        self._logger.info(f"Step 2: Completing interrupted customer: {current_customer}")

        # 找到并点击该客户
        success = await self._wecom.click_user_in_list(current_customer)
        if success:
            # 完成该客户的同步
            result = await self._sync_single_customer(current_customer)
            if result.success:
                synced_customers.append(current_customer)
                self._save_checkpoint()
        else:
            self._logger.warning(f"Could not find interrupted customer: {current_customer}")

    # ========== 步骤3: 正常流程继续 ==========
    self._logger.info("Step 3: Resuming normal sync flow...")

    # 检测红点用户
    unread_users = await self._detect_unread_users()
    self._logger.info(f"Found {len(unread_users)} users with unread messages")

    # 获取待同步客户列表（排除已同步的）
    all_customers = await self._get_customer_list()
    pending_customers = [
        c for c in all_customers
        if c.name not in synced_customers
    ]

    self._logger.info(
        f"Resuming: {len(synced_customers)} done, "
        f"{len(pending_customers)} remaining"
    )

    # 继续全量同步
    return await self._sync_customers(
        customers=pending_customers,
        skip_already_synced=synced_customers,
        unread_priority=unread_users,
    )
```

## 检查点数据结构

```python
checkpoint_data = {
    # 已完成同步的客户列表
    "synced_customers": ["客户A", "客户B", "客户C"],

    # 断开时正在处理的客户（可能未完成）
    "current_customer": "客户D",

    # 断开时的界面状态
    "last_screen_state": "chat",  # chat / private_chats / other

    # 统计信息
    "stats": {
        "total_customers": 100,
        "synced_count": 45,
        "messages_added": 230,
        "progress_percent": 45
    },

    # 时间戳
    "timestamp": "2026-01-02T10:30:00",
    "device_serial": "AMFU6R1622014533"
}
```

## 设备断开时保存

```python
# orchestrator.py - 同步循环中

for customer in customer_queue:
    customer_name = customer.name

    # 更新当前客户（用于断点恢复）
    self._current_customer = customer_name

    try:
        result = await self._sync_single_customer(customer)

        if result.success:
            self._synced_customers.append(customer_name)
            self._current_customer = None  # 完成后清除
            self._save_checkpoint()

    except Exception as e:
        # 检测设备断开
        if is_device_disconnected_error(e):
            self._logger.error("Device disconnected!")
            # 保存检查点（包含当前未完成的客户）
            self._save_checkpoint_with_current(customer_name)
            break
```

## 用户流程

```
1. 用户点击 Sync Selected 开始全量同步
2. 同步进行中... (正在同步 "客户D", 已完成45%)
3. 设备断开 (USB 拔出)
4. 系统保存检查点:
   - synced_customers: [客户A, 客户B, 客户C]
   - current_customer: 客户D
   - last_screen_state: chat
5. 同步停止，显示错误

--- 用户重新连接设备 ---

6. 用户点击 Resume Sync
7. 系统检测当前界面 -> 发现在聊天界面
8. 系统执行 go_back() 返回私聊列表
9. 找到"客户D"，进入对话，完成同步
10. 检测红点用户
11. 跳过已同步的 A/B/C/D，继续同步 E/F/G...
12. 同步完成 (100%)
```

## 实现步骤

| 步骤     | 内容                                  | 预计时间    |
| -------- | ------------------------------------- | ----------- |
| 1        | 添加 `is_device_disconnected_error()` | 15分钟      |
| 2        | 添加 `get_current_screen()` 界面检测  | 30分钟      |
| 3        | 修改检查点保存，包含 current_customer | 20分钟      |
| 4        | 实现 `resume_sync()` 恢复逻辑         | 45分钟      |
| 5        | 修改 orchestrator 断开时保存          | 20分钟      |
| 6        | 测试完整恢复流程                      | 30分钟      |
| **总计** |                                       | **2.5小时** |

## 不实现的功能

以下功能暂不实现（保持简单）：

- ❌ 应用启动时自动弹出恢复对话框
- ❌ 设备重连时的通知提示
- ❌ 多任务恢复列表
- ❌ 全局恢复检测 Hook

## 总结

此方案实现：

1. ✅ **利用现有UI** - 只使用 Resume Sync 按钮
2. ✅ **智能界面恢复** - 检测当前界面，自动导航到正确位置
3. ✅ **完成中断任务** - 先完成断开时正在处理的客户
4. ✅ **无缝继续** - 之后按正常流程检测红点、继续同步
5. ✅ **实现简单** - 约2.5小时完成
