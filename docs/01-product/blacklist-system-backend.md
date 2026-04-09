# 黑名单系统 - 后端设计文档

> 本文档专注于后端实现，由 GLM4.7 负责开发

## 背景

在 FollowUp 和 Sync 流程中，某些用户可能不希望被自动跟进或同步。需要一个黑名单系统来管理这些用户，避免程序自动进入这些用户的聊天。

## 后端需求

### 核心功能

1. **数据库存储**: 持久化存储黑名单数据
2. **API 接口**: 提供 CRUD 操作接口
3. **运行时检查**: 在 Sync/FollowUp 流程中跳过黑名单用户

## 技术方案

### 1. 数据库设计

在 `conversations.db` 中新增 `blacklist` 表：

```sql
CREATE TABLE IF NOT EXISTS blacklist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_serial TEXT NOT NULL,           -- 设备序列号
    customer_name TEXT NOT NULL,           -- 用户名
    customer_channel TEXT,                 -- 渠道 (如 @WeChat)
    reason TEXT,                           -- 加入原因 (可选)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- 唯一约束：同一设备下的用户名+渠道唯一
    UNIQUE(device_serial, customer_name, customer_channel)
);

-- 索引：加速查询
CREATE INDEX IF NOT EXISTS idx_blacklist_device ON blacklist(device_serial);
CREATE INDEX IF NOT EXISTS idx_blacklist_name ON blacklist(customer_name);
```

### 2. 后端 API 设计

新建 `backend/routers/blacklist.py`：

```python
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter()

# ============ 数据模型 ============

class BlacklistEntry(BaseModel):
    """黑名单条目"""
    id: int
    device_serial: str
    customer_name: str
    customer_channel: Optional[str] = None
    reason: Optional[str] = None
    created_at: str

class BlacklistAddRequest(BaseModel):
    """添加黑名单请求"""
    device_serial: str
    customer_name: str
    customer_channel: Optional[str] = None
    reason: Optional[str] = None

class BlacklistRemoveRequest(BaseModel):
    """移除黑名单请求"""
    device_serial: str
    customer_name: str
    customer_channel: Optional[str] = None

class CustomerWithBlacklistStatus(BaseModel):
    """带黑名单状态的用户"""
    customer_name: str
    customer_channel: Optional[str] = None
    is_blacklisted: bool
    blacklist_reason: Optional[str] = None
    last_message_at: Optional[str] = None
    message_count: int = 0

# ============ API 端点 ============

@router.get("/blacklist")
async def list_blacklist(
    device_serial: Optional[str] = Query(None, description="按设备筛选"),
) -> List[BlacklistEntry]:
    """获取黑名单列表"""
    pass

@router.get("/blacklist/customers")
async def list_customers_with_status(
    device_serial: str = Query(..., description="设备序列号"),
    search: Optional[str] = Query(None, description="用户名搜索"),
    filter: Optional[str] = Query("all", description="筛选: all/blacklisted/not_blacklisted"),
) -> List[CustomerWithBlacklistStatus]:
    """获取设备的所有用户及其黑名单状态"""
    pass

@router.post("/blacklist/add")
async def add_to_blacklist(request: BlacklistAddRequest) -> dict:
    """添加用户到黑名单"""
    pass

@router.post("/blacklist/remove")
async def remove_from_blacklist(request: BlacklistRemoveRequest) -> dict:
    """从黑名单移除用户"""
    pass

@router.get("/blacklist/check")
async def check_blacklist(
    device_serial: str = Query(...),
    customer_name: str = Query(...),
    customer_channel: Optional[str] = Query(None),
) -> dict:
    """检查用户是否在黑名单中（供运行时调用）"""
    pass

@router.post("/blacklist/batch-add")
async def batch_add_to_blacklist(entries: List[BlacklistAddRequest]) -> dict:
    """批量添加到黑名单"""
    pass

@router.post("/blacklist/batch-remove")
async def batch_remove_from_blacklist(entries: List[BlacklistRemoveRequest]) -> dict:
    """批量从黑名单移除"""
    pass
```

### 3. 黑名单服务层

新建 `backend/services/blacklist_service.py`：

```python
from typing import List, Optional, Set, Tuple
from wecom_automation.database.schema import get_connection

class BlacklistService:
    """黑名单服务"""

    # 内存缓存：避免频繁查库
    _cache: dict[str, Set[Tuple[str, Optional[str]]]] = {}
    _cache_loaded: bool = False

    @classmethod
    def load_cache(cls) -> None:
        """加载黑名单到内存缓存"""
        pass

    @classmethod
    def is_blacklisted(
        cls,
        device_serial: str,
        customer_name: str,
        customer_channel: Optional[str] = None,
    ) -> bool:
        """
        检查用户是否在黑名单中

        运行时高频调用，使用内存缓存。
        """
        pass

    @classmethod
    def add_to_blacklist(
        cls,
        device_serial: str,
        customer_name: str,
        customer_channel: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> bool:
        """添加到黑名单"""
        pass

    @classmethod
    def remove_from_blacklist(
        cls,
        device_serial: str,
        customer_name: str,
        customer_channel: Optional[str] = None,
    ) -> bool:
        """从黑名单移除"""
        pass

    @classmethod
    def invalidate_cache(cls) -> None:
        """清除缓存（在添加/删除后调用）"""
        cls._cache.clear()
        cls._cache_loaded = False
```

### 4. 运行时集成

#### 4.1 Sync Service 集成

在 `src/wecom_automation/services/sync_service.py` 中：

```python
from backend.services.blacklist_service import BlacklistService

class InitialSyncService:
    async def _should_skip_user(self, device_serial: str, user_name: str, channel: Optional[str]) -> bool:
        """检查是否应跳过该用户"""
        # 检查黑名单
        if BlacklistService.is_blacklisted(device_serial, user_name, channel):
            self._logger.info(f"跳过黑名单用户: {user_name}")
            return True
        return False
```

#### 4.2 FollowUp Scanner 集成

在 `backend/servic../03-impl-and-arch/scanner.py` 中：

```python
from backend.services.blacklist_service import BlacklistService

class FollowUpScanner:
    async def _process_single_user(self, wecom, serial, user_name, user_channel):
        # 黑名单检查
        if BlacklistService.is_blacklisted(serial, user_name, user_channel):
            logger.info(f"[{serial}] 跳过黑名单用户: {user_name}")
            return {"skipped": True, "reason": "blacklisted"}

        # ... 原有逻辑 ...
```

#### 4.3 Response Detector 集成

在 `backend/servic../03-impl-and-arch/response_detector.py` 中的相应位置添加黑名单检查。

### 5. 主程序注册路由

在 `backend/main.py` 中：

```python
from backend.routers import blacklist

app.include_router(blacklist.router, prefix="/api", tags=["blacklist"])
```

## 文件清单

| 文件                                                     | 类型 | 描述            |
| -------------------------------------------------------- | ---- | --------------- |
| `backend/routers/blacklist.py`                           | 新建 | 黑名单 API 路由 |
| `backend/services/blacklist_service.py`                  | 新建 | 黑名单服务层    |
| `src/wecom_automation/services/sync_service.py`          | 修改 | 集成黑名单检查  |
| `backend/servic../03-impl-and-arch/scanner.py`           | 修改 | 集成黑名单检查  |
| `backend/servic../03-impl-and-arch/response_detector.py` | 修改 | 集成黑名单检查  |
| `backend/main.py`                                        | 修改 | 注册黑名单路由  |

## 实现计划

### Phase 1: 数据库和服务层

1. 创建 `blacklist` 表
2. 实现 `BlacklistService` 服务类
3. 实现缓存机制

### Phase 2: API 接口

1. 实现 `blacklist.py` 路由
2. 在 `main.py` 中注册路由
3. 测试 API 端点

### Phase 3: 运行时集成

1. 修改 `sync_service.py`
2. 修改 `scanner.py`
3. 修改 `response_detector.py`

### Phase 4: 测试验证

1. 测试 API 端点
2. 测试运行时跳过逻辑
3. 性能测试（缓存效果）

## 注意事项

1. **性能优化**: 使用内存缓存减少数据库查询
2. **缓存一致性**: 添加/删除后及时清除缓存
3. **重复检查**: 使用 UNIQUE 约束防止重复添加
4. **渠道处理**: 同一用户名可能来自不同渠道，需要组合判断
5. **日志记录**: 记录跳过黑名单用户的操作日志
6. **线程安全**: 缓存操作需考虑线程安全问题

## API 测试用例

```bash
# 获取黑名单列表
curl -X GET "http://localhost:80../03-impl-and-arch/key-modules/blacklist"

# 获取指定设备的用户列表（带黑名单状态）
curl -X GET "http://localhost:80../03-impl-and-arch/key-modules/blacklist/customers?device_serial=DEVICE123"

# 添加到黑名单
curl -X POST "http://localhost:80../03-impl-and-arch/key-modules/blacklist/add" \
  -H "Content-Type: application/json" \
  -d '{"device_serial": "DEVICE123", "customer_name": "张三", "reason": "测试"}'

# 从黑名单移除
curl -X POST "http://localhost:80../03-impl-and-arch/key-modules/blacklist/remove" \
  -H "Content-Type: application/json" \
  -d '{"device_serial": "DEVICE123", "customer_name": "张三"}'

# 检查是否在黑名单
curl -X GET "http://localhost:80../03-impl-and-arch/key-modules/blacklist/check?device_serial=DEVICE123&customer_name=张三"
```

## 下一步

1. [ ] 创建数据库表
2. [ ] 实现 BlacklistService
3. [ ] 实现 API 路由
4. [ ] 集成到运行时流程
5. [ ] 测试验证
