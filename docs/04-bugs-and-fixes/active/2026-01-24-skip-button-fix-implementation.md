# Sidecar Skip 按钮修复实施总结

**日期**: 2026-01-24
**实施方案**: 方案 A - 统一使用 Sidecar Skip 机制

---

## 修改的文件

### `wecom-desktop/backend/services/followup_device_manager.py`

#### 修改 1: 移除 Skip Flag 常量（第 29-33 行）

**删除内容**:

```python
# Skip flag file path for follow-up process
# Follow-up subprocess checks this file at start of each scan cycle
FOLLOWUP_SKIP_FLAG_PREFIX = "followup_skip_"
```

**原因**: 不再使用独立的 skip flag 文件机制。

#### 修改 2: 重写 `request_skip()` 方法（第 408-457 行）

**原实现**:

```python
async def request_skip(self, serial: str) -> bool:
    """创建 skip flag 文件"""
    flag_filename = f"{FOLLOWUP_SKIP_FLAG_PREFIX}{serial}"
    flag_path = Path(tempfile.gettempdir()) / flag_filename
    timestamp = datetime.now().isoformat()
    flag_path.write_text(timestamp, encoding="utf-8")
    return True
```

**新实现**:

```python
async def request_skip(self, serial: str) -> bool:
    """
    **统一使用 Sidecar Skip 机制**，而不是创建独立的 skip flag 文件。
    这样可以复用 sync 的 skip 实现，避免维护两套独立的 skip 系统。

    response_detector.py 中已经使用 SidecarQueueClient.is_skip_requested()
    来检测 skip 请求，它会调../03-impl-and-arch/{serial}/skip API。
    """
    # 使用 sidecar skip API（与 sync 共享同一套机制）
    sidecar_skip_url = f"http://localhost:87../03-impl-and-arch/{serial}/skip"

    import httpx
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(sidecar_skip_url)
        if resp.status_code == 200:
            await self._broadcast_log(serial, "INFO", "Skip requested via sidecar API (unified mechanism)")
            return True
        else:
            await self._broadcast_log(serial, "ERROR", f"Skip request failed: HTTP {resp.status_code}")
            return False
```

**关键改动**:

- ✅ 调用 `POS../03-impl-and-arch/{serial}/skip` API（与 sync 共享）
- ✅ 不再创建 `followup_skip_{serial}` 文件
- ✅ 复用现有的 skip 检测机制

---

## 新的 Skip 流程

```
┌─────────────────────────────────────────────────────────────┐
│                    用户点击 Skip 按钮                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  SidecarView.skipDeviceSync(serial)                        │
│    检测到 controlType === 'followup'                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  POST /a../03-impl-and-arch/device/{serial}/skip                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  FollowupDeviceManager.request_skip(serial)                │
│    调用 POS../03-impl-and-arch/{serial}/skip ← 统一机制！            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  sidecar.py: request_skip(serial)                          │
│    _skip_flags[serial] = True                               │
│    清空队列消息                                               │
│    设置 waiting event                                        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  response_detector.py (while 循环)                          │
│    if client and await client.is_skip_requested():          │
│      → SidecarQueueClient.is_skip_requested()              │
│      → GE../03-impl-and-arch/{serial}/skip                           │
│      → 返回 {"skip_requested": true}                        │
│    清空队列，返回聊天列表                                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 优势

### 1. 代码统一

- ✅ Followup 和 Sync 共享同一套 skip 机制
- ✅ 不再维护两套独立的 skip 系统

### 2. 复用现有实现

- ✅ `response_detector.py` 已经在使用 `SidecarQueueClient.is_skip_requested()`
- ✅ 不需要修改检测逻辑

### 3. 更简洁

- ✅ 删除了 51 行不再需要的代码
- ✅ 删除了 skip flag 文件 I/O 操作

### 4. 更可靠

- ✅ 使用内存 flag（\_skip_flags）而不是文件系统
- ✅ 不受 temp 目录权限影响
- ✅ 响应更快

---

## 向后兼容性

- ✅ API 端点不变：仍然是 `/a../03-impl-and-arch/device/{serial}/skip`
- ✅ 前端代码不需要修改
- ✅ 用户操作体验不变

---

## 测试验证

### 手动测试步骤

1. **启动 followup 进程**:

   ```bash
   # 在桌面应用中启动设备的 followup
   ```

2. **触发 skip**:
   - 在 sidecar 界面点击 Skip 按钮
   - 观察日志应该显示：`Skip requested via sidecar API (unified mechanism)`

3. **验证效果**:
   - 当前用户应该被跳过
   - 返回到聊天列表
   - 继续处理下一个用户

### 预期日志输出

```
[INFO] [FollowUp] Skip requested via sidecar API (unified mechanism)
[INFO] [AN2FVB1706003302] ⏭️ Skip requested - clearing queue and returning to chat list
```

---

## 相关文件

- **问题分析**: `docs/04-bugs-and-fixes/active/01-24-sidecar-skip-button-issue.md`
- **实现代码**: `wecom-desktop/backend/services/followup_device_manager.py`
- **检测逻辑**: `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py:341`
- **Skip API**: `wecom-desktop/backend/routers/sidecar.py:1074`

---

## 状态

- [x] 修改 `FollowupDeviceManager.request_skip()` 调用 sidecar API
- [x] 移除 `FOLLOWUP_SKIP_FLAG_PREFIX` 常量
- [x] Python 语法检查通过
- [ ] 实际测试验证（需要设备）
- [ ] 更新相关文档
