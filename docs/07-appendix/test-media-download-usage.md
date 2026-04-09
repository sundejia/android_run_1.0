# 图片和视频下载测试脚本使用说明

## 概述

`test_media_download.py` 是一个测试脚本，用于从当前 WeCom 聊天窗口中提取和下载图片、视频消息。

## 功能

1. **截取当前屏幕** - 保存完整截图
2. **获取 UI 树** - 解析界面元素
3. **识别媒体消息** - 自动识别图片和视频消息
4. **裁剪并保存** - 从截图中裁剪出媒体区域并保存
5. **导出元数据** - 保存媒体信息到 JSON 文件

## 前置条件

1. 设备已通过 ADB 连接
2. WeCom 应用已打开
3. 当前处于包含图片/视频的聊天窗口

## 使用方法

### 方法 1: 使用 uv（推荐）

```bash
cd /path/to/android_run_test-main
uv run test_media_download.py
```

### 方法 2: 使用 python

```bash
cd /path/to/android_run_test-main
python test_media_download.py
```

## 运行流程

1. 启动脚本后，会显示前置条件检查
2. 确认设备已连接、WeCom 已打开、当前在聊天窗口
3. 按 `Enter` 键开始测试
4. 脚本自动执行：
   - 截取屏幕
   - 获取 UI 树
   - 查找媒体消息
   - 裁剪并保存媒体文件
   - 保存媒体信息到 JSON

## 输出结果

所有输出文件保存在 `./test_media_output/` 目录：

```
test_media_output/
├── screenshot_20250118_143025.png       # 完整截图
├── image_1_20250118_143026.png          # 裁剪的图片 #1
├── image_2_20250118_143027.png          # 裁剪的图片 #2
├── video_1_20250118_143028.png          # 裁剪的视频缩略图 #1
├── video_2_20250118_143029.png          # 裁剪的视频缩略图 #2
└── media_info_20250118_143030.json      # 媒体元数据
```

## 媒体信息 JSON 格式

```json
[
  {
    "type": "video",
    "bounds": "[120,350][800,650]",
    "x1": 120,
    "y1": 350,
    "x2": 800,
    "y2": 650,
    "width": 680,
    "height": 300,
    "text": "",
    "content_description": "Video message, duration 00:15",
    "resource_id": "com.tencent.wework:id/video_preview"
  },
  {
    "type": "image",
    "bounds": "[120,700][800,1000]",
    "x1": 120,
    "y1": 700,
    "x2": 800,
    "y2": 1000,
    "width": 680,
    "height": 300,
    "text": "",
    "content_description": "Image",
    "resource_id": "com.tencent.wework:id/image_preview"
  }
]
```

## 日志输出示例

```
============================================================
媒体下载测试开始
============================================================
正在截取屏幕...
屏幕截图成功: (1080, 2400)
完整截图已保存: test_media_output\screenshot_20250118_143025.png
正在获取 UI 树...
UI 树获取成功
正在查找媒体消息...
发现 VIDEO: bounds=[120,350][800,650], size=680x300
发现 IMAGE: bounds=[120,700][800,1000], size=680x300
总共找到 2 个媒体消息
媒体信息已保存到: test_media_output\media_info_20250118_143030.json
============================================================
开始裁剪和保存媒体文件...
============================================================
正在裁剪 video #1: bounds=[120,350][800,650]
✓ VIDEO 已保存: test_media_output\video_1_20250118_143031.png
  尺寸: (700, 310) (原始: 680x300, 加边距后: 700x310)
正在裁剪 image #2: bounds=[120,700][800,1000]
✓ IMAGE 已保存: test_media_output\image_1_20250118_143032.png
  尺寸: (700, 310) (原始: 680x300, 加边距后: 700x310)
============================================================
测试完成! 成功保存 2/2 个媒体文件
输出目录: D:\111\android_run_test-main\test_media_output
============================================================
```

## 故障排查

### 问题：未找到任何媒体消息

**原因**：

- 当前不在聊天窗口
- 聊天窗口中没有媒体消息
- UI 树解析失败

**解决方法**：

1. 确认 WeCom 已打开
2. 确认当前在包含图片/视频的聊天窗口
3. 滚动到包含媒体消息的位置
4. 重新运行脚本

### 问题：截图失败

**原因**：

- 设备未连接
- ADB 权限问题
- droidrun 服务未运行

**解决方法**：

```bash
# 检查设备连接
adb devices

# 重启 ADB
adb kill-server
adb start-server

# 检查 droidrun
adb shell ps | findstr droidrun
```

### 问题：裁剪失败

**原因**：

- PIL 未安装
- Bounds 超出图片范围

**解决方法**：

```bash
# 安装 PIL
uv pip install Pillow

# 或
pip install Pillow
```

## 技术细节

### 媒体识别逻辑

脚本通过以下方式识别媒体消息：

1. **图片识别**：
   - `text` 或 `content_description` 包含 "image"/"图片"
   - `resource_id` 包含 "img"
   - 特定的 WeCom 资源 ID

2. **视频识别**：
   - `text` 或 `content_description` 包含 "video"/"视频"
   - `class` 为 `android.widget.ImageView` 且内容描述包含播放关键词
   - 特定的 WeCom 资源 ID

### Bounds 裁剪

- 自动添加 10 像素的边距（padding）
- 验证 bounds 是否在图片范围内
- 过滤掉太小的元素（< 50x50 像素，可能是图标）

### 输出格式

- **完整截图**：PNG 格式，原始屏幕分辨率
- **裁剪媒体**：PNG 格式，带边距的媒体区域
- **元数据**：JSON 格式，包含所有媒体信息

## 相关文件

- **测试脚本**：`test_media_download.py`
- **输出目录**：`./test_media_output/`
- **相关代码**：
  - `src/wecom_automation/services/adb_service.py` - ADB 服务
  - `src/wecom_automation/services/ui_parser.py` - UI 解析
  - `src/wecom_automation/services/message/handlers/image.py` - 图片处理
  - `src/wecom_automation/services/message/handlers/video.py` - 视频处理
