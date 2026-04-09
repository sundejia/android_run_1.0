# 语音消息提取失败问题分析

**状态**: ✅ 已修复 (2026-01-20)

## 问题描述

`test_voice_download.py` 测试脚本无法提取到任何语音消息，显示 `Voice messages: 0`。

## 根本原因

WeCom (企业微信) 更新后，UI 元素的 `resourceId` 发生了变化。`ui_parser.py` 中硬编码的 resourceId 不再匹配当前版本的 WeCom。

## 具体变化

| 元素类型 | 旧 resourceId | 新 resourceId |
| -------- | ------------- | ------------- |
| 语音时长 | `ies`         | `ie5`         |
| 语音转写 | `p05`         | `oyl`         |
| 消息行   | `cmn`         | `cmj`         |
| 时间戳   | `ief`         | `ids`         |
| 文字内容 | `idk`         | `icx`         |

## 影响范围

- `src/wecom_automation/services/ui_parser.py` - 消息提取逻辑
  - 第 1210-1214 行：语音时长检测 (`ies` -> `ie5`)
  - 第 1216-1219 行：语音转写检测 (`p05` -> `oyl`)
  - 第 1110-1113 行：语音时长检测 (重复)
  - 消息列表和消息行的 ID 提示配置

## 修复方案

### 方案 1：添加新 ID 到现有检测逻辑（推荐）

在检测语音消息时，同时检查新旧两种 resourceId，以保持向后兼容：

```python
# Voice duration (ies or ie5) - e.g., "2\""
if ("ies" in rid or "ie5" in rid) and text:
    voice_duration = text
    message_type = "voice"
    continue

# Voice transcription (p05 or oyl)
if ("p05" in rid or "oyl" in rid) and text:
    voice_transcription = text
    continue
```

### 方案 2：更新配置文件

在 `UIConfig` 中添加语音相关的 resourceId 配置，便于后续维护。

## 测试验证

修复后，运行以下命令验证：

```bash
uv run test_voice_download.py --debug
```

预期输出应显示 `Voice messages: N` (N > 0)。

## 验证结果

修复后测试成功：

- 测试文件：`voice_4_20260120_202144.wav (111404 bytes)`
- 转写识别：`Transcription: 哈喽哈喽。`
- 退出码：0 (成功)

## 相关文件

- `test_voice_download.py` - 测试脚本
- `src/wecom_automation/services/ui_parser.py` - UI 解析器
- `debug_voice_ui_tree.json` - UI 树调试输出
