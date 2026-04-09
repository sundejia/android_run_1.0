# 图片发送功能使用指南

## 快速开始

图片发送功能已经集成到主流程中，你可以通过多种方式调用。

### 1. 通过 REST API 调用（推荐）

启动后端服务：

```bash
cd wecom-desktop/backend
uvicorn main:app --reload --port 8765
```

#### 发送图片

```bash
curl -X POST http://localhost:8765/api/image-sender/send \
  -H "Content-Type: application/json" \
  -d '{
    "device_serial": "YOUR_DEVICE_SERIAL",
    "favorite_index": 0
  }'
```

#### 列出所有收藏项

```bash
curl -X POST http://localhost:8765/api/image-sender/list-favorites \
  -H "Content-Type: application/json" \
  -d '{
    "device_serial": "YOUR_DEVICE_SERIAL"
  }'
```

### 2. 在 Python 代码中直接调用

```python
from wecom_automation.core.config import Config
from wecom_automation.services.adb_service import ADBService
from wecom_automation.services.wecom_service import WeComService
from wecom_automation.services.message.image_sender import ImageSender

# 创建配置
config = Config.from_env().with_overrides(device_serial="YOUR_DEVICE_SERIAL")

# 创建服务
adb = ADBService(config)
wecom = WeComService(config, adb)
sender = ImageSender(wecom)

# 发送图片
success = await sender.send_via_favorites(favorite_index=0)

if success:
    print("✅ 图片发送成功")
else:
    print("❌ 图片发送失败")
```

### 3. 在 Follow-up / Realtime Reply 中集成

在 `realtime_reply_process.py` 或 `followup` 相关代码中：

```python
# 导入 ImageSender
from wecom_automation.services.message.image_sender import ImageSender

# 在已有的 wecom_service 实例基础上创建 sender
sender = ImageSender(wecom_service)

# 根据业务逻辑决定是否发送图片
if should_send_image:  # 你的判断逻辑
    success = await sender.send_via_favorites(favorite_index=0)
    if success:
        logger.info("✅ Image sent as part of reply")
    else:
        logger.warning("❌ Failed to send image")
```

## API 文档

访问交互式 API 文档：

```
http://localhost:8765/docs
```

在文档中找到 **image-sender** 标签，查看完整的 API 说明和在线测试功能。

## 前置条件

发送图片前，请确保：

1. ✅ **设备已连接** - 通过 ADB 连接
2. ✅ **WeCom 已打开** - 应用正在运行
3. ✅ **在对话界面** - 进入某个联系人的聊天界面
4. ✅ **已有收藏** - Favorites 中至少有一个图片
5. ✅ **索引有效** - favorite_index 不超过收藏项数量

## 使用场景示例

### 场景 1: 自动发送产品图片

当客户询问产品信息时，自动发送产品图片：

```python
# 在 realtime_reply_process.py 中
if "产品" in customer_message or "图片" in customer_message:
    # 发送收藏中的第一张产品图
    sender = ImageSender(wecom_service)
    await sender.send_via_favorites(favorite_index=0)
```

### 场景 2: 根据关键词发送不同图片

```python
keyword_to_image = {
    "价格表": 0,
    "使用说明": 1,
    "联系方式": 2,
}

for keyword, index in keyword_to_image.items():
    if keyword in customer_message:
        sender = ImageSender(wecom_service)
        await sender.send_via_favorites(favorite_index=index)
        break
```

### 场景 3: 批量发送图片

```python
async def send_product_series(wecom_service, start_index=0, count=3):
    """发送一系列产品图片"""
    sender = ImageSender(wecom_service)

    for i in range(count):
        success = await sender.send_via_favorites(favorite_index=start_index + i)
        if success:
            print(f"✅ Sent image {start_index + i}")
            await asyncio.sleep(2)  # 等待 2 秒避免过快发送
        else:
            print(f"❌ Failed to send image {start_index + i}")
            break
```

## 调试技巧

### 查看可用的收藏项

```python
sender = ImageSender(wecom_service)
favorites = await sender.list_favorites()

for i, item in enumerate(favorites):
    print(f"[{i}] Index: {item['index']}, ID: {item['resource_id']}")
```

### 启用详细日志

```python
from wecom_automation.core.logging import get_logger

logger = get_logger("wecom_automation.image_sender")
# 日志会输出到 logs/{hostname}-global.log
```

### 常见错误处理

```python
from wecom_automation.services.message.image_sender import (
    ImageSender,
    ElementNotFoundError
)

try:
    sender = ImageSender(wecom_service)
    success = await sender.send_via_favorites(favorite_index=0)
except ElementNotFoundError as e:
    logger.error(f"UI 元素未找到: {e}")
    # 可以尝试重试或采取其他措施
except Exception as e:
    logger.error(f"发送失败: {e}")
```

## 性能建议

1. **避免频繁调用** - 每次发送需要 7-10 秒
2. **批量发送时添加延迟** - 连续发送时等待 2-3 秒
3. **使用异步调用** - 不要阻塞主线程
4. **缓存收藏项列表** - 避免重复调用 `list_favorites()`

## 下一步

- 查看完整文档：`docs/03-impl-and-arch/key-modules/image-sender.md`
- 浏览 API 文档：`http://localhost:8765/docs`
- 查看源代码：`src/wecom_automation/services/message/image_sender.py`

## 问题反馈

如有问题，请检查：

1. 日志文件：`logs/{hostname}-global.log`
2. API 响应：查看错误消息
3. 设备状态：确保设备连接正常且在对话界面

---

**提示**：这是一个模块化的功能，你可以根据具体需求灵活调用，无需修改核心代码。
