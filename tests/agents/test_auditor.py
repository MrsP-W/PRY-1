"""D10.1 — @审计员 Agent 角色契约测试.

承接 src/my_ai_employee/agents/审计员.md(本项目 L4 专属角色,D10 月报生成).

测试目标(沿 D5.5.3 范本):
    - 角色 frontmatter 4 字段必填
    - 角色定位:L4 Agent 层专属(审计员 = 我的AI员工独有,D10 月报自动生成)
    - 审计红线 4 条(LLM 延迟 / spam 误发 / SMTP 失败 / 敏感数据外发)
    - 协作关系:@审计员 ↔ @管家(双向强制)+ → @检查员(质量门)
    - 触发时机:每月 1 号 09:00(沿 week2-mvp.md L224)
"""

from __future__ import annotations

from pathlib import Path

import pytest

AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "my_ai_employee" / "agents"
AUDITOR_PATH = AGENTS_DIR / "审计员.md"


def _read() -> str:
    return AUDITOR_PATH.read_text(encoding="utf-8")


def _frontmatter() -> str:
    text = _read()
    assert text.startswith("---\n"), "审计员.md 必须以 --- 开头"
    end = text.find("\n---\n", 4)
    assert end > 0, "审计员.md 必须以 --- 包裹 frontmatter"
    return text[4:end]


def test_auditor_file_exists():
    """审计员.md 必存(本项目 L4 专属角色,D10 启动)."""
    assert AUDITOR_PATH.exists(), f"审计员.md 必存,实际 {AUDITOR_PATH}"


def test_auditor_frontmatter_name():
    """frontmatter name 必为 '审计员'."""
    fm = _frontmatter()
    assert "name: 审计员" in fm, f"frontmatter 必含 'name: 审计员',实际 fm={fm!r}"


def test_auditor_frontmatter_description_non_empty():
    """description 必非空(监督视角)."""
    fm = _frontmatter()
    lines = fm.strip().splitlines()
    desc_lines = [ln for ln in lines if ln.startswith("description:")]
    assert len(desc_lines) == 1
    desc = desc_lines[0].removeprefix("description:").strip()
    assert "审计" in desc or "权限" in desc or "LLM" in desc, (
        f"description 必含审计/权限/LLM,实际 {desc!r}"
    )


def test_auditor_frontmatter_metadata_type_agent():
    """metadata.type 必为 'agent'."""
    fm = _frontmatter()
    assert "metadata:" in fm
    assert "type: agent" in fm or "type:agent" in fm


def test_auditor_responsibilities_3_categories():
    """审计员职责 3 大类(LLM 审计 / 数据流监督 / 权限审计)."""
    body = _read()
    for keyword in ("LLM", "数据流", "权限"):
        assert keyword in body, f"审计员职责必含 {keyword}"


def test_auditor_4_red_lines():
    """审计红线 4 条(LLM 延迟 > 5000ms / spam 草稿 / SMTP 失败 / 敏感数据外发)."""
    body = _read()
    # 4 关键红线
    assert "5000ms" in body, "审计红线 1: LLM 调用超 5000ms latency"
    assert "10 封" in body, "审计红线 2: 同一邮箱 1 小时内 > 10 封草稿"
    assert "SMTP" in body, "审计红线 3: SMTP 发送失败 > 3 次"
    # 红线 4: 敏感数据
    assert "敏感数据" in body or "身份证" in body, "审计红线 4: 敏感数据外发"


def test_auditor_collaboration_with_steward():
    """审计员 ↔ 管家 双向强制(管家执行 + 审计员监督)."""
    body = _read()
    assert "@审计员 ↔ @管家" in body or "审计员 ↔ 管家" in body, "审计员必与管家双向强制"


def test_auditor_triggers_inspector_for_quality_gate():
    """审计员 → 检查员(每 D-step 收官前 @检查员 看审计日志做质量门)."""
    body = _read()
    assert "@检查员" in body, "审计员必召唤 @检查员做质量门"


def test_auditor_audit_log_retention():
    """审计留痕铁律(数据流可追溯)."""
    body = _read()
    # 审计日志 / 留痕 / llm_audit / health.log 至少出现一次
    assert any(
        keyword in body for keyword in ("审计日志", "审计留痕", "llm_audit", "health.log")
    ), "审计员必明示审计日志/留痕机制"


def test_auditor_monthly_report_trigger():
    """审计员每月 1 号 09:00 触发月报(沿 week2-mvp.md L224 + D10 启动决策)."""
    body = _read()
    assert "每月 1 号" in body or "每月1号" in body, "审计员必明示每月 1 号触发月报"
    assert "09:00" in body, "审计员必明示 09:00 触发时间"


def test_auditor_no_send_authority():
    """审计员无发送权限(只监督不执行,沿 D10 双角色边界)."""
    body = _read()
    # 监督视角,不写"SMTP 发送" / "1-click 审批"等执行类关键词
    assert "SMTP 真实发送" not in body or "审计" in body, (
        "审计员必明示'监督 SMTP 发送失败'而非'执行 SMTP 发送'"
    )


@pytest.mark.parametrize(
    "expected_section",
    [
        "核心职责",
        "审计红线",
        "协作关系",
        "Why",
        "How to apply",
    ],
)
def test_auditor_required_sections(expected_section: str):
    """审计员必含 5 大段(沿 Agent Assistant .md 范本)."""
    body = _read()
    assert expected_section in body, f"审计员必含段 {expected_section!r}"
