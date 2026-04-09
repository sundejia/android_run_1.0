# 实时回复与补刀跟进功能分离

**日期**：2026-01-29  
**版本**：v1.0  
**状态**：✅ Phase 1 & Phase 2 前端已完成，Phase 3 后端待实现

---

## 背景

原有的"Follow-up System"（跟进系统）实际上包含两个不同的功能：

1. **Phase 1**：实时响应检测（红点检测 + AI 自动回复）
2. **Phase 2**：补刀跟进（冷却期后主动发送跟进消息）

但在 UI 上只有一个"Follow-up"导航项，导致：

- 用户概念混淆（Follow-up 本意是"补刀"，但实际主要在用"实时回复"）
- Phase 2 功能没有独立的管理界面
- 难以扩展 Phase 2 的功能

---

## 解决方案

### 方案A：功能分离（已实施）

将"实时回复"和"补刀跟进"两个功能彻底分开，各自拥有独立的：

- 导航项
- 路由
- 视图组件
- 翻译配置

---

## 实施细节

### Phase 1: 改名（快速修复）✅

#### 1.1 导航栏更新

**文件**：`wecom-desktop/src/App.vue`

```typescript
// 修改前
{ key: 'followup', path: '/followup', icon: '🔄' }

// 修改后
{ key: 'realtime', path: '/realtime', icon: '⚡' },
{ key: 'followup_manage', path: '/followup', icon: '🔄' }
```

#### 1.2 翻译更新

**文件**：`wecom-desktop/backend/i18n/translations.py`

新增翻译键：

```python
# 英文
"nav": {
    "realtime": "Realtime Reply",        # Phase 1 instant response
    "followup_manage": "Follow-up",      # Phase 2 follow-up management
}

"realtime": {
    "title": "Realtime Reply",
    "subtitle": "AI-powered instant response system with red-dot detection",
    # ... 其他键
}

"followup_manage": {
    "title": "Follow-up Management",
    "subtitle": "Proactive follow-up strategy for cold customers",
    # ... 其他键
}

# 中文
"nav": {
    "realtime": "实时回复",              # Phase 1 即时响应
    "followup_manage": "补刀跟进",        # Phase 2 跟进管理
}

"realtime": {
    "title": "实时回复",
    "subtitle": "AI 驱动的即时响应系统，带红点检测",
    # ... 其他键
}

"followup_manage": {
    "title": "补刀跟进",
    "subtitle": "针对冷客户的主动跟进策略",
    # ... 其他键
}
```

#### 1.3 视图组件

**新建**：`wecom-desktop/src/views/RealtimeView.vue`

- 复制自 `FollowUpView.vue`
- 更改图标：🔄 → ⚡
- 更改翻译键：`followup.*` → `realtime.*`
- 保持所有功能不变（Phase 1 功能）

---

### Phase 2: 新建补刀跟进页面 ✅

#### 2.1 视图组件

**新建**：`wecom-desktop/src/views/FollowUpManageView.vue`

功能模块：

1. **候选人列表（Candidates）**
   - 显示冷却期结束的客户
   - 显示最后消息、时间、跟进状态
   - 手动触发补刀按钮

2. **策略配置（Strategy）**
   - 启用/禁用跟进功能
   - 冷却期设置（小时）
   - 尝试间隔设置（小时）
   - 最大尝试次数
   - 工作时间限制

3. **历史记录（History）**
   - 跟进尝试历史
   - 响应状态统计
   - 分页显示

#### 2.2 路由配置

**文件**：`wecom-desktop/src/main.ts`

```typescript
// 导入视图
import RealtimeView from './views/RealtimeView.vue'
import FollowUpManageView from './views/FollowUpManageView.vue'

// 路由配置
{
  path: '/realtime',
  name: 'realtime',
  component: RealtimeView,
},
{
  path: '/followup',
  name: 'followup',
  component: FollowUpManageView,
}
```

---

### Phase 3: 后端支持（待实现）⏳

#### 3.1 需要的新 API 端点

**文件**：`wecom-desktop/backend/routers/followup.py`

1. **获取候选人列表**

   ```
   GET /a../03-impl-and-arch/candidates
   返回：冷却期结束、待跟进的客户列表
   ```

2. **获取跟进策略**

   ```
   GET /a../03-impl-and-arch/strategy
   返回：当前的跟进策略配置
   ```

3. **保存跟进策略**

   ```
   POST /a../03-impl-and-arch/strategy
   请求体：策略配置对象
   ```

4. **手动触发跟进**

   ```
   POST /a../03-impl-and-arch/trigger/{candidate_id}
   作用：立即对指定客户触发补刀
   ```

5. **获取跟进历史**（已存在，但可能需要优化）
   ```
   GET /a../03-impl-and-arch/attempts?page=1&pageSize=20
   ```

#### 3.2 数据库表

已存在的表（无需修改）：

- `followup_attempts` - 记录每次跟进尝试
- `followup_settings` - 存储跟进策略配置

#### 3.3 后端逻辑

**候选人筛选逻辑**：

```python
def find_followup_candidates(cooling_period_hours: int) -> List[Candidate]:
    """
    查找满足以下条件的客户：
    1. 最后一条消息是客服发送的
    2. 距离最后一条消息 >= cooling_period_hours
    3. 跟进次数 < max_attempts
    4. 不在黑名单中
    5. 客户未删除
    """
```

**触发补刀逻辑**：

```python
async def trigger_followup(candidate_id: int):
    """
    1. 获取客户信息和对话历史
    2. 调用 AI 生成补刀消息
    3. 通过 Sidecar 发送消息
    4. 记录到 followup_attempts 表
    """
```

---

## 最终导航结构

```
📱 Devices │ 📊 Dashboard │ 🧑‍💼 Kefus │ 💬 Conversations │ 📁 Resources │ 👥 Streamers │ 📋 Logs │ 🚗 Sidecar │ ⚡ 实时回复 │ 🔄 补刀跟进 │ 🚫 Blacklist │ ⚙️ Settings
```

---

## 文件清单

### 新增文件

- ✅ `wecom-desktop/src/views/RealtimeView.vue`
- ✅ `wecom-desktop/src/views/FollowUpManageView.vue`
- ✅ `do../03-impl-and-arch/phase1-phase2-separation.md` (本文档)

### 修改文件

- ✅ `wecom-desktop/src/App.vue` - 导航项配置
- ✅ `wecom-desktop/src/main.ts` - 路由配置
- ✅ `wecom-desktop/backend/i18n/translations.py` - 翻译配置
- ✅ `do../03-impl-and-arch/followup-system-logic.md` - 架构说明更新

### 未修改文件

- ✅ `wecom-desktop/src/views/FollowUpView.vue` - 保留原样（可删除或作为参考）
- ✅ `wecom-desktop/backend/services/followup_process.py` - 执行逻辑不变
- ✅ `wecom-desktop/backend/services/followup_device_manager.py` - 进程管理不变
- ✅ `wecom-desktop/backend/routers/followup.py` - 现有 API 保持兼容

---

## 测试清单

### Phase 1 测试（实时回复）✅

- [x] 导航项显示"⚡ 实时回复" / "Realtime Reply"
- [x] 点击导航项跳转到 `/realtime`
- [x] 页面显示正确的标题和副标题
- [x] 设备列表、数据分析、设置等标签正常工作
- [x] 启动/停止功能正常
- [x] 翻译切换正常（中英文）

### Phase 2 测试（补刀跟进）⏳

- [ ] 导航项显示"🔄 补刀跟进" / "Follow-up"
- [ ] 点击导航项跳转到 `/followup`
- [ ] 页面显示正确的标题和副标题
- [ ] 候选人列表标签显示（当前为 mock 数据）
- [ ] 策略配置标签可以编辑和保存（需要后端 API）
- [ ] 历史记录标签显示（需要后端 API）
- [ ] 手动触发补刀按钮（需要后端 API）
- [ ] 翻译切换正常（中英文）

### Phase 3 测试（后端 API）⏳

- [ ] GET `/a../03-impl-and-arch/candidates` 返回正确的候选人
- [ ] GET `/a../03-impl-and-arch/strategy` 返回策略配置
- [ ] POST `/a../03-impl-and-arch/strategy` 保存策略成功
- [ ] POST `/a../03-impl-and-arch/trigger/{id}` 触发补刀成功
- [ ] 后端日志记录正确

---

## 待办事项

### 高优先级

1. ⏳ 实现 Phase 3 后端 API 端点
2. ⏳ 实现候选人筛选逻辑
3. ⏳ 实现手动触发补刀功能
4. ⏳ 测试完整流程

### 中优先级

5. ⏳ 优化候选人列表的分页和过滤
6. ⏳ 添加补刀效果统计（转化率、响应率等）
7. ⏳ 添加补刀消息模板管理
8. ⏳ 支持不同客户类型的差异化策略

### 低优先级

9. ⏳ 添加补刀效果可视化图表
10. ⏳ 支持 A/B 测试不同的补刀策略
11. ⏳ 删除旧的 `FollowUpView.vue`（可选）

---

## 注意事项

### 兼容性

- ✅ 现有 API 端点保持不变
- ✅ `followup_process.py` 执行逻辑不变
- ✅ Sidecar 发送消息逻辑不变
- ✅ 数据库表结构不变

### 代码规范

- ✅ 使用 Vue 3 Composition API + `<script setup>`
- ✅ 使用 TypeScript 类型定义
- ✅ 使用 Tailwind CSS（遵循 wecom-\* 主题）
- ✅ 所有用户可见文字支持 i18n

### 文档

- ✅ 更新了架构说明文档
- ✅ 创建了重构总结文档
- ⏳ 需要添加 API 文档（Phase 3 完成后）

---

## 变更历史

| 日期       | 版本 | 变更内容                        | 作者         |
| ---------- | ---- | ------------------------------- | ------------ |
| 2026-01-29 | v1.0 | 完成 Phase 1 & Phase 2 前端实现 | AI Assistant |

---

## 参考文档

- [Follow-up System 逻辑文档](./followup-system-logic.md)
- [Sidecar 消息发送文档](../03-impl-and-arch/sidecar-message-sending.md)
- [AI 配置文档](../03-impl-and-arch/key-modules/ai_prompt_context_logic.md)
