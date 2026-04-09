# 前端头像显示问题修复方案

## 问题描述

前端无法显示任何头像，头像区域显示为空白或默认头像。

## 问题分析

### 根本原因

前端头像工具 (`avatars.ts`) 中的后端API地址是**硬编码**的：

```typescript
// Backend API base URL
const API_BASE = 'http://localhost:8765'
```

而其他前端模块都使用了动态配置的 `settings.value.backendUrl`。

### 具体表现

1. **配置不一致**: 用户在设置中更改后端URL后，头像功能仍然使用硬编码地址
2. **API访问失败**: 前端尝试访问错误的URL，导致头像加载失败
3. **静默失败**: 头像加载失败时没有明显的错误提示

### 数据流问题

```
用户更改设置 → backendUrl更新 → 其他功能正常 → 头像功能仍使用硬编码地址
                                                            ↓
                                                头像API请求失败 → 显示默认头像
```

## 修复方案

### 方案选择

采用**动态配置方案**：让头像工具使用与设置同步的后端URL。

**优点**:

- 解决配置不一致问题
- 支持动态URL配置
- 保持向后兼容
- 最小化代码改动

### 具体实现

#### 修改文件: `wecom-desktop/src/utils/avatars.ts`

**添加动态URL获取函数**:

```typescript
// Backend API base URL - dynamically resolved
let API_BASE: string = 'http://localhost:8765' // Default fallback

// Function to get the current backend URL
function getApiBase(): string {
  try {
    // Try to get from localStorage first (for immediate access)
    const stored = localStorage.getItem('wecom-settings')
    if (stored) {
      const settings = JSON.parse(stored)
      if (settings.backendUrl) {
        return settings.backendUrl
      }
    }
  } catch (error) {
    // Ignore localStorage errors
  }

  // Fallback to default
  return 'http://localhost:8765'
}

// Initialize API_BASE
API_BASE = getApiBase()
```

**添加URL更新机制**:

```typescript
/**
 * Update the backend API base URL.
 * Call this when the backend URL configuration changes.
 */
export function updateApiBase(newBaseUrl: string): void {
  if (API_BASE !== newBaseUrl) {
    API_BASE = newBaseUrl
    // Reload avatars when backend URL changes
    avatarsLoaded = false
    loadingPromise = null
  }
}
```

**添加存储监听器**:

```typescript
// Update API_BASE when settings change (if store is available)
if (typeof window !== 'undefined') {
  // Listen for storage changes (when settings are updated)
  window.addEventListener('storage', (event) => {
    if (event.key === 'wecom-settings' && event.newValue) {
      try {
        const settings = JSON.parse(event.newValue)
        if (settings.backendUrl) {
          API_BASE = settings.backendUrl
          // Reload avatars when backend URL changes
          avatarsLoaded = false
          loadingPromise = null
        }
      } catch (error) {
        // Ignore parsing errors
      }
    }
  })
}
```

#### 修改文件: `wecom-desktop/src/stores/settings.ts`

**导入头像更新函数**:

```typescript
import { updateApiBase } from '../utils/avatars'
```

**在设置加载时更新头像URL**:

```typescript
async function loadFromBackend() {
  // ... existing code ...
  if (response.ok) {
    const data = await response.json()
    const merged = normalizeSettings({ ...settings.value, ...data })
    settings.value = merged
    // ... existing code ...

    // Update avatar API base URL
    updateApiBase(settings.value.backendUrl)
  }
}
```

**在设置同步后更新头像URL**:

```typescript
async function syncWithBackend() {
  // ... existing code ...
  if (updateResponse.ok) {
    const loadResponse = await fetch(`${settings.value.backendUrl}/settings`)
    if (loadResponse.ok) {
      const data = await loadResponse.json()
      // ... existing merge logic ...
      settings.value = merged
      // ... existing code ...

      // Update avatar API base URL when backend URL changes
      updateApiBase(settings.value.backendUrl)
    }
  }
}
```

## 修复逻辑说明

### 1. 初始化阶段

- 模块加载时从localStorage读取backendUrl
- 如果没有配置，使用默认值 `http://localhost:8765`

### 2. 运行时更新

- 监听localStorage变化，当设置更新时自动更新API_BASE
- 当settings store调用updateApiBase时，强制刷新头像缓存

### 3. 缓存管理

- 当后端URL改变时，重置头像加载状态
- 确保使用新的URL重新加载头像列表

## 测试验证

### 功能测试

创建测试脚本验证动态URL配置：

```javascript
// 模拟localStorage中的设置
localStorage = {
  getItem: () => JSON.stringify({ backendUrl: 'http://localhost:9000' })
}

// 测试结果
Initial API_BASE: http://localhost:9000          // ✅ 从配置加载
After update API_BASE: http://localhost:9000     // ✅ 动态更新
Avatar URL: http://localhost:9000/avatars/...   // ✅ 使用正确URL
```

### 预期效果

修复后，头像功能将：

- ✅ 使用正确的后端URL配置
- ✅ 支持动态URL更改
- ✅ 在URL改变时自动刷新头像缓存
- ✅ 保持向后兼容

## 兼容性说明

此修复完全向后兼容：

- 如果没有配置backendUrl，使用默认值
- 如果后端不可用，回退到默认头像
- 不影响现有的头像匹配逻辑

## 故障排除

### 头像仍不显示

**可能原因**:

1. 后端服务未运行
2. 头像文件不存在
3. 网络连接问题
4. CORS配置问题

**排查步骤**:

1. 检查后端是否在配置的端口运行
2. 验证 `/avatars/metadata` API返回数据
3. 检查浏览器开发者工具的网络请求
4. 查看控制台错误信息

### 头像匹配错误

**可能原因**:

1. 名称规范化算法不一致
2. 头像文件名格式问题
3. 匹配优先级逻辑问题

**排查步骤**:

1. 比较前后端的 `normalizeName()` 输出
2. 检查头像文件名格式
3. 验证匹配算法逻辑

## 相关文件

- `wecom-desktop/src/utils/avatars.ts`: 头像工具和URL配置
- `wecom-desktop/src/stores/settings.ts`: 设置存储和同步
- `wecom-desktop/backend/routers/avatars.py`: 后端头像API
- `src/wecom_automation/services/user/avatar.py`: 头像捕获服务

## 总结

通过将硬编码的后端URL改为动态配置，解决了头像显示问题。修复确保：

1. **配置一致性**: 头像功能使用与设置同步的后端URL
2. **动态更新**: 当后端URL改变时，头像功能自动适应
3. **缓存管理**: URL改变时正确刷新头像缓存
4. **向后兼容**: 不破坏现有功能和配置

现在用户在设置中更改后端URL后，头像功能会立即使用正确的地址进行加载。
