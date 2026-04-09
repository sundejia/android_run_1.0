# 实时回复与补刀跟进功能分离

**日期**: 2026-01-30  
**目的**: 彻底分离 Phase 1（实时回复）和 Phase 2（补刀跟进）的代码和界面

---

## 架构分离概览

### Before (混合架构)

```
┌─────────────────────────────────────────────────────────────┐
│  Follow-up System (混合)                                    │
├─────────────────────────────────────────────────────────────┤
│  • Phase 1: 实时回复（正在使用）                            │
│  • Phase 2: 补刀跟进（代码存在但未使用）                    │
│                                                             │
│  问题：                                                      │
│  - 概念混淆（Follow-up 名不副实）                           │
│  - Phase 2 遗留代码占用空间                                 │
│  - 难以独立扩展                                             │
└─────────────────────────────────────────────────────────────┘
```

### After (分离架构)

```
┌──────────────────────────┐    ┌──────────────────────────┐
│  实时回复系统 (Phase 1)  │    │  补刀跟进系统 (Phase 2)  │
│  ⚡ Realtime Reply       │    │  🔄 Follow-up Manage     │
├──────────────────────────┤    ├──────────────────────────┤
│  • 红点检测              │    │  • 未来独立开发          │
│  • AI 自动回复           │    │  • 新的补刀流程          │
│  • Sidecar 队列          │    │  • 独立的候选人查询      │
│  • 完整独立代码           │    │  • 独立的消息生成        │
└──────────────────────────┘    └──────────────────────────┘
```

---

## 前端分离

### 导航栏结构变化

**Before:**

```
🔄 Follow-up → /followup → FollowUpView.vue (管理实时回复)
```

**After:**

```
⚡ 实时回复 (Realtime Reply)  → /followup          → FollowUpView.vue
🔄 补刀跟进 (Follow-up Manage) → /followup-manage  → FollowUpManageView.vue (新建)
```

### 界面职责划分

| 界面         | 路由               | 主要功能                                                                           | 状态      |
| ------------ | ------------------ | ---------------------------------------------------------------------------------- | --------- |
| **实时回复** | `/followup`        | • 管理设备实时回复进程<br>• 启动/停止/暂停设备<br>• 查看实时统计<br>• 配置扫描间隔 | ✅ 完成   |
| **补刀跟进** | `/followup-manage` | • 查看补刀候选客户<br>• 配置补刀策略<br>• 查看补刀历史<br>• 手动触发补刀           | 🚧 待开发 |

### 修改的文件

1. **translations.py**
   - 添加 `nav.realtime` 和 `nav.followup_manage`
   - 添加 `realtime.*` 和 `followup_manage.*` 翻译键
   - 修复重复的 `customers` 和 `settings` 键

2. **App.vue**
   - 修改导航项：`followup` → `realtime` (⚡)
   - 添加导航项：`followup_manage` (🔄)
   - 修复 `isActive()` 函数避免双选

3. **FollowUpView.vue**
   - 修改标题：使用 `realtime.title`
   - 修改副标题：使用 `realtime.subtitle`
   - 修改图标：🔄 → ⚡

4. **main.ts**
   - 添加 `FollowUpManageView` 导入
   - 添加路由 `/followup-manage`

5. **FollowUpManageView.vue** (新建)
   - 3个Tab：候选人/历史/设置
   - 统计卡片显示
   - 设备过滤器
   - UI 框架完整（API 待实现）

6. **CustomersListView.vue**
   - 修复翻译键：`customers.*` → `conversations.*`

---

## 后端分离

### 代码清理策略

#### 🗑️ 已删除的 Phase 2 代码

| 文件            | 删除内容                                | 原因                 |
| --------------- | --------------------------------------- | -------------------- |
| `models.py`     | `FollowUpCandidate` 类                  | Phase 2 专用模型     |
| `models.py`     | `PendingCustomer` 类                    | Phase 2 专用模型     |
| `repository.py` | `find_candidates()` 方法                | Phase 2 候选人查询   |
| `repository.py` | `get_pending_customers()` 方法          | Phase 2 待处理客户   |
| `repository.py` | `save_followup_message()` 方法          | Phase 2 专用消息保存 |
| `service.py`    | `find_followup_candidates()` 方法       | Phase 2 查询封装     |
| `service.py`    | `get_pending_followup_customers()` 方法 | Phase 2 查询封装     |
| `service.py`    | `generate_followup_message()` 方法      | Phase 2 消息生成     |
| `__init__.py`   | `FollowUpCandidate` 导出                | 清理导出             |

#### ✅ 保留的 Phase 1 代码

| 文件                        | 保留内容                                                                                                             | 用途             |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------- | ---------------- |
| `realtime_reply_process.py` | 完整保留                                                                                                             | 主进程入口       |
| `response_detector.py`      | 完整保留                                                                                                             | 核心检测逻辑     |
| `repository.py`             | `save_message()`<br>`record_attempt()`<br>`mark_responded()`<br>`find_or_create_customer()`<br>`get_attempt_count()` | Phase 1 基础操作 |
| `service.py`                | 日志系统<br>数据库连接<br>设置管理                                                                                   | Phase 1 基础服务 |
| `models.py`                 | `FollowUpAttempt`<br>`ScanResult`                                                                                    | Phase 1 数据模型 |
| `settings.py`               | 完整保留                                                                                                             | 配置管理         |

---

## 关键验证点

### ✅ Phase 1 功能完整性验证

1. **realtime_reply_process.py 可正常运行**

   ```bash
   python realtime_reply_process.py --serial DEVICE123 --send-via-sidecar
   ```

   - ✅ 红点检测正常
   - ✅ 消息提取正常
   - ✅ Sidecar 发送正常

2. **数据库操作正常**
   - ✅ `save_message()` - 保存消息
   - ✅ `record_attempt()` - 记录尝试
   - ✅ `mark_responded()` - 标记回复
   - ✅ `find_or_create_customer()` - 客户管理

3. **前端界面正常**
   - ✅ 实时回复页面显示正确
   - ✅ 设备启动/停止功能正常
   - ✅ 统计数据正常显示

### 🚧 Phase 2 准备工作

1. **新界面已就绪**
   - ✅ `/followup-manage` 路由配置
   - ✅ `FollowUpManageView.vue` 组件
   - ✅ UI 框架完整（3个Tab）

2. **后端 API 占位**
   - ✅ `GET /a../03-impl-and-arch/candidates` - 查询候选人（待实现）
   - ✅ `POST /a../03-impl-and-arch/trigger/{id}` - 手动触发（待实现）

3. **未来开发方向**
   - 新的候选人查询逻辑
   - 新的补刀策略设计
   - 新的消息生成机制
   - 独立的统计分析

---

## 分离的好处

### 1. 概念清晰

- **实时回复**：看到红点就回复（主动）
- **补刀跟进**：冷却期后催促（被动）
- 两者业务逻辑完全不同，分离后更易理解

### 2. 代码整洁

- 删除未使用的遗留代码
- Phase 1 代码简洁明了
- Phase 2 有独立的开发空间

### 3. 独立扩展

- Phase 1 可以专注优化检测速度和回复质量
- Phase 2 可以全新设计补刀策略（如基于用户行为分析）
- 两者互不影响

### 4. 维护方便

- Bug 定位更容易
- 功能测试更独立
- 代码review更高效

---

## 未来 Phase 2 开发建议

### 数据模型（重新设计）

```python
@dataclass
class FollowUpCandidate:
    """补刀候选人（新设计）"""
    customer_id: int
    customer_name: str
    channel: str
    device_serial: str
    last_kefu_message_time: datetime
    days_since_last_contact: int
    priority_score: int  # 新增：优先级评分
    suggested_message: str  # 新增：AI 生成的建议消息
    cooling_status: str  # 'ready', 'cooling', 'completed'
```

### 查询策略（优化方向）

- 支持多维度筛选（设备、客服、渠道）
- 引入优先级评分（基于历史互动频率）
- 支持自定义冷却期策略
- 考虑用户活跃时段

### 消息生成（智能化）

- AI 根据对话历史生成个性化消息
- 支持多套话术模板
- 根据客户类型自动选择话术

---

## 风险控制

### ✅ 已验证无风险项

- ❌ 无其他代码调用已删除的方法
- ❌ 无循环依赖
- ❌ 无数据库迁移需求（表结构未变）

### ⚠️ 注意事项

1. **旧文档可能过时**：一些文档中提到 Phase 2 的逻辑需要更新
2. **API 响应格式**：如果有外部调用，需要确认兼容性
3. **数据库查询**：Phase 1 仍使用 `followup_attempts` 表记录数据

---

## 总结

### 完成的工作

- ✅ 前端：界面分离，导航清晰
- ✅ 后端：删除 Phase 2 遗留代码
- ✅ 翻译：中英文完整支持
- ✅ 文档：更新架构说明

### 当前状态

- ✅ Phase 1（实时回复）功能完整，可正常使用
- 🚧 Phase 2（补刀跟进）UI 就绪，后端待开发

### 下一步

当需要开发新的补刀系统时：

1. 在 `FollowUpManageView.vue` 中实现前端逻辑
2. 在 `followup.py` 中实现后端 API
3. 创建新的数据模型和查询逻辑
4. 独立测试，不影响 Phase 1

---

**分离完成！实时回复系统现在是一个干净、独立、完整的模块。** 🎉
