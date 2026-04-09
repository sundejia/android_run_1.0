# Conversations 页面重复显示问题分析

**问题报告日期**: 2025-01-18
**分析日期**: 2025-01-18
**修复日期**: 2026-01-18
**状态**: ✅ 已修复

## 问题描述

用户报告在前端 Conversations 页面中，某些用户会显示两次，且打开后内容看起来一样。

## 分析过程

### 1. 数据库层面检查

#### 表结构

`customers` 表有以下唯一约束：

```sql
UNIQUE(name, channel, kefu_id)
```

这意味着一个 customer 记录由 `(name, channel, kefu_id)` 三个字段的组合唯一确定。

#### 实际数据检查

```sql
SELECT c.id, c.name, c.channel, c.kefu_id, k.name as kefu_name,
       COUNT(m.id) as msg_count
FROM customers c
JOIN kefus k ON c.kefu_id = k.id
LEFT JOIN messages m ON m.customer_id = c.id
WHERE c.name = '沈子涵'
GROUP BY c.id;
```

结果：

```
id  | name   | channel | kefu_id | kefu_name | msg_count
-----|--------|---------|---------|-----------|----------
64  | 沈子涵 |         | 9       | wgz小号   | 78
66  | 沈子涵 |         | 12      | 沈子涵    | 75
```

**发现**: 数据库中有两条"沈子涵"记录，但它们的 `kefu_id` 不同（9 vs 12）。

#### 消息内容对比

```sql
SELECT customer_id, COUNT(*) as msg_count,
       GROUP_CONCAT(DISTINCT is_from_kefu) as sender_types
FROM messages
WHERE customer_id IN (64, 66)
GROUP BY customer_id;
```

结果：

```
customer_id | msg_count | sender_types
------------|-----------|-------------
64          | 78        | 0,1
66          | 75        | 0,1
```

**结论**: 两个 customer 记录的消息数量不同（78 vs 75），不是完全相同的会话。

### 2. 后端 API 检查

#### 代码位置

`wecom-desktop/backend/routers/customers.py:125-297`

#### 关键逻辑

后端 `GET /customers` 端点：

```python
@router.get("")
async def list_customers(
    kefu_id: Optional[int] = Query(None),
    # ... other filters
):
    query = _customer_base_query(where_clause=where_clause, order_clause=order_clause)
    cursor.execute(query, (*params, limit, offset))
    items = [dict(row) for row in cursor.fetchall()]
```

**发现**: 后端返回所有 customers 记录，**没有任何去重逻辑**。这是正确的行为，因为不同的 kefu_id 意味着不同的会话。

### 3. 前端渲染逻辑检查

#### 代码位置

`wecom-desktop/src/views/CustomersListView.vue:660-716`

#### 表格列定义

```vue
<thead>
  <tr>
    <th>Streamer</th>      <!-- customer.name -->
    <th>Agent</th>         <!-- customer.kefu_name -->
    <th>Device</th>
    <th>Last message</th>
    <th>Preview</th>
    <th>Totals</th>
    <th>Actions</th>
  </tr>
</thead>
```

#### 渲染逻辑

```vue
<tr v-for="customer in customerStore.customers" :key="customer.id">
  <td>
    <p>{{ customer.name }}</p>
    <p>{{ customer.channel || '—' }}</p>
  </td>
  <td>
    <p>{{ customer.kefu_name }}</p>
    <p>{{ customer.kefu_department || 'No dept' }}</p>
  </td>
  <!-- ... other columns -->
</tr>
```

**发现**: 前端显示了 `kefu_name` 列，所以用户应该能看到：

- 第一条：沈子涵 — wgz小号
- 第二条：沈子涵 — 沈子涵

### 4. 问题根源分析

#### 数据库设计原理

`customers` 表的设计遵循以下业务逻辑：

```
一个 customer = 一个具体的会话
              = (客户名称 + 渠道 + 服务客服) 的组合
```

因此：

- 同一个人（如"沈子涵"）可以被**多个客服**服务
- 每个客服-客户组合都是一个**独立的会话**，有独立的 customer_id
- 这些会话可能有不同的消息历史

#### 可能的重复场景

**场景 1: 多客服服务同一客户**

```
客户"沈子涵"在不同时间被两个客服服务：
- 最初由 "wgz小号" (kefu_id=9) 服务 → customer_id=64
- 后来由 "沈子涵" (kefu_id=12) 服务 → customer_id=66
```

**场景 2: 客服账号切换**

```
客服人员可能：
- 使用小号 "wgz小号" 登录设备 A
- 使用自己的账号 "沈子涵" 登录设备 B
两者都服务了同一个客户"沈子涵"
```

**场景 3: 数据同步问题**

```
如果同一个客服账号在不同时间被同步，可能会创建多个 kefu 记录：
- kefu_id=9: "wgz小号" (302实验室)
- kefu_id=12: "沈子涵" (无部门)
```

## 结论

### 是否是 Bug？

**不是 bug**，这是符合设计的行为。

### 为什么看起来像 bug？

1. **视觉相似性**: 两条记录的 `name` 和 `channel` 相同（都是"沈子涵"，channel 都是空）
2. **列宽问题**: 如果前端 "Agent" 列不够明显，用户可能忽略 kefu_name 的差异
3. **用户理解**: 用户期望看到唯一的"客户"，而不是"客服-客户会话"

### 数据是否真的相同？

**不是**。从数据检查：

- customer_id=64: 78 条消息
- customer_id=66: 75 条消息

消息数量不同，说明是不同的对话历史。

## 建议

### 1. UI 改进建议

#### 方案 A: 视觉分组

在前端将同名客户分组显示：

```vue
<div class="customer-group">
  <h3>沈子涵</h3>
  <div class="conversation-item">
    <span>客服: wgz小号</span>
    <span>78 条消息</span>
  </div>
  <div class="conversation-item">
    <span>客服: 沈子涵</span>
    <span>75 条消息</span>
  </div>
</div>
```

#### 方案 B: 合并显示

将同一客户的所有会话合并为一个条目：

- 显示名称: "沈子涵"
- 显示客服: "wgz小号, 沈子涵" (多个)
- 点击后展开显示各个会话

#### 方案 C: 增强 Agent 列

- 加粗 "Agent" 列的显示
- 使用不同的颜色标记不同的客服
- 添加 tooltip 说明

### 2. 数据完整性检查

如果这不是预期行为，需要检查：

1. **kefu_id=9 和 kefu_id=12 是否应该是同一个客服？**
   - 检查 `kefus` 表
   - 可能需要合并重复的 kefu 记录

2. **是否是同步过程中的错误？**
   - 检查同步日志
   - 检查是否有重复同步的情况

3. **是否需要添加业务逻辑去重？**
   - 例如：如果同一个 name+channel 被多个客服服务，是否只显示最新的？

### 3. 用户教育

在 UI 中添加说明：

```
💡 提示：同一客户可能被多个客服服务，
每个客服-客户组合都会显示为独立的会话。
```

## 附录

### 相关文件

**数据库**:

- `wecom_conversations.db` - SQLite 数据库文件
- `src/wecom_automation/database/schema.py` - 数据库 schema 定义

**后端**:

- `wecom-desktop/backend/routers/customers.py:125-297` - GET /customers 端点

**前端**:

- `wecom-desktop/src/views/CustomersListView.vue:660-716` - 表格渲染
- `wecom-desktop/src/stores/customers.ts:82-119` - 数据获取

### 测试用例

验证"沈子涵"重复显示：

```
1. 打开前端 Conversations 页面
2. 查找 "沈子涵"
3. 观察到两条记录
4. 第一条: Streamer="沈子涵", Agent="wgz小号"
5. 第二条: Streamer="沈子涵", Agent="沈子涵"
6. 分别点击查看，确认消息数量不同（78 vs 75）
```

### 数据库查询

```sql
-- 查找所有重复的客户名称
SELECT name, COUNT(*) as count
FROM customers
GROUP BY name
HAVING count > 1;

-- 查看具体重复情况
SELECT c.id, c.name, c.channel, c.kefu_id,
       k.name as kefu_name, k.department,
       COUNT(m.id) as msg_count
FROM customers c
JOIN kefus k ON c.kefu_id = k.id
LEFT JOIN messages m ON m.customer_id = c.id
WHERE c.name IN (
    SELECT name FROM customers GROUP BY name HAVING COUNT(*) > 1
)
GROUP BY c.id
ORDER BY c.name, c.kefu_id;
```

## 总结

### 实际问题

经过进一步分析，发现存在**两种类型的"重复"**：

1. **正常的业务逻辑**：同一客户被不同客服服务，产生不同的会话记录（如截图中的沈子涵分别被 wgz小号 和 沈子涵 服务）
2. **真正的 Bug**：同一个会话因为 kefu 关联多个设备，在 SQL JOIN 时产生多行（如截图中 沈子涵+wgz小号 出现两次，只是 Device 不同）

### 根本原因

`_customer_base_query` 函数中的 SQL 查询使用了 `LEFT JOIN kefu_devices` 和 `LEFT JOIN devices`，当一个 kefu 关联多个设备时，会导致每个 customer 返回多行。

### 修复方案

在 `wecom-desktop/backend/routers/customers.py` 中的 `_customer_base_query` 函数添加 `GROUP BY c.id`，并使用聚合函数处理设备信息：

```python
# 修改前
COALESCE(d.serial, 'unknown') AS device_serial,
d.model AS device_model,
...
{where_clause}
{order_clause}

# 修改后
COALESCE(GROUP_CONCAT(DISTINCT d.serial), 'unknown') AS device_serial,
MAX(d.model) AS device_model,
...
{where_clause}
GROUP BY c.id
{order_clause}
```

### 修复效果

- 每个 customer 只返回一行
- 如果 kefu 关联多个设备，device_serial 会显示为逗号分隔的列表
- 分页总数与实际记录数一致
