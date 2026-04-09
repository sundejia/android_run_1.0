"""
TDD Tests for AI Reply Integration

Tests the complete flow of AI reply generation:
1. Backend AI proxy endpoint
2. Message parsing logic
3. AI server communication
4. Error handling and fallbacks
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
import sys
from pathlib import Path
import json

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils.path_utils import get_project_root

from main import app


client = TestClient(app)


class TestAIProxyEndpoint:
    """Test the AI proxy endpoint that forwards requests to AI server"""

    def test_ai_proxy_endpoint_exists(self):
        """AI proxy endpoint should exist at /ai/chat"""
        # This test will fail initially - we need to create the endpoint
        response = client.post(
            "/ai/chat",
            json={"message": "你好", "serial": "test-device", "contact_name": "测试客户", "is_follow_up": False},
        )
        # Should not return 404
        assert response.status_code != 404, "AI proxy endpoint /ai/chat should exist"

    @patch("httpx.AsyncClient.post")
    def test_ai_proxy_forwards_to_ai_server(self, mock_post):
        """AI proxy should forward requests to the AI server"""
        # Mock AI server response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"output": "这是AI生成的回复", "success": True, "session_id": "test-session"}
        mock_post.return_value = mock_response

        response = client.post(
            "/ai/chat",
            json={
                "message": "客户说：我想了解一下价格",
                "serial": "test-device",
                "contact_name": "测试客户",
                "is_follow_up": False,
                "ai_server_url": "http://localhost:8000",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert "reply" in data

    def test_ai_proxy_handles_follow_up_mode(self):
        """AI proxy should handle follow-up (补刀) mode differently"""
        response = client.post(
            "/ai/chat",
            json={
                "message": "",  # No message content for follow-up
                "serial": "test-device",
                "contact_name": "测试客户",
                "is_follow_up": True,  # This is follow-up mode
                "ai_server_url": "http://localhost:8000",
            },
        )

        # Should return a valid response even without message content
        assert response.status_code == 200
        data = response.json()
        # Should either succeed with AI reply or fail gracefully
        assert "success" in data

    def test_ai_proxy_timeout_handling(self):
        """AI proxy should handle timeouts gracefully"""
        response = client.post(
            "/ai/chat",
            json={
                "message": "测试超时",
                "serial": "test-device",
                "contact_name": "测试客户",
                "is_follow_up": False,
                "ai_server_url": "http://invalid-server:9999",
                "timeout_seconds": 1,
            },
        )

        # Should return a failure response, not crash
        assert response.status_code in [200, 503, 504]
        data = response.json()
        if response.status_code == 200:
            # If 200, success should be False
            assert data.get("success") == False or "error" in data


class TestMessageParsing:
    """Test message parsing for AI prompts"""

    def test_parse_customer_message(self):
        """Should extract clean content from customer message"""
        # Test the endpoint with a typical customer message
        response = client.post(
            "/ai/chat",
            json={
                "message": "我想了解一下你们的产品价格，最近有什么优惠活动吗？",
                "serial": "test-device",
                "contact_name": "王小明",
                "is_follow_up": False,
                "ai_server_url": "http://localhost:8000",
            },
        )

        # Should process without error
        assert response.status_code in [200, 503]

    def test_parse_empty_message_in_follow_up(self):
        """Follow-up mode should work without customer message"""
        response = client.post(
            "/ai/chat",
            json={
                "message": "",
                "serial": "test-device",
                "contact_name": "王小明",
                "is_follow_up": True,
                "ai_server_url": "http://localhost:8000",
            },
        )

        assert response.status_code in [200, 503]


class TestConversationContext:
    """Test that AI receives proper conversation context"""

    def test_context_includes_contact_info(self):
        """AI request should include contact information for context"""
        response = client.post(
            "/ai/chat",
            json={
                "message": "你好",
                "serial": "test-device",
                "contact_name": "李经理",
                "channel": "企业微信",
                "is_follow_up": False,
                "ai_server_url": "http://localhost:8000",
            },
        )

        # Should process without error
        assert response.status_code in [200, 503]


class TestLastMessageAPI:
    """Test the last message API returns proper content for AI"""

    def test_last_message_returns_full_content(self):
        """Last message API should return full content, not truncated"""
        # This tests that we get the full message, not "[...truncated...]" format
        # The endpoint already exists at /sidecar/{serial}/last-message
        pass  # Existing endpoint, just documenting the requirement


class TestAIServerHealth:
    """Test AI server health checks"""

    def test_ai_health_check_endpoint(self):
        """Should have an endpoint to check AI server health"""
        response = client.get("/ai/health?server_url=http://localhost:8000")

        # Should return health status
        assert response.status_code in [200, 503]
        data = response.json()
        assert "healthy" in data or "status" in data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
