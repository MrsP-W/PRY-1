"""D4.1 — LLM 路由层单元测试(mock, 不调 HTTP).

覆盖（[docs/week1-mvp.md §D4.1 + 6/8 v2 晨报钩子 国内模型优先]）：

Capability Registry（capability.py）
    - v2 钩子: 6 个国内 provider 都在 registry(deepseek/qwen/M3/混元/GLM)
    - get_capability 命中/未知/降级
    - list_models 按 priority 升序(默认 deepseek)

Fallback Chain（fallback.py）
    - 所有 TaskType 都有链配置
    - 主选/备选/兜底全异构(参考 v2 设计)
    - CircuitBreaker 3 次失败熔断 / 成功重置

Provider 抽象（providers.py）
    - get_provider 路由: deepseek → DEEPSEEK base_url
    - get_provider 路由: ollama → OLLAMA_HOST 环境变量
    - get_provider 路由: 未知 provider → UNKNOWN 占位
    - OpenAICompatibleProvider.healthcheck 检查配置完整性

Router 决策（router.py）
    - primary 成功: 不走 fallback, 统计正确
    - primary 失败 → 走 secondary
    - 全链失败 → RuntimeError
    - reasoning 模型强制 temperature=1.0
    - 熔断的 provider 跳过
    - 单例路由器 + reset_breakers
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 让 tests/ 目录能 import 兄弟包(参考 tests/connectors/test_imap.py 风格)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from my_ai_employee.ai.capability import (  # noqa: E402
    CAPABILITY_REGISTRY,
    Provider,
    TaskType,
    get_capability,
    list_models,
)
from my_ai_employee.ai.fallback import (  # noqa: E402
    FALLBACK_CHAINS,
    CircuitBreaker,
    get_chain,
)
from my_ai_employee.ai.providers import (  # noqa: E402
    LLMRequest,
    LLMResponse,
    OpenAICompatibleProvider,
    get_provider,
)
from my_ai_employee.ai.router import (  # noqa: E402
    LLMRouter,
    get_router,
)

# ============================================================
# Capability Registry
# ============================================================


class TestCapabilityRegistry:
    """capability.py 单元测试."""

    def test_v2_priority_models_present(self) -> None:
        """v2 晨报钩子: 6 个国内 provider 都在 registry."""
        # 这些是 6/8 v2 晨报钩子要求"国内模型优先"的最小集
        for full_id in (
            "deepseek/deepseek-chat",
            "deepseek/deepseek-reasoner",
            "minimax/MiniMax-M3",
            "qwen/qwen3-max",
            "tencent/hunyuan-pro",
            "glm/glm-4-plus",
        ):
            assert full_id in CAPABILITY_REGISTRY, f"缺 {full_id}"

    def test_get_capability_known(self) -> None:
        """get_capability 命中: 返回完整 capability."""
        cap = get_capability("deepseek/deepseek-chat")
        assert cap is not None
        assert cap.provider == Provider.DEEPSEEK
        assert cap.model_id == "deepseek-chat"
        assert cap.priority == 10  # 最低(最优先)
        assert cap.supports_chinese is True

    def test_get_capability_unknown_provider(self) -> None:
        """未知 provider: 返回 None."""
        cap = get_capability("foobar/baz")
        assert cap is None

    def test_get_capability_degraded(self) -> None:
        """已知 provider 但模型未在 registry: 降级默认 capability."""
        cap = get_capability("deepseek/unknown-future-model")
        assert cap is not None
        assert cap.provider == Provider.DEEPSEEK
        assert cap.priority == 100  # 降级最低优先
        assert "未知模型" in cap.notes

    def test_list_models_sorted_by_priority(self) -> None:
        """list_models 按 priority 升序."""
        models = list_models()
        priorities = [m.priority for m in models]
        assert priorities == sorted(priorities)
        # 第一名应该是 deepseek-chat(priority=10)
        assert models[0].full_id == "deepseek/deepseek-chat"

    def test_full_id_format(self) -> None:
        """full_id 格式: provider/model."""
        cap = get_capability("qwen/qwen3-max")
        assert cap is not None
        assert cap.full_id == "qwen/qwen3-max"

    def test_reasoning_model_flag(self) -> None:
        """推理模型标记(影响 router 强制 temperature=1.0)."""
        cap = get_capability("deepseek/deepseek-reasoner")
        assert cap is not None
        assert cap.is_reasoning is True

        cap_normal = get_capability("deepseek/deepseek-chat")
        assert cap_normal is not None
        assert cap_normal.is_reasoning is False


# ============================================================
# Fallback Chain
# ============================================================


class TestFallbackChain:
    """fallback.py 单元测试."""

    def test_all_task_types_have_chains(self) -> None:
        """所有 TaskType 都有链配置."""
        for task in TaskType:
            assert task in FALLBACK_CHAINS, f"缺 {task} 配置"
            chain = FALLBACK_CHAINS[task]
            assert chain.primary
            assert chain.secondary
            assert chain.tertiary

    def test_chain_tiers_distinct(self) -> None:
        """主选/备选/兜底全异构(v2 设计: 异构优先, 避免同 provider 雪崩)."""
        for task, chain in FALLBACK_CHAINS.items():
            assert chain.primary != chain.secondary, (
                f"{task}: primary == secondary ({chain.primary})"
            )
            assert chain.secondary != chain.tertiary, (
                f"{task}: secondary == tertiary ({chain.secondary})"
            )
            assert chain.primary != chain.tertiary, f"{task}: primary == tertiary ({chain.primary})"

    def test_get_chain_returns_config(self) -> None:
        """get_chain 返回配置."""
        chain = get_chain(TaskType.CLASSIFY)
        assert chain.primary == "deepseek/deepseek-chat"

    def test_circuit_breaker_opens_after_3_failures(self) -> None:
        """CircuitBreaker: 3 次失败后熔断."""
        cb = CircuitBreaker()
        assert not cb.is_open()
        cb.record_failure()
        cb.record_failure()
        assert not cb.is_open()
        cb.record_failure()
        assert cb.is_open()

    def test_circuit_breaker_resets_on_success(self) -> None:
        """CircuitBreaker: 成功重置计数."""
        cb = CircuitBreaker()
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert not cb.is_open()
        assert cb.failure_count == 0

    def test_circuit_breaker_cooldown_recovery(self) -> None:
        """CircuitBreaker: 冷却期过后自动重置."""
        import time as _t

        cb = CircuitBreaker(cooldown_seconds=0.1)  # 0.1s 冷却
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open()  # 刚熔断
        _t.sleep(0.2)  # 0.2s 后冷却期过
        assert not cb.is_open()  # 自动重置
        assert cb.failure_count == 0


# ============================================================
# Provider 抽象
# ============================================================


class TestProviderFactory:
    """providers.py 单元测试."""

    def test_get_provider_deepseek(self) -> None:
        """get_provider: deepseek → DEEPSEEK base_url."""
        p = get_provider("deepseek/deepseek-chat")
        assert p.provider_type == Provider.DEEPSEEK
        assert "deepseek.com" in p.base_url

    def test_get_provider_qwen(self) -> None:
        """get_provider: qwen → DashScope 兼容端点."""
        p = get_provider("qwen/qwen3-max")
        assert p.provider_type == Provider.QWEN
        assert "dashscope" in p.base_url

    def test_get_provider_ollama_uses_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_provider: ollama → OLLAMA_HOST 环境变量."""
        monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9999")
        p = get_provider("ollama/llama3.2")
        assert p.provider_type == Provider.OLLAMA
        assert p.base_url == "http://127.0.0.1:9999/v1"

    def test_get_provider_unknown_full_id(self) -> None:
        """get_provider: 未知 provider → UNKNOWN 占位."""
        p = get_provider("foobar/baz")
        assert p.provider_type == Provider.UNKNOWN

    def test_get_provider_no_slash(self) -> None:
        """get_provider: 没有 / 时默认 openai."""
        p = get_provider("gpt-4.1")  # 无 slash
        assert p.provider_type == Provider.OPENAI

    def test_openai_compatible_healthcheck(self) -> None:
        """OpenAICompatibleProvider.healthcheck: 配置完整 → True."""
        p = OpenAICompatibleProvider(
            provider_type=Provider.DEEPSEEK,
            base_url="https://api.deepseek.com/v1",
            api_key="test-key",
        )
        assert p.healthcheck() is True

    def test_openai_compatible_healthcheck_missing_key(self) -> None:
        """D4.1.1: healthcheck 要求 base_url + api_key 都配置完整."""
        p = OpenAICompatibleProvider(
            provider_type=Provider.DEEPSEEK,
            base_url="https://api.deepseek.com/v1",
            api_key="",  # 无 Key
        )
        assert p.healthcheck() is False

    def test_openai_compatible_chat_http_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """D4.1.1 边界: D4.1.0 的 NotImplementedError 测试已废弃, 改为验证真实 HTTP 错误处理.

        真实场景: 无 API Key → DeepSeek 返回 401 → LLMAPIError(由 router 触发 fallback).
        此测试只验证抛错行为, 不验证 fallback 决策(fallback 决策在 test_router.py).
        """
        p = OpenAICompatibleProvider(
            provider_type=Provider.DEEPSEEK,
            base_url="https://api.deepseek.com/v1",
            api_key="invalid-key",  # 故意给错, 让真实 DeepSeek 返回 401
        )
        request = LLMRequest(
            model_full_id="deepseek/deepseek-chat",
            messages=[{"role": "user", "content": "ping"}],
        )
        # 用 monkeypatch 限制超时(避免测试卡住)
        monkeypatch.setattr(p, "_timeout", 5.0)
        # 此测试依赖网络可达(可达则 401, 不可达则 LLMConnectionError)
        # 两种都接受: 都属于"业务异常 → 应 fallback" 的范畴
        from my_ai_employee.ai.providers import LLMError

        with pytest.raises(LLMError):
            p.chat(request)


# ============================================================
# Router 决策(用 mock chat)
# ============================================================


class _MockProviderResult:
    """mock provider 返回结果的可控对象."""

    def __init__(self, responses: dict[str, LLMResponse | Exception]) -> None:
        self.responses = responses
        self.calls: list[LLMRequest] = []


def _make_mock_chat(mock: _MockProviderResult):
    """构造一个可注入的 mock chat 函数(闭包)."""

    def mock_chat(self: OpenAICompatibleProvider, request: LLMRequest) -> LLMResponse:
        mock.calls.append(request)
        result = mock.responses.get(request.model_full_id)
        if isinstance(result, Exception):
            raise result
        if result is None:
            raise RuntimeError(f"mock 未配置 {request.model_full_id}")
        return result

    return mock_chat


class TestRouterDecision:
    """router.py 单元测试(mock chat, 不发 HTTP)."""

    def test_primary_success_no_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """主选成功: 不走 fallback, 只调 1 次."""
        mock = _MockProviderResult(
            {
                "deepseek/deepseek-chat": LLMResponse(
                    content="classify result",
                    model_full_id="deepseek/deepseek-chat",
                    input_tokens=10,
                    output_tokens=5,
                    latency_ms=100,
                ),
            }
        )
        monkeypatch.setattr(OpenAICompatibleProvider, "chat", _make_mock_chat(mock))

        router = LLMRouter()
        response = router.route(
            task_type=TaskType.CLASSIFY,
            messages=[{"role": "user", "content": "test"}],
        )
        assert response.content == "classify result"
        assert len(mock.calls) == 1
        assert mock.calls[0].model_full_id == "deepseek/deepseek-chat"

    def test_primary_fails_falls_to_secondary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """主选失败 → 走 secondary."""
        mock = _MockProviderResult(
            {
                "deepseek/deepseek-chat": RuntimeError("deepseek down"),
                "qwen/qwen3-max": LLMResponse(
                    content="classify result (secondary)",
                    model_full_id="qwen/qwen3-max",
                    input_tokens=10,
                    output_tokens=5,
                    latency_ms=200,
                ),
            }
        )
        monkeypatch.setattr(OpenAICompatibleProvider, "chat", _make_mock_chat(mock))

        router = LLMRouter()
        response = router.route(
            task_type=TaskType.CLASSIFY,
            messages=[{"role": "user", "content": "test"}],
        )
        assert "secondary" in response.content
        assert len(mock.calls) == 2
        assert mock.calls[0].model_full_id == "deepseek/deepseek-chat"
        assert mock.calls[1].model_full_id == "qwen/qwen3-max"

    def test_all_fail_raises_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """全链失败 → RuntimeError(包含任务类型和 last_error)."""
        mock = _MockProviderResult(
            {
                "deepseek/deepseek-chat": RuntimeError("p1 fail"),
                "qwen/qwen3-max": RuntimeError("p2 fail"),
                "minimax/MiniMax-M3": RuntimeError("p3 fail"),
            }
        )
        monkeypatch.setattr(OpenAICompatibleProvider, "chat", _make_mock_chat(mock))

        router = LLMRouter()
        with pytest.raises(RuntimeError, match="所有 fallback 都失败"):
            router.route(
                task_type=TaskType.CLASSIFY,
                messages=[{"role": "user", "content": "test"}],
            )
        # 3 个 provider 都试了
        assert len(mock.calls) == 3

    def test_reasoning_model_strips_temperature(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """推理模型 → 强制 temperature=1.0(用户传 0.3 → 实际 1.0)."""
        mock = _MockProviderResult(
            {
                "deepseek/deepseek-reasoner": LLMResponse(
                    content="analyze result",
                    model_full_id="deepseek/deepseek-reasoner",
                    input_tokens=20,
                    output_tokens=10,
                    latency_ms=500,
                ),
            }
        )
        monkeypatch.setattr(OpenAICompatibleProvider, "chat", _make_mock_chat(mock))

        router = LLMRouter()
        router.route(
            task_type=TaskType.ANALYZE,  # primary = reasoning
            messages=[{"role": "user", "content": "analyze"}],
            temperature=0.3,
        )
        # 推理模型: temperature 被强制 1.0
        assert mock.calls[0].temperature == 1.0

    def test_non_reasoning_keeps_temperature(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """非推理模型 → 保持用户传的 temperature."""
        mock = _MockProviderResult(
            {
                "deepseek/deepseek-chat": LLMResponse(
                    content="ok",
                    model_full_id="deepseek/deepseek-chat",
                    input_tokens=10,
                    output_tokens=5,
                    latency_ms=100,
                ),
            }
        )
        monkeypatch.setattr(OpenAICompatibleProvider, "chat", _make_mock_chat(mock))

        router = LLMRouter()
        router.route(
            task_type=TaskType.CLASSIFY,
            messages=[{"role": "user", "content": "test"}],
            temperature=0.7,
        )
        assert mock.calls[0].temperature == 0.7

    def test_circuit_breaker_skips_open_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """熔断的 provider → 跳过, 直接走 secondary."""
        router = LLMRouter()
        # 强制主选熔断
        for _ in range(3):
            router._breaker("deepseek/deepseek-chat").record_failure()
        assert router._breaker("deepseek/deepseek-chat").is_open()

        mock = _MockProviderResult(
            {
                "qwen/qwen3-max": LLMResponse(
                    content="secondary success",
                    model_full_id="qwen/qwen3-max",
                    input_tokens=10,
                    output_tokens=5,
                    latency_ms=200,
                ),
            }
        )
        monkeypatch.setattr(OpenAICompatibleProvider, "chat", _make_mock_chat(mock))

        response = router.route(
            task_type=TaskType.CLASSIFY,
            messages=[{"role": "user", "content": "test"}],
        )
        # 主选跳过(熔断), 直接 secondary
        assert response.content == "secondary success"
        assert len(mock.calls) == 1
        assert mock.calls[0].model_full_id == "qwen/qwen3-max"

    def test_stats_tracking(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """统计字段正确累加."""
        mock = _MockProviderResult(
            {
                "deepseek/deepseek-chat": LLMResponse(
                    content="ok",
                    model_full_id="deepseek/deepseek-chat",
                    input_tokens=10,
                    output_tokens=5,
                    latency_ms=100,
                ),
            }
        )
        monkeypatch.setattr(OpenAICompatibleProvider, "chat", _make_mock_chat(mock))

        router = LLMRouter()
        for _ in range(3):
            router.route(
                task_type=TaskType.CLASSIFY,
                messages=[{"role": "user", "content": "test"}],
            )

        stats = router.stats()
        assert stats["primary_attempts"] == 3
        assert stats["primary_successes"] == 3
        assert stats["fallback_attempts"] == 0
        assert stats["failures"] == 0
        assert stats["primary_success_rate"] == 1.0

    def test_stats_tracking_with_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """统计: 主选失败 1 次 + 备选成功 1 次."""
        mock = _MockProviderResult(
            {
                "deepseek/deepseek-chat": RuntimeError("p1 fail"),
                "qwen/qwen3-max": LLMResponse(
                    content="ok",
                    model_full_id="qwen/qwen3-max",
                    input_tokens=10,
                    output_tokens=5,
                    latency_ms=200,
                ),
            }
        )
        monkeypatch.setattr(OpenAICompatibleProvider, "chat", _make_mock_chat(mock))

        router = LLMRouter()
        response = router.route(
            task_type=TaskType.CLASSIFY,
            messages=[{"role": "user", "content": "test"}],
        )
        assert response.content == "ok"
        stats = router.stats()
        assert stats["primary_attempts"] == 1
        assert stats["primary_successes"] == 0
        assert stats["fallback_attempts"] == 1
        assert stats["fallback_successes"] == 1
        assert stats["failures"] == 0
        assert stats["primary_success_rate"] == 0.0

    def test_singleton_returns_same_instance(self) -> None:
        """get_router() 单例."""
        r1 = get_router()
        r2 = get_router()
        assert r1 is r2

    def test_reset_breakers(self) -> None:
        """reset_breakers 重置所有熔断器."""
        router = LLMRouter()
        for _ in range(3):
            router._breaker("deepseek/deepseek-chat").record_failure()
        assert router._breaker("deepseek/deepseek-chat").is_open()
        router.reset_breakers()
        assert not router._breaker("deepseek/deepseek-chat").is_open()
