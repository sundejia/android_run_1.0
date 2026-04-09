# 图片保存逻辑现状分析

**日期**: 2026-01-18
**状态**: 分析完成

## 1. 结论：存在两套机制，主要机制存在覆盖盲区

经过对 codebase 的深度分析，确认目前代码库中存在两套独立的图片保存逻辑。然而，在实际运行的核心流程 `CustomerSyncer` 中，只有一套逻辑在生效，且导致了**新消息图片无法保存**的问题。

| 机制         | 名称                          | 核心位置                                                                | 状态                | 适用场景                                         |
| :----------- | :---------------------------- | :---------------------------------------------------------------------- | :------------------ | :----------------------------------------------- |
| **System A** | **Inline Capture (内联抓取)** | `WeComService.extract_conversation_messages` -> `_capture_image_inline` | **活跃 (的主力)**   | 历史消息提取、滚动加载                           |
| **System B** | **Handler 机制**              | `ImageMessageHandler` -> `ImageStorageHelper`                           | **被旁路 / 仅辅助** | 本应处理所有图片，但实际仅被作为文件复制工具使用 |

## 2. System A: Inline Capture (当前生效机制)

这是目前 `CustomerSyncer` 依赖的主要机制。

- **工作原理**:
  - 在调用 `wecom.extract_conversation_messages(download_images=True)` 时，脚本会执行滚动操作。
  - 每当滚动并解析出一屏消息，脚本会立即截取全屏 (`_capture_image_inline`)。
  - 脚本根据解析出的 Image Bounds 从全屏截图中裁剪出图片，保存到临时路径，并赋值给 `msg.image.local_path`。
- **代码路径**:
  - `src/wecom_automation/services/wecom_service.py` (Line 880-900)
- **局限性**:
  - **仅在滚动时有效**：这只发生在"历史消息同步"阶段。
  - **新消息盲区**：在"新消息监控"阶段 (`_wait_for_new_customer_messages`)，由于只是解析 UI Tree 而没有触发滚动和截图流程，新到达的图片消息没有机会被 Inline Capture 捕获。

## 3. System B: Handler 机制 (被闲置的潜力)

这是一套更符合设计模式的机制，但在主流程中被忽视了。

- **工作原理**:
  - 使用 `ImageMessageHandler` 来处理图片消息。
  - 它具备根据消息的 Bounds 随时进行截图保存的能力 (`save_image_from_bounds`)。
- **代码路径**:
  - `src/wecom_automation/services/message/handlers/image.py`
  - `src/wecom_automation/services/message/image_storage.py`
- **被旁路的原因**:
  - 在 `CustomerSyncer._process_and_store_message` 中，代码**手动实现**了图片保存逻辑，而不是委托给 `MessageProcessor` 或 `ImageMessageHandler`。
  - 手动逻辑如下：
    ```python
    # src/wecom_automation/services/sync_service.py
    if msg.image.local_path:
         # 有 Inline Capture 的图，复制过去
         _save_message_image(...)
    else:
         # 没有图 (即新消息或滚动时漏掉的)，直接放弃！
         logger.warning("Image ... was not captured inline")
    ```
  - 它没有尝试调用 `wecom.screenshot_element` 来补救。

## 4. 导致的问题

1.  **新消息图片丢失**：当系统处于交互等待模式时，用户发送的新图片能被检测到并存入数据库（作为记录），但图片文件本身不会被保存，因为新消息没有 `local_path` 且 Handler 逻辑未被触发。
2.  **代码冗余**：保存图片的逻辑在 `sync_service.py` 和 `image.py` 中重复存在。

## 5. 建议修复方案

为了解决新消息图片保存问题并统一代码：

1.  **重构 `CustomerSyncer._process_and_store_message`**:
    - 当 `msg.image.local_path` 不存在时（即新消息场景），应主动调用 `wecom.screenshot_element` 或复用 `ImageStorageHelper.save_image_from_bounds` 来现场抓取图片。
    - 或者，完全委托给 `self.message_processor` 处理消息，而不是手动写 `if/else`。

2.  **短期修复 (Quick Fix)**:
    - 在 `_process_and_store_message` 的 `else` 分支中，添加对 `ImageStorageHelper` 的调用，利用 `msg.image.bounds` 进行补救截图。
