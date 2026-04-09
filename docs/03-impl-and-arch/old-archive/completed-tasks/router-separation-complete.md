# Router 分离完成报告

**日期**: 2026-01-30  
**状态**: ✅ 已完成

---

## 1. 分离目标

将混合的 `followup.py` 路由文件彻底拆分为两个独立的路由：

| 路由文件             | 职责                   | API 前缀                                  |
| -------------------- | ---------------------- | ----------------------------------------- |
| `realtime_reply.py`  | 实时回复设备管理       | ../03-impl-and-arch/key-modules/realtime` |
| `followup_manage.py` | 补刀跟进管理 (Phase 2) | ../03-impl-and-arch/key-modules/followup` |

---

## 2. 实施内容

### 2.1 新建文件

#### realtime_reply.py

**文件位置**: `wecom-desktop/backend/routers/realtime_reply.py`

**包含端点**:

```
GET../03-impl-and-arch/key-modules/realtime/settings              ← 获取实时回复设置 ✅ 新增
POS../03-impl-and-arch/key-modules/realtime/settings              ← 保存实时回复设置 ✅ 新增
POS../03-impl-and-arch/key-modules/realtime/device/{serial}/start
POS../03-impl-and-arch/key-modules/realtime/device/{serial}/stop
POS../03-impl-and-arch/key-modules/realtime/device/{serial}/pause
POS../03-impl-and-arch/key-modules/realtime/device/{serial}/resume
POS../03-impl-and-arch/key-modules/realtime/device/{serial}/skip
GET../03-impl-and-arch/key-modules/realtime/device/{serial}/status
GET../03-impl-and-arch/key-modules/realtime/devices/status
POS../03-impl-and-arch/key-modules/realtime/devices/stop-all
```

**数据模型**:

- `DeviceStatus`：设备状态
- `AllDevicesStatus`：所有设备状态
- `RealtimeSettings`：实时回复设置 ✅ 新增

**集成**:

- 使用 `RealtimeReplyManager` 管理设备进程
- 通过统一设置服务读写配置

#### followup_manage.py

**文件位置**: `wecom-desktop/backend/routers/followup_manage.py`

**包含端点**:

```
GET    /a../03-impl-and-arch/analytics           ← 统计分析
GET    /a../03-impl-and-arch/attempts             ← 尝试记录列表
DELETE /a../03-impl-and-arch/attempts             ← 删除所有记录
GET    /a../03-impl-and-arch/export               ← 导出数据
GET    /a../03-impl-and-arch/candidates           ← 候选客户（占位）
POST   /a../03-impl-and-arch/trigger/{customer_id} ← 手动触发（占位）
```

**数据模型**:

- `FollowUpAttempt`：跟进尝试记录
- `FollowUpAnalytics`：统计分析数据
- `AttemptListResponse`：列表响应

**职责**:

- 提供跟进数据的查询和统计
- Phase 2 候选人管理（占位，待开发）

### 2.2 更新的文件

| 文件                         | 修改内容                                                                                      |
| ---------------------------- | --------------------------------------------------------------------------------------------- |
| `main.py`                    | 导入路由：`followup` → `realtime_reply`, `followup_manage`                                    |
| `main.py`                    | 路由注册：分别注册两个路由                                                                    |
| `RealtimeView.vue`           | API路径：`/a../03-impl-and-arch/settings` →../03-impl-and-arch/key-modules/realtime/settings` |
| `test_realtime_reply_api.py` | 导入：`routers.followup` → `routers.realtime_reply`                                           |

### 2.3 删除的文件

- ❌ `wecom-desktop/backend/routers/followup.py` (已删除)

---

## 3. API 路由对照表

### Before (混合路由)

```
/api/realtime/*  ← followup.py (错误！应该../03-impl-and-arch/key-modules/followup)
  ├── /analytics
  ├── /attempts
  ├── /export
  ├── /device/{serial}/start
  ├── /device/{serial}/stop
  └── ...
```

### After (分离路由)

```
/api/realtime/*  ← realtime_reply.py ✅ 正确
  ├── /settings         ← 新增
  ├── /device/{serial}/start
  ├── /device/{serial}/stop
  ├── /device/{serial}/pause
  ├── /device/{serial}/resume
  ├── /device/{serial}/skip
  ├── /device/{serial}/status
  ├── /devices/status
  └── /devices/stop-all

/a../03-impl-and-arch/*  ← followup_manage.py ✅ 正确
  ├── /analytics
  ├── /attempts
  ├── /export
  ├── /candidates       ← Phase 2 占位
  └── /trigger/{id}     ← Phase 2 占位
```

---

## 4. 设置功能修复

### 问题

前端调用 `/a../03-impl-and-arch/settings` 返回 404，设置无法加载和保存。

### 解决方案

在 `realtime_reply.py` 中新增设置端点：

```python
@router.get("/settings", response_model=RealtimeSettings)
async def get_realtime_settings():
    """获取实时回复设置"""
    from services.settings import get_settings_service
    service = get_settings_service()
    followup = service.get_followup_settings()

    return RealtimeSettings(
        scan_interval=followup.default_scan_interval,
        use_ai_reply=followup.use_ai_reply,
        send_via_sidecar=followup.send_via_sidecar,
    )


@router.post("/settings")
async def update_realtime_settings(settings: RealtimeSettings):
    """更新实时回复设置"""
    from services.settings import get_settings_service, SettingCategory
    service = get_settings_service()

    updates = {
        "default_scan_interval": settings.scan_interval,
        "use_ai_reply": settings.use_ai_reply,
        "send_via_sidecar": settings.send_via_sidecar,
    }

    service.set_category(SettingCategory.FOLLOWUP.value, updates, "api")

    return {"success": True, "message": "Settings saved successfully"}
```

**字段映射**:
| 前端字段 | 后端字段 | 类型 |
|---------|---------|------|
| `scan_interval` | `default_scan_interval` | int |
| `use_ai_reply` | `use_ai_reply` | bool |
| `send_via_sidecar` | `send_via_sidecar` | bool |

**存储位置**:

- 统一设置数据库 (`settings` 表)
- 类别: `SettingCategory.FOLLOWUP`

---

## 5. 前端集成

### RealtimeView.vue 更新

```typescript
// 加载设置
async function fetchSettings() {
  const response = await fetch(
    'http://localhost:87../03-impl-and-arch/key-modules/realtime/settings'
  )
  // ...
}

// 保存设置
async function saveSettings() {
  const response = await fetch(
    'http://localhost:87../03-impl-and-arch/key-modules/realtime/settings',
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings.value),
    }
  )
  // ...
}
```

### FollowUpManageView.vue (Phase 2)

```typescript
// 未来可调用
GET / api / followup / analytics
GET / api / followup / attempts
GET / api / followup / candidates
```

---

## 6. 验证结果

### ✅ Linter 检查

```bash
No linter errors found.
```

### ✅ 路由注册

```python
# main.py
app.include_router(realtime_reply.router)   ../03-impl-and-arch/key-modules/realtime/*
app.include_router(followup_manage.router)  # /a../03-impl-and-arch/*
```

### ✅ 导入更新

所有相关文件的导入已更新：

- ✅ `main.py`
- ✅ `test_realtime_reply_api.py`
- ✅ `RealtimeView.vue`

---

## 7. 架构对比

### Before (混合架构)

```
followup.py (772行)
├── Realtime Reply 设备操作 (60%)
├── Follow-up Analytics (35%)
└── 没有 settings 端点 (5% 缺失)
```

**问题**:

- 职责不清
- 路由前缀错误（analytics 挂../03-impl-and-arch/key-modules/realtime）
- 设置端点缺失

### After (分离架构)

```
realtime_reply.py (303行)         followup_manage.py (200行)
├── 设备操作 ✅                   ├── Analytics ✅
├── 设置管理 ✅ 新增              ├── Attempts ✅
└─../03-impl-and-arch/key-modules/realtime/* ✅            ├── Export ✅
                                  ├── Candidates 🚧 占位
                                  └── /a../03-impl-and-arch/* ✅
```

**优点**:

- 职责清晰
- 路由语义正确
- 功能完整（settings 已补齐）

---

## 8. 文件变更总结

### 新增文件 (2)

- ✅ `wecom-desktop/backend/routers/realtime_reply.py`
- ✅ `wecom-desktop/backend/routers/followup_manage.py`

### 删除文件 (1)

- ❌ `wecom-desktop/backend/routers/followup.py`

### 修改文件 (4)

- ✅ `wecom-desktop/backend/main.py`
- ✅ `wecom-desktop/backend/tests/test_realtime_reply_api.py`
- ✅ `wecom-desktop/src/views/RealtimeView.vue`

---

## 9. 兼容性说明

### 向后兼容

保持了以下向后兼容：

- ✅ 数据库表结构未变
- ✅ 数据模型字段未变
- ✅ WebSocket 路径未变

### 破坏性变更

需要前端更新的 API 路径：

- ❌ `/a../03-impl-and-arch/settings` → ✅../03-impl-and-arch/key-modules/realtime/settings` (已更新)

---

## 10. 下一步

### Phase 2 开发（补刀跟进）

当需要开发补刀功能时：

1. **后端**：在 `followup_manage.py` 实现
   - `GET /a../03-impl-and-arch/candidates` - 查询候选客户
   - `POST /a../03-impl-and-arch/trigger/{id}` - 手动触发补刀

2. **前端**：在 `FollowUpManageView.vue` 调用
   - 候选人列表展示
   - 手动触发操作
   - 历史记录查看

3. **数据模型**：重新设计
   - 候选人查询逻辑
   - 优先级评分算法
   - 补刀策略引擎

---

## 11. 总结

### 分离完成度

| 模块     | 分离状态    |
| -------- | ----------- |
| 文件名   | ✅ 完全分离 |
| 路由前缀 | ✅ 语义正确 |
| API 端点 | ✅ 职责清晰 |
| 数据模型 | ✅ 独立定义 |
| 设置管理 | ✅ 功能完整 |

### 关键成果

1. **概念清晰**：实时回复和补刀跟进完全独立
2. **路由语义**../03-impl-and-arch/key-modules/realtime/_`vs`/a../03-impl-and-arch/_`
3. **功能完整**：修复了设置端点缺失问题
4. **易于扩展**：Phase 2 有独立的开发空间
5. **代码整洁**：每个路由文件职责单一

---

**分离成功！现在实时回复和补刀跟进系统在 API 层面完全独立。** 🎉
