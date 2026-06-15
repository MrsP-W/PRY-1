"""D10.1 — 7 Agent 角色总览契约测试.

承接 src/my_ai_employee/agents/ 7 个 .md 文件(5 复制 + 2 专属).

测试目标(沿 D5.5.3 范本 + 角色清单同步):
    - 7 个 .md 文件全部存在
    - 5 复制(D5.5.3 软链 → 实际文件复制):教练员/检查员/调试专家/回顾员/内容编辑员
      - 沿 Agent Assistant 风格:`# 角色 System Prompt` 标题 + 色彩标识行
    - 2 专属(本项目 L4):管家/审计员
      - frontmatter 4 字段必填(name/description/metadata.type=agent)
    - Agent README.md 角色清单必与实际文件 1:1 对齐(7/7 同步)
    - 全部 type=agent 标识(2 专属 L4 owned)
"""

from __future__ import annotations

from pathlib import Path

import pytest

AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "my_employee" / "agents"
# 修正路径(沿 D5.5.3 范本)
AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "my_ai_employee" / "agents"
README_PATH = AGENTS_DIR / "README.md"

# D5.5.3 范本:5 复制 + 2 专属(7 Agent)
COPIED_ROLES = ("教练员", "检查员", "调试专家", "回顾员", "内容编辑员")
PROJECT_OWNED_ROLES = ("管家", "审计员")
ALL_ROLES = COPIED_ROLES + PROJECT_OWNED_ROLES


def _read_frontmatter(role_path: Path) -> str | None:
    """提取 .md 的 YAML frontmatter;Agent Assistant 风格无 frontmatter → None."""
    text = role_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end <= 0:
        return None
    return text[4:end]


@pytest.mark.parametrize("role_name", COPIED_ROLES)
def test_copied_roles_exist(role_name: str):
    """5 复制角色必存(D5.5.3 软链 → 实际文件复制)."""
    path = AGENTS_DIR / f"{role_name}.md"
    assert path.exists(), f"{role_name}.md 必存(D5.5.3 复制范本),实际 {path}"


@pytest.mark.parametrize("role_name", PROJECT_OWNED_ROLES)
def test_project_owned_roles_exist(role_name: str):
    """2 专属角色必存(本项目 L4 独有)."""
    path = AGENTS_DIR / f"{role_name}.md"
    assert path.exists(), f"{role_name}.md 必存(L4 专属)"


@pytest.mark.parametrize("role_name", COPIED_ROLES)
def test_copied_roles_use_agent_assistant_style(role_name: str):
    """5 复制角色必沿 Agent Assistant 风格:`# {角色} System Prompt` 标题 + 色彩标识."""
    path = AGENTS_DIR / f"{role_name}.md"
    body = path.read_text(encoding="utf-8")
    # Agent Assistant 范本:`# 角色 System Prompt` + `> **色彩标识**:` 行
    assert f"# {role_name} System Prompt" in body, (
        f"{role_name}.md 必含 '# {role_name} System Prompt' 标题(Agent Assistant 风格)"
    )
    assert "色彩标识" in body, f"{role_name}.md 必含色彩标识行"


@pytest.mark.parametrize("role_name", PROJECT_OWNED_ROLES)
def test_project_owned_roles_frontmatter_name_match_filename(role_name: str):
    """2 专属角色 frontmatter name 必与文件名 1:1 对齐."""
    path = AGENTS_DIR / f"{role_name}.md"
    fm = _read_frontmatter(path)
    assert fm is not None, f"{role_name} 必含 YAML frontmatter(L4 专属)"
    assert f"name: {role_name}" in fm, (
        f"{role_name}.md frontmatter name 必为 {role_name!r},实际 fm={fm!r}"
    )


@pytest.mark.parametrize("role_name", PROJECT_OWNED_ROLES)
def test_project_owned_roles_metadata_type_agent(role_name: str):
    """2 专属角色 metadata.type 必全为 'agent'."""
    path = AGENTS_DIR / f"{role_name}.md"
    fm = _read_frontmatter(path)
    assert fm is not None
    assert "metadata:" in fm, f"{role_name} 必含 metadata 段"
    assert "type: agent" in fm or "type:agent" in fm, (
        f"{role_name} metadata.type 必为 'agent',实际 fm={fm!r}"
    )


@pytest.mark.parametrize("role_name", PROJECT_OWNED_ROLES)
def test_project_owned_roles_description_non_empty(role_name: str):
    """2 专属角色 description 必非空(沿 D4.7.2 v1.0.6 教训)."""
    path = AGENTS_DIR / f"{role_name}.md"
    fm = _read_frontmatter(path)
    assert fm is not None
    lines = fm.strip().splitlines()
    desc_lines = [ln for ln in lines if ln.startswith("description:")]
    assert len(desc_lines) == 1, f"{role_name} description 必为单行,实际 {desc_lines}"
    desc = desc_lines[0].removeprefix("description:").strip()
    assert len(desc) >= 8, f"{role_name} description 必 >= 8 字符,实际 {desc!r}"


def test_agent_readme_lists_7_roles():
    """Agent README.md 必列 7 角色清单(沿 D5.5.3 范本)."""
    readme = README_PATH.read_text(encoding="utf-8")
    for role in ALL_ROLES:
        assert role in readme, f"Agent README 必列角色 {role}"


def test_agent_readme_marks_copied_vs_owned():
    """Agent README 必区分 5 复制 vs 2 专属(沿 D5.5.3 范本)."""
    readme = README_PATH.read_text(encoding="utf-8")
    assert "复制" in readme and "专属" in readme, "Agent README 必区分复制 vs 专属"
    for role in COPIED_ROLES:
        assert role in readme
    for role in PROJECT_OWNED_ROLES:
        assert role in readme


def test_agent_readme_role_count_matches_actual():
    """Agent README 角色数必与实际 7 个 .md 文件数 1:1 对齐(防漂移)."""
    readme = README_PATH.read_text(encoding="utf-8")
    actual_md_files = {p.stem for p in AGENTS_DIR.glob("*.md")} - {"README"}
    for stem in actual_md_files:
        assert stem in readme, f"实际有 {stem}.md,README 必列"


def test_copied_roles_have_color_marker():
    """5 复制角色必含色彩标识(沿 Agent Assistant .md 范本)."""
    # 7 常见色系:🔴🟠🟡🟢🔵🟣⚪(覆盖 Agent Assistant 全部角色)
    color_markers = ("🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "⚪")
    for role in COPIED_ROLES:
        body = (AGENTS_DIR / f"{role}.md").read_text(encoding="utf-8")
        assert any(emoji in body for emoji in color_markers), (
            f"{role}.md 必含色彩标识(沿 Agent Assistant 范本)"
        )


def test_no_legacy_symlinks_in_agents_dir():
    """D5.5.3 软链 → 实际文件复制(防 uv build FileNotFoundError)."""
    for path in AGENTS_DIR.glob("*.md"):
        assert not path.is_symlink(), f"{path.name} 不应是软链(D5.5.3 P0 修复:软链 → 实际文件复制)"
