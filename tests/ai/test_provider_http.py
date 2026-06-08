"""D4.1.1 — OpenAICompatibleProvider HTTP 调用测试 (respx mock).

覆盖(参考 D4.1.1 实施目标):
  - 6 个 provider 真实请求构造(URL/headers/payload 正确)
  - 4 类窄化业务异常(参考 D3.3.3 教训"异常范围要窄化"):
      LLMTimeoutError / LLMConnectionError / LLMAPIError / LLMResponseError
  - 编程错误透传(不 catch-all)

不依赖任何真实 API Key — 用 respx 拦截 httpx 调用.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
import respx

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.ai.capability import Provider  # noqa: E402
from my_ai_employee.ai.providers import (  # noqa: E402
    LLMAPIError,
    LLMConnectionError,
    LLMRequest,
    LLMResponseError,
    LLMTimeoutError,
    OpenAICompatibleProvider,
)

# === 测试用 Provider 矩阵 ===
# v2 晨报钩子: 6 个国内/外 + 1 个本地, 共 7 个(anthropic 是兜底, 通常不直接发)

_PROVIDER_CASES: list[tuple[Provider, str, str, str]] = [
    # (Provider, base_url, model_id, full_id)
    (Provider.DEEPSEEK, "https://api.deepseek.com/v1", "deepseek-chat", "deepseek/deepseek-chat"),
    (
        Provider.QWEN,
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen3-max",
        "qwen/qwen3-max",
    ),
    (Provider.GLM, "https://open.bigmodel.cn/api/paas/v4", "glm-4-plus", "glm/glm-4-plus"),
    (Provider.MINIMAX, "https://api.minimaxi.com/v1", "MiniMax-M3", "minimax/MiniMax-M3"),
    (Provider.TENCENT, "https://api.hunyuan.tencent.com/v1", "hunyuan-pro", "tencent/hunyuan-pro"),
    (Provider.OPENAI, "https://api.openai.com/v1", "gpt-4.1", "openai/gpt-4.1"),
    (Provider.OLLAMA, "http://127.0.0.1:11434/v1", "llama3.2", "ollama/llama3.2"),
]


def _mock_openai_response(content: str, input_tokens: int = 10, output_tokens: int = 5) -> dict:
    """构造标准 OpenAI 风格响应."""
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "test",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


# ============================================================
# TestChatSuccess — 7 个 provider 真实请求构造
# ============================================================


class TestChatSuccess:
    """成功路径: respx 拦截 + 返回标准 OpenAI 响应."""

    @pytest.mark.parametrize(
        ("provider_type", "base_url", "model_id", "full_id"),
        _PROVIDER_CASES,
    )
    @respx.mock
    def test_chat_sends_correct_request(
        self,
        provider_type: Provider,
        base_url: str,
        model_id: str,
        full_id: str,
    ) -> None:
        """验证 URL/headers/payload 正确, 返回 LLMResponse."""
        p = OpenAICompatibleProvider(
            provider_type=provider_type,
            base_url=base_url,
            api_key="test-key-12345",
        )
        expected_url = f"{base_url}/chat/completions"

        # respx 拦截 + 返回标准响应
        route = respx.post(expected_url).mock(
            return_value=httpx.Response(
                200,
                json=_mock_openai_response("hello world", input_tokens=20, output_tokens=2),
            )
        )

        request = LLMRequest(
            model_full_id=full_id,
            messages=[{"role": "user", "content": "hi"}],
            temperature=0.5,
            max_tokens=512,
        )
        response = p.chat(request)

        # 1. 响应解析正确
        assert response.content == "hello world"
        assert response.model_full_id == full_id
        assert response.input_tokens == 20
        assert response.output_tokens == 2
        assert response.latency_ms >= 0  # 至少 0ms

        # 2. 请求构造正确(URL / method / headers / body)
        assert route.called
        assert route.call_count == 1
        sent_request = route.calls.last.request
        assert sent_request.method == "POST"
        assert str(sent_request.url) == expected_url
        # Authorization header
        assert sent_request.headers["Authorization"] == "Bearer test-key-12345"
        assert sent_request.headers["Content-Type"] == "application/json"
        # Payload
        payload = json.loads(sent_request.content)
        assert payload["model"] == model_id
        assert payload["messages"] == [{"role": "user", "content": "hi"}]
        assert payload["temperature"] == 0.5
        assert payload["max_tokens"] == 512

    @respx.mock
    def test_chat_minimal_response_no_usage(self) -> None:
        """响应无 usage 字段 → 默认 0 tokens(部分 provider 不返回 usage)."""
        p = OpenAICompatibleProvider(
            provider_type=Provider.DEEPSEEK,
            base_url="https://api.deepseek.com/v1",
            api_key="test-key",
        )
        respx.post("https://api.deepseek.com/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "x",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}}],
                },
            )
        )
        response = p.chat(LLMRequest(model_full_id="deepseek/deepseek-chat", messages=[]))
        assert response.content == "ok"
        assert response.input_tokens == 0
        assert response.output_tokens == 0

    @respx.mock
    def test_chat_uses_provider_specific_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """专用 Key(DEEPSEEK_API_KEY)优先于 OPENAI_API_KEY 兜底."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-specific-key")
        monkeypatch.setenv("OPENAI_API_KEY", "openai-fallback-key")
        p = OpenAICompatibleProvider(
            provider_type=Provider.DEEPSEEK,
            base_url="https://api.deepseek.com/v1",
            # 不传 api_key, 走环境变量
        )
        assert p.api_key == "deepseek-specific-key"

    def test_resolve_api_key_fallback_to_openai(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """无专用 Key → 回退 OPENAI_API_KEY."""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "openai-fallback-key")
        p = OpenAICompatibleProvider(
            provider_type=Provider.DEEPSEEK,
            base_url="https://api.deepseek.com/v1",
        )
        assert p.api_key == "openai-fallback-key"


# ============================================================
# TestChatTimeout — 超时
# ============================================================


class TestChatTimeout:
    """httpx.TimeoutException → LLMTimeoutError."""

    @respx.mock
    def test_timeout_raises_llm_timeout_error(self) -> None:
        p = OpenAICompatibleProvider(
            provider_type=Provider.DEEPSEEK,
            base_url="https://api.deepseek.com/v1",
            api_key="test-key",
            timeout=0.001,  # 1ms 必然超时
        )
        respx.post("https://api.deepseek.com/v1/chat/completions").mock(
            side_effect=httpx.TimeoutException("simulated timeout")
        )
        with pytest.raises(LLMTimeoutError, match="超时"):
            p.chat(LLMRequest(model_full_id="deepseek/deepseek-chat", messages=[]))


# ============================================================
# TestChatAPIError — HTTP 4xx/5xx
# ============================================================


class TestChatAPIError:
    """HTTP 4xx/5xx → LLMAPIError(含 status_code + body)."""

    @pytest.mark.parametrize(
        ("status_code", "expected_in_msg"),
        [
            (401, "401"),
            (403, "403"),
            (404, "404"),
            (429, "429"),
            (500, "500"),
            (502, "502"),
        ],
    )
    @respx.mock
    def test_http_error_raises_llm_api_error(self, status_code: int, expected_in_msg: str) -> None:
        p = OpenAICompatibleProvider(
            provider_type=Provider.DEEPSEEK,
            base_url="https://api.deepseek.com/v1",
            api_key="test-key",
        )
        error_body = json.dumps({"error": {"message": f"status {status_code} test"}})
        respx.post("https://api.deepseek.com/v1/chat/completions").mock(
            return_value=httpx.Response(status_code, text=error_body)
        )
        with pytest.raises(LLMAPIError) as exc_info:
            p.chat(LLMRequest(model_full_id="deepseek/deepseek-chat", messages=[]))
        assert exc_info.value.status_code == status_code
        assert expected_in_msg in str(exc_info.value)
        assert "status" in exc_info.value.body  # 完整 body 保留

    @respx.mock
    def test_api_error_truncates_huge_body(self) -> None:
        """超长响应体截断到 500 字符, 防止爆日志."""
        p = OpenAICompatibleProvider(
            provider_type=Provider.DEEPSEEK,
            base_url="https://api.deepseek.com/v1",
            api_key="test-key",
        )
        huge_body = "x" * 5000
        respx.post("https://api.deepseek.com/v1/chat/completions").mock(
            return_value=httpx.Response(500, text=huge_body)
        )
        with pytest.raises(LLMAPIError) as exc_info:
            p.chat(LLMRequest(model_full_id="deepseek/deepseek-chat", messages=[]))
        # body 截断到 500 字符
        assert len(exc_info.value.body) == 500


# ============================================================
# TestChatConnectionError — 网络错误
# ============================================================


class TestChatConnectionError:
    """httpx.ConnectError / RequestError → LLMConnectionError."""

    @respx.mock
    def test_connect_error_raises_llm_connection_error(self) -> None:
        p = OpenAICompatibleProvider(
            provider_type=Provider.DEEPSEEK,
            base_url="https://api.deepseek.com/v1",
            api_key="test-key",
        )
        respx.post("https://api.deepseek.com/v1/chat/completions").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        with pytest.raises(LLMConnectionError, match="连接失败"):
            p.chat(LLMRequest(model_full_id="deepseek/deepseek-chat", messages=[]))

    @respx.mock
    def test_read_error_raises_llm_connection_error(self) -> None:
        """httpx.ReadError(连接成功但读取失败)→ LLMConnectionError."""
        p = OpenAICompatibleProvider(
            provider_type=Provider.DEEPSEEK,
            base_url="https://api.deepseek.com/v1",
            api_key="test-key",
        )
        respx.post("https://api.deepseek.com/v1/chat/completions").mock(
            side_effect=httpx.ReadError("read failed")
        )
        with pytest.raises(LLMConnectionError, match="网络错误"):
            p.chat(LLMRequest(model_full_id="deepseek/deepseek-chat", messages=[]))


# ============================================================
# TestChatResponseParse — 响应解析失败
# ============================================================


class TestChatResponseParse:
    """响应体非 JSON / 缺字段 / 字段类型错 → LLMResponseError."""

    @respx.mock
    def test_non_json_response_raises_llm_response_error(self) -> None:
        p = OpenAICompatibleProvider(
            provider_type=Provider.DEEPSEEK,
            base_url="https://api.deepseek.com/v1",
            api_key="test-key",
        )
        respx.post("https://api.deepseek.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, text="<html>not json</html>")
        )
        with pytest.raises(LLMResponseError, match="解析失败"):
            p.chat(LLMRequest(model_full_id="deepseek/deepseek-chat", messages=[]))

    @respx.mock
    def test_missing_choices_raises_llm_response_error(self) -> None:
        p = OpenAICompatibleProvider(
            provider_type=Provider.DEEPSEEK,
            base_url="https://api.deepseek.com/v1",
            api_key="test-key",
        )
        respx.post("https://api.deepseek.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={"id": "x"})  # 缺 choices
        )
        with pytest.raises(LLMResponseError, match="解析失败"):
            p.chat(LLMRequest(model_full_id="deepseek/deepseek-chat", messages=[]))

    @respx.mock
    def test_empty_choices_raises_llm_response_error(self) -> None:
        """choices 是空数组 → IndexError → LLMResponseError."""
        p = OpenAICompatibleProvider(
            provider_type=Provider.DEEPSEEK,
            base_url="https://api.deepseek.com/v1",
            api_key="test-key",
        )
        respx.post("https://api.deepseek.com/v1/chat/completions").mock(
            return_value=httpx.Response(200, json={"choices": []})
        )
        with pytest.raises(LLMResponseError, match="解析失败"):
            p.chat(LLMRequest(model_full_id="deepseek/deepseek-chat", messages=[]))


# ============================================================
# TestChatProgrammingError — 编程错误透传
# ============================================================


class TestChatProgrammingError:
    """编程错误(参数错)不包装, 让其自然透传, 由调用方处理.

    D3.3.3 教训: 异常范围要窄化 — ValueError 是编程错误, 不归 LLMError.
    """

    def test_missing_slash_in_full_id_raises_value_error(self) -> None:
        """model_full_id 无 / → ValueError(编程错误, 透传)."""
        p = OpenAICompatibleProvider(
            provider_type=Provider.OPENAI,
            base_url="https://api.openai.com/v1",
            api_key="test-key",
        )
        with pytest.raises(ValueError, match="格式错误"):
            p.chat(LLMRequest(model_full_id="gpt-4.1", messages=[]))  # 无 /

    def test_request_type_error_passes_through(self) -> None:
        """messages 传错类型(TypeError 透传, 不归 LLMError)."""
        p = OpenAICompatibleProvider(
            provider_type=Provider.OPENAI,
            base_url="https://api.openai.com/v1",
            api_key="test-key",
        )
        # messages 传 None → TypeError 在 list() 转换时抛, 透传
        with pytest.raises(TypeError):
            p.chat(LLMRequest(model_full_id="openai/gpt-4.1", messages=None))  # type: ignore[arg-type]


# ============================================================
# TestChatIntegrationWithRouter — router 端到端
# ============================================================


class TestChatIntegrationWithRouter:
    """验证 router.route() 触发 chat() 真实异常时, 正确走 fallback."""

    @respx.mock
    def test_router_falls_back_on_401(self) -> None:
        """primary 401 → 走 secondary(端到端)."""
        from my_ai_employee.ai.capability import TaskType
        from my_ai_employee.ai.router import LLMRouter

        # primary 401
        respx.post("https://api.deepseek.com/v1/chat/completions").mock(
            return_value=httpx.Response(401, text='{"error": "unauthorized"}')
        )
        # secondary 成功
        respx.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions").mock(
            return_value=httpx.Response(
                200,
                json=_mock_openai_response("from qwen", input_tokens=10, output_tokens=2),
            )
        )

        router = LLMRouter()
        response = router.route(
            task_type=TaskType.CLASSIFY,
            messages=[{"role": "user", "content": "test"}],
        )
        assert response.content == "from qwen"
