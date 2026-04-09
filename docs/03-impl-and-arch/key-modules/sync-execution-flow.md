# Sync Execution Flow / 同步执行流程

本文档详细描述了点击 "Sync" 按钮后的完整执行逻辑。

## 架构概览 / Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Frontend (Vue.js)                              │
│  DeviceCard.vue → devices.ts store → API call                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ HTTP POST /sync/start/{serial}
┌─────────────────────────────────────────────────────────────────────────┐
│                        Backend (FastAPI)                                 │
│  routers/sync.py → DeviceManager.start_sync()                           │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ subprocess: uv run initial_sync.py
┌─────────────────────────────────────────────────────────────────────────┐
│                     Sync Process (Python)                                │
│  initial_sync.py → InitialSyncService → WeComService → ADBService       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ ADB commands
┌─────────────────────────────────────────────────────────────────────────┐
│                        Android Device                                    │
│  WeCom App (企业微信)                                                    │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 1. 前端触发 / Frontend Trigger

### 1.1 用户点击 Sync 按钮

**文件**: `wecom-desktop/src/components/DeviceCard.vue`

```vue
<button @click="$emit('sync', device.serial)">
  🔄 Sync
</button>
```

### 1.2 Store 处理

**文件**: `wecom-desktop/src/stores/devices.ts`

```typescript
async function startSync(serial: string, options?: SyncOptions) {
  // 设置状态为 starting
  syncStatuses.value.set(serial, {
    status: 'starting',
    progress: 0,
    message: 'Starting sync...',
  })

  // 连接 WebSocket 获取实时状态更新
  connectSyncStatusStream(serial)

  // 调用 API 启动同步
  await api.startSync(serial, options)
}
```

### 1.3 API 调用

**文件**: `wecom-desktop/src/services/api.ts`

```typescript
async startSync(serial: string, options?: SyncOptions) {
  return fetch(`${BASE_URL}/sync/start/${serial}`, {
    method: 'POST',
    body: JSON.stringify(options)
  })
}
```

---

## 2. 后端处理 / Backend Processing

### 2.1 路由接收请求

**文件**: `wecom-desktop/backend/routers/sync.py`

```python
@router.post("/start/{serial}")
async def start_sync(serial: str, options: SyncOptions = None):
    """启动设备同步"""
    success = await device_manager.start_sync(
        serial=serial,
        timing_multiplier=options.timing_multiplier,
        auto_placeholder=options.auto_placeholder,
        # ... 其他参数
    )
    return {"success": success}
```

### 2.2 DeviceManager 启动同步

**文件**: `wecom-desktop/backend/services/device_manager.py`

```python
async def start_sync(self, serial: str, ...):
    # 1. 检查是否已在运行
    if serial in self._processes:
        return False

    # 2. 初始化状态
    self._sync_states[serial] = SyncState(
        status=SyncStatus.STARTING,
        message="Initializing sync...",
    )

    # 3. 构建命令
    cmd = [
        "uv", "run",
        str(PROJECT_ROOT / "initial_sync.py"),
        "--serial", serial,
        "--timing-multiplier", str(timing_multiplier),
        "--auto-placeholder",
        "--debug",
    ]

    # 4. 启动子进程
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(PROJECT_ROOT),
    )

    # 5. 启动输出读取任务
    asyncio.create_task(self._read_output(serial, process.stdout))
    asyncio.create_task(self._read_output(serial, process.stderr))
```

### 2.3 日志解析与进度更新

**文件**: `wecom-desktop/backend/services/device_manager.py`

```python
async def _parse_and_update_state(self, serial: str, message: str, level: str):
    """解析日志消息并更新同步状态"""

    # 进度阶段划分:
    # 0-10%:  预扫描阶段 (初始化、导航、客户提取)
    # 10-100%: 对话扫描阶段 (按客户数量比例)

    if "Ensuring WeCom is open" in message:
        new_progress = 1
        new_message = "Opening WeCom..."

    elif "Found X customers" in message:
        new_progress = 10
        state._total_customers = X

    elif "Processing customer X/Y" in message:
        # 计算进度: 10% + 90% * (已完成 / 总数)
        new_progress = 10 + int(90 * completed / total)

    # 广播状态更新
    await self._broadcast_status(serial)
```

### 2.4 WebSocket 状态广播

**文件**: `wecom-desktop/backend/routers/logs.py`

```python
@router.websocket("/ws/sync/{serial}")
async def websocket_sync_status(websocket: WebSocket, serial: str):
    """WebSocket 端点 - 实时同步状态更新"""
    await websocket.accept()

    async def status_callback(status: dict):
        await websocket.send_json(status)

    device_manager.register_status_callback(serial, status_callback)
```

---

## 3. 同步进程执行 / Sync Process Execution

### 3.1 入口脚本

**文件**: `initial_sync.py`

```python
async def run(args):
    # 1. 初始化同步服务
    sync_service = InitialSyncService(
        config=config,
        db_path=args.db,
        images_dir=args.images_dir,
        timing_multiplier=args.timing_multiplier,
    )

    # 2. 运行同步
    stats = await sync_service.run_initial_sync(
        send_test_messages=not args.no_test_messages,
        prioritize_unread=args.prioritize_unread,
        unread_only=args.unread_only,
    )

    # 3. 输出结果
    print(f"Customers synced: {stats['customers_synced']}")
    print(f"Messages added: {stats['messages_added']}")
```

### 3.2 InitialSyncService 主流程

**文件**: `src/wecom_automation/services/sync_service.py`

```python
async def run_initial_sync(self, ...):
    """完整同步工作流"""

    # ========== 步骤 1: 确保 WeCom 打开 ==========
    await self._ensure_wecom_open()

    # ========== 步骤 2: 获取客服信息 ==========
    kefu_info = await self.wecom.get_kefu_name()
    # 从界面顶部提取当前登录的客服名称

    # ========== 步骤 3: 设置数据库记录 ==========
    await self._setup_device_and_kefu(kefu_info)
    # 创建或获取 Device 和 Kefu 记录

    # ========== 步骤 4: 导航到私聊列表 ==========
    await self.wecom.switch_to_private_chats()
    # 点击 "私聊" 过滤器

    # ========== 步骤 5: 提取未读用户 (可选) ==========
    if prioritize_unread:
        unread_infos = await self._extract_unread_users()
        # 滚动列表，检测红点徽章

    # ========== 步骤 6: 提取客户列表 ==========
    extraction_result = await self.wecom.extract_private_chat_users()
    customers = extraction_result.users

    # ========== 步骤 7: 排序客户 (按未读优先) ==========
    if prioritize_unread:
        customers = sort_by_unread(customers, unread_infos)

    # ========== 步骤 8: 同步每个客户的对话 ==========
    for user in customers:
        await self._sync_customer_conversation(user)
```

### 3.3 单个客户对话同步

**文件**: `src/wecom_automation/services/sync_service.py`

```python
async def _sync_customer_conversation(self, user: UserDetail):
    """同步单个客户的所有消息"""

    # 1. 创建客户记录
    customer = self.repository.get_or_create_customer(
        name=user.name,
        kefu_id=self._current_kefu.id,
    )

    # 2. 点击用户打开对话
    await self.wecom.click_user_in_list(user.name)

    # 3. 确保键盘模式 (非语音模式)
    await self._ensure_keyboard_mode()

    # 4. 提取所有消息
    result = await self.wecom.extract_conversation_messages(
        download_images=True,
        download_videos=True,
        download_voices=True,
    )

    # 5. 处理并存储消息
    for msg in result.messages:
        # 解析时间戳
        timestamp = self.timestamp_parser.parse(msg.timestamp_text)

        # 保存到数据库
        self.repository.add_message(
            customer_id=customer.id,
            content=msg.content,
            timestamp=timestamp,
            is_from_customer=msg.is_from_customer,
        )

        # 保存图片/视频/语音
        if msg.image_data:
            self._save_image(msg)
        if msg.video_path:
            self._save_video(msg)
        if msg.voice_data:
            self._save_voice(msg)

    # 6. 发送测试消息 (可选)
    if send_test_messages:
        await self._send_test_message(user)

    # 7. 返回私聊列表
    await self.wecom.go_back()
```

---

## 4. ADB 交互层 / ADB Interaction Layer

### 4.1 WeComService

**文件**: `src/wecom_automation/services/wecom_service.py`

提供高级 WeCom 操作:

| 方法                              | 功能             |
| --------------------------------- | ---------------- |
| `launch_wecom()`                  | 启动 WeCom 应用  |
| `switch_to_private_chats()`       | 切换到私聊过滤器 |
| `extract_private_chat_users()`    | 提取用户列表     |
| `click_user_in_list()`            | 点击用户打开对话 |
| `extract_conversation_messages()` | 提取对话消息     |
| `go_back()`                       | 返回上一页       |

### 4.2 ADBService

**文件**: `src/wecom_automation/services/adb_service.py`

提供底层 ADB 操作:

| 方法                    | 功能               |
| ----------------------- | ------------------ |
| `get_ui_tree()`         | 获取 UI 可访问性树 |
| `tap_coordinates(x, y)` | 点击屏幕坐标       |
| `scroll_down()`         | 向下滚动           |
| `scroll_to_top()`       | 滚动到顶部         |
| `input_text()`          | 输入文本           |
| `take_screenshot()`     | 截图               |

---

## 5. 数据流 / Data Flow

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   WeCom UI   │ ──▶ │   UI Tree    │ ──▶ │   Parser     │
│   (Android)  │     │   (JSON)     │     │   Service    │
└──────────────┘     └──────────────┘     └──────────────┘
                                                  │
                                                  ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   SQLite     │ ◀── │  Repository  │ ◀── │   Models     │
│   Database   │     │              │     │              │
└──────────────┘     └──────────────┘     └──────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────┐
│                    数据库表结构                        │
├──────────────┬──────────────┬──────────────┬─────────┤
│   devices    │    kefus     │  customers   │ messages │
├──────────────┼──────────────┼──────────────┼─────────┤
│ - id         │ - id         │ - id         │ - id     │
│ - serial     │ - name       │ - name       │ - content│
│ - model      │ - device_id  │ - kefu_id    │ - time   │
│ - created_at │ - department │ - channel    │ - sender │
└──────────────┴──────────────┴──────────────┴─────────┘
```

---

## 6. 进度追踪 / Progress Tracking

### 进度百分比计算

| 阶段       | 进度范围 | 描述                     |
| ---------- | -------- | ------------------------ |
| 初始化     | 0-3%     | 打开 WeCom, 获取客服信息 |
| 数据库设置 | 3-5%     | 设置数据库记录           |
| 导航       | 5-8%     | 切换到私聊列表           |
| 客户提取   | 8-10%    | 提取客户列表             |
| 对话同步   | 10-100%  | 按客户数量比例           |

### 对话同步子步骤

每个客户同步分为 5 个子步骤:

1. **开始** (0/5): 点击用户
2. **提取** (1/5): 提取消息
3. **处理** (2/5): 处理和存储
4. **测试** (3/5): 发送测试消息
5. **返回** (4/5): 返回列表

---

## 7. 错误处理 / Error Handling

### 7.1 可恢复错误

```python
# 用户未找到 - 跳过此用户
if not await self.wecom.click_user_in_list(user.name):
    self.logger.warning(f"Could not find user {user.name}")
    continue

# 网络错误 - 重试
for attempt in range(3):
    try:
        tree = await self.adb.get_ui_tree()
        break
    except Exception:
        await asyncio.sleep(1)
```

### 7.2 致命错误

```python
# 无法获取客服信息 - 终止同步
kefu_info = await self.wecom.get_kefu_name()
if not kefu_info:
    raise RuntimeError("Could not get kefu information")
```

### 7.3 恢复机制

```python
async def _recover_to_private_chats(self):
    """错误后恢复到私聊列表"""
    # 多次返回确保退出对话
    for _ in range(3):
        await self.wecom.go_back()

    # 重新导航到私聊
    await self.wecom.switch_to_private_chats()
```

---

## 8. 文件结构 / File Structure

```
android_run_test-main/
├── initial_sync.py                 # 入口脚本
├── wecom-desktop/
│   ├── src/
│   │   ├── components/
│   │   │   └── DeviceCard.vue      # 设备卡片 UI
│   │   ├── stores/
│   │   │   └── devices.ts          # 设备状态管理
│   │   └── services/
│   │       └── api.ts              # API 客户端
│   └── backend/
│       ├── routers/
│       │   ├── sync.py             # 同步 API 路由
│       │   └── logs.py             # WebSocket 日志
│       └── services/
│           └── device_manager.py   # 设备管理器
└── src/wecom_automation/
    ├── services/
    │   ├── sync_service.py         # 同步服务
    │   ├── wecom_service.py        # WeCom 操作
    │   └── adb_service.py          # ADB 操作
    └── database/
        ├── models.py               # 数据模型
        └── repository.py           # 数据仓库
```

---

## 9. 配置选项 / Configuration Options

| 参数                | 类型  | 默认值 | 描述                  |
| ------------------- | ----- | ------ | --------------------- |
| `timing_multiplier` | float | 1.0    | 延迟倍数 (>1 更慢)    |
| `auto_placeholder`  | bool  | true   | 语音消息使用占位符    |
| `no_test_messages`  | bool  | false  | 跳过测试消息          |
| `prioritize_unread` | bool  | false  | 优先同步未读消息      |
| `unread_only`       | bool  | false  | 仅同步未读用户        |
| `send_via_sidecar`  | bool  | false  | 通过 Sidecar 发送消息 |

---

## 10. 日志示例 / Log Examples

```
24:14:56 [INFO]  sync: Starting sync: uv run initial_sync.py --serial AN2FVB1706003302
24:14:58 [INFO]  sync: Step 1: Ensuring WeCom is open...
24:15:00 [INFO]  sync: Step 2: Getting kefu information...
24:15:02 [INFO]  sync: Current kefu: 张三
24:15:03 [INFO]  sync: Step 3: Setting up database records...
24:15:04 [INFO]  sync: Step 4: Navigating to private chats...
24:15:06 [INFO]  sync: Step 5: Extracting customer list...
24:15:10 [INFO]  sync: Found 25 customers
24:15:10 [INFO]  sync: Step 6: Syncing customer conversations...
24:15:12 [INFO]  sync: Processing customer 1/25: 李四
24:15:20 [INFO]  sync: Extracted 42 messages for 李四
24:15:22 [INFO]  sync: Processing customer 2/25: 王五
...
24:25:30 [INFO]  sync: SYNC COMPLETE
24:25:30 [INFO]  sync: Customers synced: 25
24:25:30 [INFO]  sync: Messages added: 856
```
