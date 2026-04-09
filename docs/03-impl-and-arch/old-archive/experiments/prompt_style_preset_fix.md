# 提示词风格预设切换问题修复方案

## 问题描述

用户在设置界面切换提示词风格预设后，新选择的预设没有生效，AI 回复仍然使用旧的风格。

## 问题分析

### 根本原因

前端的 `syncWithBackend()` 函数存在设计缺陷：

1. **只发送不接收**: 函数只向后端发送设置数据，但不处理后端的响应
2. **缺少确认机制**: 前端无法确认设置是否成功保存到后端
3. **本地状态不同步**: 即使后端保存成功，前端的本地状态也没有从后端重新加载确认

### 数据流问题

**问题流程**:

```
用户改变 promptStyleKey → 前端发送到后端 → 后端保存成功 → 前端本地状态未更新
                                                            ↓
                                                combinedSystemPrompt 计算属性未重新计算
```

**预期流程**:

```
用户改变 promptStyleKey → 前端发送到后端 → 后端保存成功 → 前端从后端重新加载设置 → 本地状态更新 → combinedSystemPrompt 重新计算
```

## 修复方案

### 方案选择

采用**方案 A: 修改 syncWithBackend 函数**，使其在发送设置后从后端重新加载确认。

**优点**:

- 简单直接，修改范围小
- 确保前端状态与后端保持同步
- 解决所有设置同步问题，不仅仅是提示词风格预设

### 具体实现

#### 修改文件: `wecom-desktop/src/stores/settings.ts`

**修改前**:

```typescript
async function syncWithBackend() {
  if (syncTimeout) clearTimeout(syncTimeout)

  syncTimeout = window.setTimeout(async () => {
    try {
      await fetch(`${settings.value.backendUr../03-impl-and-arch/key-modules/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          // ... 设置数据
          prompt_style_key: settings.value.promptStyleKey,
          // ...
        })
      })
    } catch (error) {
      console.error('Failed to sync settings with backend:', error)
    }
  }, 500)
}
```

**修改后**:

```typescript
async function syncWithBackend() {
  if (syncTimeout) clearTimeout(syncTimeout)

  syncTimeout = window.setTimeout(async () => {
    try {
      // First, send settings to backend
      const updateResponse = await fetch(`${settings.value.backendUr../03-impl-and-arch/key-modules/update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          // ... 设置数据
          prompt_style_key: settings.value.promptStyleKey,
          // ...
        })
      })

      if (updateResponse.ok) {
        // After successful update, reload settings from backend to ensure consistency
        // This ensures promptStyleKey and other settings are properly synced
        const loadResponse = await fetch(`${settings.value.backendUrl}/settings`)
        if (loadResponse.ok) {
          const data = await loadResponse.json()
          // Merge backend settings with current settings, preserving frontend-only settings
          const merged = normalizeSettings({
            ...settings.value,
            ...data,
            // Preserve frontend-only settings that shouldn't be overridden by backend
            backendUrl: settings.value.backendUrl,
            autoRefreshInterval: settings.value.autoRefreshInterval,
            logMaxEntries: settings.value.logMaxEntries,
          })
          settings.value = merged
          // Update localStorage with confirmed backend values
          localStorage.setItem(STORAGE_KEY, JSON.stringify(settings.value))
          backendSynced.value = true
        }
      } else {
        console.error('Failed to update settings on backend:', updateResponse.status)
      }
    } catch (error) {
      console.error('Failed to sync settings with backend:', error)
    }
  }, 500)
}
```

### 修复逻辑说明

1. **发送设置**: 首先向后端发送更新请求
2. **检查响应**: 确认后端成功处理了更新
3. **重新加载**: 从后端获取最新设置数据
4. **合并设置**: 将后端数据与当前设置合并
5. **保留前端设置**: 保持前端特有的设置不受后端覆盖
6. **更新存储**: 将确认后的设置保存到 localStorage

### 关键改进点

1. **双向同步**: 从"只发送"改为"发送+确认"
2. **状态一致性**: 确保前端状态反映后端实际保存的值
3. **错误处理**: 添加对后端响应的检查
4. **设置保护**: 防止后端覆盖前端特有设置

## 测试验证

### 功能测试

创建测试脚本验证提示词风格预设切换逻辑：

```javascript
// 测试结果显示逻辑正确
Initial state: promptStyleKey: none
Combined prompt: "自定义提示词\n\n将回复控制在 50 字以内。"

Switching to "default" style: promptStyleKey: default
Combined prompt: "自定义提示词\n\n语气礼貌大方，使用"您"称呼用户。...将回复控制在 50 字以内。"

Switching to "lively" style: promptStyleKey: lively
Combined prompt: "自定义提示词\n\n语气要超级热情，多使用"哈喽"、"亲亲"、"么么哒"或"好哒"等词汇。..."
```

### 预期效果

修复后，用户切换提示词风格预设时：

1. ✅ 设置立即保存到后端
2. ✅ 前端从后端重新加载确认
3. ✅ `combinedSystemPrompt` 计算属性重新计算
4. ✅ AI 回复使用新的提示词风格

## 相关文件

- `wecom-desktop/src/stores/settings.ts`: 设置存储和同步逻辑
- `wecom-desktop/backend/routers/settings.py`: 后端设置 API
- `wecom-desktop/src/views/SettingsView.vue`: 设置界面

## 兼容性说明

此修复向后兼容，不会影响现有的设置同步机制。只是在现有的基础上增加了确认步骤。

## 总结

通过修改 `syncWithBackend()` 函数实现双向同步，解决了提示词风格预设切换后没有应用的问题。修复确保了前端状态与后端保持一致，用户的所有设置更改都能立即生效。
