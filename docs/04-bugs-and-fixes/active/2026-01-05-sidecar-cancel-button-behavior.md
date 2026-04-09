# Sidecar Cancel 按钮导致同步中断的问题分析与修复计划

**日期**: 2026-01-05
**状态**: ✅ 已修复
**组件**: Python Scripts (`initial_sync.py`), Frontend (`SidecarView.vue`)

## 问题描述

在 Sidecar 界面中，点击队列旁的 "X" (Cancel) 按钮是为了跳过当前正在同步的用户，中断当前进度并返回用户列表，以便继续同步下一个用户。

然而，之前 behavior 是：点击 "X" 按钮会导致整个同步程序完全终止（退出进程），而不是仅跳过当前用户。

此外，用户希望将 "Sync" 进度条区域的 "Stop" 按钮也改为 "Skip" 功能，以便在全量同步过程中也能方便地跳过当前用户。

## 错误原因分析

经过代码审查，问题出在 `initial_sync.py` 中的 `sidecar_send_message` 函数处理 "cancelled" 状态的方式上。

1.  **API 行为**: 前端点击 Cancel 按钮调用 `/queue/cancel` 接口，后端将消息状态设为 `CANCELLED`。
2.  **客户端行为**: `initial_sync.py` 中的 `sidecar_send_message` 等待消息发送结果。
3.  **异常抛出**: 当检测到 results 为 "cancelled" 时，代码直接抛出了 `KeyboardInterrupt`。
    ```python
    raise KeyboardInterrupt("Sync cancelled via sidecar")
    ```
4.  **程序终止**: `KeyboardInterrupt` 异常冒泡到最外层的 `run` 函数，导致程序直接退出。

## 修复实施

### 1. 后端修复 (Python)

我们引入了一个自定义异常 `SkipUserException` 来替代 `KeyboardInterrupt`，用于表示“跳过当前用户”的意图。

**修改文件**: `initial_sync.py`

- **定义异常**:
  ```python
  class SkipUserException(Exception):
      """Exception raised when user wants to skip the current customer."""
      pass
  ```
- **抛出异常**: 在 `sidecar_send_message` 中，当状态为 "cancelled" 时抛出 `SkipUserException`。
- **捕获异常**: 在 `wrapped_sync_customer` 中捕获此异常，执行导航恢复（返回用户列表），并让主循环继续。

### 2. 前端修复 (Vue)

我们将 Sidecar 界面中 Sync Progress Bar 上的 "Stop" 按钮替换为 "Skip" 按钮，并使其触发相同的 Cancel 逻辑。

**修改文件**: `wecom-desktop/src/views/SidecarView.vue`

- **替换按钮**:
  - 旧: `⏹️ Stop` (调用 `stopDeviceSync`)
  - 新: `⏭️ Skip` (调用 `skipDeviceSync`)
- **新增逻辑**: 实现 `skipDeviceSync` 函数，调用 `cancelSyncQueue` API。这会通知后端当前消息被取消，从而触发上述 Python 端的 `SkipUserException`。

## 测试验证

通过独立的模拟脚本 `tests/manual_test_skip_logic.py` 验证了后端异常流控制逻辑。
结果显示：

1.  抛出 `SkipUserException` 能正确中断当前用户的同步。
2.  异常被捕获后，能够模拟恢复操作。
3.  主循环能够继续处理列表中的下一个用户，而不是崩溃退出。

## 结论

问题已解决。Sidecar 界面现在提供了正确的“跳过当前用户”功能，无论是通过 Queue 的 Cancel 按钮还是 Sync Progress 的 Skip 按钮，都不会再导致同步服务意外终止。
