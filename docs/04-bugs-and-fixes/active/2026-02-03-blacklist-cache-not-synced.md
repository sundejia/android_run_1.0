# Bug: 黑名单缓存不同步 - 加入黑名单后仍被点击进入

**日期**: 2026-02-03  
**状态**: ✅ 已修复  
**严重程度**: 高  
**影响**: Follow-up 系统无法正确跳过黑名单用户

## 修复说明

已修改 `BlacklistChecker.is_blacklisted()` 方法，默认直接查询数据库而非使用缓存，确保 Follow-up 子进程能够立即看到前端 Block 操作的效果。

**修改文件**: `src/wecom_automation/services/blacklist_service.py`

**修改内容**:

- 添加 `use_cache` 参数（默认为 `False`）
- 默认情况下直接查询数据库，保证实时准确性
- 提供缓存选项供批量操作使用以提高性能

---

## 问题描述

用户通过前端 Sidecar 页面的 Block 按钮将用户加入黑名单后，Follow-up 系统在下一次扫描时仍然会点击进入该用户的聊天。

### 期望行为

1. 点击 Block 按钮 → 用户加入黑名单
2. Follow-up 系统检测到黑名单 → 跳过该用户（不点击进入聊天）

### 实际行为

1. 点击 Block 按钮 → 用户加入黑名单 ✅
2. Follow-up 系统仍然点击进入该用户聊天 ❌

---

## 根本原因

项目中存在**两个独立的黑名单服务类**，各自维护独立的内存缓存：

### 1. `BlacklistService`（后端 API 使用）

- **位置**: `wecom-desktop/backend/services/blacklist_service.py`
- **用途**: 后端 API 路由调用，处理前端请求
- **缓存**: `BlacklistService._cache` 和 `BlacklistService._cache_loaded`

### 2. `BlacklistChecker`（Follow-up 进程使用）

- **位置**: `src/wecom_automation/services/blacklist_service.py`
- **用途**: response_detector.py 导入并使用
- **缓存**: `BlacklistChecker._cache` 和 `BlacklistChecker._cache_loaded`

### 问题流程

```
┌─────────────────────────────────────────────────────────────────────┐
│                        前端 Block 按钮点击                           │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│              POS../03-impl-and-arch/key-modules/blacklist/toggle                              │
│                                                                      │
│  blacklist.py 路由调用:                                               │
│    BlacklistService().add_to_blacklist(...)                          │
│    BlacklistService.invalidate_cache()  ← 只清除后端缓存！            │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                │  ❌ BlacklistChecker 缓存未被清除
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Follow-up 子进程 (realtime_reply_process.py)            │
│                                                                      │
│  response_detector.py 检查:                                          │
│    from wecom_automation.services.blacklist_service import           │
│        BlacklistChecker                                              │
│                                                                      │
│    if BlacklistChecker.is_blacklisted(...):                          │
│        # 使用过期的缓存数据 → 返回 False ❌                           │
│        # 用户未被正确跳过！                                           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 代码分析

### 缓存加载逻辑 (BlacklistChecker)

```python
# src/wecom_automation/services/blacklist_service.py

class BlacklistChecker:
    _cache: dict[str, set[tuple[str, str | None]]] = {}
    _cache_loaded: bool = False  # 类级别变量

    @classmethod
    def is_blacklisted(cls, device_serial, customer_name, customer_channel):
        # 缓存只在第一次调用时加载
        if not cls._cache_loaded:
            cls.load_cache()  # 从数据库加载

        # 后续调用都使用缓存，不再查询数据库
        return (customer_name, customer_channel) in cls._cache.get(device_serial, set())
```

### 问题点

1. **缓存在进程启动时加载一次**：Follow-up 子进程启动后，`BlacklistChecker` 加载缓存
2. **缓存不会自动刷新**：除非显式调用 `invalidate_cache()`，缓存永不更新
3. **后端和子进程运行在不同进程中**：后端调用 `BlacklistService.invalidate_cache()` 只清除后端进程的缓存，子进程的 `BlacklistChecker._cache` 不受影响

---

## 解决方案

### 方案 A: 每次检查都重新查询数据库（推荐）

修改 `BlacklistChecker.is_blacklisted()` 方法，去除缓存，直接查询数据库。

**优点**：

- 实现简单，修改小
- 始终读取最新数据
- 不需要跨进程通信

**缺点**：

- 每次检查都有 IO 开销
- 性能略有下降（但对于 Follow-up 流程来说可以接受）

```python
# 修改后的代码
@classmethod
def is_blacklisted(cls, device_serial, customer_name, customer_channel):
    """直接查询数据库，不使用缓存"""
    try:
        db_path = str(get_db_path())
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 1 FROM blacklist
            WHERE device_serial = ?
              AND customer_name = ?
              AND (customer_channel = ? OR (customer_channel IS NULL AND ? IS NULL))
              AND is_blacklisted = 1
            LIMIT 1
        """, (device_serial, customer_name, customer_channel, customer_channel))

        result = cursor.fetchone() is not None
        conn.close()
        return result

    except Exception as e:
        logger.warning(f"Failed to check blacklist: {e}")
        return False  # 查询失败时默认不拉黑
```

### 方案 B: 定时刷新缓存

在 `is_blacklisted()` 中添加缓存超时机制，每隔 N 秒重新加载缓存。

```python
import time

class BlacklistChecker:
    _cache_loaded_at: float = 0
    CACHE_TTL: int = 30  # 30秒缓存过期

    @classmethod
    def is_blacklisted(cls, device_serial, customer_name, customer_channel):
        # 检查缓存是否过期
        if not cls._cache_loaded or (time.time() - cls._cache_loaded_at > cls.CACHE_TTL):
            cls.load_cache()
            cls._cache_loaded_at = time.time()

        # ... 正常检查逻辑
```

### 方案 C: 使用统一的服务类

重构代码，让 `response_detector.py` 也使用 `BlacklistService`（后端服务类）。

**注意**：这需要更多的代码修改，因为两个服务在不同的模块路径下。

---

## 受影响的文件

| 文件                                                                   | 说明                                   |
| ---------------------------------------------------------------------- | -------------------------------------- |
| `src/wecom_automation/services/blacklist_service.py`                   | `BlacklistChecker` 类需要修改          |
| `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py` | 使用 `BlacklistChecker` 进行黑名单检查 |
| `wecom-desktop/backend/services/blacklist_service.py`                  | 后端 `BlacklistService` 类（参考）     |

---

## 临时解决方法

在修复代码之前，可以通过以下方式临时解决：

1. **重启 Follow-up 进程**：停止并重新启动 Follow-up，新进程会加载最新的黑名单数据
2. **使用 Sync 模式**：全量同步模式会在每次同步开始时加载白名单

---

## 测试验证

修复后需要验证以下场景：

1. [ ] Follow-up 运行中，前端 Block 用户 → Follow-up 立即跳过该用户
2. [ ] Follow-up 运行中，前端解除 Block → Follow-up 立即开始处理该用户
3. [ ] 多次 Block/解除操作后，Follow-up 行为正确
4. [ ] 重启 Follow-up 后，黑名单状态正确

---

## 附录：相关代码位置

### response_detector.py 中的黑名单检查

```python
# wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py

# 第 35 行 - 导入
from wecom_automation.services.blacklist_service import BlacklistChecker

# 第 904-908 行 - 黑名单检查
if BlacklistChecker.is_blacklisted(serial, user_name, user_channel):
    self._logger.info(f"[{serial}] ⛔ Skipping blacklisted user: {user_name}")
    result["skipped"] = True
    return result
```

### 前端 Block 按钮调用的 API

```typescript
// SidecarView.vue toggleBlockUser()
await fetch../03-impl-and-arch/key-modules/blacklist/toggle`, {
  method: 'POST',
  body: JSON.stringify({
    device_serial: serial,
    customer_name: customerName,
    customer_channel: channel,
  }),
})
```
