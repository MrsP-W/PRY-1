"""LLM Capability Registry — D4.1 核心数据层.

参考 claw-code docs/MODEL_COMPATIBILITY.md 架构原则:
  - 命名约定: provider/model (如 "deepseek/deepseek-chat")
  - 不同模型族对参数/字段的处理不同
  - Reasoning 模型(OpenAI o1/o3/o4/Qwen qwq/Qwen3 thinking)剥离 temperature/top_p
  - GPT-5 用 max_completion_tokens 而非 max_tokens
  - Kimi 排除 is_error 字段
  - 字段检测: model name → 能力函数(基于名称的检测)

v2 晨报钩子(6/8 11:12+, MiniMax M3 冲进 OpenRouter 前 3):
  - 国内模型优先(DeepSeek / Qwen / MiniMax M3 / 腾讯混元 / 智谱)
  - capability registry 数据驱动: 加新模型只改此处一行
  - 不照搬 claw-code Rust 代码, 学架构模式不抄代码

D4.1.0 范围: registry 数据 + lookup 函数, **不调 HTTP**.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Provider(StrEnum):
    """LLM Provider 枚举.

    Python 3.11+ StrEnum 原生支持 str 行为(序列化/比较/JSON).
    """

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    DEEPSEEK = "deepseek"  # v2 晨报: 连续 3 周第一
    QWEN = "qwen"  # 通义千问 (DashScope 兼容 OpenAI)
    GLM = "glm"  # 智谱 (BigModel)
    MINIMAX = "minimax"  # v2 晨报: 冲进前三
    TENCENT = "tencent"  # v2 晨报: 腾讯混元
    OLLAMA = "ollama"  # 本地(参考 claw-code local-openai-compatible-providers.md)
    UNKNOWN = "unknown"


class TaskType(StrEnum):
    """6 个核心服务的任务类型(week1-mvp.md D4.1-D4.7.4 范围)."""

    CLASSIFY = "classify"  # 邮件 5 类分类 - 短文本 - 准确率敏感
    DRAFT = "draft"  # 草稿生成 - 中长文本 - 中文质量敏感
    ANALYZE = "analyze"  # 财务异常检测 - 结构化输出 - 推理深度
    STRUCTURE = "structure"  # 笔记结构化 - 中等长度 - 多模态
    SUMMARIZE = "summarize"  # 摘要 - 通用
    # D4.7.4 起始新增(2026-06-10): 草稿审阅 - 规则 + LLM 联合审阅 - 准确率敏感
    REVIEW = "review"


@dataclass(frozen=True)
class ModelCapability:
    """单模型能力描述(数据驱动, 参考 claw-code MODEL_COMPATIBILITY.md).

    Attributes:
        provider: provider 枚举
        model_id: 模型短名(provider 之外的标识)
        context_window: token 上限
        supports_chinese: 是否原生支持中文
        supports_vision: 是否支持多模态(图片输入)
        is_reasoning: 是否推理模型(强制 temperature=1.0)
        is_local: 是否本地模型(Ollama / vLLM)
        pricing_per_mtok: 单价(元/百万 token, 仅作参考, 实际看 provider 计费)
        priority: 路由优先级(越小越优先, 用于"默认路由"决策)
        notes: 备注(给运维/调试看, 不参与路由决策)
    """

    provider: Provider
    model_id: str
    context_window: int
    supports_chinese: bool
    supports_vision: bool
    is_reasoning: bool = False
    is_local: bool = False
    pricing_per_mtok: float = 0.0
    priority: int = 100
    notes: str = ""

    @property
    def full_id(self) -> str:
        """provider/model 格式(参考 claw-code --model "openai/gpt-4.1-mini" 范式)."""
        return f"{self.provider.value}/{self.model_id}"


# === Capability Registry ===
# 数据驱动: 后续加新模型只需在此处加一行
# v2 晨报钩子: 国内模型优先 (priority 越小越优先)

CAPABILITY_REGISTRY: dict[str, ModelCapability] = {
    # ----- 国内: 默认路由 -----
    "deepseek/deepseek-chat": ModelCapability(
        provider=Provider.DEEPSEEK,
        model_id="deepseek-chat",
        context_window=128_000,
        supports_chinese=True,
        supports_vision=False,
        pricing_per_mtok=0.5,
        priority=10,
        notes="v2 晨报: DeepSeek 连续 3 周第一, 默认路由",
    ),
    "deepseek/deepseek-reasoner": ModelCapability(
        provider=Provider.DEEPSEEK,
        model_id="deepseek-reasoner",
        context_window=128_000,
        supports_chinese=True,
        supports_vision=False,
        is_reasoning=True,
        pricing_per_mtok=2.0,
        priority=20,
        notes="DeepSeek-R1 推理模型, 智能推理场景",
    ),
    "minimax/MiniMax-M3": ModelCapability(
        provider=Provider.MINIMAX,
        model_id="MiniMax-M3",
        context_window=200_000,
        supports_chinese=True,
        supports_vision=False,
        pricing_per_mtok=1.0,
        priority=15,
        notes="v2 晨报: MiniMax M3 首次上榜冲进 OpenRouter 前 3",
    ),
    "qwen/qwen3-max": ModelCapability(
        provider=Provider.QWEN,
        model_id="qwen3-max",
        context_window=1_000_000,
        supports_chinese=True,
        supports_vision=True,
        pricing_per_mtok=2.0,
        priority=30,
        notes="通义千问 Qwen3-Max, 1M context + 多模态",
    ),
    "tencent/hunyuan-pro": ModelCapability(
        provider=Provider.TENCENT,
        model_id="hunyuan-pro",
        context_window=128_000,
        supports_chinese=True,
        supports_vision=True,
        pricing_per_mtok=1.2,
        priority=40,
        notes="v2 晨报: 腾讯混元 Hy3, 多模态场景",
    ),
    "glm/glm-4-plus": ModelCapability(
        provider=Provider.GLM,
        model_id="glm-4-plus",
        context_window=128_000,
        supports_chinese=True,
        supports_vision=False,
        pricing_per_mtok=1.0,
        priority=50,
        notes="智谱 GLM-4-Plus, 备选",
    ),
    # ----- 国外: 兜底 -----
    "anthropic/claude-sonnet-4-6": ModelCapability(
        provider=Provider.ANTHROPIC,
        model_id="claude-sonnet-4-6",
        context_window=200_000,
        supports_chinese=True,
        supports_vision=True,
        pricing_per_mtok=30.0,
        priority=90,
        notes="Claude Sonnet 4.6 兜底(成本高, 仅作 fallback)",
    ),
    "openai/gpt-4.1": ModelCapability(
        provider=Provider.OPENAI,
        model_id="gpt-4.1",
        context_window=1_000_000,
        supports_chinese=False,
        supports_vision=True,
        pricing_per_mtok=30.0,
        priority=95,
        notes="OpenAI GPT-4.1 兜底(1M context, 成本高)",
    ),
    # ----- 本地 -----
    "ollama/llama3.2": ModelCapability(
        provider=Provider.OLLAMA,
        model_id="llama3.2",
        context_window=128_000,
        supports_chinese=False,
        supports_vision=False,
        is_local=True,
        pricing_per_mtok=0.0,
        priority=70,
        notes="本地 Ollama, 离线/隐私场景",
    ),
}


def get_capability(full_id: str) -> ModelCapability | None:
    """按 provider/model 格式查找能力.

    命中: 返回完整 capability.
    未命中但 provider 已知: 返回降级默认 capability(provider + 保守 context).
    完全未知: 返回 None(调用方应跳过).
    """
    if full_id in CAPABILITY_REGISTRY:
        return CAPABILITY_REGISTRY[full_id]
    if "/" in full_id:
        provider_str = full_id.split("/", 1)[0]
        try:
            provider = Provider(provider_str)
        except ValueError:
            return None
        return ModelCapability(
            provider=provider,
            model_id=full_id.split("/", 1)[1],
            context_window=32_000,
            supports_chinese=False,
            supports_vision=False,
            priority=100,
            notes="未知模型(降级默认能力, 后续应补充到 registry)",
        )
    return None


def list_models(task_type: TaskType | None = None) -> list[ModelCapability]:
    """列出所有模型(按 priority 升序).

    task_type 预留: 后续可按任务类型推荐 provider(本 D-step 不实现).
    """
    models = sorted(CAPABILITY_REGISTRY.values(), key=lambda m: m.priority)
    return models
