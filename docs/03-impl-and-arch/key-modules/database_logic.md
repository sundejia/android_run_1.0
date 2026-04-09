# WeCom 自动化系统数据库逻辑文档

## 1. 概述

本文档详细描述了 WeCom 自动化系统中数据存储的逻辑、数据库结构、数据流程以及关键组件之间的交互关系。

## 2. 数据库配置

### 2.1 数据库类型

- **数据库引擎**: SQLite3
- **控制库**: `WECOM_DB_PATH` / 项目根目录 `wecom_conversations.db`
- **设备会话库**: `device_storage/<serial>/wecom_conversations.db`

### 2.2 数据库位置

数据库路径解析分为两层：

1. **控制平面数据库**
   - 用于 settings / orchestration metadata
   - 路径优先级：显式指定的 `db_path` 参数 -> 环境变量 `WECOM_DB_PATH` -> 项目根目录 `wecom_conversations.db`

2. **会话数据数据库**
   - 用于 customers / messages / images / videos / blacklist 等业务数据
   - 路径优先级：显式指定的 `db_path` 参数 -> 设备默认路径 `device_storage/<serial>/wecom_conversations.db`

**相关代码**: `src/wecom_automation/database/schema.py`, `wecom-desktop/backend/services/conversation_storage.py`

```python
# 控制库默认路径
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = PROJECT_ROOT / "wecom_conversations.db"
```

```python
# 设备会话库默认路径
DEVICE_STORAGE_ROOT = PROJECT_ROOT / "device_storage"
DEVICE_DB_FILENAME = "wecom_conversations.db"
device_db = DEVICE_STORAGE_ROOT / serial / DEVICE_DB_FILENAME
```

### 2.3 数据库版本

- **当前版本**: 13
- **版本管理表**: `schema_version`

## 3. 数据库表结构

### 3.1 表关系图 (ER Diagram)

```
┌─────────────┐     ┌───────────────┐     ┌─────────────┐
│   devices   │◄────┤ kefu_devices  ├────►│    kefus    │
└─────────────┘     └───────────────┘     └──────┬──────┘
                                                 │
                                                 │ 1:N
                                                 ▼
                                          ┌─────────────┐
                                          │  customers  │
                                          └──────┬──────┘
                                                 │
                                                 │ 1:N
                                                 ▼
                                          ┌─────────────┐
                                          │  messages   │
                                          └──────┬──────┘
                                                 │
                               ┌─────────────────┼─────────────────┐
                               │ 1:1             │ 1:1             │ 1:1
                               ▼                 ▼                 ▼
                        ┌──────────┐      ┌──────────┐      ┌──────────┐
                        │  images  │      │  videos  │      │ (voices) │
                        └──────────┘      └──────────┘      └──────────┘
```

### 3.2 devices 表 - 设备表

存储连接的 Android 设备信息。

| 列名            | 类型      | 约束                      | 描述         |
| --------------- | --------- | ------------------------- | ------------ |
| id              | INTEGER   | PRIMARY KEY AUTOINCREMENT | 主键         |
| serial          | TEXT      | UNIQUE NOT NULL           | 设备序列号   |
| model           | TEXT      |                           | 设备型号     |
| manufacturer    | TEXT      |                           | 设备制造商   |
| android_version | TEXT      |                           | Android 版本 |
| created_at      | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间     |
| updated_at      | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 更新时间     |

### 3.3 kefus 表 - 客服表

存储客服信息。客服通过 `name + department` 唯一标识。

| 列名                | 类型      | 约束                      | 描述     |
| ------------------- | --------- | ------------------------- | -------- |
| id                  | INTEGER   | PRIMARY KEY AUTOINCREMENT | 主键     |
| name                | TEXT      | NOT NULL                  | 客服名称 |
| department          | TEXT      |                           | 部门名称 |
| verification_status | TEXT      |                           | 认证状态 |
| created_at          | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间 |
| updated_at          | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 更新时间 |

**唯一约束**: `UNIQUE(name, department)`

### 3.4 kefu_devices 表 - 客服-设备关联表

多对多关系，记录客服使用过的设备。

| 列名       | 类型      | 约束                      | 描述       |
| ---------- | --------- | ------------------------- | ---------- |
| id         | INTEGER   | PRIMARY KEY AUTOINCREMENT | 主键       |
| kefu_id    | INTEGER   | NOT NULL, FOREIGN KEY     | 关联客服ID |
| device_id  | INTEGER   | NOT NULL, FOREIGN KEY     | 关联设备ID |
| created_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间   |
| updated_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 更新时间   |

**唯一约束**: `UNIQUE(kefu_id, device_id)`

### 3.5 customers 表 - 客户表

存储私聊联系人信息。

| 列名                 | 类型      | 约束                      | 描述                         |
| -------------------- | --------- | ------------------------- | ---------------------------- |
| id                   | INTEGER   | PRIMARY KEY AUTOINCREMENT | 主键                         |
| name                 | TEXT      | NOT NULL                  | 客户名称                     |
| channel              | TEXT      |                           | 来源渠道 (如 @WeChat, @微信) |
| kefu_id              | INTEGER   | NOT NULL, FOREIGN KEY     | 关联客服ID                   |
| last_message_preview | TEXT      |                           | 最后消息预览                 |
| last_message_date    | TEXT      |                           | 最后消息日期                 |
| created_at           | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间                     |
| updated_at           | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 更新时间                     |

**唯一约束**: `UNIQUE(name, channel, kefu_id)`

### 3.6 messages 表 - 消息表

存储所有对话消息。

| 列名             | 类型        | 约束                      | 描述                                   |
| ---------------- | ----------- | ------------------------- | -------------------------------------- |
| id               | INTEGER     | PRIMARY KEY AUTOINCREMENT | 主键                                   |
| customer_id      | INTEGER     | NOT NULL, FOREIGN KEY     | 关联客户ID                             |
| content          | TEXT        |                           | 消息内容                               |
| message_type     | TEXT        | NOT NULL, DEFAULT 'text'  | 消息类型                               |
| is_from_kefu     | BOOLEAN     | NOT NULL, DEFAULT 0       | 是否客服发送                           |
| timestamp_raw    | TEXT        |                           | 原始时间戳                             |
| timestamp_parsed | TIMESTAMP   |                           | 解析后的时间戳                         |
| extra_info       | TEXT        |                           | JSON格式的额外信息                     |
| message_hash     | TEXT        | UNIQUE NOT NULL           | SHA256哈希（去重）                     |
| **ui_position**  | **INTEGER** |                           | **UI提取顺序（用于准确的上下文排序）** |
| created_at       | TIMESTAMP   | DEFAULT CURRENT_TIMESTAMP | 创建时间                               |

> ⚠️ **重要**: `ui_position` 字段用于准确构造消息上下文。查询消息时应按 `ui_position` 排序，而非 `created_at`。

**消息类型 (message_type)**:

- `text` - 文本消息
- `voice` - 语音消息
- `image` - 图片消息
- `video` - 视频消息
- `file` - 文件消息
- `link` - 链接消息
- `location` - 位置消息
- `system` - 系统消息
- `unknown` - 未知类型

### 3.7 images 表 - 图片表

存储图片消息的文件信息。

| 列名            | 类型      | 约束                      | 描述           |
| --------------- | --------- | ------------------------- | -------------- |
| id              | INTEGER   | PRIMARY KEY AUTOINCREMENT | 主键           |
| message_id      | INTEGER   | NOT NULL, FOREIGN KEY     | 关联消息ID     |
| file_path       | TEXT      | NOT NULL                  | 文件路径       |
| file_name       | TEXT      |                           | 文件名         |
| original_bounds | TEXT      |                           | 截图时的UI坐标 |
| width           | INTEGER   |                           | 图片宽度       |
| height          | INTEGER   |                           | 图片高度       |
| file_size       | INTEGER   |                           | 文件大小       |
| created_at      | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间       |

### 3.8 videos 表 - 视频表

存储视频消息的文件信息。

| 列名             | 类型      | 约束                      | 描述                    |
| ---------------- | --------- | ------------------------- | ----------------------- |
| id               | INTEGER   | PRIMARY KEY AUTOINCREMENT | 主键                    |
| message_id       | INTEGER   | NOT NULL, FOREIGN KEY     | 关联消息ID              |
| file_path        | TEXT      | NOT NULL                  | 文件路径                |
| file_name        | TEXT      |                           | 文件名                  |
| duration         | TEXT      |                           | 时长字符串 (如 "00:45") |
| duration_seconds | INTEGER   |                           | 时长（秒）              |
| thumbnail_path   | TEXT      |                           | 缩略图路径              |
| width            | INTEGER   |                           | 视频宽度                |
| height           | INTEGER   |                           | 视频高度                |
| file_size        | INTEGER   |                           | 文件大小                |
| created_at       | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 创建时间                |

### 3.9 schema_version 表 - 版本表

记录数据库架构版本。

| 列名       | 类型      | 约束                      | 描述     |
| ---------- | --------- | ------------------------- | -------- |
| version    | INTEGER   | PRIMARY KEY               | 版本号   |
| applied_at | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 应用时间 |

## 4. 索引

```sql
-- 消息表索引
CREATE INDEX idx_messages_customer_id ON messages(customer_id);
CREATE INDEX idx_messages_hash ON messages(message_hash);
CREATE INDEX idx_messages_type ON messages(message_type);
CREATE INDEX idx_messages_timestamp ON messages(timestamp_parsed);
CREATE INDEX idx_messages_ui_position ON messages(customer_id, ui_position);  -- 用于快速排序

-- 客户表索引
CREATE INDEX idx_customers_kefu_id ON customers(kefu_id);

-- 关联表索引
CREATE INDEX idx_kefu_devices_kefu_id ON kefu_devices(kefu_id);
CREATE INDEX idx_kefu_devices_device_id ON kefu_devices(device_id);

-- 媒体表索引
CREATE INDEX idx_images_message_id ON images(message_id);
CREATE INDEX idx_videos_message_id ON videos(message_id);
```

## 5. 数据存储流程

### 5.1 整体数据流

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                              同步入口层                                           │
│  initial_sync_v2.py / initial_sync.py                                           │
└─────────────────────────────────────┬────────────────────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                              编排器层                                             │
│  SyncOrchestrator (src/wecom_automation/services/sync/orchestrator.py)          │
│  - 初始化设备/客服信息                                                            │
│  - 获取客户列表                                                                   │
│  - 协调整体同步流程                                                               │
│  - 动态红点检测与优先级调整                                                        │
└─────────────────────────────────────┬────────────────────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                           客户同步器层                                            │
│  CustomerSyncer (src/wecom_automation/services/sync/customer_syncer.py)         │
│  - 进入单个客户对话                                                               │
│  - 提取对话消息                                                                   │
│  - 交互式等待回复                                                                 │
└─────────────────────────────────────┬────────────────────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                           消息处理器层                                            │
│  MessageProcessor (src/wecom_automation/services/message/processor.py)          │
│  - 责任链模式分发消息到具体处理器                                                   │
│  - 统计处理结果                                                                   │
└─────────────────────────────────────┬────────────────────────────────────────────┘
                                      │
         ┌────────────────────────────┼────────────────────────────────┐
         │                            │                                │
         ▼                            ▼                                ▼
┌─────────────────┐          ┌─────────────────┐           ┌─────────────────┐
│ TextHandler     │          │ ImageHandler    │           │ VideoHandler    │
│ VoiceHandler    │          │                 │           │                 │
└────────┬────────┘          └────────┬────────┘           └────────┬────────┘
         │                            │                             │
         └────────────────────────────┼─────────────────────────────┘
                                      │
                                      ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             数据库仓库层                                          │
│  ConversationRepository (src/wecom_automation/database/repository.py)           │
│  - CRUD 操作                                                                     │
│  - 消息去重                                                                       │
│  - 事务管理                                                                       │
└─────────────────────────────────────┬────────────────────────────────────────────┘
                                      │
                                      ▼
                        ┌─────────────────────────┐
                        │   wecom_conversations.db │
                        │       (SQLite)          │
                        └─────────────────────────┘
```

### 5.2 消息去重机制

消息去重基于 `message_hash` 字段，使用 SHA256 哈希算法。

**哈希计算输入**:

```python
hash_input = "|".join([
    str(self.customer_id),      # 客户ID
    content_str,                 # 消息内容（或媒体标识）
    msg_type,                    # 消息类型
    "1" if self.is_from_kefu else "0",  # 发送者
    ts_str,                      # 时间戳桶（2小时粒度）
    seq_str,                     # 序列号
])
```

**时间戳桶化**:

- 使用 2 小时为单位的时间桶
- 例如: 21:18 和 21:50 都归入 20:00 桶
- 目的: 处理滚动时获取的相同消息可能有微小时间差异

**媒体消息标识**:

- 图片: `[IMG:{width}x{height}]`
- 视频: `[VID:{duration}]`
- 语音: `[VOICE:{duration}]`

**相关代码**: `src/wecom_automation/database/models.py`

```python
def compute_hash(self) -> str:
    # 使用 2 小时桶化时间戳
    if self.timestamp_parsed:
        bucket_hour = (ts.hour // 2) * 2
        bucketed = ts.replace(hour=bucket_hour, minute=0, second=0)
        ts_str = bucketed.isoformat()

    # 构建哈希输入
    hash_input = "|".join([...])
    return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
```

## 6. 数据库操作 API

### 6.1 ConversationRepository 类

**文件**: `src/wecom_automation/database/repository.py`

#### 设备操作

```python
# 获取或创建设备
device = repo.get_or_create_device(
    serial="device_serial",
    model="Pixel 6",
    manufacturer="Google",
    android_version="13"
)

# 查询设备
device = repo.get_device_by_serial("device_serial")
device = repo.get_device_by_id(1)
devices = repo.list_devices()
```

#### 客服操作

```python
# 获取或创建客服（同时关联设备）
kefu = repo.get_or_create_kefu(
    name="张三",
    device_id=device.id,
    department="客服部"
)

# 查询客服
kefu = repo.get_kefu_by_id(1)
kefu = repo.get_kefu_by_name_and_department("张三", "客服部")
kefus = repo.list_kefus_for_device(device_id)
devices = repo.get_devices_for_kefu(kefu_id)
```

#### 客户操作

```python
# 获取或创建客户
customer = repo.get_or_create_customer(
    name="客户A",
    kefu_id=kefu.id,
    channel="@WeChat"
)

# 查询客户
customer = repo.get_customer("客户A", kefu_id, "@WeChat")
customers = repo.list_customers_for_kefu(kefu_id)
count = repo.count_customers_for_kefu(kefu_id)

# 更新最后消息
repo.update_customer_last_message(customer_id, "预览内容", "2025-01-01")
```

#### 消息操作

```python
# 添加消息（自动去重）
was_added, msg_record = repo.add_message_if_not_exists(message_record)

# 批量添加
added, skipped = repo.add_messages_batch(messages)

# 查询消息
message = repo.get_message_by_hash(hash_value)
messages = repo.get_messages_for_customer(customer_id, limit=100)
last_msg = repo.get_last_message_for_customer(customer_id)
exists = repo.message_exists(message_record)

# 消息统计
count = repo.count_messages_for_customer(customer_id)
counts_by_type = repo.count_messages_by_type(customer_id)

# 更新消息元信息
repo.update_message_extra_info(message_id, {"key": "value"})
```

#### 图片/视频操作

```python
# 创建图片记录
image = repo.create_image(image_record)
image = repo.get_image_for_message(message_id)
images = repo.list_images_for_customer(customer_id)

# 创建视频记录
video = repo.create_video(video_record)
video = repo.get_video_for_message(message_id)
videos = repo.list_videos_for_customer(customer_id)
```

#### 统计信息

```python
stats = repo.get_statistics()
# 返回:
# {
#     "devices": 2,
#     "kefus": 3,
#     "customers": 150,
#     "messages": 5000,
#     "images": 200,
#     "videos": 50,
#     "messages_by_type": {"text": 4000, "image": 800, ...}
# }
```

## 7. 数据模型类

### 7.1 MessageRecord

**文件**: `src/wecom_automation/database/models.py`

```python
@dataclass
class MessageRecord:
    customer_id: int          # 客户ID（必需）
    message_type: MessageType # 消息类型（必需）
    is_from_kefu: bool        # 是否客服发送（必需）
    id: Optional[int]         # 数据库ID
    content: Optional[str]    # 消息内容
    timestamp_raw: Optional[str]      # 原始时间戳
    timestamp_parsed: Optional[datetime]  # 解析后时间戳
    extra_info: Optional[str] # JSON格式额外信息
    message_hash: Optional[str]  # 哈希值（自动计算）
    ui_position: Optional[int]   # UI提取顺序（用于排序）
    created_at: Optional[datetime]
```

> 💡 **提示**: `ui_position` 是构造准确上下文的关键字段。新消息保存时会自动分配。

### 7.2 消息类型枚举

```python
class MessageType(str, Enum):
    TEXT = "text"
    VOICE = "voice"
    IMAGE = "image"
    VIDEO = "video"
    FILE = "file"
    LINK = "link"
    LOCATION = "location"
    SYSTEM = "system"
    UNKNOWN = "unknown"
```

## 8. 消息处理器

### 8.1 处理器架构

```
MessageProcessor (责任链分发器)
    │
    ├── TextMessageHandler    -> messages 表
    ├── ImageMessageHandler   -> messages 表 + images 表 + 文件系统
    ├── VideoMessageHandler   -> messages 表 + videos 表 + 文件系统
    └── VoiceMessageHandler   -> messages 表 (+ 可选文件系统)
```

### 8.2 消息处理流程

```python
# 1. 创建处理器
processor = create_message_processor(
    repository=repo,
    wecom_service=wecom,
    images_dir="device_storage/<serial>/conversation_images",
    videos_dir="device_storage/<serial>/conversation_videos",
    voices_dir="device_storage/<serial>/conversation_voices"
)

# 2. 创建上下文
context = MessageContext(
    customer_id=customer.id,
    customer_name="客户A",
    kefu_id=kefu.id,
    kefu_name="张三",
    device_serial="xxx",
    channel="@WeChat"
)

# 3. 处理消息
result = await processor.process(message, context)
# result.added: bool     - 是否新增
# result.message_type: str  - 消息类型
# result.message_id: int   - 数据库ID
# result.content: str     - 消息内容
# result.extra: dict      - 额外信息
```

## 9. 媒体文件存储

### 9.1 文件目录结构

```
project_root/
├── device_storage/
│   └── <serial>/
│       ├── conversation_images/
│       │   └── customer_{id}/
│       │       ├── msg_{message_id}_{timestamp}.png
│       │       └── ...
│       ├── conversation_videos/
│       │   └── customer_{id}/
│       │       ├── video_{message_id}_{timestamp}.mp4
│       │       └── ...
│       └── conversation_voices/
│           └── customer_{id}/
│               └── ...
└── avatars/
    └── {customer_name}_avatar.png
```

说明：

- 通过后端 `DeviceManager` 启动的同步链路，默认把媒体输出隔离到 `device_storage/<serial>/...`
- 如果调用方显式传入 `images_dir` / `videos_dir` / `voices_dir`，则以显式路径为准
- 头像仍统一存放在项目根目录 `avatars/`

### 9.2 图片保存流程

```python
# ImageMessageHandler._save_image()
1. 创建客户目录: `device_storage/<serial>/conversation_images/customer_{id}/`
2. 生成文件名: msg_{message_id}_{timestamp}.png
3. 通过 ADB 截图保存
4. 创建 ImageRecord 并存入 images 表
5. 更新 messages.extra_info 添加 image_path
```

### 9.3 视频保存流程

```python
# VideoMessageHandler._save_video()
1. 创建客户目录: `device_storage/<serial>/conversation_videos/customer_{id}/`
2. 生成文件名: video_{message_id}_{timestamp}.mp4
3. 通过 ADB 下载视频
4. 创建 VideoRecord 并存入 videos 表
5. 更新 messages.extra_info 添加 video_path
```

## 10. 数据库迁移

### 10.1 迁移版本历史

| 版本   | 描述                                                                 |
| ------ | -------------------------------------------------------------------- |
| v1     | 初始架构                                                             |
| v2     | 添加 `kefu_devices` 关联表，合并同名客服                             |
| v3     | 添加 `videos` 表                                                     |
| v4     | 添加 `ui_position` 字段用于准确的消息排序                            |
| v5-v7  | 黑名单表扩展，加入 `deleted_by_user`、`is_blacklisted`、`avatar_url` |
| v8     | 增加 `system_settings` 表并迁移设置                                  |
| v9-v10 | 图片 AI 审核字段与工作流状态字段                                     |
| v11    | 强制 `images(message_id)` 一对一                                     |
| v12    | 视频 AI 审核聚合与逐帧字段                                           |
| v13    | 增加 `voices` 表                                                     |

### 10.2 迁移执行

```python
from wecom_automation.database.schema import run_migrations

# 自动执行所有待迁移
run_migrations(db_path="path/to/db.sqlite")
```

## 11. 使用示例

### 11.1 完整同步流程

```python
from wecom_automation.database.repository import ConversationRepository
from wecom_automation.database.models import MessageRecord, MessageType

# 初始化仓库
repo = ConversationRepository("wecom_conversations.db")

# 获取或创建设备
device = repo.get_or_create_device("R5CT1234567")

# 获取或创建客服
kefu = repo.get_or_create_kefu("张三", device.id, department="客服部")

# 获取或创建客户
customer = repo.get_or_create_customer(
    name="王五",
    kefu_id=kefu.id,
    channel="@WeChat"
)

# 添加消息
message = MessageRecord(
    customer_id=customer.id,
    content="你好",
    message_type=MessageType.TEXT,
    is_from_kefu=False,
    timestamp_raw="10:30"
)
was_added, record = repo.add_message_if_not_exists(message)

if was_added:
    print(f"消息已添加, ID: {record.id}")
else:
    print("消息重复，已跳过")
```

### 11.2 查询统计

```python
# 获取整体统计
stats = repo.get_statistics()
print(f"总消息数: {stats['messages']}")
print(f"按类型: {stats['messages_by_type']}")

# 获取特定客户的消息
messages = repo.get_messages_for_customer(customer_id)
for msg in messages:
    sender = "客服" if msg.is_from_kefu else "客户"
    print(f"[{msg.timestamp_raw}] {sender}: {msg.content}")
```

## 12. 消息排序与上下文构造

### 12.1 问题背景

在 WeCom UI 中提取消息时，消息的提取顺序可能与实际发送顺序不一致，原因包括：

- 滚动提取时消息分批获取
- `timestamp_raw` 可能是相对时间（如"昨天"、"10:30"）
- `created_at` 是数据库插入时间，非实际发送时间

### 12.2 解决方案：ui_position 字段

`ui_position` 字段记录消息在 UI 中被提取时的绝对位置顺序：

```
消息1 (ui_position=1)  ← 最早的消息
消息2 (ui_position=2)
消息3 (ui_position=3)
...
消息N (ui_position=N)  ← 最新的消息
```

### 12.3 如何正确查询消息

```python
# ✅ 正确：按 ui_position 排序
messages = repo.get_messages_for_customer(customer_id)
# 内部实现: ORDER BY COALESCE(ui_position, id) ASC

# ❌ 错误：按 created_at 排序可能导致顺序错乱
# SELECT * FROM messages ORDER BY created_at ASC
```

### 12.4 构造 AI 上下文示例

```python
def build_conversation_context(customer_id: int, limit: int = 20) -> str:
    """构造准确的对话上下文"""
    repo = ConversationRepository()

    # 获取按 ui_position 正确排序的消息
    messages = repo.get_messages_for_customer(customer_id, limit=limit)

    context_lines = []
    for msg in messages:
        role = "客服" if msg.is_from_kefu else "客户"
        context_lines.append(f"[{role}]: {msg.content}")

    return "\n".join(context_lines)
```

### 12.5 ui_position 自动分配

新消息保存时，`ui_position` 会自动分配：

```python
# 在 repository.py 中
def create_message(self, message: MessageRecord) -> MessageRecord:
    # 自动分配 ui_position = 当前最大值 + 1
    if message.ui_position is None:
        max_pos = self._get_max_ui_position(message.customer_id)
        message.ui_position = max_pos + 1
```

### 12.6 历史数据迁移

数据库升级到 v4 时，会自动为历史消息回填 `ui_position`：

```sql
-- 基于 id 顺序回填（合理的近似值）
UPDATE messages
SET ui_position = (
    SELECT COUNT(*)
    FROM messages m2
    WHERE m2.customer_id = messages.customer_id
    AND m2.id <= messages.id
);
```

## 13. 注意事项

### 13.1 并发安全

- SQLite 使用 WAL + `busy_timeout`，但仍是单文件多写者模型，多设备写入高峰时会等待
- Repository 使用上下文管理器确保连接正确关闭

### 13.1.1 多设备并发的真实隔离边界

- 媒体文件默认按设备隔离到 `device_storage/<serial>/conversation_*`
- 同步写入默认按设备隔离到 `device_storage/<serial>/wecom_conversations.db`
- 共享控制库继续负责 settings / orchestration metadata
- `dashboard` / `customers` / `resources` / `streamers` 在未显式传入 `db_path` 时，默认做跨设备联邦聚合读取
- 三台设备并发时，最常见的相互影响点主要变成共享控制库、ADB 服务端、AI 服务端点和宿主机资源竞争

### 13.2 消息去重

- 基于内容、发送者、时间桶的哈希去重
- 2小时时间桶可能导致间隔很近的相同内容消息被误判为重复
- 媒体消息使用尺寸/时长作为区分依据

### 13.3 外键约束

- 默认启用外键约束 (`PRAGMA foreign_keys = ON`)
- 删除客户会级联删除其所有消息
- 删除客服会级联删除其所有客户

### 13.4 触发器

- `devices`, `kefus`, `customers`, `kefu_devices` 表有 `updated_at` 自动更新触发器

### 13.5 消息排序

- 查询消息时始终使用 `ORDER BY COALESCE(ui_position, id)`
- 不要依赖 `created_at` 进行排序，因为它是数据库写入时间
