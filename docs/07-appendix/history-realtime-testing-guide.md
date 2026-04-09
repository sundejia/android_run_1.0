# History 界面实时更新 - 测试指南

## 实施总结

已成功实施**方案 2（全局 WebSocket）**，让 History 界面支持实时更新。

### 修改的文件

#### 前端

1. ✅ `src/stores/globalWebSocket.ts` - **新建**，全局 WebSocket 管理器
2. ✅ `src/stores/customers.ts` - 添加 WebSocket 监听逻辑
3. ✅ `src/views/CustomerDetailView.vue` - 组件挂载时连接 WebSocket

#### 后端

4. ✅ `backend/routers/global_websocket.py` - **新建**，全局 WebSocket 路由
5. ✅ `backend/main.py` - 注册全局 WebSocket 路由
6. ✅ `backend/servic../03-impl-and-arch/response_detector.py` - 存储消息后广播事件

---

## 测试步骤

### 前提条件

1. 确保企业微信在**私聊标签页**
2. 确保 followup 功能已配置
3. 确保有测试客户可以发送消息

### 测试场景 1: 基本实时更新

#### 步骤

1. **启动后端服务**

   ```bash
   cd wecom-desktop/backend
   uvicorn main:app --reload --port 8765
   ```

2. **启动前端**

   ```bash
   cd wecom-desktop
   npm run dev
   ```

3. **打开 History 界面**
   - 访问 `http://localhost:5173`（或你的前端地址）
   - 进入任意客户的详情页（History 界面）

4. **打开浏览器开发者工具**
   - 按 `F12` 打开开发者工具
   - 切换到 `Network` 标签
   - 筛选 `WS`（WebSocket）

5. **验证 WebSocket 连接**
   - 应该看到一个新的 WebSocket 连接：`ws://localhost:8765/ws/global`
   - 点击该连接，查看状态：
     - State: `101 Switching Protocols`
     - 应该收到一条 `connected` 消息

6. **触发 Followup 检测**
   - 在测试客户发送一条新消息
   - 或者手动触发 followup 扫描

7. **验证实时更新**
   - 观察 History 界面是否**自动刷新**显示新消息
   - 在开发者工具的 WebSocket 标签中，应该看到：
     ```json
     {
       "type": "history_refresh",
       "timestamp": "2026-01-23T18:40:00",
       "data": {
         "customer_name": "测试客户",
         "channel": "wechat",
         "customer_id": 123
       }
     }
     ```

#### 预期结果

✅ **成功**：

- WebSocket 连接建立成功
- 收到 `connected` 消息
- 发送新消息后，History 界面**自动刷新**
- 控制台日志显示：
  ```
  [GlobalWS] Connected
  [Customers] Setting up global WebSocket
  [Customers] Global WebSocket listener attached
  [Customers] Received history_refresh event, reloading...
  ```

❌ **失败**：

- WebSocket 无法连接 → 检查后端是否启动，端口是否正确
- History 界面不刷新 → 检查控制台是否有错误，查看客户名称和渠道是否匹配
- 收到事件但不刷新 → 检查 `selectedCustomer` 的 `name` 和 `channel` 是否匹配事件中的数据

---

### 测试场景 2: 多标签页同步

#### 步骤

1. **打开多个标签页**
   - 在浏览器中打开多个标签页
   - 每个标签页都访问同一个客户的 History 界面

2. **发送测试消息**
   - 给该客户发送一条新消息

3. **验证所有标签页同步**
   - 所有打开的标签页都应该**同时刷新**

#### 预期结果

✅ **成功**：

- 所有标签页同时自动刷新
- 每个标签页的控制台都显示 `Received history_refresh event`

---

### 测试场景 3: WebSocket 断开重连

#### 步骤

1. **打开 History 界面**
   - 验证 WebSocket 已连接

2. **重启后端服务**
   - 在后端终端按 `Ctrl+C` 停止服务
   - 等待几秒

3. **重新启动后端**

   ```bash
   uvicorn main:app --reload --port 8765
   ```

4. **观察前端重连**
   - 检查浏览器控制台日志
   - 应该看到自动重连日志：
     ```
     [GlobalWS] Reconnecting in 1000ms... (attempt 1)
     [GlobalWS] ✓ Connected
     ```

#### 预期结果

✅ **成功**：

- 前端自动重连成功
- 重连后可以继续接收实时更新

---

### 测试场景 4: Sidecar 和 History 同时更新

#### 步骤

1. **打开 Sidecar 界面**
   - 访问任意客户的 Sidecar（实时上下文面板）

2. **打开 History 界面**
   - 在另一个标签页打开同一客户的 History

3. **触发 Followup**
   - 发送测试消息

4. **验证两个界面同时更新**
   - Sidecar 应该收到消息（旧逻辑）
   - History 应该自动刷新（新逻辑）

#### 预期结果

✅ **成功**：

- Sidecar 和 History 都能正常显示新消息
- 控制台日志显示：
  ```
  [serial] → Global WS: history_refresh for XXX
  [serial] → Sidecar WS: history_refresh for XXX
  ```

---

## 调试技巧

### 1. 查看 WebSocket 统计信息

打开浏览器控制台，执行：

```javascript
// 获取全局 WebSocket 统计
import { useGlobalWebSocketStore } from '@/stores/globalWebSocket'
const ws = useGlobalWebSocketStore()
console.log(ws.getStats())
```

应该看到类似输出：

```json
{
  "totalMessagesReceived": 5,
  "totalEventsDispatched": 3,
  "connectionCount": 1,
  "lastConnectedAt": "2026-01-23T18:40:00.000Z",
  "lastMessageAt": "2026-01-23T18:42:30.000Z",
  "connected": true,
  "status": "connected",
  "listenerCounts": {
    "history_refresh": 1,
    "connected": 0
  }
}
```

### 2. 手动触发刷新测试

在浏览器控制台执行：

```javascript
import { useCustomerStore } from '@/stores/customers'
const store = useCustomerStore()
await store.forceRefreshMessages()
```

### 3. 检查后端 WebSocket 连接数

访问 `http://localhost:8765/ws/global/stats`，应该看到：

```json
{
  "total_connections": 1,
  "active_connections": 1,
  "total_messages_sent": 10,
  "total_broadcasts": 5,
  "total_connections": 1
}
```

### 4. 模拟发送 WebSocket 事件（后端测试）

在后端添加临时测试路由：

```python
@router.get("/ws/test/broadcast")
async def test_broadcast():
    """测试 WebSocket 广播"""
    from routers.global_websocket import broadcast_history_refresh
    await broadcast_history_refresh("测试客户", "wechat", 123)
    return {"status": "ok", "message": "Broadcast sent"}
```

访问 `http://localhost:8765/ws/test/broadcast`，前端应该收到事件并刷新。

---

## 常见问题排查

### 问题 1: WebSocket 无法连接

**症状**：

- 浏览器控制台显示：`WebSocket connection to 'ws://localhost:8765/ws/global' failed`

**原因**：

- 后端服务未启动
- 端口被占用
- CORS 配置问题

**解决方案**：

```bash
# 检查后端是否启动
curl http://localhost:8765/health

# 检查端口占用
netstat -ano | findstr :8765

# 检查 CORS 配置（main.py）
# 确保有 CORSMiddleware
```

### 问题 2: 收到事件但不刷新

**症状**：

- WebSocket 连接成功
- 控制台显示 `Received history_refresh event, reloading...`
- 但界面不刷新

**可能原因**：

- 客户名称不匹配（中文 vs 英文）
- 渠道（channel）不匹配
- 客户 ID 不匹配

**调试步骤**：

在 `customers.ts` 的 `handleHistoryRefresh` 中添加调试日志：

```typescript
const handleHistoryRefresh = async (event: GlobalWebSocketEvent) => {
  const { customer_name, channel } = event.data || {}

  console.log('[Customers DEBUG]', {
    event_customer_name: customer_name,
    event_channel: channel,
    selected_customer_name: selectedCustomer.value?.name,
    selected_customer_channel: selectedCustomer.value?.channel,
    match:
      selectedCustomer.value?.name === customer_name && selectedCustomer.value?.channel === channel,
  })

  // ... 原有代码
}
```

### 问题 3: 多个刷新事件冲突

**症状**：

- 短时间内多次刷新导致卡顿
- 数据加载冲突

**解决方案**：添加防抖（已在方案文档中提供，如需要可实施）

---

## 性能监控

### 前端性能

在浏览器控制台执行：

```javascript
// 监控刷新频率
let refreshCount = 0
const originalFetch = useCustomerStore().fetchCustomerDetail

useCustomerStore().fetchCustomerDetail = async function (...args) {
  refreshCount++
  console.log(`[Performance] Refresh #${refreshCount} at ${new Date().toISOString()}`)
  const start = performance.now()
  const result = await originalFetch.apply(this, args)
  const duration = performance.now() - start
  console.log(`[Performance] Refresh took ${duration.toFixed(2)}ms`)
  return result
}
```

### 后端性能

访问 `http://localhost:8765/ws/global/stats` 查看统计信息：

```json
{
  "total_connections": 3, // 当前连接数
  "total_messages_sent": 125, // 总发送消息数
  "total_broadcasts": 42 // 总广播次数
}
```

---

## 日志示例

### 成功的完整日志流程

```
# 后端日志
[INFO] [GlobalWS] New connection (total: 1)
[INFO] [serial] → Global WS: history_refresh for 测试客户
[INFO] [serial] → Sidecar WS: history_refresh for 测试客户

# 前端日志（控制台）
[GlobalWS] Connecting to ws://localhost:8765/ws/global...
[GlobalWS] ← Received: connected {...}
[Customers] Setting up global WebSocket
[Customers] Global WebSocket listener attached
[Customers] Received history_refresh event, reloading...
[Customers] fetchCustomerDetail called
```

---

## 下一步（Phase 2 增强功能）

如果基础功能正常，可以实施以下增强：

1. **消息去重** - 避免重复处理相同消息
2. **节流/防抖** - 短时间内多次刷新合并为一次
3. **乐观更新** - 先显示"正在刷新..."，提升用户体验
4. **错误降级** - WebSocket 失败自动降级到轮询
5. **性能监控** - 收集刷新性能指标

详细实施方案请参考：`docs/history-realtime-update-solution.md`

---

## 回滚方案

如果遇到问题需要回滚：

### 前端回滚

```typescript
// src/views/CustomerDetailView.vue
// 移除这两行
customerStore.setupGlobalWebSocket()
customerStore.cleanupGlobalWebSocket()
```

### 后端回滚

```python
# backend/servic../03-impl-and-arch/response_detector.py
# 注释掉全局 WebSocket 部分
# from routers.global_websocket import broadcast_history_refresh
# await broadcast_history_refresh(...)
```

---

## 总结

✅ **已完成**：

- 创建全局 WebSocket 管理器
- 实现 History 界面实时更新
- 支持自动重连
- 保持向后兼容（Sidecar 仍然可用）

🎯 **预期效果**：

- History 界面实时显示新消息
- 延迟 < 100ms（WebSocket 推送）
- 支持多标签页同步
- 支持自动重连

📝 **测试要点**：

1. WebSocket 连接成功
2. 新消息自动刷新
3. 多标签页同步
4. 断开自动重连
5. Sidecar 和 History 同时工作
