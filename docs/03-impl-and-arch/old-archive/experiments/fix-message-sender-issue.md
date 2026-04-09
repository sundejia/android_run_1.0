# 修复消息发送者判断问题

## 问题描述

在 Sidecar 页面显示聊天记录时，消息位置显示错误：

- 客服发送的消息应该在**右边**（绿色）
- 客户发送的消息应该在**左边**（灰色）

但实际显示时，所有消息的发送者标记 (`is_from_kefu`) 可能是错误的。

## 问题原因

`ui_parser.py` 中判断消息发送者的逻辑有缺陷：

### 修复前的逻辑（有问题）

```python
# 只根据头像位置判断
if avatar_x is not None:
    is_self = avatar_x > screen_width - 200
elif content_x is not None:
    is_self = content_x > screen_width // 2
```

问题：

1. **企业微信中，客服发送的消息不显示头像**
2. 当找不到头像时，fallback 逻辑不够健壮

### 修复后的逻辑

```python
# WeCom 聊天布局：
# - KEFU (客服) 消息：右边，通常不显示头像
# - CUSTOMER (客户) 消息：左边，头像在左边

# 检测策略：
# 1. 如果头像在左边 (x < 200) → 客户消息
# 2. 如果头像在右边 (x > screen_width - 200) → 客服消息
# 3. 如果没有头像，检查消息内容/气泡位置
```

## 修改的文件

### 1. `src/wecom_automation/services/ui_parser.py`

- 修复 `_extract_message_from_row` 方法中的发送者判断逻辑
- 参照 `followup_service.py` 中的 `_is_message_from_kefu` 方法

### 2. `wecom-desktop/src/views/SidecarView.vue`

- 修改消息图标显示：
  - 客服消息（右边）：💼
  - 客户消息（左边）：👤

### 3. 新增 `fix_message_sender.py`

- 用于修复数据库中已存储的错误数据

## 数据库修复

聊天记录存储在 `wecom_conversations.db` 数据库的 `messages` 表中。

### 修复命令

```bash
# 1. 检查当前数据
python fix_message_sender.py --check

# 2. 如果所有消息的发送者都反了，一键交换
python fix_message_sender.py --swap-all

# 3. 根据内容特征自动修复
python fix_message_sender.py --fix-by-content

# 4. 修复特定客户
python fix_message_sender.py --fix-customer "客户名"

# 5. 清空消息表，重新全量同步（最干净）
python fix_message_sender.py --clear-messages
```

## 数据库位置

- **数据库文件**: `wecom_conversations.db`（项目根目录）
- **消息表**: `messages`
- **关键字段**: `is_from_kefu` (1=客服发送, 0=客户发送)

### 消息表结构

```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    content TEXT,
    message_type TEXT DEFAULT 'text',
    is_from_kefu BOOLEAN NOT NULL DEFAULT 0,  -- 关键字段
    timestamp_raw TEXT,
    timestamp_parsed TIMESTAMP,
    extra_info TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(id)
);
```

## 前端显示逻辑

`SidecarView.vue` 中的消息显示：

```vue
<!-- 消息布局 -->
<div
  v-for="msg in historyMessages"
  class="flex gap-3"
  :class="msg.is_from_kefu ? 'flex-row-reverse' : ''"
>
  <!-- 头像 -->
  <div>{{ msg.is_from_kefu ? '💼' : '👤' }}</div>

  <!-- 消息气泡 -->
  <div :class="msg.is_from_kefu
    ? 'bg-wecom-primary text-white'  <!-- 客服：绿色，右边 -->
    : 'bg-wecom-surface text-wecom-text'">  <!-- 客户：灰色，左边 -->
    {{ msg.content }}
  </div>
</div>
```

## 验证修复

修复后重新运行全量同步或使用修复脚本后，可以通过以下方式验证：

1. 在 Sidecar 页面查看聊天记录
2. 客服消息应该在**右边**（绿色，💼图标）
3. 客户消息应该在**左边**（灰色，👤图标）

## 相关文件

| 文件                                                 | 说明                              |
| ---------------------------------------------------- | --------------------------------- |
| `src/wecom_automation/services/ui_parser.py`         | UI解析器，提取消息并判断发送者    |
| `src/wecom_automation/services/sync_service.py`      | 同步服务，使用 `msg.is_self` 判断 |
| `wecom-desktop/src/views/SidecarView.vue`            | 前端聊天记录显示                  |
| `wecom-desktop/backend/services/followup_service.py` | 参考的判断逻辑                    |
| `fix_message_sender.py`                              | 数据库修复脚本                    |

---

_修复日期: 2025-12-31_
