# Avatar Storage Architecture

## Overview

本项目的头像存储采用 **"单一数据源 + 后端 API"** 的简化架构。

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Avatar Data Flow                              │
└─────────────────────────────────────────────────────────────────────┘

    ┌──────────────────┐
    │  Sync / FollowUp │  (截图捕获头像)
    │     Process      │
    └────────┬─────────┘
             │ 写入
             ▼
    ┌──────────────────┐
    │    avatars/      │  ← 唯一数据源
    │  (项目根目录)     │
    │                  │
    │  • avatar_01_    │
    │    张三.png      │
    │  • avatar_02_    │
    │    李四.png      │
    │  • avatar_default│
    │    .png          │
    └────────┬─────────┘
             │ 后端读取
             ▼
    ┌──────────────────┐
    │  Backend API     │
    │  /avatars/*      │
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────┐
    │    Frontend      │
    │   (Vue App)      │
    └──────────────────┘
```

## Directory Role

| 目录       | 角色           | 读/写 | 说明                                    |
| ---------- | -------------- | ----- | --------------------------------------- |
| `avatars/` | **唯一数据源** | 写+读 | 同步进程写入，后端 API 读取并提供给前端 |

## Design Rationale

### 1. 单一数据源 (Single Source of Truth)

只有 `avatars/` 一个位置存储头像，避免数据不一致问题。

```python
# sync_service.py - 唯一写入位置
self.avatars_dir = Path(__file__).parent.parent.parent.parent / "avatars"

# response_detector.py - 同样写入 avatars/
avatars_dir = project_root / "avatars"
```

### 2. 后端 API 提供访问

前端通过后端 API 获取头像，不依赖静态资源。

```typescript
// avatars.ts
const resp = await fetch(`${API_BASE}/avatars/metadata`)
return `${API_BASE}/avatars/${avatar.filename}`
```

**优点**：

- 实时性好：后端直接读 `avatars/`，新头像立即可用
- 架构简单：无需同步机制
- 逻辑集中：头像匹配算法可在后端统一处理

### 3. 默认头像回退

当没有匹配的头像时，使用 `avatar_default.png` 作为回退。

```typescript
// avatars.ts
if (avatarFiles.length === 0) {
  return `${API_BASE}/avatars/avatar_default.png`
}
```

## Benefits

| 特点       | 说明                       |
| ---------- | -------------------------- |
| **简单**   | 只有一份数据，一个访问路径 |
| **实时**   | 新捕获的头像立即可用       |
| **无冗余** | 不再占用双倍磁盘空间       |
| **易维护** | 无需维护同步机制           |

## Trade-off

| 优点       | 代价                 |
| ---------- | -------------------- |
| 架构简单   | 依赖后端运行         |
| 无冗余存储 | 后端故障时头像不可用 |
| 实时性好   | 无离线支持           |

> **注意**：如果后端未启动，头像将显示为默认头像或加载失败。这在实际使用中是可接受的，因为本应用本身就依赖后端运行。

## File Locations

```
project-root/
├── avatars/                          # ← 唯一数据源
│   ├── avatar_01_张三.png
│   ├── avatar_02_李四.png
│   └── avatar_default.png
│
├── wecom-desktop/
│   ├── src/utils/avatars.ts          # ← 前端头像工具（调用后端 API）
│   │
│   └── backend/
│       └── routers/avatars.py        # ← 后端 API（读取 avatars/）
│
└── src/wecom_automation/
    └── services/
        ├── sync_service.py           # ← 头像捕获（写入 avatars/）
        └── user/avatar.py            # ← AvatarManager
```

## Related Code

- **写入**：`src/wecom_automation/services/sync_service.py` → `_try_capture_avatar_once()`
- **后端 API**：`wecom-desktop/backend/routers/avatars.py`
- **前端工具**：`wecom-desktop/src/utils/avatars.ts`
- **Git 忽略**：`.gitignore` 中 `avatars/` 被忽略（运行时生成）
