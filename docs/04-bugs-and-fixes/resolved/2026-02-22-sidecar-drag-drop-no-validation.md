# Sidecar / Logs 拖放功能缺少校验导致任意文本被当作设备 Serial

**日期**: 2026-02-22  
**状态**: 已修复（已归档）  
**严重程度**: 中等  
**影响范围**: `wecom-desktop/src/views/SidecarView.vue`、`wecom-desktop/src/views/LogsView.vue`

## 问题描述

消息助手（Sidecar）与日志（Logs）界面均支持拖放设备到面板区域来添加面板。两处页面的 `handleDrop` 均未对拖入数据做校验，导致页面上的**任何文本**（如消息内容、错误日志等）都可被拖入并被当作设备 serial 创建面板。

### 表现症状

- 面板区域显示 `Failed to connect to device [serial=一段消息文本...]`
- 错误信息包含 `(caused by: Error setting up keyboard)`
- 多个无效面板同时出现，界面混乱

### 错误截图

页面上的中文消息内容被拖入 sidecar 区域后，系统尝试以该文本作为 serial 连接设备，必然失败。

## 根因分析

问题位于 `SidecarView.vue` 的 `handleDrop` 函数：

```typescript
// 当前代码（无校验）
function handleDrop(event: DragEvent) {
  event.preventDefault()
  isDragOver.value = false

  const serial = event.dataTransfer?.getData('text/plain')
  if (serial) {
    addPanel(serial, focusedSerial.value === null) // 任何非空字符串都会通过
  }
}
```

`getData('text/plain')` 会返回浏览器中任何被拖拽的文本内容。由于只做了 `if (serial)` 的非空判断，任何非空文本都会被当作设备 serial 添加为面板。

对比 `handleDragStart`，它只在设备按钮上触发，使用 `setData('text/plain', serial)` 设置正确的 serial。但 `handleDrop` 的接收端没有验证来源。

## 修复方案

### 方案 A：校验 serial 是否在已知设备列表中（推荐）

最简单直接，在 `handleDrop` 中验证拖入的文本是否是已知设备的 serial：

```typescript
function handleDrop(event: DragEvent) {
  event.preventDefault()
  isDragOver.value = false

  const serial = event.dataTransfer?.getData('text/plain')?.trim()
  if (!serial) return

  // 校验：只接受已知设备的 serial
  if (!availableDevices.value.includes(serial)) {
    console.warn(`[Sidecar] Rejected drop: "${serial}" is not a known device serial`)
    return
  }

  addPanel(serial, focusedSerial.value === null)
}
```

**优点**：实现简单，一行校验即可解决问题
**缺点**：如果设备列表还没加载完毕，合法的 serial 也会被拒绝（概率极低）

### 方案 B：使用自定义 MIME type 区分拖放来源

在 `dragstart` 时使用自定义 MIME type 标记来源，`drop` 时检查：

```typescript
const SIDECAR_DRAG_MIME = 'application/x-wecom-device-serial'

function handleDragStart(serial: string, event: DragEvent) {
  event.dataTransfer?.setData(SIDECAR_DRAG_MIME, serial)
  event.dataTransfer?.setData('text/plain', serial) // 保留兼容性
  dropMessage.value = 'Drop to open sidecar side-by-side'
}

function handleDrop(event: DragEvent) {
  event.preventDefault()
  isDragOver.value = false

  // 只接受通过自定义 MIME type 标记的拖放
  const serial = event.dataTransfer?.getData(SIDECAR_DRAG_MIME)
  if (!serial) {
    console.warn('[Sidecar] Rejected drop: not from a device button')
    return
  }

  // 双重校验：也检查设备列表
  if (!availableDevices.value.includes(serial)) {
    console.warn(`[Sidecar] Rejected drop: "${serial}" is not a known device serial`)
    return
  }

  addPanel(serial, focusedSerial.value === null)
}
```

**优点**：从根本上区分了"从设备按钮拖来的"和"从其他地方拖来的"
**缺点**：稍微多几行代码

### 方案 C：同时优化 dragover 的视觉提示

在 `handleDragOver` 中也做校验，避免显示误导性的 "Release to add sidecar" 提示：

```typescript
function handleDragOver(event: DragEvent) {
  event.preventDefault()

  // 检查是否包含自定义 MIME type（合法的设备拖放）
  const hasDeviceData = event.dataTransfer?.types?.includes(SIDECAR_DRAG_MIME)
  isDragOver.value = !!hasDeviceData && panels.value.length < maxPanels
}
```

这样当用户拖放非设备文本时，不会出现绿色虚线框和提示文字。

## 推荐方案

**推荐组合使用方案 B + C**，因为：

1. 自定义 MIME type 从源头区分拖放来源（方案 B）
2. dragover 阶段就过滤无效拖放，避免误导用户（方案 C）
3. 最终 drop 时双重校验（MIME type + 设备列表），确保万无一失

## 完整修复代码

以下为已采用的修复（方案 B+C），**SidecarView.vue** 与 **LogsView.vue** 逻辑一致，仅常量名不同（`SIDECAR_DRAG_MIME` / `LOGS_DRAG_MIME`，值均为 `application/x-wecom-device-serial`）。以 Sidecar 为例：

```typescript
// ====== 新增常量 ======
const SIDECAR_DRAG_MIME = 'application/x-wecom-device-serial'

// ====== 修改 handleDragStart ======
function handleDragStart(serial: string, event: DragEvent) {
  event.dataTransfer?.setData(SIDECAR_DRAG_MIME, serial)
  event.dataTransfer?.setData('text/plain', serial)
  dropMessage.value = 'Drop to open sidecar side-by-side'
}

// ====== 修改 handleDragOver ======
function handleDragOver(event: DragEvent) {
  event.preventDefault()
  const hasDeviceData = event.dataTransfer?.types?.includes(SIDECAR_DRAG_MIME)
  isDragOver.value = !!hasDeviceData && panels.value.length < maxPanels
}

// ====== 修改 handleDrop ======
function handleDrop(event: DragEvent) {
  event.preventDefault()
  isDragOver.value = false

  const serial = event.dataTransfer?.getData(SIDECAR_DRAG_MIME)
  if (!serial) return

  if (!availableDevices.value.includes(serial)) {
    console.warn(`[Sidecar] Rejected drop: "${serial}" is not a known device serial`)
    return
  }

  addPanel(serial, focusedSerial.value === null)
}
```

## 同类问题排查

检查其他视图是否存在同样的拖放校验缺失：

| 文件                 | 是否有拖放 | 是否有校验            | 状态       |
| -------------------- | ---------- | --------------------- | ---------- |
| `SidecarView.vue`    | 是         | 有（MIME + 设备列表） | **已修复** |
| `LogsView.vue`       | 是         | 有（MIME + 设备列表） | **已修复** |
| `DeviceListView.vue` | 否         | -                     | 无需修复   |

## 测试清单

- [ ] **Sidecar**：从设备按钮拖放到面板区域 → 正常添加面板
- [ ] **Sidecar**：从页面其他文本拖放到面板区域 → 被拒绝，无反应
- [ ] **Sidecar**：拖放非设备文本时，不显示 "Release to add sidecar" 提示
- [ ] **Logs**：从设备按钮拖放到面板区域 → 正常添加面板
- [ ] **Logs**：从页面其他文本拖放到面板区域 → 被拒绝，无反应
- [ ] **Logs**：拖放非设备文本时，不显示 "Release to add device logs" 提示
- [ ] 已达 3 面板上限时，拖放设备按钮 → 显示上限提示
- [ ] 拖放已存在于面板中的设备 → 不重复添加，切换焦点

---

## 修复记录（归档）

| 日期       | 操作 | 说明                                                                                                                      |
| ---------- | ---- | ------------------------------------------------------------------------------------------------------------------------- |
| 2026-02-22 | 修复 | **SidecarView.vue**：采用方案 B+C，新增 `SIDECAR_DRAG_MIME`，`handleDragStart` / `handleDragOver` / `handleDrop` 全部校验 |
| 2026-02-22 | 修复 | **LogsView.vue**：同上，新增 `LOGS_DRAG_MIME`（同值 `application/x-wecom-device-serial`），三处拖放逻辑同步修复           |
| 2026-02-22 | 归档 | 文档同步并归档，两处视图均已修复，无遗留                                                                                  |
