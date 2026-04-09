# Followup 阶段二（补刀）问题分析

## 问题概述

当前 followup 系统的阶段二（补刀操作）无法正常工作。

## 核心问题

### 问题一：红点检测与补刀逻辑冲突

当前 `scanner.py` 的扫描逻辑是**基于红点检测**的：

```python
# scanner.py 第125-144行
initial_unread = await self._detect_first_page_unread(wecom, serial)
# ... 过滤后只处理红点用户
```

**问题**：补刀的目标用户**不会有红点**！

- **红点** = 用户发送了新消息（未读）
- **补刀目标** = 客服发送了消息，用户没有回复

这两者是完全相反的场景：

- 如果用户有红点 → 用户已回复 → 不需要补刀
- 如果用户没有红点 → 用户未回复 → 需要补刀

### 问题二：Phase 2 的数据流错误

当前流程：

```
Phase 2 (scheduler.py 第216-241行):
1. 从数据库查询 candidates (客服发送最后一条消息的客户)
2. 获取 target_names 列表
3. 调用 scanner.scan_all_devices(target_users=target_names)
   ↓
scanner.py:
4. 检测红点用户
5. 过滤：只保留 target_users 中的红点用户
6. 处理过滤后的用户
```

**问题**：

- Step 4-5 会把所有 target_users 过滤掉，因为需要补刀的用户不会有红点
- 结果：Phase 2 永远找不到用户来补刀

## 正确的补刀流程

### 理想流程

```
Phase 2 补刀流程:
1. 从数据库查询候选人 (客服是最后发消息的人)
2. 检查冷却时间 (上次消息过了多久)
3. 直接导航到每个候选用户的聊天窗口（不需要红点）
4. 提取当前对话消息
5. 再次确认：客服是否仍然是最后发消息的人？
   - 如果是 → 发送补刀消息
   - 如果不是 → 用户已回复，跳过并更新数据库
6. 返回首页，处理下一个候选人
```

### 与 Phase 1 的区别

| 对比项   | Phase 1 (回复检测) | Phase 2 (补刀)           |
| -------- | ------------------ | ------------------------ |
| 目标     | 有红点的用户       | 没有红点但需要跟进的用户 |
| 触发条件 | 用户发送了新消息   | 客服发送消息后用户没回复 |
| 用户状态 | 有未读消息         | 无未读消息               |
| 查找方式 | 扫描红点           | 从数据库查询+直接导航    |

## 修复方案

### 方案一：为 Phase 2 创建单独的扫描逻辑

修改 `scanner.py`，添加新的方法专门处理补刀：

```python
async def scan_for_followup(
    self,
    device_serial: str,
    target_users: List[str],  # 从数据库查询到的候选人
) -> ScanResult:
    """
    扫描需要补刀的用户（不依赖红点检测）
    """
    for user_name in target_users:
        # 直接点击用户进入聊天
        clicked = await wecom.click_user_in_list(user_name)
        if not clicked:
            # 用户不在列表中，可能需要搜索
            continue

        # 提取消息，判断是否需要补刀
        messages = await self._extract_messages(wecom)
        last_msg = messages[-1] if messages else None

        if last_msg and last_msg.is_self:
            # 客服是最后发消息的人 → 发送补刀
            await self._send_followup(wecom, user_name, messages)
        else:
            # 用户已回复 → 标记为已回复
            self._repository.mark_responded(customer_id)

        await wecom.go_back()
```

### 方案二：修改现有扫描逻辑

在 `scan_device` 中区分两种模式：

```python
async def scan_device(
    self,
    device_serial: str,
    mode: str = "red_dot",  # "red_dot" 或 "followup"
    target_users: Optional[List[str]] = None,
) -> ScanResult:
    if mode == "red_dot":
        # Phase 1: 红点检测模式
        users = await self._detect_first_page_unread(wecom, serial)
    else:
        # Phase 2: 补刀模式，直接处理目标用户
        users = [UnreadUser(name=n, unread_count=0) for n in target_users]
```

### 方案三：搜索功能

如果目标用户不在首页列表中，需要实现搜索功能：

```python
async def _find_user_by_search(self, wecom, user_name: str) -> bool:
    """通过搜索功能找到用户"""
    # 1. 点击搜索按钮
    # 2. 输入用户名
    # 3. 点击搜索结果
    pass
```

## 当前代码位置

- **scheduler.py 第207-247行**: Phase 2 的调度逻辑
- **scanner.py 第61-266行**: `scan_device` 扫描逻辑（当前基于红点）
- **scanner.py 第589-628行**: `_detect_first_page_unread` 红点检测
- **repository.py 第225-308行**: `find_candidates` 数据库查询

## 建议修复优先级

1. **高优先级**：为 Phase 2 创建单独的扫描方法 `scan_for_followup()`
2. **中优先级**：添加搜索功能，支持查找不在首页的用户
3. **低优先级**：优化数据库查询，确保消息时间戳正确

## 附录：日志分析

如果看到以下日志，说明 Phase 2 没有找到任何用户：

```
Phase 2: Finding customers who need follow-up...
Found X total candidates from database
Found X candidate(s) ready for follow-up: [...]
...
[device] Step 6: Detecting red dot users...
[device] ✅ No red dot users found, scan complete
```

这证实了问题：数据库找到了候选人，但红点检测没有找到这些用户（因为他们没有红点）。

---

## ✅ 已实施的修复

### 新增方法

在 `scanner.py` 中添加了以下方法：

1. **`scan_device_for_followup(device_serial, candidates)`**
   - Phase 2 专用扫描方法
   - 直接处理候选人列表，不依赖红点检测
   - 导航到每个用户聊天，检查最后消息，发送补刀

2. **`_process_followup_candidate(wecom, serial, candidate)`**
   - 处理单个候选人
   - 检查客服是否仍是最后发消息的人
   - 如果是 → 发送补刀
   - 如果不是 → 标记已回复

3. **`_send_followup_message(...)`**
   - 发送补刀消息（AI 或模板）
   - 记录到数据库

4. **`_scroll_and_find_user(...)`**
   - 如果用户不在首页，滚动查找

5. **`scan_all_devices_for_followup(candidates)`**
   - 多设备并行扫描入口

### scheduler.py 更新

Phase 2 现在调用 `scan_all_devices_for_followup(candidates)` 而不是 `scan_all_devices(target_users=...)`

### 新流程

```
Phase 2 (修复后):
1. 从数据库查询 candidates (客服发送最后一条消息的客户)
2. 过滤：is_ready=True 且不在 exclude_users 中
3. 调用 scanner.scan_all_devices_for_followup(candidates)
   ↓
scanner.py:
4. 直接遍历 candidates 列表
5. 点击用户进入聊天（如需要可滚动查找）
6. 检查最后消息是否仍是客服发的
7. 是 → 发送补刀，记录到DB
8. 否 → 标记为已回复
```

### 测试验证

修复后应该看到以下日志：

```
Phase 2: Finding customers who need follow-up (补刀)...
Found X candidate(s) ready for follow-up:
   - 用户A: attempt #1, elapsed 300s >= required 180s
   - 用户B: attempt #2, elapsed 600s >= required 360s
[device] PHASE 2: Starting followup scan (no red dot)
[device] [1/X] 📤 Processing: 用户A
[device]   Extracting messages...
[device]   Is from kefu: True
[device]   ✅ Follow-up #1/3 sent and recorded!
```
