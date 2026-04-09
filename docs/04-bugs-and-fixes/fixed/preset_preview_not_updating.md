# 预设内容预览框不实时更新问题修复

## 问题描述

在设置界面的"提示词风格预设"下拉菜单中，当用户切换选择不同的预设时，下方的"预设内容预览"框没有实时更新显示对应的内容。

**具体表现**：

- 选择"无预设 - 不使用预设风格"时，预览框应该隐藏，但仍然显示之前的预设内容
- 切换到其他预设时，预览内容没有即时更新

## 问题分析

### 根本原因

在 Vue 模板中，`v-if` 条件和内容显示使用了直接的表达式计算：

```vue
<div v-if="settings.promptStyleKey && settings.promptStyleKey !== 'none'">
  {{ promptStylePresets.find(p => p.key === settings.promptStyleKey)?.prompt }}
</div>
```

问题在于：

1. `settings` 是通过 `storeToRefs(settingsStore)` 获取的响应式引用
2. 模板中直接使用 `settings.promptStyleKey` 进行条件判断和数组查找
3. 当 `promptStyleKey` 变化时，Vue 的响应式系统可能没有正确触发重新渲染

### 技术细节

- `storeToRefs` 返回的是对 store 中 state 的 ref 引用
- 访问 `settings.promptStyleKey` 实际上是 `settings.value.promptStyleKey`
- 在模板中直接使用复杂表达式可能导致响应式追踪不完整

## 解决方案

### 修改的文件

**`wecom-desktop/src/views/SettingsView.vue`**

1. **添加计算属性**（第 21-27 行）：

```typescript
// Computed property for selected preset preview - ensures reactive update
const selectedPresetPrompt = computed(() => {
  const key = settings.value.promptStyleKey
  if (!key || key === 'none') return null
  const preset = promptStylePresets.find((p) => p.key === key)
  return preset?.prompt || null
})
```

2. **更新模板使用计算属性**：

```vue
<!-- 修复前 -->
<div v-if="settings.promptStyleKey && settings.promptStyleKey !== 'none'">
  {{ promptStylePresets.find(p => p.key === settings.promptStyleKey)?.prompt }}
</div>

<!-- 修复后 -->
<div v-if="selectedPresetPrompt">
  {{ selectedPresetPrompt }}
</div>
```

### 为什么使用计算属性可以解决问题

1. **明确的依赖追踪**：`computed` 会自动追踪 `settings.value.promptStyleKey` 的变化
2. **单一数据源**：条件判断和内容显示都使用同一个计算属性
3. **缓存优化**：计算属性只在依赖变化时重新计算
4. **简化模板**：模板中不再需要重复的逻辑判断

## 效果

修复后：

- 选择"无预设"时，预设内容预览框正确隐藏
- 切换到其他预设时，预览框实时显示对应的内容
- 响应式更新正常工作

## 相关文件

- `wecom-desktop/src/views/SettingsView.vue` - 设置页面组件
- `wecom-desktop/src/stores/settings.ts` - 设置状态管理（包含 `PROMPT_STYLE_PRESETS` 定义）
