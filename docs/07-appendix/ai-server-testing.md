# AI 服务器连通性测试

本文档介绍如何使用 `test_ai_server.py` 脚本测试与 AI 服务器的连通性。

## 概述

测试脚本会自动执行以下测试：

1. **健康检查** - 测试 `GET /health` 端点
2. **简单聊天** - 测试基本的聊天功能（无上下文）
3. **上下文聊天** - 测试带对话历史的聊天
4. **系统提示词** - 测试带系统提示词的聊天
5. **转人工检测** - 测试 AI 是否能正确识别转人工请求

## 前置要求

- Python 3.7+
- `requests` 库（脚本会自动检查并提示安装）

```bash
pip install requests
```

## 使用方法

### Windows 用户

#### 方式 1：使用批处理文件（推荐）

双击 `test_ai_server.bat` 或在命令行中运行：

```cmd
test_ai_server.bat
```

指定自定义服务器地址：

```cmd
test_ai_server.bat --url http://192.168.1.100:8000
```

指定超时时间：

```cmd
test_ai_server.bat --url http://localhost:8000 --timeout 15
```

#### 方式 2：直接使用 Python

```cmd
python test_ai_server.py
python test_ai_server.py --url http://localhost:8000
python test_ai_server.py --url http://192.168.1.100:8000 --timeout 15
```

### Linux/macOS 用户

```bash
python3 test_ai_server.py
python3 test_ai_server.py --url http://localhost:8000
python3 test_ai_server.py --url http://192.168.1.100:8000 --timeout 15
```

## 命令行参数

| 参数        | 说明               | 默认值                  |
| ----------- | ------------------ | ----------------------- |
| `--url`     | AI 服务器地址      | `http://localhost:8000` |
| `--timeout` | 请求超时时间（秒） | `10`                    |
| `--help`    | 显示帮助信息       | -                       |

## 输出示例

### 成功的测试输出

```
============================================================
                     测试 1: 健康检查 (GET /health)
============================================================

ℹ 请求地址: http://localhost:8000/health
ℹ 响应时间: 45ms
ℹ 状态码: 200
ℹ 响应内容: {
  "status": "healthy"
}
✓ 健康检查通过！

============================================================
                  测试 2: 简单聊天消息（无上下文）
============================================================

ℹ 请求地址: http://localhost:8000/chat
ℹ 请求体:
{
  "chatInput": "[LATEST MESSAGE]\n你好",
  "sessionId": "test_TEST_DEVICE_001_1706500000",
  "username": "test_TEST_DEVICE_001",
  "message_type": "text",
  "metadata": {
    "source": "test_script",
    "serial": "TEST_DEVICE_001",
    "timestamp": "2026-01-29T12:00:00.000000",
    "original_message": "你好"
  }
}
ℹ 响应时间: 1234ms
ℹ 状态码: 200
ℹ 响应内容:
{
  "success": true,
  "output": "你好！有什么可以帮助你的吗？",
  "session_id": "test_TEST_DEVICE_001_1706500000",
  "username": "test_TEST_DEVICE_001",
  "timestamp": "2026-01-29T12:00:01.234000"
}
✓ 聊天成功！AI 回复: 你好！有什么可以帮助你的吗？

============================================================
                         测试总结
============================================================

总测试数: 5
通过: 5
失败: 0

详细结果:
测试项               结果          响应时间
--------------------------------------------------
健康检查             ✓ 通过        45ms
简单聊天             ✓ 通过        1234ms
上下文聊天           ✓ 通过        1456ms
系统提示词聊天       ✓ 通过        1123ms
转人工检测           ✓ 通过        987ms

✓ 🎉 所有测试通过！AI 服务器运行正常。
```

### 失败的测试输出

```
============================================================
                     测试 1: 健康检查 (GET /health)
============================================================

ℹ 请求地址: http://localhost:8000/health
✗ 无法连接到服务器: http://localhost:8000
ℹ 请检查:
ℹ   1. 服务器地址是否正确
ℹ   2. AI 服务器是否正在运行
ℹ   3. 防火墙设置

============================================================
                         测试总结
============================================================

总测试数: 5
通过: 0
失败: 5

✗ 有 5 个测试失败，请检查 AI 服务器配置。
```

## 常见问题

### 1. 连接被拒绝

**错误信息**：

```
✗ 无法连接到服务器: http://localhost:8000
```

**解决方法**：

- 确认 AI 服务器是否正在运行
- 检查服务器地址和端口是否正确
- 检查防火墙设置

### 2. 请求超时

**错误信息**：

```
✗ 请求超时 (>10秒)
```

**解决方法**：

- 增加超时时间：`--timeout 30`
- 检查网络连接
- 检查服务器负载

### 3. 响应格式不正确

**错误信息**：

```
✗ 响应格式不正确或缺少 output 字段
```

**解决方法**：

- 检查 AI 服务器的实现是否符合 API 规范
- 查看响应内容，确认返回的 JSON 格式
- 参考 [AI 服务器消息格式文档](../03-impl-and-arch/key-modules/ai-server-message-format.md)

### 4. 缺少 requests 库

**错误信息**：

```
❌ 需要安装 requests 库: pip install requests
```

**解决方法**：

```bash
pip install requests
```

## 在 CI/CD 中使用

### GitHub Actions 示例

```yaml
- name: Test AI Server Connectivity
  run: |
    python test_ai_server.py --url ${{ secrets.AI_SERVER_URL }} --timeout 30
```

### 作为健康检查

可以定期运行此脚本来监控 AI 服务器状态：

```bash
# Linux cron (每 5 分钟检查一次)
*/5 * * * * cd /path/to/project && python3 test_ai_server.py >> /var/log/ai_health.log 2>&1
```

```powershell
# Windows 任务计划程序
schtasks /create /tn "AI Server Health Check" /tr "python test_ai_server.py" /sc minute /mo 5
```

## 扩展测试

如果需要添加自定义测试，可以继承 `AIServerTester` 类：

```python
from test_ai_server import AIServerTester

class CustomTester(AIServerTester):
    def test_custom_scenario(self):
        """自定义测试场景"""
        self.print_header("测试 6: 自定义场景")

        # 实现你的测试逻辑
        payload = {
            "chatInput": "你的测试消息",
            # ...
        }

        # 发送请求并验证
        # ...

if __name__ == '__main__':
    tester = CustomTester('http://localhost:8000')
    tester.test_custom_scenario()
```

## 相关文档

- [AI 服务器消息格式](../03-impl-and-arch/key-modules/ai-server-message-format.md)
- [AI 配置 API](../03-impl-and-arch/key-modules/ai-config.md)
- [AI 提示词与上下文逻辑](../03-impl-and-arch/key-modules/ai_prompt_context_logic.md)

## 故障排查清单

遇到问题时，按以下顺序检查：

- [ ] AI 服务器是否正在运行
- [ ] 服务器地址和端口是否正确
- [ ] 网络连接是否正常
- [ ] 防火墙是否允许连接
- [ ] AI 服务器日志是否有错误信息
- [ ] 请求和响应格式是否符合 API 规范
- [ ] Python 和 requests 库版本是否正确

## 贡献

如果发现测试脚本的问题或有改进建议，请：

1. 在 GitHub 上提交 Issue
2. 提交 Pull Request 并描述改进内容
3. 更新相关文档
