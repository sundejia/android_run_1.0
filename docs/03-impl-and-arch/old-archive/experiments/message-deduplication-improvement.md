# 消息去重机制改进方案

## 一、问题概述

当前系统的消息去重机制存在以下问题：

### 问题 1: 正常重复文本被误去重

**场景描述：**

```
消息 #1: 用户发送 "好"
消息 #2: 用户发送 "收到"
消息 #3: 用户发送 "明白"
消息 #4: 用户发送 "OK"
消息 #5: 用户发送 "了解"
消息 #6: 用户发送 "好"  ← 被误判为重复，丢失！
```

两条 "好" 消息虽然内容相同，但属于不同的对话上下文，应该被保留。

### 问题 2: 同时发送的多张图片被误去重

**场景描述：**

```
用户同时发送 5 张图片（尺寸相同，均为 405x306）：
- 图片 A: 产品正面图
- 图片 B: 产品背面图
- 图片 C: 产品细节图 1
- 图片 D: 产品细节图 2
- 图片 E: 产品包装图

结果：只保留了图片 A，其他 4 张被误判为重复！
```

---

## 二、当前去重机制分析

### 2.1 Hash 计算逻辑

当前 `MessageRecord.compute_hash()` 使用以下字段：

```python
hash_input = "|".join([
    str(self.customer_id),      # 客户 ID
    content_str,                 # 内容（图片用尺寸代替）
    msg_type,                    # 消息类型
    "1" if self.is_from_kefu else "0",  # 发送方向
    ts_str,                      # 2小时时间桶
    seq_str,                     # 序列号
])
```

### 2.2 问题根因分析

#### 问题 1 根因：序列号在跨滚动时重置

```
第一次滚动提取：
  消息 #1 "好" → sequence=0 → hash=abc123

第二次滚动提取：
  消息 #6 "好" → sequence=0 → hash=abc123 (相同！)
```

`sequence_counters` 是在每次 `_extract_conversation_messages` 调用时重新创建的，导致跨滚动时序列号无法正确累加。

#### 问题 2 根因：图片仅用尺寸作为标识

```python
# 当前逻辑
if msg_type == "image":
    img_dims = extra.get("image_dimensions", "")
    if img_dims:
        content_str = f"[IMG:{img_dims}]"  # 仅用尺寸！
```

同尺寸的多张图片会产生相同的 `content_str`，进而产生相同的 hash。

---

## 三、改进方案

### 方案 A: 增强序列号机制 (推荐)

#### A.1 改进 ConversationMessage 的 unique_key

**修改文件**: `src/wecom_automation/core/models.py`

```python
def unique_key(self) -> str:
    """
    Generate a stable key for deduplication across scrolls.

    改进：添加 ui_position 作为额外区分因素
    """
    dir_part = "self" if self.is_self else "other"
    type_part = self.message_type

    # ... 现有 content_part 逻辑 ...

    # 改进：使用 _raw_index 作为位置标识
    # _raw_index 是消息在原始 UI 树中的位置，更稳定
    pos_part = str(self._raw_index) if self._raw_index >= 0 else ""

    # 改进：序列号仅当 >0 时包含
    seq_part = str(self._sequence) if self._sequence > 0 else ""

    # 改进：组合位置和序列号
    suffix = f"{pos_part}_{seq_part}" if pos_part or seq_part else ""

    return f"{dir_part}|{type_part}|{content_part}|{suffix}"
```

#### A.2 改进数据库 Hash 计算

**修改文件**: `src/wecom_automation/database/models.py`

```python
def compute_hash(self) -> str:
    """
    Compute a unique hash for this message.

    改进要点：
    1. 缩小时间桶范围（2小时 → 30分钟）
    2. 添加 ui_position 作为区分因素
    3. 图片使用 bounds 而非仅尺寸
    """
    # 改进 1: 使用 30 分钟时间桶
    ts_str = ""
    if self.timestamp_parsed:
        ts = self.timestamp_parsed
        # 30 分钟桶：0, 30
        bucket_minute = (ts.minute // 30) * 30
        bucketed = ts.replace(minute=bucket_minute, second=0, microsecond=0)
        ts_str = bucketed.isoformat()
    elif self.timestamp_raw:
        ts_str = self.timestamp_raw

    extra = self.get_extra_info_dict()
    seq_str = str(extra.get("sequence", ""))

    # 改进 2: 添加 ui_position
    pos_str = str(self.ui_position) if self.ui_position is not None else ""

    content_str = self.content or ""
    msg_type = self.message_type.value if isinstance(self.message_type, MessageType) else str(self.message_type)

    # 改进 3: 图片使用 bounds 作为标识
    if msg_type == "image":
        # 优先使用 bounds（唯一标识图片位置）
        img_bounds = extra.get("image_bounds", "")
        img_dims = extra.get("image_dimensions", "")
        if img_bounds:
            content_str = f"[IMG:{img_bounds}]"
        elif img_dims:
            content_str = f"[IMG:{img_dims}]"
    # ... 其他类型处理 ...

    hash_input = "|".join([
        str(self.customer_id),
        content_str,
        msg_type,
        "1" if self.is_from_kefu else "0",
        ts_str,
        seq_str,
        pos_str,  # 新增
    ])
    return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
```

### 方案 B: 基于消息顺序的累计去重

#### B.1 维护全局序列号上下文

**修改文件**: `src/wecom_automation/services/sync_service.py`

```python
class InitialSyncService:
    def __init__(self, ...):
        # ... 现有初始化 ...

        # 新增：全局消息计数器（按客户分组）
        self._message_counters: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    async def _process_and_store_message(
        self,
        msg: ConversationMessage,
        customer: CustomerRecord,
    ) -> dict:
        # 获取该客户的消息计数器
        counters = self._message_counters[customer.id]

        # 计算基础键（不含序列号）
        base_key = self._get_message_base_key(msg)

        # 获取并递增序列号
        sequence = counters[base_key]
        counters[base_key] += 1

        # 更新 extra_info 中的 sequence
        extra_info = {...}
        extra_info["sequence"] = sequence

        # ... 创建 MessageRecord ...

    def _get_message_base_key(self, msg: ConversationMessage) -> str:
        """生成消息基础键（用于序列号追踪）"""
        dir_part = "kefu" if msg.is_self else "customer"
        type_part = msg.message_type

        if msg.message_type == "image" and msg.image:
            # 图片：使用尺寸作为基础键
            if msg.image.bounds:
                match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', msg.image.bounds)
                if match:
                    x1, y1, x2, y2 = map(int, match.groups())
                    content_part = f"{x2-x1}x{y2-y1}"
                else:
                    content_part = "img"
            else:
                content_part = "img"
        elif msg.message_type == "voice":
            content_part = msg.voice_duration or "voice"
        else:
            content_part = (msg.content or "")[:50]

        return f"{dir_part}|{type_part}|{content_part}"
```

### 方案 C: 使用图片 bounds 作为唯一标识 (针对问题 2)

#### C.1 修改图片 Hash 计算

**修改文件**: `src/wecom_automation/database/models.py`

```python
def compute_hash(self) -> str:
    # ... 现有代码 ...

    if msg_type == "image":
        # 改进：使用 bounds 作为主要标识（bounds 对每张图片唯一）
        img_bounds = extra.get("image_bounds", "")
        img_dims = extra.get("image_dimensions", "")

        if img_bounds:
            # bounds 格式: [x1,y1][x2,y2] - 对每张图片唯一
            content_str = f"[IMG:{img_bounds}]"
        elif img_dims:
            # 备用：尺寸 + 序列号
            content_str = f"[IMG:{img_dims}:{seq_str}]"
        else:
            content_str = f"[IMG:{seq_str}]"
```

**注意**: bounds 在滚动后可能变化，需要在截图时记录原始 bounds。

---

## 四、实现步骤

### Phase 1: 修复图片去重问题 (优先级高)

1. [ ] 修改 `compute_hash()` 使用 `image_bounds` 作为图片标识
2. [ ] 确保 `sync_service.py` 正确传递 `image_bounds` 到 `extra_info`
3. [ ] 测试：同时发送 5 张相同尺寸图片，验证全部保存

### Phase 2: 修复文本去重问题

1. [ ] 修改时间桶大小从 2 小时改为 30 分钟
2. [ ] 添加 `ui_position` 到 hash 计算
3. [ ] 测试：发送相同文本间隔 5 条消息，验证全部保存

### Phase 3: 增强全局序列号追踪

1. [ ] 在 `InitialSyncService` 中添加 `_message_counters`
2. [ ] 修改 `_process_and_store_message` 使用全局计数器
3. [ ] 测试：跨滚动提取相同消息，验证序列号正确累加

---

## 五、测试用例

### 5.1 文本消息去重测试

```python
async def test_text_dedup():
    """测试相同文本在不同上下文中不被去重"""
    repo = ConversationRepository(":memory:")

    # 创建测试客户
    customer = repo.get_or_create_customer("Test", kefu_id=1)

    # 消息 1: "好"
    msg1 = MessageRecord(
        customer_id=customer.id,
        content="好",
        message_type=MessageType.TEXT,
        is_from_kefu=False,
        timestamp_parsed=datetime(2026, 1, 22, 10, 0),
        extra_info='{"sequence": 0}'
    )
    added1, _ = repo.add_message_if_not_exists(msg1)
    assert added1, "Message 1 should be added"

    # 消息 2-5: 其他消息
    # ...

    # 消息 6: "好" (相同内容，但稍后的时间)
    msg6 = MessageRecord(
        customer_id=customer.id,
        content="好",
        message_type=MessageType.TEXT,
        is_from_kefu=False,
        timestamp_parsed=datetime(2026, 1, 22, 10, 15),  # 15分钟后
        extra_info='{"sequence": 0, "ui_position": 5}'
    )
    added6, _ = repo.add_message_if_not_exists(msg6)
    assert added6, "Message 6 should be added (different context)"
```

### 5.2 图片去重测试

```python
async def test_image_dedup():
    """测试同尺寸多图片不被去重"""
    repo = ConversationRepository(":memory:")
    customer = repo.get_or_create_customer("Test", kefu_id=1)

    # 5 张相同尺寸的图片
    for i in range(5):
        msg = MessageRecord(
            customer_id=customer.id,
            content="[图片]",
            message_type=MessageType.IMAGE,
            is_from_kefu=False,
            timestamp_parsed=datetime(2026, 1, 22, 10, 0),
            extra_info=json.dumps({
                "image_dimensions": "405x306",
                "image_bounds": f"[177,{1293 + i * 100}][582,{1599 + i * 100}]",  # 不同 bounds
                "sequence": i
            })
        )
        added, _ = repo.add_message_if_not_exists(msg)
        assert added, f"Image {i+1} should be added"
```

---

## 六、风险评估

### 6.1 向后兼容性

| 改动             | 风险                                         | 缓解措施                       |
| ---------------- | -------------------------------------------- | ------------------------------ |
| 修改 hash 计算   | 已存在的消息 hash 不变，新消息 hash 可能不同 | 可接受，不影响已有数据         |
| 缩小时间桶       | 同一消息可能产生不同 hash                    | 可接受，宁可重复不可丢失       |
| 添加 ui_position | 旧数据无此字段                               | 设置默认值 None，不影响旧 hash |

### 6.2 性能影响

- Hash 计算增加了字段，但计算量微乎其微
- 无需数据库迁移
- 无需重建索引

---

## 七、配置建议

建议添加配置项允许调整去重策略：

```python
# 在 config.py 或 settings 中添加

@dataclass
class DeduplicationConfig:
    """消息去重配置"""

    # 时间桶大小（分钟）
    # 较小的值 = 更少误去重，但可能产生更多重复
    timestamp_bucket_minutes: int = 30

    # 是否使用 ui_position 作为去重因素
    use_ui_position: bool = True

    # 是否使用 image_bounds 作为图片标识
    use_image_bounds: bool = True

    # 严格模式：完全不去重相同内容（调试用）
    strict_mode: bool = False
```

---

## 八、总结

| 问题       | 根因                        | 解决方案                      | 优先级 |
| ---------- | --------------------------- | ----------------------------- | ------ |
| 文本误去重 | 2小时时间桶太宽，序列号重置 | 缩小时间桶 + 添加 ui_position | P1     |
| 图片误去重 | 仅用尺寸标识，不含 bounds   | 使用 bounds 作为图片标识      | P0     |

**核心原则**: 宁可多存一条重复消息，也不可丢失正常消息。

---

## 九、相关文件

| 文件                                            | 改动类型 | 说明                  |
| ----------------------------------------------- | -------- | --------------------- |
| `src/wecom_automation/database/models.py`       | 修改     | `compute_hash()` 逻辑 |
| `src/wecom_automation/core/models.py`           | 修改     | `unique_key()` 逻辑   |
| `src/wecom_automation/services/sync_service.py` | 修改     | 全局序列号追踪        |
| `src/wecom_automation/services/ui_parser.py`    | 修改     | 序列号分配逻辑        |
| `tests/unit/test_deduplication.py`              | 新建     | 去重测试用例          |
