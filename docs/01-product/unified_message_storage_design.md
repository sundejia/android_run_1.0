# 统一消息存储方案设计 (Unified Message Storage Design)

## 1. 背景与目标

当前系统中存在两个主要的消息获取场景：

1.  **全量同步 (Full Sync)**: 扫描所有联系人，获取历史消息，用于建立初始数据库。
2.  **即时跟进 (FollowUp)**: 实时监控未读消息，进行自动回复，并捕获最新的上下文。

**目标**: 无论消息来源是全量同步还是实时跟进，都应该**无缝**地集成到同一个 `messages` 表中，确保：

- **数据唯一性**: 避免重复存储。
- **上下文完整性**: FollowUp 获取的新消息应能接续全量同步的历史记录。
- **时间线连续性**: 消息排序准确。

## 2. 数据库架构现状 (Schema)

目前的 `messages` 表结构通常包含：

- `id`: 主键
- `customer_id`: 外键关联 `customers`
- `content`: 消息内容
- `sender`: 'customer' | 'kefu' | 'system'
- `timestamp`: 消息时间
- `msg_hash` (建议): 消息内容的哈希值，用于去重

## 3. 核心挑战与解决方案

### 3.1 挑战：消息去重 (De-duplication)

**问题**: FollowUp 可能会读取到 Sync 已经存下的最后几条消息作为上下文；Sync 也可能会再次扫描到 FollowUp 刚处理过的消息。
**方案**: **基于 `(customer_id, content, timestamp)` 的唯一性约束或指纹识别。**

1.  **生成消息指纹 (Fingerprint)**:
    在插入消息前，生成一个唯一标识符：
    `fingerprint = md5(f"{customer_id}_{content}_{timestamp_minutes}")`
    _注意：时间戳可能存在微小误差（OCR vs 系统时间），建议截断到分钟或使用模糊匹配。_

2.  **Upsert 策略**:
    使用 `INSERT OR IGNORE` 或 `INSERT ... ON CONFLICT DO NOTHING`。

### 3.2 挑战：时间戳对齐 (Timestamp Alignment)

**问题**:

- Sync 依赖 OCR 读取屏幕上的相对时间（"昨天", "12:30"），需要转换为绝对时间。
- FollowUp 是实时运行，可以使用 `datetime.now()` 记录捕获时间，或者同样依赖 OCR。
  **方案**: **统一使用标准化时间转换器。**
- 所有写入操作前，必须将时间转换为标准 UTC 或本地 `datetime` 对象。
- FollowUp 捕获的消息，如果 OCR 解析失败，可以使用当前系统时间作为后备（Fallback），因为它是实时的。

## 4. 统一存储流程设计

### 4.1 统一写入层 (Unified Ingestion Layer)

创建一个名为 `MessageStorageService` 的独立服务，供 SyncService 和 FollowUpService 共同调用。

```python
class MessageStorageService:
    def store_messages(self, customer_id: int, messages: List[MessageData]):
        """
        核心存储方法
        """
        for msg in messages:
            # 1. 解析/规范化时间
            db_time = self._normalize_timestamp(msg.timestamp)

            # 2. 生成去重指纹
            msg_hash = self._generate_hash(customer_id, msg.content, db_time)

            # 3. 尝试插入
            self.db.execute("""
                INSERT OR IGNORE INTO messages
                (customer_id, content, sender, timestamp, msg_hash)
                VALUES (?, ?, ?, ?, ?)
            """, ...)
```

### 4.2 场景集成

#### (1) 全量同步 (Full Sync) 流程

1.  进入聊天窗口。
2.  向上滚动抓取所有可见消息。
3.  调用 `MessageStorageService.store_messages(cid, history_msgs)`。
4.  **关键点**: Sync 往往能获取更准确的历史时间（因为可以看到日期分割线），可以修正 FollowUp 之前可能估算错误的时间。

#### (2) 即时跟进 (FollowUp) 流程

1.  检测到红点，进入窗口。
2.  抓取当屏可见消息（通常是最近几条）。
3.  调用 `MessageStorageService.store_messages(cid, recent_msgs)`。
4.  由于有去重机制，旧消息会被忽略，只有新消息被插入。
5.  如果 FollowUp 发送了 AI 回复，该回复也通过此接口立刻存入，无需等待下一次 Sync。

## 5. 具体实施步骤

1.  **数据库迁移**:
    - 确保 `messages` 表有 `msg_hash` 字段或 `(customer_id, content, timestamp)` 的联合索引。

2.  **重构代码**:
    - 将分散在 `SyncService` 和 `ResponseDetector` 中的 SQL 插入代码提取到 `MessageStorageService`。

3.  **优化时间解析**:
    - 升级 `TimeParser`，支持将 "Just now", "5 mins ago" 转换为基于当前时间的绝对时间戳。

4.  **FollowUp 增强**:
    - 在 Sidecar 发送消息成功后，不仅更新 UI，还要主动构造一条 `sender='kefu'` 的消息对象存入数据库，确保机器人回复不丢失。

## 6. 优势

- **单一数据源**: 前端统一从 API 读取 `messages` 表，无需关心消息来源。
- **无缝衔接**: 用户在 L4 聊天回放页面可以看到完整的、连续的时间轴。
- **容错性**: 即使 FollowUp 漏抓了某条，下次 Full Sync 时也会自动补全；即使 Full Sync 重跑，也不会造成数据重复。
