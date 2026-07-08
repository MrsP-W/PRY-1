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
from typing import Any

import httpx
import pytest
import respx

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
    LLMAPIError,
    LLMError,
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

    def test_draft_chain_prefers_qwen_for_bare_json_contract(self) -> None:
        """D13.x P0: 草稿链主选 Qwen,避免 MiniMax <think> 破坏裸 JSON 契约."""
        chain = get_chain(TaskType.DRAFT)
        assert chain.primary == "qwen/qwen3-max"
        assert chain.secondary == "deepseek/deepseek-chat"
        assert chain.tertiary == "minimax/MiniMax-M3"

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

    def test_openai_compatible_chat_http_error(self) -> None:
        """D4.1.1 阻塞修复: 真实网络/无效 API key 测试改 respx mock, 不依赖网络.

        旧版本: 真实发 HTTP → 401 或 connection error, CI/离线环境会抖.
        新版本: respx 拦截 httpx.post, 模拟 401 → 验证 LLMAPIError 抛错.
        """
        p = OpenAICompatibleProvider(
            provider_type=Provider.DEEPSEEK,
            base_url="https://api.deepseek.com/v1",
            api_key="invalid-key",
        )
        with respx.mock:
            respx.post("https://api.deepseek.com/v1/chat/completions").mock(
                return_value=httpx.Response(401, text='{"error": "unauthorized"}')
            )
            with pytest.raises(LLMError) as exc_info:
                p.chat(
                    LLMRequest(
                        model_full_id="deepseek/deepseek-chat",
                        messages=[{"role": "user", "content": "ping"}],
                    )
                )
        # 401 → LLMAPIError
        assert isinstance(exc_info.value, LLMAPIError)
        assert exc_info.value.status_code == 401


# ============================================================
# Router 决策(用 mock chat)
# ============================================================


class _MockProviderResult:
    """mock provider 返回结果的可控对象."""

    def __init__(self, responses: dict[str, LLMResponse | Exception]) -> None:
        self.responses = responses
        self.calls: list[LLMRequest] = []


def _make_mock_chat(mock: _MockProviderResult) -> Any:
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

    @pytest.fixture(autouse=True)
    def _ensure_deepseek_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """撞坑 #86 修复后: router 在 chat() 前会做 healthcheck 门控,
        空 api_key 会被跳过 — 所以 mock deepseek 的测试必须先确保 env 有 key."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key-fixture")

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
        """主选业务异常 → 走 secondary."""
        mock = _MockProviderResult(
            {
                "deepseek/deepseek-chat": LLMError("deepseek down"),
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
        """全链业务异常 → LLMAllFallbacksError(D4.6 v1.0.1 P1-1).

        v1.0 旧实现:抛 RuntimeError(不属 LLMError,业务方 except 不到)
        v1.0.1 修复:抛 LLMAllFallbacksError(LLMError 子类,业务方 except LLMError 覆盖)
        """
        from my_ai_employee.ai.providers import LLMAllFallbacksError

        mock = _MockProviderResult(
            {
                "deepseek/deepseek-chat": LLMError("p1 fail"),
                "qwen/qwen3-max": LLMError("p2 fail"),
                "minimax/MiniMax-M3": LLMError("p3 fail"),
            }
        )
        monkeypatch.setattr(OpenAICompatibleProvider, "chat", _make_mock_chat(mock))

        router = LLMRouter()
        with pytest.raises(LLMAllFallbacksError, match="所有 fallback 都失败"):
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
        """统计: 主选业务异常 + 备选成功."""
        mock = _MockProviderResult(
            {
                "deepseek/deepseek-chat": LLMError("p1 fail"),
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


# ============================================================
# Router 异常收窄(锁 D3.3.3 教训: 编程错误透传)
# ============================================================


class TestRouterExceptionNarrowing:
    """D4.1.1 阻塞修复: router 只 catch LLMError, 编程错误直接透传.

    教训来源: D3.3.3 "异常范围要窄化到真要处理的类型".
    """

    @pytest.fixture(autouse=True)
    def _ensure_deepseek_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """撞坑 #86 修复后:同 TestRouterDecision,确保 deepseek 走 healthcheck 门."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key-fixture")

    def test_programming_error_passes_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ValueError(编程错误)从 chat() 抛出 → router 不 catch, 直接透传.

        反向验证: 不再变成 RuntimeError("所有 fallback 都失败").
        """
        mock = _MockProviderResult(
            {
                "deepseek/deepseek-chat": ValueError("model_full_id 格式错误"),
                "qwen/qwen3-max": LLMResponse(  # secondary 备好也不该用
                    content="should not reach",
                    model_full_id="qwen/qwen3-max",
                    input_tokens=10,
                    output_tokens=5,
                    latency_ms=100,
                ),
            }
        )
        monkeypatch.setattr(OpenAICompatibleProvider, "chat", _make_mock_chat(mock))

        router = LLMRouter()
        with pytest.raises(ValueError, match="格式错误"):
            router.route(
                task_type=TaskType.CLASSIFY,
                messages=[{"role": "user", "content": "test"}],
            )
        # 关键: 只调了 primary, secondary 没被触发
        assert len(mock.calls) == 1
        assert mock.calls[0].model_full_id == "deepseek/deepseek-chat"

    def test_type_error_passes_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TypeError 同样透传(双保险)."""
        mock = _MockProviderResult(
            {
                "deepseek/deepseek-chat": TypeError("messages 类型错"),
            }
        )
        monkeypatch.setattr(OpenAICompatibleProvider, "chat", _make_mock_chat(mock))

        router = LLMRouter()
        with pytest.raises(TypeError, match="messages"):
            router.route(
                task_type=TaskType.CLASSIFY,
                messages=[{"role": "user", "content": "test"}],
            )
        assert len(mock.calls) == 1

    def test_llm_error_subclass_triggers_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """LLMError 子类(LLMTimeoutError / LLMConnectionError / LLMAPIError / LLMResponseError)
        都被 router 当业务异常处理, 走 fallback 链.

        这是 D3.3.3 "窄化但不能漏" 的对偶断言 — 业务异常必须被 catch.
        """
        from my_ai_employee.ai.providers import (
            LLMAPIError,
            LLMConnectionError,
            LLMResponseError,
            LLMTimeoutError,
        )

        for business_exc in (
            LLMTimeoutError("timeout"),
            LLMConnectionError("conn fail"),
            LLMAPIError("api err", status_code=500, body="x"),
            LLMResponseError("parse fail"),
        ):
            mock = _MockProviderResult(
                {
                    "deepseek/deepseek-chat": business_exc,
                    "qwen/qwen3-max": LLMResponse(
                        content="recovered",
                        model_full_id="qwen/qwen3-max",
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
            assert response.content == "recovered", f"{type(business_exc).__name__} 没走 fallback"


# ============================================================
# Router 配置完整性门控(撞坑 #86 · 2026-07-08 实战触发)
# ============================================================


class TestRouterHealthcheckGate:
    """撞坑 #86: provider 配置不完整(空 api_key / 空 base_url)时,
    router 不调 chat(),直接 skip 该档并走 fallback.

    触发场景:DEEPSEEK_API_KEY 未设置 → _resolve_api_key 返回 ""
    → provider.healthcheck() 返回 False → router 跳过 deepseek 走 qwen,
    不再产生 "Illegal header value b'Bearer '" 噪声 + 不熔断(配置问题非网络问题).
    """

    def test_empty_deepseek_key_skips_primary(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """DEEPSEEK_API_KEY 未设置 → primary(deepseek)healthcheck=False → 跳过,secondary(qwen)成功."""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        # 留 OPENAI_API_KEY(避免 _resolve_api_key 兜底让 deepseek 又配上 — 实际不会,
        # 因为 _resolve_api_key 优先用 DEEPSEEK_API_KEY,空字符串 '' 仍会触发 False 分支)
        # 实际上 _resolve_api_key: if override: → 用 override
        #                       else: env_name = DEEPSEEK_API_KEY → os.environ.get(DEEPSEEK_API_KEY, "") or OPENAI_API_KEY
        # monkeypatch.delenv 后 get 返回 "",短路 or → 走到 OPENAI_API_KEY
        # 所以要同时 unset OPENAI_API_KEY 才能让 deepseek 真的"空"
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        mock = _MockProviderResult(
            {
                # deepseek 不应被调,因为 healthcheck False
                "deepseek/deepseek-chat": LLMResponse(
                    content="should not reach",
                    model_full_id="deepseek/deepseek-chat",
                    input_tokens=10,
                    output_tokens=5,
                    latency_ms=100,
                ),
                "qwen/qwen3-max": LLMResponse(
                    content="classify result from qwen",
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
        assert response.content == "classify result from qwen"
        # 关键: 只调了 qwen,deepseek 因 healthcheck=False 被跳过
        assert len(mock.calls) == 1
        assert mock.calls[0].model_full_id == "qwen/qwen3-max"

    def test_empty_key_does_not_trip_breaker(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """配置缺失不计入熔断(配置问题非网络问题) — 撞坑 #86 关键设计."""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        mock = _MockProviderResult(
            {
                "qwen/qwen3-max": LLMResponse(
                    content="qwen ok",
                    model_full_id="qwen/qwen3-max",
                    input_tokens=10,
                    output_tokens=5,
                    latency_ms=100,
                ),
            }
        )
        monkeypatch.setattr(OpenAICompatibleProvider, "chat", _make_mock_chat(mock))

        router = LLMRouter()
        for _ in range(5):  # 多次路由
            router.route(
                task_type=TaskType.CLASSIFY,
                messages=[{"role": "user", "content": "test"}],
            )
        # deepseek 熔断器不应被打开(配置问题不计入失败计数)
        assert not router._breaker("deepseek/deepseek-chat").is_open()
        assert router._breaker("deepseek/deepseek-chat").failure_count == 0

    def test_empty_key_all_tiers_config_missing_raises(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """全链都缺 api_key → LLMAllFallbacksError(行为不变)."""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)  # qwen 实际 env 名
        monkeypatch.delenv("QWEN_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GLM_API_KEY", raising=False)
        monkeypatch.delenv("TENCENT_API_KEY", raising=False)

        from my_ai_employee.ai.providers import LLMAllFallbacksError

        router = LLMRouter()
        with pytest.raises(LLMAllFallbacksError, match="所有 fallback 都失败"):
            router.route(
                task_type=TaskType.CLASSIFY,
                messages=[{"role": "user", "content": "test"}],
            )

    def test_valid_key_still_uses_primary(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """DEEPSEEK_API_KEY 存在 → primary 仍被调(不破坏正常路径)."""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key-not-empty")

        mock = _MockProviderResult(
            {
                "deepseek/deepseek-chat": LLMResponse(
                    content="classify from deepseek",
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
        assert response.content == "classify from deepseek"
        assert len(mock.calls) == 1
        assert mock.calls[0].model_full_id == "deepseek/deepseek-chat"
