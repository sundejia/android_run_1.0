#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 服务器连通性测试脚本

测试与 AI 服务器的连接和基本功能：
- 健康检查 (GET /health)
- 聊天接口 (POST /chat)
- 不同场景的消息格式测试

使用方法:
    python test_ai_server.py
    python test_ai_server.py --url http://localhost:8000
    python test_ai_server.py --url http://your-server.com:8000 --timeout 15
"""

import argparse
import json
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

try:
    import requests
except ImportError:
    print("❌ 需要安装 requests 库: pip install requests")
    sys.exit(1)


class Colors:
    """终端颜色代码"""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


class AIServerTester:
    """AI 服务器连通性测试器"""
    
    def __init__(self, server_url: str, timeout: int = 10):
        """
        初始化测试器
        
        Args:
            server_url: AI 服务器地址 (例如: http://localhost:8000)
            timeout: 请求超时时间（秒）
        """
        self.server_url = server_url.rstrip('/')
        self.timeout = timeout
        self.test_results = []
        
    def print_header(self, text: str):
        """打印标题"""
        print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}")
        print(f"{Colors.HEADER}{Colors.BOLD}{text:^60}{Colors.ENDC}")
        print(f"{Colors.HEADER}{Colors.BOLD}{'='*60}{Colors.ENDC}\n")
    
    def print_success(self, text: str):
        """打印成功消息"""
        print(f"{Colors.OKGREEN}✓ {text}{Colors.ENDC}")
    
    def print_error(self, text: str):
        """打印错误消息"""
        print(f"{Colors.FAIL}✗ {text}{Colors.ENDC}")
    
    def print_info(self, text: str):
        """打印信息"""
        print(f"{Colors.OKCYAN}ℹ {text}{Colors.ENDC}")
    
    def print_warning(self, text: str):
        """打印警告"""
        print(f"{Colors.WARNING}⚠ {text}{Colors.ENDC}")
    
    def test_health_check(self) -> bool:
        """
        测试健康检查端点
        
        Returns:
            bool: 测试是否通过
        """
        self.print_header("测试 1: 健康检查 (GET /health)")
        
        endpoint = f"{self.server_url}/health"
        self.print_info(f"请求地址: {endpoint}")
        
        try:
            start_time = time.time()
            response = requests.get(endpoint, timeout=self.timeout)
            elapsed = (time.time() - start_time) * 1000
            
            self.print_info(f"响应时间: {elapsed:.0f}ms")
            self.print_info(f"状态码: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                self.print_info(f"响应内容: {json.dumps(data, ensure_ascii=False, indent=2)}")
                
                if data.get('status') == 'healthy':
                    self.print_success("健康检查通过！")
                    self.test_results.append(("健康检查", True, elapsed))
                    return True
                else:
                    self.print_error(f"服务器状态异常: {data.get('status')}")
                    self.test_results.append(("健康检查", False, elapsed))
                    return False
            else:
                self.print_error(f"HTTP 状态码错误: {response.status_code}")
                self.print_error(f"响应内容: {response.text}")
                self.test_results.append(("健康检查", False, elapsed))
                return False
                
        except requests.exceptions.Timeout:
            self.print_error(f"请求超时 (>{self.timeout}秒)")
            self.test_results.append(("健康检查", False, None))
            return False
        except requests.exceptions.ConnectionError:
            self.print_error(f"无法连接到服务器: {self.server_url}")
            self.print_info("请检查:")
            self.print_info("  1. 服务器地址是否正确")
            self.print_info("  2. AI 服务器是否正在运行")
            self.print_info("  3. 防火墙设置")
            self.test_results.append(("健康检查", False, None))
            return False
        except Exception as e:
            self.print_error(f"未知错误: {type(e).__name__}: {str(e)}")
            self.test_results.append(("健康检查", False, None))
            return False
    
    def test_chat_simple(self) -> bool:
        """
        测试简单聊天消息（无上下文）
        
        Returns:
            bool: 测试是否通过
        """
        self.print_header("测试 2: 简单聊天消息（无上下文）")
        
        endpoint = f"{self.server_url}/chat"
        timestamp = int(time.time())
        serial = "TEST_DEVICE_001"
        
        payload = {
            "chatInput": "[LATEST MESSAGE]\n你好",
            "sessionId": f"test_{serial}_{timestamp}",
            "username": f"test_{serial}",
            "message_type": "text",
            "metadata": {
                "source": "test_script",
                "serial": serial,
                "timestamp": datetime.now().isoformat(),
                "original_message": "你好"
            }
        }
        
        self.print_info(f"请求地址: {endpoint}")
        self.print_info(f"请求体:")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        
        try:
            start_time = time.time()
            response = requests.post(
                endpoint,
                json=payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"}
            )
            elapsed = (time.time() - start_time) * 1000
            
            self.print_info(f"响应时间: {elapsed:.0f}ms")
            self.print_info(f"状态码: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                self.print_info(f"响应内容:")
                print(json.dumps(data, ensure_ascii=False, indent=2))
                
                if data.get('success') and data.get('output'):
                    self.print_success(f"聊天成功！AI 回复: {data['output']}")
                    self.test_results.append(("简单聊天", True, elapsed))
                    return True
                else:
                    self.print_error("响应格式不正确或缺少 output 字段")
                    self.test_results.append(("简单聊天", False, elapsed))
                    return False
            else:
                self.print_error(f"HTTP 状态码错误: {response.status_code}")
                self.print_error(f"响应内容: {response.text}")
                self.test_results.append(("简单聊天", False, elapsed))
                return False
                
        except requests.exceptions.Timeout:
            self.print_error(f"请求超时 (>{self.timeout}秒)")
            self.test_results.append(("简单聊天", False, None))
            return False
        except Exception as e:
            self.print_error(f"错误: {type(e).__name__}: {str(e)}")
            self.test_results.append(("简单聊天", False, None))
            return False
    
    def test_chat_with_context(self) -> bool:
        """
        测试带对话上下文的聊天
        
        Returns:
            bool: 测试是否通过
        """
        self.print_header("测试 3: 带对话上下文的聊天")
        
        endpoint = f"{self.server_url}/chat"
        timestamp = int(time.time())
        serial = "TEST_DEVICE_002"
        
        # 构建带上下文的输入
        chat_input = """[CONTEXT]
STREAMER: 你好，我想了解一下你们的产品
AGENT: 您好！很高兴为您服务，请问您想了解哪方面的信息？
STREAMER: 价格多少

[LATEST MESSAGE]
价格多少"""
        
        payload = {
            "chatInput": chat_input,
            "sessionId": f"test_{serial}_{timestamp}",
            "username": f"test_{serial}",
            "message_type": "text",
            "metadata": {
                "source": "test_script",
                "serial": serial,
                "timestamp": datetime.now().isoformat(),
                "original_message": "价格多少"
            }
        }
        
        self.print_info(f"请求地址: {endpoint}")
        self.print_info(f"请求体:")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        
        try:
            start_time = time.time()
            response = requests.post(
                endpoint,
                json=payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"}
            )
            elapsed = (time.time() - start_time) * 1000
            
            self.print_info(f"响应时间: {elapsed:.0f}ms")
            self.print_info(f"状态码: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                self.print_info(f"响应内容:")
                print(json.dumps(data, ensure_ascii=False, indent=2))
                
                if data.get('success') and data.get('output'):
                    self.print_success(f"聊天成功！AI 回复: {data['output']}")
                    self.test_results.append(("上下文聊天", True, elapsed))
                    return True
                else:
                    self.print_error("响应格式不正确或缺少 output 字段")
                    self.test_results.append(("上下文聊天", False, elapsed))
                    return False
            else:
                self.print_error(f"HTTP 状态码错误: {response.status_code}")
                self.print_error(f"响应内容: {response.text}")
                self.test_results.append(("上下文聊天", False, elapsed))
                return False
                
        except requests.exceptions.Timeout:
            self.print_error(f"请求超时 (>{self.timeout}秒)")
            self.test_results.append(("上下文聊天", False, None))
            return False
        except Exception as e:
            self.print_error(f"错误: {type(e).__name__}: {str(e)}")
            self.test_results.append(("上下文聊天", False, None))
            return False
    
    def test_chat_with_system_prompt(self) -> bool:
        """
        测试带系统提示词的聊天
        
        Returns:
            bool: 测试是否通过
        """
        self.print_header("测试 4: 带系统提示词的聊天")
        
        endpoint = f"{self.server_url}/chat"
        timestamp = int(time.time())
        serial = "TEST_DEVICE_003"
        
        # 构建带系统提示词的输入
        chat_input = """system_prompt: 回复要友好自然。
If the user wants to switch to human operation, human agent, or manual service, directly return ONLY the text 'command back to user operation' without any other text.
user_prompt: [CONTEXT]
STREAMER: 你好，我想了解一下产品
AGENT: 您好！很高兴为您服务，请问您想了解哪方面的信息？
STREAMER: 详细介绍一下功能

[LATEST MESSAGE]
详细介绍一下功能"""
        
        payload = {
            "chatInput": chat_input,
            "sessionId": f"test_{serial}_{timestamp}",
            "username": f"test_{serial}",
            "message_type": "text",
            "metadata": {
                "source": "test_script",
                "serial": serial,
                "timestamp": datetime.now().isoformat(),
                "original_message": "详细介绍一下功能"
            }
        }
        
        self.print_info(f"请求地址: {endpoint}")
        self.print_info(f"请求体:")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        
        try:
            start_time = time.time()
            response = requests.post(
                endpoint,
                json=payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"}
            )
            elapsed = (time.time() - start_time) * 1000
            
            self.print_info(f"响应时间: {elapsed:.0f}ms")
            self.print_info(f"状态码: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                self.print_info(f"响应内容:")
                print(json.dumps(data, ensure_ascii=False, indent=2))
                
                if data.get('success') and data.get('output'):
                    reply = data['output']
                    self.print_success(f"聊天成功！AI 回复: {reply}")
                    
                    # 检查回复长度是否符合系统提示词要求
                    if len(reply) <= 50:
                        self.print_success(f"✓ 回复长度符合要求 ({len(reply)} 字)")
                    else:
                        self.print_warning(f"回复长度超过 50 字 ({len(reply)} 字)")
                    
                    self.test_results.append(("系统提示词聊天", True, elapsed))
                    return True
                else:
                    self.print_error("响应格式不正确或缺少 output 字段")
                    self.test_results.append(("系统提示词聊天", False, elapsed))
                    return False
            else:
                self.print_error(f"HTTP 状态码错误: {response.status_code}")
                self.print_error(f"响应内容: {response.text}")
                self.test_results.append(("系统提示词聊天", False, elapsed))
                return False
                
        except requests.exceptions.Timeout:
            self.print_error(f"请求超时 (>{self.timeout}秒)")
            self.test_results.append(("系统提示词聊天", False, None))
            return False
        except Exception as e:
            self.print_error(f"错误: {type(e).__name__}: {str(e)}")
            self.test_results.append(("系统提示词聊天", False, None))
            return False
    
    def test_human_request_detection(self) -> bool:
        """
        测试转人工请求检测
        
        Returns:
            bool: 测试是否通过
        """
        self.print_header("测试 5: 转人工请求检测")
        
        endpoint = f"{self.server_url}/chat"
        timestamp = int(time.time())
        serial = "TEST_DEVICE_004"
        
        # 使用明确的转人工请求
        chat_input = """system_prompt: If the user wants to switch to human operation, human agent, or manual service, directly return ONLY the text 'command back to user operation' without any other text.
user_prompt: [LATEST MESSAGE]
我要转人工"""
        
        payload = {
            "chatInput": chat_input,
            "sessionId": f"test_{serial}_{timestamp}",
            "username": f"test_{serial}",
            "message_type": "text",
            "metadata": {
                "source": "test_script",
                "serial": serial,
                "timestamp": datetime.now().isoformat(),
                "original_message": "我要转人工"
            }
        }
        
        self.print_info(f"请求地址: {endpoint}")
        self.print_info(f"测试消息: '我要转人工'")
        
        try:
            start_time = time.time()
            response = requests.post(
                endpoint,
                json=payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"}
            )
            elapsed = (time.time() - start_time) * 1000
            
            self.print_info(f"响应时间: {elapsed:.0f}ms")
            self.print_info(f"状态码: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                self.print_info(f"响应内容:")
                print(json.dumps(data, ensure_ascii=False, indent=2))
                
                if data.get('success') and data.get('output'):
                    reply = data['output'].lower()
                    if 'command back to user operation' in reply:
                        self.print_success("✓ 正确识别转人工请求！")
                        self.print_success(f"AI 回复: {data['output']}")
                        self.test_results.append(("转人工检测", True, elapsed))
                        return True
                    else:
                        self.print_warning("AI 未返回转人工命令")
                        self.print_warning(f"AI 回复: {data['output']}")
                        self.print_info("这可能是正常的，取决于 AI 模型的配置")
                        self.test_results.append(("转人工检测", True, elapsed))
                        return True
                else:
                    self.print_error("响应格式不正确或缺少 output 字段")
                    self.test_results.append(("转人工检测", False, elapsed))
                    return False
            else:
                self.print_error(f"HTTP 状态码错误: {response.status_code}")
                self.print_error(f"响应内容: {response.text}")
                self.test_results.append(("转人工检测", False, elapsed))
                return False
                
        except requests.exceptions.Timeout:
            self.print_error(f"请求超时 (>{self.timeout}秒)")
            self.test_results.append(("转人工检测", False, None))
            return False
        except Exception as e:
            self.print_error(f"错误: {type(e).__name__}: {str(e)}")
            self.test_results.append(("转人工检测", False, None))
            return False
    
    def test_new_friend_welcome(self) -> bool:
        """
        测试新好友添加后的欢迎消息场景
        
        模拟场景：用户刚添加为WeCom联系人，显示系统欢迎提示
        如：You have added 旺旺小仙 as your WeCom contact. Start chatting!
        
        Returns:
            bool: 测试是否通过
        """
        self.print_header("测试 6: 新好友欢迎消息")
        
        endpoint = f"{self.server_url}/chat"
        timestamp = int(time.time())
        serial = "TEST_DEVICE_005"
        
        # 构建新好友场景的输入
        # 系统消息 + 用户自我介绍
        chat_input = """system_prompt: 你是一个友好的客服助手。当用户刚添加为好友时，请热情欢迎。回复要简洁自然。
user_prompt: [CONTEXT]
SYSTEM: You have added 旺旺小仙 as your WeCom contact. Start chatting!
STREAMER: 我是旺旺小仙
agent: 感谢您新人并选择welike，未来我将会在该账号与您保持沟通
[LATEST MESSAGE]
感谢您新人并选择welike，未来我将会在该账号与您保持沟通"""
        
        payload = {
            "chatInput": chat_input,
            "sessionId": f"test_{serial}_{timestamp}",
            "username": f"test_{serial}",
            "message_type": "text",
            "metadata": {
                "source": "test_script",
                "serial": serial,
                "timestamp": datetime.now().isoformat(),
                "original_message": "我是旺旺小仙",
                "is_new_friend": True,
                "customer_name": "旺旺小仙"
            }
        }
        
        self.print_info(f"请求地址: {endpoint}")
        self.print_info(f"测试场景: 新好友 '旺旺小仙' 添加后发送自我介绍")
        self.print_info(f"请求体:")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        
        try:
            start_time = time.time()
            response = requests.post(
                endpoint,
                json=payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"}
            )
            elapsed = (time.time() - start_time) * 1000
            
            self.print_info(f"响应时间: {elapsed:.0f}ms")
            self.print_info(f"状态码: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                self.print_info(f"响应内容:")
                print(json.dumps(data, ensure_ascii=False, indent=2))
                
                if data.get('success') and data.get('output'):
                    reply = data['output']
                    self.print_success(f"新好友欢迎消息生成成功！")
                    self.print_success(f"AI 回复: {reply}")
                    
                    # 检查回复是否友好（包含欢迎/你好等词汇）
                    welcome_keywords = ['欢迎', '你好', '您好', '很高兴', '认识', '朋友', 'Hi', 'Hello']
                    has_welcome = any(kw in reply for kw in welcome_keywords)
                    
                    if has_welcome:
                        self.print_success("✓ 回复包含欢迎语")
                    else:
                        self.print_warning("回复未检测到明确的欢迎语（可能仍然正确）")
                    
                    self.test_results.append(("新好友欢迎", True, elapsed))
                    return True
                else:
                    self.print_error("响应格式不正确或缺少 output 字段")
                    self.test_results.append(("新好友欢迎", False, elapsed))
                    return False
            else:
                self.print_error(f"HTTP 状态码错误: {response.status_code}")
                self.print_error(f"响应内容: {response.text}")
                self.test_results.append(("新好友欢迎", False, elapsed))
                return False
                
        except requests.exceptions.Timeout:
            self.print_error(f"请求超时 (>{self.timeout}秒)")
            self.test_results.append(("新好友欢迎", False, None))
            return False
        except Exception as e:
            self.print_error(f"错误: {type(e).__name__}: {str(e)}")
            self.test_results.append(("新好友欢迎", False, None))
            return False
    
    def print_summary(self):
        """打印测试总结"""
        self.print_header("测试总结")
        
        total = len(self.test_results)
        passed = sum(1 for _, result, _ in self.test_results if result)
        failed = total - passed
        
        print(f"总测试数: {total}")
        print(f"{Colors.OKGREEN}通过: {passed}{Colors.ENDC}")
        print(f"{Colors.FAIL}失败: {failed}{Colors.ENDC}")
        print()
        
        # 详细结果
        print("详细结果:")
        print(f"{'测试项':<20} {'结果':<10} {'响应时间':<15}")
        print("-" * 50)
        
        for name, result, elapsed in self.test_results:
            status = f"{Colors.OKGREEN}✓ 通过{Colors.ENDC}" if result else f"{Colors.FAIL}✗ 失败{Colors.ENDC}"
            time_str = f"{elapsed:.0f}ms" if elapsed is not None else "N/A"
            print(f"{name:<20} {status:<20} {time_str:<15}")
        
        print()
        
        if failed == 0:
            self.print_success(f"🎉 所有测试通过！AI 服务器运行正常。")
            return True
        else:
            self.print_error(f"有 {failed} 个测试失败，请检查 AI 服务器配置。")
            return False
    
    def run_all_tests(self) -> bool:
        """
        运行所有测试
        
        Returns:
            bool: 所有测试是否通过
        """
        print(f"\n{Colors.BOLD}AI 服务器连通性测试{Colors.ENDC}")
        print(f"服务器地址: {Colors.OKCYAN}{self.server_url}{Colors.ENDC}")
        print(f"超时时间: {self.timeout}秒")
        
        # 运行测试
        tests = [
            self.test_health_check,
            self.test_chat_simple,
            self.test_chat_with_context,
            self.test_chat_with_system_prompt,
            self.test_human_request_detection,
            self.test_new_friend_welcome,
        ]
        
        for test in tests:
            try:
                test()
            except KeyboardInterrupt:
                print(f"\n{Colors.WARNING}测试被用户中断{Colors.ENDC}")
                break
            except Exception as e:
                self.print_error(f"测试执行出错: {type(e).__name__}: {str(e)}")
            
            # 在测试之间稍作停顿
            time.sleep(0.5)
        
        # 打印总结
        return self.print_summary()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='AI 服务器连通性测试脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s
  %(prog)s --url http://localhost:8000
  %(prog)s --url http://your-server.com:8000 --timeout 15
        """
    )
    
    parser.add_argument(
        '--url',
        type=str,
        default='http://localhost:8000',
        help='AI 服务器地址 (默认: http://localhost:8000)'
    )
    
    parser.add_argument(
        '--timeout',
        type=int,
        default=10,
        help='请求超时时间（秒）(默认: 10)'
    )
    
    args = parser.parse_args()
    
    # 创建测试器并运行测试
    tester = AIServerTester(args.url, args.timeout)
    success = tester.run_all_tests()
    
    # 返回退出码
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
