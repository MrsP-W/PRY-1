"""D10.1 — @管家 Agent 角色契约测试.

承接 src/my_ai_employee/agents/管家.md(本项目 L4 专属角色).

测试目标(沿 D5.5.3 范本 + D6 4-字段 frontmatter 严判):
    - 角色 frontmatter 4 字段必填(name/description/metadata.type/metadata 内容)
    - 角色定位:L4 Agent 层专属(管家 = 我的AI员工独有)
    - 职责清单:邮件处理 / 日程管理 / 账本 / 笔记(后续 D6+ 接入)
    - 协作关系:@管家 ↔ @审计员(双向强制)
    - 铁律:不抢控制权 / 不联网外传 / 不收费 SaaS

不依赖 LLM(纯 prompt 契约 + 文件 frontmatter 解析).
"""

from __future__ import annotations

from pathlib import Path

import pytest

AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "my_ai_employee" / "agents"
STEWARD_PATH = AGENTS_DIR / "管家.md"


def _read() -> str:
    return STEWARD_PATH.read_text(encoding="utf-8")


def _frontmatter() -> str:
    """提取管家.md 的 YAML frontmatter(以 --- 包裹)."""
    text = _read()
    assert text.startswith("---\n"), "管家.md 必须以 --- 开头(YAML frontmatter)"
    end = text.find("\n---\n", 4)
    assert end > 0, "管家.md 必须以 --- 包裹 frontmatter"
    return text[4:end]


def test_steward_file_exists():
    """管家.md 必存(本项目 L4 专属角色,新建于 D5 周)."""
    assert STEWARD_PATH.exists(), f"管家.md 必存,实际路径 {STEWARD_PATH}"


def test_steward_frontmatter_name():
    """frontmatter name 必为 '管家'(L4 角色契约 1)."""
    fm = _frontmatter()
    assert "name: 管家" in fm, f"frontmatter 必含 'name: 管家',实际 fm={fm!r}"


def test_steward_frontmatter_description_non_empty():
    """frontmatter description 必非空(单行描述)."""
    fm = _frontmatter()
    lines = fm.strip().splitlines()
    desc_lines = [ln for ln in lines if ln.startswith("description:")]
    assert len(desc_lines) == 1, f"description 必为单行,实际 {desc_lines}"
    desc = desc_lines[0].removeprefix("description:").strip()
    assert len(desc) > 10, f"description 必 > 10 字符,实际 {desc!r}"


def test_steward_frontmatter_metadata_type_agent():
    """metadata.type 必为 'agent'(L4 角色类型契约)."""
    fm = _frontmatter()
    assert "metadata:" in fm, "frontmatter 必含 metadata 段"
    assert "type: agent" in fm or "type:agent" in fm, f"metadata.type 必为 'agent',实际 fm={fm!r}"


def test_steward_responsibilities_listed():
    """管家职责 4 大类必在正文列出(邮件/日程/账本/笔记)."""
    body = _read()
    for keyword in ("邮件处理", "日程管理", "账本", "笔记"):
        assert keyword in body, f"管家职责必列 {keyword},正文未含"


def test_steward_collaboration_with_auditor():
    """管家 ↔ 审计员 双向强制(沿 D10 决策 1)."""
    body = _read()
    assert "@管家 ↔ @审计员" in body or "管家 ↔ 审计员" in body, (
        "管家必与审计员双向强制(管家执行 + 审计员监督)"
    )


def test_steward_three_iron_rules():
    """管家铁律 3 条(不抢控制权 / 不联网外传 / 不收费 SaaS)."""
    body = _read()
    for rule in ("不抢控制权", "不联网外传", "不收费 SaaS"):
        assert rule in body, f"管家铁律必含 {rule}"


def test_steward_24h_on_duty():
    """管家 24h 在岗(全天候数字员工视角)."""
    body = _read()
    assert "24h 在岗" in body or "24小时在岗" in body, "管家必明示 24h 在岗"


def test_steward_no_duplicate_with_auditor_prompts():
    """管家与审计员职责必不重叠(双角色边界清晰)."""
    auditor = (AGENTS_DIR / "审计员.md").read_text(encoding="utf-8")
    steward_body = _read()
    # 管家执行 → 审计员监督,职责不重叠
    assert "执行" in steward_body and "监督" in auditor, "管家 = 执行,审计员 = 监督(双角色边界)"


@pytest.mark.parametrize(
    "expected_section",
    [
        "核心职责",
        "协作关系",
        "Why",
        "How to apply",
    ],
)
def test_steward_required_sections(expected_section: str):
    """管家必含 4 大段(沿 Agent Assistant .md 范本)."""
    body = _read()
    assert expected_section in body, f"管家必含段 {expected_section!r}"


def test_steward_markdown_paragraph_breaks():
    """管家.md 段间必有空行(沿 D6 docs Lint 范本)."""
    body = _read()
    assert "## 核心职责\n\n" in body or "## 核心职责 \n\n" in body, (
        "## 核心职责 标题后必空一行(MD022)"
    )
