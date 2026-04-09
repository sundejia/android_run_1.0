# 全量同步第一阶段 Bug 修复 PRD

## 1. 背景 (Context)

全量同步（Full Sync）是系统核心功能，负责将 WeCom 客户端的聊天记录同步到本地数据库。
第一阶段（Phase 1）主要负责**环境初始化**和**获取待同步客户列表**，为后续的逐个客户消息同步（Phase 2）做准备。

### Phase 1 核心流程

1.  **初始化 (`_initialize`)**:
    - 确保 WeCom 客户端已打开 (`_ensure_wecom_open`)。
    - 获取当前登录的客服（Kefu）信息 (`get_kefu_info`)。
    - 在数据库中注册或更新 Device 和 Kefu 记录。
2.  **获取客户列表 (`_get_customers`)**:
    - 导航至私聊列表界面 (`switch_to_private_chats`)。
    - 滚动并提取所有客户列表 (`extract_private_chat_users`)。
    - (可选) 根据未读消息状态对列表进行排序或过滤。

## 2. 问题描述 (Problem Description)

**现象**：当微信好友列表过长（例如数千人）时，程序无法完成全量同步，甚至无法获取完整的好友列表。
**具体表现**：

- **无法回到列表顶部**：程序尝试“滚动到顶部”操作，但对于长列表，默认的重试次数不足以回到顶部。

  > [!IMPORTANT]
  > **最新发现 (2025-01-03)**: 日志显示 `scroll_to_top` 默认仅尝试 3 次 (`max_attempts=3`)，这对于含有数百/数千用户的长列表完全不足。

- **列表获取不全**：提取用户列表时，受限于默认的 `max_scrolls` 限制，只能获取列表的一部分（通常是顶部或中间的一小段）。
- **逻辑失效**：由于未能获取所有用户，导致只有部分用户被纳入同步计划，遗漏大量用户。用户感知为“程序未能运行”或“数据缺失”。

## 3. 当前实现分析 (Current Implementation)

该逻辑主要位于 `src/wecom_automation/services/wecom_service.py` 和 `adb_service.py` 中。

### 3.1 滚动到顶部逻辑 (`adb_service.py`)

```python
async def scroll_to_top(self, scroll_count: int = 3) -> None:
    # 默认尝试次数非常有限 (Config默认 6 次)
    max_attempts = configured_attempts
    for attempt in range(1, max_attempts + 1):
        # ... try scrolling up ...
    # 超过次数后直接放弃，即使没到顶部
```

### 3.2 客户列表提取逻辑 (`wecom_service.py`)

```python
async def extract_private_chat_users(self, max_scrolls=None, ...):
    # 默认 max_scrolls 仅为 20 次
    max_scrolls = max_scrolls or self.config.scroll.max_scrolls

    # 先尝试回到顶部 (可能失败，停在半路)
    await self.adb.scroll_to_top()

    # 向下滚动有限次数
    for scroll_num in range(max_scrolls + 1):
        # ... extract users ...
    # 循环结束，返回当前已获取的局部列表
```

## 4. 根本原因分析 (Root Cause Analysis)

这是代码中的**逻辑设计缺陷**，未考虑到长列表场景：

1.  **硬编码的循环限制 (Hardcoded Limits)**：

# 全量同步第一阶段 Bug 修复 PRD

## 1. 背景 (Context)

全量同步（Full Sync）是系统核心功能，负责将 WeCom 客户端的聊天记录同步到本地数据库。
第一阶段（Phase 1）主要负责**环境初始化**和**获取待同步客户列表**，为后续的逐个客户消息同步（Phase 2）做准备。

### Phase 1 核心流程

1.  **初始化 (`_initialize`)**:
    - 确保 WeCom 客户端已打开 (`_ensure_wecom_open`)。
    - 获取当前登录的客服（Kefu）信息 (`get_kefu_info`)。
    - 在数据库中注册或更新 Device 和 Kefu 记录。
2.  **获取客户列表 (`_get_customers`)**:
    - 导航至私聊列表界面 (`switch_to_private_chats`)。
    - 滚动并提取所有客户列表 (`extract_private_chat_users`)。
    - (可选) 根据未读消息状态对列表进行排序或过滤。

## 2. 问题描述 (Problem Description)

**现象**：当微信好友列表过长（例如数千人）时，程序无法完成全量同步，甚至无法获取完整的好友列表。
**具体表现**：

- **无法回到列表顶部**：程序尝试“滚动到顶部”操作，但对于长列表，默认的重试次数不足以回到顶部。
- **列表获取不全**：提取用户列表时，受限于默认的 `max_scrolls` 限制，只能获取列表的一部分（通常是顶部或中间的一小段）。
- **逻辑失效**：由于未能获取所有用户，导致只有部分用户被纳入同步计划，遗漏大量用户。用户感知为“程序未能运行”或“数据缺失”。

## 3. 当前实现分析 (Current Implementation)

该逻辑主要位于 `src/wecom_automation/services/wecom_service.py` 和 `adb_service.py` 中。

### 3.1 滚动到顶部逻辑 (`adb_service.py`)

```python
async def scroll_to_top(self, scroll_count: int = 3) -> None:
    # 默认尝试次数非常有限 (Config默认 6 次)
    max_attempts = configured_attempts
    for attempt in range(1, max_attempts + 1):
        # ... try scrolling up ...
    # 超过次数后直接放弃，即使没到顶部
```

### 3.2 客户列表提取逻辑 (`wecom_service.py`)

```python
async def extract_private_chat_users(self, max_scrolls=None, ...):
    # 默认 max_scrolls 仅为 20 次
    max_scrolls = max_scrolls or self.config.scroll.max_scrolls

    # 先尝试回到顶部 (可能失败，停在半路)
    await self.adb.scroll_to_top()

    # 向下滚动有限次数
    for scroll_num in range(max_scrolls + 1):
        # ... extract users ...
    # 循环结束，返回当前已获取的局部列表
```

## 4. 根本原因分析 (Root Cause Analysis)

这是代码中的**逻辑设计缺陷**，未考虑到长列表场景：

1.  **硬编码的循环限制 (Hardcoded Limits)**：
    - `scroll_to_top` 的尝试次数（默认6次）对于长列表（如5000人）完全不够，导致无法复位到起始点。
    - `extract_private_chat_users` 的滚动次数（默认20次）只能覆盖約100-150人，对于长列表无法遍历完全。
2.  **错误的状态假设**：程序假设在有限次操作后一定能到达“顶部”或“底部”，而没有根据实际UI状态（是否真的到底）来动态决定是否继续。
3.  **缺乏分页/流式处理**：试图在一个函数调用中通过有限步数获取“所有”用户，这在长列表场景下在逻辑上就是不可行的（或非常低效）。
4.  **Scroll to Top 默认值过低**: `adb_service.py` 中的 `scroll_to_top` 方法默认参数 `scroll_count=3` 覆盖了 Config 中的配置，导致回顶操作在长列表底部必定失败。

## 5. 修复方案 (Proposed Solution)

采用 **"两阶段全量提取 (Two-Phase Full Extraction)"** 策略。

### 5.1 核心逻辑

放弃流式处理，回归到“先获取全量列表，再逐个同步”的模式，但改进提取逻辑以支持无限长列表。

### 5.2 阶段一：全量提取 (Phase 1: Robust Extraction)

1.  **回顶 (Ensure Top)**:
    - 执行滚动到顶部操作。
    - **判定标准**：连续 **3次** 尝试滚动后，UI 树 Hash 均无变化，确认处于列表最顶端。
2.  **扫描与去重 (Scan & Deduplicate)**:
    - 使用 `Dict[str, UserDetail]` (类似 Set) 存储用户，以用户名为唯一键进行去重。
    - **循环逻辑**:
      - 提取当前页用户 -> 存入 Dict。
      - 执行 `scroll_down()`。
    - **终止条件**: 连续 **3次** 滚动操作后，都没有发现任何**新用户** (New Users == 0)，则判定已到达底部，结束扫描。

### 5.3 阶段二：顺序同步 (Phase 2: Sequential Sync)

1.  **重置位置**:
    - 提取完成后，处于列表底部。
    - 调用 `adb.scroll_to_top(scroll_count=1000)` (显式传入大数值)。
    - **原因**: 覆盖默认的 3 次限制，确保即使在 500 页深的位置也能滚回顶部。
2.  **顺序执行**:
    - 遍历提取到的完整用户列表。
    - 从第一个用户开始，依次点击进入详情页进行同步。

### 5.4 优势

- **逻辑简单清晰**: 避免了流式处理中复杂的上下文切换和断点定位问题。
- **完备性**: 通过“连续3次无新用户”的判定，能最准确地保证获取了完整列表。
- **性能**: 仅在开始时进行一次全量扫描，后续同步过程无需频繁的 OCR 扫描整个列表。

## 6. 验证计划 (Verification Plan)

### 6.1 单元/组件测试

- Mock 一个包含 200 个用户的长列表。
- 验证 `extract_all` 能够完整提取 200 个用户，不会在 20 页限制处停止。
- 验证在列表底部时，能正确触发“3次无新用户”的终止条件。

### 6.2 真实场景验证

- 运行 `initial_sync_v2.py`。
- 观察日志：
  1.  Initialization 后进入 "Extracting" 阶段。
  2.  日志显示 "Found X users" 持续增长。
  3.  到达底部后，显示 "Reached bottom (3 times no new users)"。
  4.  界面快速回滚到顶部。
  5.  开始点击第一个用户进行同步。
