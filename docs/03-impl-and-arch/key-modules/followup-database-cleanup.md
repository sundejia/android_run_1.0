# Follow-up 数据库代码清理

## 清理目标

将 follow-up 相关的数据库代码从通用数据库层移除，因为：

1. **职责分离**：Follow-up management（Phase 2 补刀系统）应该独立管理自己的数据
2. **避免冗余**：`followup_manage.py` 路由已经自己创建和管理 `followup_attempts` 表
3. **简化依赖**：Realtime reply 不再需要 follow-up attempts 追踪功能

## 清理内容

### 1. FollowUpRepository (`wecom-desktop/backend/servic../03-impl-and-arch/repository.py`)

**移除的表创建代码：**

- `_ensure_tables()` 中删除了创建 `followup_attempts` 表的 SQL
- 删除了 `idx_followup_attempts_customer` 和 `idx_followup_attempts_date` 索引创建

**移除的方法：**

- `record_attempt()` - 记录跟进尝试到 followup_attempts 表
- `mark_responded()` - 标记客户已回复
- `get_attempt_count()` - 获取待回复跟进尝试次数

**保留的方法：**

- `find_or_create_customer()` - Realtime reply 需要
- `save_message()` - 存储消息（基础功能）
- 其他基础数据库操作

### 2. FollowUpService (`wecom-desktop/backend/servic../03-impl-and-arch/service.py`)

**移除的包装方法：**

- `record_attempt()` - 调用 repository.record_attempt
- `mark_customer_responded()` - 调用 repository.mark_responded
- `get_customer_attempt_count()` - 调用 repository.get_attempt_count

这些方法在当前架构中已经没有调用者。

### 3. FollowUpAttempt 模型 (`wecom-desktop/backend/servic../03-impl-and-arch/models.py`)

**移除：**

- `@dataclass class FollowUpAttempt` - 跟进尝试记录模型
- `__init__.py` 中的 `FollowUpAttempt` 导出

**原因：**

- Repository 和 Service 不再使用此模型
- `followup_manage.py` 路由使用自己的 Pydantic `FollowUpAttempt` 模型（不同的定义）

### 4. 主数据库 Schema (`src/wecom_automation/database/schema.py`)

**移除注释中的 "followup" 提及：**

```sql
-- 旧: Blacklist table: users to skip during sync/followup
-- 新: Blacklist table: users to skip during sync
```

主数据库从未包含 `followup_attempts` 表，只在注释中提及。

## 架构说明

### 移除后的架构

```
主数据库 (src/wecom_automation/database/)
├── schema.py          - 核心表：devices, kefus, customers, messages, images, videos, blacklist
└── repository.py      - 会话数据操作（ConversationRepository）

Follow-up 模块 (wecom-desktop/backend/servic../03-impl-and-arch/)
├── repository.py      - 基础操作（customers, messages）- 给 Realtime Reply 用
├── service.py         - 服务封装 - 给 Realtime Reply 用
├── response_detector.py - 实时回复检测器（Phase 1）
└── settings.py        - 设置管理

Follow-up Management API (wecom-desktop/backend/routers/)
└── followup_manage.py - Phase 2 补刀管理（统计/导出）
    ├── 自己创建 followup_attempts 表
    ├── 定义自己的 FollowUpAttempt Pydantic 模型
    └── 直接操作数据库（不依赖 FollowUpRepository）
```

### 关键点

1. **表创建职责**
   - `followup_attempts` 表由 `followup_manage.py` 路由自己管理（`_ensure_followup_tables`）
   - FollowUpRepository 不再创建此表

2. **数据访问**
   - Realtime Reply (response_detector) 使用 FollowUpRepository 的基础方法（customer/message）
   - Follow-up Management API 直接操作数据库，不依赖 FollowUpRepository

3. **模型定义**
   - `followup/models.py` 的 FollowUpAttempt 已删除
   - `followup_manage.py` 有自己的 Pydantic FollowUpAttempt（用于 API 响应）

## 影响范围

**无破坏性影响：**

- ✅ Realtime reply (response_detector) 不使用被移除的方法
- ✅ Follow-up management API (followup_manage.py) 自己管理 followup_attempts
- ✅ 主同步服务不依赖 followup 表

**清理的是死代码：**

- 被移除的方法和模型在当前架构中已无调用者
- 表创建重复（repository 和 router 都创建）- 现在只由 router 创建

## 验证

运行以下命令验证无语法错误：

```bash
python -m py_compile wecom-desktop/backend/servic../03-impl-and-arch/*.py
```

所有文件编译通过，无语法错误。

---

_清理完成时间: 2026-01-30_
