# 黑名单系统 - 前端设计文档

> 本文档专注于前端实现，由 Gemini 负责开发

## 背景

在 FollowUp 和 Sync 流程中，某些用户可能不希望被自动跟进或同步。需要一个黑名单系统来管理这些用户，避免程序自动进入这些用户的聊天。

## 前端需求

### 核心功能

1. **独立的黑名单管理页面** (`BlacklistView.vue`)
   - 分设备显示所有聊天用户
   - 支持用户名搜索
   - 支持加入/移出黑名单
   - 支持筛选（全部 / 已加入黑名单 / 未加入黑名单）

## 技术方案

### 1. 前端页面设计

新建 `wecom-desktop/src/views/BlacklistView.vue`：

```vue
<template>
  <div class="blacklist-view">
    <!-- 页面标题 -->
    <header class="page-header">
      <h1>🚫 黑名单管理</h1>
      <p class="subtitle">管理不自动跟进的用户</p>
    </header>

    <!-- 设备选择器 -->
    <div class="device-selector">
      <label>选择设备：</label>
      <select v-model="selectedDevice">
        <option value="">全部设备</option>
        <option v-for="device in devices" :key="device.serial" :value="device.serial">
          {{ device.name || device.serial }}
        </option>
      </select>
    </div>

    <!-- 搜索和筛选 -->
    <div class="filters">
      <input v-model="searchQuery" type="text" placeholder="搜索用户名..." class="search-input" />

      <div class="filter-buttons">
        <button :class="{ active: filter === 'all' }" @click="filter = 'all'">全部</button>
        <button :class="{ active: filter === 'blacklisted' }" @click="filter = 'blacklisted'">
          已加入黑名单
        </button>
        <button
          :class="{ active: filter === 'not_blacklisted' }"
          @click="filter = 'not_blacklisted'"
        >
          未加入黑名单
        </button>
      </div>
    </div>

    <!-- 统计信息 -->
    <div class="stats">
      <span>共 {{ totalCount }} 个用户</span>
      <span>已加入黑名单：{{ blacklistedCount }} 个</span>
    </div>

    <!-- 用户列表 -->
    <div class="user-list">
      <div
        v-for="user in filteredUsers"
        :key="user.customer_name + (user.customer_channel || '')"
        class="user-item"
        :class="{ blacklisted: user.is_blacklisted }"
      >
        <div class="user-info">
          <span class="user-name">{{ user.customer_name }}</span>
          <span v-if="user.customer_channel" class="user-channel">{{ user.customer_channel }}</span>
          <span v-if="user.is_blacklisted" class="blacklist-badge">🚫 已加入黑名单</span>
        </div>

        <div class="user-actions">
          <button v-if="!user.is_blacklisted" @click="addToBlacklist(user)" class="btn-add">
            加入黑名单
          </button>
          <button v-else @click="removeFromBlacklist(user)" class="btn-remove">移出黑名单</button>
        </div>
      </div>
    </div>
  </div>
</template>
```

### 2. 路由配置

在 `wecom-desktop/src/router/index.js` 中添加路由：

```javascript
{
  path: '/blacklist',
  name: 'Blacklist',
  component: () => import('@/views/BlacklistView.vue'),
  meta: { title: '黑名单管理' }
}
```

### 3. API 接口调用

前端需要调用以下后端 API：

| API 端点                                                | 方法 | 描述                             | 请求参数                                                       | 响应                                |
| ------------------------------------------------------- | ---- | -------------------------------- | -------------------------------------------------------------- | ----------------------------------- |
| ../03-impl-and-arch/key-modules/blacklist`              | GET  | 获取黑名单列表                   | `device_serial` (可选)                                         | `List[BlacklistEntry]`              |
| ../03-impl-and-arch/key-modules/blacklist/customers`    | GET  | 获取设备的所有用户及其黑名单状态 | `device_serial`, `search`, `filter`                            | `List[CustomerWithBlacklistStatus]` |
| ../03-impl-and-arch/key-modules/blacklist/add`          | POST | 添加用户到黑名单                 | `device_serial`, `customer_name`, `customer_channel`, `reason` | `{success: bool, message: str}`     |
| ../03-impl-and-arch/key-modules/blacklist/remove`       | POST | 从黑名单移除用户                 | `device_serial`, `customer_name`, `customer_channel`           | `{success: bool, message: str}`     |
| ../03-impl-and-arch/key-modules/blacklist/batch-add`    | POST | 批量添加到黑名单                 | `List[BlacklistAddRequest]`                                    | `{success: bool, count: int}`       |
| ../03-impl-and-arch/key-modules/blacklist/batch-remove` | POST | 批量从黑名单移除                 | `List[BlacklistRemoveRequest]`                                 | `{success: bool, count: int}`       |

#### 数据模型

```typescript
// 黑名单条目
interface BlacklistEntry {
  id: number
  device_serial: string
  customer_name: string
  customer_channel?: string
  reason?: string
  created_at: string
}

// 带黑名单状态的用户
interface CustomerWithBlacklistStatus {
  customer_name: string
  customer_channel?: string
  is_blacklisted: boolean
  blacklist_reason?: string
  last_message_at?: string
  message_count: number
}

// 添加黑名单请求
interface BlacklistAddRequest {
  device_serial: string
  customer_name: string
  customer_channel?: string
  reason?: string
}

// 移除黑名单请求
interface BlacklistRemoveRequest {
  device_serial: string
  customer_name: string
  customer_channel?: string
}
```

## 文件清单

| 文件                                        | 类型 | 描述               |
| ------------------------------------------- | ---- | ------------------ |
| `wecom-desktop/src/views/BlacklistView.vue` | 新建 | 黑名单管理页面     |
| `wecom-desktop/src/router/index.js`         | 修改 | 添加黑名单路由     |
| `wecom-desktop/src/components/Sidebar.vue`  | 修改 | 添加黑名单菜单入口 |

## UI 设计要点

1. **设备分组显示**: 支持选择设备或查看全部
2. **搜索功能**: 实时过滤用户列表
3. **筛选标签**: 快速切换查看黑名单状态
4. **批量操作**: 支持一次性添加/移除多个用户
5. **视觉区分**: 黑名单用户有明显的标记样式

## 样式参考

```css
.blacklist-view {
  padding: 20px;
}

.page-header h1 {
  font-size: 24px;
  margin-bottom: 8px;
}

.user-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid #e0e0e0;
}

.user-item.blacklisted {
  background-color: #fff0f0;
}

.blacklist-badge {
  color: #ff4444;
  font-size: 12px;
  margin-left: 8px;
}

.btn-add {
  background-color: #ff4444;
  color: white;
  border: none;
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
}

.btn-remove {
  background-color: #4caf50;
  color: white;
  border: none;
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
}

.filter-buttons button.active {
  background-color: #1976d2;
  color: white;
}
```

## 实现计划

### Phase 1: 基础页面

1. 创建 `BlacklistView.vue` 页面框架
2. 添加路由配置
3. 在导航菜单中添加入口

### Phase 2: 功能实现

1. 实现设备选择器
2. 实现用户列表展示
3. 实现搜索和筛选功能
4. 实现添加/移除黑名单操作

### Phase 3: 优化完善

1. 添加批量操作功能
2. 优化加载状态和错误处理
3. 添加操作成功/失败提示

## 注意事项

1. **响应式设计**: 确保页面在不同屏幕尺寸下正常显示
2. **加载状态**: 在请求 API 时显示加载指示器
3. **错误处理**: 妥善处理网络错误和 API 错误
4. **用户反馈**: 操作成功/失败时给予清晰的提示
5. **防抖处理**: 搜索输入使用防抖避免频繁请求
