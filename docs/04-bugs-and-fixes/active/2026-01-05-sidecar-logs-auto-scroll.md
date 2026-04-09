# Sidecar 日志自动滚动失效问题

**创建日期:** 2026-01-05  
**状态:** 待修复  
**严重程度:** 中等

## 问题描述

在 Sidecar 页面的日志面板中，当日志条目数量超过 1000 条后，自动滚动功能失效，用户无法自动看到最新的日志。

## 根因分析

### 1. 日志存储限制 (`stores/logs.ts`)

```typescript
// 第26行
const maxLogsPerDevice = 1000

// 第98-105行 - 当日志超过最大值时裁剪
if (logs.length > maxLogsPerDevice) {
  const removed = logs.splice(0, logs.length - maxLogsPerDevice)
  // Clean up known IDs for removed logs
  for (const log of removed) {
    knownLogIds.value.delete(log.id)
  }
}
```

当日志数量达到 1000 条后，每新增一条日志就会从数组头部删除一条旧日志。

### 2. 自动滚动监听逻辑 (`components/LogStream.vue`)

```typescript
// 第44-49行
watch(
  () => props.logs.length,
  async () => {
    if (props.autoScroll && containerRef.value) {
      await nextTick()
      containerRef.value.scrollTop = containerRef.value.scrollHeight
    }
  }
)
```

**问题核心：** `watch` 只监听 `logs.length` 的变化。当日志数量达到 1000 条后：

- 新日志加入：`length = 1001`
- 旧日志删除：`length = 1000`
- 最终 `length` 始终保持 1000，**没有变化**
- `watch` 不会触发 → **自动滚动失效**

## 解决方案

### 方案 A：监听日志内容变化（推荐）

修改 `LogStream.vue` 的监听逻辑，改为深度监听整个数组或监听最后一条日志的 ID：

```typescript
// 方案 A1：监听最后一条日志的 ID
watch(
  () => props.logs[props.logs.length - 1]?.id,
  async () => {
    if (props.autoScroll && containerRef.value) {
      await nextTick()
      containerRef.value.scrollTop = containerRef.value.scrollHeight
    }
  }
)

// 方案 A2：使用计算属性监听最新日志
const latestLogId = computed(() => props.logs[props.logs.length - 1]?.id || '')

watch(latestLogId, async () => {
  if (props.autoScroll && containerRef.value) {
    await nextTick()
    containerRef.value.scrollTop = containerRef.value.scrollHeight
  }
})
```

### 方案 B：在 logStore 中触发滚动事件

在 `logs.ts` 的 `addLogInternal` 函数中，添加一个递增的计数器：

```typescript
const logAddCounter = ref(0)

function addLogInternal(serial: string, entry: LogEntry, broadcast: boolean) {
  // ... 现有逻辑 ...

  // 每次添加日志都递增计数器
  logAddCounter.value++
}
```

然后在 `LogStream.vue` 中监听该计数器。

### 方案 C：使用 deep watch（性能较差）

```typescript
watch(
  () => props.logs,
  async () => {
    if (props.autoScroll && containerRef.value) {
      await nextTick()
      containerRef.value.scrollTop = containerRef.value.scrollHeight
    }
  },
  { deep: true }
)
```

**注意：** 此方案会导致每次日志变化都进行深度比较，性能较差，不推荐。

## 推荐修复

采用 **方案 A1**，修改 `LogStream.vue` 第44-49行：

**修改前：**

```typescript
watch(
  () => props.logs.length,
  async () => {
    if (props.autoScroll && containerRef.value) {
      await nextTick()
      containerRef.value.scrollTop = containerRef.value.scrollHeight
    }
  }
)
```

**修改后：**

```typescript
// 监听最后一条日志的 ID，确保日志内容变化时也能触发滚动
watch(
  () => props.logs[props.logs.length - 1]?.id,
  async () => {
    if (props.autoScroll && containerRef.value) {
      await nextTick()
      containerRef.value.scrollTop = containerRef.value.scrollHeight
    }
  }
)
```

## 涉及文件

| 文件                                         | 作用                         |
| -------------------------------------------- | ---------------------------- |
| `wecom-desktop/src/stores/logs.ts`           | 日志存储，定义了1000条的限制 |
| `wecom-desktop/src/components/LogStream.vue` | 日志显示组件，自动滚动逻辑   |

## 验证步骤

1. 启动同步任务，产生大量日志
2. 等待日志数量超过 1000 条
3. 观察日志面板是否自动滚动到最新日志
4. 验证删除旧日志后，面板仍能正常显示和滚动

## 补充说明

如果未来需要调整日志上限，可以修改 `logs.ts` 中的 `maxLogsPerDevice` 常量。建议保持在 1000-2000 条之间，以平衡内存使用和用户体验。
