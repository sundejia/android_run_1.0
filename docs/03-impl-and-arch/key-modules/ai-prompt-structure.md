# AI 回复 Prompt 结构详解

本文档详细说明系统在调用 AI 服务生成回复时，如何构建和传递完整的 Prompt。

## 概述

AI 回复功能在以下场景中使用：

1. **实时回复** - 检测到客户新消息时自动生成回复
2. **补刀功能** - 客户长时间未回复时的跟进消息

两种场景共用相同的 `_generate_reply()` 方法生成回复。

## XML 结构化 Prompt（生产级标准）

从 2026-02 开始，系统采用 **XML 结构化 Prompt** 格式，这是生产级（Production-Ready）标准：

### 为什么使用 XML 结构？

1. **明确区分**：清晰划分任务、上下文、需求、约束和思维过程
2. **防止幻觉**：通过 `<constraints>` 明确禁止的行为
3. **可追溯**：结构化便于日志记录和调试
4. **一致性**：统一的格式降低 AI 理解偏差

## 正常回复场景的 XML Prompt

```xml
<task>
为客户 {customer_name} 的最新消息生成一条合适的回复。
</task>

<context>
<scenario>实时回复场景</scenario>
<customer_name>{customer_name}</customer_name>
<situation>客户发送了新消息，需要及时、恰当地回复。</situation>
<business_background>这是一个直播经纪公司的客服场景，目标是招募主播，同时需要专业地处理各种客户咨询。</business_background>
</context>

<conversation_history count="{message_count}">
CUSTOMER: 我是柠檬
AGENT: 感谢您信任并选择WELIKE...
CUSTOMER: 柠檬
...
</conversation_history>

<latest_customer_message>
{last_customer_msg}
</latest_customer_message>

<style_guidelines>
{system_prompt or "使用礼貌、友好的语气。"}
</style_guidelines>

<requirements>
<functional>
1. 针对客户的最新消息进行回复
2. 回复要解决客户的问题或回应客户的诉求
3. 保持对话的连贯性和上下文关联
</functional>
<content_rules>
1. 仔细阅读完整对话历史，理解客户需求和背景
2. 回复要自然、礼貌，与之前的对话风格保持一致
3. 如果是延续之前的话题，要有上下文连贯性
4. 简洁明了，不要重复之前已经说过的内容
</content_rules>
</requirements>

<constraints>
<length_limit>回复控制在 {max_length} 字以内</length_limit>
<forbidden_patterns>
1. 禁止忽视客户的问题而转移话题
2. 禁止使用模板化的敷衍回复
3. 禁止重复之前已经说过的内容
</forbidden_patterns>
<special_commands>
如果客户要求转人工、找真人客服、或表示要人工服务，直接返回: command back to user operation
</special_commands>
</constraints>

<thinking>
在生成回复之前，请按以下步骤思考：
1. 理解客户最新消息的真实意图和诉求
2. 回顾对话历史，确保回复具有上下文连贯性
3. 判断是否需要转人工处理
4. 根据 style_guidelines 调整回复的语气和风格
5. 确保回复直接解决客户的问题
</thinking>

<output_format>
直接输出回复消息文本，不要包含任何解释、标签或格式标记。
</output_format>
```

## 补刀跟进场景的 XML Prompt

```xml
<task>
为客户 {customer_name} 生成一条主动跟进消息。该客户已长时间未回复，需要友好地重新激活对话。
</task>

<context>
<scenario>补刀跟进场景</scenario>
<customer_name>{customer_name}</customer_name>
<situation>客户已经长时间未回复消息，需要主动发起跟进以重新激活对话。</situation>
<business_background>这是一个直播经纪公司的客服场景，目标是招募主播，需要在保持专业的同时展现诚意。</business_background>
</context>

<conversation_history count="{message_count}">
CUSTOMER: 我是柠檬
AGENT: 感谢您信任并选择WELIKE...
...
</conversation_history>

<custom_instructions>
{followup_prompt}
</custom_instructions>

<style_guidelines>
{system_prompt or "使用礼貌、友好的语气。"}
</style_guidelines>

<requirements>
<functional>
1. 生成一条自然的跟进消息，重新激活与客户的对话
2. 消息应该友好、不带压迫感
3. 可以询问客户近况或提供新的价值信息
</functional>
<content_rules>
1. 不要重复之前已经说过的内容
2. 不要过于急切或有销售压力
3. 保持与之前对话风格的一致性
4. 消息要自然，像是正常的后续关心
</content_rules>
</requirements>

<constraints>
<length_limit>消息控制在 {max_length} 字以内</length_limit>
<forbidden_patterns>
1. 禁止使用"打扰了"等负面开场
2. 禁止连续发送相同或相似内容
3. 禁止过度推销或施压
</forbidden_patterns>
<special_commands>
如果判断客户明确表示不感兴趣或要求转人工，直接返回: command back to user operation
</special_commands>
</constraints>

<thinking>
在生成消息之前，请按以下步骤思考：
1. 回顾对话历史，理解客户的态度和之前的交流内容
2. 分析客户最后一条消息的语气和意图
3. 思考什么样的跟进方式最不会让客户反感
4. 确保消息内容不重复之前说过的话
5. 根据 custom_instructions 中的风格要求调整语气
</thinking>

<output_format>
直接输出跟进消息文本，不要包含任何解释、标签或格式标记。
</output_format>
```

## XML 标签说明

| 标签                        | 用途         | 说明                         |
| --------------------------- | ------------ | ---------------------------- |
| `<task>`                    | 任务定义     | 明确告诉 AI 要完成什么任务   |
| `<context>`                 | 上下文信息   | 场景、客户信息、业务背景     |
| `<conversation_history>`    | 对话历史     | 完整的聊天记录（最多100条）  |
| `<latest_customer_message>` | 最新客户消息 | 正常回复场景中客户的最新消息 |
| `<custom_instructions>`     | 自定义指令   | 补刀场景中的 followup_prompt |
| `<style_guidelines>`        | 风格指南     | 回复风格设置（预设或自定义） |
| `<requirements>`            | 需求定义     | 功能需求和内容规则           |
| `<constraints>`             | 约束条件     | 长度限制、禁止模式、特殊命令 |
| `<thinking>`                | 思维步骤     | 引导 AI 的推理过程           |
| `<output_format>`           | 输出格式     | 明确输出要求                 |

## 预设风格

系统提供 5 种预设风格，会填充到 `<style_guidelines>` 中：

| 风格 Key       | 名称     | Prompt 内容                                                                  |
| -------------- | -------- | ---------------------------------------------------------------------------- |
| `none`         | 无预设   | 空                                                                           |
| `default`      | 默认风格 | 语气礼貌大方，使用"您"称呼用户。回答要直接且有条理，避免冗长。始终保持耐心。 |
| `lively`       | 活泼风格 | 语气要超级热情，多使用"哈喽"、"亲亲"等词汇。适当使用表情符号...              |
| `professional` | 专业风格 | 使用极其正式的商务用语，确保表达的准确性。采用结构化方式回答...              |
| `minimal`      | 极简风格 | 拒绝寒暄。直接识别用户意图并给出答案。使用精炼的短句...                      |

## API 请求格式

最终发送给 AI 服务的请求体：

```json
{
  "chatInput": "<task>...</task><context>...</context>...",
  "sessionId": "response_{customer_name}_{device_serial}",
  "username": "response_system",
  "message_type": "text",
  "metadata": {
    "source": "followup_response_detector",
    "serial": "{device_serial}",
    "customer": "{customer_name}",
    "context_length": {context_length},
    "prompt_format": "xml_structured"
  }
}
```

## 补刀 vs 正常回复对比

| 场景         | 触发条件               | 特有标签                    |
| ------------ | ---------------------- | --------------------------- |
| **正常回复** | `followup_prompt=None` | `<latest_customer_message>` |
| **补刀跟进** | `followup_prompt` 有值 | `<custom_instructions>`     |

## followup_prompt 示例

在设置页面配置的补刀提示词会填充到 `<custom_instructions>` 中：

```
# 设置页面配置
followup_prompt = "你是一个专业的销售客服，客户已经很久没有回复了，
请生成一条温和友好的跟进消息，不要太有压迫感，字数控制在30字以内"

# 最终出现在 XML 中
<custom_instructions>
你是一个专业的销售客服，客户已经很久没有回复了，
请生成一条温和友好的跟进消息，不要太有压迫感，字数控制在30字以内
</custom_instructions>
```

## 日志输出示例

系统会记录 XML 结构化 Prompt 的摘要：

```
[device_serial] ============================================================
[device_serial] AI REQUEST for 柠檬 [实时回复]
[device_serial] ============================================================
[device_serial] AI Server: http://47.113.187.234:8000/chat
[device_serial] Timeout: 15s
[device_serial] Session ID: response_柠檬_abc123
[device_serial] Prompt Format: XML Structured
[device_serial]
[device_serial] --- XML Prompt Structure ---
[device_serial] <task> 为 柠檬 生成回复
[device_serial] <context> 场景=实时回复, 客户=柠檬
[device_serial] <conversation_history> 9 条消息
[device_serial] <latest_customer_message> 不当主播...
[device_serial] <style_guidelines> 默认风格...
[device_serial] <constraints> length_limit=50字, special_commands=转人工检测
[device_serial]
[device_serial] --- Conversation History (9 messages) ---
[device_serial] [1] 👨 CUSTOMER: 我是柠檬
[device_serial] [2] 👤 AGENT: 感谢您信任并选择WELIKE...
...
[device_serial] ============================================================
```

## 测试脚本

可以使用独立测试脚本验证 AI 回复效果：

```bash
cd wecom-desktop/backend

# 测试正常回复场景
python tests/test_ai_reply_prompt.py

# 测试补刀场景
python tests/test_ai_reply_prompt.py --followup

# 使用不同风格
python tests/test_ai_reply_prompt.py --style lively

# 自定义补刀提示词
python tests/test_ai_reply_prompt.py --followup --followup-prompt "生成一条友好的跟进消息"
```

## 相关配置项

| 配置项             | 位置       | 默认值                     | 说明                                             |
| ------------------ | ---------- | -------------------------- | ------------------------------------------------ |
| `system_prompt`    | AI回复设置 | 空                         | 自定义系统提示词（填充到 style_guidelines）      |
| `prompt_style_key` | AI回复设置 | "none"                     | 预设风格选择                                     |
| `reply_max_length` | AI回复设置 | 50                         | 回复最大字数限制                                 |
| `aiServerUrl`      | AI回复设置 | http://47.113.187.234:8000 | AI 服务地址                                      |
| `aiReplyTimeout`   | AI回复设置 | 15                         | AI 请求超时（秒）                                |
| `followup_prompt`  | 补刀设置   | 空                         | 补刀场景专用提示词（填充到 custom_instructions） |

## 参考代码

- `wecom-desktop/backend/servic../03-impl-and-arch/response_detector.py` - `_generate_reply()` 方法
- `wecom-desktop/backend/tests/test_ai_reply_prompt.py` - 独立测试脚本
- `wecom-desktop/backend/servic../03-impl-and-arch/key-modules/service.py` - `get_combined_system_prompt()` 方法

## AI 回复中的 XML 标签处理

**问题描述**: 某些 LLM 可能会在输出中包含 XML 格式的标签（如 `<response>`、`</response>`），特别是当 prompt 中使用了 XML 格式时。

**解决方案**: 在 `response_detector.py` 的 `_generate_reply()` 方法中，添加了 XML 标签清理逻辑：

```python
# 清除 LLM 可能包含的 XML 标签
xml_tags_to_remove = [
    r'</?response>',
    r'</?output>',
    r'</?reply>',
    r'</?answer>',
    r'</?message>',
]
for pattern in xml_tags_to_remove:
    cleaned_reply = re.sub(pattern, '', cleaned_reply, flags=re.IGNORECASE)
```

**影响**: 确保发送到企微的消息不包含任何 XML 标签，保持消息内容纯净。

**相关文档**: `docs/04-bugs-and-fixes/active/02-04-ai-reply-contains-xml-tags.md`
